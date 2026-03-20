# `swarm_control_core`

Community local/LAN FPV and robot control for ROS 2 fleets.

`swarm_control_core` is the open-source community package for low-latency first-person video, manual drive control, and local fleet visibility on a private network. Its current focus is local/LAN operation, while `swarm_control_pro` covers the more remote-operations-oriented workflows used in the broader project.

![demo](media/hide-and-seek-GIF.gif)

## What This Is

- Local/LAN FPV and robot control for ROS 2 fleets
- WebRTC main-view streaming with operator-focused fleet UI
- Community-friendly launch/bootstrap scripts for control machines and robots
- Runtime profiles for diff-drive and mecanum robots
- Local-only workflow with no required cloud control plane

## What This Is Not

- Public internet or WAN ingress
- TURN/certificate/tunneling automation
- Persistent robot services that auto-own the machine at boot
- Remote operations/security orchestration

Those capabilities are generally handled in `swarm_control_pro` today.

## Quick Start

For the fastest path to a working local deployment:

1. Read the community quickstart in [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md).
2. Run workspace bootstrap plus deep reset in each terminal.
3. Bootstrap the control machine and each robot.
4. Launch robot bringup on the robots.
5. Launch the local FPV UI on the control machine.

If you are assembling a reference robot and want the longer hardware + software walkthrough, use [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md) as the main guide.

## Supported Environment

- Ubuntu 24.04
- ROS 2 Jazzy
- Private LAN or direct local Wi-Fi deployment

## Runtime Rules

- Local/LAN operation only
- `ROS_DOMAIN_ID=17`
- No required `.bashrc` exports
- Dependency install is script-driven and idempotent
- Main video uses local WebRTC; thumbnail video is bounded to protect control latency

## Documentation

- Quickstart: [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md)
- Architecture: [DOCS/ARCHITECTURE.md](./DOCS/ARCHITECTURE.md)
- Community boundary: [DOCS/COMMUNITY_BOUNDARY.md](./DOCS/COMMUNITY_BOUNDARY.md)
- ADR index: [DOCS/ADR/README.md](./DOCS/ADR/README.md)
- Low-latency validation: [DOCS/LOW_LATENCY_VALIDATION.md](./DOCS/LOW_LATENCY_VALIDATION.md)

## Repository Layout

- `swarm_control_core/`: ROS 2 Python package and UI server
- `launch/`: robot and UI launch files
- `scripts/`: bootstrap, reset, runtime, and release-gate tooling
- `config/`: baseline robot/control/capability profile templates
- `DOCS/`: runbooks, architecture notes, and ADRs

## Release Boundary

This repository is the community edition. It is designed for:

- local operator-driven robot control
- local FPV
- community experimentation on private networks

This repository is the community-facing local/LAN package in the current project split. In practice, features like public ingress, persistent operational ownership of the robots, and stronger remote security controls are usually developed in `swarm_control_pro`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Security

See [SECURITY.md](./SECURITY.md).

## License

Apache-2.0. See [LICENSE](./LICENSE).
