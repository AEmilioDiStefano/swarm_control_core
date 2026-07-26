# Security

`swarm_control_core` is the public, source-available substrate for swarm
control: local robot bringup, the local FPV UI, private-LAN discovery, camera
publishing, teleop primitives, and reusable hardware/control profiles. It is
scoped to **local/private-LAN operation only**. This document states the
security model that scope implies, the concrete protections in this package,
and how to report a vulnerability.

Remote operation, operator authentication, ingress, and fleet trust machinery
are deliberately **not** in this repository; they belong to the separate
`swarm_control_pro` layer. That is a security decision, not just packaging —
see "Public-source posture" below.

## Scope and Threat Model

- **Operating perimeter is the private LAN.** ROS 2/DDS traffic is not itself
  authenticated, so core must only be run on networks you control. This is a
  stated assumption, not a defect: core is the local substrate, and wire-level
  identity (SROS2) is a pro/roadmap concern.
- **Nothing in core is a secret by obscurity.** Topic names, domain IDs, robot
  names, and profile names are not treated as confidential, and no security
  property depends on the source being private. An attacker who has read all
  of this public code should still gain no command authority over a robot they
  are not authorized to drive.
- **Out of scope for core:** internet exposure, remote operator identity,
  production authentication, TURN/ingress, and fleet enrollment trust. Core
  fails closed rather than pretending to provide these (see below).

## Protections In This Package

**Command authority is an allowlist, not discovery.** The registered/approved
robot registry is the only source of drive/autonomy authority in the UI.
Robots seen over ROS discovery but absent from the registry stay read-only for
video and diagnostics. Registration reads each robot's saved profile over SSH
and validates it; profiles describe capability and never grant authority.

**Weak lab auth fails closed.** The local-lab auth modes (`off`, `dev`) refuse
to start when non-loopback, tunnel, or gateway-style exposure is requested,
unless a deliberately loud override
(`SWARM_CORE_UNSAFE_ALLOW_WEAK_AUTH_NON_LOOPBACK=1`) is set. Non-local HTTP
`Host` headers are also rejected at request time while weak auth is active. A
lab shortcut cannot silently become an exposed deployment.

**No custom relay configuration in the community entrypoint.** The community
CLI hard-codes an empty WebRTC ICE server list and ignores ICE-related
environment variables and ROS parameters; TURN/STUN relay configuration is a
pro-layer capability injected only through an explicit code seam, never from
ambient process state. A regression test enforces that the community path
cannot read ICE configuration from the environment.

**SSH onboarding hygiene.** Robot onboarding generates an ed25519 key when
missing, pre-seeds it through the OS imager, and never places passwords in
command arguments. Stale host keys are cleared only for the specific robot
being (re-)enrolled. Onboarding refuses to target the machine it runs on.

**Runtime state integrity.** Every write to the runtime configuration
directory (`~/.config/swarm_control_core/`) is serialized through an advisory
lock and lands atomically (temp file + rename) with owner-only permissions
(0600). A crash or a concurrent command cannot truncate a registry or leave a
partially written trust file, and registry contents are never world-readable.

**No secrets in the repository.** Runtime state, generated profiles, and keys
live under `~/.config/` and `~/.ssh/`, never in git. A committed-secret scan
(`test/test_secret_scan.py`) runs in CI and fails the build on pasted private
keys, hard-coded API/auth secrets, or real-looking passwords in tracked files.

**Protected supply chain.** CI and the release gate run on every merge, and
`main` only advances through reviewed pull requests with required checks. The
release gate mechanically enforces the local-only boundary: it fails if
disallowed remote/topology/credential content appears in core.

**Bootstrap verification.** The first-contact bootstrap is fetched over HTTPS
from this repository's protected `main`. Each release tag embeds
`first_contact_sha256=<hash>` in its annotation; verify a fetched copy by
comparing `wget -qO- <raw-url> | sha256sum` against the value shown by
`git show <tag> --no-patch`.

## Public-source Posture

This repository is public but proprietary (see [LICENSE](../LICENSE)). Two
consequences shape its security:

- **Kerckhoffs's principle is the design rule.** Because anyone can read the
  code, the code's secrecy is never a security control. Fielded security must
  rest on credentials and keys held outside this repository, which is why
  remote authority and trust machinery live in `swarm_control_pro`.
- **Publishing a fix discloses the bug.** Security-relevant fixes to shared
  code are applied to fielded systems before the public core fix is pushed.
  This ordering is documented in the pro git workflow.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately to:

`emilio@vitruvian.systems`

When possible, include affected files or features, reproduction steps,
expected vs. observed behavior, an impact assessment, and whether the issue is
local/LAN only or could affect broader deployment. Please do not open a public
issue for a suspected security vulnerability until Vitruvian Systems LLC has
had a reasonable opportunity to review it.
