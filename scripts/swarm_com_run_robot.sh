#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_com_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_com_workspace.sh"

WS="$(swarm_com_detect_workspace_root "${SWARM_COM_WORKSPACE_ROOT:-}" || true)"
[[ -n "$WS" ]] || {
  echo "[swarm_com_run_robot] ERROR: unable to detect workspace root; set SWARM_COM_WORKSPACE_ROOT." >&2
  exit 1
}
ROBOT_NAME="${1:-${SWARM_COM_ROBOT_NAME:-${USER}}}"
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
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE="${SWARM_COM_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export SWARM_COM_REQUIRE_UFW_INACTIVE="${SWARM_COM_REQUIRE_UFW_INACTIVE:-1}"

is_truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
  esac
  return 1
}

check_ufw_runtime_guard() {
  local range_lc="${ROS_AUTOMATIC_DISCOVERY_RANGE,,}"
  if [[ "$range_lc" == "off" ]]; then
    return 0
  fi
  if ! is_truthy "$SWARM_COM_REQUIRE_UFW_INACTIVE"; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if systemctl is-active --quiet ufw.service; then
    echo "[swarm_com_run_robot] ERROR: ufw.service is active and likely blocking DDS discovery/traffic." >&2
    echo "[swarm_com_run_robot] Run compat reset in this robot shell, then retry:" >&2
    echo "  source \"$SCRIPT_DIR/swarm_com_reset_env.sh\" --scope deep --machine-role robot --compat-mode --domain-id \"\${SWARM_COM_ROS_DOMAIN_ID:-17}\"" >&2
    echo "[swarm_com_run_robot] Override guard only if your firewall rules are already DDS-safe: export SWARM_COM_REQUIRE_UFW_INACTIVE=0" >&2
    exit 2
  fi
}

warn_if_wifi_powersave_enabled() {
  if ! command -v iw >/dev/null 2>&1; then
    return 0
  fi
  if ! iw dev wlan0 info >/dev/null 2>&1; then
    return 0
  fi
  if iw dev wlan0 get power_save 2>/dev/null | grep -qi 'Power save: on'; then
    echo "[swarm_com_run_robot] WARN: wlan0 power save is ON. This can cause lag spikes/SSH instability under load." >&2
    echo "[swarm_com_run_robot] Recommend once per boot: sudo iw dev wlan0 set power_save off" >&2
  fi
}

check_ufw_runtime_guard
warn_if_wifi_powersave_enabled

echo "[swarm_com_run_robot] ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "[swarm_com_run_robot] discovery_env=cleared"
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
