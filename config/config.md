# swarm_control_core config

This directory contains the baseline profile templates for local
`swarm_control_core` operation. Runtime setup scripts copy these templates into
machine-local config under `~/.config/swarm_control_core/`.

## Files

| File | Role |
| --- | --- |
| `robot_instances.yaml` | Robot registry and profile entrypoint. Each controllable robot should have one explicit robot key. |
| `control_types.yaml` | Reusable movement templates such as differential and mecanum drive. |
| `control_interfaces.yaml` | Reusable hardware interface templates such as GPIO pins, motor driver model, wheel layout, and wiring guide. |
| `camera_profiles.yaml` | Camera defaults and per-robot camera overrides when needed. |

## Profile Rule

Add a robot by creating or updating one entry in `robot_instances.yaml`, then
select existing reusable profiles. Only add a new profile when the hardware or
movement behavior is genuinely new.

Use `control_types.yaml` and `control_interfaces.yaml` as the profile catalog.
Use the setup guide and YAML `docs.wiring` fields for examples and wiring maps:

- `DOCS/ADD_robot_pi.md`
- `DOCS/GPIO/CONTROL_INTERFACE_INDEX.md`
