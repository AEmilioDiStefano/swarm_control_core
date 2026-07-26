# Local FPV Quickstart

Status: active local/LAN quickstart for `swarm_control_core`.

Use this for the shortest path to local robot FPV + control.
For full detail and extended troubleshooting, use:
- [`LOCAL_FPV_runbook.md`](LOCAL_FPV_runbook.md)

If robot setup has not already been done for the robot(s) you want to
control, you must first follow one of the ADD_robots guide docs (for
example, [`ADD_robot_pi.md`](ADD_robot_pi.md) for Raspberry Pi robots).
If you are still assembling the robot hardware, start with
[`setup_instructions_ASSEMBLY.md`](setup_instructions_ASSEMBLY.md).
To operate an existing swarm from a new machine, use
[`ADD_control_machine.md`](ADD_control_machine.md).

This runbook is split into two parts:
1. **Quickstart Path** at the top.
2. **Alternative/Debug/Fix** at the bottom.

For the guide-authoring standard, see
[`DRP_guide_format.md`](./DRP_guide_format.md).

Operator model for this quickstart (required):
- Run everything from the control machine.
- Keep one dedicated terminal per robot SSH session open for the full run.
- Keep one separate control-machine terminal for the local FPV UI.

Suggested terminal layout on the control machine:
- `CM-UI`: local UI terminal.
- `R-<robot-a>`: `ssh <robot_user>@<robot_host>.local`
- `R-<robot-b>`: `ssh <robot_user>@<robot_host>.local`
- add one terminal per additional robot.

