#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

_qs_common_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./swarm_core_workspace.sh
source "${_qs_common_dir}/swarm_core_workspace.sh"

swarm_core_qs_fail() {
  echo "[swarm_core_quickstart] $*" >&2
  exit 1
}

swarm_core_qs_warn() {
  echo "[swarm_core_quickstart] WARN: $*" >&2
}

swarm_core_qs_detect_workspace() {
  local requested="${1:-}"
  local ws=""
  ws="$(swarm_core_detect_workspace_root "$requested" 2>/dev/null || true)"
  if [[ -z "$ws" || ! -d "$ws/src/swarm_control_core" ]]; then
    swarm_core_qs_fail "Could not detect a valid workspace containing src/swarm_control_core."
  fi
  printf '%s' "$ws"
}

swarm_core_qs_prepare_workspace_env() {
  local ws="${1:-}"
  if [[ -z "$ws" ]]; then
    swarm_core_qs_fail "Workspace path is required."
  fi
  export WS="$ws"
  export SC="${ws}/src/swarm_control_core"
  export SWARM_CORE_WORKSPACE_ROOT="$ws"
}

swarm_core_qs_source_reset_env() {
  local ws="${1:-}"
  local machine_role="${2:-}"
  local domain_id="${3:-17}"
  local compat_mode="${4:-1}"
  local skip_process_reset="${5:-0}"
  local reset_script="${ws}/src/swarm_control_core/scripts/swarm_core_reset_env.sh"

  [[ -f "$reset_script" ]] || swarm_core_qs_fail "Missing reset helper: ${reset_script}"

  local args=(--scope deep --machine-role "$machine_role" --domain-id "$domain_id")
  if [[ "$compat_mode" == "1" ]]; then
    args+=(--compat-mode)
  fi
  if [[ "$skip_process_reset" == "1" ]]; then
    args+=(--skip-process-reset)
  fi

  set +u
  # shellcheck disable=SC1090
  source "$reset_script" "${args[@]}"
  set -u || true
}

swarm_core_qs_source_ros_overlay() {
  local ws="${1:-}"
  set +u
  # shellcheck source=/dev/null
  source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
  # shellcheck source=/dev/null
  source "${ws}/install/setup.bash"
  set -u || true
}

swarm_core_qs_git_sync() {
  local sc="${1:-}"
  local current_branch=""
  local current_commit=""
  local fetch_ok="1"
  cd "$sc"
  if ! git fetch origin --prune; then
    fetch_ok="0"
    swarm_core_qs_warn "GitHub fetch failed; continuing with the local checkout. Check DNS/network if you expected an online sync."
  fi

  if git show-ref --verify --quiet refs/heads/main; then
    if ! git switch main; then
      swarm_core_qs_warn "Could not switch to local branch 'main'; continuing with the current checkout."
    fi
  elif git show-ref --verify --quiet refs/remotes/origin/main; then
    if ! git checkout -b main origin/main; then
      swarm_core_qs_warn "Could not create local branch 'main' from origin/main; continuing with the current checkout."
    fi
  else
    swarm_core_qs_warn "No local 'main' branch reference is available; continuing with the current checkout."
  fi

  current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ "$fetch_ok" == "1" && "$current_branch" == "main" ]]; then
    if ! git pull --ff-only origin main; then
      swarm_core_qs_warn "git pull --ff-only origin main failed; continuing with the current local checkout."
    fi
  fi

  current_commit="$(git rev-parse --short HEAD 2>/dev/null || true)"
  echo "[swarm_core_quickstart] git checkout: branch=${current_branch:-unknown} commit=${current_commit:-unknown}"
}

swarm_core_qs_wireless_iface() {
  if ! command -v iw >/dev/null 2>&1; then
    return 1
  fi
  iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}'
}
