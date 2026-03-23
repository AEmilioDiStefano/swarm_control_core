#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step4.sh [--domain-id <id>]

Behavior:
  - Sources the current ROS/workspace overlay.
  - Prints the control-side discovery environment.
  - Prints the currently visible heartbeat/camera/cmd_vel topics and relevant nodes.
USAGE
}

domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"

while [[ $# -gt 0 ]]; do
  case "$1" in
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

WS="$(swarm_core_qs_detect_workspace "${SWARM_CORE_WORKSPACE_ROOT:-}")"
swarm_core_qs_prepare_workspace_env "$WS"

export ROS_DOMAIN_ID="$domain_id"
swarm_core_qs_source_ros_overlay "$WS"

env | rg -E '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION)=' || true
ros2 topic list | rg "/.*/(heartbeat|camera/image_raw|cmd_vel)"
ros2 node list | rg "(swarm_fpv_ui|motor_driver_node|heartbeat_node|unit_executor_action_server|camera)"
