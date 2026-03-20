# Community FPV QUICKSTART

Status: active local/LAN quickstart for `swarm_control_core`.

Use this for the shortest path to local robot FPV + control.
For full detail and extended troubleshooting, use:
- [`LOCAL_FPV_runbook.md`](LOCAL_FPV_runbook.md)

This runbook is split into two parts:
1. **Quickstart Path** at the top.
2. **Alternative/Debug/Fix** at the bottom.

Operator model for this quickstart (required):
- Run everything from the control machine.
- Keep one dedicated terminal per robot SSH session open for the full run.
- Keep one separate control-machine terminal for the local FPV UI.

Suggested terminal layout on the control machine:
- `CM-UI`: local UI terminal.
- `R-<robot-a>`: `ssh <robot_user>@<robot_host>.local`
- `R-<robot-b>`: `ssh <robot_user>@<robot_host>.local`
- add one terminal per additional robot.

## Mode Handoff Checklist (core <-> pro)

Use this when both `swarm_control_core` and `swarm_control_pro` exist on the same robots.

From pro persistent mode to core session mode:
- Run this core quickstart normally (Step 2 robot prep + Step 3 UI).
- Core compat prep stops conflicting services/processes and applies runtime-only masks as needed.
- No reboot is required to enter core session mode.

From core session mode back to pro persistent mode:
- Run pro quickstart Step 2 (`service-sync`) from the control machine.
- Pro service-sync now clears core runtime masks automatically and restores pro persistent service ownership in the same boot.
- Reboot is still acceptable (optional) if you want a full clean restart of robot state before returning to pro.

Quick sanity checks on a robot:

```bash
sudo systemctl is-enabled swarm-robot.service || true
sudo systemctl is-active swarm-robot.service || true
```

# Quickstart Path:

<a id="step-0"></a>
## Step 0: Workspace Bootstrap + Dependency Readiness

### Step 0.0: Workspace bootstrap (run in each terminal)

```bash
SWARM_CORE_BOOTSTRAP="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_com_workspace_bootstrap.sh" 2>/dev/null | sort | head -n1)"
if [[ -z "$SWARM_CORE_BOOTSTRAP" ]]; then
  echo "[FAIL] Could not locate swarm_control_core workspace bootstrap script under ${SWARM_SEARCH_ROOT:-$HOME}." >&2
else
  eval "$("$SWARM_CORE_BOOTSTRAP" --interactive --emit-shell)"
fi
unset SWARM_CORE_BOOTSTRAP
```

### Run on control machine:

```bash
"$WS/src/swarm_control_core/scripts/swarm_com_check_install_dependencies.sh" \
  --machine-role control
```

### Run in each dedicated robot SSH terminal (one terminal per robot):

```bash
"$WS/src/swarm_control_core/scripts/swarm_com_check_install_dependencies.sh" \
  --machine-role robot
```

### Verify success

Expected output ends with:

`All community dependencies have been successfully installed.`

And includes:
- `[iw] is already installed.` (or installed during this step), so Wi-Fi power-save checks are available on robots.

### IF dependency install/check fails

