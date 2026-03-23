#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step1.sh --machine-role <control|robot> [--domain-id <id>]

Behavior:
  - Detects the workspace from the script path.
  - Clears stale overlay/discovery state inside the script environment.
  - Attempts to sync the local checkout to origin/main.
  - Continues from the local checkout if GitHub is unreachable.
  - Builds swarm_control_core and verifies the current quickstart compatibility hooks.
USAGE
}

machine_role=""
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --machine-role)
      shift
      machine_role="${1:-}"
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
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

[[ "$machine_role" == "control" || "$machine_role" == "robot" ]] || {
  usage >&2
  swarm_core_qs_fail "--machine-role must be control or robot."
}

WS="$(swarm_core_qs_detect_workspace "${SWARM_CORE_WORKSPACE_ROOT:-}")"
swarm_core_qs_prepare_workspace_env "$WS"

echo "[quickstart step1] workspace=${WS}"
echo "[quickstart step1] machine_role=${machine_role} domain_id=${domain_id}"

swarm_core_qs_source_reset_env "$WS" "$machine_role" "$domain_id" "1" "1"
swarm_core_qs_git_sync "$SC"

rg -n -- '--machine-role|--compat-mode|compat-stop-ufw|ROS_AUTOMATIC_DISCOVERY_RANGE|SWARM_CORE_PROCESS_RESET_DONE|SWARM_CORE_WEBRTC_FPS|SWARM_CORE_THUMB_REFRESH_HZ|SWARM_CORE_IMAGE_SUBSCRIPTION_MODE|SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S|SWARM_CORE_THUMB_ROBOTS_PER_TICK|SWARM_CORE_DRIVE_CMD_RATE_HZ|SWARM_CORE_DRIVE_HOLD_TIMEOUT_S' \
  "${SC}/scripts/swarm_core_reset_env.sh" \
  "${SC}/scripts/swarm_core_terminate_existing_robot_processes.sh" \
  "${SC}/scripts/swarm_core_run_robot.sh" \
  "${SC}/scripts/swarm_core_run_local_ui.sh"

cd "$WS"
swarm_core_qs_source_ros_overlay "$WS"
colcon build --base-paths "$SC" --packages-select swarm_control_core

echo "[quickstart step1] complete"
