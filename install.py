#!/usr/bin/env python3
"""
OpenClaw Watchdog - Installation and Configuration Script

Supported platforms:
- macOS: Uses launchd
- Linux: Uses systemd or cron

Features:
1. Create configuration file
2. Deploy system service
3. Start/Stop watchdog
4. Uninstall watchdog
"""

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Project paths
PROJECT_DIR = Path(__file__).parent.resolve()
SCRIPT_PATH = PROJECT_DIR / "watchdog.py"
CONFIG_PATH = Path.home() / ".openclaw" / "watchdog" / "config.json"
PLIST_SOURCE = PROJECT_DIR / "com.openclaw.watchdog.plist"

# Import config module for platform info
sys.path.insert(0, str(PROJECT_DIR))
from config import (
    get_platform,
    get_service_manager,
    get_systemd_service_template,
    get_cron_template,
    get_default_config,
    save_config,
    load_config
)


# Platform-specific paths
def get_plist_path() -> Path:
    """Get platform-specific service config file path"""
    platform = get_platform()

    if platform == "darwin":
        return Path.home() / "Library/LaunchAgents" / "com.openclaw.watchdog.plist"
    else:
        # Linux systemd
        return Path("/etc/systemd/system/openclaw-watchdog.service")


def run_command(cmd: list, check: bool = True, shell: bool = False) -> subprocess.CompletedProcess:
    """Run system command"""
    if shell:
        cmd_str = cmd[0] if isinstance(cmd, list) else cmd
        print(f"Execute: {cmd_str}")
    else:
        print(f"Execute: {' '.join(cmd)}")

    try:
        if shell:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True, shell=True)
        else:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command execution failed: {e}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        if check:
            sys.exit(1)
        return e


def detect_openclaw_log_path() -> Optional[str]:
    """
    Auto-detect OpenClaw log file path

    Returns:
        str or None: Detected log path or None if not found
    """
    home = Path.home()
    common_paths = [
        # macOS common paths
        home / "Library/Logs/OpenClaw/diagnostics.jsonl",
        home / "Library/Logs/openclaw/diagnostics.jsonl",
        home / ".openclaw/logs/diagnostics.jsonl",
        home / ".openclaw/logs/openclaw.log",
        home / ".config/openclaw/logs/diagnostics.jsonl",
        # Linux common paths
        home / ".local/share/openclaw/logs/diagnostics.jsonl",
        home / ".openclaw/logs/diagnostics.jsonl",
        # Current working directory
        Path.cwd() / "logs/diagnostics.jsonl",
    ]

    # Check each path
    for path in common_paths:
        if path.exists():
            return str(path)

    # Try to detect via openclaw CLI
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True,
            timeout=5,
            text=True
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            # Some versions might return log path in status
            if "log_path" in data:
                return data["log_path"]
    except Exception:
        pass

    return None


def prompt_log_path() -> str:
    """
    Auto-detect OpenClaw log file path (no user input required)

    Returns:
        str: Log path detected or default
    """
    print("\n" + "=" * 50)
    print("OpenClaw Log Path Detection")
    print("=" * 50)

    # Try to auto-detect
    detected = detect_openclaw_log_path()

    if detected:
        print(f"[OK] Auto-detected log path: {detected}")
    else:
        # Try to find via openclaw CLI with different approaches
        log_path = try_detect_via_cli()
        if log_path:
            print(f"[OK] Detected via CLI: {log_path}")
            detected = log_path
        else:
            # Fallback: check if openclaw config exists
            log_path, _ = find_via_config()
            if log_path:
                print(f"[OK] Found in config: {log_path}")
                detected = log_path

    # Check diagnostics setting and warn if not enabled
    diagnostics_warning = check_diagnostics_setting()
    if diagnostics_warning:
        print(f"\n[WARN] Diagnostics may not be enabled in OpenClaw")
        if diagnostics_warning != "default":
            print(f"[WARN] Please check: {diagnostics_warning}")
            print(f"[WARN] Add \"diagnostics\": true to enable diagnostics logging")
        else:
            print(f"[WARN] Using default settings - ensure diagnostics is enabled")

    if detected:
        return detected

    # Use default but warn
    default_path = str(Path.home() / "Library/Logs/OpenClaw/diagnostics.jsonl")
    print(f"\n[WARN] Could not detect log path, using default: {default_path}")
    print(f"[INFO] You can manually update 'io_silence.log_path' in config later")
    return default_path


