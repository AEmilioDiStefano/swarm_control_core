# Setup Instructions: Software

This guide takes a control machine plus one or more freshly imaged Ubuntu
24.04 robot machines from first boot to a state that is ready for the live
local/LAN bringup in [QUICKSTART.md](./QUICKSTART.md).

When you finish this guide:

- `swarm_control_core` will be checked out in a ROS 2 workspace on every
  machine
- required dependencies, including ROS 2 Jazzy, will be installed as needed
- `swarm_control_core` will be built in the workspace on every machine
- runtime config will be seeded into `~/.config/swarm_control_core/`
- each robot will have a matching `robot_instances.yaml` entry
- the control machine will have synced robot entries for UI metadata and
  per-robot tuning
- GPIO access will be prepared on each robot
- each robot will have a saved camera profile
- you can continue with [QUICKSTART.md](./QUICKSTART.md) without doing any
  extra install/setup work first

## Assumptions

- each Raspberry Pi already has Ubuntu 24.04 written to its SD card
- Raspberry Pi Imager or equivalent has already applied SSH settings and Wi-Fi
  credentials
- the control machine and robots can reach the internet during initial install
- the control machine and robots will be on the same private LAN for runtime
- you can use `sudo` on every machine

## Terminal Layout

Use the same operator model as the quickstart:

- one control-machine terminal for setup and the later local FPV UI
- one dedicated SSH terminal per robot
- keep the robot SSH terminals open after setup so they can be reused for
  quickstart bringup

Suggested labels:

- `CM-SETUP`
- `R-<robot-a>`
- `R-<robot-b>`

## How This Guide Works

- every command block below is safe to rerun
- Step 1 is the same on the control machine and in every robot SSH terminal
- the guide defaults to `~/ros2_ws_dev`; if you intentionally want a different
  workspace, export `SWARM_CORE_WORKSPACE_ROOT=/path/to/your_ws` before Step 1
- if you close and reopen a terminal later, rerun Step 1 in the new shell

## 1. Universal Workspace Bootstrap

Run this once in the control-machine terminal and once in each dedicated robot
SSH terminal. Run the same block again any time you open a fresh shell or
reconnect to a robot.

This block:

- reuses an existing `swarm_control_core` checkout in the target workspace when
  one is already present
- otherwise installs `git` if needed, creates `~/ros2_ws_dev/src`, and clones
  `swarm_control_core`
- runs the idempotent setup bootstrap helper
- tells you whether bootstrap was already complete or which missing pieces it
  created
- exports `WS`, `WS_DEV`, `SC`, and `SWARM_CORE_WORKSPACE_ROOT`

```bash
SWARM_CORE_SETUP_WORKSPACE="${SWARM_CORE_WORKSPACE_ROOT:-${WS:-$HOME/ros2_ws_dev}}"
SWARM_CORE_SETUP_WORKSPACE="${SWARM_CORE_SETUP_WORKSPACE%/}"
SWARM_CORE_SETUP_HELPER="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_setup_bootstrap.sh" 2>/dev/null | sort | head -n1)"

if [[ -z "${SWARM_CORE_SETUP_HELPER:-}" ]]; then
  command -v git >/dev/null 2>&1 || {
    sudo apt-get update
    sudo apt-get install -y git
  }

  SWARM_CORE_SETUP_PKG="${SWARM_CORE_SETUP_WORKSPACE}/src/swarm_control_core"
  install -d "${SWARM_CORE_SETUP_WORKSPACE}/src"
  if [[ ! -d "${SWARM_CORE_SETUP_PKG}/.git" ]]; then
    git clone https://github.com/AEmilioDiStefano/swarm_control_core.git "$SWARM_CORE_SETUP_PKG"
  fi
  SWARM_CORE_SETUP_HELPER="${SWARM_CORE_SETUP_PKG}/scripts/swarm_core_setup_bootstrap.sh"
fi

eval "$("$SWARM_CORE_SETUP_HELPER" \
  --workspace "$SWARM_CORE_SETUP_WORKSPACE" \
  --emit-shell)"

unset SWARM_CORE_SETUP_WORKSPACE SWARM_CORE_SETUP_HELPER SWARM_CORE_SETUP_PKG
export SWARM_CORE_ROS_DOMAIN_ID="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
```

Expected result:

- `WS` points at the workspace that contains `src/swarm_control_core`
- `SC` points at `"$WS/src/swarm_control_core"`
- the helper prints either `Bootstrap already complete...` or a short list of
  the changes it just applied

## 2. Prepare the Control Machine

Run this in the control-machine terminal after Step 1:

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role control \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"

source "$SC/scripts/swarm_core_reset_env.sh" \
  --scope deep \
  --machine-role control \
  --compat-mode \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"
```

What this does:

- installs dependencies, including ROS 2 Jazzy if needed
- seeds runtime config into `~/.config/swarm_control_core/`
- builds `swarm_control_core`
- prepares the current terminal for the later quickstart UI flow

Expected success signals:

- dependency output ends with `All dependencies have been successfully installed.`
- bootstrap summary shows `BUILD_STATUS = completed`
- the shell still has `WS` and `SC` exported

## 3. Prepare Each Robot

SSH into each robot from the control machine and keep one dedicated terminal
open per robot:

```bash
ssh <robot_user>@<robot_host>.local
```

In each robot SSH terminal:

1. run Step 1
2. run the robot bootstrap block below
3. if the bootstrap says GPIO access is not active in the current session,
   open a new SSH session to that robot and rerun Step 1 there
4. in the robot terminal you plan to keep open for quickstart, run the reset
   block below

Robot bootstrap block:

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"
```

