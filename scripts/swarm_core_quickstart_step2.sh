#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step2.sh [--robot-name <name>] [--domain-id <id>] [--skip-camera-profile]

Behavior:
  - Runs the robot-side quickstart prep in one script.
  - Applies compat reset and robot identity defaults.
  - Verifies ufw state and disables Wi-Fi power save when possible.
  - Runs interactive camera profile save unless --skip-camera-profile is used.
  - Launches robot bringup and stays attached to it.
USAGE
}

robot_name="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
skip_camera_profile="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --robot-name)
      shift
      robot_name="${1:-}"
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
      ;;
    --skip-camera-profile)
      skip_camera_profile="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      swarm_core_qs_fail "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$robot_name" ]] || swarm_core_qs_fail "--robot-name resolved empty."

WS="$(swarm_core_qs_detect_workspace "${SWARM_CORE_WORKSPACE_ROOT:-}")"
swarm_core_qs_prepare_workspace_env "$WS"

export SWARM_CORE_ROS_DOMAIN_ID="$domain_id"
export SWARM_CORE_ROBOT_NAME="$robot_name"

echo "[quickstart step2] workspace=${WS}"
echo "[quickstart step2] robot_name=${robot_name} domain_id=${domain_id}"

swarm_core_qs_source_reset_env "$WS" "robot" "$domain_id" "1" "0"

systemctl is-active ufw.service || true

wifi_iface="$(swarm_core_qs_wireless_iface || true)"
if [[ -n "$wifi_iface" ]]; then
  if iw dev "$wifi_iface" info >/dev/null 2>&1; then
    if iw dev "$wifi_iface" get power_save 2>/dev/null | grep -qi 'Power save: on'; then
      sudo iw dev "$wifi_iface" set power_save off
    fi
    iw dev "$wifi_iface" get power_save || true
  fi
fi

swarm_core_qs_source_ros_overlay "$WS"

if [[ "$skip_camera_profile" != "1" ]]; then
  ros2 run swarm_control_core save_camera_profile_core --robot "$robot_name"
fi

exec "${SCRIPT_DIR}/swarm_core_run_robot.sh" "$robot_name"
