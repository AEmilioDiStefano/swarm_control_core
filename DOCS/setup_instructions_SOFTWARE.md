# Setup Instructions: Software

This guide is the full software setup path for a control machine plus one or
more freshly imaged Ubuntu 24.04 robot machines. A robot is not considered
ready for live FPV/control until it has a local robot profile, has been
registered/approved on the control machine, and has passed the verification
steps below.

This guide follows the DRP guide format:

1. **Direct Run Path**: the normal setup path, in order.
2. **Alternative/Debug/Fix Reference**: all conditional branches live at the
   bottom and are referenced from the run path with `### IF...` callouts.

For the guide-authoring standard, see
[`DRP_guide_format.md`](./DRP_guide_format.md).

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

- every command block in the Direct Run Path is safe to rerun
- Step 1 is the same on the control machine and in every robot SSH terminal
- the guide defaults to `~/ros2_ws_dev`; if you intentionally want a different
  workspace, export `SWARM_CORE_WORKSPACE_ROOT=/path/to/your_ws` before Step 1
- if a step fails or your situation differs from the normal path, follow the
  nearest `### IF...` callout to the reference section, then return to the step
  that sent you there

# Direct Run Path

<a id="setup-step-0"></a>
## Step 0: SSH Into Each Robot

SSH into each robot from the control machine and keep one dedicated terminal
open per robot.

### CONTROL MACHINE:

```bash
ssh <robot_user>@<robot_host>.local
```

### IF SSH fails or hostname resolution fails

