#!/usr/bin/env bash
# shellcheck shell=bash

# Source-only helper that exports workspace/package paths for docs/runbooks.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "This script must be sourced, not executed." >&2
  echo "Example: source <workspace>/src/swarm_control_core/scripts/swarm_com_workspace_env.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_com_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_com_workspace.sh"

usage() {
  cat <<'USAGE'
Usage (must be sourced):
  source swarm_com_workspace_env.sh [--workspace <path>]

Exports:
  WS                        Workspace root
  SC                        Core package path (${WS}/src/swarm_control_core)
  SWARM_COM_WORKSPACE_ROOT  Workspace root (for core scripts)
  WS_DEV                    Alias of WS for legacy doc compatibility
USAGE
}

workspace_override=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace_override="${1:-}"
      ;;
    -h|--help)
      usage
      return 0
      ;;
    *)
      echo "[swarm_com_workspace_env] Unknown argument: $1" >&2
      usage >&2
      return 2
      ;;
  esac
  shift
done

WS="$(swarm_com_detect_workspace_root "$workspace_override" || true)"
if [[ -z "$WS" ]]; then
  echo "[swarm_com_workspace_env] ERROR: Unable to detect workspace root." >&2
  echo "[swarm_com_workspace_env] Set --workspace <path> or SWARM_COM_WORKSPACE_ROOT and retry." >&2
  return 1
fi

SC="${WS}/src/swarm_control_core"
if [[ ! -d "$SC" ]]; then
  echo "[swarm_com_workspace_env] ERROR: Core package directory not found: $SC" >&2
  return 1
fi

export WS
export SC
export SWARM_COM_WORKSPACE_ROOT="$WS"
export WS_DEV="$WS"

echo "[swarm_com_workspace_env] WS=${WS}"
echo "[swarm_com_workspace_env] SC=${SC}"
