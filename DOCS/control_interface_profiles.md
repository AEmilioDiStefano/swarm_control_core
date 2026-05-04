# Control Interface Profiles

Control interfaces describe the reusable hardware/control backend for a robot:
GPIO pins, motor-controller model, wheel-channel layout, safety parameters, and
the wiring guide. They are selected from `robot_instances.yaml` through the
`control_interface` field.

## Naming Convention

Canonical profile IDs use lowercase snake case:

```text
<controller_count>_<controller_model>_<drive_family>[_physical_layout]
```

Examples:

- `l298n_diff`
- `dual_l298n_diff`
- `dual_l298n_mecanum`
- `dual_tb6612_diff_4wheel_tracked`
- `dual_tb6612_mecanum`

Legacy mixed-case aliases such as `dual_L298N_diff` are accepted for backward
compatibility, and the old `dual_tb6612_diff` profile ID resolves as an alias
for `dual_tb6612_diff_4wheel_tracked`. New docs and robot entries should use
the canonical lowercase names.

## Required Metadata

Every `config/control_interfaces.yaml` entry should include:

- `compatible_control_types`: wizard/filter source of truth
- `backend`: backend schema registered in `interface_backends.py`, currently `gpio_hbridge`
- `wheel_layout`: `side_pair`, `front_pair`, or `four_wheel`
- `controller.model` and `controller.count`
- `docs.wiring`
- `gpio`
- `params`

This lets the add-robot wizard expose compatible hardware profiles without
hardcoded Python name checks.

## Add a New Interface

Preferred scaffold command shape (change the name, model, and pins for the new
hardware):

```bash
"$WS/src/swarm_control_core/scripts/swarm_core_add_control_interface.sh" \
  --name dual_newdriver_mecanum \
  --compatible-control-types mecanum_drive \
  --backend gpio_hbridge \
  --wheel-layout four_wheel \
  --controller-model NEWDRIVER \
  --controller-count 2 \
  --gpio fl_pwm=12 --gpio fl_in1=5 --gpio fl_in2=6 \
  --gpio fr_pwm=13 --gpio fr_in1=16 --gpio fr_in2=19 \
  --gpio rl_pwm=18 --gpio rl_in1=20 --gpio rl_in2=21 \
  --gpio rr_pwm=26 --gpio rr_in1=23 --gpio rr_in2=24 \
  --generate-wiring-doc
```

Then regenerate the GPIO index:

```bash
ros2 run swarm_control_core generate_profile_docs_core \
  --control-interfaces "$WS/src/swarm_control_core/config/control_interfaces.yaml" \
  --output "$WS/src/swarm_control_core/DOCS/GPIO/CONTROL_INTERFACE_INDEX.md"
```

Validate profiles:

```bash
ros2 run swarm_control_core validate_profiles_core \
  --control-types "$WS/src/swarm_control_core/config/control_types.yaml" \
  --control-interfaces "$WS/src/swarm_control_core/config/control_interfaces.yaml" \
  --package-root "$WS/src/swarm_control_core" \
  --check-docs-exist
```

## When Python Changes Are Still Needed

Adding a new motor-controller wiring profile should not require Python changes.

Python changes are still expected when adding a genuinely new runtime behavior,
such as:

- a new drive mixer beyond differential/mecanum
- a new backend beyond GPIO H-bridge output
- new safety behavior or diagnostics
- a new ROS topic/adapter contract
