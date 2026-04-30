# GPIO connections from L298N motor controller to Raspberry Pi 4 for differential drive chassis

This mapping is aligned to `l298n_diff.gpio` in
`config/control_interfaces.yaml` and should be treated as authoritative for this package.

Left motor channel:

- `ENA` -> GPIO 12 (Pin 32, PWM0)
- `IN1` -> GPIO 17 (Pin 11)
- `IN2` -> GPIO 27 (Pin 13)

Right motor channel:

- `ENB` -> GPIO 13 (Pin 33, PWM1)
- `IN3` -> GPIO 22 (Pin 15)
- `IN4` -> GPIO 23 (Pin 16)

Power/ground reminders:

- Share ground between Raspberry Pi and motor power ground.
- Keep motor supply wiring sized appropriately for current draw.
