#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_com_seed_runtime_config.sh [options]

Options:
  --workspace <path>      Workspace root (default: ~/ros2_ws_dev)
  --target-dir <path>     Runtime config dir (default: ~/.config/swarm_control_core)
  --overwrite             Overwrite existing runtime config files
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
  echo "[swarm_com_seed_runtime_config] $*" >&2
}

fail() {
  echo "[swarm_com_seed_runtime_config] ERROR: $*" >&2
  exit 1
}

workspace="${HOME}/ros2_ws_dev"
target_dir="${HOME}/.config/swarm_control_core"
overwrite="0"

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

if [[ "${workspace}" == "~/"* ]]; then
  workspace="${HOME}/${workspace#~/}"
fi
if [[ "${workspace}" == '$HOME/'* ]]; then
  workspace="${HOME}/${workspace#\$HOME/}"
fi
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
  capability_profiles.yaml
  adapter_profiles.yaml
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
