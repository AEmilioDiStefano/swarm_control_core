#!/usr/bin/env bash
#
# swarm_com_reset_env.sh
#
# Source-only reset helper that clears ROS/community/proprietary carryover
# environment variables in the current shell and optionally stops running
# robot/UI processes and services.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "This script must be sourced, not executed." >&2
  echo "Example: source ~/ros2_ws_dev/src/swarm_control_core/scripts/swarm_com_reset_env.sh" >&2
  exit 1
fi

_usage() {
  cat <<'USAGE'
Usage (must be sourced):
  source <workspace>/src/swarm_control_core/scripts/swarm_com_reset_env.sh [options]

Options:
  --scope <runtime|deep>       Reset scope (default: deep)
                               runtime: clear runtime vars only
                               deep: clear runtime + overlay/session vars and set ROS_DOMAIN_ID=<domain-id>
  --domain-id <id>             Community ROS domain ID target (default: 17)
  --machine-role <control|robot|auto>
                               Used for process/service reset behavior (default: auto)
  --compat-mode                Community compatibility prep mode:
                               stop conflicting services/processes and on robots apply
                               runtime-only masks for proprietary services.
  --skip-process-reset         Do not stop existing services/processes
  --dry-run                    Print process-reset actions without applying them
  -h, --help                   Show this help

Behavior:
  - Clears stale ROS/discovery/auth/profile variables from current shell.
  - Deep scope also clears shell overlay vars (AMENT/CMAKE/COLCON) and sets
    ROS_DOMAIN_ID to --domain-id (17 by default) for community defaults.
  - By default, calls swarm_com_terminate_existing_robot_processes.sh to stop
    prior package processes/services.
USAGE
}

scope="deep"
domain_id="17"
machine_role="auto"
compat_mode="0"
skip_process_reset="0"
dry_run="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)
      shift
      scope="${1:-}"
      if [[ -z "$scope" ]]; then
        echo "[swarm_com_reset] --scope requires runtime or deep." >&2
        return 1
      fi
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
      if [[ -z "$domain_id" ]]; then
        echo "[swarm_com_reset] --domain-id requires a value." >&2
        return 1
      fi
      ;;
    --machine-role)
      shift
      machine_role="${1:-}"
      if [[ -z "$machine_role" ]]; then
        echo "[swarm_com_reset] --machine-role requires control, robot, or auto." >&2
        return 1
      fi
      ;;
    --compat-mode)
      compat_mode="1"
      ;;
    --skip-process-reset)
      skip_process_reset="1"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      _usage
      return 0
      ;;
    *)
      echo "[swarm_com_reset] Unknown argument: $1" >&2
      _usage >&2
      return 1
      ;;
  esac
  shift
done

if [[ "$scope" != "runtime" && "$scope" != "deep" ]]; then
  echo "[swarm_com_reset] Invalid --scope '$scope'. Expected runtime or deep." >&2
  return 1
fi

machine_role="$(printf '%s' "$machine_role" | tr '[:upper:]' '[:lower:]')"
if [[ "$machine_role" != "control" && "$machine_role" != "robot" && "$machine_role" != "auto" ]]; then
  echo "[swarm_com_reset] Invalid --machine-role '$machine_role'. Expected control, robot, or auto." >&2
  return 1
fi

