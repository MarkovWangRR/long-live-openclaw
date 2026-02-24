
## Technical Solution Design

We use the **"Triple-Silence Logic"** approach combined with macOS's native **launchd** daemon mechanism to implement a robust yet gentle watchdog.

### 1. Architecture Components

* **Monitor Layer**: Managed by macOS's `launchd`, responsible for waking up the detection script every 300 seconds (5 minutes).
* **Logic Layer**: A Python script that performs multi-dimensional state scanning via OpenClaw CLI and system-level APIs.
* **Action Layer**: Calls `openclaw gateway restart` for graceful restart, utilizing its built-in `SIGTERM` handling to protect data.

### 2. Core Detection Algorithm (Restart Decision)

The script makes decisions in the following priority order. If any step fails, the restart will be cancelled:

1. **Health Check**:
   * Call `openclaw doctor`. If there's no response after 10 seconds, it's considered a **hard deadlock** and triggers an immediate forced restart.


2. **Business Silence**:
   * Parse `openclaw status --json`.
   * **Criteria**: `active_sessions` == 0 AND `running_tools` == 0.


3. **IO Silence**:
   * Check the file modification time (mtime) of `~/Library/Logs/OpenClaw/diagnostics.jsonl`.
   * **Criteria**: No log writes in the past 180 seconds (3 minutes), ensuring no potential data flow.


4. **Resource Silence**:
   * Check process CPU usage.
   * **Criteria**: CPU Usage < 5%, ensuring no ongoing background inference or vector computation.



### 3. Technology Stack

| Aspect | Recommended Solution | Reason |
| --- | --- | --- |
| **Scheduler** | `launchd` (LaunchAgents) | Native macOS support, more stable than `cron`, supports auto-restart on process crash. |
| **Logic Language** | Python | Best system compatibility, no extra dependencies, handles JSON data quickly. |
| **Status Acquisition** | `OpenClaw CLI` | Can read internal program state (session count), more intelligent than pure process monitoring. |
| **Restart Method** | `Graceful Restart` | Allows Node.js process to complete final disk cache writes, preventing memory loss. |

---

## Implementation Steps

1. **Script Deployment**: Write a Python script containing the above logic.
2. **Plist Configuration**: Create a corresponding `.plist` file in `~/Library/LaunchAgents` with `StartInterval` set to 300.
3. **Log Monitoring**: Redirect watchdog script output to `/tmp/claw_watchdog.log` for easy auditing of restart records.

> **Important Note**: Before enabling in production, it is recommended to manually run the script in the terminal and verify that the output format of `openclaw status --json` matches the parsing logic in the script.

For detailed usage instructions, please refer to [README_USAGE.MD](README_USAGE.MD).

