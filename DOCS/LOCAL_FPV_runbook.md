# Local FPV Runbook (DRP-First)

This runbook is for control-machine-local browser operation of
`swarm_control_core` over a trusted private ROS LAN. It is the
raw, low-level companion to [QUICKSTART.md](./QUICKSTART.md): the quickstart
wraps these stages in `swarmc step*` commands, while this runbook runs the
underlying launch files and tools directly for debugging and development.

Core is experimental supervised-lab software, not a safety-rated controller.
Before bringup, provide an operator-reachable physical motor cutoff, raise or
secure wheels/tracks for first motion, use a spotter, and keep every other
command/autonomy surface closed.

Runtime safeguards are layered: browser drive input is strict and finite,
invalid input or disconnect stops retained targets owned by that browser
session, the browser bridge uses a bounded monotonic drive deadman, and the
robot motor driver has an independent watchdog/hard-stop path. Reversing motor
channels are commanded to zero before their direction pins change. These
behaviors are software-tested only; verify them with wheels clear and do not
use them in place of the physical cutoff.

# Direct Run Path

## Step 0: Bootstrap Workspace Shell

Load the workspace environment into this shell. This exports `WS`, `WS_DEV`,
and `SC`, and sources the ROS + workspace overlays for the raw commands
below. If the launcher is missing, the command prints a failure message and
leaves this shell open; install it via Step 0 of
[NOBLE_FRESH_INSTALL.md](./NOBLE_FRESH_INSTALL.md).

### CONTROL MACHINE / ROBOT(S):

```bash
eval "$(~/.local/bin/swarmc env)"
```

## Step 1: Install Dependencies

This gate is idempotent: it checks what is already installed and installs only
what is missing or outdated, so it is safe to re-run at any time.

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role control
```

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role robot
```

### IF dependency installation fails

Go to [Fix Step 1.1](#ref-1-1), then return to [Step 1](#step-1-install-dependencies).

## Step 2: Build The Package

### CONTROL MACHINE / ROBOT(S):

```bash
~/.local/bin/swarmc rebuild
eval "$(~/.local/bin/swarmc env)"
```

The second line reloads the freshly built overlay into this shell.

### IF build fails

Go to [Fix Step 2.1](#ref-2-1), then return to [Step 2](#step-2-build-the-package).

## Step 3: Start Robot Bringup

### ROBOT(S):

```bash
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
"$SC/scripts/swarm_core_terminate_existing_robot_processes.sh"
ros2 launch swarm_control_core swarm_bringup.launch.py robot_name:="$ROBOT_NAME" ros_domain_id:="$ROS_DOMAIN_ID" use_camera:=true camera_pipeline:=adapter
```

### IF camera or motion nodes do not come up

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3-start-robot-bringup).

Before continuing, verify that the intended real hardware profile resolved and
that logs contain no mock-hardware warning. Nodes/topics alone do not prove
actuator readiness.

## Step 4: Start Control UI

### CONTROL MACHINE:

```bash
ros2 launch swarm_control_core swarm_fpv_ui.launch.py ros_domain_id:="$ROS_DOMAIN_ID"
```

Open:

- `http://127.0.0.1:8080` (default local-only)

### IF UI opens but robots are missing

Go to [Fix Step 4.1](#ref-4-1), then return to [Step 4](#step-4-start-control-ui).

### IF you need private-LAN browser access

Go to [Alternative Step 4.2](#ref-4-2), then return to [Step 4](#step-4-start-control-ui).

## Step 5: Browser Control Smoke Test

In the loopback UI, select the intended robot. With the robot raised/secured,
the spotter ready, and the physical cutoff reachable, apply the smallest input
and release it. Confirm only that robot responds and the command returns to
zero. A malformed drive message is rejected rather than coerced, and closing
the controlling tab requests zero for the targets that tab owns; the
robot-side watchdog remains the next software backstop. The terminal teleop
tool is not a current acceptance path; see
[Fix Step 5.1](#ref-5-1).

# Alternative/Debug/Fix Reference

<a id="ref-1-1"></a>
## Fix Step 1.1: Dependency Install Fails

### CONTROL MACHINE / ROBOT(S):

```bash
echo "$ROS_DISTRO"
ls /opt/ros
sudo apt-get update
```

Then return to [Step 1](#step-1-install-dependencies).

<a id="ref-2-1"></a>
## Fix Step 2.1: Build Fails

### CONTROL MACHINE / ROBOT(S):

```bash
~/.local/bin/swarmc rebuild --clean
eval "$(~/.local/bin/swarmc env)"
```

Then return to [Step 2](#step-2-build-the-package).

<a id="ref-3-1"></a>
## Fix Step 3.1: Robot Nodes Or Camera Not Running

### ROBOT(S):

```bash
eval "$(~/.local/bin/swarmc env)"
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
ros2 node list
ros2 topic list | rg "/${ROBOT_NAME}/(cmd_vel|heartbeat|camera)"
```

### ROBOT(S):

```bash
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
ros2 run swarm_control_core save_camera_profile_core --robot "$ROBOT_NAME"
```

Then return to [Step 3](#step-3-start-robot-bringup).

<a id="ref-4-1"></a>
## Fix Step 4.1: UI Starts But No Robots Appear

### CONTROL MACHINE:

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 topic list | rg "/.*/(heartbeat|camera/image_raw|cmd_vel)"
```

If empty, verify robot and control are on same LAN/domain ID and both sourced with the same workspace.

Then return to [Step 4](#step-4-start-control-ui).

<a id="ref-4-2"></a>
## Alternative Step 4.2: Private LAN Browser Access

Standalone Core's browser endpoint is currently loopback-only. Setting a LAN
bind does not satisfy the non-loopback authentication guard, so there is no
supported standalone command for this alternative. Use an appropriately
authenticated distribution for browser exposure; keep ROS itself on a trusted
private LAN.

Then return to [Step 4](#step-4-start-control-ui).

<a id="ref-5-1"></a>
## Fix Step 5.1: Terminal Teleop Known Limitation

The terminal entry point exists, but its active input loop does not reliably
service republish, discovery, offline-watchdog, and override timers. Do not use
it as a readiness or stop-safety test until timer-liveness behavioral tests
pass. The commands below are diagnostics only.

### CONTROL MACHINE:

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 topic list | rg "/.*/cmd_vel"
ros2 action list | rg "/.*/execute_playbook" || \
  ros2 topic list | rg "/.*/execute_playbook_(cmd|result)"
```

On a clean Core-only install, the optional action interface package is absent
and the `_cmd`/`_result` topic pair is the expected compatibility interface.
If both forms are missing, verify `unit_executor_action_server_core` is
running from Step 3.

Then return to [Step 5](#step-5-browser-control-smoke-test).

<a id="ref-5-2"></a>
## Optional: Service-Mode Switch On Shared Robots

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_switch_robot_mode.sh" status
"$SC/scripts/swarm_core_switch_robot_mode.sh" activate --install-if-missing
```

Then return to the step you were running.
