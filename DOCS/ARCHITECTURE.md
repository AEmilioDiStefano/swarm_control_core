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
- Optional terminal playbook control.
- No cloud control plane and no internet-ingress automation.

## Local Scope Boundary

`swarm_control_core` is the limited local/private-LAN runtime. Its docs
should describe local robot setup and operation without documenting features
outside this package or site-specific deployment architecture.

- Robot profiles describe local capability and wiring.
- The robot registry is the local control allowlist. Discovered robots absent
  from the registry may appear for diagnostics, but remain read-only.
- Profile names, ROS namespaces, and topic names are operational identifiers,
  not secrets.
- Public core docs should not contain credentials, site-specific access policy,
  deployment topology, or remote-operation procedures.

## Runtime Components

- `motor_driver_node_core`: consumes `/robot/cmd_vel` and drives hardware interface.
- `heartbeat_node_core`: publishes robot liveness and profile identity.
- `unit_executor_action_server_core`: executes robot playbooks.
- `swarm_camera_node_core`: camera publishing.
- `swarm_fpv_ui_core`: browser UI server and fleet state bridge.
- `swarm_teleop_core`: keyboard terminal teleop node.

## Data and Control Flow

- Robots publish heartbeat and camera topics.
- Control clients publish commands/playbooks to robot namespaces.
- Browser UI consumes ROS state via local server bridge and renders fleet controls.
- Terminal tools interact directly with ROS topics/actions.

## Low-Complexity Runtime Strategy

The runtime now uses an **interest-driven active set** model so robot-count growth does
not force full-fleet hot-path work at all times.

### Video Plane (`swarm_fpv_ui_core`)

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

### Command/Control Plane

- Drive commands and mode updates remain per-robot constant-time operations (`O(1)` per event).
- Control loops operate over active robot targets, not over full-fleet camera payloads.
- Health/telemetry snapshots are cache-bounded to reduce repeated compute under multiple UI readers.

Design rule for future features:

- Keep hot loops bounded by active-interest sets and explicit budgets.
- Avoid full-fleet scans inside high-frequency paths unless required for correctness.
- Reset scripts clear runtime tuning env vars so mode switches do not inherit stale runtime budgets.

## Configuration Model

- Directory guide: [../config/config.md](../config/config.md)
- `config/robot_instances.yaml` is the canonical robot registry: robot name,
  SSH target, control type, selected hardware/control interface, and per-robot
  tuning belong there.
- `config/control_types.yaml` and `config/control_interfaces.yaml` are reusable
  component/profile libraries. Hardware profiles declare
  `compatible_control_types`, `backend`, `wheel_layout`, controller metadata,
  GPIO maps, params, and a `docs.wiring` pointer so tools can filter, validate,
  and document interfaces without hardcoded profile names.
- Control interface IDs use canonical lowercase snake case. The YAML registry is
  the authoritative control-interface catalog.
- `validate_profiles_core` performs generic profile schema validation, and
  `generate_profile_docs_core` keeps `DOCS/GPIO/CONTROL_INTERFACE_INDEX.md`
  aligned as a generated pointer back to YAML.
- `add_control_interface_core` scaffolds new reusable control interfaces so most
  motor-controller additions touch YAML/docs only, not runtime Python.
- Core does not ship baseline `capability_profiles.yaml` or
  `adapter_profiles.yaml` files. The resolver accepts optional higher-level
  deployment files when supplied, otherwise it uses an empty capability fallback
  and the built-in `passthrough_local` adapter fallback.
- `camera_profiles.yaml` is generated robot-local state. It records detected
  camera choices and guarded software orientation (`flip_horizontal`,
  `flip_vertical`, `orientation_device`) from `save_camera_profile_core` and
  `camera_flipper_core`; robots do not need empty placeholders in the repository
  template.
- `add_robot_core` is the preferred front door for creating or updating robot
  entries. It syncs runtime robot entries, refreshes runtime reusable core
  profiles, preserves camera profiles, and prints wiring guidance.
- The FPV UI separates ROS discovery from trusted control. Robots visible on the
  ROS domain but absent from the configured robot registry may appear read-only
  for diagnostics/video; drive and autonomy commands are blocked.
- `wheel_test_core` validates physical wheel direction/order. Saved results are
  robot-specific GPIO overrides in `robot_instances.yaml`, not changes to the
  reusable hardware profile shared by every robot of that type.
- `robot_doctor_core` reports source/runtime/install drift, including stale
  `control_interfaces.yaml` files that would hide newly added hardware profiles.
- Robot setup and control-machine registration are runtime-first by default:
  they update `~/.config/swarm_control_core` without dirtying the git checkout.
  Maintainers can opt into source-baseline edits with `--update-source-baseline`
  when they intentionally want to commit a fleet default.
- Runtime overrides can still be placed in machine-local config paths when a
  deployment intentionally diverges from the source baseline.

## Safety and Constraints

- Browser UI enforces local security defaults (`auth_mode=off` with local binding defaults).
- Core docs and guides assume local/private-LAN operation.
- Runtime wrappers fail-fast when `ufw.service` is active under LAN discovery defaults, to avoid silent DDS traffic loss.
- Quickstart applies an idempotent Wi-Fi check (`iw`): if `wlan0` power save is ON, it is switched OFF before bringup to avoid camera/control jitter on Wi-Fi links.
- Runtime behavior is scoped to `SWARM_CORE_*` env names.
- Main pane is strict WebRTC-only.
- Thumbnail rail stays bounded with JPEG polling budgets and does not replace main-stream video.
- Recommended multi-robot switching profile keeps `thumb_robots_per_tick=1`; `0` is a single-robot focus mode with lower background load but slower switches.
- Commands are constrained by robot drive and hardware limits in profiles.

## Extension Surfaces

- Adapter registry (`swarm_control_core/adapters`) for state/task translation.
- Playbook helpers and strategy compiler for task execution behavior.
- Launch arguments for per-deployment tuning without code changes.
