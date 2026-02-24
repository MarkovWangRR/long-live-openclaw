When running Node.js-based AI Agents (like OpenClaw) for extended periods, setting up a "watchdog" process is a standard practice to ensure high availability. This is due to memory thrashing, zombie child processes, or network connection hangs.

![alt text](watch_dog_openclaw.png)

---

## Project Overview

* **Core Goal**: Design an automated monitoring and self-healing system for **OpenClaw (Moltbot/Clawdbot)** gateway running on macOS.
* **Pain Points**:
    * **Stability**: Long-running gateways may become unresponsive or enter a deadlock state.
    * **Seamless Restart**: Need a mechanism to periodically clean and restart the service without interrupting the user's current conversation or ongoing tool (Tools) tasks.


* **Core Constraints**: Default monitoring interval is 5 minutes (customizable), restart actions must avoid active communication windows, and must be compatible with the native macOS architecture.

---


## Features

- **Cross-platform support**: macOS (launchd) and Linux (systemd/cron)
- **Four-layer detection**: Health check, business silence, IO silence, resource silence
- **Fully configurable**: All thresholds and parameters are customizable
- **Graceful restart**: Support pre/post restart hooks
- **Logging**: Complete operation logs for auditing

---

## Supported Platforms

| Platform | Service Manager | Log Path |
|----------|----------------|----------|
| macOS | launchd | `~/Library/Logs/OpenClaw/diagnostics.jsonl` |
| Linux (systemd) | systemd | `~/.config/openclaw/logs/diagnostics.jsonl` |
| Linux (cron) | cron | `~/.config/openclaw/logs/diagnostics.jsonl` |

---

## Quick Start

### 1. Install Dependencies

```bash
# Ensure Python 3 is installed
python3 --version

# No additional dependencies required, uses standard library
```

### 2. One-Click Install

```bash
# Install and start watchdog
python3 install.py install
```

The installation will automatically:
1. Detect current platform
2. Create default config file (`~/.openclaw/watchdog/config.json`)
3. Deploy corresponding system service
4. Start watchdog

### 3. Check Status

```bash
# View service status and logs
python3 install.py status
```

---

## Configuration File

Config file is located at `~/.openclaw/watchdog/config.json`

### Complete Config Example

```json
{
    // ========== Platform Info (Read-only) ==========
    "platform": "darwin",

    // ========== Monitoring Interval ==========
    "check_interval": 300,

    // ========== Health Check Config ==========
    "health_check": {
        "enabled": true,
        "command": "openclaw doctor",
        "timeout": 10,
        "fail_action": "restart"
    },

    // ========== Business Silence Config ==========
    "business_silence": {
        "enabled": true,
        "status_command": "openclaw status --json",
        "require_zero_sessions": true,
        "require_zero_tools": true,
        "status_timeout": 15
    },

    // ========== IO Silence Config ==========
    "io_silence": {
        "enabled": true,
        "log_path": "~/Library/Logs/OpenClaw/diagnostics.jsonl",
        "silence_threshold": 180,
        "check_file_exists": true
    },

    // ========== Resource Silence Config ==========
    "resource_silence": {
        "enabled": true,
        "process_name": "openclaw",
        "cpu_threshold": 5.0,
        "check_interval": 3,
        "check_delay": 1,
        "ps_command": "ps -ax -o %cpu,comm | grep \"{process}\" | grep -v grep | head -1"
    },

    // ========== Restart Config ==========
    "restart": {
        "command": "openclaw gateway restart",
        "max_retries": 3,
        "retry_delay": 10,
        "cooldown": 300,
        "graceful_wait": 5
    },

    // ========== Logging Config ==========
    "logging": {
        "log_file": "/tmp/claw_watchdog.log",
        "log_level": "INFO",
        "max_log_size": 10485760,
        "log_rotation": 5
    },

    // ========== Advanced Config ==========
    "advanced": {
        "require_all_checks": true,
        "skip_on_error": true,
        "pre_restart_hook": null,
        "post_restart_hook": null
    }
}
```

### Config Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `platform` | string | (auto-detect) | Platform: `darwin` or `linux` |
| `check_interval` | int | 300 | Check interval in seconds |
| `health_check.timeout` | int | 10 | Health check timeout in seconds |
| `health_check.fail_action` | string | "restart" | Action on timeout: `restart` or `ignore` |
| `business_silence.require_zero_sessions` | bool | true | Require `active_sessions == 0` |
| `business_silence.require_zero_tools` | bool | true | Require `running_tools == 0` |
| `io_silence.silence_threshold` | int | 180 | IO silence threshold in seconds |
| `io_silence.check_file_exists` | bool | true | Check if log file exists before checking |
| `io_silence.fail_on_missing` | bool | false | Fail IO check if log file doesn't exist |
| `resource_silence.cpu_threshold` | float | 5.0 | CPU usage threshold in % |
| `resource_silence.ps_command` | string | (platform-specific) | Command template to get CPU usage |
| `restart.cooldown` | int | 300 | Restart cooldown in seconds |
| `restart.max_retries` | int | 3 | Maximum retry attempts |
| `logging.log_level` | string | "INFO" | Log level: `DEBUG` `INFO` `WARNING` `ERROR` |
| `advanced.require_all_checks` | bool | true | Require all checks to pass before restart |
| `advanced.pre_restart_hook` | string | null | Script to run before restart |
| `advanced.post_restart_hook` | string | null | Script to run after restart |

---

## Usage

### Command Line Arguments

```bash
# Start watchdog (runs in loop by default)
python3 watchdog.py

# Single check (for testing)
python3 watchdog.py --once

# Specify config file
python3 watchdog.py --config /path/to/config.json

# Validate config file
python3 watchdog.py --validate
```

