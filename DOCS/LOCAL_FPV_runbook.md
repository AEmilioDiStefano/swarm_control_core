# Local FPV Runbook (DRP-First)

This runbook is for local/LAN operation of `swarm_control_core`.

Workspace bootstrap (run once per terminal before DRP steps):

```bash
# If your current directory is the workspace root (<workspace>/):
source "./src/swarm_control_core/scripts/swarm_com_workspace_env.sh"

# If your current directory is the package root (<workspace>/src/swarm_control_core/):
# source "./scripts/swarm_com_workspace_env.sh"
```

## DRP Steps

### 1. Install Dependencies (Control + Robots)

Run this on each machine:

```bash
"$WS_DEV/src/swarm_control_core/scripts/swarm_com_check_install_dependencies.sh" \
  --machine-role control
```

On robot machines, replace `control` with `robot`.

### IF dependency installation fails
Go to [5.1](#51-dependency-install-fails).

### 2. Build the Package

Run on each machine where nodes will run:

```bash
cd "$WS_DEV"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --packages-select swarm_control_core
source "$WS_DEV/install/setup.bash"
set -u || true
```

### IF build fails
Go to [5.2](#52-build-fails).

### 3. Start Robot Bringup (each robot)

Run on each robot:

```bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-17}"
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
"$WS_DEV/src/swarm_control_core/scripts/swarm_com_terminate_existing_robot_processes.sh"

ros2 launch swarm_control_core swarm_bringup.launch.py \
  robot_name:="$ROBOT_NAME" \
  ros_domain_id:="$ROS_DOMAIN_ID" \
  use_camera:=true \
  camera_pipeline:=adapter
```

### IF camera or motion nodes do not come up
Go to [5.3](#53-robot-nodes-or-camera-not-running).

### 4. Start Control UI

Run on the control machine:

```bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-17}"
ros2 launch swarm_control_core swarm_fpv_ui.launch.py ros_domain_id:="$ROS_DOMAIN_ID"
```

Open:

- `http://127.0.0.1:8080` (default local-only)

Optional private LAN bind:

```bash
export SWARM_COM_ALLOW_LAN_BIND=1
export SWARM_COM_BIND_HOST=0.0.0.0
ros2 launch swarm_control_core swarm_fpv_ui.launch.py ros_domain_id:="$ROS_DOMAIN_ID"
```

### IF UI opens but robots are missing
Go to [5.4](#54-ui-starts-but-no-robots-appear).

### 5. Optional Terminal Control Nodes

Terminal teleop:

```bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-17}"
ros2 run swarm_control_core swarm_teleop_com
```

Terminal orchestrator (simple playbooks):

```bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-17}"
ros2 run swarm_control_core terminal_orchestrator_com
```

### IF terminal nodes fail to discover robots
Go to [5.5](#55-terminal-nodes-cannot-discover-robots).

## Alternative/Debug/Fix

### 5.1 Dependency install fails

Check apt sources and ROS install:

```bash
echo "$ROS_DISTRO"
ls /opt/ros
sudo apt-get update
```

Re-run Step 1.

### 5.2 Build fails

Run clean rebuild:

```bash
cd "$WS_DEV"
rm -rf build/swarm_control_core install/swarm_control_core log/latest_build/swarm_control_core
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --packages-select swarm_control_core --event-handlers console_direct+
source "$WS_DEV/install/setup.bash"
set -u || true
```

### 5.3 Robot nodes or camera not running

On the robot:

```bash
source "$WS_DEV/install/setup.bash"
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
ros2 node list
ros2 topic list | rg "/${ROBOT_NAME}/(cmd_vel|heartbeat|camera)"
```

If camera topic is missing, verify camera profile and device path:

```bash
ROBOT_NAME="${ROBOT_NAME:-$(id -un)}"
ros2 run swarm_control_core save_camera_profile_com --robot "$ROBOT_NAME"
```

### 5.4 UI starts but no robots appear

On control machine:

```bash
source "$WS_DEV/install/setup.bash"
ros2 topic list | rg "/.*/(heartbeat|camera/image_raw|cmd_vel)"
```

If empty, verify robot and control are on same LAN/domain ID and both sourced with the same workspace.

### 5.5 Terminal nodes cannot discover robots

Confirm endpoints:

```bash
source "$WS_DEV/install/setup.bash"
ros2 topic list | rg "/.*/cmd_vel"
ros2 action list | rg "/.*/execute_playbook"
```

If actions are missing, verify `unit_executor_action_server_com` is running from Step 3.

### 5.6 Service-mode switch on shared robots

If robots are shared between multiple stacks, use mode switching on the robot:

```bash
"$WS_DEV/src/swarm_control_core/scripts/swarm_com_switch_robot_mode.sh" status
"$WS_DEV/src/swarm_control_core/scripts/swarm_com_switch_robot_mode.sh" activate --install-if-missing
```
