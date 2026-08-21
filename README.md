# `swarm_control_core`

Local/LAN FPV and robot control for ROS 2 fleets.

`swarm_control_core` provides low-latency first-person video, manual drive
control, and local fleet visibility on a private network. It focuses on
local/LAN operation, while `swarm_control_pro` covers the broader
remote-operations workflows used in the larger project.

> [!WARNING]
> `swarm_control_core` is experimental, operator-supervised lab software. It is
> not a safety-certified motion controller or emergency-stop system. Operate
> with an accessible physical motor-power cutoff, keep the motion area clear,
> and do not rely on a browser or terminal stop as the only way to halt a robot.

<p align="center">
  <img src="media/remote_operation_GIF.gif" alt="Remote operation demo"> <img src="media/playbook_two_robots_INITIAL.gif" alt="Playbook orchestration demo">
</p>

## Quick Start

For a fresh Ubuntu 24.04 control machine and freshly flashed Ubuntu 24.04 Pi,
start with the canonical
[Noble fresh-card guide](./DOCS/NOBLE_FRESH_INSTALL.md). It includes setup,
IP-first onboarding, camera/frame validation, safe retry, and the first local
browser FPV session.

For later live local FPV/control sessions on machines that are already
onboarded, use [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md).

If you are building and preparing the reference robot from scratch, start with:

1. [DOCS/setup_instructions_ASSEMBLY.md](./DOCS/setup_instructions_ASSEMBLY.md)
2. [DOCS/NOBLE_FRESH_INSTALL.md](./DOCS/NOBLE_FRESH_INSTALL.md)

## Supported Environment

- Ubuntu 24.04
- ROS 2 Jazzy
- Private LAN or direct local Wi-Fi deployment

## Runtime Rules

- Local/LAN operation only
- Standalone browser UI binds to loopback; the LAN is used for trusted ROS
  robot traffic, not unauthenticated browser exposure
- Trusted private LAN only: ROS 2/DDS traffic is not authenticated, and the UI
  robot registry does not authorize other processes on the DDS domain
- `ROS_DOMAIN_ID=17`
- No required `.bashrc` exports
- Dependency install is script-driven and idempotent
- Main video uses local WebRTC; thumbnail video is bounded to protect control
  latency
- Use only one active drive, playbook, or autonomy command source per robot;
  current Core does not arbitrate competing ROS command publishers
- Drive/playbook/motor numeric boundaries reject malformed and non-finite
  values; browser disconnect/deadman handling and the robot-side motor watchdog
  request zero independently. These are software safeguards, not an e-stop.

## Documentation

- Fresh Noble install: [DOCS/NOBLE_FRESH_INSTALL.md](./DOCS/NOBLE_FRESH_INSTALL.md)
- Quickstart: [DOCS/QUICKSTART.md](./DOCS/QUICKSTART.md)
- Control interface profiles: [DOCS/control_interface_profiles.md](./DOCS/control_interface_profiles.md)
- Assembly setup: [DOCS/setup_instructions_ASSEMBLY.md](./DOCS/setup_instructions_ASSEMBLY.md)
- GPIO wiring guides: [DOCS/GPIO/README.md](./DOCS/GPIO/README.md)
- Architecture: [DOCS/ARCHITECTURE.md](./DOCS/ARCHITECTURE.md)
- ADR index: [DOCS/ADR/README.md](./DOCS/ADR/README.md)
- Low-latency validation: [DOCS/LOW_LATENCY_VALIDATION.md](./DOCS/LOW_LATENCY_VALIDATION.md)
- Security model and reporting: [DOCS/SECURITY.md](./DOCS/SECURITY.md)
- Code of conduct: [DOCS/CODE_OF_CONDUCT.md](./DOCS/CODE_OF_CONDUCT.md)

## Repository Layout

- `swarm_control_core/`: ROS 2 Python package and UI server
- `swarm_launch/`: robot and UI launch files
- `scripts/`: bootstrap, reset, runtime, and release-gate tooling
- `config/`: canonical robot registry plus reusable control/interface/camera defaults
- `DOCS/`: runbooks, GPIO wiring guides, architecture notes, and ADRs

## Contribution Summary

Contributions are welcome.

Accepted contributions may be credited and may receive non-monetary
career-support benefits described in this repository. Contributors are not
entitled to financial compensation, royalties, or profit-sharing unless
separately agreed in writing.

See:

- [DOCS/CONTRIBUTING.md](./DOCS/CONTRIBUTING.md)
- [DOCS/CONTRIBUTOR_BENEFITS.md](./DOCS/CONTRIBUTOR_BENEFITS.md)
- [DOCS/CONTRIBUTORS.md](./DOCS/CONTRIBUTORS.md)

## License Summary

- Free for entities below USD $1,000,000 annual gross revenue, including
  commercial use while they remain below that threshold
- Commercial license required once the licensee and its Affiliates reach or
  exceed USD $1,000,000 annual gross revenue for continued commercial use

## Contact

- Commercial licensing: `emilio@vitruvian.systems`
- Security reports: see [DOCS/SECURITY.md](./DOCS/SECURITY.md)

<br>
<br>

<p align="center">
  <img src="media/hide-and-seek-GIF.gif" alt="Hide and seek demo">
</p>
