#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_com_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_com_workspace.sh"

WS="$(swarm_com_detect_workspace_root "${SWARM_COM_WORKSPACE_ROOT:-}" || true)"
[[ -n "$WS" ]] || {
  echo "[swarm_com_run_robot] ERROR: unable to detect workspace root; set SWARM_COM_WORKSPACE_ROOT." >&2
  exit 1
}
ROBOT_NAME="${1:-${SWARM_COM_ROBOT_NAME:-${USER}}}"
USE_CAMERA_RAW="${SWARM_COM_USE_CAMERA:-true}"
CAMERA_PIPELINE="${SWARM_COM_CAMERA_PIPELINE:-adapter}"

export ROS_DOMAIN_ID="${SWARM_COM_ROS_DOMAIN_ID:-17}"

# Guard against stale proprietary discovery/session exports.
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset ROS_STATIC_PEERS
unset ROS_AUTOMATIC_DISCOVERY_RANGE
unset ROS_LOCALHOST_ONLY

USE_CAMERA="$(printf '%s' "$USE_CAMERA_RAW" | tr '[:upper:]' '[:lower:]')"
if [[ "$USE_CAMERA" != "true" && "$USE_CAMERA" != "false" ]]; then
  echo "[swarm_com_run_robot] WARN: invalid SWARM_COM_USE_CAMERA='${USE_CAMERA_RAW}', defaulting to true" >&2
  USE_CAMERA="true"
fi

if [[ "${SWARM_COM_TERMINATE_EXISTING_PROCESSES:-1}" == "1" ]]; then
  if [[ "${SWARM_COM_PROCESS_RESET_DONE:-0}" == "1" ]]; then
    echo "[swarm_com_run_robot] process reset already completed in this shell; skipping duplicate reset."
    export SWARM_COM_PROCESS_RESET_DONE="0"
  else
    term_args=(--machine-role robot)
    if [[ "${SWARM_COM_COMPAT_PREP:-1}" == "1" ]]; then
      term_args+=(--compat-mode)
    fi
    "${SCRIPT_DIR}/swarm_com_terminate_existing_robot_processes.sh" "${term_args[@]}" || true
    export SWARM_COM_PROCESS_RESET_DONE="1"
  fi
fi

if [[ -x "${SCRIPT_DIR}/swarm_com_seed_runtime_config.sh" ]]; then
  seed_args=(--workspace "$WS")
  if [[ "${SWARM_COM_SEED_OVERWRITE_CORE_PROFILES:-1}" == "1" ]]; then
    seed_args+=(--overwrite-core-profiles)
  fi
  if [[ "${SWARM_COM_SEED_OVERWRITE_ALL_PROFILES:-0}" == "1" ]]; then
    seed_args+=(--overwrite)
  fi
  "${SCRIPT_DIR}/swarm_com_seed_runtime_config.sh" "${seed_args[@]}" || true
fi

runtime_cfg_dir="${SWARM_COM_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
if [[ -f "${runtime_cfg_dir}/robot_instances.yaml" ]]; then
  export PROFILES_PATH="${runtime_cfg_dir}/robot_instances.yaml"
fi
if [[ -f "${runtime_cfg_dir}/camera_profiles.yaml" ]]; then
  export CAMERA_PROFILES_PATH="${runtime_cfg_dir}/camera_profiles.yaml"
fi

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
    echo "[swarm_com_run_robot] ERROR: ufw.service is active and likely blocking DDS discovery/traffic." >&2
    echo "[swarm_com_run_robot] Run compat reset in this robot shell, then retry:" >&2
    echo "  source \"$SCRIPT_DIR/swarm_com_reset_env.sh\" --scope deep --machine-role robot --compat-mode --domain-id \"\${SWARM_COM_ROS_DOMAIN_ID:-17}\"" >&2
    echo "[swarm_com_run_robot] Override guard only if your firewall rules are already DDS-safe: export SWARM_COM_REQUIRE_UFW_INACTIVE=0" >&2
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
    echo "[swarm_com_run_robot] WARN: wlan0 power save is ON. This can cause lag spikes/SSH instability under load." >&2
    echo "[swarm_com_run_robot] Recommend once per boot: sudo iw dev wlan0 set power_save off" >&2
  fi
}

check_ufw_runtime_guard
warn_if_wifi_powersave_enabled

echo "[swarm_com_run_robot] ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "[swarm_com_run_robot] discovery_env=cleared"
echo "[swarm_com_run_robot] ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "[swarm_com_run_robot] ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}"
echo "[swarm_com_run_robot] RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}"
echo "[swarm_com_run_robot] use_camera=${USE_CAMERA} camera_pipeline=${CAMERA_PIPELINE}"
if [[ -n "${PROFILES_PATH:-}" ]]; then
  echo "[swarm_com_run_robot] PROFILES_PATH=${PROFILES_PATH}"
fi
if [[ -n "${CAMERA_PROFILES_PATH:-}" ]]; then
  echo "[swarm_com_run_robot] CAMERA_PROFILES_PATH=${CAMERA_PROFILES_PATH}"
fi

launch_pid=""
ready_probe_pid=""
_shutdown_in_progress="0"
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

