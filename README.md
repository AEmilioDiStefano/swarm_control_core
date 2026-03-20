# `swarm_control_core`

Community local/LAN FPV and robot control for ROS 2 fleets.

`swarm_control_core` is the public, source-available community package for
low-latency first-person video, manual drive control, and local fleet
visibility on a private network. It focuses on local/LAN operation, while
`swarm_control_pro` covers the broader remote-operations workflows used in the
larger project.

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

## License Summary

- Free for personal use
- Free for academic and research use
- Free for internal evaluation
- Free for entities below USD $1,000,000 annual gross revenue, including
  commercial use while they remain below that threshold
- Commercial license required once the licensee and its Affiliates reach or
  exceed USD $1,000,000 annual gross revenue for continued commercial use

If you cross the USD $1,000,000 annual gross revenue threshold, see COMMERCIAL_LICENSE.md for the required notice
and transition procedure.

The legal terms are in [LICENSE](./LICENSE). Practical business-use guidance is
in [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md).



## Contribution Summary

Contributions are welcome.

Accepted contributions may be publicly credited and may receive non-monetary
career-support benefits described in this repository. Contributors are not
entitled to financial compensation, royalties, or profit-sharing unless
separately agreed in writing.

See:

- [CONTRIBUTING.md](./CONTRIBUTING.md)
- [CONTRIBUTOR_BENEFITS.md](./CONTRIBUTOR_BENEFITS.md)
- [CONTRIBUTORS.md](./CONTRIBUTORS.md)

## Quick Start

For the fastest path to a working local deployment:

1. Read the community quickstart in [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md).
2. Run workspace bootstrap plus deep reset in each terminal.
3. Bootstrap the control machine and each robot.
4. Launch robot bringup on the robots.
5. Launch the local FPV UI on the control machine.

If you are assembling a reference robot and want the longer hardware plus
software walkthrough, use [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md) as the
main guide.

## Supported Environment

- Ubuntu 24.04
- ROS 2 Jazzy
- Private LAN or direct local Wi-Fi deployment

## Runtime Rules

- Local/LAN operation only
- `ROS_DOMAIN_ID=17`
- No required `.bashrc` exports
- Dependency install is script-driven and idempotent
- Main video uses local WebRTC; thumbnail video is bounded to protect control
  latency

## Documentation

- Quickstart: [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md)
- Architecture: [DOCS/ARCHITECTURE.md](./DOCS/ARCHITECTURE.md)
- Community boundary: [DOCS/COMMUNITY_BOUNDARY.md](./DOCS/COMMUNITY_BOUNDARY.md)
- ADR index: [DOCS/ADR/README.md](./DOCS/ADR/README.md)
- Low-latency validation: [DOCS/LOW_LATENCY_VALIDATION.md](./DOCS/LOW_LATENCY_VALIDATION.md)
- Security policy: [SECURITY.md](./SECURITY.md)
- Code of conduct: [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)

## Repository Layout

- `swarm_control_core/`: ROS 2 Python package and UI server
- `launch/`: robot and UI launch files
- `scripts/`: bootstrap, reset, runtime, and release-gate tooling
- `config/`: baseline robot/control/capability profile templates
- `DOCS/`: runbooks, architecture notes, and ADRs

## Contact

- Commercial licensing: `emilio@vitruvian.systems`
- Security reports: see [SECURITY.md](./SECURITY.md)
