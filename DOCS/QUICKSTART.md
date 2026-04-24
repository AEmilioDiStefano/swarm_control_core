# Local FPV Quickstart

Status: active local/LAN quickstart for `swarm_control_core`.

Use this for the shortest path to local robot FPV + control.
For full detail and extended troubleshooting, use:
- [`LOCAL_FPV_runbook.md`](LOCAL_FPV_runbook.md)

If you are still assembling the reference robot or doing first-time machine
setup, start with:
- [`setup_instructions_ASSEMBLY.md`](setup_instructions_ASSEMBLY.md)
- [`setup_instructions_SOFTWARE.md`](setup_instructions_SOFTWARE.md)

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

Desktop/SSH usage note:
- Open the robot SSH session from the Ubuntu desktop first, then run the robot command blocks inside that SSH shell.
- Source only `swarm_core_bootstrap_env.sh`; run `swarm_core_quickstart_step*.sh` as commands.
- If bootstrap lookup fails, the shell should stay open so you can inspect the error instead of getting kicked out of SSH.

Workspace selection below is handled by the Step 0 terminal-bootstrap helper.
After that, use `WS` for the workspace root and `SC` for
`"$WS/src/swarm_control_core"`.

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

### Run on control machine:

```bash
swarm_core_bootstrap_terminal() {
  local helper=""
  helper="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_bootstrap_env.sh" 2>/dev/null | sort | head -n1)"
  if [[ -z "${helper:-}" ]]; then
    echo "[FAIL] Could not locate swarm_control_core terminal bootstrap helper under ${SWARM_SEARCH_ROOT:-$HOME}." >&2
    return 1
  fi
  if ! source "$helper" --interactive; then
    echo "[FAIL] swarm_control_core terminal bootstrap failed; keeping this shell open for inspection." >&2
    return 1
  fi
}

if swarm_core_bootstrap_terminal; then
  "$SC/scripts/swarm_core_quickstart_step0.sh" --machine-role control
fi
unset -f swarm_core_bootstrap_terminal
```

### Run in each dedicated robot SSH terminal (one per robot):

```bash
swarm_core_bootstrap_terminal() {
  local helper=""
  helper="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_bootstrap_env.sh" 2>/dev/null | sort | head -n1)"
  if [[ -z "${helper:-}" ]]; then
    echo "[FAIL] Could not locate swarm_control_core terminal bootstrap helper under ${SWARM_SEARCH_ROOT:-$HOME}." >&2
    return 1
  fi
  if ! source "$helper" --interactive; then
    echo "[FAIL] swarm_control_core terminal bootstrap failed; keeping this shell open for inspection." >&2
    return 1
  fi
}

if swarm_core_bootstrap_terminal; then
  "$SC/scripts/swarm_core_quickstart_step0.sh" --machine-role robot
fi
unset -f swarm_core_bootstrap_terminal
```

### Verify success

Expected output ends with:

`All dependencies are installed and up to date.`

And includes:
- `[iw] is already installed and up to date.` (or installed/updated during this step), so Wi-Fi power-save checks are available on robots.

### IF dependency install/check fails