runtime_vars=(
  ROS_DOMAIN_ID
  ROS_LOCALHOST_ONLY
  ROS_DISCOVERY_SERVER
  ROS_SUPER_CLIENT
  ROS_STATIC_PEERS
  ROS_AUTOMATIC_DISCOVERY_RANGE
  RMW_IMPLEMENTATION
  CYCLONEDDS_URI
  FASTRTPS_DEFAULT_PROFILES_FILE
  ROS_NAMESPACE
  PROFILES_PATH
  CAMERA_PROFILES_PATH
  CONTROL_TYPES_PATH
  CONTROL_INTERFACES_PATH
  CONTROL_INTERFACE_PATH
  CAPABILITY_PROFILES_PATH
  ADAPTER_PROFILES_PATH
  ROBOT_PROFILES
  ROBOT_CAMERA_PROFILES
  SWARM_WORKSPACE_ROOT
  SWARM_PRESETS_DIR
  SWARM_PROFILES_PATH
  SWARM_CAMERA_PROFILES_PATH
  SWARM_CONTROL_TYPES_PATH
  SWARM_CONTROL_INTERFACES_PATH
  SWARM_CONTROL_INTERFACE_PATH
  SWARM_CAPABILITY_PROFILES_PATH
  SWARM_ADAPTER_PROFILES_PATH
  SWARM_COM_WORKSPACE_ROOT
  SWARM_COM_PRESETS_DIR
  SWARM_COM_PROFILES_PATH
  SWARM_COM_CAMERA_PROFILES_PATH
  SWARM_COM_CONTROL_TYPES_PATH
  SWARM_COM_CONTROL_INTERFACES_PATH
  SWARM_COM_CONTROL_INTERFACE_PATH
  SWARM_COM_CAPABILITY_PROFILES_PATH
  SWARM_COM_ADAPTER_PROFILES_PATH
  SWARM_DISCOVERY_MODE
  SWARM_ROLE
  SWARM_CONTROL_HOST
  SWARM_ROSTER_FILE
  SWARM_UNITS_FILE
  SWARM_ROBOT_NAME
  SWARM_COM_ROBOT_NAME
  SWARM_COM_EXISTING_ROBOT_SERVICE
  SWARM_CONFIG_DIR
  SWARM_COM_CONFIG_DIR
  SWARM_EDGE_SITE_ID
  SWARM_COM_AUTH_MODE
  SWARM_COM_AUTH_ISSUER
  SWARM_COM_AUTH_AUDIENCE
  SWARM_COM_AUTH_JWKS_URL
  SWARM_COM_BIND_HOST
  SWARM_COM_BIND_PORT
  SWARM_COM_ALLOW_ANON_READONLY
  SWARM_COM_DEV_LOGIN_ENABLED
  SWARM_COM_DEV_USERS_JSON
  SWARM_COM_WEBRTC_ICE_SERVERS_JSON
  SWARM_COM_WEBRTC_ICE_TRANSPORT_POLICY
  SWARM_COM_FPV_BIND_HOST
  SWARM_COM_FPV_BIND_PORT
  SWARM_FPV_AUTH_MODE
  SWARM_FPV_AUTH_ISSUER
  SWARM_FPV_AUTH_AUDIENCE
  SWARM_FPV_AUTH_JWKS_URL
  SWARM_FPV_BIND_HOST
  SWARM_FPV_BIND_PORT
  SWARM_FPV_ALLOW_ANON_READONLY
  SWARM_FPV_DEV_LOGIN_ENABLED
  SWARM_FPV_DEV_USERS_JSON
  SWARM_FPV_WEBRTC_ICE_SERVERS_JSON
  SWARM_FPV_WEBRTC_ICE_TRANSPORT_POLICY
  SWARM_COM_MAIN_STREAM_FPS
  SWARM_COM_WEBRTC_FPS
  SWARM_COM_WEBRTC_MAIN_ONLY
  SWARM_COM_THUMB_REFRESH_HZ
  SWARM_COM_IMAGE_SUBSCRIPTION_MODE
  SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S
  SWARM_COM_THUMB_ROBOTS_PER_TICK
  SWARM_COM_AUDIT_CMD_VEL_MIN_PERIOD_S
  SWARM_FPV_WEBRTC_FPS
  SWARM_FPV_WEBRTC_MAIN_ONLY
  SWARM_FPV_THUMB_REFRESH_HZ
  SWARM_FPV_IMAGE_SUBSCRIPTION_MODE
  SWARM_FPV_IMAGE_THUMB_INTEREST_TTL_S
  SWARM_FPV_THUMB_ROBOTS_PER_TICK
  SWARM_COM_ALLOW_LAN_BIND
  FPV_BIND_HOST
  FPV_BIND_PORT
  FPV_WEBRTC_ICE_SERVERS_JSON
  FPV_WEBRTC_ICE_TRANSPORT_POLICY
  CONTROL_HOST
  DISCOVERY_PORT
  DOMAIN_ID
)

deep_overlay_vars=(
  AMENT_PREFIX_PATH
  COLCON_PREFIX_PATH
  CMAKE_PREFIX_PATH
  COLCON_CURRENT_PREFIX
  _colcon_cd_root
)

vars=("${runtime_vars[@]}")
if [[ "$scope" == "deep" ]]; then
  vars+=("${deep_overlay_vars[@]}")
fi

for v in "${vars[@]}"; do
  unset "$v"
done

if [[ "$scope" == "deep" ]]; then
  export ROS_DOMAIN_ID="$domain_id"
fi

if [[ "$skip_process_reset" != "1" ]]; then
  export SWARM_COM_PROCESS_RESET_DONE="0"
  _script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _term_script="${_script_dir}/swarm_com_terminate_existing_robot_processes.sh"
  if [[ -x "$_term_script" ]]; then
    _term_args=(--machine-role "$machine_role")
    if [[ "$compat_mode" == "1" ]]; then
      _term_args+=(--compat-mode)
    fi
    if [[ "$dry_run" == "1" ]]; then
      _term_args+=(--dry-run)
    fi
    if "$_term_script" "${_term_args[@]}"; then
      export SWARM_COM_PROCESS_RESET_DONE="1"
    else
      echo "[swarm_com_reset] WARN: process reset helper returned non-zero." >&2
      export SWARM_COM_PROCESS_RESET_DONE="0"
    fi
  else
    echo "[swarm_com_reset] WARN: process reset helper not found: ${_term_script}" >&2
    export SWARM_COM_PROCESS_RESET_DONE="0"
  fi
else
  export SWARM_COM_PROCESS_RESET_DONE="0"
fi

export SWARM_COM_RESET_ENV_DONE="1"

if [[ "$scope" == "deep" ]]; then
  echo "[swarm_com_reset] Cleared runtime + overlay variables. Set ROS_DOMAIN_ID=${ROS_DOMAIN_ID}."
else
  echo "[swarm_com_reset] Cleared runtime variables."
fi
echo "[swarm_com_reset] Terminal is ready for swarm_control_core setup."
