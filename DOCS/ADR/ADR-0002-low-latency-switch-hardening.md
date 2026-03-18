# ADR-0002: Low-Latency Robot-Switch Hardening

- Status: Accepted
- Date: 2026-03-13
- Scope: `swarm_control_core` only

## Context

Even with WebRTC enabled, switching between robots could produce visible stalls and stale in-flight negotiations.

## Decision

Add coordinated switch hardening in UI control logic:

- debounce rapid local robot selections,
- apply a short switch grace window before changing main-pane transport/placeholder paint,
- serialize WebRTC setup attempts,
- cancel stale in-flight offer requests on switch,
- reject stale negotiation completions using per-switch nonce checks,
- retry quickly after transient failure (instead of permanently disabling WebRTC).

## Why This Works

- Debounce prevents redundant renegotiations from rapid UI interactions.
- Grace window avoids immediate transport flicker right after a switch.
- Abort + nonce checks prevent stale offers/answers from attaching to the wrong active robot.
- Retry behavior improves resilience under brief packet loss or timing races.

## Tradeoffs

- More stateful client logic.
- Slightly higher code complexity in switch/transport paths.

## Tuning Knobs

Current defaults:

- `ROBOT_SWITCH_DEBOUNCE_MS=140`
- `ROBOT_SWITCH_GRACE_MS=500`
- `WEBRTC_RETRY_INTERVAL_MS=900`

Adjust based on observed switch latency, camera startup behavior, and operator UX goals.

## Related

- [ADR-0001: Local Video Transport Strategy](./ADR-0001-local-video-transport.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
