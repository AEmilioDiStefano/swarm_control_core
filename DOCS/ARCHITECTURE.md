# swarm_control_core Architecture

## Decision Records

- ADR index: [ADR/README.md](./ADR/README.md)
- Validation runbook: [LOW_LATENCY_VALIDATION.md](./LOW_LATENCY_VALIDATION.md)

## Goals

- Provide a practical local/LAN AMR fleet control stack.
- Support heterogeneous robots through profile-driven configuration.
- Keep operations simple and robust with ROS 2/DDS native discovery.
- Expose terminal and browser control surfaces for operators.

## Operational Scope

- Local and private LAN operation only.
- Browser FPV/control UI using strict WebRTC-only main-stream transport.
- Fleet thumbnail rail uses bounded JPEG polling (separate from main-stream transport).
- Terminal teleop for direct manual driving.
- Terminal orchestrator for simple playbook execution.
- No cloud control plane and no internet-ingress automation.

## Runtime Components

- `motor_driver_node_com`: consumes `/robot/cmd_vel` and drives hardware interface.
- `heartbeat_node_com`: publishes robot liveness and profile identity.
- `unit_executor_action_server_com`: executes robot playbooks.
- `swarm_camera_node_com`: camera publishing.
- `swarm_fpv_ui_com`: browser UI server and fleet state bridge.
- `swarm_teleop_com`: keyboard terminal teleop node.
- `terminal_orchestrator_com`: menu-driven terminal playbook node.

## Data and Control Flow

- Robots publish heartbeat and camera topics.
- Control clients publish commands/playbooks to robot namespaces.
- Browser UI consumes ROS state via local server bridge and renders fleet controls.
- Terminal tools interact directly with ROS topics/actions.

## Low-Complexity Runtime Strategy

The runtime now uses an **interest-driven active set** model so robot-count growth does
not force full-fleet hot-path work at all times.

### Video Plane (`swarm_fpv_ui_com`)

- Camera subscriptions are interest-driven by default (`active_only`):
  - always keep active robot stream,
  - keep short-lived on-demand streams for thumbnail requests,
  - unsubscribe non-interest robots.
- Thumbnail updates use bounded round-robin work (`thumb_robots_per_tick`) instead of
  refreshing all non-active robots every cycle.
- Safety floor: if `thumb_robots_per_tick=0`, the client still refreshes one
  stale thumbnail per tick (minimal-liveness mode) so fleet tiles do not stay black.
- Decoded RGB frames are cached per frame-stamp so multiple WebRTC consumers do not
  repeatedly decode the same JPEG payload.

Resulting complexity shape:

- Previous steady-state ingress pressure: `O(R * F * B)`
- Current default pressure: `O((A + K) * F * B)`
  - `R`: discovered robots
  - `A`: active-stream robots (typically `1`)
  - `K`: thumbnail budget (typically `1` effective in low-latency mode)
  - `F`: frame rate
  - `B`: frame size bytes

Decode path:

- Previous: `O(C * W)` per active robot stream
- Current: `O(F)` per active robot stream (decode once, reuse for consumers)
  - `C`: WebRTC consumers
  - `W`: WebRTC send pacing

### Orchestration/Control Plane (`terminal_orchestrator_com` / swarm_orchestrator workflow)

- Drive commands and mode updates remain per-robot constant-time operations (`O(1)` per event).
- Control loops operate over active robot targets, not over full-fleet camera payloads.
- Health/telemetry snapshots are cache-bounded to reduce repeated compute under multiple UI readers.

Design rule for future features:

- Keep hot loops bounded by active-interest sets and explicit budgets.
- Avoid full-fleet scans inside high-frequency paths unless required for correctness.
- Reset scripts clear both community and proprietary FPV tuning env vars so mode switches do not inherit stale runtime budgets.

## Configuration Model

- Robot behavior is profile-driven from `config/*.yaml`.
- Runtime overrides can be placed in machine-local config paths.
- Camera profile persistence is supported through `save_camera_profile_com`.

## Safety and Constraints

- Browser UI enforces local security defaults (`auth_mode=off` with local binding defaults).
- Runtime wrappers fail-fast when `ufw.service` is active under LAN discovery defaults, to avoid silent DDS traffic loss.
- Quickstart applies an idempotent Wi-Fi check (`iw`): if `wlan0` power save is ON, it is switched OFF before bringup to avoid camera/control jitter on Wi-Fi links.
- Runtime behavior is scoped to `SWARM_COM_*` env names; proprietary env names are only cleared by reset scripts, not consumed for behavior.
- Main pane is strict WebRTC-only.
- Thumbnail rail stays bounded with JPEG polling budgets and does not replace main-stream video.
- Recommended multi-robot switching profile keeps `thumb_robots_per_tick=1`; `0` is a single-robot focus mode with lower background load but slower switches.
- Commands are constrained by robot drive and hardware limits in profiles.

## Extension Surfaces

- Adapter registry (`swarm_control_core/adapters`) for state/task translation.
- Playbook helpers and strategy compiler for task execution behavior.
- Launch arguments for per-deployment tuning without code changes.
