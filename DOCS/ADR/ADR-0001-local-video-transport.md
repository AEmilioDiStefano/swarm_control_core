# ADR-0001: Local Video Transport Strategy (WebRTC-Only Main Stream)

- Status: Accepted
- Date: 2026-03-13
- Scope: `swarm_control_core` only

## Context

Local operation needs low-latency operator video while avoiding duplicated main-stream transport paths that increase runtime load and jitter under multi-robot control.

## Decision

- Use local WebRTC as the only main-stream transport path.
- Keep JPEG polling for thumbnail rail updates only (non-active robots).
- Do not auto-switch the main pane into JPEG fallback when WebRTC negotiation fails.

## Why This Works

- WebRTC delivers lower end-to-end latency than JPEG polling in local control loops.
- Removing main-pane fallback avoids competing decode/render paths and simplifies failure behavior.
- Operators get deterministic behavior: active pane is always WebRTC, while thumbnails remain low-cost JPEG polls.

## Tradeoffs

- Temporary WebRTC failures now surface as explicit main-pane outages until WebRTC recovers.
- Thumbnail rail may still update while main-pane WebRTC is re-establishing, which can appear asymmetric.

## Operational Notes

- `TURN entries: 0` is expected in many local runs where direct connectivity succeeds.
- TURN is typically required for restrictive NAT/WAN cases, not for same-LAN paths.
- `SWARM_COM_WEBRTC_MAIN_ONLY=1` is the default strict mode for community quickstart.

## Related

- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR-0002-low-latency-switch-hardening.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
