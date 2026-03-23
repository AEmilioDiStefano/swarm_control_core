#!/usr/bin/env bash
set -euo pipefail

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
  swarm_core_checkout_workspace.sh --mode <default|existing> [--emit-shell] [--repo-url <url>] [--workspace-src <path>]

Modes:
  default   Create or refresh the default workspace at ~/ros2_ws_dev and ensure
            swarm_control_core is checked out at ~/ros2_ws_dev/src/swarm_control_core.
  existing  If the current directory is a workspace src/ directory, add or
            refresh swarm_control_core there. If not, but the default workspace
            from Step 1.1 already exists, reuse that workspace safely instead
            of failing in a way that could interrupt the shell session.

Options:
  --emit-shell   Print export commands for eval usage.
  --repo-url     Git clone URL (default: official swarm_control_core repository).
  --workspace-src
                 Existing workspace src/ directory to use when --mode existing.
                 This allows the script to run from any current directory.
  -h, --help     Show this help.

Environment:
  SWARM_CORE_GIT_BRANCH
      Branch to clone/update (default: current checkout branch when detectable,
      otherwise main).
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
  local target_branch="${SWARM_CORE_GIT_BRANCH:-}"
  target_src="$(dirname "$target_repo")"
  mkdir -p "$target_src"

  if [[ -d "${target_repo}/.git" ]]; then
    if [[ -z "$target_branch" ]]; then
      target_branch="$(git -C "$target_repo" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    fi
    if [[ -z "$target_branch" ]]; then
      target_branch="main"
    fi
    log "Refreshing existing checkout at ${target_repo}."
    if ! git -C "$target_repo" fetch origin --prune \
      || ! git -C "$target_repo" show-ref --verify --quiet "refs/remotes/origin/${target_branch}" \
      || ! { git -C "$target_repo" switch "$target_branch" || git -C "$target_repo" checkout -b "$target_branch" "origin/${target_branch}"; } \
      || ! git -C "$target_repo" pull --ff-only origin "$target_branch"; then
      log "WARN: Could not fully refresh ${target_repo}. Keeping the existing checkout so setup can continue."
    fi
    return 0
  fi

  if [[ -e "$target_repo" ]]; then
    fail "Path exists but is not a git checkout: ${target_repo}"
  fi

  if [[ -z "$target_branch" ]]; then
    target_branch="main"
  fi
  log "Cloning swarm_control_core into ${target_repo}."
  git clone --branch "$target_branch" --single-branch "$repo_url" "$target_repo"
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
workspace_src=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      shift
      mode="${1:-}"
      ;;
    --emit-shell)
      emit_shell="1"
      ;;
    --repo-url)
      shift
      repo_url="${1:-}"
      ;;
    --workspace-src)
      shift
      workspace_src="${1:-}"
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

default_ws="${HOME}/ros2_ws_dev"
default_sc="${default_ws}/src/swarm_control_core"

workspace_root=""
package_dir=""

case "$mode" in
  default)
    ensure_git
    clone_or_update_repo "$default_sc"
    workspace_root="$default_ws"
    package_dir="$default_sc"
    log "Using default workspace at ${workspace_root}."
    ;;
  existing)
    ensure_git
    current_dir="${PWD%/}"
    if [[ -n "$workspace_src" ]]; then
      workspace_src="${workspace_src%/}"
      if [[ "$(basename "$workspace_src")" != "src" || ! -d "$workspace_src" ]]; then
        log "The package can only be added to a ROS 2 workspace src directory."
        log "The --workspace-src value must point to an existing .../src directory."
        exit 2
      fi
      workspace_root="$(dirname "$workspace_src")"
      package_dir="${workspace_src}/swarm_control_core"
      log "Using explicit workspace src directory: ${workspace_src}"
      clone_or_update_repo "$package_dir"
    elif [[ "$(basename "$current_dir")" == "src" ]]; then
      workspace_root="$(dirname "$current_dir")"
      package_dir="${current_dir}/swarm_control_core"
      log "Current directory is a workspace src directory: ${current_dir}"
      clone_or_update_repo "$package_dir"
    elif [[ -d "${default_sc}/.git" ]]; then
      workspace_root="$default_ws"
      package_dir="$default_sc"
      log "Current directory is not a workspace src directory: ${current_dir}"
      log "Step 1.1 appears to have already prepared the default workspace at ${default_ws}."
      log "Keeping that workspace so setup can continue safely."
      clone_or_update_repo "$package_dir"
    else
      log "Current directory is not a workspace src directory: ${current_dir}"
      log "The package can only be added to a ROS 2 workspace src directory."
      log "Example: --workspace-src /path/to/your_ws/src"
      log "Or run Step 1.1 to create ~/ros2_ws_dev automatically."
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
