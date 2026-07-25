# ADD Robot: Raspberry Pi

This guide takes a Raspberry Pi robot from a blank SD card to a fully
onboarded, registered/approved swarm robot **without ever opening a manual SSH
session on the robot**. Every command in the direct path runs on the control
machine; the robot side is provisioned over SSH automatically by
`scripts/swarm_core_new_robot.sh`.

This guide is also the correct path for **re-imaging an existing robot** (for
example after a lost password): the flow clears the stale SSH host key and
re-enrolls the robot from scratch.

A robot is not considered ready for live FPV/control until it has a local
robot profile, has been registered/approved on the control machine, and has
passed the verification steps below.

This guide follows the DRP guide format
([`DRP_guide_format.md`](./DRP_guide_format.md)):

1. **Direct Run Path**: the normal setup path, in order.
2. **Alternative/Debug/Fix Reference**: all conditional branches live at the
   bottom and are referenced from the run path with `### IF...` callouts.

Prerequisites:

- the robot is assembled and wired
  ([`setup_instructions_ASSEMBLY.md`](./setup_instructions_ASSEMBLY.md))
- an SD card, a Raspberry Pi, and Raspberry Pi Imager on any computer
- the control machine and robot share (or will share) the same private LAN
- the control machine and robot can reach the internet during initial install

When you finish this guide:

- `swarm_control_core` will be checked out and built on the control machine
  and the robot
- the robot will have a local `robot_instances.yaml` entry describing its own
  drive type, hardware interface, and SSH target
- the control machine will have registered/approved the robot for UI trust
- GPIO access and a camera profile will be prepared on the robot
- you can continue with [QUICKSTART.md](./QUICKSTART.md)

# Direct Run Path

<a id="add-step-0"></a>
## Step 0: Prepare the Control Machine

Run this once in a control-machine terminal. It is safe to rerun; if the
control machine is already set up, it finishes quickly.

### CONTROL MACHINE:

```bash
SWARM_CORE_SETUP_WORKSPACE="${SWARM_CORE_WORKSPACE_ROOT:-${WS:-$HOME/ros2_ws_dev}}"
SWARM_CORE_SETUP_WORKSPACE="${SWARM_CORE_SETUP_WORKSPACE%/}"
SWARM_CORE_SETUP_HELPER="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_setup_bootstrap.sh" 2>/dev/null | sort | head -n1)"

if [[ -z "${SWARM_CORE_SETUP_HELPER:-}" ]]; then
  command -v git >/dev/null 2>&1 || {
    sudo apt-get -o DPkg::Lock::Timeout=1800 update
    sudo apt-get -o DPkg::Lock::Timeout=1800 install -y git
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

- the control machine has `WS` and `SC` exported
- dependency output ends with `All dependencies are installed and up to date.`
- bootstrap summary shows `BUILD_STATUS = completed`

### IF dependency installation, build, or source setup fails

Go to [Fix: Control Bootstrap or Build Fails](#add-ref-0-1), then return to
[Step 0](#add-step-0).

<a id="add-step-1"></a>
## Step 1: Print the Imager Checklist

Pick the robot's name and hostname first (the house convention is user
`robotN` on host `legionN`). This prints the exact flash settings, including
this control machine's SSH public key (generated now if missing).

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_new_robot.sh" --imager-checklist \
  --robot-name robot4 --robot-hostname legion4
```

Expected success signals:

- a checklist block listing hostname, username, Wi-Fi, and SSH settings
- an `ssh-ed25519 ...` public key line to paste into the Imager
- the exact onboarding command to run in Step 3

<a id="add-step-2"></a>
## Step 2: Flash and Boot the Pi

In Raspberry Pi Imager, choose **Ubuntu Server 24.04 LTS (64-bit)**, open
**Edit Settings**, and enter the checklist values exactly:

- hostname `legionN`, username `robotN`, a recorded fallback password
- Wi-Fi credentials for the robot LAN (or use Ethernet)
- Services: enable SSH and paste the public key from Step 1

