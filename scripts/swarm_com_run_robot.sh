#!/usr/bin/env bash
set -euo pipefail

WS="${SWARM_COM_WORKSPACE_ROOT:-$HOME/ros2_ws_dev}"
ROBOT_NAME="${1:-${SWARM_COM_ROBOT_NAME:-${USER}}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USE_CAMERA_RAW="${SWARM_COM_USE_CAMERA:-true}"
CAMERA_PIPELINE="${SWARM_COM_CAMERA_PIPELINE:-adapter}"

export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"

# Guard against stale proprietary discovery/session exports.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

USE_CAMERA="$(printf '%s' "$USE_CAMERA_RAW" | tr '[:upper:]' '[:lower:]')"
if [[ "$USE_CAMERA" != "true" && "$USE_CAMERA" != "false" ]]; then
  echo "[swarm_com_run_robot] WARN: invalid SWARM_COM_USE_CAMERA='${USE_CAMERA_RAW}', defaulting to true" >&2
  USE_CAMERA="true"
fi

if [[ "${SWARM_COM_TERMINATE_EXISTING_PROCESSES:-1}" == "1" ]]; then
  if [[ "${SWARM_COM_PROCESS_RESET_DONE:-0}" == "1" ]]; then
    echo "[swarm_com_run_robot] process reset already completed in this shell; skipping duplicate reset."
    export SWARM_COM_PROCESS_RESET_DONE="0"
  else
    term_args=(--machine-role robot)
    if [[ "${SWARM_COM_COMPAT_PREP:-1}" == "1" ]]; then
      term_args+=(--compat-mode)
    fi
    "${SCRIPT_DIR}/swarm_com_terminate_existing_robot_processes.sh" "${term_args[@]}" || true
    export SWARM_COM_PROCESS_RESET_DONE="1"
  fi
fi

if [[ -x "${SCRIPT_DIR}/swarm_com_seed_runtime_config.sh" ]]; then
  "${SCRIPT_DIR}/swarm_com_seed_runtime_config.sh" --workspace "$WS" || true
fi

runtime_cfg_dir="${SWARM_COM_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
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
export ROS_AUTOMATIC_DISCOVERY_RANGE="${SWARM_COM_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export RMW_IMPLEMENTATION="${SWARM_COM_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

echo "[swarm_com_run_robot] ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "[swarm_com_run_robot] discovery_env=cleared"
echo "[swarm_com_run_robot] SWARM_DISCOVERY_MODE=${SWARM_DISCOVERY_MODE}"
echo "[swarm_com_run_robot] ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "[swarm_com_run_robot] ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}"
echo "[swarm_com_run_robot] RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
echo "[swarm_com_run_robot] use_camera=${USE_CAMERA} camera_pipeline=${CAMERA_PIPELINE}"
if [[ -n "${PROFILES_PATH:-}" ]]; then
  echo "[swarm_com_run_robot] PROFILES_PATH=${PROFILES_PATH}"
fi
if [[ -n "${CAMERA_PROFILES_PATH:-}" ]]; then
  echo "[swarm_com_run_robot] CAMERA_PROFILES_PATH=${CAMERA_PROFILES_PATH}"
fi

ros2 launch swarm_control_core swarm_bringup.launch.py \
  robot_name:="$ROBOT_NAME" \
  ros_domain_id:="$ROS_DOMAIN_ID" \
  use_camera:="$USE_CAMERA" \
  camera_pipeline:="$CAMERA_PIPELINE"
