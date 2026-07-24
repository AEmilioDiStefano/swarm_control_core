#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

log() {
  echo "[swarm_core_ensure_pro_checkout] $*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_ensure_pro_checkout.sh [--workspace <path>] [--repo-url <url>]

Options:
  --workspace <path>  Workspace root. Defaults to SWARM_CORE_WORKSPACE_ROOT,
                      WS, detected workspace, or ~/ros2_ws_dev.
  --repo-url <url>    swarm_control_pro clone URL.
                      Default: https://github.com/Vitruvian-Systems/swarm_control_pro.git
  -h, --help          Show this help.

Behavior:
  - Does nothing when <workspace>/src/swarm_control_pro is already a git checkout.
  - Clones swarm_control_pro only when the package checkout is missing.
  - Never overwrites a non-git directory at <workspace>/src/swarm_control_pro.
USAGE
}

workspace="${SWARM_CORE_WORKSPACE_ROOT:-${WS:-}}"
repo_url="${SWARM_PRO_REPO_URL:-https://github.com/Vitruvian-Systems/swarm_control_pro.git}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace="${1:-}"
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

workspace="$(swarm_core__expand_path "${workspace%/}")"
if [[ -z "$workspace" ]]; then
  workspace="$(swarm_core_detect_workspace_root "" 2>/dev/null || true)"
fi
if [[ -z "$workspace" ]]; then
  workspace="${HOME}/ros2_ws_dev"
fi

pro_dir="${workspace}/src/swarm_control_pro"
bootstrap_file="${pro_dir}/scripts/swarm_bootstrap_env.sh"

if [[ -d "${pro_dir}/.git" ]]; then
  if [[ ! -f "$bootstrap_file" ]]; then
    fail "Existing swarm_control_pro checkout is missing ${bootstrap_file}."
  fi
  log "[OK] swarm_control_pro checkout already present: ${pro_dir}"
  exit 0
fi

if [[ -e "$pro_dir" ]]; then
  if [[ -d "$pro_dir" && -z "$(find "$pro_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    log "Empty swarm_control_pro directory found; cloning into it: ${pro_dir}"
  else
    fail "Path exists but is not a git checkout: ${pro_dir}. Move it aside or convert it to a valid checkout before continuing."
  fi
fi

if ! command -v git >/dev/null 2>&1; then
  fail "git is required to clone swarm_control_pro. Run Step 0 dependency setup first, then retry."
fi

mkdir -p "${workspace}/src"
log "Cloning swarm_control_pro into ${pro_dir}."
git clone "$repo_url" "$pro_dir"

if [[ ! -f "$bootstrap_file" ]]; then
  fail "Clone completed but expected bootstrap helper is missing: ${bootstrap_file}"
fi

log "[OK] swarm_control_pro checkout ready: ${pro_dir}"
