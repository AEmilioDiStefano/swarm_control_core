# ADR-0011: Metadata-Driven Control Interfaces

Status: Accepted

## Context

Adding a new motor-controller profile previously required edits in several
places: `control_interfaces.yaml`, wizard filtering code, profile-specific
tests, quickstart examples, and wiring docs. That made normal hardware-profile
work feel like a code change even when the runtime behavior already existed.

The immediate trigger was adding a mecanum profile for two L298N boards. The
runtime already supported four-channel mecanum output, but the package still
needed Python edits so the wizard could discover the new profile.

## Decision

Control interface compatibility and schema details now live in
`config/control_interfaces.yaml`.

Each interface declares:

- canonical lowercase snake-case ID
- optional legacy `aliases`
- `compatible_control_types`
- `backend`
- `wheel_layout`
- `controller`
- `docs.wiring`
- `gpio`
- `params`

Python uses this metadata to:

- resolve legacy aliases to canonical names
- filter wizard choices by `compatible_control_types`
- validate profile schemas generically
- generate the GPIO/control-interface index from YAML

The canonical naming convention is lowercase snake case, such as
`dual_l298n_mecanum`. Existing mixed-case names such as `dual_L298N_mecanum`
remain aliases for backward compatibility.

## Consequences

Adding another GPIO H-bridge motor-controller profile should usually require:

1. one `control_interfaces.yaml` entry
2. an optional wiring doc
3. regenerated profile docs
4. generic validation

It should not require edits to wizard code or profile-specific Python tests.

New drive mixers or new backend families still require Python, because those
change runtime behavior rather than profile metadata. They should be registered
through `drive_types.py` or `interface_backends.py` instead of adding one-off
conditionals around profile names.

## Validation

Use:

```bash
ros2 run swarm_control_core validate_profiles_core \
  --control-types "$WS/src/swarm_control_core/config/control_types.yaml" \
  --control-interfaces "$WS/src/swarm_control_core/config/control_interfaces.yaml" \
  --package-root "$WS/src/swarm_control_core" \
  --check-docs-exist
```

Regenerate profile docs with:

```bash
ros2 run swarm_control_core generate_profile_docs_core \
  --control-interfaces "$WS/src/swarm_control_core/config/control_interfaces.yaml" \
  --output "$WS/src/swarm_control_core/DOCS/GPIO/CONTROL_INTERFACE_INDEX.md"
```
