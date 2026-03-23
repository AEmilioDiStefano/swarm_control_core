#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

WS="$(swarm_core_detect_workspace_root "${SWARM_CORE_WORKSPACE_ROOT:-}" || true)"
if [[ -z "$WS" || ! -d "$WS/src/swarm_control_core" ]]; then
  echo "[swarm_core_run_robot] ERROR: Unable to detect workspace root. Set SWARM_CORE_WORKSPACE_ROOT or run from within a workspace containing src/swarm_control_core." >&2
  exit 1
fi

ROBOT_NAME="${1:-${SWARM_CORE_ROBOT_NAME:-${USER}}}"
USE_CAMERA_RAW="${SWARM_CORE_USE_CAMERA:-true}"
CAMERA_PIPELINE="${SWARM_CORE_CAMERA_PIPELINE:-adapter}"

export ROS_DOMAIN_ID="${SWARM_CORE_ROS_DOMAIN_ID:-17}"

# Guard against stale proprietary discovery/session exports.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

USE_CAMERA="$(printf '%s' "$USE_CAMERA_RAW" | tr '[:upper:]' '[:lower:]')"
if [[ "$USE_CAMERA" != "true" && "$USE_CAMERA" != "false" ]]; then
  echo "[swarm_core_run_robot] WARN: invalid SWARM_CORE_USE_CAMERA='${USE_CAMERA_RAW}', defaulting to true" >&2
  USE_CAMERA="true"
fi

if [[ "${SWARM_CORE_TERMINATE_EXISTING_PROCESSES:-1}" == "1" ]]; then
  if [[ "${SWARM_CORE_PROCESS_RESET_DONE:-0}" == "1" ]]; then
    echo "[swarm_core_run_robot] process reset already completed in this shell; skipping duplicate reset."
    export SWARM_CORE_PROCESS_RESET_DONE="0"
  else
    term_args=(--machine-role robot)
    if [[ "${SWARM_CORE_COMPAT_PREP:-1}" == "1" ]]; then
      term_args+=(--compat-mode)
    fi
    "${SCRIPT_DIR}/swarm_core_terminate_existing_robot_processes.sh" "${term_args[@]}" || true
    export SWARM_CORE_PROCESS_RESET_DONE="1"
  fi
fi

if [[ -x "${SCRIPT_DIR}/swarm_core_seed_runtime_config.sh" ]]; then
  "${SCRIPT_DIR}/swarm_core_seed_runtime_config.sh" --workspace "$WS" || true
fi

runtime_cfg_dir="${SWARM_CORE_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
if [[ -f "${runtime_cfg_dir}/robot_instances.yaml" ]]; then
  export PROFILES_PATH="${runtime_cfg_dir}/robot_instances.yaml"
fi
if [[ -f "${runtime_cfg_dir}/camera_profiles.yaml" ]]; then
  export CAMERA_PROFILES_PATH="${runtime_cfg_dir}/camera_profiles.yaml"
fi

set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

# Enforce community LAN discovery defaults after sourcing overlays.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
export SWARM_DISCOVERY_MODE="multicast"
export SWARM_ROLE="robot"
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE="${SWARM_CORE_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export RMW_IMPLEMENTATION="${SWARM_CORE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

echo "[swarm_core_run_robot] ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "[swarm_core_run_robot] discovery_env=cleared"
echo "[swarm_core_run_robot] SWARM_DISCOVERY_MODE=${SWARM_DISCOVERY_MODE}"
echo "[swarm_core_run_robot] ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "[swarm_core_run_robot] ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}"
echo "[swarm_core_run_robot] RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
echo "[swarm_core_run_robot] use_camera=${USE_CAMERA} camera_pipeline=${CAMERA_PIPELINE}"
if [[ -n "${PROFILES_PATH:-}" ]]; then
  echo "[swarm_core_run_robot] PROFILES_PATH=${PROFILES_PATH}"
fi
if [[ -n "${CAMERA_PROFILES_PATH:-}" ]]; then
  echo "[swarm_core_run_robot] CAMERA_PROFILES_PATH=${CAMERA_PROFILES_PATH}"
fi

ros2 launch swarm_control_core swarm_launch/swarm_bringup.launch.py \
  robot_name:="$ROBOT_NAME" \
  ros_domain_id:="$ROS_DOMAIN_ID" \
  use_camera:="$USE_CAMERA" \
  camera_pipeline:="$CAMERA_PIPELINE"
