#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"
# shellcheck source=./lib/swarm_core_discovery.sh
source "${SCRIPT_DIR}/lib/swarm_core_discovery.sh"

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
swarm_core_apply_discovery_env
swarm_core_stop_ros_daemon

echo "DISCOVERY ENVIRONMENT:"
env | rg -e '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION|SWARM_DISCOVERY_MODE)=' || true

topics="$(ros2 topic list)" || swarm_core_qs_fail "ros2 topic list failed. Check the ROS overlay and RMW installation."
nodes="$(ros2 node list)" || swarm_core_qs_fail "ros2 node list failed. Check the ROS overlay and RMW installation."
topic_matches="$(printf '%s\n' "$topics" | rg -e '/.*/(heartbeat|camera/image_raw|cmd_vel)' || true)"
node_matches="$(printf '%s\n' "$nodes" | rg -e '(swarm_fpv_ui|motor_driver_node|heartbeat_node|unit_executor_action_server|camera)' || true)"
runtime_cfg_dir="${SWARM_CORE_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
registered_robots="$(python3 - "${runtime_cfg_dir}/robot_instances.yaml" <<'PY_ROBOTS'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
robots = data.get("robots", {}) if isinstance(data, dict) else {}
if isinstance(robots, dict):
    for name in sorted(str(name).strip() for name in robots if str(name).strip()):
        print(name)
PY_ROBOTS
)"

echo
echo "RELEVANT TOPICS:"
printf '%s\n' "${topic_matches:-(none)}"
echo
echo "RELEVANT NODES:"
printf '%s\n' "${node_matches:-(none)}"

missing_robot_graph="0"
if [[ -z "$registered_robots" ]]; then
  swarm_core_qs_warn "No approved robots exist in ${runtime_cfg_dir}/robot_instances.yaml. Complete onboarding first."
  missing_robot_graph="1"
else
  live_robot_count=0
  while IFS= read -r robot; do
    [[ -n "$robot" ]] || continue
    robot_ready="1"
    for expected in "/${robot}/heartbeat_node" "/${robot}/motor_driver_node"; do
      if ! printf '%s\n' "$nodes" | rg -Fxq "$expected"; then
        swarm_core_qs_warn "Approved robot '${robot}' is missing required node ${expected}."
        robot_ready="0"
      fi
    done
    if [[ "$robot_ready" == "1" ]]; then
      live_robot_count=$((live_robot_count + 1))
    fi
  done <<< "$registered_robots"
  if (( live_robot_count == 0 )); then
    swarm_core_qs_warn "No approved robot has both a heartbeat and motor-driver node in the graph."
    missing_robot_graph="1"
  else
    echo "LIVE ROBOTS: ${live_robot_count}"
  fi
fi

if [[ -z "$topic_matches" || -z "$node_matches" || "$missing_robot_graph" == "1" ]]; then
  swarm_core_qs_warn "Fleet graph is incomplete. This indicates a node-startup or DDS/runtime failure, not proof that .local/mDNS is broken."
  swarm_core_qs_warn "Confirm robot and control use domain ${ROS_DOMAIN_ID}, RMW ${RMW_IMPLEMENTATION}, and the peer list shown above."
  swarm_core_qs_warn "If IP ping works but multicast does not, rerun every host with SWARM_CORE_DISCOVERY_MODE=static; static mode requires configured peers."
  exit 1
fi
