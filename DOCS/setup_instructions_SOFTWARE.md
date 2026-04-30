# Setup Instructions: Software

This guide is the full software setup path for a control machine plus one or
more freshly imaged Ubuntu 24.04 robot machines. A robot is not considered
ready for the live local/LAN bringup in [QUICKSTART.md](./QUICKSTART.md) until
it has been registered/approved on the control machine and verified below.

When you finish this guide:

- `swarm_control_core` will be checked out in a ROS 2 workspace on every
  machine
- required dependencies, including ROS 2 Jazzy, will be installed as needed
- `swarm_control_core` will be built in the workspace on every machine
- runtime config will be seeded into `~/.config/swarm_control_core/`
- each robot will have a local `robot_instances.yaml` entry describing its own
  drive type, hardware interface, and SSH target
- the control machine will have registered/approved those robot entries for UI
  trust, metadata, and per-robot tuning
- GPIO access will be prepared on each robot
- each robot will have a saved camera profile
- the UI will only allow control of robots that are present in the trusted
  control-machine `robot_instances.yaml`
- you can continue with [QUICKSTART.md](./QUICKSTART.md) only after the
  registration/approval step confirms the control machine can recognize the
  robots as trusted

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

## 0. SSH into your Raspberry Pi(s)

SSH into each robot from the control machine and keep one dedicated terminal
open per robot:

### CONTROL MACHINE:

```bash
ssh <robot_user>@<robot_host>.local
```

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

### CONTROL MACHINE:

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

### ROBOT(S):

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

### CONTROL MACHINE:

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

- dependency output ends with `All dependencies are installed and up to date.`
- bootstrap summary shows `BUILD_STATUS = completed`
- the shell still has `WS` and `SC` exported

## 3. Prepare Each Robot

In each robot SSH terminal:

1. run Step 1
2. run the robot bootstrap block below
3. if the bootstrap says GPIO access is not active in the current session,
   open a new SSH session to that robot and rerun Step 1 there
4. in the robot terminal you plan to keep open for quickstart, run the reset
   block below

Robot bootstrap block:

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"
```

Robot reset block:

### ROBOT(S):

```bash
source "$SC/scripts/swarm_core_reset_env.sh" \
  --scope deep \
  --machine-role robot \
  --compat-mode \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"

export SWARM_CORE_ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"
export ROBOT_NAME="${ROBOT_NAME:-$SWARM_CORE_ROBOT_NAME}"
```

Optional quick confirmation in the active robot terminal:

### ROBOT(S):

```bash
if [[ -e /dev/gpiomem && -r /dev/gpiomem && -w /dev/gpiomem ]]; then
  echo "[OK] GPIO access is active in this SSH session."
else
  echo "[INFO] GPIO access is not active in this SSH session yet."
  echo "[INFO] Open a new SSH session to this robot, rerun Step 1 there, then rerun the reset block above."
fi
```

At this point the robot terminal has the shell/workspace environment expected
by the later quickstart, but the robot has not been added or approved for
control yet.

## 4. Add or Update the Robot's Local Profile

Run this in each prepared robot SSH terminal:

### ROBOT(S):

```bash
export SWARM_CORE_ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"
export ROBOT_NAME="${ROBOT_NAME:-$SWARM_CORE_ROBOT_NAME}"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core add_robot_core \
  --workspace "$WS" \
  --name "$ROBOT_NAME"
```

What to do here:

- choose the robot `control_type` and `control_interface` if this robot is not
  already in the canonical `robot_instances.yaml`
- choose the camera entry that robot should use if no generated camera profile
  exists yet
- confirm generated camera data lands in
  `~/.config/swarm_control_core/camera_profiles.yaml`

If you want the runtime robot name to be something other than the Linux
username, export `SWARM_CORE_ROBOT_NAME=<name>` before running the command
above, and keep using that same value later in the quickstart robot terminal.
`ROBOT_NAME` is a convenience alias for manual diagnostic commands in the
current shell.

If you already know the selected hardware profile, pass it explicitly. Example
for the four-channel dual-L298N robot4 profile:

### ROBOT(S):

```bash
ros2 run swarm_control_core add_robot_core \
  --workspace "$WS" \
  --name "$ROBOT_NAME" \
  --control-type diff_drive \
  --control-interface dual_l298n_diff
```

For a mecanum robot using two L298N boards, use:

### ROBOT(S):

```bash
ros2 run swarm_control_core add_robot_core \
  --workspace "$WS" \
  --name "$ROBOT_NAME" \
  --control-type mecanum_drive \
  --control-interface dual_l298n_mecanum
```

For new hardware profiles that are not already listed, use the metadata-driven
process in [`control_interface_profiles.md`](./control_interface_profiles.md)
before running `add_robot_core`.

This command treats `robot_instances.yaml` as the canonical source of robot
identity on the robot, syncs that robot's runtime `robot_instances.yaml`,
refreshes runtime `control_types.yaml` and `control_interfaces.yaml`, preserves
generated camera profiles, and prints the selected wiring document when
available.

This is a local robot-profile step only. The robot is not approved for FPV UI
drive/autonomy control until Step 5.1 registers it on the control machine.

Security note:

- A robot can be visible on the ROS network before the control machine has
  registered and approved its trusted registry entry.
- The FPV UI shows those unknown robots read-only for diagnostics/video, but it
  blocks drive/autonomy commands until Step 5.1 registers the robot on the
  control machine.

If the camera chooser warns about probing behavior and you intentionally want
auto-fallback behavior, enable it in that shell with:

### ROBOT(S):

```bash
export SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1
```

### 4.1 Optional Wheel Direction Test

Run this after Step 4 when the robot uses GPIO motor control and before the
live quickstart bringup. This test drives the GPIO hardware directly, so keep
the robot on blocks, wheels/tracks clear, and do not run robot bringup at the
same time.

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_wheel_test.sh" --robot "$ROBOT_NAME"
```