kill_launch_tree() {
  local pid="$1"
  local int_grace="${SWARM_COM_SHUTDOWN_INT_GRACE_S:-5.0}"
  local term_grace="${SWARM_COM_SHUTDOWN_TERM_GRACE_S:-3.0}"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  echo "[swarm_com_run_robot] Stopping launch process tree (pid=${pid}) with SIGINT..." >&2
  kill -INT "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
  if wait_for_exit "$pid" "$int_grace"; then
    return 0
  fi

  echo "[swarm_com_run_robot] Launch still running; escalating to SIGTERM..." >&2
  kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  if wait_for_exit "$pid" "$term_grace"; then
    return 0
  fi

  echo "[swarm_com_run_robot] Launch still running; forcing SIGKILL..." >&2
  kill -KILL "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
}

topic_count() {
  local topic="$1"
  local label="$2"
  local out count
  out="$(ros2 topic info "$topic" 2>/dev/null || true)"
  count="$(printf '%s\n' "$out" | awk -F': ' -v k="$label" '$1==k {print $2; exit}')"
  if [[ "$count" =~ ^[0-9]+$ ]]; then
    printf '%s' "$count"
  else
    printf '0'
  fi
}

readiness_probe() {
  local timeout_s="${SWARM_COM_READY_TIMEOUT_S:-45}"
  local warned="0"
  local start_s now_s elapsed_s
  start_s="$(date +%s)"

  while [[ -n "$launch_pid" ]] && kill -0 "$launch_pid" 2>/dev/null; do
    local hb_pub cmd_sub cam_comp_pub cam_raw_pub
    hb_pub="$(topic_count "/${ROBOT_NAME}/heartbeat" "Publisher count")"
    cmd_sub="$(topic_count "/${ROBOT_NAME}/cmd_vel" "Subscription count")"
    cam_comp_pub="$(topic_count "/${ROBOT_NAME}/camera/image_raw/compressed" "Publisher count")"
    cam_raw_pub="$(topic_count "/${ROBOT_NAME}/camera/image_raw" "Publisher count")"

    local hb_ok cmd_ok cam_ok
    hb_ok="0"
    cmd_ok="0"
    cam_ok="1"

    (( hb_pub >= 1 )) && hb_ok="1"
    (( cmd_sub >= 1 )) && cmd_ok="1"
    if [[ "${USE_CAMERA}" == "true" ]]; then
      if (( cam_comp_pub < 1 && cam_raw_pub < 1 )); then
        cam_ok="0"
      fi
    fi

    if [[ "$hb_ok" == "1" && "$cmd_ok" == "1" && "$cam_ok" == "1" ]]; then
      echo "[swarm_com_run_robot] [READY] robot=${ROBOT_NAME} heartbeat=ok cmd_vel_subscriber=ok camera=ok" >&2
      echo "[swarm_com_run_robot] [READY] You can now select '${ROBOT_NAME}' in the UI and drive immediately." >&2
      return 0
    fi

    now_s="$(date +%s)"
    elapsed_s=$(( now_s - start_s ))
    if (( elapsed_s >= timeout_s )) && [[ "$warned" == "0" ]]; then
      warned="1"
      echo "[swarm_com_run_robot] [WAIT] readiness timeout (${timeout_s}s)." >&2
      echo "[swarm_com_run_robot] [WAIT] heartbeat_pub=${hb_pub} cmd_vel_sub=${cmd_sub} camera_comp_pub=${cam_comp_pub} camera_raw_pub=${cam_raw_pub}" >&2
      echo "[swarm_com_run_robot] [WAIT] Robot may still come up; keeping launch running." >&2
    fi
    sleep 1
  done
  return 0
}

on_signal() {
  local sig="$1"
  if [[ "$_shutdown_in_progress" == "1" ]]; then
    echo "[swarm_com_run_robot] ${sig} received while shutdown is already in progress; please wait..." >&2
    return 0
  fi
  _shutdown_in_progress="1"
  if [[ -n "$ready_probe_pid" ]] && kill -0 "$ready_probe_pid" 2>/dev/null; then
    kill "$ready_probe_pid" 2>/dev/null || true
  fi
  if [[ -n "$launch_pid" ]] && kill -0 "$launch_pid" 2>/dev/null; then
    kill_launch_tree "$launch_pid"
  fi
  return 0
}

cleanup() {
  local ec=$?
  if [[ "$_cleanup_done" == "1" ]]; then
    return 0
  fi
  _cleanup_done="1"
  trap - EXIT INT TERM
  if [[ -n "$ready_probe_pid" ]] && kill -0 "$ready_probe_pid" 2>/dev/null; then
    kill "$ready_probe_pid" 2>/dev/null || true
    wait "$ready_probe_pid" 2>/dev/null || true
  fi
  if [[ -n "$launch_pid" ]] && kill -0 "$launch_pid" 2>/dev/null; then
    kill_launch_tree "$launch_pid"
    wait "$launch_pid" 2>/dev/null || true
  fi
  exit "$ec"
}

trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap cleanup EXIT

if command -v setsid >/dev/null 2>&1; then
  setsid ros2 launch swarm_control_core swarm_bringup.launch.py \
    robot_name:="$ROBOT_NAME" \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    use_camera:="$USE_CAMERA" \
    camera_pipeline:="$CAMERA_PIPELINE" &
else
  ros2 launch swarm_control_core swarm_bringup.launch.py \
    robot_name:="$ROBOT_NAME" \
    ros_domain_id:="$ROS_DOMAIN_ID" \
    use_camera:="$USE_CAMERA" \
    camera_pipeline:="$CAMERA_PIPELINE" &
fi
launch_pid="$!"
if [[ "${SWARM_COM_PRINT_READY_ON_START:-1}" == "1" ]]; then
  readiness_probe &
  ready_probe_pid="$!"
fi
wait "$launch_pid"