Write the card, insert it into the Pi, and power on. First boot takes a few
minutes while cloud-init provisions the user and network; the onboarding
command in Step 3 waits for it automatically.

<a id="add-step-3"></a>
## Step 3: Onboard With One Command

Run this in the prepared control-machine terminal from Step 0. Add
`--control-type` and `--control-interface` to preselect the drive and
hardware profiles; omit them to answer the profile prompts interactively in
this terminal (the prompts still run here, never on the robot).

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_new_robot.sh" robot4@legion4.local \
  --control-type diff_drive \
  --control-interface 4wheel_diff_l298n_2
```

The command waits for the robot to appear on the network, waits for
first-boot provisioning to settle, clones and builds the workspace on the
robot, prepares GPIO, adds the robot-local profile (including camera
selection), and registers/approves the robot on this control machine. The
build stage on a Pi takes a while; the run is unattended unless you omitted
the profile flags.

Expected success signals:

- `[OK] Local robot profile is prepared on this robot.`
- `[OK] Control-machine robot registration/approval complete.`
- `[OK] robot4 (robot4@legion4.local) is onboarded and registered/approved on this control machine.`

### IF the wait for SSH times out

Go to [Fix: Robot Never Appears on the Network](#add-ref-3-1), then return to
[Step 3](#add-step-3).

### IF you are prompted for a password

Go to [Fix: Password Prompt Appears](#add-ref-3-2), then return to
[Step 3](#add-step-3).

### IF an SSH host-key warning appears

Go to [Fix: Stale SSH Host Key](#add-ref-3-3), then return to
[Step 3](#add-step-3).

### IF `.local` names do not resolve on this network

Go to [Fix: mDNS `.local` Not Resolving](#add-ref-3-4), then return to
[Step 3](#add-step-3).

### IF dependency installation, build, or robot preparation fails

Go to [Fix: Robot Bootstrap or Build Fails](#add-ref-3-5), then return to
[Step 3](#add-step-3).

### IF apt update waits on first-boot Ubuntu package jobs

Go to [Fix: First-Boot Ubuntu Updates Hold the Apt Lock](#add-ref-3-6), then
return to [Step 3](#add-step-3).

### IF you need a non-default robot name, known hardware profile, or new hardware profile

Go to [Alternative: Non-Default Names or Hardware Profiles](#add-ref-3-7),
then return to [Step 3](#add-step-3).

### IF camera probing needs manual fallback

Go to [Fix: Camera Probing Needs Manual Fallback](#add-ref-3-8), then return
to [Step 3](#add-step-3).

### IF you prefer the manual per-robot SSH setup path

Go to [Alternative: Manual Per-Robot Setup](#add-ref-manual), then return to
[Step 4](#add-step-4).

<a id="add-step-4"></a>
## Step 4: Verify Control-Machine Recognition

Run this in the control-machine terminal. It prints every robot currently in
the control machine's registered/approved runtime registry, then checks each
one with `robot_doctor_core`.

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

REGISTERED_ROBOTS="$(
python3 - <<'PY'
from pathlib import Path
import os
import yaml

default_config_dir = Path.home() / ".config" / "swarm_control_core"
config_dir = Path(os.environ.get("SWARM_CORE_CONFIG_DIR", str(default_config_dir)))
path = config_dir / "robot_instances.yaml"
data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
robots = data.get("robots", {}) if isinstance(data, dict) else {}
for name in sorted(robots):
    print(name)
PY
)"

if [[ -z "${REGISTERED_ROBOTS//[[:space:]]/}" ]]; then
  echo "[FAIL] No registered/approved robots found in the control-machine runtime registry." >&2
  echo "[NEXT] Return to Step 3 and onboard at least one robot." >&2
else
  echo "[OK] Registered/approved robots:"
  printf '  %s\n' $REGISTERED_ROBOTS

  for robot in $REGISTERED_ROBOTS; do
    echo
    echo "[CHECK] robot_doctor_core --robot ${robot}"
    ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot "$robot"
  done
fi
```

Expected success signals for each robot:

- `robot_entry: current`
- the selected `control_interface` matches the robot hardware

