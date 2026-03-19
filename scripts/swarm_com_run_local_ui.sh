#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[swarm_com_run_local_ui] $*" >&2
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
# shellcheck source=./lib/swarm_com_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_com_workspace.sh"
WS="$(swarm_com_detect_workspace_root "${SWARM_COM_WORKSPACE_ROOT:-}" || true)"
if [[ -z "$WS" ]]; then
  log "ERROR: unable to detect workspace root; set SWARM_COM_WORKSPACE_ROOT."
  exit 1
fi
BIND_HOST="${SWARM_COM_BIND_HOST:-127.0.0.1}"
BIND_PORT="${SWARM_COM_BIND_PORT:-8080}"
RECLAIM_BIND_PORT="${SWARM_COM_RECLAIM_BIND_PORT:-1}"
export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"

# Guard against stale proprietary discovery/session exports.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

if [[ "${SWARM_COM_ALLOW_LAN_BIND:-0}" != "1" ]]; then
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
    log "Set SWARM_COM_RECLAIM_BIND_PORT=1 to force reclaim."
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
export ROS_LOCALHOST_ONLY=0
export ROS_AUTOMATIC_DISCOVERY_RANGE="${SWARM_COM_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export SWARM_COM_REQUIRE_UFW_INACTIVE="${SWARM_COM_REQUIRE_UFW_INACTIVE:-1}"

is_truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
  esac
  return 1
}

check_ufw_runtime_guard() {
  local range_lc="${ROS_AUTOMATIC_DISCOVERY_RANGE,,}"
  if [[ "$range_lc" == "off" ]]; then
    return 0
  fi
  if ! is_truthy "$SWARM_COM_REQUIRE_UFW_INACTIVE"; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if systemctl is-active --quiet ufw.service; then
    log "ERROR: ufw.service is active and likely blocking DDS discovery/traffic."
    log "Run compat reset in this control shell, then retry:"
    log "  source \"$SCRIPT_DIR/swarm_com_reset_env.sh\" --scope deep --machine-role control --compat-mode --domain-id \"\${SWARM_COM_ROS_DOMAIN_ID:-17}\""
    log "Override guard only if your firewall rules are already DDS-safe: export SWARM_COM_REQUIRE_UFW_INACTIVE=0"
    exit 2
  fi
}

warn_if_wifi_powersave_enabled() {
  if ! command -v iw >/dev/null 2>&1; then
    return 0
  fi
  if ! iw dev wlan0 info >/dev/null 2>&1; then
    return 0
  fi
  if iw dev wlan0 get power_save 2>/dev/null | grep -qi 'Power save: on'; then
    log "WARN: wlan0 power save is ON. This can cause lag spikes in local Wi-Fi sessions."
    log "Recommend once per boot: sudo iw dev wlan0 set power_save off"
  fi
}

check_ufw_runtime_guard
warn_if_wifi_powersave_enabled

export SWARM_COM_BIND_HOST="$BIND_HOST"
export SWARM_COM_BIND_PORT="$BIND_PORT"
export SWARM_COM_AUTH_MODE="off"
export SWARM_COM_ALLOW_ANON_READONLY="false"
export SWARM_COM_WEBRTC_ICE_SERVERS_JSON='[]'
export SWARM_COM_WEBRTC_ICE_TRANSPORT_POLICY="all"
export SWARM_COM_MAIN_STREAM_FPS="${SWARM_COM_MAIN_STREAM_FPS:-15.0}"
export SWARM_COM_WEBRTC_FPS="${SWARM_COM_WEBRTC_FPS:-15.0}"
export SWARM_COM_WEBRTC_MAIN_ONLY="${SWARM_COM_WEBRTC_MAIN_ONLY:-0}"
export SWARM_COM_THUMB_REFRESH_HZ="${SWARM_COM_THUMB_REFRESH_HZ:-0.5}"
export SWARM_COM_IMAGE_SUBSCRIPTION_MODE="${SWARM_COM_IMAGE_SUBSCRIPTION_MODE:-active_only}"
export SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S="${SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S:-6.0}"
export SWARM_COM_THUMB_ROBOTS_PER_TICK="${SWARM_COM_THUMB_ROBOTS_PER_TICK:-1}"
export SWARM_COM_DRIVE_CMD_RATE_HZ="${SWARM_COM_DRIVE_CMD_RATE_HZ:-15.0}"
export SWARM_COM_DRIVE_HOLD_TIMEOUT_S="${SWARM_COM_DRIVE_HOLD_TIMEOUT_S:-0.10}"
export SWARM_COM_DRIVE_RATE_EMA_ALPHA="${SWARM_COM_DRIVE_RATE_EMA_ALPHA:-0.25}"
case "${SWARM_COM_WEBRTC_MAIN_ONLY,,}" in
  1|true|yes|on)
    export SWARM_COM_WEBRTC_MAIN_ONLY="true"
    ;;
  0|false|no|off)
    export SWARM_COM_WEBRTC_MAIN_ONLY="false"
    ;;
  *)
    log "Invalid SWARM_COM_WEBRTC_MAIN_ONLY='${SWARM_COM_WEBRTC_MAIN_ONLY}', forcing true."
    export SWARM_COM_WEBRTC_MAIN_ONLY="true"
    ;;
