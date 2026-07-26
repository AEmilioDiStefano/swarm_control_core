# Security

`swarm_control_core` is scoped to local/private-LAN operation. This document
describes the security model that scope implies, the concrete protections in
the package, and how to report a suspected vulnerability.

## Scope and Threat Model

- Core owns local robot bringup, the local FPV UI, private-LAN discovery,
  and reusable hardware/control profiles. It does not own internet ingress,
  remote operator access, or production authentication — those belong to a
  separate remote-operations layer by design.
- The private LAN is the current network perimeter: ROS 2/DDS traffic is not
  itself authenticated, so core must only be operated on networks you
  control. Nothing in core treats topic names, domain IDs, or robot names as
  secrets, and no security property depends on implementation obscurity.

## Protections In This Package

**Command authority is an allowlist, not discovery.** The control machine's
registered/approved robot registry is the only source of drive/autonomy
authority in the UI. Robots discovered over ROS but absent from the registry
stay read-only for video/diagnostics. Registration pulls each robot's saved
profile over SSH and validates it; profiles describe capability and never
grant authority.

**Weak lab auth fails closed.** The local-lab auth modes (`off`, `dev`)
refuse to start when non-loopback, tunnel, or gateway-style exposure is
requested, unless a deliberately loud override
(`SWARM_CORE_UNSAFE_ALLOW_WEAK_AUTH_NON_LOOPBACK=1`) is set. Non-local HTTP
Host headers are also rejected at request time while weak auth is active. A
lab shortcut cannot silently become an exposed deployment.

**SSH onboarding hygiene.** Robot onboarding generates an ed25519 key when
missing, pre-seeds it through the OS imager, and never places passwords in
command arguments. Stale host keys are cleared only for the specific robot
being (re-)enrolled. Onboarding refuses to target the machine it is running
on.

**Runtime state integrity.** Every write to the runtime configuration
directory (`~/.config/swarm_control_core/`) is serialized through an
advisory lock and lands atomically (temp file + rename) with owner-only
permissions (0600). A crash or a concurrent command can never truncate a
registry or leave a partially written trust file, and registry contents are
never world-readable.

**No secrets in the repository.** Runtime state, generated profiles, and
keys live under `~/.config/` and `~/.ssh/`, never in git. CI and the release
gate run on every merge to `main`, and `main` only advances through reviewed
pull requests with required checks.

**Bootstrap verification.** The first-contact bootstrap is fetched over
HTTPS from this repository's protected `main`. Each release tag embeds
`first_contact_sha256=<hash>` in its annotation; to verify a fetched copy,
compare `wget -qO- <raw-url> | sha256sum` against the value shown by
`git show <tag> --no-patch`.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately to:

`emilio@vitruvian.systems`

When possible, include:

- affected files or features
- reproduction steps
- expected behavior
- observed behavior
- impact assessment
- whether the issue is local/LAN only or could affect broader deployment

Please do not open a public issue for a suspected security vulnerability until
Vitruvian Systems LLC has had a reasonable opportunity to review it.
