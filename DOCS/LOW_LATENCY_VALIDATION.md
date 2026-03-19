# swarm_control_core Low-Latency Validation

## Purpose

Provide a repeatable validation procedure for low-latency FPV/control behavior and record outcomes for engineering review.

## Baseline Assumptions

- Local/LAN deployment
- `ROS_DOMAIN_ID=17`
- WebRTC dependencies installed (`python3-aiortc`, `python3-av`)
- `swarm_fpv_ui` running in its default strict WebRTC-only main-stream mode
- Interest-driven balanced switch profile:
  - `SWARM_COM_IMAGE_SUBSCRIPTION_MODE=active_only`
  - `SWARM_COM_THUMB_ROBOTS_PER_TICK=1`
  - `SWARM_COM_THUMB_REFRESH_HZ=0.5`

## Validation Procedure

1. Start robots and UI using current quickstart.
2. Confirm transport state:
   - UI transport badge should show `WebRTC` for active robot once settled.
   - WebRTC diagnostics should show connected client state.
3. Drive-hold test:
   - Hold directional control for 10-15 seconds on each robot.
   - Verify smooth motion without pulse-stop behavior.
4. Switch test:
   - Switch active robot 10 times, including rapid consecutive clicks.
   - Verify no persistent blanking and reduced post-switch stall.
   - Brief settle windows are expected during renegotiation/handoff; repeated multi-second stalls are not.
5. Recovery test:
   - Briefly interrupt one robot stream (camera unplug/replug or process restart).
   - Verify main-pane outage is temporary and WebRTC recovers without manual restart.
6. Log review:
   - Confirm no recurring hard failures in UI process logs.
   - Benign aioice retry race messages should be suppressed.

## Suggested Data to Capture

- Active robot switch time (input to stable video)
- Per-robot frame-age and FPS values from UI health cards
- Observed control smoothness notes per platform
- WebRTC diagnostics snapshot (offers, peer connection counts, state counters)

## Acceptance Criteria

- Active robot typically reaches stable video quickly after switch.
- Control path remains responsive under sustained directional hold.
- Temporary negotiation disruption recovers without manual restart.
- Logs contain actionable errors only, not repeated benign callback noise.

## Related ADRs

- [ADR-0001: Local Video Transport Strategy](./ADR/ADR-0001-local-video-transport.md)
- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR/ADR-0002-low-latency-switch-hardening.md)
- [ADR-0003: Benign aioice STUN Retry Race Handling](./ADR/ADR-0003-aioice-race-handling.md)
