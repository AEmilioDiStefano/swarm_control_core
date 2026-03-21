#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_terminate_existing_robot_processes.sh [options]

Options:
  --machine-role <control|robot|auto>
                                   Apply role-specific behavior (default: auto)
  --compat-mode                    Community compatibility prep mode:
                                   stop conflicting services/processes and, on robots,
                                   apply runtime-only masks to proprietary services.
  --compat-stop-ufw <auto|always|never>
                                   In compat mode, optionally stop ufw at runtime
                                   so DDS traffic is not blocked by restrictive
                                   firewall policy. Defaults to env
                                   SWARM_CORE_COMPAT_STOP_UFW or auto.
  --service-name <name>            Existing robot service name to stop.
                                   Repeat to pass multiple names.
                                   Defaults: swarm-robot, swarm-core-robot
  --runtime-mask-service <name>    Service to runtime-mask in compat mode (robot role).
                                   Repeatable. Default: swarm-robot, swarm-agent
  --skip-user-process-kill         Do not kill non-systemd ROS launch processes.
  --dry-run                        Print actions without applying them.
  -h, --help                       Show this help

Behavior:
  - Stops known robot services if present.
  - Best-effort kills local user ROS launch/run processes for robot bringup/UI.
  - In --compat-mode on robots, runtime masks clear automatically on reboot.
  - In --compat-mode, ufw runtime stop (if enabled) is temporary and returns on reboot.
USAGE
}

log() {
  echo "[swarm_core_terminate_existing_robot_processes] $*" >&2
}

run_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return $?
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return $?
  fi
  return 1
}

trim() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

dry_run="0"
kill_user_processes="1"
machine_role="auto"
compat_mode="0"
compat_stop_ufw="${SWARM_CORE_COMPAT_STOP_UFW:-auto}"
declare -a service_names=()
declare -a runtime_mask_services=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --machine-role)
      shift
      machine_role="${1:-}"
      ;;
    --compat-mode)
      compat_mode="1"
      ;;
    --compat-stop-ufw)
      shift
      compat_stop_ufw="${1:-}"
      ;;
    --service-name)
      shift
      service_names+=("${1:-}")
      ;;
    --runtime-mask-service)
      shift
      runtime_mask_services+=("${1:-}")
      ;;
    --skip-user-process-kill)
      kill_user_processes="0"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[swarm_core_terminate_existing_robot_processes] ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

machine_role="$(printf '%s' "$(trim "$machine_role")" | tr '[:upper:]' '[:lower:]')"
[[ "$machine_role" == "auto" || "$machine_role" == "control" || "$machine_role" == "robot" ]] || {
  echo "[swarm_core_terminate_existing_robot_processes] ERROR: --machine-role must be control, robot, or auto." >&2
  exit 2
}
compat_stop_ufw="$(printf '%s' "$(trim "$compat_stop_ufw")" | tr '[:upper:]' '[:lower:]')"
[[ "$compat_stop_ufw" == "auto" || "$compat_stop_ufw" == "always" || "$compat_stop_ufw" == "never" ]] || {
  echo "[swarm_core_terminate_existing_robot_processes] ERROR: --compat-stop-ufw must be auto, always, or never." >&2
  exit 2
}

if [[ "${#service_names[@]}" -eq 0 ]]; then
  service_names=("swarm-robot" "swarm-core-robot")
fi

if [[ "$compat_mode" == "1" ]]; then
  service_names+=("swarm-agent")
fi

_service_catalog_loaded="0"
_service_catalog_text=""

load_service_catalog() {
  [[ "$_service_catalog_loaded" == "1" ]] && return 0
  _service_catalog_loaded="1"
  if ! command -v systemctl >/dev/null 2>&1; then
    _service_catalog_text=""
    return 0
  fi
  _service_catalog_text="$(
    systemctl list-unit-files --type=service --no-legend 2>/dev/null \
      | awk '{print $1}' \
      || true
  )"
}

service_exists() {
  local service_name="$1"
  load_service_catalog
  grep -Fxq "${service_name}.service" <<< "${_service_catalog_text}"
}

ufw_service_exists() {
  load_service_catalog
  grep -Fxq "ufw.service" <<< "${_service_catalog_text}"
}

ufw_is_active() {
  systemctl is-active --quiet ufw.service
}

effective_machine_role="$machine_role"
if [[ "$effective_machine_role" == "auto" ]]; then
  if [[ -e /dev/gpiomem ]] || service_exists "swarm-robot" || service_exists "swarm-core-robot" || service_exists "swarm-agent"; then
    effective_machine_role="robot"
  else
    effective_machine_role="control"
  fi