### Installer Commands

```bash
# Install and start
python3 install.py install

# Stop service
python3 install.py stop

# Restart service
python3 install.py restart

# View status
python3 install.py status

# Uninstall service
python3 install.py uninstall

# Test run (single check)
python3 install.py test
```

### Platform-Specific Service Management

#### macOS (launchd)

```bash
# Load service
launchctl load -w ~/Library/LaunchAgents/com.openclaw.watchdog.plist

# Unload service
launchctl unload -w ~/Library/LaunchAgents/com.openclaw.watchdog.plist

# View service status
launchctl list | grep openclaw
```

#### Linux (systemd)

```bash
# Start service
sudo systemctl start openclaw-watchdog.service

# Stop service
sudo systemctl stop openclaw-watchdog.service

# View service status
sudo systemctl status openclaw-watchdog.service

# View real-time logs
journalctl -u openclaw-watchdog.service -f
```

#### Linux (cron)

```bash
# Edit crontab
crontab -e

# View current cron jobs
crontab -l | grep openclaw
```

### View Logs

```bash
# Real-time logs
tail -f /tmp/claw_watchdog.log

# Recent 100 lines
tail -100 /tmp/claw_watchdog.log
```

---

## Log Details

Log file is located at `/tmp/claw_watchdog.log`

### Log Levels

- `DEBUG`: Detailed debug information
- `INFO`: Normal operation information
- `WARNING`: Warning information
- `ERROR`: Error information

### Example Log

```
2024-01-15 10:00:00 [INFO] OpenClaw Watchdog started
2024-01-15 10:00:00 [INFO] Check interval: 300 seconds
2024-01-15 10:00:00 [INFO] ==================
2024-01-15 10:00:00 [INFO] Starting health check
2024-01-15 10:00:00 [INFO] Running health check: openclaw doctor
2024-01-15 10:00:01 [INFO] Health check passed
2024-01-15 10:00:01 [INFO] Running business silence check
2024-01-15 10:00:01 [INFO] Business silence check passed
2024-01-15 10:00:02 [INFO] Running IO silence check
2024-01-15 10:00:02 [INFO] IO silence check passed
2024-01-15 10:00:05 [INFO] Running resource silence check
2024-01-15 10:00:05 [INFO] Resource silence check passed
2024-01-15 10:00:05 [INFO] Conditions not met, not restarting
2024-01-15 10:00:05 [INFO] Waiting 300 seconds for next check...
```

---

## Troubleshooting

### 1. Watchdog Not Starting

```bash
# View service status
python3 install.py status

# View error logs
cat /tmp/claw_watchdog.stderr.log
```

### 2. Config File Format Error

```bash
# Validate config
python3 watchdog.py --validate
```

### 3. openclaw Command Not Found

Ensure `openclaw` is in system PATH:
```bash
which openclaw
```

### 4. IO Silence Check - Log File Not Found

If you see warnings like:
```
[WARNING] Log file does not exist: /path/to/log
[WARNING] IO silence check skipped - log file not found
```

This means OpenClaw diagnostics log file is not being created. To fix:

1. **Enable diagnostics in OpenClaw config** (add or update):
   ```json
   {
     "diagnostics": true
   }
   ```

2. **Or update config location** in `~/.openclaw/watchdog/config.json`:
   ```json
   {
     "io_silence": {
       "log_path": "/correct/path/to/diagnostics.jsonl",
       "fail_on_missing": false
     }
   }
   ```

3. **Or disable IO check** if not needed:
   ```json
   {
     "io_silence": {
       "enabled": false
     }
   }
   ```

By default, watchdog allows restart even if log file is missing. Set `fail_on_missing: true` to enforce stricter checks.

### 5. Manual Test Detection Logic

```bash
# Single run test
python3 watchdog.py --once
```

### 6. Linux Permission Issues

systemd service may require root:
```bash
sudo python3 install.py install
```

---

## Hook Script Examples

### Pre-Restart Notification

```bash
#!/bin/bash
# pre_restart.sh

echo "$(date): Preparing to restart OpenClaw" >> /tmp/claw_restart.log
# Add notification, status logging, etc.
```

### Post-Restart Check

```bash
#!/bin/bash
# post_restart.sh

sleep 5  # Wait for service to start

# Check if service is healthy
if openclaw status > /dev/null 2>&1; then
    echo "$(date): OpenClaw restarted successfully" >> /tmp/claw_restart.log
else
    echo "$(date): OpenClaw restart failed" >> /tmp/claw_restart.log
fi
```

Enable in config:
```json
{
    "advanced": {
        "pre_restart_hook": "/path/to/pre_restart.sh",
        "post_restart_hook": "/path/to/post_restart.sh"
    }
}
```

---

## Uninstall

```bash
# Uninstall watchdog
python3 install.py uninstall

# Manual cleanup
# macOS
rm -f ~/Library/LaunchAgents/com.openclaw.watchdog.plist

# Linux (systemd)
sudo rm -f /etc/systemd/system/openclaw-watchdog.service
sudo systemctl daemon-reload

# Config
rm -f ~/.openclaw/watchdog/config.json

# Logs
rm -f /tmp/claw_watchdog.log
```

---

## Directory Structure

```
long-live-openclaw/
├── README.MD              # Project background
├── README_USAGE.MD         # Usage guide
├── config.py               # Configuration module (cross-platform)
├── watchdog.py             # Core watchdog script
├── install.py              # Installer (multi-platform)
├── com.openclaw.watchdog.plist  # launchd config template
└── test_watchdog.py        # Test cases
```

---

## Testing

```bash
# Run all tests
python3 test_watchdog.py

# Test coverage:
# - Config module tests
# - Core logic tests
# - Cross-platform tests
# - Integration tests
```
