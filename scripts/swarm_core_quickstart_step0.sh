#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step0.sh --machine-role <control|robot> [--domain-id <id>]

Behavior:
  - Detects the workspace containing swarm_control_core from the script path.
  - Applies a deep compat reset in the script environment.
  - Runs the dependency check/install flow for the selected machine role.
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

echo "[quickstart step0] workspace=${WS}"
echo "[quickstart step0] machine_role=${machine_role} domain_id=${domain_id}"

swarm_core_qs_source_reset_env "$WS" "$machine_role" "$domain_id" "1" "0"
"${SCRIPT_DIR}/swarm_core_check_install_dependencies.sh" --machine-role "$machine_role"

echo "[quickstart step0] complete"