Go to [Fix Step 0.1](#ref-0-1), then return to [Step 0](#step-0).

Proceed to Step 1.

<a id="step-1"></a>
## Step 1: Sync/Build/Source Gate (All Machines)

### Run on control machine, then run the same sync/build block in each dedicated robot SSH terminal:

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune
git switch main || git checkout -b main origin/main
git pull --ff-only origin main

rg -n -- '--machine-role|--compat-mode|compat-stop-ufw|ROS_AUTOMATIC_DISCOVERY_RANGE|SWARM_COM_PROCESS_RESET_DONE|SWARM_COM_WEBRTC_FPS|SWARM_COM_THUMB_REFRESH_HZ|SWARM_COM_IMAGE_SUBSCRIPTION_MODE|SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S|SWARM_COM_THUMB_ROBOTS_PER_TICK|SWARM_COM_DRIVE_CMD_RATE_HZ|SWARM_COM_DRIVE_HOLD_TIMEOUT_S' \
  "$WS/src/swarm_control_core/scripts/swarm_com_reset_env.sh" \
  "$WS/src/swarm_control_core/scripts/swarm_com_terminate_existing_robot_processes.sh" \
  "$WS/src/swarm_control_core/scripts/swarm_com_run_robot.sh" \
  "$WS/src/swarm_control_core/scripts/swarm_com_run_local_ui.sh"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --packages-select swarm_control_core
source "$WS/install/setup.bash"
set -u || true
```

### Verify success

Expected:
- package builds successfully
- no missing `swarm_control_core` package errors
- compatibility script check prints matches for:
  `--machine-role`, `--compat-mode`, `compat-stop-ufw`,
  `ROS_AUTOMATIC_DISCOVERY_RANGE`, and `SWARM_COM_PROCESS_RESET_DONE`

### IF build/source fails

Go to [Fix Step 1.1](#ref-1-1), then return to [Step 1](#step-1).

Proceed to Step 2.

<a id="step-2"></a>
## Step 2: Start Robot Bringup (Dedicated Robot SSH Terminals)

### Run in each dedicated robot SSH terminal:

```bash
# Block A: compatibility prep + robot identity exports
# Compatibility prep for mixed-use robots (community + proprietary):
# - clears conflicting env/session vars
# - stops conflicting services/processes
# - applies runtime-only proprietary service masks (auto-cleared on reboot)
# - in compat mode, may stop ufw runtime so DDS discovery is not blocked
#   (reboot restores ufw policy)
source "$WS/src/swarm_control_core/scripts/swarm_com_reset_env.sh" \
  --scope deep \
  --machine-role robot \
  --compat-mode \
  --domain-id "${SWARM_COM_ROS_DOMAIN_ID:-17}" || {
    echo "[FAIL] community compatibility reset failed; sync/pull latest swarm_control_core and retry."
    return 1 2>/dev/null || exit 1
  }

export SWARM_COM_ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"
export SWARM_COM_ROBOT_NAME="${SWARM_COM_ROBOT_NAME:-$(id -un)}"
# Optional camera bypass for noisy camera devices:
# export SWARM_COM_USE_CAMERA=false

# Verify robot firewall/power-save state (required for stable local DDS + Wi-Fi latency):
systemctl is-active ufw.service || true
if command -v iw >/dev/null 2>&1; then
  if iw dev wlan0 info >/dev/null 2>&1; then
    # Idempotent: only changes state when power save is currently ON.
    if iw dev wlan0 get power_save 2>/dev/null | grep -qi 'Power save: on'; then
      sudo iw dev wlan0 set power_save off
    fi
    iw dev wlan0 get power_save || true
  fi
fi
# If ufw is active, stop it for this runtime session:
#   sudo systemctl stop ufw.service
# If `iw` is missing, rerun Step 0 on this robot.
```

### SET CAMERA PROFILE

### Run in each dedicated robot SSH terminal:

```bash
# Block B (recommended): configure/persist camera profile before launch
# ACTION REQUIRED:
#   choose the camera entry that should be used for this robot when prompted.
# NOTE:
#   explicit menu selection is now respected even if probe warns.
#   (set SWARM_COM_CAMERA_ALLOW_PROBE_FALLBACK=1 to allow auto-fallback)
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true
ROBOT_NAME="${SWARM_COM_ROBOT_NAME:-${USER:-$(id -un)}}"
ros2 run swarm_control_core save_camera_profile_com --robot "$ROBOT_NAME"
```

Expected from save step:
- `output: /home/<user>/.config/swarm_control_core/camera_profiles.yaml`

### LAUNCH EACH ROBOT

### Run in each dedicated robot SSH terminal:

```bash
# Block C: launch robot bringup
ROBOT_NAME="${SWARM_COM_ROBOT_NAME:-${USER:-$(id -un)}}"
"$WS/src/swarm_control_core/scripts/swarm_com_run_robot.sh" "$ROBOT_NAME"
```

Profile refresh behavior:
- `swarm_com_run_robot.sh` refreshes core runtime profiles from Git each launch
  (`robot_instances.yaml`, `control_types.yaml`, `control_interfaces.yaml`,
  `capability_profiles.yaml`, `adapter_profiles.yaml`) while preserving
  existing `camera_profiles.yaml`.
- Disable this only if you intentionally maintain custom local runtime profiles:
  `export SWARM_COM_SEED_OVERWRITE_CORE_PROFILES=0`

### Verify success

Expected robot-side nodes include:
- `motor_driver_node`
- `heartbeat_node`
- `unit_executor_action_server`
- `camera` (if `use_camera:=true`)

### IF robot nodes or camera do not come up

Go to [Fix Step 2.1](#ref-2-1), then return to [Step 2](#step-2).

For multi-robot sessions:
- keep each robot SSH terminal running.
- proceed to Step 3 after each robot terminal shows all bringup nodes started and camera first-frame logs.

If one robot feed is much darker than others (while transport/control are healthy), validate camera controls on that robot:

```bash
v4l2-ctl --device /dev/v4l/by-id/<your-camera> --list-ctrls
```

This is typically per-camera exposure/gain behavior, not DDS/WebRTC transport behavior.

If teleop/video feels laggy while motors are receiving frequent commands:
- reduce cmd_vel audit overhead for this session:

```bash
export SWARM_COM_AUDIT_CMD_VEL_MIN_PERIOD_S=2.0
```

Reboot behavior note:
- Compatibility prep uses runtime-only masks for proprietary services.
- Reboot clears those masks automatically and returns service startup policy to proprietary defaults.
- If compat mode stopped `ufw.service` at runtime, reboot (or `sudo systemctl start ufw.service`)
  restores the saved firewall policy.

Proceed to Step 3.

<a id="step-3"></a>
## Step 3: Start Local FPV UI (Control Machine)

Prerequisite (required):
- Do not start Step 3 until every robot terminal has completed Step 2 and each robot bringup is running.

### Run on control machine:

```bash
# Compatibility prep for mixed-use control machine state:
# - in compat mode, may stop ufw runtime if needed for DDS discovery
source "$WS/src/swarm_control_core/scripts/swarm_com_reset_env.sh" \
  --scope deep \
  --machine-role control \
  --compat-mode \
  --domain-id "${SWARM_COM_ROS_DOMAIN_ID:-17}" || {
    echo "[FAIL] community compatibility reset failed; sync/pull latest swarm_control_core and retry."
    return 1 2>/dev/null || exit 1
  }

export SWARM_COM_ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"
# Multi-robot low-latency defaults (local/LAN):
# - keep main-pane transport WebRTC-only
# - pace WebRTC to match the low-latency camera clamp
# - disable passive thumbnail probing so non-active robot video stays completely off
# - keep camera subscriptions interest-driven so control does not ingest full-fleet video continuously
# - keep drive target refresh aligned with the last stable community defaults
# - set explicit values (no `:-`) so old shell values cannot silently persist
export SWARM_COM_WEBRTC_FPS=15.0
export SWARM_COM_THUMB_REFRESH_HZ=0.5
export SWARM_COM_IMAGE_SUBSCRIPTION_MODE=active_only
export SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S=0.75
export SWARM_COM_THUMB_ROBOTS_PER_TICK=0
export SWARM_COM_DRIVE_CMD_RATE_HZ=20.0
export SWARM_COM_DRIVE_HOLD_TIMEOUT_S=0.35
"$WS/src/swarm_control_core/scripts/swarm_com_run_local_ui.sh"
```

Terminal usage requirement:
- Keep each robot SSH terminal open while operating.
- Run the UI only in `CM-UI`.

Operator tip:
- Keep only one active UI tab/window connected to avoid unnecessary duplicate WebRTC/control sessions.

For maximum active-robot latency reduction in single-robot focus mode (at the cost of much slower fleet-tile updates and slower robot switching):

```bash
export SWARM_COM_THUMB_ROBOTS_PER_TICK=0
```

Switch behavior (expected):

- Active robot switch triggers WebRTC main-stream handoff while thumbnail requests keep short-lived interest windows warm on side tiles.
- Keep `SWARM_COM_THUMB_ROBOTS_PER_TICK=1` for balanced fleet tile updates.
- Use `SWARM_COM_THUMB_ROBOTS_PER_TICK=0` only when you care about one active robot and minimal background load.

If rapid back-and-forth switching still feels sticky in `active_only` mode, use this switch-heavy profile:

```bash
export SWARM_COM_THUMB_REFRESH_HZ=1.0
export SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S=4.0
```

Open in browser:
- `http://127.0.0.1:8080`

Video path:
- Main stream uses strict WebRTC-only transport by default.
- To keep all robot camera streams subscribed continuously (higher load), set `SWARM_COM_IMAGE_SUBSCRIPTION_MODE=all`.
- Fleet thumbnails stay in side tiles and do not take over the main pane.

Optional private LAN bind:

```bash
export SWARM_COM_ALLOW_LAN_BIND=1
export SWARM_COM_BIND_HOST=0.0.0.0
"$WS/src/swarm_control_core/scripts/swarm_com_run_local_ui.sh"
```

### IF UI does not load or bind

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3).

