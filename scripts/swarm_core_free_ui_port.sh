#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_free_ui_port.sh [options]

Options:
  --port <port>        TCP port to free (default: 8080)
  --host <host>        Host label used for logs (default: 127.0.0.1)
  --no-reclaim         Do not kill existing listeners; fail if port is busy.
  --dry-run            Print actions without applying them.
  -h, --help           Show this help

Behavior:
  - Detects listeners on the selected TCP port.
  - Gracefully terminates listeners, then force-kills if needed.
  - Falls back to privileged fuser kill when listener PIDs are hidden.
USAGE
}

log() {
  echo "[swarm_core_free_ui_port] $*" >&2
}

fail() {
  echo "[swarm_core_free_ui_port] ERROR: $*" >&2
  exit 1
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

port="8080"
host="127.0.0.1"
reclaim="1"
dry_run="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      shift
      port="${1:-}"
      ;;
    --host)
      shift
      host="${1:-}"
      ;;
    --no-reclaim)
      reclaim="0"
      ;;
    --dry-run)
      dry_run="1"
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

[[ "$port" =~ ^[0-9]+$ ]] || fail "--port must be numeric"
(( port >= 1 && port <= 65535 )) || fail "--port must be between 1 and 65535"
[[ -n "$host" ]] || fail "--host cannot be empty"

list_listener_pids() {
  local target_port="$1"
  local -a found=()
  local line=""

  if command -v ss >/dev/null 2>&1; then
    while IFS= read -r line; do
      while [[ "$line" =~ pid=([0-9]+) ]]; do
        found+=("${BASH_REMATCH[1]}")
        line="${line#*pid=${BASH_REMATCH[1]}}"
      done
    done < <(ss -ltnp "sport = :${target_port}" 2>/dev/null || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]] && command -v lsof >/dev/null 2>&1; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && found+=("$line")
    done < <(lsof -t -iTCP:"$target_port" -sTCP:LISTEN 2>/dev/null || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]] && command -v fuser >/dev/null 2>&1; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && found+=("$line")
    done < <(fuser -n tcp "$target_port" 2>/dev/null | tr ' ' '\n' || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]]; then
    return 0
  fi

  printf '%s\n' "${found[@]}" | grep -E '^[0-9]+$' | sort -u || true
}

port_is_busy() {
  local target_port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${target_port}" 2>/dev/null | awk 'NR>1 {found=1} END {exit(found ? 0 : 1)}'
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$target_port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  return 1
}

describe_pid() {
  local pid="$1"
  ps -o user= -o pid= -o args= -p "$pid" 2>/dev/null | sed -e 's/^[[:space:]]*//' || true
}

kill_known_ui_processes() {
  local -a patterns=(
    "ros2 launch .*swarm_control_pro.*swarm_fpv_ui.launch.py"
    "ros2 run .*swarm_control_pro.*swarm_fpv_ui"
    "/swarm_control_pro/.*/swarm_fpv_ui"
    "ros2 launch .*swarm_control_core.*swarm_fpv_ui.launch.py"
    "ros2 run .*swarm_control_core.*swarm_fpv_ui"
    "/swarm_control_core/.*/swarm_fpv_ui_core"
  )

  local killed="0"
  local pattern=""
  for pattern in "${patterns[@]}"; do
    if pgrep -af "$pattern" >/dev/null 2>&1; then
      if [[ "$dry_run" == "1" ]]; then
        log "DRY-RUN: would terminate matching process pattern: $pattern"
      else
        pkill -f "$pattern" || true
        log "Terminated matching process pattern: $pattern"
      fi
      killed="1"
    fi
  done

  [[ "$killed" == "1" ]]
}

terminate_pid() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  local desc
  desc="$(describe_pid "$pid")"
  if [[ -n "$desc" ]]; then
    log "Reclaiming ${host}:${port} from: ${desc}"
  else
    log "Reclaiming ${host}:${port} from PID ${pid}"
  fi

  if [[ "$dry_run" == "1" ]]; then
    return 0
  fi

  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
}

if ! port_is_busy "$port"; then
  log "Port ${host}:${port} is already free."
  exit 0
fi

if [[ "$reclaim" != "1" ]]; then
  fail "Port ${host}:${port} is in use and reclaim is disabled."
fi

declare -a pids=()
mapfile -t pids < <(list_listener_pids "$port")

if [[ "${#pids[@]}" -eq 0 ]]; then
  log "Port ${host}:${port} is in use but listener PID ownership is hidden."
  if kill_known_ui_processes; then
    sleep 0.2
  fi
  if ! port_is_busy "$port"; then
    if [[ "$dry_run" == "1" ]]; then
      log "DRY-RUN complete."
    else
      log "Port ${host}:${port} reclaimed successfully."
    fi
    exit 0
  fi
  if [[ "$dry_run" == "1" ]]; then
    log "DRY-RUN: would run privileged fuser reclaim."
  elif command -v fuser >/dev/null 2>&1; then
    log "Attempting privileged reclaim with fuser..."
    run_root fuser -k -TERM -n tcp "$port" >/dev/null || true
    sleep 0.2
    if port_is_busy "$port"; then
      run_root fuser -k -KILL -n tcp "$port" >/dev/null || true
    fi
  else
    fail "fuser is unavailable and listener PID is hidden."
  fi
fi

for pid in "${pids[@]}"; do
  [[ "$pid" == "$$" ]] && continue
  terminate_pid "$pid"
done

if [[ "$dry_run" == "1" ]]; then
  log "DRY-RUN complete."
  exit 0
fi

sleep 0.2
if port_is_busy "$port"; then
  mapfile -t pids < <(list_listener_pids "$port")
  log "Port ${host}:${port} is still in use."
  if [[ "${#pids[@]}" -gt 0 ]]; then
    for pid in "${pids[@]}"; do
      log "  $(describe_pid "$pid")"
    done
  else
    log "  (listener PID still hidden; try: sudo fuser -v -n tcp ${port})"
  fi
  exit 1
fi

log "Port ${host}:${port} reclaimed successfully."
