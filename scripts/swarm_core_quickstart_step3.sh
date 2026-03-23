#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step3.sh [--domain-id <id>] [--balanced-fleet] [--switch-heavy] [--allow-lan-bind]

Behavior:
  - Runs the control-machine UI quickstart prep in one script.
  - Applies compat reset.
  - Sets the documented local/LAN UI defaults.
  - Optionally enables the balanced-fleet profile, switch-heavy profile, or private-LAN bind.
  - Launches the local FPV UI and stays attached to it.
USAGE
}

domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
balanced_fleet="0"
switch_heavy="0"
allow_lan_bind="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain-id)
      shift
      domain_id="${1:-}"
      ;;
    --balanced-fleet)
      balanced_fleet="1"
      ;;
    --switch-heavy)
      switch_heavy="1"
      ;;
    --allow-lan-bind)
      allow_lan_bind="1"
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

export SWARM_CORE_ROS_DOMAIN_ID="$domain_id"

echo "[quickstart step3] workspace=${WS}"
echo "[quickstart step3] domain_id=${domain_id}"

swarm_core_qs_source_reset_env "$WS" "control" "$domain_id" "1" "0"

export SWARM_CORE_WEBRTC_FPS=15.0
export SWARM_CORE_THUMB_REFRESH_HZ=0.5
export SWARM_CORE_IMAGE_SUBSCRIPTION_MODE=active_only
export SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S=0.75
export SWARM_CORE_THUMB_ROBOTS_PER_TICK=0
export SWARM_CORE_DRIVE_CMD_RATE_HZ=20.0
export SWARM_CORE_DRIVE_HOLD_TIMEOUT_S=0.35

if [[ "$balanced_fleet" == "1" ]]; then
  export SWARM_CORE_THUMB_ROBOTS_PER_TICK=1
fi

if [[ "$switch_heavy" == "1" ]]; then
  export SWARM_CORE_THUMB_REFRESH_HZ=1.0
  export SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S=4.0
fi

if [[ "$allow_lan_bind" == "1" ]]; then
  export SWARM_CORE_ALLOW_LAN_BIND=1
  export SWARM_CORE_BIND_HOST=0.0.0.0
fi

exec "${SCRIPT_DIR}/swarm_core_run_local_ui.sh"