Proceed to Step 4.

<a id="step-4"></a>
## Step 4: Fleet Readiness Check (Control Machine)

Run on control machine:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

env | rg -E '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION)=' || true
ros2 topic list | rg "/.*/(heartbeat|camera/image_raw|cmd_vel)"
ros2 node list | rg "(swarm_fpv_ui|motor_driver_node|heartbeat_node|unit_executor_action_server|camera)"
```

### Verify success

Expected:
- heartbeat/camera/cmd_vel topics visible for active robots
- UI displays robots and streams

### IF robots are missing in UI/topics

Go to [Fix Step 4.1](#ref-4-1), then return to [Step 4](#step-4).

Proceed to Step 5.

<a id="step-5"></a>
## Step 5: Optional Terminal Control (Control Machine)

Terminal teleop:

```bash
export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"
ros2 run swarm_control_core swarm_teleop_com
```

Terminal orchestrator:

```bash
export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"
ros2 run swarm_control_core terminal_orchestrator_com
```

### IF terminal control cannot discover robots

Go to [Fix Step 5.1](#ref-5-1), then return to [Step 5](#step-5).

Quickstart complete.

# Alternative/Debug/Fix

<a id="ref-0-1"></a>
## Fix Step 0.1: Dependency install/check fails

Run:

```bash
sudo apt-get update
"$WS/src/swarm_control_core/scripts/swarm_com_check_install_dependencies.sh" \
  --machine-role control
