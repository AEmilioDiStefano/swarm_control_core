# swarm_control_core Transport And Resource Isolation Checklist

## Guardrail

Do not ship any phase if it makes the existing `robot2` + `robot3` experience feel worse.

Non-regression requirement:

- no human-detectable control-latency regression versus the current healthy two-robot baseline,
- no new persistent blanking in the active pane,
- no new multi-second switch stalls,
- and no loss of current plug-and-play usability unless the feature is explicitly optional.

## Phase 0: Architecture + Acceptance Gates

- Status: Implemented
- Risk: Lowest
- Purpose: lock in the design goals and regression gates before changing runtime behavior

Files:

- [ADR-0008-per-robot-fault-isolation.md](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/ADR/ADR-0008-per-robot-fault-isolation.md)
- [ADR-0009-transport-resource-isolation-and-discovery-modes.md](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/ADR/ADR-0009-transport-resource-isolation-and-discovery-modes.md)
- [ADR README](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/ADR/README.md)
- [LOW_LATENCY_VALIDATION.md](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/LOW_LATENCY_VALIDATION.md)

Env vars:

- none

Default vs optional:

- no runtime changes

Acceptance tests:

- `robot2 + robot3` healthy baseline still passes existing quickstart flow
- one robot can flap/restart without forcing healthy robots out of the UI roster
- low-latency validation doc remains the release gate for future phases

## Phase 1: Soft Robot-Side Video Budgeting

- Status: Implemented
- Risk: Low
- Purpose: let a struggling robot shed compressed-video cost before it harms control or other robots

Files:

- [camera_runtime_defaults.py](/home/aemilio/ros2_ws_dev/src/swarm_control_core/swarm_control_core/camera_runtime_defaults.py)
- [camera_adapter.py](/home/aemilio/ros2_ws_dev/src/swarm_control_core/swarm_control_core/camera_adapter.py)
- [swarm_bringup.launch.py](/home/aemilio/ros2_ws_dev/src/swarm_control_core/launch/swarm_bringup.launch.py)
- [test_camera_runtime_defaults.py](/home/aemilio/ros2_ws_dev/src/swarm_control_core/test/test_camera_runtime_defaults.py)

Env vars:

- `SWARM_CORE_CAMERA_JPEG_QUALITY`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG_MIN_QUALITY`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG_STEP`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG_OVERLOAD_RATIO`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG_ENCODE_RATIO`
- `SWARM_CORE_CAMERA_ADAPTIVE_JPEG_RECOVER_AFTER_S`

Default vs optional:

- default:
  - adaptive JPEG load shedding enabled
  - healthy robots stay at their configured JPEG quality
- optional:
  - all knobs above may be overridden per robot

Acceptance tests:

- healthy `robot2 + robot3` run looks the same as before
- when one robot camera path is stressed, only that robot's compressed-video quality drops
- control responsiveness remains unchanged while the stressed robot degrades video first
- camera diagnostics report `jpeg_quality_current`, `jpeg_quality_target`, `cycle_elapsed_ms`, and `encode_elapsed_ms`

## Phase 2: Control-Over-Video Prioritization

- Status: Implemented at the control/UI layer
- Risk: Low
- Purpose: keep one stale/flapping robot from consuming healthy robots' UI/media budget

Files:

- [swarm_fpv_ui.py](/home/aemilio/ros2_ws_dev/src/swarm_control_core/swarm_control_core/swarm_fpv_ui.py)
- [LOW_LATENCY_VALIDATION.md](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/LOW_LATENCY_VALIDATION.md)
- [ADR-0008-per-robot-fault-isolation.md](/home/aemilio/ros2_ws_dev/src/swarm_control_core/DOCS/ADR/ADR-0008-per-robot-fault-isolation.md)

Env vars:

- existing UI knobs only:
  - `SWARM_CORE_IMAGE_SUBSCRIPTION_MODE`
  - `SWARM_CORE_THUMB_ROBOTS_PER_TICK`
  - `SWARM_CORE_THUMB_REFRESH_HZ`
  - `SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S`
  - `SWARM_CORE_DRIVE_CMD_RATE_HZ`
  - `SWARM_CORE_DRIVE_HOLD_TIMEOUT_S`

Default vs optional:

- default:
  - stale robots remain visible
  - healthy robots get thumbnail-refresh priority
  - per-robot failure backoff applies at the UI/media layer
- optional:
  - operator tuning of the existing UI refresh knobs

Acceptance tests:

- with `robot1` flapping, `robot2` and `robot3` remain visible and controllable
- restarting `robot1` does not require restarting the UI
- stale/live transition logs identify whether `heartbeat`, `camera`, or both are missing

## Phase 3: Optional Static-Peer Discovery Mode

- Status: Planned
- Risk: Medium
- Purpose: reduce multicast discovery churn for stable fleets while preserving current plug-and-play defaults

Planned files:

- [swarm_core_run_robot.sh](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_run_robot.sh)
- [swarm_core_run_local_ui.sh](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_run_local_ui.sh)
- [swarm_core_reset_env.sh](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_reset_env.sh)
- new helper to generate static peer config from known robot/control identities

Planned env vars:

- `SWARM_CORE_DISCOVERY_MODE`
- `SWARM_CORE_STATIC_PEERS`
- `SWARM_CORE_STATIC_PEERS_FILE`

Default vs optional:

- default:
  - current multicast / subnet-scoped discovery remains unchanged
- optional:
  - static peers for stable known fleets

Acceptance tests:

- multicast mode remains current default behavior
- static-peer mode brings up the known fleet without subnet-wide discovery
- hostname/IP drift produces explicit errors instead of silent partial discovery

## Phase 4: Hard Robot-Side Bandwidth Shaping

- Status: Planned
- Risk: Highest
- Purpose: enforce hard per-robot network budgets only after softer containment is proven safe

Planned files:

- [swarm_core_run_robot.sh](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_run_robot.sh)
- [swarm_core_bootstrap_machine.sh](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts/swarm_core_bootstrap_machine.sh)
- new optional shaping helper under [scripts](/home/aemilio/ros2_ws_dev/src/swarm_control_core/scripts)

Planned env vars:

- `SWARM_CORE_ENABLE_EGRESS_SHAPING`
- `SWARM_CORE_EGRESS_RATE_MBIT`
- `SWARM_CORE_EGRESS_BURST_KBIT`

Default vs optional:

- default:
  - off
- optional:
  - explicit opt-in only

Acceptance tests:

- shaping off keeps current healthy-robot performance unchanged
- shaping on caps one robot's egress without adding human-detectable control latency
- if shaping harms control or discovery, this phase does not ship

## Current Rollout Summary

Implemented now:

- Phase 0
- Phase 1
- Phase 2

Still pending:

- Phase 3
- Phase 4
