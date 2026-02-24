#!/usr/bin/env python3
"""
OpenClaw Watchdog - Core Monitoring Script

Implements "Triple-Silence Logic":
1. Health Check - Call openclaw doctor to check if process is alive
2. Business Silence - Check for active sessions and running tools
3. IO Silence - Check if log file has been updated within threshold time
4. Resource Silence - Check if process CPU usage is below threshold

Usage:
    python watchdog.py [--config CONFIG_PATH] [--once]
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Import config module
from config import load_config, validate_config, CONFIG_FILE


class OpenClawWatchdog:
    """OpenClaw Watchdog main class"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize watchdog

        Args:
            config_path: Config file path
        """
        self.config = load_config(config_path)
        self.logger = self._setup_logging()
        self.last_restart_time = 0  # Last restart time
        self.restart_count = 0  # Restart counter

        # Validate config
        is_valid, errors = validate_config(self.config)
        if not is_valid:
            self.logger.warning(f"Config has issues: {', '.join(errors)}")

    def _setup_logging(self) -> logging.Logger:
        """
        Setup logging

        Returns:
            logging.Logger: Configured logger
        """
        log_config = self.config.get("logging", {})

        # Create logger
        logger = logging.getLogger("OpenClawWatchdog")
        logger.setLevel(getattr(logging, log_config.get("log_level", "INFO")))

        # Avoid duplicate handlers
        if logger.handlers:
            return logger

        # File handler
        log_file = log_config.get("log_file", "/tmp/claw_watchdog.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Format
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def run_command(
        self,
        cmd: str,
        timeout: int = 30,
        shell: bool = True
    ) -> Tuple[bool, str, int]:
        """
        Run system command

        Args:
            cmd: Command string
            timeout: Timeout in seconds
            shell: Whether to use shell execution

        Returns:
            Tuple[bool, str, int]: (success, output, return_code)
        """
        try:
            result = subprocess.run(
                cmd,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else result.stderr.strip()
            return success, output, result.returncode
        except subprocess.TimeoutExpired:
            return False, f"Command timeout ({timeout}s)", -1
        except Exception as e:
            return False, f"Command execution failed: {str(e)}", -1

    def check_health(self) -> Tuple[bool, str]:
        """
        Health Check - Call openclaw doctor

        Returns:
            Tuple[bool, str]: (passed, details)
        """
        health_config = self.config.get("health_check", {})

        if not health_config.get("enabled", True):
            return True, "Health check disabled"

        cmd = health_config.get("command", "openclaw doctor")
        timeout = health_config.get("timeout", 10)

        self.logger.info(f"Running health check: {cmd} (timeout: {timeout}s)")

        success, output, returncode = self.run_command(cmd, timeout=timeout)

        if success:
            self.logger.info("Health check passed - OpenClaw process is healthy")
            return True, output
        else:
            self.logger.warning(f"Health check failed: {output}")
            return False, output

    def check_business_silence(self) -> Tuple[bool, str]:
        """
        Business Silence Check - Check active sessions and running tools

        Returns:
            Tuple[bool, str]: (passed, details)
        """
        business_config = self.config.get("business_silence", {})

        if not business_config.get("enabled", True):
            return True, "Business silence check disabled"

        cmd = business_config.get("status_command", "openclaw status --json")
        timeout = business_config.get("status_timeout", 15)

        self.logger.info(f"Running business silence check: {cmd}")

        success, output, returncode = self.run_command(cmd, timeout=timeout)

        if not success:
            # Command failed, process may be dead
            self.logger.warning(f"Business status query failed: {output}")
            if business_config.get("fail_on_error", True):
                return False, f"Cannot get business status: {output}"
            return True, "Command failed, skipping check"

        try:
            status = json.loads(output)
        except json.JSONDecodeError:
            # Try to extract JSON from output (in case there's extra text)
            import re
            json_match = re.search(r'\{[\s\S]*\}', output)
            if json_match:
                try:
                    status = json.loads(json_match.group())
                except json.JSONDecodeError:
                    self.logger.warning(f"JSON parse failed: {output[:200]}")
                    return False, "JSON parse failed"
            else:
                self.logger.warning(f"JSON parse failed: {output[:200]}")
                return False, "JSON parse failed"

        # Check active sessions
        # Try multiple possible field names for sessions
        active_sessions = status.get("active_sessions")
        if active_sessions is None:
            # Try sessions.count or agents.totalSessions
            sessions_data = status.get("sessions", {})
            active_sessions = sessions_data.get("count", -1)
        if active_sessions is None or active_sessions == -1:
            agents_data = status.get("agents", {})
            active_sessions = agents_data.get("totalSessions", -1)

        require_zero_sessions = business_config.get("require_zero_sessions", True)

        if require_zero_sessions and active_sessions > 0:
            msg = f"Active sessions found: {active_sessions}"
            self.logger.info(msg)
            return False, msg

        # Check running tools
        # Try multiple possible field names
        running_tools = status.get("running_tools")
        if running_tools is None:
            running_tools = status.get("active_tools", -1)

        require_zero_tools = business_config.get("require_zero_tools", True)

        if require_zero_tools and running_tools > 0:
            msg = f"Running tools found: {running_tools}"
            self.logger.info(msg)
            return False, msg

        self.logger.info(f"Business silence check passed (sessions: {active_sessions}, tools: {running_tools})")
        return True, f"Active sessions: {active_sessions}, running tools: {running_tools}"

    def check_io_silence(self) -> Tuple[bool, str]:
        """
        IO Silence Check - Check log file modification time

        Returns:
            Tuple[bool, str]: (passed, details)
        """
        io_config = self.config.get("io_silence", {})

        if not io_config.get("enabled", True):
            return True, "IO silence check disabled"

        log_path = io_config.get("log_path")
        if not log_path:
            log_path = str(Path.home() / "Library/Logs/OpenClaw/diagnostics.jsonl")

        threshold = io_config.get("silence_threshold", 180)
        check_exists = io_config.get("check_file_exists", True)

        self.logger.info(f"Running IO silence check: {log_path}")

        # Check if file exists
        if check_exists and not os.path.exists(log_path):
            msg = f"Log file does not exist: {log_path}"
            self.logger.warning(msg)
            self.logger.warning("IO silence check skipped - log file not found")
            self.logger.warning("To enable IO monitoring, ensure diagnostics is enabled in OpenClaw config")
            if io_config.get("fail_on_missing", False):
                return False, msg
            return True, f"Log file not found ({log_path}), skipping check"

        # Get file modification time
        try:
            mtime = os.path.getmtime(log_path)
            current_time = time.time()
            elapsed = current_time - mtime

            if elapsed > threshold:
                msg = f"Log file silent for {elapsed:.0f}s (threshold: {threshold}s)"
                self.logger.info(msg)
                return True, msg
            else:
                msg = f"Log file updated {elapsed:.0f}s ago"
                self.logger.info(msg)
                return False, msg

        except OSError as e:
            self.logger.warning(f"Cannot read file info: {e}")
            return True, f"File read failed, skipping check: {e}"

    def check_resource_silence(self) -> Tuple[bool, str]:
        """
        Resource Silence Check - Check process CPU usage

        Returns:
            Tuple[bool, str]: (passed, details)
        """
        resource_config = self.config.get("resource_silence", {})

        if not resource_config.get("enabled", True):
            return True, "Resource silence check disabled"

        process_name = resource_config.get("process_name", "openclaw")
        cpu_threshold = resource_config.get("cpu_threshold", 5.0)
        check_interval = resource_config.get("check_interval", 3)
        check_delay = resource_config.get("check_delay", 1)
        ps_command_template = resource_config.get(
            "ps_command",
            'ps -ax -o %cpu,comm | grep "{process}" | grep -v grep | head -1'
        )

        self.logger.info(
            f"Running resource silence check: process {process_name}, "
            f"CPU threshold: {cpu_threshold}%, samples: {check_interval}"
        )

        cpu_samples = []

        for i in range(check_interval):
            # Use ps command to get CPU usage
            cmd = ps_command_template.replace("{process}", process_name)
            success, output, _ = self.run_command(cmd, timeout=5)

            if success and output:
                try:
                    # Parse CPU usage
                    parts = output.strip().split()
                    if parts:
                        cpu = float(parts[0])
                        cpu_samples.append(cpu)
                        self.logger.debug(f"Sample {i+1}: CPU = {cpu}%")
                except (ValueError, IndexError):
                    pass

            if i < check_interval - 1:
                time.sleep(check_delay)

        if not cpu_samples:
            msg = f"Process not found: {process_name}"
            self.logger.warning(msg)
            return False, msg

        # Calculate average CPU
        avg_cpu = sum(cpu_samples) / len(cpu_samples)

        if avg_cpu < cpu_threshold:
            msg = f"CPU usage {avg_cpu:.1f}% < {cpu_threshold}%"
            self.logger.info(msg)
            return True, msg
        else:
            msg = f"CPU usage {avg_cpu:.1f}% >= {cpu_threshold}%"
            self.logger.info(msg)
            return False, msg

    def perform_restart(self) -> bool:
        """
        Perform restart operation

        Returns:
            bool: Whether restart succeeded
        """
        restart_config = self.config.get("restart", {})
        advanced_config = self.config.get("advanced", {})

        # Check cooldown
        cooldown = restart_config.get("cooldown", 300)
        current_time = time.time()

        if current_time - self.last_restart_time < cooldown:
            self.logger.info(
                f"Restart in cooldown (need to wait "
                f"{cooldown - (current_time - self.last_restart_time):.0f} more seconds)"
            )
            return False

        # Execute pre-restart hook
        pre_hook = advanced_config.get("pre_restart_hook")
        if pre_hook and os.path.exists(pre_hook):
            self.logger.info(f"Executing pre-restart hook: {pre_hook}")
            self.run_command(pre_hook, timeout=30)

        # Execute restart
        cmd = restart_config.get("command", "openclaw gateway restart")
        max_retries = restart_config.get("max_retries", 3)
        retry_delay = restart_config.get("retry_delay", 10)

        self.logger.info(f"Starting restart: {cmd}")

        for attempt in range(max_retries):
            success, output, returncode = self.run_command(cmd, timeout=60)

            if success:
                self.logger.info(f"Restart command succeeded (attempt {attempt + 1}/{max_retries})")
                self.last_restart_time = current_time
                self.restart_count += 1
                break
            else:
                self.logger.warning(
                    f"Restart failed (attempt {attempt + 1}/{max_retries}): {output}"
                )
                if attempt < max_retries - 1:
                    self.logger.info(f"Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)

        # Execute post-restart hook
        post_hook = advanced_config.get("post_restart_hook")
        if post_hook and os.path.exists(post_hook):
            self.logger.info(f"Executing post-restart hook: {post_hook}")
            self.run_command(post_hook, timeout=30)

        return success

    def run_check(self) -> Tuple[bool, str]:
        """
        Run complete health check

        Returns:
            Tuple[bool, str]: (can_restart, check_result_details)
        """
        self.logger.info("=" * 50)
        self.logger.info(f"Starting health check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 50)

        advanced_config = self.config.get("advanced", {})
        require_all = advanced_config.get("require_all_checks", True)

        results = {}

        # 1. Health Check
        health_pass, health_msg = self.check_health()
        results["health"] = (health_pass, health_msg)

        # If health check failed, decide whether to restart based on config
        if not health_pass:
            fail_action = self.config.get("health_check", {}).get("fail_action", "restart")
            if fail_action == "restart":
                self.logger.warning("Health check failed, triggering restart")
                return True, "Health check failed"

        # 2. Business Silence Check
        business_pass, business_msg = self.check_business_silence()
        results["business"] = (business_pass, business_msg)

        # 3. IO Silence Check
        io_pass, io_msg = self.check_io_silence()
        results["io"] = (io_pass, io_msg)

        # 4. Resource Silence Check
        resource_pass, resource_msg = self.check_resource_silence()
        results["resource"] = (resource_pass, resource_msg)

        # Comprehensive judgment
        all_passed = health_pass and business_pass and io_pass and resource_pass
        any_passed = health_pass or business_pass or io_pass or resource_pass

        # Decide whether to restart based on config
        if require_all:
            can_restart = all_passed
        else:
            # As long as one passes (except health check)
            can_restart = business_pass and io_pass and resource_pass

        # Generate result details
        details = []
        details.append(f"Health check: {'PASS' if health_pass else 'FAIL'} - {health_msg}")
        details.append(f"Business silence: {'PASS' if business_pass else 'FAIL'} - {business_msg}")
        details.append(f"IO silence: {'PASS' if io_pass else 'FAIL'} - {io_msg}")
        details.append(f"Resource silence: {'PASS' if resource_pass else 'FAIL'} - {resource_msg}")

        # Determine restart reason if applicable
        if can_restart:
            reasons = []
            if not health_pass:
                reasons.append("health_check_failed")
            if business_pass:
                reasons.append("business_silent")
            if io_pass:
                reasons.append("io_silent")
            if resource_pass:
                reasons.append("resource_silent")
            details.append(f"Overall: WILL RESTART (reasons: {', '.join(reasons)})")
        else:
            # Find which checks failed
            failed = []
            if not health_pass:
                failed.append("health")
            if not business_pass:
                failed.append("business")
            if not io_pass:
                failed.append("io")
            if not resource_pass:
                failed.append("resource")
            details.append(f"Overall: WILL NOT RESTART (blocked by: {', '.join(failed)})")

        result_str = "\n".join(details)
        self.logger.info(f"\n{result_str}")

        return can_restart, result_str

    def run(self, once: bool = False) -> None:
        """
        Run watchdog

        Args:
            once: Whether to run only once
        """
        check_interval = self.config.get("check_interval", 300)

        self.logger.info(f"OpenClaw Watchdog started")
        self.logger.info(f"Check interval: {check_interval} seconds")
        self.logger.info(f"Config path: {CONFIG_FILE}")

        try:
            while True:
                can_restart, details = self.run_check()

                restart_executed = False
                if can_restart:
                    if self.perform_restart():
                        self.logger.info("Restart executed")
                        restart_executed = True
                    else:
                        self.logger.info("Restart not executed (possibly in cooldown)")
                else:
                    self.logger.info("Conditions not met, will not restart")

                # After restart, wait for a grace period to let IO stabilize
                if restart_executed:
                    restart_config = self.config.get("restart", {})
                    grace_wait = restart_config.get("graceful_wait", 10)
                    self.logger.info(f"Waiting {grace_wait} seconds for IO to stabilize...")
                    time.sleep(grace_wait)

                if once:
                    self.logger.info("Single check completed, exiting")
                    break

                self.logger.info(f"Waiting {check_interval} seconds for next check...")
                time.sleep(check_interval)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, watchdog exiting")
        except Exception as e:
            self.logger.error(f"Watchdog exited with exception: {e}")
            raise


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="OpenClaw Watchdog - Automated Monitoring and Self-Healing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python watchdog.py                 # Start watchdog
    python watchdog.py --once          # Single check
    python watchdog.py --config /path/to/config.json  # Specify config file
        """
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Config file path (default: ~/.openclaw/watchdog/config.json)"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run only once, do not loop"
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate config file and exit"
    )

    args = parser.parse_args()

    # Validate mode
    if args.validate:
        config = load_config(args.config)
        is_valid, errors = validate_config(config)
        if is_valid:
            print("Config validation passed")
            print(json.dumps(config, indent=2, ensure_ascii=False))
        else:
            print("Config validation failed:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
        sys.exit(0)

    # Start watchdog
    watchdog = OpenClawWatchdog(args.config)
    watchdog.run(once=args.once)


if __name__ == "__main__":
    main()
