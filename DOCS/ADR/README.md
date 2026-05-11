# swarm_control_core ADR Index

This folder contains Architecture Decision Records (ADRs) for swarm_control_core.

Use ADRs to track:
- the problem we needed to solve,
- the options we considered,
- the decision we made,
- why we believe it works,
- and what to monitor when operating the system.

Active ADRs:
- [ADR-0001: Local Video Transport Strategy (WebRTC-only main stream)](./ADR-0001-local-video-transport.md)
- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR-0002-low-latency-switch-hardening.md)
- [ADR-0003: Benign aioice STUN Retry Race Handling](./ADR-0003-aioice-race-handling.md)
- [ADR-0004: Interest-Driven Video Scaling for Multi-Robot FPV](./ADR-0004-interest-driven-video-scaling.md)
- [ADR-0005: Local/LAN Runtime Stabilization](./ADR-0005-runtime-stabilization.md)
- [ADR-0008: Per-Robot Fault Isolation In Local FPV Sessions](./ADR-0008-per-robot-fault-isolation.md)
- [ADR-0009: Transport Resource Isolation And Optional Discovery Modes](./ADR-0009-transport-resource-isolation-and-discovery-modes.md)
- [ADR-0010: Canonical Robot Registry and Generated Runtime Profiles](./ADR-0010-canonical-robot-registry.md)
- [ADR-0011: Metadata-Driven Control Interfaces](./ADR-0011-metadata-driven-control-interfaces.md)
- [ADR-0012: Portable GPIO Backends for Raspberry Pi and SBC Robots](./ADR-0012-portable-gpio-backends.md)

Companion validation doc:
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
- [TRANSPORT_RESOURCE_ISOLATION_CHECKLIST.md](../TRANSPORT_RESOURCE_ISOLATION_CHECKLIST.md)
