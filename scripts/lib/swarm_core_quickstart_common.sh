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
  local config_dir_was_set="0"
  local preserved_config_dir=""

  if [[ -v SWARM_CORE_CONFIG_DIR ]]; then
    config_dir_was_set="1"
    preserved_config_dir="$SWARM_CORE_CONFIG_DIR"
  fi

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

  # Deep reset clears compatibility/runtime variables. Restore structural
  # locators so adopted standalone checkouts and custom runtime config paths
  # remain usable by the launcher that requested the reset.
  swarm_core_qs_prepare_workspace_env "$ws"
  if [[ "$config_dir_was_set" == "1" ]]; then
    export SWARM_CORE_CONFIG_DIR="$preserved_config_dir"
  fi
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

swarm_core_qs_prune_legacy_launch_share() {
  local ws="${1:-}"
  local source_legacy_dir="${ws}/src/swarm_control_core/launch"
  local build_legacy_dir="${ws}/build/swarm_control_core/swarm_launch"
  local legacy_dir="${ws}/install/swarm_control_core/share/swarm_control_core/swarm_launch"
  local canonical_dir="${ws}/install/swarm_control_core/share/swarm_control_core/launch"

  [[ -n "$ws" ]] || swarm_core_qs_fail "Workspace path is required."

  if [[ -d "$source_legacy_dir" ]]; then
    rm -rf "$source_legacy_dir"
    echo "[swarm_core_quickstart] Removed stale source launch directory: ${source_legacy_dir}"
  fi

  if [[ -d "$build_legacy_dir" ]]; then
    rm -rf "$build_legacy_dir"
    echo "[swarm_core_quickstart] Removed stale build launch directory: ${build_legacy_dir}"
  fi

  if [[ -d "$legacy_dir" ]]; then
    rm -rf "$legacy_dir"
    echo "[swarm_core_quickstart] Removed stale install launch directory: ${legacy_dir}"
  fi

  if [[ -d "$canonical_dir" ]]; then
    echo "[swarm_core_quickstart] Canonical launch directory: ${canonical_dir}"
  fi
}

swarm_core_qs_verify_launch_share() {
  local ws="${1:-}"
  local launch_dir="${ws}/install/swarm_control_core/share/swarm_control_core/launch"
  local -a required=(
    "swarm_bringup.launch.py"
    "swarm_fpv_ui.launch.py"
    "robot_minimal_launch.py"
  )
  local missing=0
  local name=""

  [[ -n "$ws" ]] || swarm_core_qs_fail "Workspace path is required."

  if [[ ! -d "$launch_dir" ]]; then
    swarm_core_qs_fail "Missing installed launch directory after build: ${launch_dir}"
  fi

  for name in "${required[@]}"; do
    if [[ ! -f "${launch_dir}/${name}" ]]; then
      swarm_core_qs_warn "Missing installed launch file: ${launch_dir}/${name}"
      missing=1
    fi
  done

  if [[ "$missing" == "1" ]]; then
    swarm_core_qs_fail "Launch-file install verification failed."
  fi

  echo "[swarm_core_quickstart] Verified launch files in: ${launch_dir}"
}

swarm_core_qs_wireless_iface() {
  if ! command -v iw >/dev/null 2>&1; then
    return 1
  fi
  iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}'
}