def try_detect_via_cli() -> Optional[str]:
    """Try to detect log path via openclaw CLI commands"""
    # Try various CLI approaches
    commands = [
        ["openclaw", "doctor"],  # May contain paths
        ["openclaw", "info"],
        ["openclaw", "config", "get", "log"],
        ["openclaw", "config", "get", "logPath"],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
            if result.returncode == 0:
                output = result.stdout + result.stderr
                # Look for path patterns
                for line in output.split('\n'):
                    if '/logs/' in line or 'log' in line.lower():
                        # Extract potential path
                        paths = re.findall(r'[/~][^\s"\'<>]+(?:log|Logs)[^\s"\'<>]*', line)
                        if paths:
                            # Resolve path
                            p = Path(paths[0].replace('~', str(Path.home())))
                            if p.exists() or p.parent.exists():
                                return str(p)
        except Exception:
            continue

    return None


def find_via_config() -> tuple[Optional[str], bool]:
    """
    Find log path in openclaw config files

    Returns:
        tuple: (log_path, diagnostics_enabled)
    """
    home = Path.home()

    config_locations = [
        home / ".openclaw/config.json",
        home / ".openclaw/openclaw.json",
        home / ".config/openclaw/config.json",
        home / ".config/openclaw/openclaw.json",
    ]

    for config_file in config_locations:
        if config_file.exists():
            try:
                # Try JSON
                with open(config_file) as f:
                    data = json.load(f)

                    # Check for log path
                    for key in ['log', 'logPath', 'log_file', 'logging.path', 'diagnosticsPath']:
                        if key in data:
                            return data[key], True

                    # Check nested logging config
                    if 'logging' in data:
                        logging_config = data['logging']
                        for key in ['path', 'logPath', 'file']:
                            if key in logging_config:
                                return logging_config[key], logging_config.get('diagnostics', False)

            except Exception:
                pass

    return None, False


def check_diagnostics_setting() -> Optional[str]:
    """
    Check if diagnostics is enabled in OpenClaw config

    Returns:
        str or None: Warning message if diagnostics not enabled
    """
    home = Path.home()

    config_locations = [
        home / ".openclaw/config.json",
        home / ".openclaw/openclaw.json",
        home / ".config/openclaw/config.json",
        home / ".config/openclaw/openclaw.json",
    ]

    for config_file in config_locations:
        if config_file.exists():
            try:
                with open(config_file) as f:
                    data = json.load(f)

                    # Check various possible locations for diagnostics setting
                    diagnostics_enabled = False

                    # Top level
                    if data.get('diagnostics') is True:
                        diagnostics_enabled = True

                    # In logging section
                    if 'logging' in data:
                        if data['logging'].get('diagnostics') is True:
                            diagnostics_enabled = True

                    if diagnostics_enabled:
                        return None  # All good

                    # Find the config file path to show in warning
                    return str(config_file)

            except Exception:
                pass

    # No config found - might be using defaults
    return "default"


def create_config(force: bool = False) -> None:
    """Create configuration file

    Args:
        force: If True, force recreation of config without asking
    """
    print("=" * 50)
    print("Step 1: Create Configuration File")
    print("=" * 50)

    # Ensure directory exists
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists():
        print(f"\nConfig file already exists: {CONFIG_PATH}")

        # If force mode, just delete and recreate
        if force:
            print("Force mode: deleting existing config and creating new one...")
            CONFIG_PATH.unlink()
        else:
            # Ask user what to do
            print("\nOptions:")
            print("  [1] Keep existing configuration (recommended)")
            print("  [2] Delete and recreate with new settings")
            print("  [3] View current configuration")

            while True:
                choice = input("\nPlease select [1/2/3] (default: 1): ").strip()

                if choice == "" or choice == "1":
                    print("Using existing configuration")
                    return
                elif choice == "2":
                    print("Deleting existing config and recreating...")
                    CONFIG_PATH.unlink()
                    break
                elif choice == "3":
                    # Show current config
                    try:
                        with open(CONFIG_PATH, 'r') as f:
                            import json
                            config_data = json.load(f)
                        print("\n" + "=" * 40)
                        print("Current Configuration:")
                        print("=" * 40)
                        print(json.dumps(config_data, indent=2, ensure_ascii=False))
                        print("=" * 40)
                    except Exception as e:
                        print(f"Error reading config: {e}")
                    # Ask again after showing
                    print("\nOptions:")
                    print("  [1] Keep existing configuration")
                    print("  [2] Delete and recreate with new settings")
                    continue
                else:
                    print("Invalid input, please enter 1, 2, or 3")

    config = get_default_config()

    # Prompt for check interval
    print("\n--- Check Interval Configuration ---")
    print(f"Current: {config['check_interval']} seconds (5 minutes)")
    interval_input = input("Enter check interval in seconds (press Enter to keep default): ").strip()
    if interval_input:
        try:
            config['check_interval'] = int(interval_input)
            print(f"Set to: {config['check_interval']} seconds")
        except ValueError:
            print("Invalid input, using default: 300 seconds")
            config['check_interval'] = 300

    # Prompt for log path
    log_path = prompt_log_path()
    config['io_silence']['log_path'] = log_path

    save_config(config, CONFIG_PATH)

    print(f"\nConfig file created: {CONFIG_PATH}")
    print(f"Current platform: {config['platform']}")
    print(f"Service manager: {get_service_manager()}")
    print(f"\nConfig parameters:")
    print(f"  - Check interval: {config['check_interval']} seconds")
    print(f"  - IO log path: {log_path}")
    print(f"  - IO silence threshold: {config['io_silence']['silence_threshold']} seconds")
    print(f"  - CPU threshold: {config['resource_silence']['cpu_threshold']}%")
    print(f"  - Restart cooldown: {config['restart']['cooldown']} seconds")


def deploy_service() -> None:
    """Deploy system service"""
    print("\n" + "=" * 50)
    print("Step 2: Deploy System Service")
    print("=" * 50)

    platform = get_platform()
    service_manager = get_service_manager()

    print(f"Detected platform: {platform}")
    print(f"Service manager: {service_manager}")

    if platform == "darwin":
        deploy_launchd()
    elif platform == "linux":
        if service_manager == "systemd":
            deploy_systemd()
        else:
            deploy_cron()
    else:
        print(f"Unsupported platform: {platform}")
        sys.exit(1)


def deploy_launchd() -> None:
    """Deploy macOS launchd service"""
    plist_target = get_plist_path()

    # Ensure LaunchAgents directory exists
    plist_target.parent.mkdir(parents=True, exist_ok=True)

    # Get check interval from config
    try:
        config = load_config()
        check_interval = config.get("check_interval", 300)
    except Exception:
        check_interval = 300

    # Read plist template file and replace placeholders
    with open(PLIST_SOURCE, 'r', encoding='utf-8') as f:
        plist_content = f.read()

    # Replace placeholders
    plist_content = plist_content.replace('__SCRIPT_PATH__', str(SCRIPT_PATH))
    plist_content = plist_content.replace('__WORK_DIR__', str(PROJECT_DIR))
    plist_content = plist_content.replace('__INTERVAL__', str(check_interval))

    # Parse plist
    from io import BytesIO
    plist_data = plistlib.load(BytesIO(plist_content.encode('utf-8')))

    # Write plist
    with open(plist_target, 'wb') as f:
        plistlib.dump(plist_data, f)

    print(f"plist file created: {plist_target}")
    print(f"Check interval: {check_interval} seconds")


def deploy_systemd() -> None:
    """Deploy systemd service"""
    service_file = get_plist_path()

    # Ensure directory exists
    service_file.parent.mkdir(parents=True, exist_ok=True)

    # Get config
    try:
        config = load_config()
        check_interval = config.get("check_interval", 300)
    except Exception:
        check_interval = 300

    # Create service file
    template = get_systemd_service_template()
    template["Service"]["ExecStart"] = f"/usr/bin/python3 {SCRIPT_PATH} --once"

    # Write service file
    with open(service_file, 'w') as f:
        # Manual INI format
        f.write("[Unit]\n")
        for key, value in template["Unit"].items():
            f.write(f"{key}={value}\n")

        f.write("\n[Service]\n")
        for key, value in template["Service"].items():
            f.write(f"{key}={value}\n")

        f.write("\n[Install]\n")
        for key, value in template["Install"].items():
            f.write(f"{key}={value}\n")

    print(f"systemd service file created: {service_file}")

    # Reload systemd
    print("Reloading systemd configuration...")
    run_command(["systemctl", "daemon-reload"], check=False)


def deploy_cron() -> None:
    """Deploy cron job"""
    try:
        config = load_config()
        check_interval = config.get("check_interval", 300)
    except Exception:
        check_interval = 300

    # Calculate cron interval (minutes)
    interval_minutes = max(1, check_interval // 60)

    template = get_cron_template()
    cron_entry = template.replace("*/5", f"*/{interval_minutes}")
    cron_entry = cron_entry.replace("__SCRIPT_PATH__", str(SCRIPT_PATH))

    print(f"cron job entry:")
    print(f"  {cron_entry}")

    # Add to crontab
    print("\nAdding cron job...")
    # Get current crontab
    try:
        result = run_command(["crontab", "-l"], check=False, shell=False)
        current_crontab = result.stdout if result.returncode == 0 else ""
    except Exception:
        current_crontab = ""

    # Check if already exists
    if "openclaw-watchdog" in current_crontab:
        print("cron job already exists, skipping")
        return

    # Add new job
    new_crontab = current_crontab.strip() + "\n" + cron_entry + "\n"

    # Write to crontab
    process = subprocess.Popen(
        ["crontab", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    process.communicate(input=new_crontab)

    print("cron job added")


def start_service() -> None:
    """Start watchdog"""
    print("\n" + "=" * 50)
    print("Step 3: Start Watchdog")
    print("=" * 50)

    platform = get_platform()
    service_manager = get_service_manager()

    if platform == "darwin":
        start_launchd()
    elif platform == "linux":
        if service_manager == "systemd":
            start_systemd()
        else:
            print("In cron mode, service will run automatically")
            print(f"Watchdog will first execute in */{load_config().get('check_interval', 300)//60} minutes")


def start_launchd() -> None:
    """Start launchd service"""
    plist_target = get_plist_path()

    # Try to stop old service first
    print("Trying to stop old service...")
    run_command(['launchctl', 'unload', str(plist_target)], check=False)

    # Load new service
    print("Loading service...")
    run_command(['launchctl', 'load', '-w', str(plist_target)])

    # Check status
    print("Checking service status...")
    run_command(['launchctl', 'list', '|', 'grep', 'openclaw'], check=False)


def start_systemd() -> None:
    """Start systemd service"""
    service_name = "openclaw-watchdog.service"

    # Enable service
    print("Enabling service...")
    run_command(['systemctl', 'enable', service_name], check=False)

    # Start service
    print("Starting service...")
    run_command(['systemctl', 'start', service_name])

    # Check status
    print("Checking service status...")
    run_command(['systemctl', 'status', service_name], check=False)


def stop_service() -> None:
    """Stop watchdog"""
    print("\n" + "=" * 50)
    print("Stop Watchdog")
    print("=" * 50)

    platform = get_platform()
    service_manager = get_service_manager()

    if platform == "darwin":
        plist_target = get_plist_path()
        run_command(['launchctl', 'unload', '-w', str(plist_target)], check=False)
    elif platform == "linux" and service_manager == "systemd":
        service_name = "openclaw-watchdog.service"
        run_command(['systemctl', 'stop', service_name], check=False)
        run_command(['systemctl', 'disable', service_name], check=False)
    elif platform == "linux":
        # Clean up cron
        print("Cleaning up cron job...")
        run_command(
            "crontab -l | grep -v 'openclaw-watchdog' | crontab -",
            shell=True,
            check=False
        )

    print("Service stopped")


def uninstall() -> None:
    """Uninstall watchdog"""
    print("\n" + "=" * 50)
    print("Uninstall Watchdog")
    print("=" * 50)

    # Stop service
    stop_service()

    # Delete service config file
    service_file = get_plist_path()
    if service_file.exists():
        service_file.unlink()
        print(f"Deleted: {service_file}")

    # If systemd, reload
    if get_platform() == "linux" and get_service_manager() == "systemd":
        run_command(["systemctl", "daemon-reload"], check=False)

    # Delete config file
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
        print(f"Deleted config file: {CONFIG_PATH}")

    print("\nUninstall complete!")


def show_status() -> None:
    """Show service status"""
    print("\n" + "=" * 50)
    print("Service Status")
    print("=" * 50)

    platform = get_platform()
    service_manager = get_service_manager()

    print(f"Current platform: {platform}")
    print(f"Service manager: {service_manager}")

    if platform == "darwin":
        print("\nlaunchd service:")
        run_command(['launchctl', 'list', '|', 'grep', '-i', 'claw'], check=False)

    elif platform == "linux" and service_manager == "systemd":
        print("\nsystemd service:")
        run_command(['systemctl', 'status', 'openclaw-watchdog.service'], check=False)

    elif platform == "linux":
        print("\ncron job:")
        run_command(['crontab', '-l', '|', 'grep', 'claw'], check=False)

    # Check log
    log_file = Path("/tmp/claw_watchdog.log")
    if log_file.exists():
        print(f"\nRecent log ({log_file}):")
        run_command(['tail', '-20', str(log_file)], check=False)
    else:
        print("\nLog file does not exist")


def test_run() -> None:
    """Test run (single check)"""
    print("\n" + "=" * 50)
    print("Test Run - Single Check")
    print("=" * 50)

    cmd = [sys.executable, str(SCRIPT_PATH), '--once']
    run_command(cmd)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="OpenClaw Watchdog Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported platforms:
  - macOS: Uses launchd
  - Linux: Uses systemd or cron
        """
    )

    parser.add_argument(
        "action",
        choices=["install", "uninstall", "start", "stop", "restart", "status", "test"],
        help="Action to perform"
    )

    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip config creation step"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recreate configuration without asking (use with --skip-config to skip entirely)"
    )

    args = parser.parse_args()

    # Check if script exists
    if not SCRIPT_PATH.exists():
        print(f"Error: Script does not exist: {SCRIPT_PATH}")
        sys.exit(1)

    print("=" * 50)
    print("OpenClaw Watchdog Installer")
    print(f"Platform: {get_platform()}")
    print(f"Service Manager: {get_service_manager()}")
    print("=" * 50)

    if args.action == "install":
        if not args.skip_config:
            create_config(force=args.force)
        deploy_service()
        start_service()
        print("\n" + "=" * 50)
        print("Installation Complete!")
        print("=" * 50)
        print(f"Config path: {CONFIG_PATH}")
        print(f"Log path: /tmp/claw_watchdog.log")

    elif args.action == "uninstall":
        uninstall()

    elif args.action == "start":
        start_service()

    elif args.action == "stop":
        stop_service()

    elif args.action == "restart":
        stop_service()
        start_service()

    elif args.action == "status":
        show_status()

    elif args.action == "test":
        test_run()


if __name__ == "__main__":
    main()
