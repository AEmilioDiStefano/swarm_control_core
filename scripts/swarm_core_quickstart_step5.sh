#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step5.sh --tool <teleop|orchestrator> [--domain-id <id>]

Behavior:
  - Sources the current ROS/workspace overlay.
  - Starts either terminal teleop or terminal orchestrator.
USAGE
}

tool=""
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)
      shift
      tool="${1:-}"
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

[[ "$tool" == "teleop" || "$tool" == "orchestrator" ]] || {
  usage >&2
  swarm_core_qs_fail "--tool must be teleop or orchestrator."
}

WS="$(swarm_core_qs_detect_workspace "${SWARM_CORE_WORKSPACE_ROOT:-}")"
swarm_core_qs_prepare_workspace_env "$WS"

export ROS_DOMAIN_ID="$domain_id"
swarm_core_qs_source_ros_overlay "$WS"

if [[ "$tool" == "teleop" ]]; then
  exec ros2 run swarm_control_core swarm_teleop_core
fi

exec ros2 run swarm_control_core terminal_orchestrator_core
