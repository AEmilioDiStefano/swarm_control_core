# `swarm_control_core`

Source-available local/LAN FPV and robot control for ROS 2 fleets.

`swarm_control_core` is the public, source-available package for
low-latency first-person video, manual drive control, and local fleet
visibility on a private network. It focuses on local/LAN operation, while
`swarm_control_pro` covers the broader remote-operations workflows used in the
larger project.

<p align="center">
  <img src="media/remote_operation_GIF.gif" alt="Remote operation demo"> <img src="media/playbook_two_robots_INITIAL.gif" alt="Playbook orchestration demo">
</p>

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

For a live local FPV/control session, use [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md).

If you are building and preparing the reference robot from scratch, start with:

1. [DOCS/setup_instructions_ASSEMBLY.md](./DOCS/setup_instructions_ASSEMBLY.md)
2. [DOCS/setup_instructions_SOFTWARE.md](./DOCS/setup_instructions_SOFTWARE.md)
3. [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md)

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
- Add/update robots: [DOCS/add_robot.md](./DOCS/add_robot.md)
- Assembly setup: [DOCS/setup_instructions_ASSEMBLY.md](./DOCS/setup_instructions_ASSEMBLY.md)
- Software setup: [DOCS/setup_instructions_SOFTWARE.md](./DOCS/setup_instructions_SOFTWARE.md)
- GPIO wiring guides: [DOCS/GPIO/README.md](./DOCS/GPIO/README.md)
- Architecture: [DOCS/ARCHITECTURE.md](./DOCS/ARCHITECTURE.md)
- ADR index: [DOCS/ADR/README.md](./DOCS/ADR/README.md)
- Low-latency validation: [DOCS/LOW_LATENCY_VALIDATION.md](./DOCS/LOW_LATENCY_VALIDATION.md)
- Security policy: [SECURITY.md](./SECURITY.md)
- Code of conduct: [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)

## Repository Layout

- `swarm_control_core/`: ROS 2 Python package and UI server
- `swarm_launch/`: robot and UI launch files
- `scripts/`: bootstrap, reset, runtime, and release-gate tooling
- `config/`: canonical robot registry plus reusable control/interface/camera defaults
- `DOCS/`: runbooks, GPIO wiring guides, architecture notes, and ADRs

## Contact

- Commercial licensing: `emilio@vitruvian.systems`
- Security reports: see [SECURITY.md](./SECURITY.md)

<br>
<br>

<p align="center">
  <img src="media/hide-and-seek-GIF.gif" alt="Hide and seek demo">
</p>
