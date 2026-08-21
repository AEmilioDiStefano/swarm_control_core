# Ubuntu Noble Fresh-Card Local FPV Guide

Status: supported Direct Run Path for a fresh Ubuntu 24.04 (Noble) desktop
control machine and Raspberry Pis freshly flashed with Ubuntu Server 24.04 LTS
(64-bit).

Use this guide to go from a clean clone to local browser FPV and a supervised
first motion. This path supports the GPIO motor interfaces listed by the
onboarding menu and a USB UVC camera connected to each Pi. CSI-camera variants
need separate platform-specific validation and are not part of this fresh-card
path.

This guide follows [`DRP_guide_format.md`](./DRP_guide_format.md):

1. **Direct Run Path** contains only the normal successful sequence.
2. **Alternative/Debug/Fix Reference** contains every retry, repair, and
   start-over procedure.

Command style note: after Step 0, commands use `~/.local/bin/swarmc` so they
work in fresh terminals without `.bashrc` changes. Every robot is onboarded by
IPv4 address; `.local` is retained only as an identity that onboarding verifies.

Operator terminal model:

- `CM-SETUP`: control-machine setup/onboarding commands;
- `R-<robot>`: one dedicated SSH terminal kept open for robot bringup;
- `CM-UI`: one control-machine terminal kept open for the local FPV UI; and
- `CM-CHECK`: a fresh control-machine terminal for the readiness check.

# Direct Run Path

## Motion-Safety and Network Preflight

Before flashing or powering motor hardware:

- provide an operator-reachable physical motor-power cutoff;
- raise and secure wheels/tracks for every first-motion test and use a spotter;
- keep the motion area clear;
- connect the control desktop and Pi to the same trusted private LAN;
- make sure that LAN permits direct unicast traffic between clients; and
- have access to the router/DHCP lease list.

Attach a USB UVC camera before onboarding. Keep exactly one active browser
control surface per robot. Heartbeats, ROS topics, or a browser image do not by
themselves prove that physical motion is safe.

<a id="step-0"></a>
## Step 0: Clone and Set Up the Control Machine

The package must live at
`$HOME/ros2_ws_dev/src/swarm_control_core`. The command below reuses a clean
clone already at that path and creates it when it is absent.

### CONTROL MACHINE:

```bash
sudo apt-get update
sudo apt-get install -y git
mkdir -p "$HOME/ros2_ws_dev/src"
if [[ -d "$HOME/ros2_ws_dev/src/swarm_control_core/.git" ]]; then
  git -C "$HOME/ros2_ws_dev/src/swarm_control_core" pull --ff-only origin main
else
  git clone https://github.com/AEmilioDiStefano/swarm_control_core.git \
    "$HOME/ros2_ws_dev/src/swarm_control_core"
fi
cd "$HOME/ros2_ws_dev/src/swarm_control_core"
./scripts/swarmc setup --role control
```

Setup installs ROS 2 Jazzy, CycloneDDS, browser/video dependencies, mDNS
support, and the local launcher, then builds the package.

### Verify success

Expected output includes:

```text
All dependencies are installed and up to date.
BUILD_STATUS = completed
```

### IF dependency installation or the build fails