Go to [Fix Step 0.1](#ref-0-1), then return to [Step 0](#step-0).

Proceed to Step 1.

<a id="step-1"></a>
## Step 1: Sync/Build/Source Gate (All Machines)

### Run on control machine, then run the same sync/build block in each dedicated robot SSH terminal:

```bash
"$SC/scripts/swarm_core_quickstart_step1.sh" --machine-role control
```

### Run in each dedicated robot SSH terminal:

```bash
"$SC/scripts/swarm_core_quickstart_step1.sh" --machine-role robot
```

### Verify success

Expected:
- package builds successfully
- no missing `swarm_control_core` package errors
- if GitHub/DNS is unavailable, Step 1 may print a warning and continue from the local checkout instead of aborting
- compatibility script check prints matches for:
  `--machine-role`, `--compat-mode`, `compat-stop-ufw`,
  `ROS_AUTOMATIC_DISCOVERY_RANGE`, and `SWARM_CORE_PROCESS_RESET_DONE`

### IF build/source fails

Go to [Fix Step 1.1](#ref-1-1), then return to [Step 1](#step-1).

Proceed to Step 2.

<a id="step-2"></a>
## Step 2: Start Robot Bringup (Dedicated Robot SSH Terminals)

### Run in each dedicated robot SSH terminal:

```bash
"$SC/scripts/swarm_core_quickstart_step2.sh"
```

Behavior of the step-2 wrapper:
- applies the robot compat reset
- defaults `SWARM_CORE_ROBOT_NAME` to the Linux username when not already set
- checks firewall/power-save state
- runs the interactive camera-profile save
- launches robot bringup and stays attached to it

Optional:
- if you already trust the saved camera profile and want to skip the interactive camera menu:
  `"$SC/scripts/swarm_core_quickstart_step2.sh" --skip-camera-profile`

Runtime config seeding behavior:
- `swarm_core_run_robot.sh` seeds missing runtime config files from
  `src/swarm_control_core/config` into `~/.config/swarm_control_core/`.
- Existing runtime files are kept by default, including
  `robot_instances.yaml`, `control_types.yaml`, `control_interfaces.yaml`,
  and `camera_profiles.yaml`.
- If you want to refresh the core profile files while preserving
  `camera_profiles.yaml`, run:
  `"$WS/src/swarm_control_core/scripts/swarm_core_seed_runtime_config.sh" --workspace "$WS" --overwrite-core-profiles`

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
export SWARM_CORE_AUDIT_CMD_VEL_MIN_PERIOD_S=2.0
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
"$SC/scripts/swarm_core_quickstart_step3.sh"
```

Terminal usage requirement:
- Keep each robot SSH terminal open while operating.
- Run the UI only in `CM-UI`.

Operator tip:
- Keep only one active UI tab/window connected to avoid unnecessary duplicate WebRTC/control sessions.

For maximum active-robot latency reduction in single-robot focus mode (at the cost of much slower fleet-tile updates and slower robot switching):

- the default Step 3 script already uses this single-robot-focus profile

Switch behavior (expected):

- Active robot switch triggers WebRTC main-stream handoff.
- Keep `SWARM_CORE_THUMB_ROBOTS_PER_TICK=1` for balanced fleet tile updates with passive side-tile probing.
- Use `SWARM_CORE_THUMB_ROBOTS_PER_TICK=0` only when you care about one active robot and minimal background load.

Balanced fleet profile:

```bash
"$SC/scripts/swarm_core_quickstart_step3.sh" --balanced-fleet
```

If rapid back-and-forth switching still feels sticky in `active_only` mode, use this switch-heavy profile:

```bash
"$SC/scripts/swarm_core_quickstart_step3.sh" --switch-heavy
```

Open in browser:
- `http://127.0.0.1:8080`

Video path:
- Main stream uses strict WebRTC-only transport by default.
- To keep all robot camera streams subscribed continuously (higher load), set `SWARM_CORE_IMAGE_SUBSCRIPTION_MODE=all`.
- Fleet thumbnails stay in side tiles and do not take over the main pane.

Optional private LAN bind:

```bash
"$SC/scripts/swarm_core_quickstart_step3.sh" --allow-lan-bind
```

### IF UI does not load or bind

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3).

Proceed to Step 4.

<a id="step-4"></a>
## Step 4: Fleet Readiness Check (Control Machine)

Run on control machine:

```bash
"$SC/scripts/swarm_core_quickstart_step4.sh"
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
"$SC/scripts/swarm_core_quickstart_step5.sh" --tool teleop
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
"$WS/src/swarm_control_core/scripts/swarm_core_check_install_dependencies.sh" \
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
colcon build --base-paths "$WS/src/swarm_control_core" --packages-select swarm_control_core --event-handlers console_direct+
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
ros2 run swarm_control_core save_camera_profile_core --robot "$ROBOT_NAME"
```

Then return to [Step 2](#step-2).

<a id="ref-3-1"></a>
## Fix Step 3.1: UI does not load or bind

Run on control machine:

```bash
"$WS/src/swarm_control_core/scripts/swarm_core_free_ui_port.sh" --port 8080
export ROS_DOMAIN_ID="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
"$WS/src/swarm_control_core/scripts/swarm_core_run_local_ui.sh"
```

If LAN access is needed, set:

```bash
export SWARM_CORE_ALLOW_LAN_BIND=1
export SWARM_CORE_BIND_HOST=0.0.0.0
```

Then return to [Step 3](#step-3).

<a id="ref-4-1"></a>
## Fix Step 4.1: Robots missing in UI/topics

Check domain and source consistency on control + robots:

```bash
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID (target=${SWARM_CORE_ROS_DOMAIN_ID:-17})"
env | rg -E '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION)=' || true
ros2 topic list | rg "/.*/heartbeat"
```

All machines must use the same domain id (default `17`) and sourced workspace.

If robot terminals show heartbeat publishing but control still has no heartbeat topics,
DDS traffic is being blocked (commonly by ufw state carried from proprietary setup).
Keep compat defaults and rerun [Step 2](#step-2) on robots + [Step 3](#step-3) on control.

If you previously forced firewall preservation, remove that override:

```bash
unset SWARM_CORE_COMPAT_STOP_UFW
```

If reset script prints `Unknown argument: --machine-role`, your robot/control checkout is stale.
Run on each machine:

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune
git switch main || git checkout -b main origin/main
git pull --ff-only origin main

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths "$WS/src/swarm_control_core" --packages-select swarm_control_core --event-handlers console_direct+
fi
source "$WS/install/setup.bash"
set -u || true
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
