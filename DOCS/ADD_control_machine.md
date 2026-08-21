# ADD Control Machine

> [!IMPORTANT]
> Engineering reference: this is not currently a supported fresh-install or
> replacement-control-machine Direct Run Path. Public-key-only robots and DDS
> peer migration require an explicit credential/peer handoff that this guide
> does not yet automate. Do not use it for the Noble fresh-card path; follow
> [`NOBLE_FRESH_INSTALL.md`](./NOBLE_FRESH_INSTALL.md) on the original control
> machine.

This guide sets up an **additional or replacement control machine** for a
swarm whose robots were already onboarded with
[ADD_robot_pi.md](./ADD_robot_pi.md). Robots keep their drive, hardware
interface, and camera configuration locally, so nothing is re-provisioned on
any robot. The new machine needs the software, SSH administration access, and
each robot's saved `robot_instances.yaml` entry for its local UI trust
registry; camera profiles remain on the robots.

Use this guide when:

- you want to control the same swarm from a second computer
- the original control machine broke and you are replacing it

`swarm_control_core` is local/private-LAN scoped. Keep these authority planes
separate:

- SSH key authorization permits administration of the robot; it does not
  approve browser/UI motion commands.
- The control machine's runtime `robot_instances.yaml` registry approves which
  robot entries this Core UI may control; it does not grant SSH access.
- ROS 2/DDS discovery and topic transport are a separate network plane.
  Registry approval does not authenticate or encrypt DDS traffic and does not
  replace trusted-LAN or DDS security controls.

The pro package adds a swarm-wide credential pack on top of this; see
`swarm_control_pro/DOCS/ADD_control_machine.md` if you use pro.

This document preserves a DRP-style step/reference layout for engineering
review, but the sequence below is not an active Direct Run Path. The Important
notice above is authoritative until the missing credential/peer handoff is
implemented and the guide is reconciled with
[`DRP_guide_format.md`](./DRP_guide_format.md).

Prerequisites:

- the robots are already onboarded and reachable on the same private LAN
- you know each robot's SSH target (`robotN@legionN.local`) and the fallback
  password recorded when the robot was flashed

# Engineering Reference Sequence

<a id="acm-step-0"></a>
## Step 0: Prepare This Machine

Run this once in a terminal on the new control machine. It fetches the
first-contact bootstrap, which finds or clones the workspace, installs the
`swarmc` launcher, and runs full control-machine setup.

### CONTROL MACHINE:

```bash
set -o pipefail
wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup control
```

This convenience bootstrap currently follows mutable `main`; verify the
documented success output. A pinned, digest-verified release flow is pending.

Expected success signals:

- dependency output ends with `All dependencies are installed and up to date.`
- bootstrap summary shows `BUILD_STATUS = completed`

<a id="acm-step-1"></a>
## Step 1: Authorize This Machine's SSH Key on Each Robot

Create this machine's SSH key if it does not exist, then copy it to each
robot. Enter the robot's recorded password once per robot; afterwards all
access is key-based.

### CONTROL MACHINE:

```bash
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
ssh-copy-id robot4@legion4.local
```

Repeat the `ssh-copy-id` line for each robot in the swarm.

This step establishes SSH administration access only. UI command approval is
the separate registration gate in Step 2, and DDS participation remains
governed by the deployment's network and DDS controls.

### IF `.local` names do not resolve on this network

Go to [Fix: mDNS `.local` Not Resolving](#acm-ref-1-1), then return to
[Step 1](#acm-step-1).

### IF SSH refuses to connect because the host identification changed

Go to [Fix: Stale SSH Host Key](#acm-ref-1-2), then return to
[Step 1](#acm-step-1).

<a id="acm-step-2"></a>
## Step 2: Register the Robots on This Machine

The registration wizard pulls each robot's saved local
`robot_instances.yaml` entry over SSH and imports that entry into this
machine's trusted runtime registry. That entry carries the robot identity,
SSH target, drive type, and hardware interface used by the Core UI trust
gate. The generated camera profile is intentionally robot-local and is not
copied by `swarmc register`; robot-side bringup continues to use the camera
profile already saved on that robot.

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc register
```

When prompted, enter one source per robot (`robot_name=robot_user@host.local`
form), then press Enter on a blank line. Expected success output ends with
`[OK] Registered/approved robots are ready for QUICKSTART handoff.`

<a id="acm-step-3"></a>
## Step 3: Verify

### CONTROL MACHINE:

```bash
~/.local/bin/swarmc verify-robots
```

Expected success signals for each robot:

- `robot_entry: current`
- the selected `control_interface` matches the robot hardware

This verifies control-machine profile and UI-trust readiness. It does not
change SSH authorization, establish DDS participant authority, or certify
physical actuator readiness.

This control machine's SSH-access and UI-registry setup is complete. Continue
with [QUICKSTART.md](./QUICKSTART.md), and complete each robot's
[physical actuator-readiness gate](./ADD_robot_pi.md#add-ref-actuator-readiness)
before issuing motion commands.

# Alternative/Debug/Fix Reference

<a id="acm-ref-1-1"></a>
## Fix: mDNS `.local` Not Resolving

Find the robot's IP from your router's client list, then pin the name once:

### CONTROL MACHINE:

```bash
echo "<robot-ip> legion4.local legion4" | sudo tee -a /etc/hosts
```

IPs are transport only — keep using the hostname form everywhere. Then
return to [Step 1](#acm-step-1).

<a id="acm-ref-1-2"></a>
## Fix: Stale SSH Host Key

Use when this machine previously knew a different host key for the robot's
hostname (for example after a robot re-image):

### CONTROL MACHINE:

```bash
ssh-keygen -R legion4.local
ssh-keygen -R legion4
```

Then return to [Step 1](#acm-step-1).
