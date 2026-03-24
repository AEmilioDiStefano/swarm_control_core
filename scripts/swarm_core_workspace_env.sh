#!/usr/bin/env bash
# shellcheck shell=bash

# Source-only helper that exports workspace/package paths for docs/runbooks.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "This script must be sourced, not executed." >&2
  echo "Example: source <workspace>/src/swarm_control_core/scripts/swarm_core_workspace_env.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

usage() {
  cat <<'USAGE'
Usage (must be sourced):
  source swarm_core_workspace_env.sh [--workspace <path>] [--non-interactive]

Exports:
  WS                        Workspace root
  SC                        Core package path (${WS}/src/swarm_control_core)
  SWARM_CORE_WORKSPACE_ROOT  Workspace root (for core scripts)
  WS_DEV                    Alias of WS for legacy doc compatibility
  SWARM_CORE_WORKSPACE_NAME  Workspace directory name (basename of WS)
USAGE
}

workspace_override=""
interactive_mode="auto"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace_override="${1:-}"
      ;;
    --interactive)
      interactive_mode="yes"
      ;;
    --non-interactive)
      interactive_mode="no"
      ;;
    -h|--help)
      usage
      return 0
      ;;
    *)
      echo "[swarm_core_workspace_env] Unknown argument: $1" >&2
      usage >&2
      return 2
      ;;
  esac
  shift
done

WS="$(swarm_core_detect_workspace_root "$workspace_override" || true)"
if [[ -z "$WS" ]]; then
  echo "[swarm_core_workspace_env] ERROR: Unable to detect workspace root." >&2
  echo "[swarm_core_workspace_env] Set --workspace <path> or SWARM_CORE_WORKSPACE_ROOT and retry." >&2
  return 1
fi

SC="${WS}/src/swarm_control_core"
if [[ ! -d "$SC" ]]; then
  echo "[swarm_core_workspace_env] ERROR: Core package directory not found: $SC" >&2
  return 1
fi

if [[ "$interactive_mode" == "yes" ]] || { [[ "$interactive_mode" == "auto" ]] && [[ -t 0 ]] && [[ -z "$workspace_override" ]]; }; then
  _detected_ws_name="$(basename "$WS")"
  while true; do
    printf 'Detected swarm_control_core workspace: %s\n' "$WS"
    read -r -p "Use this workspace [Y]: " _confirm
    case "${_confirm:-Y}" in
      y|Y)
        break
        ;;
      n|N)
        while true; do
          read -r -p "Workspace directory name or absolute path [${_detected_ws_name}]: " _ws_input
          _ws_input="${_ws_input:-$_detected_ws_name}"
          if [[ "$_ws_input" == /* ]]; then
            _ws_candidate="$_ws_input"
          elif [[ "$_ws_input" == "~/"* ]]; then
            _ws_candidate="${HOME}/${_ws_input#~/}"
          else
            _ws_candidate="${HOME}/${_ws_input}"
          fi
          _ws_candidate="${_ws_candidate%/}"
          if [[ ! -d "${_ws_candidate}/src/swarm_control_core" ]]; then
            echo "[swarm_core_workspace_env] Path does not contain src/swarm_control_core: ${_ws_candidate}" >&2
            continue
          fi
          WS="$_ws_candidate"
          SC="${WS}/src/swarm_control_core"
          _detected_ws_name="$(basename "$WS")"
          break
        done
        break
        ;;
      *)
        echo "Please enter Y, N, or press ENTER." >&2
        ;;
    esac
  done
  unset _confirm _ws_input _ws_candidate
fi

export WS
export SC
export SWARM_CORE_WORKSPACE_ROOT="$WS"
export WS_DEV="$WS"
export SWARM_CORE_WORKSPACE_NAME="$(basename "$WS")"

echo "[swarm_core_workspace_env] WS=${WS}"
echo "[swarm_core_workspace_env] SC=${SC}"
echo "Workspace name has been set to: ${SWARM_CORE_WORKSPACE_NAME}"
