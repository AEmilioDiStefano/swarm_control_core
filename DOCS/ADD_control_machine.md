# ADD Control Machine

This guide sets up an **additional or replacement control machine** for a
swarm whose robots were already onboarded with
[ADD_robot_pi.md](./ADD_robot_pi.md). Robots keep their drive, hardware
interface, and camera profiles locally, so nothing is re-provisioned on any
robot: the new machine only needs the software, SSH access, and a pull of
each robot's saved profile.

Use this guide when:

- you want to control the same swarm from a second computer
- the original control machine broke and you are replacing it

`swarm_control_core` is local/private-LAN scoped: SSH key authorization is
the robot-side trust step, and the control-machine registry is what approves
robots for UI control. (The pro package adds a swarm-wide credential pack on
top of this; see `swarm_control_pro/DOCS/ADD_control_machine.md` if you use
pro.)

This guide follows the DRP guide format
([`DRP_guide_format.md`](./DRP_guide_format.md)).

Prerequisites:

- the robots are already onboarded and reachable on the same private LAN
- you know each robot's SSH target (`robotN@legionN.local`) and the fallback
  password recorded when the robot was flashed

# Direct Run Path

<a id="acm-step-0"></a>
## Step 0: Prepare This Machine

Run this once in a terminal on the new control machine. It fetches the
first-contact bootstrap, which finds or clones the workspace, installs the
`swarmc` launcher, and runs full control-machine setup.

### CONTROL MACHINE:

```bash
wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup control
```

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

### IF `.local` names do not resolve on this network

Go to [Fix: mDNS `.local` Not Resolving](#acm-ref-1-1), then return to
[Step 1](#acm-step-1).

### IF SSH refuses to connect because the host identification changed

Go to [Fix: Stale SSH Host Key](#acm-ref-1-2), then return to
[Step 1](#acm-step-1).

<a id="acm-step-2"></a>
## Step 2: Register the Robots on This Machine

The registration wizard pulls each robot's saved local profile over SSH and
imports it into this machine's trusted runtime registry — drive type,
hardware interface, and camera profile included, exactly as configured
during original onboarding.

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

This machine can now operate the swarm. Continue with
[QUICKSTART.md](./QUICKSTART.md).

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
