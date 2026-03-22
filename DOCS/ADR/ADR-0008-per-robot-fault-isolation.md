# ADR-0008: Per-Robot Fault Isolation In Local FPV Sessions

- Status: Accepted
- Date: 2026-03-22
- Scope: `swarm_control_core` only

## Context

`swarm_control_core` is meant to stay usable when one robot is unhealthy.

The observed failure pattern was unacceptable for field debugging:

- `robot2` and `robot3` could operate normally together,
- adding an unstable `robot1` degraded control/video for the whole session,
- stale robots could disappear and reappear in the roster,
- and restarting one robot could churn the UI enough that healthy robots felt worse.

That behavior defeats one of the main operational goals of a swarm UI:

- healthy robots must keep working even while one robot is being debugged, restarted, or flapping.

## Decision

Treat robot liveness, robot visibility, and robot media interest as separate concerns.

Accepted design changes:

- Keep a `visible` robot roster separate from the `live` robot roster.
  - `visible` means the UI should still show the robot.
  - `live` means recent heartbeat/frame evidence exists right now.
- Do not remove a robot from the roster immediately when it becomes stale.
  - Keep it visible long enough to diagnose it as degraded/stale instead of making the whole rail churn.
- Report per-robot presence state separately from per-robot camera state.
  - camera issues and heartbeat/liveness issues must be distinguishable.
- Prioritize healthy robots in background thumbnail refresh.
  - healthy live robots consume the passive refresh budget first,
  - unhealthy/stale robots are deprioritized and backed off individually.
- Apply failure backoff per robot, not globally.
  - a bad thumbnail path or stale camera should reduce retries for that robot only.
- Keep active-robot choice and roster reconciliation stable when one robot flaps.
  - one stale robot must not force unnecessary active-robot churn for the rest of the session.

## Why This Works

The old behavior mixed two different questions:

- "Should this robot still be shown to the operator?"
- "Should this robot still receive expensive background media attention right now?"

Those are not the same.

Separating them improves fault isolation:

- Stale robots remain visible for debugging instead of disappearing from the UI.
- Healthy robots keep their background refresh budget instead of losing it to a flapping peer.
- A failing robot's thumbnail retries back off independently instead of creating shared churn.
- Heartbeat/camera failures can be diagnosed per robot without removing the robot from operator context.
- Restarting one robot no longer needs to collapse the visible fleet roster.

## Operational Consequences

Expected behavior after this ADR:

- Healthy robots should remain controllable even if another robot is stale or restarting.
- A bad robot should stay visible in the roster/health panel as stale or degraded.
- Background thumbnail work should prefer healthy robots first.
- Operators can stop/start one robot while keeping the UI open and preserving context for the others.

## Tradeoffs

- Stale robots can remain visible in the UI longer than before by design.
- The roster now represents operator context, not only currently live robots.
- Background thumbnail updates for unhealthy robots may become sparse due to per-robot backoff.
- This ADR improves application-layer isolation, not absolute lower-layer network isolation.

## Limits

This does not guarantee perfect protection from every lower-layer failure.

Examples of residual shared risk:

- LAN congestion,
- DDS multicast behavior,
- host-level Wi-Fi instability,
- or OS/device-level camera problems.

Those can still affect healthy robots indirectly.

The design goal here is narrower and practical:

- one robot's bad application/media behavior should not make the whole UI session unusable.

## Related

- [ADR-0004: Interest-Driven Video Scaling for Multi-Robot FPV](./ADR-0004-interest-driven-video-scaling.md)
- [ADR-0005: Local/LAN Runtime Stabilization](./ADR-0005-runtime-stabilization.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
