# OpenClaw Watchdog Quick Start

## Install

```bash
python3 install.py install
```

## Check Status

```bash
python3 install.py status
```

## Modify Config

Config file: `~/.openclaw/watchdog/config.json`

Common options:

```json
{
    "check_interval": 300,  // Check interval in seconds (default 5 min)
    "restart": {
        "command": "openclaw gateway restart",
        "cooldown": 300
    },
    "business_silence": {
        "enabled": true,
        "require_zero_sessions": true,
        "require_zero_tools": true
    }
}
```

Restart to apply:

```bash
python3 install.py restart
```

## Stop

```bash
python3 install.py stop
```

## Logs

```bash
tail -f /tmp/claw_watchdog.log
```
