#!/usr/bin/env bash
# shellcheck shell=bash

# First-contact bootstrap for swarm_control_core.
#
# Designed to be fetched and piped to bash on a machine that may not have the
# repository yet:
#
#   wget -qO- https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/main/scripts/swarm_core_first_contact.sh | bash -s -- --setup control
#
# It finds or clones the workspace, installs the ~/.local/bin/swarmc and
# ~/.local/bin/swarmp launcher shims, and optionally runs full machine setup.
# Keep this file thin: it is frozen at fetch time, so real logic must live in
# the repo scripts it delegates to.

set -euo pipefail

log() {
  echo "[swarm_core_first_contact] $*" >&2
}

fail() {
  echo "[swarm_core_first_contact] ERROR: $*" >&2
  exit 1
}

workspace="${SWARM_CORE_WORKSPACE_ROOT:-${WS:-$HOME/ros2_ws_dev}}"
workspace="${workspace%/}"
setup_role=""
with_pro="0"
repo_url="https://github.com/AEmilioDiStefano/swarm_control_core.git"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace="${1:?--workspace needs a path}"
      ;;
    --setup)
      shift
      setup_role="${1:?--setup needs control or robot}"
      ;;
    --with-pro)
      with_pro="1"
      ;;
    --repo-url)
      shift
      repo_url="${1:?--repo-url needs a URL}"
      ;;
    -h|--help)
      echo "Usage: swarm_core_first_contact.sh [--workspace <path>] [--setup control|robot] [--with-pro]"
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
  shift || true
done

case "${setup_role}" in
  ""|control|robot) ;;
  *) fail "--setup must be 'control' or 'robot', got: ${setup_role}" ;;
esac

if ! command -v git >/dev/null 2>&1; then
  log "installing git"
  sudo apt-get -o DPkg::Lock::Timeout=1800 update
  sudo apt-get -o DPkg::Lock::Timeout=1800 install -y git
fi

pkg_dir=""
existing="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f \
  -path "*/swarm_control_core/scripts/swarmc" 2>/dev/null | sort | head -n1)"
if [[ -n "$existing" ]]; then
  existing_pkg="$(cd "$(dirname "$existing")/.." && pwd)"
  if [[ "$(basename "$(dirname "$existing_pkg")")" == "src" ]]; then
    pkg_dir="$existing_pkg"
    workspace="$(cd "${pkg_dir}/../.." && pwd)"
  else
    pkg_dir="${workspace}/src/swarm_control_core"
    install -d "${workspace}/src"
    if [[ -e "$pkg_dir" && "$(readlink -f "$pkg_dir")" != "$existing_pkg" ]]; then
      fail "${pkg_dir} already points to a different checkout; set --workspace to use another workspace."
    fi
    if [[ ! -e "$pkg_dir" ]]; then
      ln -s "$existing_pkg" "$pkg_dir"
      log "adopted standalone checkout into workspace: ${pkg_dir} -> ${existing_pkg}"
    fi
  fi
  log "reusing existing checkout: ${existing_pkg}"
else
  pkg_dir="${workspace}/src/swarm_control_core"
  install -d "${workspace}/src"
fi

# An interrupted earlier clone can leave a directory that looks present but
# is not a usable git repo; quarantine it instead of trusting or deleting it.
if [[ -d "$pkg_dir" ]] && ! git -C "$pkg_dir" rev-parse --git-dir >/dev/null 2>&1; then
  quarantine="${pkg_dir}.corrupt.$(date +%Y%m%d_%H%M%S)"
  log "Existing checkout at ${pkg_dir} is not a valid git repo; moving it to ${quarantine}"
  mv "$pkg_dir" "$quarantine"
fi
if [[ ! -d "${pkg_dir}/.git" ]]; then
  log "cloning swarm_control_core into ${pkg_dir}"
  git clone "$repo_url" "$pkg_dir"
fi

"${pkg_dir}/scripts/swarm_core_install_launchers.sh" --workspace "$workspace"

if [[ -n "$setup_role" ]]; then
  SWARM_CORE_WORKSPACE_ROOT="$workspace" \
    "${pkg_dir}/scripts/swarmc" setup --role "$setup_role"
fi

if [[ "$with_pro" == "1" ]]; then
  SWARM_CORE_WORKSPACE_ROOT="$workspace" \
    "${pkg_dir}/scripts/swarmc" ensure-pro
fi

log "[OK] First contact complete. Workspace: ${workspace}"
log "Use ~/.local/bin/swarmc in this terminal; plain 'swarmc' works in new terminals."
if [[ "$with_pro" == "1" ]]; then
  log "Pro launcher available as ~/.local/bin/swarmp."
fi