fi
log "machine_role=${effective_machine_role} (requested=${machine_role})"

stop_service_if_present() {
  local service_name="$1"
  service_name="$(trim "$service_name")"
  [[ -n "$service_name" ]] || return 0
  if ! service_exists "$service_name"; then
    log "Service not installed: ${service_name}.service"
    return 0
  fi
  if [[ "$dry_run" == "1" ]]; then
    log "DRY-RUN stop ${service_name}.service"
    return 0
  fi
  if run_root systemctl stop "${service_name}.service"; then
    log "Stopped ${service_name}.service"
  else
    log "WARN: Failed to stop ${service_name}.service (permissions or policy)."
  fi
}

mask_runtime_if_present() {
  local service_name="$1"
  service_name="$(trim "$service_name")"
  [[ -n "$service_name" ]] || return 0
  if ! service_exists "$service_name"; then
    log "Runtime mask skip (service not installed): ${service_name}.service"
    return 0
  fi
  if [[ "$dry_run" == "1" ]]; then
    log "DRY-RUN systemctl mask --runtime ${service_name}.service"
    return 0
  fi
  if run_root systemctl mask --runtime "${service_name}.service"; then
    log "Applied runtime mask: ${service_name}.service (clears on reboot)"
  else
    log "WARN: Failed to runtime-mask ${service_name}.service"
  fi
}

maybe_stop_ufw_runtime_for_compat() {
  [[ "$compat_mode" == "1" ]] || return 0

  if [[ "$compat_stop_ufw" == "never" ]]; then
    log "compat-mode ufw runtime stop disabled (--compat-stop-ufw=never)."
    return 0
  fi

  if ! ufw_service_exists; then
    log "compat-mode ufw runtime stop skipped (ufw.service not installed)."
    return 0
  fi

  if ! ufw_is_active; then
    log "compat-mode ufw runtime stop skipped (ufw.service already inactive)."
    return 0
  fi

  if [[ "$dry_run" == "1" ]]; then
    log "DRY-RUN systemctl stop ufw.service"
    return 0
  fi

  if run_root systemctl stop ufw.service; then
    log "Stopped ufw.service for community compat mode (runtime-only override)."
    log "Firewall policy is restored by reboot (or: sudo systemctl start ufw.service)."
  else
    log "WARN: Failed to stop ufw.service for compat mode."
  fi
}

kill_user_launches() {
  local -a patterns=(
    "ros2 launch .*swarm_control_core.*swarm_bringup.launch.py"
    "ros2 launch .*swarm_control_core.*robot_minimal.launch.py"
    "ros2 launch .*swarm_control_core.*swarm_fpv_ui.launch.py"
    "ros2 launch .*swarm_control.*swarm_bringup.launch.py"
    "ros2 launch .*swarm_control.*swarm_fpv_ui.launch.py"
    "ros2 run .*swarm_control_core.*swarm_fpv_ui"
    "ros2 run .*swarm_control_core.*swarm_teleop"
    "ros2 run .*swarm_control_core.*terminal_orchestrator"
    "swarm_control_core/.*/swarm_fpv_ui_core"
    "swarm_control_core/.*/swarm_teleop_core"
    "swarm_control_core/.*/terminal_orchestrator_core"
    "ros2 run .*swarm_control.*swarm_fpv_ui"
    "ros2 run .*swarm_control.*swarm_teleop"
    "ros2 run .*swarm_control.*terminal_orchestrator"
    "fastdds discovery"
  )

  for pattern in "${patterns[@]}"; do
    if pgrep -af "$pattern" >/dev/null 2>&1; then
      if [[ "$dry_run" == "1" ]]; then
        log "DRY-RUN pkill -f \"$pattern\""
      else
        pkill -f "$pattern" || true
        log "Terminated user process pattern: $pattern"
      fi
    fi
  done
}

for service_name in "${service_names[@]}"; do
  stop_service_if_present "$service_name"
done

if [[ "$compat_mode" == "1" && "$effective_machine_role" == "robot" ]]; then
  if [[ "${#runtime_mask_services[@]}" -eq 0 ]]; then
    runtime_mask_services=("swarm-robot" "swarm-agent")
  fi
  for service_name in "${runtime_mask_services[@]}"; do
    mask_runtime_if_present "$service_name"
  done
  log "compat-mode runtime masks will be cleared automatically at reboot."
fi

maybe_stop_ufw_runtime_for_compat

if [[ "$kill_user_processes" == "1" ]]; then
  kill_user_launches
fi

log "Done."