Robot reset block:

```bash
source "$SC/scripts/swarm_core_reset_env.sh" \
  --scope deep \
  --machine-role robot \
  --compat-mode \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"
```

Optional quick confirmation in the active robot terminal:

```bash
if [[ -e /dev/gpiomem && -r /dev/gpiomem && -w /dev/gpiomem ]]; then
  echo "[OK] GPIO access is active in this SSH session."
else
  echo "[INFO] GPIO access is not active in this SSH session yet."
  echo "[INFO] Open a new SSH session to this robot, rerun Step 1 there, then rerun the reset block above."
fi
```

At this point the robot terminal is in the same prepared state expected by the
quickstart.

## 4. Save a Camera Profile on Each Robot

Run this in each prepared robot SSH terminal:

```bash
export SWARM_CORE_ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core save_camera_profile_core --robot "$SWARM_CORE_ROBOT_NAME"
```

What to do here:

- choose the camera entry that robot should use
- confirm the saved profile lands in
  `~/.config/swarm_control_core/camera_profiles.yaml`

If you want the runtime robot name to be something other than the Linux
username, export `SWARM_CORE_ROBOT_NAME=<name>` before running the command
above, and keep using that same value later in the quickstart robot terminal.

If you want the robot to use one of the named entries already present in
`~/.config/swarm_control_core/robot_instances.yaml`, set
`SWARM_CORE_ROBOT_NAME` to that same entry key before saving the camera
profile and before launching the robot in quickstart.

If the camera chooser warns about probing behavior and you intentionally want
auto-fallback behavior, enable it in that shell with:

```bash
export SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1
```

## 5. Final Robot Profile Registration and Readiness Check

Run this in each prepared robot SSH terminal after the camera save step:

```bash
export SWARM_CORE_ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core configure_robot_profile_core \
  --workspace "$WS" \
  --robot "$SWARM_CORE_ROBOT_NAME"
```

What this command does:

- checks whether this robot already has an entry in
  `"$WS/src/swarm_control_core/config/robot_instances.yaml"`
- if the entry already exists, prints it and syncs it into the active runtime
  `robot_instances.yaml`
- if the entry does not exist yet, guides you through creating it interactively
  using the current core-supported `control_type` and `control_interface`
  options
- auto-fills `ssh_target` from the current Linux username and hostname
- checks whether this robot already has a camera profile and launches the
  camera chooser automatically if one is still missing
- finishes by printing a ready message when the robot is prepared for
  [QUICKSTART.md](./QUICKSTART.md)

### 5.1 Sync Robot Entries Back to the Control Machine

After Step 5 has been completed on every robot, run this in the
control-machine terminal:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core sync_robot_entries_core --workspace "$WS"
```

What this command does:

- prompts for the robot sources that should be synced back to the control
  machine
- accepts one source per line in either of these forms:
  - `robot_user@robot_host.local`
  - `robot_name=robot_user@robot_host.local`
- examples:
  - `robot1@legion1.local`
  - `my_robot=robot1@legion1.local`
- SSHes into each robot
- pulls that robot's active runtime `robot_instances.yaml`
- selects the matching robot entry automatically in the common case
- merges the pulled entry into the control-machine workspace baseline
  `robot_instances.yaml`
- repairs the control-machine runtime `robot_instances.yaml` if it was missing
  or stale

Use the `robot_name=ssh_target` form if you intentionally set
`SWARM_CORE_ROBOT_NAME` to something different from the robot's Linux username.

Step 5 on each robot now prints the exact sync source strings that this step
can accept.

## 6. Quick Verification Before the Live Session

Run this in each prepared robot SSH terminal:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

test -f "$HOME/.config/swarm_control_core/robot_instances.yaml" && echo "[OK] runtime profiles seeded"
test -f "$HOME/.config/swarm_control_core/camera_profiles.yaml" && echo "[OK] camera profiles file present"
ros2 pkg executables swarm_control_core | rg "_core$"
```

Run this in the control-machine terminal:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 pkg executables swarm_control_core | rg "_core$"
```

## 7. Handoff to QUICKSTART

After this guide, the machines are ready for the live local FPV/control flow in
[QUICKSTART.md](./QUICKSTART.md).

Recommended handoff:

- if you keep these prepared terminals open, continue with
  [QUICKSTART.md](./QUICKSTART.md) starting at Step 2 for the robot terminals,
  then Step 3 on the control machine
- if you open fresh terminals later, rerun Step 1 of this guide or Step 0 of
  [QUICKSTART.md](./QUICKSTART.md) so the new shells get the same workspace
  bootstrap and reset flow

## 8. Optional Robot Service Mode

Manual quickstart bringup is the recommended first run, but if you want a robot
service installed after the fresh setup succeeds, run this in that robot SSH
terminal:

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID" \
  --install-service
```

If you want the service enabled immediately, add `--enable-service-now`.

## 9. Troubleshooting Quick Checks

Robot-side quick checks:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-${USER:-$(id -un)}}"
ros2 node list
ros2 topic list | rg "/${ROBOT_NAME}/(cmd_vel|heartbeat|camera)"
ros2 run swarm_control_core save_camera_profile_core --robot "$ROBOT_NAME"
```

Control-side quick checks:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 topic list | rg "/.*/(heartbeat|camera/image_raw|cmd_vel)"
```

For the full live-session startup and expanded fix paths, use:

- [QUICKSTART.md](./QUICKSTART.md)
- [LOCAL_FPV_runbook.md](./LOCAL_FPV_runbook.md)
