#!/usr/bin/env python3
"""
OpenClaw Watchdog - Test Suite

Test coverage:
1. Config module tests
2. Core logic tests
3. Integration tests
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add project path
PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

from config import (
    get_default_config,
    load_config,
    save_config,
    merge_config,
    validate_config,
    get_platform,
    get_default_log_path,
    get_ps_command,
    get_service_manager,
    CONFIG_DIR,
    CONFIG_FILE
)
from watchdog import OpenClawWatchdog


class TestConfigModule(unittest.TestCase):
    """Config module tests"""

    def test_get_default_config(self):
        """Test get default config"""
        config = get_default_config()

        self.assertIsInstance(config, dict)
        self.assertEqual(config['check_interval'], 300)
        self.assertEqual(config['health_check']['timeout'], 10)
        self.assertEqual(config['resource_silence']['cpu_threshold'], 5.0)
        self.assertEqual(config['io_silence']['silence_threshold'], 180)

    def test_save_and_load_config(self):
        """Test save and load config"""
        # Use temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Save config
            test_config = get_default_config()
            test_config['check_interval'] = 600
            test_config['custom_field'] = 'test_value'

            save_config(test_config, temp_path)
            self.assertTrue(temp_path.exists())

            # Load config
            loaded = load_config(temp_path)

            # Verify
            self.assertEqual(loaded['check_interval'], 600)
            self.assertEqual(loaded['custom_field'], 'test_value')

        finally:
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()

    def test_merge_config(self):
        """Test config merge"""
        default = {
            'a': 1,
            'b': {'x': 10, 'y': 20},
            'c': [1, 2, 3]
        }

        loaded = {
            'a': 100,
            'b': {'x': 99},
            'd': 'new'
        }

        result = merge_config(default, loaded)

        # Top-level override
        self.assertEqual(result['a'], 100)
        # Nested merge
        self.assertEqual(result['b']['x'], 99)
        self.assertEqual(result['b']['y'], 20)
        # Keep default
        self.assertEqual(result['c'], [1, 2, 3])
        # New field
        self.assertEqual(result['d'], 'new')

    def test_validate_config_valid(self):
        """Test validate config - valid"""
        config = get_default_config()
        is_valid, errors = validate_config(config)

        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_validate_config_invalid(self):
        """Test validate config - invalid"""
        config = get_default_config()
        config['check_interval'] = 30  # Less than 60
        config['health_check']['timeout'] = 0  # Less than 1
        config['resource_silence']['cpu_threshold'] = -1  # Less than 0

        is_valid, errors = validate_config(config)

        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)

    def test_load_nonexistent_config(self):
        """Test load non-existent config"""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / 'nonexistent.json'

            # Config doesn't exist, should return default config
            config = load_config(temp_path)

            self.assertIsInstance(config, dict)


class TestWatchdogCore(unittest.TestCase):
    """Watchdog core logic tests"""

    def setUp(self):
        """Test setup"""
        # Use temporary config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            self.temp_config = Path(f.name)
            json.dump(get_default_config(), f)

        self.watchdog = OpenClawWatchdog(self.temp_config)

    def tearDown(self):
        """Test cleanup"""
        if self.temp_config.exists():
            self.temp_config.unlink()

    def test_init(self):
        """Test initialization"""
        self.assertIsNotNone(self.watchdog.config)
        self.assertIsNotNone(self.watchdog.logger)

    def test_run_command_success(self):
        """Test run command - success"""
        success, output, returncode = self.watchdog.run_command('echo "test"')

        self.assertTrue(success)
        self.assertEqual(output, 'test')
        self.assertEqual(returncode, 0)

    def test_run_command_failure(self):
        """Test run command - failure"""
        success, output, returncode = self.watchdog.run_command('exit 1')

        self.assertFalse(success)
        self.assertNotEqual(returncode, 0)

    def test_run_command_timeout(self):
        """Test run command - timeout"""
        success, output, returncode = self.watchdog.run_command(
            'sleep 10',
            timeout=1
        )

        self.assertFalse(success)
        self.assertIn('timeout', output)

    @patch('watchdog.subprocess.run')
    def test_check_health_success(self, mock_run):
        """Test health check - success"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = 'All systems operational'
        mock_result.stderr = ''
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_health()

        self.assertTrue(success)

    @patch('watchdog.subprocess.run')
    def test_check_health_timeout(self, mock_run):
        """Test health check - timeout"""
        mock_run.side_effect = TimeoutError()

        success, msg = self.watchdog.check_health()

        self.assertFalse(success)

    @patch('watchdog.subprocess.run')
    def test_check_business_silence_pass(self, mock_run):
        """Test business silence check - pass"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'active_sessions': 0,
            'running_tools': 0
        })
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_business_silence()

        self.assertTrue(success)
        # Check if message contains session and tool count
        self.assertIn('0', msg)

    @patch('watchdog.subprocess.run')
    def test_check_business_silence_has_session(self, mock_run):
        """Test business silence check - has active session"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'active_sessions': 2,
            'running_tools': 0
        })
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_business_silence()

        self.assertFalse(success)
        self.assertIn('Active sessions', msg)

    @patch('watchdog.subprocess.run')
    def test_check_business_silence_has_tool(self, mock_run):
        """Test business silence check - has running tool"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'active_sessions': 0,
            'running_tools': 1
        })
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_business_silence()

        self.assertFalse(success)
        self.assertIn('Running tools', msg)

    def test_check_io_silence_pass(self):
        """Test IO silence check - pass"""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_log = Path(f.name)

        try:
            # Set file modification time to 5 minutes ago
            import time
            old_mtime = time.time() - 300
            os.utime(temp_log, (old_mtime, old_mtime))

            self.watchdog.config['io_silence']['log_path'] = str(temp_log)
            self.watchdog.config['io_silence']['silence_threshold'] = 180

            success, msg = self.watchdog.check_io_silence()

            self.assertTrue(success)

        finally:
            temp_log.unlink()

    def test_check_io_silence_fail(self):
        """Test IO silence check - fail"""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_log = Path(f.name)

        try:
            # File was just updated
            self.watchdog.config['io_silence']['log_path'] = str(temp_log)
            self.watchdog.config['io_silence']['silence_threshold'] = 180

            success, msg = self.watchdog.check_io_silence()

            self.assertFalse(success)

        finally:
            temp_log.unlink()

    @patch('watchdog.subprocess.run')
    def test_check_resource_silence_pass(self, mock_run):
        """Test resource silence check - pass (low CPU)"""
        # Simulate low CPU usage
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = '  3.2  /usr/bin/openclaw'
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_resource_silence()

        self.assertTrue(success)

    @patch('watchdog.subprocess.run')
    def test_check_resource_silence_fail(self, mock_run):
        """Test resource silence check - fail (high CPU)"""
        # Simulate high CPU usage
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ' 80.5  /usr/bin/openclaw'
        mock_run.return_value = mock_result

        success, msg = self.watchdog.check_resource_silence()

        self.assertFalse(success)

    def test_perform_restart_cooldown(self):
        """Test restart cooldown"""
        import time as time_module
        # Set last restart to 10 seconds ago (cooldown is 300)
        cooldown = self.watchdog.config['restart']['cooldown']
        self.watchdog.last_restart_time = time_module.time() - (cooldown - 10)

        success = self.watchdog.perform_restart()

        self.assertFalse(success)

    @patch('watchdog.OpenClawWatchdog.run_command')
    def test_perform_restart_success(self, mock_run):
        """Test restart success"""
        mock_run.return_value = (True, 'Restarted', 0)
        self.watchdog.last_restart_time = 0

        success = self.watchdog.perform_restart()

        self.assertTrue(success)
        self.assertGreater(self.watchdog.restart_count, 0)

    def test_run_check_all_pass(self):
        """Test complete check - all passed"""
        # Mock all checks pass
        with patch.object(self.watchdog, 'check_health', return_value=(True, 'OK')):
            with patch.object(self.watchdog, 'check_business_silence', return_value=(True, 'OK')):
                with patch.object(self.watchdog, 'check_io_silence', return_value=(True, 'OK')):
                    with patch.object(self.watchdog, 'check_resource_silence', return_value=(True, 'OK')):
                        can_restart, msg = self.watchdog.run_check()

                        # Business, IO, resource all passed, can restart
                        self.assertTrue(can_restart)
                        self.assertIn('WILL RESTART', msg)

    def test_run_check_not_pass(self):
        """Test complete check - not passed"""
        # Mock IO silence check not passed
        with patch.object(self.watchdog, 'check_health', return_value=(True, 'OK')):
            with patch.object(self.watchdog, 'check_business_silence', return_value=(True, 'OK')):
                with patch.object(self.watchdog, 'check_io_silence', return_value=(False, 'IO active')):
                    with patch.object(self.watchdog, 'check_resource_silence', return_value=(True, 'OK')):
                        can_restart, msg = self.watchdog.run_check()

                        # IO not passed, don't restart
                        self.assertFalse(can_restart)


class TestIntegration(unittest.TestCase):
    """Integration tests"""

    def test_config_file_creation(self):
        """Test config file auto-creation"""
        # Ensure directory exists
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load config (will create default config)
        config = load_config()

        self.assertIsInstance(config, dict)
        self.assertTrue(CONFIG_FILE.exists())


class TestCrossPlatform(unittest.TestCase):
    """Cross-platform tests"""

    def test_get_platform(self):
        """Test platform detection"""
        platform = get_platform()
        # Should be darwin or linux
        self.assertIn(platform, ["darwin", "linux"])

    def test_get_default_log_path(self):
        """Test get default log path"""
        platform = get_platform()
        log_path = get_default_log_path()

        self.assertIsInstance(log_path, str)
        self.assertTrue(len(log_path) > 0)

        if platform == "darwin":
            self.assertIn("Library/Logs", log_path)
        else:
            self.assertIn(".config", log_path)

    def test_get_ps_command(self):
        """Test get ps command"""
        platform = get_platform()
        ps_cmd = get_ps_command()

        self.assertIsInstance(ps_cmd, str)
        self.assertIn("{process}", ps_cmd)

        if platform == "darwin":
            self.assertIn("ps -ax", ps_cmd)
        else:
            self.assertIn("ps -eo", ps_cmd)

    def test_get_service_manager(self):
        """Test get service manager"""
        service_manager = get_service_manager()
        platform = get_platform()

        self.assertIsInstance(service_manager, str)

        if platform == "darwin":
            self.assertEqual(service_manager, "launchd")
        else:
            self.assertIn(service_manager, ["systemd", "cron"])

    def test_default_config_contains_platform(self):
        """Test default config contains platform info"""
        config = get_default_config()

        self.assertIn("platform", config)
        self.assertEqual(config["platform"], get_platform())

    def test_resource_silence_has_ps_command(self):
        """Test resource silence has ps command"""
        config = get_default_config()

        self.assertIn("resource_silence", config)
        self.assertIn("ps_command", config["resource_silence"])

    @patch('config.platform.system')
    def test_darwin_log_path(self, mock_system):
        """Test macOS log path"""
        mock_system.return_value = "Darwin"

        # Re-import to get new platform functions
        import importlib
        import config
        importlib.reload(config)

        log_path = config.get_default_log_path()
        self.assertIn("Library/Logs", log_path)

    @patch('config.platform.system')
    def test_linux_log_path(self, mock_system):
        """Test Linux log path"""
        mock_system.return_value = "Linux"

        # Re-import to get new platform functions
        import importlib
        import config
        importlib.reload(config)

        log_path = config.get_default_log_path()
        self.assertIn(".config", log_path)


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestConfigModule))
    suite.addTests(loader.loadTestsFromTestCase(TestWatchdogCore))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestCrossPlatform))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return result
    return result.wasSuccessful()


if __name__ == "__main__":
    print("=" * 60)
    print("OpenClaw Watchdog - Test Suite")
    print("=" * 60)

    success = run_tests()

    print("\n" + "=" * 60)
    if success:
        print("All tests passed!")
    else:
        print("Some tests failed")
    print("=" * 60)

    sys.exit(0 if success else 1)
