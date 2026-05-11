# ADR-0012: Portable GPIO Backends for Raspberry Pi and SBC Robots

Status: Accepted

## Context

The original motor hardware layer imported `RPi.GPIO` directly and dependency
installation pulled `python3-rpi.gpio` for robot machines. That worked for many
Raspberry Pi 4 deployments, but a robotics club member hit GPIO failures while
running a robot on Raspberry Pi 5.

Raspberry Pi 5 moved GPIO access toward the Linux gpiochip character-device
path. On current Raspberry Pi OS and Ubuntu images, the older direct
`RPi.GPIO` path can fail or behave inconsistently. At the same time, we still
need to preserve working Raspberry Pi 4 robots and avoid making every existing
motor profile or wheel-test workflow change at once.

The swarm should also be allowed to contain mixed robot hardware:

- Raspberry Pi 4 robots
- Raspberry Pi 5 robots
- future Pi-class boards
- other SBCs that expose Linux gpiochip-compatible GPIO

The software should choose the best available local GPIO backend per robot
without making the ROS graph, profile schema, or control-machine registry care
which SBC is underneath a given robot.

## Decision

Introduce a small GPIO backend-selection layer behind the existing
`HardwareInterface` API.

The motor layer continues to use the same minimal RPi.GPIO-shaped operations:

- `setmode`
- `setwarnings`
- `setup`
- `output`
- `PWM(...).start(...)`
- `PWM(...).ChangeDutyCycle(...)`
- `cleanup`

The backend adapter now chooses the first usable backend in this order:

1. `lgpio`
2. `gpiozero` using its `LGPIOFactory`
3. `RPi.GPIO`, including environments where the compatibility provider is
   `rpi-lgpio`
4. mock mode when no GPIO backend is available

The backend selection is local to each robot. A mixed swarm can therefore run
one robot through `lgpio`, another through `RPi.GPIO`, and a desktop/laptop
simulation through mock mode while all robots keep the same ROS topics and
profile schema.

Robot dependency installation now installs the gpiochip-oriented dependencies
for robot machines:

- `python3-lgpio`
- `python3-gpiozero`

Existing `RPi.GPIO` or `rpi-lgpio` installs can still be used as a fallback, but
they are no longer the preferred backend.

Two environment variables provide operator escape hatches:

- `SWARM_GPIO_BACKEND=lgpio|gpiozero|rpi_gpio`
- `SWARM_GPIOCHIP=<number>`

`SWARM_GPIOCHIP` is especially useful on systems where the GPIO chip number is
different from the common Raspberry Pi defaults.

## Consequences

Raspberry Pi 5 robots should use the gpiochip-compatible `lgpio` path instead
of failing through the old direct `RPi.GPIO` assumption.

Raspberry Pi 4 robots continue to work. They can use `lgpio` when available,
`gpiozero` when that path is available, or their existing `RPi.GPIO`/`rpi-lgpio`
setup.

The control-machine registry, ROS discovery mode, UI trust model, and robot
profile schema do not need SBC-specific branches. Hardware differences remain
inside the robot-local hardware interface.

The code keeps compatibility with the existing motor output logic, so the
initial migration does not require rewriting all H-bridge control through
GPIO Zero's object model.

Mixed-SBC swarms still need per-robot validation. The backend abstraction does
not remove the need to verify:

- GPIO pin numbering and wiring
- gpiochip numbering
- PWM behavior under the selected backend
- camera device identity
- power and thermal behavior

## Alternatives Considered

### Keep `RPi.GPIO` Only

Rejected. It leaves Raspberry Pi 5 users exposed to a known compatibility
problem and keeps robot support tied to one historical GPIO stack.

### Replace Everything with GPIO Zero

Deferred. GPIO Zero is a good high-level API and remains supported as a backend,
but rewriting the motor layer directly around GPIO Zero would be a larger
behavioral change. The current motor layer only needs a small output/PWM API,
so a backend adapter is less disruptive.

### Use Only `rpi-lgpio`

Rejected as the sole answer. `rpi-lgpio` is useful because it preserves the
`RPi.GPIO` import shape on gpiochip systems, but it conflicts with the original
`RPi.GPIO` package in the same Python environment and does not give us a clean
path for non-Pi SBCs. It remains valid as a fallback compatibility provider.

### Use Only `lgpio`

Rejected as the sole answer. It is the preferred modern backend, but keeping
fallbacks preserves older working robots and makes laptop/mock development
friendlier.

## Operational Notes

Robot bringup logs should report which GPIO backend initialized. If GPIO
initialization falls back to mock mode on a physical robot, treat that as a
setup failure before driving.

For Raspberry Pi 5, a useful diagnostic override is:

```bash
SWARM_GPIOCHIP=4
```

To force a backend during diagnosis:

```bash
SWARM_GPIO_BACKEND=lgpio
SWARM_GPIO_BACKEND=gpiozero
SWARM_GPIO_BACKEND=rpi_gpio
```

## Validation

Before trusting a robot for live driving:

1. run the software setup dependency step on the robot;
2. confirm `python3-lgpio` and `python3-gpiozero` are installed;
3. start robot bringup and confirm the log reports a real GPIO backend;
4. run the wheel test for that robot;
5. save any per-robot GPIO direction/order fixes into the robot profile;
6. verify camera profile selection separately.

Run focused software checks after changes to this layer:

```bash
python3 -m py_compile \
  swarm_control_core/swarm_control_core/gpio_backend.py \
  swarm_control_core/swarm_control_core/hardware_interface.py

PYTHONPATH="$WS/src/swarm_control_core" \
  pytest -q swarm_control_core/test/test_4wheel_diff_l298n_2_profile.py
```

