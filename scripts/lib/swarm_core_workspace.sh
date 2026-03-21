#!/usr/bin/env bash
# shellcheck shell=bash

# Shared workspace detection helpers for swarm_control_core scripts.

swarm_core__expand_path() {
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
  if [[ "$raw" == *"/~/"* ]]; then
    raw="${raw//\/~\//\/}"
  fi
  printf '%s' "$raw"
}

swarm_core__search_workspace_upward() {
  local start="${1:-}"
  local dir=""
  dir="$(swarm_core__expand_path "$start")"
  while [[ -n "$dir" && "$dir" != "/" ]]; do
    if [[ -d "$dir/src/swarm_control_core" ]]; then
      printf '%s' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

swarm_core_detect_workspace_root() {
  local requested="${1:-}"
  local candidate=""
  local helper_dir=""
  local pkg_dir=""

  candidate="$(swarm_core__expand_path "$requested")"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return 0
  fi

  candidate="$(swarm_core__expand_path "${SWARM_CORE_WORKSPACE_ROOT:-}")"
  if [[ -n "$candidate" ]]; then
    printf '%s' "$candidate"
    return 0
  fi

  helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  pkg_dir="$(cd "${helper_dir}/../.." && pwd)"
  if [[ "$(basename "$pkg_dir")" == "swarm_control_core" && "$(basename "$(dirname "$pkg_dir")")" == "src" ]]; then
    printf '%s' "$(dirname "$(dirname "$pkg_dir")")"
    return 0
  fi

  return 1
}

swarm_core_workspace_name() {
  local workspace_root="${1:-}"
  workspace_root="$(swarm_core__expand_path "$workspace_root")"
  if [[ -z "$workspace_root" ]]; then
    workspace_root="$(swarm_core_detect_workspace_root 2>/dev/null || true)"
  fi
  if [[ -n "$workspace_root" ]]; then
    basename "$workspace_root"
    return 0
  fi
  return 1
}
