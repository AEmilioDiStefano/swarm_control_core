#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_com_switch_robot_mode.sh [options] <command>

Commands:
  status       Show service status summary.
  activate     Terminate existing robot processes, then start community service.
  deactivate   Stop community service.
  restart      Restart community service.

Options:
  --community-service-name <name>  Community service name (default: com-swarm-robot)
  --existing-service-name <name>   Existing service to stop before activate
                                   (default: swarm-robot)
  --workspace <path>               Workspace root (default: ~/ros2_ws_dev)
  --install-if-missing             Install community service if missing.
  --domain-id <id>                 Domain ID for install-if-missing (default: 17)
  --robot-name <name>              Robot name for install-if-missing (default: $USER)
  -h, --help                       Show this help
USAGE
}

log() {
  echo "[swarm_com_switch_robot_mode] $*" >&2
}

fail() {
  echo "[swarm_com_switch_robot_mode] ERROR: $*" >&2
  exit 1
}

run_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return $?
  fi
  command -v sudo >/dev/null 2>&1 || fail "sudo is required."
  sudo "$@"
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
community_service_name="com-swarm-robot"
existing_service_name="${SWARM_COM_EXISTING_ROBOT_SERVICE:-swarm-robot}"
workspace="${HOME}/ros2_ws_dev"
install_if_missing="0"
domain_id="17"
robot_name="${SWARM_COM_ROBOT_NAME:-${USER:-$(id -un)}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --community-service-name)
      shift
      community_service_name="${1:-}"
      ;;
    --existing-service-name)
      shift
      existing_service_name="${1:-}"
      ;;
    --workspace)
      shift
      workspace="${1:-}"
      ;;
    --install-if-missing)
      install_if_missing="1"
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
      ;;
    --robot-name)
      shift
      robot_name="${1:-}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
  shift
done

[[ $# -ge 1 ]] || fail "Expected <command>."
command_name="$1"

service_installed() {
  local service_name="$1"
  systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "${service_name}.service"
}

print_status() {
  for s in "$existing_service_name" "$community_service_name"; do
    if [[ -z "$s" ]]; then
      continue
    fi
    if service_installed "$s"; then
      local state
      state="$(systemctl is-active "${s}.service" 2>/dev/null || true)"
      log "${s}.service installed; active=${state:-unknown}"
    else
      log "${s}.service not installed"
    fi
  done
}

maybe_install_service() {
  if service_installed "$community_service_name"; then
    return 0
  fi
  if [[ "$install_if_missing" != "1" ]]; then
    fail "Missing ${community_service_name}.service (use --install-if-missing)."
  fi
  "${script_dir}/swarm_com_install_robot_service.sh" \
    --workspace "$workspace" \
    --service-name "$community_service_name" \
    --existing-service-name "$existing_service_name" \
    --domain-id "$domain_id" \
    --robot-name "$robot_name"
}

case "$command_name" in
  status)
    print_status
    ;;
  activate)
    "${script_dir}/swarm_com_terminate_existing_robot_processes.sh" \
      --service-name "$existing_service_name" \
      --service-name "$community_service_name"
    maybe_install_service
    run_root systemctl start "${community_service_name}.service"
    print_status
    ;;
  deactivate)
    if service_installed "$community_service_name"; then
      run_root systemctl stop "${community_service_name}.service"
    fi
    print_status
    ;;
  restart)
    maybe_install_service
    run_root systemctl restart "${community_service_name}.service"
    print_status
    ;;
  *)
    fail "Unknown command: ${command_name}"
    ;;
esac