esac
if ! [[ "${SWARM_COM_THUMB_ROBOTS_PER_TICK}" =~ ^-?[0-9]+$ ]]; then
  log "Invalid SWARM_COM_THUMB_ROBOTS_PER_TICK='${SWARM_COM_THUMB_ROBOTS_PER_TICK}', forcing 1."
  export SWARM_COM_THUMB_ROBOTS_PER_TICK="1"
elif (( SWARM_COM_THUMB_ROBOTS_PER_TICK < 0 )); then
  log "Negative SWARM_COM_THUMB_ROBOTS_PER_TICK='${SWARM_COM_THUMB_ROBOTS_PER_TICK}', forcing 0."
  export SWARM_COM_THUMB_ROBOTS_PER_TICK="0"
fi

log "bind=${SWARM_COM_BIND_HOST}:${SWARM_COM_BIND_PORT}"
log "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
log "discovery_env=cleared"
log "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
log "ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}"
log "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
if [[ "${SWARM_COM_WEBRTC_MAIN_ONLY}" == "true" ]]; then
  log "stream=WebRTC-only main stream (no MJPEG fallback)"
else
  log "stream=WebRTC primary main stream + MJPEG fallback"
fi
log "main_stream_fps=${SWARM_COM_MAIN_STREAM_FPS}"
log "webrtc_fps=${SWARM_COM_WEBRTC_FPS}"
log "webrtc_main_only=${SWARM_COM_WEBRTC_MAIN_ONLY}"
log "thumb_refresh_hz=${SWARM_COM_THUMB_REFRESH_HZ}"
log "image_subscription_mode=${SWARM_COM_IMAGE_SUBSCRIPTION_MODE}"
log "image_thumb_interest_ttl_s=${SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S}"
log "thumb_robots_per_tick=${SWARM_COM_THUMB_ROBOTS_PER_TICK}"
log "drive_cmd_rate_hz=${SWARM_COM_DRIVE_CMD_RATE_HZ}"
log "drive_hold_timeout_s=${SWARM_COM_DRIVE_HOLD_TIMEOUT_S}"
log "drive_rate_ema_alpha=${SWARM_COM_DRIVE_RATE_EMA_ALPHA}"
if [[ "${SWARM_COM_ALLOW_LAN_BIND:-0}" == "1" ]]; then
  log "LAN bind enabled (private LAN use only)."
else
  log "loopback-only mode enforced."
fi

term_args=(--machine-role control)
if [[ "${SWARM_COM_COMPAT_PREP:-1}" == "1" ]]; then
  term_args+=(--compat-mode)
fi
if [[ "${SWARM_COM_PROCESS_RESET_DONE:-0}" == "1" ]]; then
  log "process reset already completed in this shell; skipping duplicate reset."
  export SWARM_COM_PROCESS_RESET_DONE="0"
else
  "${SCRIPT_DIR}/swarm_com_terminate_existing_robot_processes.sh" "${term_args[@]}" || true
  export SWARM_COM_PROCESS_RESET_DONE="1"
fi
if [[ -x "${SCRIPT_DIR}/swarm_com_free_ui_port.sh" ]]; then
  if [[ "$RECLAIM_BIND_PORT" == "1" ]]; then
    "${SCRIPT_DIR}/swarm_com_free_ui_port.sh" --host "$BIND_HOST" --port "$BIND_PORT"
  else
    "${SCRIPT_DIR}/swarm_com_free_ui_port.sh" --host "$BIND_HOST" --port "$BIND_PORT" --no-reclaim
  fi
