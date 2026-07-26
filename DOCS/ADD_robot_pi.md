# ADD Robot: Raspberry Pi

This guide takes a Raspberry Pi robot from a blank SD card to a fully
onboarded, registered/approved swarm robot **without ever opening a manual SSH
session on the robot**. Every command in the direct path runs on the control
machine; the robot side is provisioned over SSH automatically. Each step is
one short command: the heavy lifting lives in repository scripts behind the
`swarmc` launcher (which wraps `scripts/swarm_core_new_robot.sh` and friends).

This guide is also the correct path for **re-imaging an existing robot** (for
example after a lost password): the flow clears the stale SSH host key and
re-enrolls the robot from scratch.

A robot is not considered ready for live FPV/control until it has a local
robot profile, has been registered/approved on the control machine, and has
passed the verification steps below. A robot is not approved for FPV UI
control until registration/approval has completed on the control machine.

This guide follows the DRP guide format
([`DRP_guide_format.md`](./DRP_guide_format.md)):

1. **Direct Run Path**: the normal setup path, in order.
2. **Alternative/Debug/Fix Reference**: all conditional branches live at the
   bottom and are referenced from the run path with `### IF...` callouts.

If your swarm uses `swarm_control_pro`, use the pro package's version of
this guide instead (`swarm_control_pro/DOCS/ADD_robot_pi.md`): it adds the
`swarm-robot` service, roster, and swarm trust setup on top of this flow.
This core guide is for core-only (local/LAN) swarms.

Prerequisites:

- the robot is assembled and wired
  ([`setup_instructions_ASSEMBLY.md`](./setup_instructions_ASSEMBLY.md))
- an SD card, a Raspberry Pi, and Raspberry Pi Imager on any computer
- the control machine and robot share (or will share) the same private LAN
- the control machine and robot can reach the internet during initial install

When you finish this guide:

- `swarm_control_core` will be checked out and built on the control machine
  and the robot, with the `swarmc` launcher installed on both
- the robot will have a local `robot_instances.yaml` entry describing its own
  drive type, hardware interface, and SSH target
- the control machine will have registered/approved the robot for UI trust
- GPIO access and a camera profile will be prepared on the robot
- you can continue with [QUICKSTART.md](./QUICKSTART.md)

Command style note: this guide calls the launcher as `~/.local/bin/swarmc` so
every command works in any terminal, even before `~/.local/bin` is on your
PATH. In terminals opened after Step 0, plain `swarmc` works too.

# Direct Run Path

<a id="add-step-0"></a>
## Step 0: Prepare the Control Machine

Run this once in a control-machine terminal. It is safe to rerun; if the
control machine is already set up, it finishes quickly. It fetches the
first-contact bootstrap (`scripts/swarm_core_first_contact.sh`), which finds
or clones the workspace, installs the `swarmc` launcher, and runs full
control-machine setup (dependencies + build).

### CONTROL MACHINE:

```bash
wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup control
```

Expected success signals:

- dependency output ends with `All dependencies are installed and up to date.`
- bootstrap summary shows `BUILD_STATUS = completed`
- the final lines report `[OK] First contact complete.` and the launcher path

### IF dependency installation, build, or source setup fails

