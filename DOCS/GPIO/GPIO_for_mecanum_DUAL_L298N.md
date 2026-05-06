# GPIO connections from two L298N motor controllers to Raspberry Pi 4 for mecanum drive

This mapping is aligned to `mecanum_l298n_2.gpio` in
`config/control_interfaces.yaml`. It is intended for a four-wheel mecanum robot
where each wheel has its own L298N channel.

## Motor controller layout

Use two L298N boards:

- L298N #1 drives the front wheels:
  - Channel A -> front-left mecanum wheel
  - Channel B -> front-right mecanum wheel
- L298N #2 drives the rear wheels:
  - Channel A -> rear-left mecanum wheel
  - Channel B -> rear-right mecanum wheel

Do not wire two wheels in parallel into one channel. Mecanum drive needs
independent FL/FR/BL/BR wheel commands for strafe and diagonal movement.

## Raspberry Pi to L298N #1: front wheels

Front-left wheel, L298N #1 Channel A:

- `ENA` -> GPIO 12 (Pin 32)
- `IN1` -> GPIO 5 (Pin 29)
- `IN2` -> GPIO 6 (Pin 31)
- `OUT1` / `OUT2` -> front-left motor

Front-right wheel, L298N #1 Channel B:

- `ENB` -> GPIO 13 (Pin 33)
- `IN3` -> GPIO 16 (Pin 36)
- `IN4` -> GPIO 19 (Pin 35)
- `OUT3` / `OUT4` -> front-right motor

## Raspberry Pi to L298N #2: rear wheels

Rear-left wheel, L298N #2 Channel A:

- `ENA` -> GPIO 18 (Pin 12)
- `IN1` -> GPIO 20 (Pin 38)
- `IN2` -> GPIO 21 (Pin 40)
- `OUT1` / `OUT2` -> rear-left motor

Rear-right wheel, L298N #2 Channel B:

- `ENB` -> GPIO 26 (Pin 37)
- `IN3` -> GPIO 23 (Pin 16)
- `IN4` -> GPIO 24 (Pin 18)
- `OUT3` / `OUT4` -> rear-right motor

## Power and ground

- Remove the L298N `ENA` and `ENB` jumpers on both boards when using Pi PWM.
- Battery positive -> both L298N `+12V`, `VS`, or motor-power inputs.
- Battery negative -> both L298N `GND` terminals.
- Raspberry Pi `GND` -> common motor-power ground.
- Keep Raspberry Pi power separate from motor power.
- If the L298N `5V_EN` regulator jumper is installed, do not connect the L298N
  `5V` terminal to the Pi `5V` rail.

## Expected software behavior

The software treats this profile as a mecanum drive robot:

- forward -> all four wheels drive forward
- backward -> all four wheels drive backward
- rotate left/right -> left/right wheel pairs drive opposite directions
- strafe left/right -> diagonal wheel pairs drive opposite directions
- strafe diagonals -> two wheels drive while the opposite diagonal wheels stop

Run the wheel direction test before live operation:

```bash
"$WS/src/swarm_control_core/scripts/swarm_core_wheel_test.sh" --robot "$ROBOT_NAME"
```

Use `0` to toggle strafe mode, then test `4`, `6`, `7`, `9`, `1`, and `3`. If a
wheel is reversed, use `v` to toggle that wheel inversion and press `S` to save.
If the wrong wheel moves, use `c` to swap wheel channel mappings and press `S`
to save.