Go to [Fix Step 0.1](#ref-0-1), then return to [Step 0](#step-0).

### IF the canonical checkout is incomplete or locally modified

Go to [Fix Step 0.2](#ref-0-2), then return to [Step 0](#step-0).

Proceed to Step 1.

<a id="step-1"></a>
## Step 1: Generate the Exact Pi and Hardware Checklist

Run the checklist once for each Pi.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc imager-checklist
```

The checklist asks for:

1. a unique lowercase Linux username, which is also the robot name;
2. a unique lowercase hostname;
3. the robot control/kinematics type; and
4. the motor-controller interface physically wired to this Pi.

It prints the exact wiring document, the control machine's complete public
key, all Raspberry Pi Imager settings, and the exact post-boot onboarding
command block. Save that output.

Do not copy a hardware choice from an example. In particular,
`4wheel_diff_l298n_1` means one L298N driving left/right motor pairs, while
`4wheel_diff_l298n_2` means two L298Ns with four independently driven wheels.

### Verify success

Expected output includes all of these sections:

- `Hardware profile:` and `Wiring guide:`;
- `Enable SSH: YES` and one complete `ssh-ed25519` key; and
- `RUN ON THE CONTROL MACHINE`, followed by a block that prompts for
  `ROBOT_IP` and passes `--robot-ip "$ROBOT_IP"`.

### IF the menu does not contain the hardware that is actually wired

Go to [Fix Step 1.1](#ref-1-1), then return to [Step 1](#step-1).

Proceed to Step 2.

<a id="step-2"></a>
## Step 2: Flash and Boot the Pi

In Raspberry Pi Imager, apply every value printed by Step 1:

- Ubuntu Server 24.04 LTS (64-bit);
- the printed username and hostname;
- the robot LAN SSID/password, or Ethernet;
- SSH enabled with public-key authentication only; and
- the entire printed `ssh-ed25519` public key as one line.

Record the local-recovery password even though public-key-only SSH does not
accept it over the network. Write the card, attach the USB UVC camera, insert
the card, boot the Pi, and leave it powered for several minutes while
first-boot cloud-init runs.

Find the new hostname in the router/DHCP lease list and record its IPv4
address. Create a DHCP reservation when possible. Stock Noble Server does not
include Avahi, so `<hostname>.local` is not expected to resolve yet.

### Verify success

Expected:

- the Pi remains powered and connected to the intended LAN; and
- the router/DHCP list shows the exact hostname from Step 1 with an IPv4
  address.

### IF the Pi never appears in the router/DHCP list

Go to [Fix Step 2.1](#ref-2-1), then return to [Step 2](#step-2).

### IF the Imager username, Wi-Fi, or public key was entered incorrectly

Go to [Fix Step 2.2](#ref-2-2), then return to [Step 2](#step-2).

Proceed to Step 3.

<a id="step-3"></a>
## Step 3: Onboard the Fresh Pi from the Control Machine

Run the exact two-command block printed by Step 1. The first command prompts
for the IPv4 address from Step 2. The second command runs `new-robot` with that
address, the expected user/hostname, the exact SSH key, and the exact hardware
selections. Do not reconstruct it from memory.

### CONTROL MACHINE:

Run the saved block under `RUN ON THE CONTROL MACHINE` from Step 1 and enter
the Pi's IPv4 address when prompted.

The onboarding command does not scan the LAN. Before changing the Pi, it
checks that the supplied address reports the expected hostname. It then waits
for cloud-init, prepares the exact published Git commit, repairs package state,
builds the robot workspace, verifies GPIO-chip access, writes the selected
profile, stream-tests the USB camera, records direct DDS peers, and
registers/approves the robot on the control machine.

### Verify success

Expected output ends with both:

```text
[OK] <robot-name> (...) is onboarded and registered/approved on this control machine.
NEXT: ssh ... <robot-user>@<robot-IPv4>
```

Save the exact `NEXT: ssh ...` command.

### IF onboarding reports key authentication or `ssh-copy-id` failed

Go to [Fix Step 2.2](#ref-2-2), then return to [Step 2](#step-2).

### IF onboarding stops or reports any other error

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3).

### IF this is a reflash of a previously onboarded robot

Go to [Alternative Step 3.2](#ref-3-2), then return to [Step 3](#step-3).

Proceed to Step 4.

<a id="step-4"></a>
## Step 4: Verify Wheel Mapping and Start Robot Bringup

Keep motor power off while checking the printed wiring guide one final time.
Raise and secure the chassis, place the physical cutoff within reach, then run
the exact `NEXT: ssh ...` command from Step 3 in a dedicated control-machine
terminal. Enable motor power only after the chassis is secured, the spotter is
ready, and the wheel-test prompt asks you to exercise an output. Cut motor
power immediately after the test if any result is unexpected.

Use the wheel test in that robot SSH terminal.

### ROBOT SSH TERMINAL:

```bash
~/.local/bin/swarmc wheel-test --robot "$(id -un)"
```

Follow the prompts at the lowest useful power. Confirm that every stated wheel
position and direction matches the physical result. Save any offered
inversion/order correction.

After the wheel test is correct, start robot bringup.

### ROBOT SSH TERMINAL:

```bash
~/.local/bin/swarmc step2 --robot-name "$(id -un)" --skip-camera-profile
```

Leave this terminal running. Camera selection is skipped here only because
Step 3 already required and stream-tested the camera.

### Verify success

Expected:

- `motor_driver_node`, `heartbeat_node`, and `unit_executor_action_server`
  start;
- the camera node logs a first frame;
- the resolved actuator backend is the selected real GPIO profile, not mock;
  and
- no process exits or repeatedly restarts.

### IF wheel position or direction is wrong

Go to [Fix Step 4.1](#ref-4-1), then return to [Step 4](#step-4).

### IF bringup reports mock GPIO, a camera failure, or a node crash

Go to [Fix Step 4.2](#ref-4-2), then return to [Step 4](#step-4).

Proceed to Step 5.

<a id="step-5"></a>
## Step 5: Start the Local FPV UI

Do not stop the robot terminal from Step 4. Open a separate terminal on the
control desktop.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3
```

Leave the UI terminal running. On that same desktop, open
`http://127.0.0.1:8080` in a browser and keep only one active UI tab.

Standalone Core's browser boundary is loopback-only. The private LAN is for
trusted ROS/SSH traffic, not unauthenticated browser exposure. If port 8080 is
already occupied, this command fails without terminating its listener.

### Verify success

Expected:

- the terminal reports `Swarm FPV UI URL: http://127.0.0.1:8080`;
- the browser loads the fleet UI; and
- the onboarded robot is present and not marked unknown/read-only.

### IF the UI does not load or port 8080 is already in use

Go to [Fix Step 5.1](#ref-5-1), then return to [Step 5](#step-5).

### IF the robot is visible but read-only/untrusted

Go to [Fix Step 5.2](#ref-5-2), then return to [Step 5](#step-5).

Proceed to Step 6.

<a id="step-6"></a>
## Step 6: Prove a Fresh Frame Reaches the Browser UI

In the browser, select the intended robot. Move an object in front of the
camera and cover/uncover the lens. You must see a live moving camera frame,
not a placeholder or frozen image.

Keep the robot, UI, and browser running. Open one more control terminal and run
the targeted readiness check.

### CONTROL MACHINE:

```bash
read -r -p "Robot name (the Pi Linux username): " ROBOT_NAME
~/.local/bin/swarmc step4 --robot-name "$ROBOT_NAME"
```

### Verify success

Expected output includes:

```text
FPV ACCEPTANCE PASSED
```

Step 4 verifies the shared CycloneDDS environment, robot-originated heartbeat
and motor nodes, a decodable JPEG received by the UI, a fresh frame timestamp,
a successful browser WebRTC offer for this robot, and connected browser
telemetry. It is not proof that the human sees changing video; the physical
cover/uncover or moving-object check remains required.

### IF Step 4 reports no fresh frame

Go to [Fix Step 6.1](#ref-6-1), then return to [Step 6](#step-6).

### IF Step 4 reports no browser WebRTC offer or connection

Go to [Fix Step 6.2](#ref-6-2), then return to [Step 6](#step-6).

### IF the robot nodes/topics are missing

Go to [Fix Step 6.3](#ref-6-3), then return to [Step 6](#step-6).

Proceed to Step 7.

<a id="step-7"></a>
## Step 7: Supervised Browser Control Smoke Test

This step establishes physical actuator readiness; the earlier network, trust,
and frame checks did not.

Keep the chassis raised/secured, use a spotter, make the physical cutoff
reachable, and close every other drive/autonomy command source. In the
loopback browser UI, select the intended robot, apply the smallest control
input, and release it immediately.

### Verify success

Expected:

- only the selected robot responds;
- the intended wheels move in the intended direction;
- the displayed command returns to zero on release; and
- physical wheel output stops.

Do not use the terminal teleop tool as this acceptance test; its active input
loop is not the supported fresh-install motion path.

### IF the wrong robot, wheel, or direction moves, or motion does not stop

Use the physical cutoff immediately. Go to [Fix Step 7.1](#ref-7-1), then
return to [Step 7](#step-7).

Fresh-card local browser FPV bringup is complete.

# Alternative/Debug/Fix Reference

<a id="ref-0-1"></a>
## Fix Step 0.1: Control Dependency Installation or Build Failed

Do not delete apt/dpkg lock files or kill an apt/dpkg process. Wait for the
lock holder, then rerun the idempotent setup.

### CONTROL MACHINE:

```bash
cd "$HOME/ros2_ws_dev/src/swarm_control_core"
./scripts/swarmc apt-wait
./scripts/swarmc setup --role control
```

Expected recovery output again includes
`All dependencies are installed and up to date.` and
`BUILD_STATUS = completed`.

Then return to [Step 0](#step-0).

<a id="ref-0-2"></a>
## Fix Step 0.2: Preserve and Replace an Incomplete Control Checkout

Use this only when the canonical checkout is not a clean Git checkout. It
moves the existing directory to a timestamped backup; it does not delete it.

### CONTROL MACHINE:

```bash
cd "$HOME/ros2_ws_dev/src"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -e swarm_control_core ]]; then
  mv swarm_control_core "swarm_control_core.backup.$stamp"
fi
git clone https://github.com/AEmilioDiStefano/swarm_control_core.git \
  "$HOME/ros2_ws_dev/src/swarm_control_core"
```

Then return to [Step 0](#step-0).

<a id="ref-1-1"></a>
## Fix Step 1.1: The Wired Hardware Is Not in the Menu

Do not select a similar-looking profile. Check the profile index and add a
validated interface/wiring document before onboarding unsupported hardware.

See [`control_interface_profiles.md`](./control_interface_profiles.md) and
[`GPIO/CONTROL_INTERFACE_INDEX.md`](./GPIO/CONTROL_INTERFACE_INDEX.md).

Then return to [Step 1](#step-1).

<a id="ref-2-1"></a>
## Fix Step 2.1: The Pi Does Not Appear in DHCP

Check Pi power, Ethernet link, Imager Wi-Fi SSID/password, Wi-Fi country, and
router client isolation. Connect a display/keyboard or serial console when
available and confirm that the expected user exists and the network acquired
an address.

Do not run a broad LAN SSH scan. Correct the Imager settings or use a private
AP/Ethernet link, then boot the Pi again.

Then return to [Step 2](#step-2).

<a id="ref-2-2"></a>
## Fix Step 2.2: Wrong Imager User, Wi-Fi, or Public Key

If remote login is unavailable and the mistake cannot be repaired from the
Pi's local console, reflash the card with the exact Step 1 checklist. Reusing
the same hostname is supported. Wait for first boot and obtain the new IPv4
address from DHCP.

Then return to [Step 2](#step-2).

<a id="ref-3-1"></a>
## Fix Step 3.1: Onboarding Was Interrupted or Failed

Stop only the foreground onboarding command with Ctrl-C, fix the reported
cause, and rerun the exact same `new-robot` command block printed by Step 1. It
is safe to rerun; do not reflash for an ordinary timeout or build/camera
failure.

Retry behavior is intentionally recoverable:

- cloud-init timeout exits before package/profile changes; leave the Pi
  powered, wait, and rerun;
- apt/dpkg repair runs before and after the robot update;
- an incomplete, corrupt, wrong-origin, or dirty managed robot checkout is
  moved to a timestamped `swarm_control_core.recovery.*` backup before a clean
  exact-commit checkout is made;
- a stale Core robot service is stopped before provisioning;
- camera validation fails before overwriting a successful camera profile; and
- registry/profile writes are atomic and repeat peer additions are
  idempotent.

If the camera gate fails, connect a USB UVC camera, close any process using it,
and rerun the same exact onboarding block. If the IPv4 address changed, use the
new DHCP address at its prompt. The hostname check refuses to provision the
wrong machine.

Then return to [Step 3](#step-3).

<a id="ref-3-2"></a>
## Alternative Step 3.2: Re-Onboard a Reflashed Pi

Run the same exact Step 1 onboarding block with the reflashed Pi's current
IPv4 address. Onboarding removes stale SSH host-key entries for the expected
name/address and verifies the new hostname before provisioning. A DHCP
reservation keeps the recorded unicast DDS peer stable.

Then return to [Step 3](#step-3).

<a id="ref-4-1"></a>
## Fix Step 4.1: Wheel Position or Direction Is Wrong

Keep the robot raised and rerun the direct GPIO wheel test. Use its inversion
and channel-mapping controls, then save the correction.

### AFFECTED ROBOT:

```bash
~/.local/bin/swarmc wheel-test --robot "$(id -un)"
```

Then return to [Step 4](#step-4).

<a id="ref-4-2"></a>
## Fix Step 4.2: Mock GPIO, Camera, or Robot Node Failure

Stop the affected Step 4 bringup with Ctrl-C. Run the doctor and strict camera
probe; the camera file changes only after a successful stream probe.

### AFFECTED ROBOT:

```bash
~/.local/bin/swarmc doctor --robot "$(id -un)"
eval "$(~/.local/bin/swarmc env)"
ros2 run swarm_control_core save_camera_profile_core \
  --robot "$(id -un)" --require-camera
```

Resolve every reported GPIO/profile/camera error. Then return to
[Step 4](#step-4).

<a id="ref-5-1"></a>
## Fix Step 5.1: UI Does Not Load or Port 8080 Is Busy

Inspect the listener before changing anything.

### CONTROL MACHINE:

```bash
ss -ltnp | rg ':8080' || true
```

If it is an old Core UI, stop that identified foreground process normally and
rerun Step 5. Do not terminate an unidentified listener. Port reclamation is
available only through the explicit `SWARM_CORE_RECLAIM_BIND_PORT=1` override;
this fresh-install guide does not use that override. Standalone Core stays on
loopback; do not expose this unauthenticated UI on the LAN.

Then return to [Step 5](#step-5).

<a id="ref-5-2"></a>
## Fix Step 5.2: Robot Is Visible but Read-Only/Untrusted

Onboarding normally performs this registration. Rerun the registration wizard
only if Step 3 completed but the UI registry is missing the robot.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register
```

Expected output ends with
`[OK] Registered/approved robots are ready for QUICKSTART handoff.` Stop and
restart the Step 5 UI after registration.

Then return to [Step 5](#step-5).

<a id="ref-6-1"></a>
## Fix Step 6.1: No Fresh Browser Frame

Stop the affected robot bringup with Ctrl-C. Reconnect the USB UVC camera and
run the strict stream probe.

### AFFECTED ROBOT:

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 run swarm_control_core save_camera_profile_core \
  --robot "$(id -un)" --require-camera
```

After it succeeds, restart Step 4 robot bringup and keep it running. Then
return to [Step 6](#step-6).

<a id="ref-6-2"></a>
## Fix Step 6.2: Browser WebRTC Offer or Connection Is Missing

Use this only when Step 4 already received a fresh JPEG but reports that the
browser did not complete a WebRTC offer/connection for the selected robot.
Keep robot bringup running. Stop the Step 5 UI with Ctrl-C, close every Core UI
tab, and rerun the idempotent control setup so the WebRTC Python packages and
workspace build are verified.

### CONTROL MACHINE:

```bash
cd "$HOME/ros2_ws_dev/src/swarm_control_core"
./scripts/swarmc setup --role control
```

Restart Step 5, open exactly one `http://127.0.0.1:8080` tab, select the same
robot, and wait until the live video and WebRTC transport badge appear. Then
return to [Step 6](#step-6).

<a id="ref-6-3"></a>
## Fix Step 6.3: Robot Nodes or Topics Are Missing

Check the shared domain/RMW/peer state on both machines.

### CONTROL MACHINE / AFFECTED ROBOT:

```bash
eval "$(~/.local/bin/swarmc env)"
env | rg '^(ROS_DOMAIN_ID|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|RMW_IMPLEMENTATION|SWARM_DISCOVERY_MODE)='
ros2 topic list | rg '/.*/heartbeat'
```

The default hybrid policy uses CycloneDDS subnet multicast plus the direct
unicast peers recorded during onboarding. If IP ping/SSH also fails, fix
power, Wi-Fi/Ethernet, routing, firewall policy, or AP client isolation first;
software discovery cannot bypass blocked unicast.

For a multicast-free diagnostic, stop the Step 4 robot process and Step 5 UI
with Ctrl-C. Then relaunch both processes in static mode, keeping both
terminals running.

### AFFECTED ROBOT:

```bash
export SWARM_CORE_DISCOVERY_MODE=static
eval "$(~/.local/bin/swarmc env)"
~/.local/bin/swarmc step2 --robot-name "$(id -un)" --skip-camera-profile
```

### CONTROL MACHINE:

```bash
export SWARM_CORE_DISCOVERY_MODE=static
eval "$(~/.local/bin/swarmc env)"
~/.local/bin/swarmc step3
```

CycloneDDS/Jazzy static-peer mode intentionally reports
`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`; do not change it to `OFF`, because
CycloneDDS ignores static peers in OFF mode. Reopen the loopback browser,
select the intended robot, and keep both relaunched terminals running.

Then return to [Step 6](#step-6).

<a id="ref-7-1"></a>
## Fix Step 7.1: Wrong or Unsafe Physical Motion

Remove motor power first. Resolve the physical wiring fault or saved channel /
inversion mapping while the chassis remains raised. With robot bringup running,
use a second SSH terminal for a short command-path wheel test.

### SECOND ROBOT SSH TERMINAL:

```bash
~/.local/bin/swarmc wheel-test --robot "$(id -un)" --mode cmd_vel
```

Save any correction, stop/restart Step 4 robot bringup so it reloads the
profile, and verify physical stop behavior again.

Then return to [Step 7](#step-7).

<a id="ref-r-1"></a>
## Optional: Preserve and Reset Core Runtime Configuration

Use this only for an intentional machine-local Core reset, not an ordinary
retry. Stop robot/UI processes first. The command moves the runtime directory
to a timestamped backup and does not delete it.

### AFFECTED CONTROL MACHINE / ROBOT:

```bash
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -d "$HOME/.config/swarm_control_core" ]]; then
  mv "$HOME/.config/swarm_control_core" \
    "$HOME/.config/swarm_control_core.backup.$stamp"
fi
```

On a control machine, return to [Step 0](#step-0), then rerun the saved exact
onboarding block for every robot that should be trusted on this control
machine; moving the runtime directory intentionally removed its approval
registry. On a Pi, rerun the exact Step 1 onboarding block and return to
[Step 3](#step-3). No reflash is required solely because runtime configuration
was moved. The backup remains available for manual recovery.
