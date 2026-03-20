# ADR-0005: Local/LAN Runtime Stabilization

- Status: Accepted
- Date: 2026-03-20
- Scope: `swarm_control_core` only

## Context

The strongest low-latency behavior came from fixing runtime instability at the control/robot boundary.

The failure pattern was consistent:

- one robot would work great,
- adding another robot caused major latency or black video,
- stale robots could linger in UI state,
- and behavior varied too much between shells/machines.

This suggested a mixed runtime problem involving DDS transport, stale shell overlays, UI active-robot state handling, and hidden background stream pressure.

## Decision

Stabilize the local/LAN runtime path first, and treat that as the foundation for all later video-quality tuning.

Accepted changes that produced the best low-latency behavior:

- Force a known-good community LAN transport path:
  - CycloneDDS,
  - multicast discovery defaults,
  - consistent control/robot launch behavior.
- Expand deep reset so bringup shells clear stale overlay/runtime variables before launching.
- Keep robot presence based on robot-originated evidence:
  - real camera publishers,
  - recent heartbeat freshness,
  - recent frame freshness,
  instead of controller-originated artifacts like local `cmd_vel` publishers.
- Keep UI active-robot changes and WebRTC session changes synchronized so roster churn does not silently desynchronize controls, main video, and selected robot state.
- Remove hidden background stream behavior as a default source of control-machine load:
  - interest-driven subscriptions,
  - bounded thumbnail work,
  - no implicit fallback warming beyond the explicit interest rules.
- Suppress benign aioice teardown race noise so real errors are easier to spot during field debugging.

## Why This Worked

These changes fixed the actual blockers:

- DDS/runtime consistency eliminated the "works in one shell, fails in another" class of latency bugs.
- Deep reset removed stale workspace contamination that could corrupt discovery/runtime behavior after repo/workspace switching.
- Real presence signals stopped ghost robots and stale selections from perturbing the UI.
- Active-robot/WebRTC alignment prevented switch churn from tearing down the wrong session or leaving the UI logically attached to the wrong robot.
- Removing hidden background stream pressure protected the control path when more robots appeared on the LAN.

The result was the first branch state where low-latency control felt consistently strong enough to be described as "it works" rather than merely "it regressed less."

## Tradeoffs

- The runtime is intentionally opinionated around a known-good local/LAN configuration rather than trying to auto-support every DDS/environment combination.
- Interest-driven video remains the default because full-fleet always-hot background video was one of the root causes of instability.
- Operators still need to use the reset/bootstrap flow correctly; this ADR improves that path, but does not remove the need for it.

## Operational Notes

- Use the deep reset step in the same shell that will run bringup.
- Treat stale underlay/overlay warnings as real operational risk, not harmless noise.
- When latency returns, check runtime state first:
  - reset/deep-reset usage,
  - DDS middleware/discovery mode,
  - presence/discovery correctness,
  - background stream load.

## Related

- [ADR-0001: Local Video Transport Strategy](./ADR-0001-local-video-transport.md)
- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR-0002-low-latency-switch-hardening.md)
- [ADR-0003: Benign aioice STUN Retry Race Handling](./ADR-0003-aioice-race-handling.md)
- [ADR-0004: Interest-Driven Video Scaling for Multi-Robot FPV](./ADR-0004-interest-driven-video-scaling.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
