# Security Policy

`swarm_control_core` is the community local/LAN package. In the current project split, the internet-facing and remote-operations-heavy workflows are generally handled in `swarm_control_pro`.

## Supported Scope

Security reports for this repository are most useful when they focus on issues such as:

- local/LAN authentication or authorization bypass
- unintended exposure of robot control APIs on non-local interfaces
- unsafe default configuration in the community package
- credential handling bugs in local development flows
- package boundary leaks that reintroduce remote/internet-facing behavior into `swarm_control_core`

## Reporting a Vulnerability

Please report suspected vulnerabilities privately to `opensource@vitruvian.systems`.

When possible, include:

- affected file(s) or feature(s)
- reproduction steps
- expected behavior
- observed behavior
- severity/impact assessment

## Notes On Scope

The following topics are usually handled in `swarm_control_pro` rather than this repository:

- internet ingress setup
- TURN/certificate/tunneling automation
- persistent remote operations services
- deployment-specific `swarm_control_pro` features

If you are unsure where something fits, it is still reasonable to ask first and sort out the boundary from there.
