# Community Boundary

This package is intentionally scoped to local/LAN operation.

## Included
- local ROS 2 robot bringup
- local FPV UI + browser control path
- local profile persistence
- local service/node development surfaces

## Excluded
- public internet ingress setup
- cloud session/routing control plane
- TURN/certificate/tunneling setup automation
- defense-specific remote deployment flows

## Guardrails
- `swarm_fpv_ui_com` forces `auth_mode=off`
- main stream is strict local WebRTC-only
- JPEG polling is limited to fleet thumbnails
- default bind host is `127.0.0.1`
- LAN bind requires explicit `SWARM_COM_ALLOW_LAN_BIND=1`
- default ROS 2 domain ID is `17` unless explicitly overridden
- shared-robot helper: `scripts/swarm_com_terminate_existing_robot_processes.sh`
- release gate script: `scripts/swarm_com_release_gate.sh`
