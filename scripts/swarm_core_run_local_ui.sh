#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[swarm_core_run_local_ui] $*" >&2
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${SWARM_CORE_WORKSPACE_ROOT:-$HOME/ros2_ws_dev}"
BIND_HOST="${SWARM_CORE_BIND_HOST:-127.0.0.1}"
BIND_PORT="${SWARM_CORE_BIND_PORT:-8080}"
RECLAIM_BIND_PORT="${SWARM_CORE_RECLAIM_BIND_PORT:-1}"
export ROS_DOMAIN_ID="${SWARM_CORE_ROS_DOMAIN_ID:-17}"

# Guard against stale proprietary discovery/session exports.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

if [[ "${SWARM_CORE_ALLOW_LAN_BIND:-0}" != "1" ]]; then
  BIND_HOST="127.0.0.1"
fi

list_listener_pids() {
  local port="$1"
  local -a found=()
  local line=""

  if command -v ss >/dev/null 2>&1; then
    while IFS= read -r line; do
      while [[ "$line" =~ pid=([0-9]+) ]]; do
        found+=("${BASH_REMATCH[1]}")
        line="${line#*pid=${BASH_REMATCH[1]}}"
      done
    done < <(ss -ltnp "sport = :${port}" 2>/dev/null || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]] && command -v lsof >/dev/null 2>&1; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && found+=("$line")
    done < <(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]] && command -v fuser >/dev/null 2>&1; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && found+=("$line")
    done < <(fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' || true)
  fi

  if [[ "${#found[@]}" -eq 0 ]]; then
    return 0
  fi

  printf '%s\n' "${found[@]}" | grep -E '^[0-9]+$' | sort -u || true
}

port_is_busy() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${port}" 2>/dev/null | awk 'NR>1 {found=1} END {exit(found ? 0 : 1)}'
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  return 1
}