Go to [Fix: Control Bootstrap or Build Fails](#add-ref-0-1), then return to
[Step 0](#add-step-0).

<a id="add-step-1"></a>
## Step 1: Print the Imager Checklist

The script asks for this robot's Linux username, then its hostname (the
house convention is user `robotN` on host `legionN`), and only then prints
the exact flash settings for those values, including this control machine's
SSH public key (generated now if missing). On a terminal it always asks —
values are never reused from a previous robot.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc imager-checklist
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

Every robot needs a unique hostname: flashing two cards with the same
hostname makes `.local` name resolution ambiguous on the LAN and onboarding
will target the wrong robot. Reuse a hostname only when re-imaging that same
robot.

Write the card, insert it into the Pi, and power on. First boot takes a few
minutes while cloud-init provisions the user and network; the onboarding
command in Step 3 waits for it automatically. Leave the robot powered on and
ready to connect.

<a id="add-step-3"></a>
## Step 3: Onboard With One Command

Run this in a control-machine terminal. Add `--control-type` and
`--control-interface` to preselect the drive and hardware profiles; omit them
to answer the profile prompts interactively in this terminal (the prompts
still run here, never on the robot).

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc new-robot robot4@legion4.local --control-type diff_drive --control-interface 4wheel_diff_l298n_2
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

Run this in a control-machine terminal. It prints every robot currently in
the control machine's registered/approved runtime registry, then checks each
one with `robot_doctor_core`.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc verify-robots
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

<a id="add-step-5"></a>
## Step 5: Prepare for Additional Control Machines (Recommended)

The robots you just onboarded keep their drive/hardware/camera profiles
locally, so another control machine can operate this same swarm without
re-provisioning any robot. When you want a second machine (or a replacement
machine), follow [ADD_control_machine.md](./ADD_control_machine.md).

Setup on this control machine is complete. Robots onboarded by this guide
are ready for either core operating document — pick by need:

- [QUICKSTART.md](./QUICKSTART.md) — the guided path: one `swarmc` command
  per step, trust-gated, recommended for every normal session.
- [LOCAL_FPV_runbook.md](./LOCAL_FPV_runbook.md) — the raw path: direct
  launch files and tools for debugging and development.

# Alternative/Debug/Fix Reference

<a id="add-ref-0-1"></a>
## Fix: Control Bootstrap or Build Fails

Run these in the control-machine terminal, in order. The first two repair
interrupted package operations; the third waits for background Ubuntu
updates; the last reruns machine setup.

If `apt` reports `Conflicting values set for option Signed-By` for
`packages.ros.org/ros2/ubuntu`, the control machine has duplicate ROS apt
source entries; the dependency flow inside setup repairs this on its next
run.

### CONTROL MACHINE:

```bash
sudo dpkg --configure -a
sudo apt-get --fix-broken install -y
~/.local/bin/swarmc apt-wait
~/.local/bin/swarmc setup --role control
```

If `swarmc` itself is missing (first contact never completed), rerun the
Step 0 one-liner instead. Then return to [Step 0](#add-step-0).

<a id="add-ref-3-1"></a>
## Fix: Robot Never Appears on the Network

Use when onboarding times out waiting for SSH.

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
username, pass `--robot-name <name>` to the onboarding command and keep
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
ssh -tt robot4@legion4.local "SWARM_CORE_CAMERA_ALLOW_PROBE_FALLBACK=1 ~/.local/bin/swarmc add-robot --name robot4"
```

Then return to [Step 3](#add-step-3).

<a id="add-ref-4-1"></a>
## Fix: Control Machine Does Not Recognize an Approved Robot

First list what the control machine actually has:

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc verify-robots
```

If the robot is missing, re-run the registration directly with an explicit
source:

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register --source "robot4=robot4@legion4.local"
```

If the robot is present but the UI still says read-only, restart the FPV UI
so it reloads the trusted registry. Then return to [Step 4](#add-step-4).

<a id="add-ref-manual"></a>
## Alternative: Manual Per-Robot Setup

Use only when you explicitly want to run the setup on the robot yourself
(for example on non-Pi hardware, or while developing the robot stack). SSH
into the robot and run the same stages the onboarding command automates:
first contact + machine setup, then the robot-local profile tool.

### ROBOT(S):

```bash
wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup robot
~/.local/bin/swarmc add-robot --name "$(id -un)"
```

Expected success output includes
`[OK] Local robot profile is prepared on this robot.` and a `[NEXT]` line
telling you to register/approve on the control machine. The robot is not
approved for FPV UI control until you run the registration on the control
machine:

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register
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
ssh -tt robot4@legion4.local "~/.local/bin/swarmc wheel-test --robot robot4"
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
ssh -tt robot4@legion4.local "~/.local/bin/swarmc camera-flip --robot robot4"
```

Use the interactive menu to choose horizontal flip, vertical flip, clear all
flips, show status, or exit.

The camera flipper refuses to save a flip when the currently plugged-in
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
ssh -tt robot4@legion4.local "~/.local/bin/swarmc setup --role robot --enable-service-now"
```

For the full live-session startup and expanded fix paths, use
[QUICKSTART.md](./QUICKSTART.md) and
[LOCAL_FPV_runbook.md](./LOCAL_FPV_runbook.md).
