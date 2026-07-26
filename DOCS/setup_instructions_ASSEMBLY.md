# Setup Instructions: Assembly

This guide describes the reference differential-drive robot assembly for
`swarm_control_core`.

After you complete this assembly guide and the companion robot onboarding
guide in [ADD_robot_pi.md](./ADD_robot_pi.md), you will be able to power on
one or more robots, launch local FPV/control, and drive from your control
machine on the same LAN.

If you already have compatible robot hardware, skip to
[ADD_robot_pi.md](./ADD_robot_pi.md).

# Direct Run Path

## Step 0: Confirm Scope

This assembly guide is for a Raspberry Pi based differential-drive robot using:

- a 2-channel L298N motor controller
- a USB camera for local FPV
- a left/right differential drive chassis

If you are building a different robot type, change the physical assembly and
match your local runtime config to that hardware before bringup.

## Step 1: Confirm Assumptions

- Ubuntu 24.04 will be installed on the robot computer
- ROS 2 Jazzy is the target ROS distribution
- `swarm_control_core` will be used in local/LAN mode only
- the reference software setup will use `ROS_DOMAIN_ID=17`

## Step 2: Gather Materials

- One Raspberry Pi 4 or newer Pi-class board with accessible GPIO
- One L298N motor controller
- One stable power source for the Pi
- One fused motor power path
- One on/off switch for the motor power path
- Motor batteries appropriate for the drivetrain
- One USB webcam
- Female-to-female jumper wires
- Male-to-female jumper wires
- One differential-drive chassis with two driven sides
- Mounting hardware and cable management supplies

## Step 3: Gather Tools

- Small screwdriver set
- Wire stripper or equivalent
- Tweezers
- Hot glue, standoffs, or equivalent mounting hardware

## Step 4: Prepare the Raspberry Pi SD Card

Flash Ubuntu 24.04 to the Pi SD card, enable the user/SSH settings you want,
and insert the card into the Pi.

Recommended:

- use a hostname that is easy to recognize on the LAN
- enable SSH during imaging so the robot can be reached remotely after first boot
- keep the robot on the same private LAN as the control machine

## Step 5: Wire the Pi to the L298N Controller

Connect Pi ground to motor-controller ground first and keep that common ground
through the whole build.

The default `swarm_control_core` reference wiring for `4wheel_diff_l298n_1` is:

| Drive side | Function | BCM GPIO | Physical pin |
| --- | --- | --- | --- |
| Side A | PWM / enable | `12` | `32` |
| Side A | direction 1 | `17` | `11` |
| Side A | direction 2 | `27` | `13` |
| Side B | PWM / enable | `13` | `33` |
| Side B | direction 1 | `22` | `15` |
| Side B | direction 2 | `23` | `16` |

Important notes:

- This mapping is chosen to match the current default `4wheel_diff_l298n_1` interface in
  [../config/control_interfaces.yaml](../config/control_interfaces.yaml).
- Treat one L298N motor channel as one side of the drivetrain and the other
  L298N motor channel as the opposite side.
- If you intentionally use a different GPIO mapping, update your machine-local
  `control_interfaces.yaml` before bringup instead of forcing the robot to match
  old wiring diagrams.
- Do not power the drivetrain motors from the Pi 5V rail.

## Step 6: Connect the Motors to the Controller

Connect one side of the drivetrain to one L298N output channel and the other
side to the other output channel.

For common four-wheel differential-drive chassis builds:

- use a four-channel control interface such as `4wheel_diff_l298n_2` or
  `4wheel_diff_tb6612fng_2`
- wire each physical motor to its own motor-controller output channel
- let the software mirror the left command to the left-front/left-rear motors
  and the right command to the right-front/right-rear motors
- make sure the current draw stays within the limits of the controller and power path

Do not connect two motors in parallel into one output channel unless you have
explicitly verified that the motor-controller channel, wiring, fuse, and battery
path are rated for the combined stall current.

Do not worry if one side later spins backward during software validation. That
can be corrected by:

- swapping that side's motor leads, or
- using a local polarity inversion in the runtime config

## Step 7: Complete Power and Mechanical Assembly

Finish the robot so it is electrically safe and mechanically stable before
software bringup.

Recommended reference layout:

- Pi powered from a stable Pi-safe 5V source
- drivetrain powered through a fused motor supply and switch
- motor-controller ground tied to Pi ground
- USB webcam mounted with a forward-facing view
- Pi, controller, batteries, and wiring secured to the chassis

Before moving on to software, verify:

- the Pi boots successfully
- the camera is physically connected
- no bare conductors can short against the chassis
- motor polarity and battery polarity have been checked
- wheels spin freely by hand
- the GPIO wiring matches the current `swarm_control_core` control-interface mapping

Next step:

- Continue to [ADD_robot_pi.md](./ADD_robot_pi.md)

# Alternative/Debug/Fix Reference

## Optional: Different Chassis Or Motor Controller

If you are building a robot that does not match this reference chassis, use the
matching GPIO wiring guide under [GPIO/](./GPIO/) and make the runtime
`control_interface` match the hardware before software bringup.

Then return to the software setup guide.
