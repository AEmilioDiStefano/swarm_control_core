# Ubuntu Noble Fresh-Card Bringup

This is the intended fresh-card path for a control machine and Raspberry Pis
flashed with Ubuntu Server 24.04 LTS (Noble). Keep wheels/tracks lifted and a
physical motor-power cutoff within reach for first motion.

## 1. Set up the control machine from a clone

A standalone clone is now adopted non-destructively into
`~/ros2_ws_dev/src/swarm_control_core`; the original checkout remains the
source of truth.

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/AEmilioDiStefano/swarm_control_core.git \
  "$HOME/swarm_control_core"
"$HOME/swarm_control_core/scripts/swarmc" setup --role control
```

Expected: dependency setup ends with `All dependencies are installed and up
to date`, and the bootstrap summary says `BUILD_STATUS = completed`.

## 2. Print and apply the Imager settings

```bash
~/.local/bin/swarmc imager-checklist
```

In Raspberry Pi Imager select Ubuntu Server 24.04 LTS (64-bit), use the unique
username/hostname printed by the checklist, configure the robot LAN, enable
SSH, and paste the entire printed `ssh-ed25519` key. Boot the Pi and allow a
few minutes for cloud-init.

## 3. Onboard from the control machine

Run the exact command printed by the checklist, for example:

```bash
~/.local/bin/swarmc new-robot robot4@legion4.local \
  --robot-ip 10.42.0.89 \
  --control-type diff_drive \
  --control-interface 4wheel_diff_l298n_2
```

The stock Noble image normally cannot answer `.local` yet. Obtain the Pi's
address from the router/DHCP lease list; the command uses that address but
verifies the expected hostname before provisioning the machine.

Onboarding installs/enables Avahi, verifies UI imports, verifies the actual
`lgpio.gpiochip_open()` path on the Pi, and records control/robot DDS peer IPs.
Use DHCP reservations on a multicast-filtered LAN so those IPs remain stable.

## 4. Bring up one robot, then the UI

Use a robot terminal (SSH by the transport IP printed at the end of
onboarding):

```bash
ssh robot4@10.42.0.89
~/.local/bin/swarmc step2 --robot-name robot4
```

Leave it running. On the control machine:

```bash
~/.local/bin/swarmc step3
```

In another control terminal:

```bash
~/.local/bin/swarmc step4
```

Step 4 must show the domain, `rmw_cyclonedds_cpp`, discovery range, recorded
peers, robot heartbeat/camera/cmd_vel topics, and the expected nodes.

## What “multicast failure” actually means here

There are two separate protocols:

1. `.local` is mDNS on UDP 5353. It affected SSH bootstrap before ROS started.
2. ROS 2 discovery is DDS. Core previously forced SUBNET multicast and erased
   static peers; systemd/raw launches could also silently use Fast DDS instead
   of CycloneDDS.

The repaired default is `hybrid`: CycloneDDS SUBNET discovery plus the direct
unicast peers recorded during onboarding. That already supplies the fallback
for multicast-filtered networks. To force a multicast-free test, stop any
running robot service and launch every robot/control process manually from a
shell containing:

```bash
export SWARM_CORE_DISCOVERY_MODE=static
eval "$(~/.local/bin/swarmc env)"
```

For CycloneDDS on Jazzy, static mode intentionally uses
`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` with `ROS_STATIC_PEERS`. Do not set
the range to `OFF`; that implementation ignores static peers in OFF mode.

If robot and control cannot reach one another by IP, first check that the robot
is online, its Wi-Fi settings are correct, both machines have a valid route,
and host/network firewalls permit the traffic. AP client isolation or separate
networks are also common causes. Software discovery settings cannot bypass
blocked unicast; use a private AP/Ethernet or change the network policy.
