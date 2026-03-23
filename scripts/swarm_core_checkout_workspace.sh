#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

log() {
  echo "[swarm_core_checkout_workspace] $*" >&2
}

fail() {
  log "ERROR: $*"
  exit 2
}

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_checkout_workspace.sh --mode <default|existing> [--workspace <path>] [--emit-shell] [--repo-url <url>]

Modes:
  default   Create or refresh the workspace you choose and ensure
            swarm_control_core is checked out at <workspace>/src/swarm_control_core.
  existing  If the current directory is a workspace src/ directory, add or
            refresh swarm_control_core there. If not, but --workspace (or
            SWARM_CORE_WORKSPACE_ROOT) already points at a valid workspace,
            reuse that workspace safely instead of guessing a workspace name.

Options:
  --workspace   Target workspace root.
  --emit-shell   Print export commands for eval usage.
  --repo-url     Git clone URL (default: official swarm_control_core repository).
  -h, --help     Show this help.
USAGE
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  log "git is not installed yet. Installing it now."
  if ! command -v sudo >/dev/null 2>&1; then
    fail "git is required and sudo is unavailable, so it could not be installed automatically."
  fi
  sudo apt-get update
  sudo apt-get install -y git
}

clone_or_update_repo() {
  local target_repo="$1"
  local target_src=""
  target_src="$(dirname "$target_repo")"
  mkdir -p "$target_src"

  if [[ -d "${target_repo}/.git" ]]; then
    log "Refreshing existing checkout at ${target_repo}."
    if ! git -C "$target_repo" fetch origin --prune \
      || ! { git -C "$target_repo" switch main || git -C "$target_repo" checkout -b main origin/main; } \
      || ! git -C "$target_repo" pull --ff-only origin main; then
      log "WARN: Could not fully refresh ${target_repo}. Keeping the existing checkout so setup can continue."
    fi
    return 0
  fi

  if [[ -e "$target_repo" ]]; then
    fail "Path exists but is not a git checkout: ${target_repo}"
  fi

  log "Cloning swarm_control_core into ${target_repo}."
  git clone "$repo_url" "$target_repo"
}

emit_workspace_exports() {
  local ws="$1"
  local sc="$2"
  local ws_name=""
  ws_name="$(basename "$ws")"

  printf 'export WS=%q\n' "$ws"
  printf 'export SC=%q\n' "$sc"
  printf 'export SWARM_CORE_WORKSPACE_ROOT=%q\n' "$ws"
  printf 'export WS_DEV=%q\n' "$ws"
  printf 'export SWARM_CORE_WORKSPACE_NAME=%q\n' "$ws_name"
  printf 'echo %q\n' "[OK] Workspace root: ${ws}"
  printf 'echo %q\n' "[OK] Package checkout: ${sc}"
}

mode=""
emit_shell="0"
repo_url="https://github.com/AEmilioDiStefano/swarm_control_core.git"
workspace_override="${SWARM_CORE_WORKSPACE_ROOT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      shift
      mode="${1:-}"
      ;;
    --emit-shell)
      emit_shell="1"
      ;;
    --workspace)
      shift
      workspace_override="${1:-}"
      ;;
    --repo-url)
      shift
      repo_url="${1:-}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$mode" ]] || fail "--mode is required."

workspace_override="$(swarm_core__expand_path "${workspace_override%/}")"

workspace_root=""
package_dir=""

case "$mode" in
  default)
    ensure_git
    workspace_root="${workspace_override%/}"
    if [[ -z "$workspace_root" ]]; then
      if [[ -t 0 ]]; then
        printf 'Enter workspace path to create or refresh (absolute path or ~/...): ' >&2
        read -r workspace_root
      fi
    fi
    [[ -n "${workspace_root// }" ]] || fail "--workspace is required for --mode default."
    if [[ "$workspace_root" == "~/"* ]]; then
      workspace_root="${HOME}/${workspace_root#~/}"
    fi
    package_dir="${workspace_root}/src/swarm_control_core"
    clone_or_update_repo "$package_dir"
    log "Using workspace at ${workspace_root}."
    ;;
  existing)
    ensure_git
    current_dir="${PWD%/}"
    if [[ "$(basename "$current_dir")" == "src" ]]; then
      workspace_root="$(dirname "$current_dir")"
      package_dir="${current_dir}/swarm_control_core"
      log "Current directory is a workspace src directory: ${current_dir}"
      clone_or_update_repo "$package_dir"
    elif [[ -n "$workspace_override" ]] && [[ -d "${workspace_override}/src" ]]; then
      workspace_root="$workspace_override"
      package_dir="${workspace_root}/src/swarm_control_core"
      log "Current directory is not a workspace src directory: ${current_dir}"
      log "Reusing workspace specified by --workspace/SWARM_CORE_WORKSPACE_ROOT: ${workspace_root}"
      clone_or_update_repo "$package_dir"
    elif workspace_root="$(swarm_core__search_workspace_upward "$current_dir" || true)"; [[ -n "$workspace_root" && -d "${workspace_root}/src" ]]; then
      package_dir="${workspace_root}/src/swarm_control_core"
      log "Current directory is not a workspace src directory: ${current_dir}"
      log "Detected workspace from current directory: ${workspace_root}"
      clone_or_update_repo "$package_dir"
    else
      log "Current directory is not a workspace src directory: ${current_dir}"
      log "The package can only be added to a ROS 2 workspace src directory."
      log "Example: cd /path/to/your_ws/src"
      log "Then rerun with --workspace /path/to/your_ws if you want to reuse a known workspace."
      exit 2
    fi
    ;;
  *)
    fail "--mode must be default or existing."
    ;;
esac

if [[ "$emit_shell" == "1" ]]; then
  emit_workspace_exports "$workspace_root" "$package_dir"
else
  log "Workspace root: ${workspace_root}"
  log "Package checkout: ${package_dir}"
fi
