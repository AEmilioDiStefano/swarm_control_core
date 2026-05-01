#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_seed_runtime_config.sh [options]

Options:
  --workspace <path>      Workspace root (default: auto-detect)
  --target-dir <path>     Runtime config dir (default: ~/.config/swarm_control_core)
  --overwrite             Overwrite existing runtime config files
  --overwrite-core-profiles
                          Overwrite existing core profile files but keep
                          existing camera_profiles.yaml
  -h, --help              Show this help

Behavior:
  Copies required runtime config files from:
    <workspace>/src/swarm_control_core/config
  to:
    <target-dir>
  Missing files are created. Existing files are kept unless --overwrite is used.
USAGE
}

log() {
  echo "[swarm_core_seed_runtime_config] $*" >&2
}

fail() {
  echo "[swarm_core_seed_runtime_config] ERROR: $*" >&2
  exit 1
}

workspace=""
target_dir="${HOME}/.config/swarm_control_core"
overwrite="0"
overwrite_core_profiles="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace="${1:-}"
      ;;
    --target-dir)
      shift
      target_dir="${1:-}"
      ;;
    --overwrite)
      overwrite="1"
      ;;
    --overwrite-core-profiles)
      overwrite_core_profiles="1"
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

workspace="$(swarm_core_detect_workspace_root "$workspace" || true)"
[[ -n "$workspace" ]] || fail "Unable to detect workspace root. Pass --workspace or set SWARM_CORE_WORKSPACE_ROOT."
if [[ "${target_dir}" == "~/"* ]]; then
  target_dir="${HOME}/${target_dir#~/}"
fi
if [[ "${target_dir}" == '$HOME/'* ]]; then
  target_dir="${HOME}/${target_dir#\$HOME/}"
fi

src_dir="${workspace}/src/swarm_control_core/config"
[[ -d "$src_dir" ]] || fail "Config source directory not found: $src_dir"

required_files=(
  robot_instances.yaml
  control_types.yaml
  control_interfaces.yaml
  camera_profiles.yaml
)

mkdir -p "$target_dir"

copied=0
kept=0
for f in "${required_files[@]}"; do
  src_file="${src_dir}/${f}"
  dst_file="${target_dir}/${f}"
  [[ -f "$src_file" ]] || fail "Missing required source file: $src_file"
  if [[ -f "$dst_file" && "$overwrite" != "1" ]]; then
    if [[ "$overwrite_core_profiles" == "1" && "$f" != "robot_instances.yaml" && "$f" != "camera_profiles.yaml" ]]; then
      cp -f "$src_file" "$dst_file"
      chmod 644 "$dst_file" || true
      copied=$((copied + 1))
      log "Refreshed core profile: ${dst_file}"
      continue
    fi
    kept=$((kept + 1))
    log "Keeping existing: ${dst_file}"
    continue
  fi
  cp -f "$src_file" "$dst_file"
  chmod 644 "$dst_file" || true
  copied=$((copied + 1))
  log "Seeded: ${dst_file}"
done

log "Done (copied=${copied}, kept=${kept}, target=${target_dir})."