```

Then return to [Step 0](#step-0).

<a id="ref-1-1"></a>
## Fix Step 1.1: Build/source fails

Run clean rebuild:

```bash
cd "$WS"
rm -rf build/swarm_control_core install/swarm_control_core log/latest_build/swarm_control_core
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --packages-select swarm_control_core --event-handlers console_direct+
source "$WS/install/setup.bash"
set -u || true
```

Then return to [Step 1](#step-1).

<a id="ref-2-1"></a>
## Fix Step 2.1: Robot nodes/camera fail to start

Run on affected robot:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
ros2 node list
ros2 topic list | rg "/${ROBOT_NAME}/(heartbeat|camera/image_raw|cmd_vel)"
ros2 run swarm_control_core save_camera_profile_com --robot "$ROBOT_NAME"
```

Then return to [Step 2](#step-2).

<a id="ref-3-1"></a>
## Fix Step 3.1: UI does not load or bind

Run on control machine:

```bash
"$WS/src/swarm_control_core/scripts/swarm_com_free_ui_port.sh" --port 8080
export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"
"$WS/src/swarm_control_core/scripts/swarm_com_run_local_ui.sh"
```

If LAN access is needed, set:

```bash
export SWARM_COM_ALLOW_LAN_BIND=1
export SWARM_COM_BIND_HOST=0.0.0.0
```

Then return to [Step 3](#step-3).

<a id="ref-4-1"></a>
## Fix Step 4.1: Robots missing in UI/topics

Check domain and source consistency on control + robots:

```bash
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID (target=${SWARM_COM_ROS_DOMAIN_ID:-17})"
env | rg -E '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION)=' || true
ros2 topic list | rg "/.*/heartbeat"
```

All machines must use the same domain id (default `17`) and sourced workspace.

If robot terminals show heartbeat publishing but control still has no heartbeat topics,
DDS traffic is being blocked (commonly by ufw state carried from proprietary setup).
Keep compat defaults and rerun [Step 2](#step-2) on robots + [Step 3](#step-3) on control.

If you previously forced firewall preservation, remove that override:

```bash
unset SWARM_COM_COMPAT_STOP_UFW
```

If reset script prints `Unknown argument: --machine-role`, your robot/control checkout is stale.
Run on each machine:

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune
git switch main || git checkout -b main origin/main
git pull --ff-only origin main
```

Then return to [Step 4](#step-4).

<a id="ref-5-1"></a>
## Fix Step 5.1: Terminal control cannot discover robots

Run on control machine:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 topic list | rg "/.*/cmd_vel"
ros2 action list | rg "/.*/execute_playbook"
```

Then return to [Step 5](#step-5).