describe_pid() {
  local pid="$1"
  ps -o user= -o pid= -o args= -p "$pid" 2>/dev/null | sed -e 's/^[[:space:]]*//' || true
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
    log "Reclaiming ${BIND_HOST}:${BIND_PORT} from: ${desc}"
  else
    log "Reclaiming ${BIND_HOST}:${BIND_PORT} from PID ${pid}"
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

reclaim_bind_port_if_needed() {
  if ! port_is_busy "$BIND_PORT"; then
    return 0
  fi

  local -a pids=()
  mapfile -t pids < <(list_listener_pids "$BIND_PORT")

  if [[ "$RECLAIM_BIND_PORT" != "1" ]]; then
    log "ERROR: ${BIND_HOST}:${BIND_PORT} already in use and reclaim is disabled."
    log "Set SWARM_CORE_RECLAIM_BIND_PORT=1 to force reclaim."
    return 1
  fi

  if [[ "${#pids[@]}" -eq 0 ]]; then
    log "Port ${BIND_HOST}:${BIND_PORT} is in use but PID ownership is not visible."
    if command -v fuser >/dev/null 2>&1; then
      log "Attempting privileged reclaim with fuser..."
      run_root fuser -k -TERM -n tcp "$BIND_PORT" >/dev/null 2>&1 || true
      sleep 0.2
      if port_is_busy "$BIND_PORT"; then
        run_root fuser -k -KILL -n tcp "$BIND_PORT" >/dev/null 2>&1 || true
      fi
    fi
  fi

  for pid in "${pids[@]}"; do
    [[ "$pid" == "$$" ]] && continue
    terminate_pid "$pid"
  done

  sleep 0.2
  if port_is_busy "$BIND_PORT"; then
    mapfile -t pids < <(list_listener_pids "$BIND_PORT")
    log "ERROR: could not reclaim ${BIND_HOST}:${BIND_PORT}; still in use by:"
    if [[ "${#pids[@]}" -gt 0 ]]; then
      for pid in "${pids[@]}"; do
        log "  $(describe_pid "$pid")"
      done
    else
      log "  (listener PID hidden; try: sudo fuser -v -n tcp ${BIND_PORT})"
    fi
    return 1
  fi
}

set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
source "$WS/install/setup.bash"
set -u || true

# Enforce community LAN discovery defaults after sourcing overlays.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
export SWARM_DISCOVERY_MODE="multicast"
export SWARM_ROLE="control"
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE="${SWARM_CORE_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export RMW_IMPLEMENTATION="${SWARM_CORE_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

export SWARM_CORE_BIND_HOST="$BIND_HOST"
export SWARM_CORE_BIND_PORT="$BIND_PORT"
export SWARM_CORE_AUTH_MODE="off"
export SWARM_CORE_ALLOW_ANON_READONLY="false"
export SWARM_CORE_WEBRTC_ICE_SERVERS_JSON='[]'
export SWARM_CORE_WEBRTC_ICE_TRANSPORT_POLICY="all"
export SWARM_CORE_WEBRTC_FPS="${SWARM_CORE_WEBRTC_FPS:-15.0}"
export SWARM_CORE_THUMB_REFRESH_HZ="${SWARM_CORE_THUMB_REFRESH_HZ:-0.5}"
export SWARM_CORE_IMAGE_SUBSCRIPTION_MODE="${SWARM_CORE_IMAGE_SUBSCRIPTION_MODE:-active_only}"
export SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S="${SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S:-0.75}"
export SWARM_CORE_THUMB_ROBOTS_PER_TICK="${SWARM_CORE_THUMB_ROBOTS_PER_TICK:-0}"
export SWARM_CORE_DRIVE_CMD_RATE_HZ="${SWARM_CORE_DRIVE_CMD_RATE_HZ:-20.0}"
export SWARM_CORE_DRIVE_HOLD_TIMEOUT_S="${SWARM_CORE_DRIVE_HOLD_TIMEOUT_S:-0.35}"
if ! [[ "${SWARM_CORE_THUMB_ROBOTS_PER_TICK}" =~ ^-?[0-9]+$ ]]; then
  log "Invalid SWARM_CORE_THUMB_ROBOTS_PER_TICK='${SWARM_CORE_THUMB_ROBOTS_PER_TICK}', forcing 0."
  export SWARM_CORE_THUMB_ROBOTS_PER_TICK="0"
elif (( SWARM_CORE_THUMB_ROBOTS_PER_TICK < 0 )); then
  log "Negative SWARM_CORE_THUMB_ROBOTS_PER_TICK='${SWARM_CORE_THUMB_ROBOTS_PER_TICK}', forcing 0."
  export SWARM_CORE_THUMB_ROBOTS_PER_TICK="0"
fi

log "bind=${SWARM_CORE_BIND_HOST}:${SWARM_CORE_BIND_PORT}"
log "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
log "discovery_env=cleared"
log "SWARM_DISCOVERY_MODE=${SWARM_DISCOVERY_MODE}"
log "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
log "ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}"
log "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
log "stream=WebRTC-only main stream"
log "webrtc_fps=${SWARM_CORE_WEBRTC_FPS}"
log "thumb_refresh_hz=${SWARM_CORE_THUMB_REFRESH_HZ}"
log "image_subscription_mode=${SWARM_CORE_IMAGE_SUBSCRIPTION_MODE}"
log "image_thumb_interest_ttl_s=${SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S}"
log "thumb_robots_per_tick=${SWARM_CORE_THUMB_ROBOTS_PER_TICK}"
log "drive_cmd_rate_hz=${SWARM_CORE_DRIVE_CMD_RATE_HZ}"
log "drive_hold_timeout_s=${SWARM_CORE_DRIVE_HOLD_TIMEOUT_S}"
if [[ "${SWARM_CORE_ALLOW_LAN_BIND:-0}" == "1" ]]; then
  log "LAN bind enabled (private LAN use only)."
else
  log "loopback-only mode enforced."
fi

term_args=(--machine-role control)
if [[ "${SWARM_CORE_COMPAT_PREP:-1}" == "1" ]]; then
  term_args+=(--compat-mode)
fi
if [[ "${SWARM_CORE_PROCESS_RESET_DONE:-0}" == "1" ]]; then
  log "process reset already completed in this shell; skipping duplicate reset."
  export SWARM_CORE_PROCESS_RESET_DONE="0"
else
  "${SCRIPT_DIR}/swarm_core_terminate_existing_robot_processes.sh" "${term_args[@]}" || true
  export SWARM_CORE_PROCESS_RESET_DONE="1"
fi
if [[ -x "${SCRIPT_DIR}/swarm_core_free_ui_port.sh" ]]; then
  if [[ "$RECLAIM_BIND_PORT" == "1" ]]; then
    "${SCRIPT_DIR}/swarm_core_free_ui_port.sh" --host "$BIND_HOST" --port "$BIND_PORT"
  else
    "${SCRIPT_DIR}/swarm_core_free_ui_port.sh" --host "$BIND_HOST" --port "$BIND_PORT" --no-reclaim
  fi
else
  reclaim_bind_port_if_needed
fi

ui_pid=""

cleanup() {
  local ec=$?
  if [[ -n "$ui_pid" ]] && kill -0 "$ui_pid" 2>/dev/null; then
    log "Stopping local UI process tree (pid=${ui_pid})"
    kill -TERM "-${ui_pid}" 2>/dev/null || kill -TERM "${ui_pid}" 2>/dev/null || true
    wait "$ui_pid" 2>/dev/null || true
  fi
  exit "$ec"
}
trap cleanup EXIT INT TERM

if command -v setsid >/dev/null 2>&1; then
  setsid ros2 launch swarm_control_core swarm_launch/swarm_fpv_ui.launch.py \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    bind_host:="$SWARM_CORE_BIND_HOST" \
    bind_port:="$SWARM_CORE_BIND_PORT" \
    webrtc_fps:="$SWARM_CORE_WEBRTC_FPS" \
    thumb_refresh_hz:="$SWARM_CORE_THUMB_REFRESH_HZ" \
    image_subscription_mode:="$SWARM_CORE_IMAGE_SUBSCRIPTION_MODE" \
    image_thumb_interest_ttl_s:="$SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S" \
    thumb_robots_per_tick:="$SWARM_CORE_THUMB_ROBOTS_PER_TICK" \
    drive_cmd_rate_hz:="$SWARM_CORE_DRIVE_CMD_RATE_HZ" \
    drive_hold_timeout_s:="$SWARM_CORE_DRIVE_HOLD_TIMEOUT_S" &
else
  ros2 launch swarm_control_core swarm_launch/swarm_fpv_ui.launch.py \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    bind_host:="$SWARM_CORE_BIND_HOST" \
    bind_port:="$SWARM_CORE_BIND_PORT" \
    webrtc_fps:="$SWARM_CORE_WEBRTC_FPS" \
    thumb_refresh_hz:="$SWARM_CORE_THUMB_REFRESH_HZ" \
    image_subscription_mode:="$SWARM_CORE_IMAGE_SUBSCRIPTION_MODE" \
    image_thumb_interest_ttl_s:="$SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S" \
    thumb_robots_per_tick:="$SWARM_CORE_THUMB_ROBOTS_PER_TICK" \
    drive_cmd_rate_hz:="$SWARM_CORE_DRIVE_CMD_RATE_HZ" \
    drive_hold_timeout_s:="$SWARM_CORE_DRIVE_HOLD_TIMEOUT_S" &
fi
ui_pid="$!"
wait "$ui_pid"
