#!/usr/bin/env python3
"""
OpenClaw Watchdog - Configuration Module
Defines all customizable parameters and behaviors

Supported platforms: macOS, Linux
"""

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# ========== Platform Detection ==========
def get_platform() -> str:
    """
    Get current operating system platform

    Returns:
        str: "darwin" (macOS) or "linux"
    """
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "linux":
        return "linux"
    else:
        return system


# Configuration directory
CONFIG_DIR = Path.home() / ".openclaw" / "watchdog"
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_default_log_path() -> str:
    """
    Get platform-specific default log file path

    Returns:
        str: Default log file path
    """
    system = get_platform()

    if system == "darwin":
        # macOS: ~/Library/Logs/OpenClaw/diagnostics.jsonl
        return str(Path.home() / "Library/Logs/OpenClaw/diagnostics.jsonl")
    elif system == "linux":
        # Linux: ~/.config/openclaw/logs/diagnostics.jsonl
        return str(Path.home() / ".config" / "openclaw" / "logs" / "diagnostics.jsonl")
    else:
        return str(Path.home() / ".openclaw" / "logs" / "diagnostics.jsonl")


def get_ps_command() -> str:
    """
    Get platform-specific ps command

    Returns:
        str: ps command
    """
    system = get_platform()

    if system == "darwin":
        # macOS ps command
        return 'ps -ax -o %cpu,comm | grep "{process}" | grep -v grep | head -1'
    else:
        # Linux ps command (supports procps)
        return 'ps -eo %cpu,comm --no-headers | grep "{process}" | head -1'