Go to [Fix Step 0.1](#setup-ref-0-1), then return to [Step 0](#setup-step-0).

<a id="setup-step-1"></a>
## Step 1: Universal Workspace Bootstrap

Run this once in the control-machine terminal and once in each dedicated robot
SSH terminal. Run the same block again any time you open a fresh shell or
reconnect to a robot.

This block:

- reuses an existing `swarm_control_core` checkout in the target workspace when
  one is already present
- otherwise installs `git` if needed, creates `~/ros2_ws_dev/src`, and clones
  `swarm_control_core`
- runs the idempotent setup bootstrap helper
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

### IF bootstrap cannot find the helper, clone, or export `WS`/`SC`

Go to [Fix Step 1.1](#setup-ref-1-1), then return to [Step 1](#setup-step-1).

<a id="setup-step-2"></a>
## Step 2: Prepare the Control Machine

Run this in the control-machine terminal after Step 1.

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

Expected success signals:

- dependency output ends with `All dependencies are installed and up to date.`
- bootstrap summary shows `BUILD_STATUS = completed`
- the shell still has `WS` and `SC` exported

### IF dependency installation, build, or source setup fails

Go to [Fix Step 2.1](#setup-ref-2-1), then return to [Step 2](#setup-step-2).

<a id="setup-step-3"></a>
## Step 3: Prepare Each Robot

Run this in each robot SSH terminal after Step 1.

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID"
```

Then prepare the active robot shell that you will keep open for quickstart.

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

At this point the robot terminal has the shell/workspace environment expected
by the later quickstart, but the robot has not been added or approved for
control yet.

### IF GPIO access is not active in the current SSH session

Go to [Fix Step 3.1](#setup-ref-3-1), then return to [Step 3](#setup-step-3).

### IF dependency installation, build, or robot preparation fails

Go to [Fix Step 3.2](#setup-ref-3-2), then return to [Step 3](#setup-step-3).

<a id="setup-step-4"></a>
## Step 4: Add or Update the Robot's Local Profile

Run this in each prepared robot SSH terminal.

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
- copy the printed control-machine registration source, such as
  `robot4=robot4@legion4.local`, for Step 6
- keep robot setup runtime-local by default; this step should not dirty the
  robot's git checkout

Expected success output includes:

```text
[OK] Local robot profile is prepared on this robot.
[NEXT] Register/approve this robot on the control machine with sync_robot_entries_core before expecting FPV UI drive/autonomy control.
```

This is a local robot-profile step only. The robot is not approved for FPV UI
drive/autonomy control until Step 6 registers it on the control machine.

### IF you need a non-default robot name, known hardware profile, or new hardware profile

Go to [Alternative Step 4.1](#setup-ref-4-1), then return to [Step 4](#setup-step-4).

### IF camera probing needs manual fallback

Go to [Fix Step 4.2](#setup-ref-4-2), then return to [Step 4](#setup-step-4).

<a id="setup-step-5"></a>
## Step 5: Check Local Robot Readiness

Run this in each prepared robot SSH terminal after Step 4.

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

Expected success signals:

- `robot_entry_source: source_baseline` for pre-programmed robots, or
  `robot_entry_source: runtime` for robots added locally through the wizard
- `source_control_interface: present`
- `robot_entry: current`
- `control_types.yaml: current`
- `control_interfaces.yaml: current`
- a `control_machine_sync` block that lists the source strings for Step 6

### IF the doctor reports stale runtime profiles or missing entries

Go to [Fix Step 5.1](#setup-ref-5-1), then return to [Step 5](#setup-step-5).

### IF you want to test wheel direction/order before live quickstart

Go to [Optional: Wheel Direction Test](#setup-ref-optional-wheel-test), then
return to [Step 5](#setup-step-5).

<a id="setup-step-6"></a>
## Step 6: Register and Approve Robots on the Control Machine

This step is required. It is the trust gate that allows the FPV UI to control
new robots. Do not start the FPV UI until this step succeeds.

Do not expect the robot SSH terminals to print the final Quickstart-ready
message. The robot terminals only prove that each robot has a valid local
profile. The final readiness message appears in the control-machine terminal
after this registration/approval command succeeds.

Run this in the control-machine terminal. Use one `--source` per robot. Replace
the examples with the exact source strings printed by Step 4 or Step 5.
This updates the control machine's runtime trust registry by default; it does
not modify the source-tree `config/robot_instances.yaml` unless you explicitly
add `--update-source-baseline`.

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core sync_robot_entries_core --workspace "$WS" \
  --source robot4=robot4@legion4.local \
  --source robot5=robot5@legion5.local
```

Expected success output ends with:

```text
[OK] Control-machine robot registration/approval complete.
[OK] Registered/approved robots are ready for QUICKSTART handoff.
[NEXT] Restart the FPV UI so it reloads the trusted robot registry before driving.
```

Only after this step should a new robot be considered added/approved for
control-machine FPV UI control.

### IF you prefer interactive entry or the sync command fails

Go to [Fix Step 6.1](#setup-ref-6-1), then return to [Step 6](#setup-step-6).

<a id="setup-step-7"></a>
## Step 7: Verify Control-Machine Recognition

Run this in the control-machine terminal. Replace the example robot names with
the robots you just registered.

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

Expected success signals for each robot:

- `source_entry: present` for pre-programmed robots, or
  `robot_entry_source: runtime` for robots approved from runtime registration
- `robot_entry: current`
- the selected `control_interface` matches the robot hardware

### IF either robot is missing, stale, or still read-only in the UI later

Go to [Fix Step 7.1](#setup-ref-7-1), then return to [Step 7](#setup-step-7).

<a id="setup-step-8"></a>
## Step 8: Final Quick Verification

Run this in each prepared robot SSH terminal.

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

Run this in the control-machine terminal.

### CONTROL MACHINE:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 pkg executables swarm_control_core | rg "_core$"
```

After Step 6 registration/approval and Step 7 verification succeed, the
machines are ready for the live local FPV/control flow in
[QUICKSTART.md](./QUICKSTART.md).

Recommended handoff:

- if you keep these prepared terminals open, continue with
  [QUICKSTART.md](./QUICKSTART.md) starting at Step 2 for the robot terminals,
  then Step 3 on the control machine
- if you open fresh terminals later, rerun Step 1 of this guide or Step 0 of
  [QUICKSTART.md](./QUICKSTART.md) so the new shells get the same workspace
  bootstrap and reset flow

### IF the verification commands fail

Go to [Fix Step 8.1](#setup-ref-8-1), then return to [Step 8](#setup-step-8).

### IF you want robot service mode after manual setup succeeds

Go to [Optional: Robot Service Mode](#setup-ref-optional-service-mode).

# Alternative/Debug/Fix Reference

<a id="setup-ref-0-1"></a>
## Fix Step 0.1: SSH or Hostname Resolution Fails

Run this on the control machine to confirm the robot hostname or IP is reachable.

### CONTROL MACHINE:

```bash
ping -c 2 <robot_host>.local || true
ssh <robot_user>@<robot_ip_or_hostname>
```

If `.local` does not resolve, use the robot IP address for SSH and for Step 6
sources, for example `robot4=robot4@192.168.1.44`.

Return to [Step 0](#setup-step-0).

<a id="setup-ref-1-1"></a>
## Fix Step 1.1: Workspace Bootstrap Fails

Run this in the affected terminal.

### CONTROL MACHINE:

```bash
command -v git || sudo apt-get install -y git
mkdir -p "$HOME/ros2_ws_dev/src"
cd "$HOME/ros2_ws_dev/src"
test -d swarm_control_core/.git || git clone https://github.com/AEmilioDiStefano/swarm_control_core.git
cd "$HOME/ros2_ws_dev"
export WS="$HOME/ros2_ws_dev"
export SC="$WS/src/swarm_control_core"
```

### ROBOT(S):

```bash
command -v git || sudo apt-get install -y git
mkdir -p "$HOME/ros2_ws_dev/src"
cd "$HOME/ros2_ws_dev/src"
test -d swarm_control_core/.git || git clone https://github.com/AEmilioDiStefano/swarm_control_core.git
cd "$HOME/ros2_ws_dev"
export WS="$HOME/ros2_ws_dev"
export SC="$WS/src/swarm_control_core"
```

Return to [Step 1](#setup-step-1).

<a id="setup-ref-2-1"></a>
## Fix Step 2.1: Control Bootstrap or Build Fails

Run this in the control-machine terminal.

### CONTROL MACHINE:

```bash
sudo apt-get update
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role control
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --base-paths "$WS/src/swarm_control_core" --packages-select swarm_control_core --event-handlers console_direct+
source "$WS/install/setup.bash"
set -u || true
```

Return to [Step 2](#setup-step-2).

<a id="setup-ref-3-1"></a>
## Fix Step 3.1: GPIO Access Is Not Active

Open a new SSH session to that robot, rerun Step 1 there, then rerun the Step 3
reset block. Confirm access in the active robot terminal.

### ROBOT(S):

```bash
if [[ -e /dev/gpiomem && -r /dev/gpiomem && -w /dev/gpiomem ]]; then
  echo "[OK] GPIO access is active in this SSH session."
else
  echo "[INFO] GPIO access is not active in this SSH session yet."
  echo "[INFO] Open a new SSH session to this robot and rerun Step 1 + Step 3."
fi
```

Return to [Step 3](#setup-step-3).

<a id="setup-ref-3-2"></a>
## Fix Step 3.2: Robot Bootstrap or Build Fails

Run this in the affected robot SSH terminal.

### ROBOT(S):

```bash
sudo apt-get update
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role robot
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --base-paths "$WS/src/swarm_control_core" --packages-select swarm_control_core --event-handlers console_direct+
source "$WS/install/setup.bash"
set -u || true
```

Return to [Step 3](#setup-step-3).

<a id="setup-ref-4-1"></a>
## Alternative Step 4.1: Non-Default Names or Known Hardware Profiles

If you want the runtime robot name to be something other than the Linux
username, export `SWARM_CORE_ROBOT_NAME=<name>` before running Step 4, and keep
using that same value later in quickstart robot terminals.

For the four-channel dual-L298N robot4 profile, run this on the robot.

### ROBOT(S):

```bash
ros2 run swarm_control_core add_robot_core \
  --workspace "$WS" \
  --name "$ROBOT_NAME" \
  --control-type diff_drive \
  --control-interface dual_l298n_diff
```

For a mecanum robot using two L298N boards, run this on the robot.

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

Return to [Step 4](#setup-step-4).

<a id="setup-ref-4-2"></a>
## Fix Step 4.2: Camera Probing Needs Manual Fallback

If the camera chooser warns about probing behavior and you intentionally want
auto-fallback behavior, enable it in that robot shell.

### ROBOT(S):

```bash
export SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1
```

Return to [Step 4](#setup-step-4).

<a id="setup-ref-5-1"></a>
## Fix Step 5.1: Robot Doctor Reports Stale Runtime Profiles

Repair the local robot runtime profile files.

### ROBOT(S):

```bash
ros2 run swarm_control_core robot_doctor_core \
  --workspace "$WS" \
  --robot "$ROBOT_NAME" \
  --repair
```

Return to [Step 5](#setup-step-5).

<a id="setup-ref-6-1"></a>
## Fix Step 6.1: Registration/Approval Sync Fails

Interactive form:

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

- `robot4=robot4@legion4.local`
- `robot5=robot5@legion5.local`

If SSH fails, verify that the control machine can SSH into each robot using the
same target string.

### CONTROL MACHINE:

```bash
ssh robot4@legion4.local hostname
ssh robot5@legion5.local hostname
```

Return to [Step 6](#setup-step-6).

If you are maintaining a committed fleet baseline and intentionally want the
registration command to update source control too, rerun the same sync command
with `--update-source-baseline`. Normal setup should not use that flag.

<a id="setup-ref-7-1"></a>
## Fix Step 7.1: Control Machine Does Not Recognize an Approved Robot

Inspect the control-machine runtime registry.

### CONTROL MACHINE:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
path = Path.home() / ".config/swarm_control_core/robot_instances.yaml"
print(path)
data = yaml.safe_load(path.read_text()) if path.exists() else {}
print(sorted((data or {}).get("robots", {}).keys()))
PY
```

If the robot is missing, rerun Step 6 with explicit `robot_name=ssh_target`
sources. If the robot is present but the UI still says read-only, restart the
FPV UI so it reloads the trusted registry.

Return to [Step 7](#setup-step-7).

<a id="setup-ref-8-1"></a>
## Fix Step 8.1: Final Verification Commands Fail

Check that the workspace overlay is sourced and executables are visible.

### CONTROL MACHINE:

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true
ros2 pkg executables swarm_control_core | rg "_core$"
```

### ROBOT(S):

```bash
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true
ros2 pkg executables swarm_control_core | rg "_core$"
```

Return to [Step 8](#setup-step-8).

<a id="setup-ref-optional-wheel-test"></a>
## Optional: Wheel Direction Test

Run this after Step 4 when the robot uses GPIO motor control and before the
live quickstart bringup. This test drives the GPIO hardware directly, so keep
the robot on blocks, wheels/tracks clear, and do not run robot bringup at the
same time.

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_wheel_test.sh" --robot "$ROBOT_NAME"
```

The terminal app accepts movement keys and prints the expected wheel directions.
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

<a id="setup-ref-optional-service-mode"></a>
## Optional: Robot Service Mode

Manual quickstart bringup is the recommended first run, but if you want a robot
service installed after the fresh setup succeeds, run this in that robot SSH
terminal.

### ROBOT(S):

```bash
"$SC/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$WS" \
  --domain-id "$SWARM_CORE_ROS_DOMAIN_ID" \
  --install-service
```

If you want the service enabled immediately, add `--enable-service-now`.

For the full live-session startup and expanded fix paths, use:

- [QUICKSTART.md](./QUICKSTART.md)
- [LOCAL_FPV_runbook.md](./LOCAL_FPV_runbook.md)
