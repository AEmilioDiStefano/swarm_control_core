# ADR-0004: Interest-Driven Video Scaling for Multi-Robot FPV

- Status: Accepted
- Date: 2026-03-16
- Scope: `swarm_control_core` only

## Context

As robot count increased, control-node latency regressed because the UI bridge subscribed to all robot camera streams continuously and repeatedly decoded frames under multi-client WebRTC load.

This created compounding CPU/network pressure during mixed operations (active teleop + background thumbnails + health polling).

## Decision

Adopt an interest-driven camera pipeline in `swarm_fpv_ui`:

- Default `image_subscription_mode=active_only`.
- Keep camera subscriptions for:
  - active robot stream,
  - short-lived on-demand thumbnail interest windows.
- Unsubscribe non-interest robots to reduce continuous DDS camera traffic into control.
- Round-robin thumbnail refresh with bounded budget (`thumb_robots_per_tick`) instead of refreshing all non-active robots every tick.
- Safety floor: when `thumb_robots_per_tick=0`, client thumbnail refresh stays in sparse minimal-liveness mode (one stale tile per tick) so fleet tiles do not stay permanently black.
- Cache decoded RGB frame per robot by frame-stamp to avoid re-decoding the same JPEG for each WebRTC recv/client.
- Cache camera-health snapshots briefly to reduce repeated expensive graph/health calculations under multi-client polling.

## Why This Works

Hot-path complexity changes:

- Previous camera ingress pressure: `O(R * F * B)`
  - `R`: discovered robots
  - `F`: camera FPS
  - `B`: per-frame bytes
- New ingress pressure (default): `O((A + K) * F * B)`
  - `A`: active robots (typically `1`)
  - `K`: thumbnail interest budget (low-latency mode is typically `K=1` effective)

Decode path changes:

- Previous decode work (compressed path): `O(C * W)` per active robot stream
  - `C`: WebRTC consumers
  - `W`: WebRTC pacing FPS
- New decode work: `O(F)` per active robot stream
  - decode once per source frame, then reuse cached RGB for consumers.

## Tradeoffs

- Non-active thumbnails update less frequently by design.
- First thumbnail request for an unsubscribed robot may show one warm-up miss before frames arrive.
- Active robot switches incur a short settle window because main-stream WebRTC renegotiation and
  interest-driven subscription handoff occur together.
- Operators wanting all streams always-on can switch to `image_subscription_mode=all` (higher load).
- LAN discovery precondition still applies: if host firewall blocks DDS (for example active `ufw` defaults),
  camera/control can appear "missing" even when robot camera nodes are publishing locally.

## Operational Knobs

- `SWARM_CORE_IMAGE_SUBSCRIPTION_MODE` (`active_only` default, optional `all`)
- `SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S` (`6.0` default; runtime also applies a dynamic lower bound from `thumb_refresh_hz` and `thumb_robots_per_tick` to prevent subscription flapping)
- `SWARM_CORE_THUMB_ROBOTS_PER_TICK` (`1` balanced default for multi-robot switching; `0` is single-robot focus mode with lower background load but slower switches)
- `SWARM_CORE_WEBRTC_FPS` (`15.0` default)
- Main pane is always strict WebRTC-only
- `SWARM_CORE_THUMB_REFRESH_HZ` (`0.5` default)
- `swarm_core_reset_env.sh` clears these tuning env vars to prevent stale cross-session carryover.
- Core runtime knobs are scoped to `SWARM_CORE_*`; proprietary env names are not used for core runtime behavior.
- `swarm_core_run_robot.sh` / `swarm_core_run_local_ui.sh` invoke
  `swarm_core_terminate_existing_robot_processes.sh` in compat mode by default.
- In compat mode, temporary `ufw` stop behavior is controlled by
  `SWARM_CORE_COMPAT_STOP_UFW` (or `--compat-stop-ufw`) with `auto`,
  `always`, and `never` options.
- Quickstart robot setup includes an idempotent Wi-Fi power-save step:
  if `wlan0` power save is ON, it is set OFF before bringup.

## Related

- [ADR-0001: Local Video Transport Strategy](./ADR-0001-local-video-transport.md)
- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR-0002-low-latency-switch-hardening.md)
- [ADR-0005: Local/LAN Runtime Stabilization](./ADR-0005-runtime-stabilization.md)
- [LOW_LATENCY_VALIDATION.md](../LOW_LATENCY_VALIDATION.md)
