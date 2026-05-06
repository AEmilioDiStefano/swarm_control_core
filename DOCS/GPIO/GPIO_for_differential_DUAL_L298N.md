# GPIO connections from two L298N motor controllers to Raspberry Pi 4 for differential drive

This mapping is aligned to `4wheel_diff_l298n_2.gpio` in
`config/control_interfaces.yaml` and is intended for a four-motor differential
drive robot where each motor has its own L298N channel.

`robot4` uses this profile through `config/robot_instances.yaml`.

## Motor controller layout

Use two L298N boards:

- L298N #1 drives the left side:
  - Channel A -> left-front motor
  - Channel B -> left-rear motor
- L298N #2 drives the right side:
  - Channel A -> right-front motor
  - Channel B -> right-rear motor

Do not wire the two left motors in parallel into one channel, and do not wire
the two right motors in parallel into one channel. The purpose of this profile is
to split the four TT motors across four H-bridge channels.

## Raspberry Pi to L298N #1: left side

Left-front motor, L298N #1 Channel A:

- `ENA` -> GPIO 12 (Pin 32)
- `IN1` -> GPIO 5 (Pin 29)
- `IN2` -> GPIO 6 (Pin 31)
- `OUT1` / `OUT2` -> left-front motor

Left-rear motor, L298N #1 Channel B:

- `ENB` -> GPIO 18 (Pin 12)
- `IN3` -> GPIO 20 (Pin 38)
- `IN4` -> GPIO 21 (Pin 40)
- `OUT3` / `OUT4` -> left-rear motor

## Raspberry Pi to L298N #2: right side

Right-front motor, L298N #2 Channel A:

- `ENA` -> GPIO 13 (Pin 33)
- `IN1` -> GPIO 16 (Pin 36)
- `IN2` -> GPIO 19 (Pin 35)
- `OUT1` / `OUT2` -> right-front motor

Right-rear motor, L298N #2 Channel B:

- `ENB` -> GPIO 26 (Pin 37)
- `IN3` -> GPIO 23 (Pin 16)
- `IN4` -> GPIO 24 (Pin 18)
- `OUT3` / `OUT4` -> right-rear motor

## Power and ground

- Remove the L298N `ENA` and `ENB` jumpers on both boards when using Pi PWM.
- Battery positive -> both L298N `+12V`, `VS`, or motor-power inputs.
- Battery negative -> both L298N `GND` terminals.
- Raspberry Pi `GND` -> common motor-power ground.
- Keep Raspberry Pi power separate from motor power.
- If the L298N `5V_EN` regulator jumper is installed, do not connect the L298N
  `5V` terminal to the Pi `5V` rail.

## Expected software behavior

The software still treats `robot4` as a differential-drive robot:

- forward -> all four motors drive forward
- backward -> all four motors drive backward
- rotate left/right -> left-side motors and right-side motors drive opposite directions

The motor driver mirrors the left command to `left-front` and `left-rear`, and
mirrors the right command to `right-front` and `right-rear`.

If one wheel on a side fights the other wheel, reverse that motor's two output
wires at the L298N output terminal.
