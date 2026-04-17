#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_setup_bootstrap.sh [options]

Options:
  --workspace <path>    Workspace root to create or reuse.
                        Default: detected workspace or ~/ros2_ws_dev
  --repo-url <url>      Clone URL for swarm_control_core.
  --refresh-existing    Refresh an existing git checkout with git fetch/pull.
  --emit-shell          Print export commands for eval usage.
  -h, --help            Show this help.

Behavior:
  - Reuses an existing workspace when one is already explicit in the shell or
    current working tree.
  - Otherwise defaults to ~/ros2_ws_dev for this guide.
  - Creates <workspace>/src when missing.
  - Clones swarm_control_core into <workspace>/src/swarm_control_core when
    missing.
  - Prints a no-op summary when the workspace bootstrap was already complete.
USAGE
}

log() {
  echo "[swarm_core_setup_bootstrap] $*" >&2
}

fail() {
  echo "[swarm_core_setup_bootstrap] ERROR: $*" >&2
  exit 1
}

record_action() {
  actions_taken+=("$1")
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi

  record_action "Installed git"
  log "git is not installed yet. Installing it now."
  if ! command -v sudo >/dev/null 2>&1; then
    fail "git is required and sudo is unavailable, so it could not be installed automatically."
  fi
  sudo apt-get update
  sudo apt-get install -y git
}

detect_target_workspace() {
  local requested="${1:-}"
  local detected=""

  requested="$(swarm_core__expand_path "${requested%/}")"
  if [[ -n "$requested" ]]; then
    printf '%s' "$requested"
    return 0
  fi

  detected="$(swarm_core_detect_workspace_root "" 2>/dev/null || true)"
  if [[ -n "$detected" ]]; then
    printf '%s' "${detected%/}"
    return 0
  fi

  printf '%s' "${HOME}/ros2_ws_dev"
}

ensure_workspace_layout() {
  local workspace_root="$1"

  if [[ ! -d "$workspace_root" ]]; then
    mkdir -p "$workspace_root"
    record_action "Created workspace root: ${workspace_root}"
  fi

  if [[ ! -d "${workspace_root}/src" ]]; then
    mkdir -p "${workspace_root}/src"
    record_action "Created workspace src directory: ${workspace_root}/src"
  fi
}

refresh_existing_checkout() {
  local target_repo="$1"

  if ! git -C "$target_repo" fetch origin --prune \
    || ! { git -C "$target_repo" switch main || git -C "$target_repo" checkout -b main origin/main; } \
    || ! git -C "$target_repo" pull --ff-only origin main; then
    log "WARN: Could not fully refresh ${target_repo}. Keeping the existing checkout so setup can continue."
    return 0
  fi

  record_action "Refreshed existing swarm_control_core checkout: ${target_repo}"
}

ensure_checkout() {
  local target_repo="$1"

  if [[ -d "${target_repo}/.git" ]]; then
    if [[ "$refresh_existing" == "1" ]]; then
      refresh_existing_checkout "$target_repo"
    fi
    return 0
  fi

  if [[ -f "${target_repo}/scripts/swarm_core_workspace_bootstrap.sh" ]]; then
    log "Using existing package directory at ${target_repo}."
    return 0
  fi

  if [[ -e "$target_repo" ]]; then
    fail "Path exists but is not a valid swarm_control_core checkout: ${target_repo}"
  fi

  log "Cloning swarm_control_core into ${target_repo}."
  git clone "$repo_url" "$target_repo"
  record_action "Cloned swarm_control_core into ${target_repo}"
}

print_summary() {
  local workspace_root="$1"
  local package_dir="$2"

  if (( ${#actions_taken[@]} == 0 )); then
    log "Bootstrap already complete at ${workspace_root}. No workspace checkout changes were needed."
  else
    log "Bootstrap completed at ${workspace_root}."
    for action in "${actions_taken[@]}"; do
      log " - ${action}"
    done
  fi

  if [[ -d "${package_dir}" && -f "${package_dir}/scripts/swarm_core_workspace_bootstrap.sh" ]]; then
    log "Workspace bootstrap is complete and ready to use."
  else
    fail "Workspace bootstrap could not be confirmed at ${package_dir}"
  fi
}

workspace_override=""
repo_url="https://github.com/AEmilioDiStefano/swarm_control_core.git"
emit_shell="0"
refresh_existing="0"
declare -a actions_taken=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace_override="${1:-}"
      ;;
    --repo-url)
      shift
      repo_url="${1:-}"
      ;;
    --refresh-existing)
      refresh_existing="1"
      ;;
    --emit-shell)
      emit_shell="1"
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

workspace_root="$(detect_target_workspace "$workspace_override")"
workspace_root="${workspace_root%/}"
[[ -n "$workspace_root" ]] || fail "Unable to determine a workspace root."
[[ -n "$repo_url" ]] || fail "--repo-url cannot be empty."

ensure_git
ensure_workspace_layout "$workspace_root"

package_dir="${workspace_root}/src/swarm_control_core"
ensure_checkout "$package_dir"

workspace_bootstrap="${package_dir}/scripts/swarm_core_workspace_bootstrap.sh"
[[ -x "$workspace_bootstrap" ]] || fail "Expected executable workspace bootstrap script at ${workspace_bootstrap}"

print_summary "$workspace_root" "$package_dir"

if [[ "$emit_shell" == "1" ]]; then
  "$workspace_bootstrap" --workspace "$workspace_root" --non-interactive --emit-shell
else
  "$workspace_bootstrap" --workspace "$workspace_root" --non-interactive
fi