Registered/approved robots are ready for QUICKSTART handoff: continue with
[QUICKSTART.md](./QUICKSTART.md).

### IF a robot is missing, stale, or still read-only in the UI later

Go to [Fix: Control Machine Does Not Recognize an Approved Robot](#add-ref-4-1),
then return to [Step 4](#add-step-4).

### IF you want to test wheel direction/order before live quickstart

Go to [Optional: Wheel Direction Test](#add-ref-optional-wheel-test), then
return to [Step 4](#add-step-4).

### IF you see an inverted image after camera configuration

Go to [Optional: Camera Orientation Flip](#add-ref-optional-camera-flip),
then return to [Step 4](#add-step-4).

### IF you want robot service mode instead of manual bringup

Go to [Optional: Robot Service Mode](#add-ref-optional-service-mode).

# Alternative/Debug/Fix Reference

<a id="add-ref-0-1"></a>
## Fix: Control Bootstrap or Build Fails

Run this in the control-machine terminal.

If `apt` reports `Conflicting values set for option Signed-By` for
`packages.ros.org/ros2/ubuntu`, the control machine has duplicate ROS apt
source entries. The dependency script disables duplicate ROS entries under
`/etc/apt/sources.list.d` and rewrites the canonical
`/etc/apt/sources.list.d/ros2.list` entry before it refreshes apt.

### CONTROL MACHINE:

```bash
sudo dpkg --configure -a
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role control
sudo apt-get --fix-broken install -y
"$SC/scripts/swarm_core_check_install_dependencies.sh" --machine-role control
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
colcon build --base-paths "$WS/src/swarm_control_core" --packages-select swarm_control_core --event-handlers console_direct+
source "$WS/install/setup.bash"
set -u || true
```

Then return to [Step 0](#add-step-0).

<a id="add-ref-3-1"></a>
## Fix: Robot Never Appears on the Network

Use when `swarm_core_new_robot.sh` times out waiting for SSH.

- confirm the Pi has power and the SD card is seated
- confirm the Wi-Fi SSID/password typed into the Imager are correct for the
  robot LAN (a typo here is the most common cause; reflash if wrong)
- if on Ethernet, confirm link lights
- try the raw reachability probe:

### CONTROL MACHINE:

```bash
ping -c 3 legion4.local
ssh-keyscan -T 5 legion4.local
```

If `ping` resolves but `ssh-keyscan` fails, SSH was not enabled in the Imager
settings; reflash with SSH enabled. Then return to [Step 3](#add-step-3).

<a id="add-ref-3-2"></a>
## Fix: Password Prompt Appears

Use when the run asks for a password. This means the Imager did not pre-seed
the control machine's SSH public key (or a different key was pasted).

Enter the password you set in the Imager once — the run installs key auth
via `ssh-copy-id` and continues; all later steps and future sessions are
password-free. If the password is rejected, the username or password typed
into the Imager does not match what you are using; reflash with known
values. Then return to [Step 3](#add-step-3).

<a id="add-ref-3-3"></a>
## Fix: Stale SSH Host Key

Use when SSH refuses to connect because the host identification changed
(usually because `--keep-known-hosts` was passed, or the host was previously
enrolled under a different name/IP).

### CONTROL MACHINE:

```bash
ssh-keygen -R legion4.local
ssh-keygen -R legion4
```

Then return to [Step 3](#add-step-3).

<a id="add-ref-3-4"></a>
## Fix: mDNS `.local` Not Resolving

Use when `legion4.local` cannot be resolved (multicast-blocked router or
network). Find the robot's IP from your router's client list, then pin the
name once:

### CONTROL MACHINE:

```bash
echo "<robot-ip> legion4.local legion4" | sudo tee -a /etc/hosts
```

IPs are transport only — keep using the hostname form
(`robot4@legion4.local`) everywhere. Then return to [Step 3](#add-step-3).

<a id="add-ref-3-5"></a>
## Fix: Robot Bootstrap or Build Fails

The onboarding command is safe to rerun; completed stages are skipped or
converge quickly. If a rerun keeps failing at the same place, run the
repair commands below **from the control machine over SSH** (still no manual
robot session needed).

If `apt` reports `Conflicting values set for option Signed-By` for
`packages.ros.org/ros2/ubuntu`, the robot has duplicate ROS apt source
entries; the dependency script repairs this on its next run.

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "sudo dpkg --configure -a && sudo apt-get --fix-broken install -y"
```

If `apt --fix-broken install` fails with an overwrite error like
`trying to overwrite '/usr/lib/python3/dist-packages/catkin_pkg/__init__.py'`
followed by `which is also in package python3-catkin-pkg`, remove the older
conflicting package first:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "sudo apt-get -s remove python3-catkin-pkg"
ssh -tt robot4@legion4.local "sudo apt-get remove -y python3-catkin-pkg && sudo apt-get --fix-broken install -y && sudo dpkg --configure -a"
```

The first command is a dry run. If it says it would remove a large ROS stack
instead of only the stale `python3-catkin-pkg` package, stop and inspect the
package state before continuing. Then return to [Step 3](#add-step-3) and
rerun the onboarding command.

<a id="add-ref-3-6"></a>
## Fix: First-Boot Ubuntu Updates Hold the Apt Lock

On freshly imaged Ubuntu, `unattended-upgrades` may run automatically in the
background. If onboarding output repeats a line like
`Waiting for cache lock: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process ... (unattended-upgr)`,
the package manager is busy, not permanently broken.

Do not remove apt lock files. The robot bootstrap waits for real apt/dpkg
lock holders automatically (up to 30 minutes). If it timed out, wait for the
background update to finish, then rerun the onboarding command. To check the
lock holder from the control machine:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "ps -o pid,etime,comm,args -p \$(fuser /var/lib/dpkg/lock-frontend 2>/dev/null | tr -d ' ') 2>/dev/null || echo no-lock-holder"
```

Then return to [Step 3](#add-step-3).

<a id="add-ref-3-7"></a>
## Alternative: Non-Default Names or Hardware Profiles

If you want the runtime robot name to be something other than the Pi's Linux
username, pass `--robot-name <name>` to `swarm_core_new_robot.sh` and keep
using that value later in quickstart terminals.

Known hardware profile combinations for `--control-type` /
`--control-interface`:

- `diff_drive` + `4wheel_diff_l298n_1` or `4wheel_diff_l298n_2` or
  `4wheel_diff_tb6612fng_2`
- `mecanum_drive` + `mecanum_l298n_2` or `mecanum_tb6612fng_2`

For new hardware profiles that are not already listed, use the
metadata-driven process in
[`control_interface_profiles.md`](./control_interface_profiles.md) before
onboarding. Then return to [Step 3](#add-step-3).

<a id="add-ref-3-8"></a>
## Fix: Camera Probing Needs Manual Fallback

If the camera chooser warns about probing behavior and you intentionally
want auto-fallback behavior, rerun the profile step with the fallback
enabled:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "export SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1; cd ~/ros2_ws_dev && source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 run swarm_control_core add_robot_core --workspace ~/ros2_ws_dev --name robot4"
```

Then return to [Step 3](#add-step-3).

<a id="add-ref-4-1"></a>
## Fix: Control Machine Does Not Recognize an Approved Robot

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

If the robot is missing, re-run the registration directly with an explicit
source:

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core sync_robot_entries_core \
  --workspace "$WS" \
  --source "robot4=robot4@legion4.local"
```

If the robot is present but the UI still says read-only, restart the FPV UI
so it reloads the trusted registry. Then return to [Step 4](#add-step-4).

<a id="add-ref-manual"></a>
## Alternative: Manual Per-Robot Setup

Use only when you explicitly want to run the setup on the robot yourself
(for example on non-Pi hardware, or while developing the robot stack). SSH
into the robot and run the same stages the onboarding command automates:

### ROBOT(S):

```bash
sudo apt-get -o DPkg::Lock::Timeout=1800 update
sudo apt-get -o DPkg::Lock::Timeout=1800 install -y git
install -d "$HOME/ros2_ws_dev/src"
test -d "$HOME/ros2_ws_dev/src/swarm_control_core/.git" || \
  git clone https://github.com/AEmilioDiStefano/swarm_control_core.git "$HOME/ros2_ws_dev/src/swarm_control_core"

"$HOME/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_bootstrap_machine.sh" \
  --machine-role robot \
  --workspace "$HOME/ros2_ws_dev" \
  --domain-id "${SWARM_CORE_ROS_DOMAIN_ID:-17}"

cd "$HOME/ros2_ws_dev"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$HOME/ros2_ws_dev/install/setup.bash"
set -u || true

ros2 run swarm_control_core add_robot_core \
  --workspace "$HOME/ros2_ws_dev" \
  --name "$(id -un)"
```

Expected success output includes
`[OK] Local robot profile is prepared on this robot.` and a `[NEXT]` line
telling you to register/approve on the control machine. The robot is not
approved for FPV UI control until you run the registration on the control
machine:

### CONTROL MACHINE:

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

ros2 run swarm_control_core sync_robot_entries_core --workspace "$WS"
```

When prompted, enter one source per robot (`robot_name=robot_user@host.local`
form), then press Enter on a blank line. Expected success output ends with
`[OK] Registered/approved robots are ready for QUICKSTART handoff.` Then
return to [Step 4](#add-step-4).

<a id="add-ref-optional-wheel-test"></a>
## Optional: Wheel Direction Test

Run this when the robot uses GPIO motor control and before the live
quickstart bringup. This test drives the GPIO hardware directly, so keep the
robot on blocks, wheels/tracks clear, and do not run robot bringup at the
same time. It is interactive, so allocate a TTY over SSH:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "~/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_wheel_test.sh --robot robot4"
```

The terminal app accepts movement keys and prints the expected wheel
directions. Movement keys match terminal teleop and the Swarm Control UI:

- `8/2`: forward/backward
- `4/6`: rotate left/right, or strafe left/right when strafe mode is enabled
- `7/9/1/3`: arc diagonals in normal mode, strafe diagonals in strafe mode
- arrow keys: same movement behavior as `8/2/4/6`
- `0`: toggle strafe mode for mecanum robots
- `space`, `s`, or `5`: stop

Calibration keys:

- `v`: choose FL/BL/FR/BR and toggle wheel inversion when a wheel spins backward
- `c`: swap two wheel channel mappings when the wrong wheel moves
- `P`: print pending GPIO overrides
- `S`: save pending GPIO overrides into `robot_instances.yaml`

Then return to [Step 4](#add-step-4).

<a id="add-ref-optional-camera-flip"></a>
## Optional: Camera Orientation Flip

Use this after the robot has a generated camera profile and the FPV image is
inverted: upside-down or mirrored left/right. The flipper menu is
interactive, so allocate a TTY over SSH:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "cd ~/ros2_ws_dev && source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 run swarm_control_core camera_flipper_core --robot robot4"
```

Use the interactive menu to choose horizontal flip, vertical flip, clear all
flips, show status, or exit.

`camera_flipper_core` refuses to save a flip when the currently plugged-in
camera does not match the saved profile unless `--force` is used. That
prevents one camera's correction from silently applying to a different
replacement camera. Restart that robot's quickstart bringup after saving.

Then return to [Step 4](#add-step-4).

<a id="add-ref-optional-service-mode"></a>
## Optional: Robot Service Mode

Manual quickstart bringup is the recommended first run, but if you want the
robot bringup installed as a systemd service, pass `--install-service` to the
onboarding command in Step 3, or install it afterwards from the control
machine:

### CONTROL MACHINE:

```bash
ssh -tt robot4@legion4.local "~/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_bootstrap_machine.sh --machine-role robot --workspace ~/ros2_ws_dev --domain-id ${SWARM_CORE_ROS_DOMAIN_ID:-17} --enable-service-now"
```

For the full live-session startup and expanded fix paths, use
[QUICKSTART.md](./QUICKSTART.md) and
[LOCAL_FPV_runbook.md](./LOCAL_FPV_runbook.md).
