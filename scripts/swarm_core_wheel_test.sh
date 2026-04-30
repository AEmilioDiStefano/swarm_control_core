#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

WS="$(swarm_core_detect_workspace_root "${SWARM_CORE_WORKSPACE_ROOT:-}" || true)"
if [[ -z "$WS" || ! -d "$WS/src/swarm_control_core" ]]; then
  echo "[swarm_core_wheel_test] ERROR: Unable to detect workspace root. Set SWARM_CORE_WORKSPACE_ROOT or run from within a workspace containing src/swarm_control_core." >&2
  exit 1
fi

runtime_cfg_dir="${SWARM_CORE_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
if [[ -f "${runtime_cfg_dir}/robot_instances.yaml" && -z "${PROFILES_PATH:-}" ]]; then
  export PROFILES_PATH="${runtime_cfg_dir}/robot_instances.yaml"
fi

set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

exec ros2 run swarm_control_core wheel_test_core "$@"