def get_service_manager() -> str:
    """
    Get system service manager type

    Returns:
        str: "launchd", "systemd", or "cron"
    """
    system = get_platform()

    if system == "darwin":
        # Prefer launchd
        return "launchd"
    else:
        # Linux: prefer systemd
        try:
            result = subprocess.run(
                ["which", "systemd"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return "systemd"
        except Exception:
            pass
        return "cron"


def get_systemd_service_template() -> Dict[str, Any]:
    """
    Get systemd service configuration template

    Returns:
        Dict[str, Any]: systemd configuration dictionary
    """
    return {
        "Unit": {
            "Description": "OpenClaw Watchdog Service",
            "After": "network.target"
        },
        "Service": {
            "Type": "simple",
            "ExecStart": "/usr/bin/python3 __SCRIPT_PATH__ --once",
            "WorkingDirectory": "__WORK_DIR__",
            "Restart": "always",
            "RestartSec": 10,
            "User": os.environ.get("USER", "root")
        },
        "Install": {
            "WantedBy": "multi-user.target"
        }
    }


def get_cron_template() -> str:
    """
    Get cron configuration template

    Returns:
        str: crontab entry
    """
    return "*/5 * * * * /usr/bin/python3 __SCRIPT_PATH__ --once >> /tmp/claw_watchdog.log 2>&1"


def get_default_config() -> Dict[str, Any]:
    """
    Get default configuration parameters

    Returns:
        Dict[str, Any]: Default configuration dictionary
    """
    system = get_platform()

    return {
        # ========== Platform Info (Read-only) ==========
        "platform": system,

        # ========== Monitoring Interval ==========
        "check_interval": 300,  # Check interval in seconds (default 5 minutes)

        # ========== Health Check Config ==========
        "health_check": {
            "enabled": True,  # Enable health check
            "command": "openclaw doctor",  # Health check command
            "timeout": 10,  # Timeout in seconds
            "fail_action": "restart"  # Action on timeout: "restart" or "ignore"
        },

        # ========== Business Silence Config ==========
        "business_silence": {
            "enabled": True,  # Enable business silence check
            "status_command": "openclaw status --json",  # Status query command
            "require_zero_sessions": True,  # Require active_sessions == 0
            "require_zero_tools": True,  # Require running_tools == 0
            "status_timeout": 15  # Status query timeout in seconds
        },

        # ========== IO Silence Config ==========
        "io_silence": {
            "enabled": True,  # Enable IO silence check
            "log_path": get_default_log_path(),  # Cross-platform log path
            "silence_threshold": 180,  # Silence threshold in seconds (default 3 minutes)
            "check_file_exists": True  # Check if file exists
        },

        # ========== Resource Silence Config ==========
        "resource_silence": {
            "enabled": True,  # Enable resource silence check
            "process_name": "openclaw",  # Process name
            "cpu_threshold": 5.0,  # CPU threshold in %
            "check_interval": 3,  # Number of checks
            "check_delay": 1,  # Delay between checks in seconds
            "ps_command": get_ps_command()  # Platform-specific ps command template
        },

        # ========== Restart Config ==========
        "restart": {
            "command": "openclaw gateway restart",  # Restart command
            "max_retries": 3,  # Maximum retry attempts
            "retry_delay": 10,  # Retry delay in seconds
            "cooldown": 300,  # Cooldown period in seconds (prevent frequent restarts)
            "graceful_wait": 10  # Graceful restart wait time in seconds
        },

        # ========== Logging Config ==========
        "logging": {
            "log_file": "/tmp/claw_watchdog.log",  # Log file path
            "log_level": "INFO",  # Log level: DEBUG | INFO | WARNING | ERROR
            "max_log_size": 10 * 1024 * 1024,  # Max log size in bytes (default 10MB)
            "log_rotation": 5  # Number of log rotations
        },

        # ========== Advanced Config ==========
        "advanced": {
            "require_all_checks": True,  # Require all checks to pass before restart
            "skip_on_error": True,  # Skip check on error and continue
            "pre_restart_hook": None,  # Script to run before restart (optional)
            "post_restart_hook": None,  # Script to run after restart (optional)
        }
    }


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration file

    Args:
        config_path: Config file path, defaults to CONFIG_FILE

    Returns:
        Dict[str, Any]: Configuration dictionary
    """
    path = config_path or CONFIG_FILE

    if not path.exists():
        # Config file doesn't exist, create default config
        config = get_default_config()
        save_config(config, path)
        return config

    try:
        with open(path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        # Merge with default config to ensure new parameters have values
        return merge_config(get_default_config(), loaded)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Config file read failed: {e}, using default config")
        return get_default_config()


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> None:
    """
    Save configuration file

    Args:
        config: Configuration dictionary
        config_path: Config file path, defaults to CONFIG_FILE
    """
    path = config_path or CONFIG_FILE

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def merge_config(default: Dict[str, Any], loaded: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge configurations, loaded config overrides defaults

    Args:
        default: Default configuration
        loaded: Loaded configuration

    Returns:
        Dict[str, Any]: Merged configuration
    """
    result = default.copy()

    for key, value in loaded.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value

    return result


def validate_config(config: Dict[str, Any]) -> tuple[bool, list]:
    """
    Validate configuration

    Args:
        config: Configuration dictionary

    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []

    # Check required parameters
    if config.get("check_interval", 0) < 60:
        errors.append("check_interval must be >= 60 seconds")

    if config.get("health_check", {}).get("timeout", 0) < 1:
        errors.append("health_check.timeout must be >= 1 second")

    if config.get("resource_silence", {}).get("cpu_threshold", 0) < 0:
        errors.append("resource_silence.cpu_threshold must be >= 0")

    if config.get("restart", {}).get("max_retries", 0) < 0:
        errors.append("restart.max_retries must be >= 0")

    return len(errors) == 0, errors


def create_sample_config() -> None:
    """
    Create sample configuration file in config directory
    """
    sample_path = CONFIG_DIR / "config.sample.json"
    config = get_default_config()

    # Add comments
    sample_content = '''{
    // OpenClaw Watchdog Configuration File
    // Copy this file as config.json to use
    //
    // Important parameters:
    // - check_interval: Monitoring interval, recommended >= 60 seconds
    // - health_check.timeout: Health check timeout
    // - business_silence: Check for active sessions and tools
    // - io_silence.silence_threshold: How long without log update to consider silent
    // - resource_silence.cpu_threshold: CPU usage below this is considered silent
    // - restart.cooldown: Wait time before allowing another restart

    ''' + json.dumps(config, indent=4, ensure_ascii=False) + "\n}"

    sample_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sample_path, 'w', encoding='utf-8') as f:
        f.write(sample_content)

    print(f"Sample config file created: {sample_path}")


if __name__ == "__main__":
    # Test configuration functionality
    print("=== OpenClaw Watchdog Configuration Manager ===\n")

    # Create sample config
    create_sample_config()

    # Load config
    config = load_config()
    print(f"\nCurrent config path: {CONFIG_FILE}")
    print(f"Check interval: {config['check_interval']} seconds")
    print(f"CPU threshold: {config['resource_silence']['cpu_threshold']}%")
    print(f"IO silence threshold: {config['io_silence']['silence_threshold']} seconds")