else
  reclaim_bind_port_if_needed
fi

ui_pid=""
_cleanup_done="0"

seconds_to_ticks() {
  local seconds="${1:-0}"
  awk -v s="$seconds" 'BEGIN { t=int((s*10)+0.5); if (t < 1) t=1; print t }'
}

wait_for_exit() {
  local pid="$1"
  local seconds="$2"
  local ticks
  ticks="$(seconds_to_ticks "$seconds")"
  for ((i=0; i<ticks; i++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

stop_ui_tree() {
  local pid="$1"
  local int_grace="${SWARM_COM_UI_SHUTDOWN_INT_GRACE_S:-4.0}"
  local term_grace="${SWARM_COM_UI_SHUTDOWN_TERM_GRACE_S:-3.0}"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  log "Stopping local UI process tree (pid=${pid}) with SIGINT..."
  kill -INT "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
  if wait_for_exit "$pid" "$int_grace"; then
    return 0
  fi

  log "Local UI still running; escalating to SIGTERM..."
  kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  if wait_for_exit "$pid" "$term_grace"; then
    return 0
  fi

  log "Local UI still running; forcing SIGKILL..."
  kill -KILL "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
}

cleanup() {
  local ec=$?
  if [[ "$_cleanup_done" == "1" ]]; then
    return 0
  fi
  _cleanup_done="1"
  trap - EXIT INT TERM
  if [[ -n "$ui_pid" ]] && kill -0 "$ui_pid" 2>/dev/null; then
    stop_ui_tree "$ui_pid"
    wait "$ui_pid" 2>/dev/null || true
  fi
  exit "$ec"
}
trap cleanup EXIT INT TERM

if command -v setsid >/dev/null 2>&1; then
  setsid ros2 launch swarm_control_core swarm_fpv_ui.launch.py \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    bind_host:="$SWARM_COM_BIND_HOST" \
    bind_port:="$SWARM_COM_BIND_PORT" \
    main_stream_fps:="$SWARM_COM_MAIN_STREAM_FPS" \
    webrtc_fps:="$SWARM_COM_WEBRTC_FPS" \
    webrtc_main_only:="$SWARM_COM_WEBRTC_MAIN_ONLY" \
    thumb_refresh_hz:="$SWARM_COM_THUMB_REFRESH_HZ" \
    image_subscription_mode:="$SWARM_COM_IMAGE_SUBSCRIPTION_MODE" \
    image_thumb_interest_ttl_s:="$SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S" \
    thumb_robots_per_tick:="$SWARM_COM_THUMB_ROBOTS_PER_TICK" \
    drive_cmd_rate_hz:="$SWARM_COM_DRIVE_CMD_RATE_HZ" \
    drive_hold_timeout_s:="$SWARM_COM_DRIVE_HOLD_TIMEOUT_S" \
    drive_rate_ema_alpha:="$SWARM_COM_DRIVE_RATE_EMA_ALPHA" &
else
  ros2 launch swarm_control_core swarm_fpv_ui.launch.py \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    bind_host:="$SWARM_COM_BIND_HOST" \
    bind_port:="$SWARM_COM_BIND_PORT" \
    main_stream_fps:="$SWARM_COM_MAIN_STREAM_FPS" \
    webrtc_fps:="$SWARM_COM_WEBRTC_FPS" \
    webrtc_main_only:="$SWARM_COM_WEBRTC_MAIN_ONLY" \
    thumb_refresh_hz:="$SWARM_COM_THUMB_REFRESH_HZ" \
    image_subscription_mode:="$SWARM_COM_IMAGE_SUBSCRIPTION_MODE" \
    image_thumb_interest_ttl_s:="$SWARM_COM_IMAGE_THUMB_INTEREST_TTL_S" \
    thumb_robots_per_tick:="$SWARM_COM_THUMB_ROBOTS_PER_TICK" \
    drive_cmd_rate_hz:="$SWARM_COM_DRIVE_CMD_RATE_HZ" \
    drive_hold_timeout_s:="$SWARM_COM_DRIVE_HOLD_TIMEOUT_S" \
    drive_rate_ema_alpha:="$SWARM_COM_DRIVE_RATE_EMA_ALPHA" &
fi
ui_pid="$!"
wait "$ui_pid"
