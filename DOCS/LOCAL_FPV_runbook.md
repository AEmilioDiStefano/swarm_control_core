# Local FPV Runbook (DRP-First)

This runbook is for local/LAN operation of `swarm_control_core`. It is the
raw, low-level companion to [QUICKSTART.md](./QUICKSTART.md): the quickstart
wraps these stages in `swarmc step*` commands, while this runbook runs the
underlying launch files and tools directly for debugging and development.

# Direct Run Path

## Step 0: Bootstrap Workspace Shell

Load the workspace environment into this shell. This exports `WS`, `WS_DEV`,
and `SC`, and sources the ROS + workspace overlays for the raw commands
below. If the launcher is missing, the command prints a failure message and
leaves this shell open; install it via the first-contact bootstrap in
[ADD_robot_pi.md](./ADD_robot_pi.md) Step 0.

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

## Step 4: Start Control UI

### CONTROL MACHINE:

```bash
ros2 launch swarm_control_core swarm_fpv_ui.launch.py ros_domain_id:="$ROS_DOMAIN_ID"
```

Open:

- `http://127.0.0.1:8080` (default local-only)

### IF UI opens but robots are missing

Go to [Fix Step 4.1](#ref-4-1), then return to [Step 4](#step-4-start-control-ui).

### IF you need private LAN browser access

Go to [Alternative Step 4.2](#ref-4-2), then return to [Step 4](#step-4-start-control-ui).

## Step 5: Optional Terminal Control Smoke Test

### CONTROL MACHINE:

```bash
ros2 run swarm_control_core swarm_teleop_core
```

### IF terminal nodes fail to discover robots

Go to [Fix Step 5.1](#ref-5-1), then return to [Step 5](#step-5-optional-terminal-control-smoke-test).

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

### CONTROL MACHINE:

```bash
export SWARM_CORE_ALLOW_LAN_BIND=1
export SWARM_CORE_BIND_HOST=0.0.0.0
ros2 launch swarm_control_core swarm_fpv_ui.launch.py ros_domain_id:="$ROS_DOMAIN_ID"
```

Then return to [Step 4](#step-4-start-control-ui).

<a id="ref-5-1"></a>
## Fix Step 5.1: Terminal Nodes Cannot Discover Robots

### CONTROL MACHINE:

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 topic list | rg "/.*/cmd_vel"
ros2 action list | rg "/.*/execute_playbook"
```

If actions are missing, verify `unit_executor_action_server_core` is running from Step 3.

Then return to [Step 5](#step-5-optional-terminal-control-smoke-test).

<a id="ref-5-2"></a>
## Optional: Service-Mode Switch On Shared Robots

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_switch_robot_mode.sh" status
"$SC/scripts/swarm_core_switch_robot_mode.sh" activate --install-if-missing
```

Then return to the step you were running.
