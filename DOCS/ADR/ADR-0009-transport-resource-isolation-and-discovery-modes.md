# ADR-0009: Transport Resource Isolation And Optional Discovery Modes

- Status: Accepted
- Date: 2026-03-22
- Scope: `swarm_control_core` only

## Context

`swarm_control_core` must remain usable when one robot behaves poorly.

The problem is not only UI churn. A bad robot can also create pressure lower in the stack:

- camera bandwidth can consume more LAN or CPU budget than intended,
- multicast DDS discovery can create unnecessary churn in stable fleets,
- and video traffic can compete with control/liveness traffic for shared resources.

At the same time, `swarm_control_core` is intentionally easy to bring up:

- current default behavior is local/LAN auto-discovery,
- healthy robots already feel effectively zero-latency to the operator,
- and we do not want reliability improvements to make normal setup noticeably harder.

The design therefore needs two guardrails:

- preserve the current healthy two-robot operator experience,
- and make stronger containment features available without making them mandatory.

## Decision

Adopt a phased transport/resource-isolation strategy, from safest to riskiest.

Accepted sequence:

1. Soft robot-side video budgeting
   - let a struggling robot shed compressed-video cost first,
   - keep healthy robots at their configured quality,
   - prefer graceful local degradation over shared harm.

2. Control-over-video prioritization
   - continue treating control, liveness, and operator context as more important than background media freshness,
   - keep unhealthy robots from consuming healthy robots' UI/media budget.

3. Optional static-peer discovery mode
   - keep current multicast/subnet auto-discovery as the default,
   - add a stricter deterministic mode for stable known fleets.

4. Optional hard robot-side bandwidth shaping
   - only after the softer phases are proven safe,
   - and only as an explicit opt-in because it has the highest risk of self-inflicted latency if misapplied.

## Why This Works

This decision matches risk to rollout order.

Soft budgeting is the safest first move because it is local to one robot and can degrade only that robot's compressed video before affecting others.

Control-over-video prioritization is also low risk because it preserves the operator's main goal:

- control and awareness of healthy robots matter more than perfect video quality from an unhealthy robot.

Static peers are useful, but they trade convenience for determinism. That makes them a good optional mode, not a default.

Hard bandwidth shaping is the most powerful and the most dangerous. If introduced too early, it can throttle the wrong traffic and make latency worse instead of better.

## Operational Consequences

Expected behavior after the accepted low-risk phases:

- healthy robots should keep their current feel,
- a struggling robot may reduce its own compressed-video quality before it harms control,
- and one robot flapping should have less blast radius on the rest of the UI session.

Expected behavior once optional phases exist:

- operators can choose deterministic static-peer discovery for stable fleets,
- and advanced users can opt into hard egress shaping only when their network environment justifies it.

## Tradeoffs

- soft video budgeting can reduce image quality on a struggling robot,
- control-over-video prioritization can allow video to degrade before drive responsiveness does,
- static-peer discovery reduces plug-and-play convenience,
- and hard shaping increases operational complexity.

These tradeoffs are acceptable only if they do not regress the current healthy baseline.

## Defaults

Accepted default posture:

- keep current multicast/subnet discovery as default,
- keep healthy robot media settings unchanged unless the robot is already under pressure,
- keep hard shaping off by default,
- and ship stronger containment features as opt-in where the usability cost is meaningful.

## Release Gate

No phase is accepted if it introduces human-detectable control-latency regression compared with the current healthy `robot2 + robot3` baseline.

That release gate applies before enabling any new behavior by default.

## Related

- [ADR-0004: Interest-Driven Video Scaling for Multi-Robot FPV](./ADR-0004-interest-driven-video-scaling.md)
- [ADR-0005: Local/LAN Runtime Stabilization](./ADR-0005-runtime-stabilization.md)
- [ADR-0008: Per-Robot Fault Isolation In Local FPV Sessions](./ADR-0008-per-robot-fault-isolation.md)
- [TRANSPORT_RESOURCE_ISOLATION_CHECKLIST.md](../TRANSPORT_RESOURCE_ISOLATION_CHECKLIST.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
