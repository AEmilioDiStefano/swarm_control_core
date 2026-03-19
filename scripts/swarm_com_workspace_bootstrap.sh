#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_com_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_com_workspace.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_com_workspace_bootstrap.sh [--workspace <path>] [--search-root <path>] [--interactive|--non-interactive] [--emit-shell]

Behavior:
  - Detects the workspace containing swarm_control_core from anywhere.
  - Optionally confirms detected workspace interactively.
  - With --emit-shell, prints export commands to stdout for eval usage.

Examples:
  eval "$(/path/to/swarm_com_workspace_bootstrap.sh --interactive --emit-shell)"
  /path/to/swarm_com_workspace_bootstrap.sh --workspace /home/user/ros2_ws --non-interactive
USAGE
}

emit_shell="0"
interactive_mode="auto"
workspace_override=""
search_root="${SWARM_SEARCH_ROOT:-$HOME}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace_override="${1:-}"
      ;;
    --search-root)
      shift
      search_root="${1:-}"
      ;;
    --interactive)
      interactive_mode="yes"
      ;;
    --non-interactive)
      interactive_mode="no"
      ;;
    --emit-shell)
      emit_shell="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[swarm_com_workspace_bootstrap] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

expand_core_path() {
  local raw="${1:-}"
  if [[ -z "$raw" ]]; then
    printf '%s' ""
    return 0
  fi
  if [[ "$raw" == "~/"* ]]; then
    raw="${HOME}/${raw#~/}"
  elif [[ "$raw" == '$HOME/'* ]]; then
    raw="${HOME}/${raw#\$HOME/}"
  fi
  printf '%s' "$raw"
}

resolve_env_script() {
  local ws_candidate="${1:-}"
  local expanded=""
  if [[ -z "$ws_candidate" ]]; then
    return 1
  fi
  expanded="$(expand_core_path "$ws_candidate")"
  if [[ -f "${expanded}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh" ]]; then
    printf '%s' "${expanded}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh"
    return 0
  fi
  return 1
}

resolve_from_pwd() {
  local cur="${PWD}"
  while [[ -n "$cur" && "$cur" != "/" ]]; do
    if [[ -f "${cur}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh" ]]; then
      printf '%s' "${cur}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh"
      return 0
    fi
    cur="$(dirname "$cur")"
  done
  return 1
}

env_script=""
script_workspace_root="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

if [[ -n "$workspace_override" ]]; then
  env_script="$(resolve_env_script "$workspace_override" || true)"
elif env_from_pwd="$(resolve_from_pwd || true)"; [[ -n "$env_from_pwd" ]]; then
  env_script="$env_from_pwd"
elif [[ -f "${script_workspace_root}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh" ]]; then
  env_script="${script_workspace_root}/src/swarm_control_core/scripts/swarm_com_workspace_env.sh"
elif [[ -n "${SWARM_COM_WORKSPACE_ROOT:-}" ]]; then
  env_script="$(resolve_env_script "${SWARM_COM_WORKSPACE_ROOT}" || true)"
fi

if [[ -z "$env_script" ]]; then
  mapfile -t env_candidates < <(find "$search_root" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_com_workspace_env.sh" 2>/dev/null | sort)
  if (( ${#env_candidates[@]} == 0 )); then
    echo "[FAIL] Could not locate swarm_control_core workspace under $search_root." >&2
    exit 1
  fi
  if (( ${#env_candidates[@]} > 1 )); then
    echo "[WARN] Multiple swarm_control_core workspaces found; using: ${env_candidates[0]}" >&2
    echo "       Set SWARM_COM_WORKSPACE_ROOT=/path/to/workspace to force selection." >&2
  fi
  env_script="${env_candidates[0]}"
fi

workspace_root="$(cd "$(dirname "$env_script")/../../.." && pwd)"
if [[ ! -d "${workspace_root}/src/swarm_control_core" ]]; then
  echo "[swarm_com_workspace_bootstrap] ERROR: Invalid workspace root derived from ${env_script}" >&2
  exit 1
fi

if [[ "$interactive_mode" == "yes" ]] || { [[ "$interactive_mode" == "auto" ]] && [[ -t 0 ]]; }; then
  detected_name="$(basename "$workspace_root")"
  while true; do
    printf '\nA workspace called [%s] has been detected as the parent workspace for the swarm_control_core package. Is this correct?\n' "$detected_name" >&2
    printf '(Y/n): ' >&2
    read -r confirm
    case "${confirm:-Y}" in
      y|Y)
        break
        ;;
      n|N)
        while true; do
          printf 'Enter workspace directory name: ' >&2
          read -r ws_input
          if [[ -z "${ws_input// }" ]]; then
            echo "[swarm_com_workspace_bootstrap] Workspace directory name cannot be empty." >&2
            continue
          fi
          if [[ "$ws_input" == /* ]]; then
            ws_candidate="$ws_input"
          elif [[ "$ws_input" == "~/"* ]]; then
            ws_candidate="${HOME}/${ws_input#~/}"
          else
            ws_candidate="${HOME}/${ws_input}"
          fi
          ws_candidate="${ws_candidate%/}"
          if [[ ! -d "${ws_candidate}/src/swarm_control_core" ]]; then
            echo "[swarm_com_workspace_bootstrap] Path does not contain src/swarm_control_core: ${ws_candidate}" >&2
            continue
          fi
          workspace_root="$ws_candidate"
          detected_name="$(basename "$workspace_root")"
          break
        done
        break
        ;;
      *)
        echo "Please enter Y, N, or press ENTER." >&2
        ;;
    esac
  done
fi

SC="${workspace_root}/src/swarm_control_core"
WORKSPACE_NAME="$(basename "$workspace_root")"

if [[ "$emit_shell" == "1" ]]; then
  printf 'export WS=%q\n' "$workspace_root"
  printf 'export SC=%q\n' "$SC"
  printf 'export SWARM_COM_WORKSPACE_ROOT=%q\n' "$workspace_root"
  printf 'export WS_DEV=%q\n' "$workspace_root"
  printf 'export SWARM_COM_WORKSPACE_NAME=%q\n' "$WORKSPACE_NAME"
  printf 'echo %q\n' "Workspace name has been set to: ${WORKSPACE_NAME}"
else
  echo "[swarm_com_workspace_bootstrap] WS=${workspace_root}"
  echo "[swarm_com_workspace_bootstrap] SC=${SC}"
  echo "Workspace name has been set to: ${WORKSPACE_NAME}"
fi