The terminal app accepts movement keys and prints the expected wheel directions.
Example for the forward command:

```text
Command:
FORWARD

Expected:
FL = FORWARD
BL = FORWARD
FR = FORWARD
BR = FORWARD
```

Movement keys match terminal teleop and the Swarm Control UI:

- `8/2`: forward/backward
- `4/6`: rotate left/right, or strafe left/right when strafe mode is enabled
- `7/9/1/3`: arc diagonals in normal mode, strafe diagonals in strafe mode
- arrow keys: same movement behavior as `8/2/4/6`
- `0`: toggle strafe mode for mecanum/omni robots
- `space`, `s`, or `5`: stop

Calibration keys:

- `v`: choose FL/BL/FR/BR and toggle wheel inversion when a wheel spins backward
- `c`: swap two wheel channel mappings when the wrong wheel moves
- `P`: print pending GPIO overrides
- `S`: save pending GPIO overrides into `robot_instances.yaml`

Saved overrides are robot-specific. They are useful for wiring differences on
one physical robot without changing the reusable hardware profile for every
robot of that type.

## 5. Local Robot Readiness Check

Run this in each prepared robot SSH terminal after Step 4:

### ROBOT(S):

```bash
export SWARM_CORE_ROBOT_NAME="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"
export ROBOT_NAME="${ROBOT_NAME:-$SWARM_CORE_ROBOT_NAME}"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core robot_doctor_core \
  --workspace "$WS" \
  --robot "$ROBOT_NAME"
```

What this command does:

- verifies the canonical source robot entry exists
- verifies the selected `control_interface` exists in source profiles
- checks runtime `robot_instances.yaml`
- checks runtime `control_types.yaml` and `control_interfaces.yaml` for stale
  copies
- reports whether a generated camera profile exists
- prints control-machine registration/approval hints

If the doctor reports stale runtime core profiles, repair them with:

### ROBOT(S):

```bash
ros2 run swarm_control_core robot_doctor_core \
  --workspace "$WS" \
  --robot "$ROBOT_NAME" \
  --repair
```

### 5.1 Register and Approve New Robots on the Control Machine

After Step 5 has been completed on every robot, register and approve each new
robot from the control-machine terminal. This is the trust gate that allows the
FPV UI to control the robot.

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core sync_robot_entries_core --workspace "$WS"
```

When prompted, enter one source per line, then press Enter on a blank line when
finished.

Accepted source forms:

- `robot_user@robot_host.local`
- `robot_name=robot_user@robot_host.local`

Examples:

- `robot1@legion1.local`
- `robot4=robot4@legion4.local`
- `robot5=robot5@legion5.local`

Non-interactive form for known robots:

### CONTROL MACHINE:

```bash
ros2 run swarm_control_core sync_robot_entries_core --workspace "$WS" \
  --source robot4=robot4@legion4.local \
  --source robot5=robot5@legion5.local
```

What this approval command does:

- prompts for the robot sources that should be synced back to the control
  machine
- SSHes into each robot
- pulls that robot's active runtime `robot_instances.yaml`
- selects the matching robot entry automatically in the common case
- merges the pulled entry into the control-machine workspace baseline
  `robot_instances.yaml`
- repairs the control-machine runtime `robot_instances.yaml` if it was missing
  or stale

Use the `robot_name=ssh_target` form if you intentionally set
`SWARM_CORE_ROBOT_NAME` to something different from the robot's Linux username.

Security behavior:

- Newly discovered robots are allowed to publish camera/video and diagnostics.
- Drive and autonomy commands are blocked until this registration step approves
  the robot into the control-machine `robot_instances.yaml`.
- After approving new robots, restart the local FPV UI so it reloads the trusted
  robot registry.
- Do not use `SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL=1` except for short,
  trusted-lab debugging sessions.

Only after this step should a new robot be considered added/approved for
control-machine FPV UI control. Step 5 on each robot prints the exact source
strings that this step can accept.

## 6. Quick Verification Before the Live Session

First verify each approved robot from the control-machine terminal. Replace the
example robot names with the robots you just registered:

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot robot4
ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot robot5
```

The doctor should report `source_entry: present` and `robot_entry: current` for
the control-machine runtime `robot_instances.yaml`. If either robot is missing
or stale here, rerun Step 5.1 before opening the FPV UI.

Then run this in each prepared robot SSH terminal:

### ROBOT(S):

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

### CONTROL MACHINE:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 pkg executables swarm_control_core | rg "_core$"
```

## 7. Handoff to QUICKSTART

After Step 5.1 registration/approval and Step 6 verification succeed, the
machines are ready for the live local FPV/control flow in
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

### ROBOT(S):

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

### ROBOT(S):

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

### CONTROL MACHINE:

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