Command style note: every step is one short `swarmc` launcher command; the
heavy lifting lives in `scripts/swarm_core_quickstart_step*.sh`. This guide
calls the launcher as `~/.local/bin/swarmc` so the commands work in any
terminal, even before `~/.local/bin` is on your PATH (plain `swarmc` works
in terminals opened after machine setup). The launcher was installed by the
ADD-robot guide's machine setup; if it is missing on a machine, see
[Fix Step 0.0](#ref-0-0).

Trust/verification rule:
- Every robot you intend to control must be registered/approved on the control
  machine before the FPV UI starts.
- The required success signal is:
  `[OK] Registered/approved robots are ready for QUICKSTART handoff.`
- If a robot is visible over ROS but missing from the control machine's trusted
  registry, the UI keeps it read-only by design.

### IF switching between `swarm_control_core` and `swarm_control_pro`

Go to [Alternative Step A.1](#ref-a-1), then return to [Step 0](#step-0).

# Direct Run Path

<a id="apt-lock-preflight"></a>
## Before Step 0: Apt/Dpkg Lock Preflight

Run this in any control-machine or robot terminal that may install packages.
If Ubuntu first-boot updates are active, it waits with readable status
before the quickstart starts dependency installation.

### CONTROL MACHINE / ROBOT(S):

```bash
~/.local/bin/swarmc apt-wait
```

Expected output ends with `[OK] apt/dpkg locks are clear.` If it times out,
it prints the exact recovery commands to inspect the lock holder.

<a id="step-0"></a>
## Step 0: Workspace Bootstrap + Dependency Readiness

The dependency flow inside this step is idempotent: it checks what is already
installed and installs only what is missing or outdated, so this step is safe
to re-run at any time (fresh machine or existing machine).

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step0 --machine-role control
```

### ROBOT(S):

```bash
~/.local/bin/swarmc step0 --machine-role robot
```

### Verify success

Expected output ends with:

`All dependencies are installed and up to date.`

And includes:
- `[iw] is already installed and up to date.` (or installed/updated during this step), so Wi-Fi power-save checks are available on robots.

### IF `swarmc` is missing on this machine

Go to [Fix Step 0.0](#ref-0-0), then return to [Step 0](#step-0).

### IF dependency install/check fails

Go to [Fix Step 0.1](#ref-0-1), then return to [Step 0](#step-0).

Proceed to Step 1.

<a id="step-1"></a>
## Step 1: Sync/Build/Source Gate (All Machines)

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step1 --machine-role control
```

### ROBOT(S):

```bash
~/.local/bin/swarmc step1 --machine-role robot
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

### ROBOT(S):

```bash
~/.local/bin/swarmc step2
```

Behavior of the step-2 wrapper:
- applies the robot compat reset
- defaults the robot name to the Linux username (pass `--robot-name <name>`
  to override)
- checks firewall/power-save state
- ensures the canonical `robot_instances.yaml` entry exists
- refreshes runtime `control_types.yaml` and `control_interfaces.yaml` from the
  source tree while preserving generated camera profiles
- prints the selected hardware profile's wiring document when available
- runs the interactive camera-profile save
- launches robot bringup and stays attached to it

### Verify success

Expected robot-side nodes include:
- `motor_driver_node`
- `heartbeat_node`
- `unit_executor_action_server`
- `camera` (if `use_camera:=true`)

### IF robot nodes or camera do not come up

Go to [Fix Step 2.1](#ref-2-1), then return to [Step 2](#step-2).

### IF you want to skip the camera menu or preselect a hardware profile

Go to [Alternative Step 2.2](#ref-2-2), then return to [Step 2](#step-2).

### IF you see an inverted image (either upside-down or mirror image) after camera configuration

Go to [Optional Step 2.4: Camera Orientation Flip](#ref-2-4), then return to
[Step 2](#step-2).

### IF wheels move but direction/order is wrong

Go to [Fix Step 2.3](#ref-2-3), then return to [Step 2](#step-2).

### IF one camera is dark or teleop/video feels laggy

Go to [Fix Step 2.5](#ref-2-5), then return to [Step 2](#step-2).

For multi-robot sessions:
- keep each robot SSH terminal running.
- proceed to Step 2.5 after each robot terminal shows all bringup nodes started and camera first-frame logs.

Proceed to Step 2.5.

<a id="step-2-5"></a>
## Step 2.5: Register/Verify Trusted Robots (Control Machine)

Run this after each robot has completed Step 2 at least once. This is the trust
gate for drive/autonomy control.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register
```

The wizard first repairs/quarantines stale runtime entries that would prevent
the UI from loading the trusted registry. It then ends its initial output with
the ready registered/trusted robots as `username@hostname.local`, with a blank
line between robots. Check that list visually. If every robot you intend to
control is listed, press Enter. If one is missing, enter the exact source
printed by the affected robot in Step 2. Repeat for multiple missing robots,
then press Enter on a blank line.

When you enter a missing robot source, the sync step pulls that robot's saved
profile from the robot over SSH and imports it into the control machine runtime
registry. If the robot does not have a saved local profile yet, the command
prints the robot-side quickstart/profile wizard command to run first.

What this confirms or repairs:
- imports the robot's generated local profile into the control machine's
  runtime trust registry
- refreshes the control machine runtime `control_types.yaml` and
  `control_interfaces.yaml`
- repairs stale runtime entries that still reference removed profile names, when
  a current baseline entry exists for that robot
- validates that the same trusted robot registry used by the UI can load before
  the UI starts

Expected success output ends with
`[OK] Control-machine robot registration/approval complete.` and
`[OK] Registered/approved robots are ready for QUICKSTART handoff.`

### IF registration/verification fails

Go to [Fix Step 3.2](#ref-3-2), then return to [Step 2.5](#step-2-5).

Proceed to Step 3.

<a id="step-3"></a>
## Step 3: Start Local FPV UI (Control Machine)

Prerequisite (required):
- Do not start Step 3 until every robot terminal has completed Step 2 and each robot bringup is running.
- Do not start Step 3 until Step 2.5 prints
  `[OK] Registered/approved robots are ready for QUICKSTART handoff.`

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3
```

Terminal usage requirement:
- Keep each robot SSH terminal open while operating.
- Run the UI only in `CM-UI`.

Operator tip:
- Keep only one active UI tab/window connected to avoid unnecessary duplicate WebRTC/control sessions.

Open in browser:
- `http://127.0.0.1:8080`

Video path:
- Main stream uses strict WebRTC-only transport by default.
- Fleet thumbnails stay in side tiles and do not take over the main pane.

Robot trust model:
- The UI may discover robots that are publishing on the ROS domain before the
  control machine has that robot in its local `robot_instances.yaml`.
- Unknown robots are shown read-only for video/diagnostics, but drive and
  autonomy commands are blocked by default.

### IF UI does not load or bind

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3).

### IF robots are visible but read-only/untrusted

Go to [Fix Step 3.2](#ref-3-2), then return to [Step 3](#step-3).

### IF you need balanced fleet, switch-heavy, all-stream, or LAN-bind mode

Go to [Alternative Step 3.3](#ref-3-3), then return to [Step 3](#step-3).

Proceed to Step 4.

<a id="step-4"></a>
## Step 4: Fleet Readiness Check (Control Machine)

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step4
```

### Verify success

Expected:
- heartbeat/camera/cmd_vel topics visible for active robots
- UI displays robots and streams

### IF robots are missing in UI/topics

Go to [Fix Step 4.1](#ref-4-1), then return to [Step 4](#step-4).

Proceed to Step 5.

<a id="step-5"></a>
## Step 5: Terminal Control Smoke Test (Control Machine)

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step5 --tool teleop
```

### IF terminal control cannot discover robots

Go to [Fix Step 5.1](#ref-5-1), then return to [Step 5](#step-5).

Quickstart complete.

# Alternative/Debug/Fix Reference

<a id="ref-a-1"></a>
## Alternative Step A.1: Mode Handoff Checklist (core <-> pro)

Use this when both `swarm_control_core` and `swarm_control_pro` exist on the
same robots.

From pro persistent mode to core session mode:

- run this core quickstart normally, starting with Step 2 robot prep and Step 3
  UI
- core compat prep stops conflicting services/processes and applies
  runtime-only masks as needed
- no reboot is required to enter core session mode

From core session mode back to pro persistent mode:

- run pro quickstart Step 2 (`service-sync`) from the control machine
- pro service-sync clears core runtime masks and restores pro persistent
  service ownership in the same boot
- reboot is still acceptable if you want a full clean restart of robot state
  before returning to pro

### ROBOT(S):

```bash
sudo systemctl is-enabled swarm-robot.service || true
sudo systemctl is-active swarm-robot.service || true
```

Then return to [Step 0](#step-0).

<a id="ref-0-0"></a>
## Fix Step 0.0: `swarmc` Is Missing on This Machine

The launcher is installed by machine setup in the ADD-robot guides. On a
machine that has never been set up, run the first-contact bootstrap
(`control` on the control machine, `robot` on a robot):

### CONTROL MACHINE / ROBOT(S):

```bash
wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup control
```

If the machine already has the workspace checkout, this reuses it and only
installs the launcher + missing dependencies. Then return to
[Step 0](#step-0).

<a id="ref-0-1"></a>
## Fix Step 0.1: Dependency install/check fails

### CONTROL MACHINE / ROBOT(S):

```bash
sudo apt-get update
~/.local/bin/swarmc step0 --machine-role control
```

Use `--machine-role robot` in robot terminals. Then return to
[Step 0](#step-0).

<a id="ref-1-1"></a>
## Fix Step 1.1: Build/source fails

Clean-rebuild the package in this workspace:

### CONTROL MACHINE / ROBOT(S):

```bash
~/.local/bin/swarmc rebuild --clean
```

Then return to [Step 1](#step-1).

<a id="ref-2-1"></a>
## Fix Step 2.1: Robot nodes/camera fail to start

Load the workspace environment into this shell, then probe nodes/topics and
re-save the camera profile:

### ROBOT (affected):

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 node list
ros2 topic list | rg "/$(id -un)/(heartbeat|camera/image_raw|cmd_vel)"
ros2 run swarm_control_core save_camera_profile_core --robot "$(id -un)"
```

If the robot runs under a non-default name, replace `$(id -un)` with that
name. Then return to [Step 2](#step-2).

<a id="ref-2-2"></a>
## Alternative Step 2.2: Skip Camera Menu or Preselect Hardware

If you already trust the saved camera profile and want to skip the interactive
camera menu, run Step 2 like this.

### ROBOT(S):

```bash
~/.local/bin/swarmc step2 --skip-camera-profile
```

If this is a new robot with a known hardware profile, preselect it. Example for
a differential dual-L298N robot.

### ROBOT(S):

```bash
~/.local/bin/swarmc step2 --control-type diff_drive --control-interface 4wheel_diff_l298n_2
```

For a mecanum robot using two L298N boards.

### ROBOT(S):

```bash
~/.local/bin/swarmc step2 --control-type mecanum_drive --control-interface mecanum_l298n_2
```

For a new hardware profile, add/validate it first with
[control_interface_profiles.md](./control_interface_profiles.md).

Runtime config seeding behavior:

- `swarm_core_run_robot.sh` seeds missing runtime config files from
  `src/swarm_control_core/config` into `~/.config/swarm_control_core/`.
- Existing runtime files are kept by default, including
  `robot_instances.yaml`, `control_types.yaml`, `control_interfaces.yaml`,
  and `camera_profiles.yaml`.
- Step 2 and `add_robot_core` refresh reusable core profile files while
  preserving `camera_profiles.yaml`.
- To diagnose stale source/runtime profile state manually, run
  `~/.local/bin/swarmc doctor --robot <robot-name>`.

Then return to [Step 2](#step-2).

<a id="ref-2-3"></a>
## Fix Step 2.3: Wheel Direction or Wheel Order Is Wrong

For a robot that already has bringup running, open a second SSH terminal to that
same robot and run.

### SECOND ROBOT SSH TERMINAL:

```bash
~/.local/bin/swarmc wheel-test --robot "$(id -un)" --mode cmd_vel
```

Each movement key uses the same controls as terminal teleop and the Swarm
Control UI, then prints the intended wheel directions before publishing the test
command. Use `8/2/4/6/7/9/1/3` or arrow keys for movement, `0` for mecanum
strafe mode, and `space`, `s`, or `5` for stop.

If a wheel direction is reversed, use `v` to choose FL/BL/FR/BR and toggle that
wheel inversion, then press `S` to save. If the wrong wheel moves, use `c` to
swap wheel channel mappings and press `S` to save.

Saved profile changes are consumed on the next robot bringup. Stop the affected
Step 2 terminal with `Ctrl-C`, then return to [Step 2](#step-2).

<a id="ref-2-4"></a>
## Optional Step 2.4: Camera Orientation Flip

If the camera image is inverted after camera configuration, use the interactive
camera flipper tool to save software orientation in that robot's camera profile.

### AFFECTED ROBOT:

```bash
~/.local/bin/swarmc camera-flip --robot "$(id -un)"
```

Main menu options:

- `1) Flip horizontally / left-right mirror`
- `2) Flip vertically / up-down`
- `3) Clear all flips`
- `4) Show status`
- `5) Exit`

`camera_flipper_core` only saves the flip when the currently plugged-in camera
matches the saved camera profile. That keeps one robot's mirrored camera fix
from accidentally applying to a different camera later. Stop the affected Step 2
terminal with `Ctrl-C`, then return to [Step 2](#step-2).

<a id="ref-2-5"></a>
## Fix Step 2.5: Dark Camera or Laggy Video/Control

If one robot feed is much darker than others while transport/control are
healthy, validate camera controls on that robot.

### AFFECTED ROBOT:

```bash
v4l2-ctl --device /dev/v4l/by-id/<your-camera> --list-ctrls
```

This is typically per-camera exposure/gain behavior, not DDS/WebRTC transport
behavior.

If teleop/video feels laggy while motors are receiving frequent commands,
reduce cmd_vel audit overhead for this session.

### ROBOT(S):

```bash
export SWARM_CORE_AUDIT_CMD_VEL_MIN_PERIOD_S=2.0
```

Compatibility prep uses runtime-only masks for conflicting services. Reboot
clears those masks automatically and returns service startup policy to its saved
defaults. If compat mode stopped `ufw.service` at runtime, reboot or run
`sudo systemctl start ufw.service` to restore the saved firewall policy.

Then return to [Step 2](#step-2).

<a id="ref-3-1"></a>
## Fix Step 3.1: UI does not load or bind

Free the UI port, then restart the UI step:

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc free-ui-port --port 8080
~/.local/bin/swarmc step3
```

If LAN access is needed, restart the UI with the bind override instead:

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3 --allow-lan-bind
```

Then return to [Step 3](#step-3).

<a id="ref-3-2"></a>
## Fix Step 3.2: Robots Are Visible but Read-Only/Untrusted

If the UI logs `trusted_robots=<none>` or says a robot is unknown/read-only, the
control machine either does not have that robot in its trusted runtime registry
or could not load the registry. If the UI log includes `Failed to load profile
registry`, run the sync command below for the robot you intend to control; it
refreshes the split profile catalogs and validates the registry load before the
UI starts.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register
```

The wizard repairs/quarantines stale runtime entries, then prints only ready
registered/trusted robots from a registry the UI can load. If every robot you
intend to control is already listed, press Enter. If one is missing, enter the
exact source strings printed by `add_robot_core` or `robot_doctor_core` on each
robot. Accepted source forms:

- `robot_user@robot_host.local`
- `robot_name=robot_user@robot_host.local`

Expected success output ends with
`[OK] Control-machine robot registration/approval complete.` and
`[OK] Registered/approved robots are ready for QUICKSTART handoff.`

The sync command updates the control machine's runtime trust registry by
default. It should not dirty the source-tree `config/robot_instances.yaml`
unless you explicitly pass `--update-source-baseline`.

Then stop and restart [Step 3](#step-3). Unknown robots remain read-only until
they are registered in `robot_instances.yaml`.

Then return to [Step 3](#step-3).

<a id="ref-3-3"></a>
## Alternative Step 3.3: Fleet, Switching, Streaming, or LAN Bind Modes

Balanced fleet profile.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3 --balanced-fleet
```

If rapid back-and-forth switching still feels sticky in `active_only` mode, use
the switch-heavy profile.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3 --switch-heavy
```

To keep all robot camera streams subscribed continuously, at higher load.

### CONTROL MACHINE:

```bash
SWARM_CORE_IMAGE_SUBSCRIPTION_MODE=all ~/.local/bin/swarmc step3
```

For private-LAN browser access.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc step3 --allow-lan-bind
```

Then return to [Step 3](#step-3).

<a id="ref-4-1"></a>
## Fix Step 4.1: Robots missing in UI/topics

Check domain and source consistency on control + robots.

### CONTROL MACHINE / ROBOT(S):

```bash
eval "$(~/.local/bin/swarmc env)"
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID (target=${SWARM_CORE_ROS_DOMAIN_ID:-17})"
env | rg -E '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION)=' || true
ros2 topic list | rg "/.*/heartbeat"
```

All machines must use the same domain id (default `17`) and sourced workspace.

If robot terminals show heartbeat publishing but control still has no heartbeat topics,
DDS traffic is being blocked (commonly by ufw state carried from an earlier setup).
Keep compat defaults and rerun [Step 2](#step-2) on robots + [Step 3](#step-3) on control.

If the UI sees a robot but logs it as unknown/read-only, go to
[Fix Step 3.2](#ref-3-2), then return to [Step 4](#step-4).

If you previously forced firewall preservation, remove that override.

### CONTROL MACHINE / ROBOT(S):

```bash
unset SWARM_CORE_COMPAT_STOP_UFW
```

If a step script prints `Unknown argument: --machine-role`, your robot/control
checkout is stale. If `git pull --ff-only` is blocked by local changes to
`config/robot_instances.yaml` after running robot setup, the runtime profile is
already stored under `~/.config/swarm_control_core/robot_instances.yaml`; restore
the generated source-file edit before pulling.

### CONTROL MACHINE / ROBOT(S):

```bash
eval "$(~/.local/bin/swarmc env)"
cd "$WS/src/swarm_control_core"
git restore config/robot_instances.yaml
git fetch origin --prune
git switch main || git checkout -b main origin/main
git pull --ff-only origin main
```

Then rerun the sync/build gate on that machine:

### CONTROL MACHINE / ROBOT(S):

```bash
~/.local/bin/swarmc step1 --machine-role control
```

Use `--machine-role robot` in robot terminals. Then return to
[Step 4](#step-4).

<a id="ref-5-1"></a>
## Fix Step 5.1: Terminal control cannot discover robots

### CONTROL MACHINE:

```bash
eval "$(~/.local/bin/swarmc env)"
ros2 topic list | rg "/.*/cmd_vel"
ros2 action list | rg "/.*/execute_playbook"
```

Then return to [Step 5](#step-5).
