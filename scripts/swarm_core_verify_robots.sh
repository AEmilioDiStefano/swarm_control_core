#!/usr/bin/env bash
# shellcheck shell=bash

# Lists every robot in the control machine's registered/approved runtime
# registry, then checks each one with robot_doctor_core. This is the ADD-robot
# guide's final verification step.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SC="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS="$(cd "${SC}/../.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: swarm_core_verify_robots.sh"
  exit 0
fi

set +u
# shellcheck disable=SC1091
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
if [[ ! -f "${WS}/install/setup.bash" ]]; then
  set -u
  echo "[swarm_core_verify_robots] ERROR: Workspace overlay is not built (${WS}/install/setup.bash missing)." >&2
  echo "[NEXT] Run: ~/.local/bin/swarmc setup" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "${WS}/install/setup.bash"
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-${SWARM_CORE_ROS_DOMAIN_ID:-17}}"

registered_robots="$(
python3 - <<'PY'
from pathlib import Path
import os
import yaml

default_config_dir = Path.home() / ".config" / "swarm_control_core"
config_dir = Path(os.environ.get("SWARM_CORE_CONFIG_DIR", str(default_config_dir)))
path = config_dir / "robot_instances.yaml"
data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
robots = data.get("robots", {}) if isinstance(data, dict) else {}
for name in sorted(robots):
    print(name)
PY
)"

if [[ -z "${registered_robots//[[:space:]]/}" ]]; then
  echo "[FAIL] No registered/approved robots found in the control-machine runtime registry." >&2
  echo "[NEXT] Return to the onboarding step and onboard at least one robot." >&2
  exit 1
fi

echo "[OK] Registered/approved robots:"
# shellcheck disable=SC2086
printf '  %s\n' $registered_robots

status=0
for robot in $registered_robots; do
  echo
  echo "[CHECK] robot_doctor_core --robot ${robot}"
  if ! ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot "$robot"; then
    status=1
  fi
done

exit "$status"
