# Contributing

Thanks for helping improve `swarm_control_core`.

## Ground Rules

- Keep `swarm_control_core` scoped to local/LAN operation.
- If you are proposing public internet ingress, cloud control plane features, TURN/certificate automation, or persistent remote-operations ownership flows, coordinate first since that work may fit better in `swarm_control_pro`.
- Prefer small, reviewable pull requests with clear user-facing motivation.
- Update docs when runtime behavior or operator workflow changes.

## Development Notes

- Target environment: Ubuntu 24.04 + ROS 2 Jazzy
- Build the package with:

```bash
colcon build --packages-select swarm_control_core
```

- Run tests with:

```bash
pytest -q src/swarm_control_core/test
```

## Before Opening a PR

- make sure the package builds cleanly
- run the relevant tests
- keep the community/pro boundary intact
- update ADRs or docs when the change affects architecture, runtime assumptions, or operator workflow

## Issue Reports

Useful issue reports usually include:

- what you were trying to do
- machine role(s) involved: control, robot, or both
- exact command(s) used
- observed logs or screenshots
- expected behavior
