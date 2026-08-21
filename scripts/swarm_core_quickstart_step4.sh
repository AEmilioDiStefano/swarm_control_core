#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_quickstart_common.sh
source "${SCRIPT_DIR}/lib/swarm_core_quickstart_common.sh"
# shellcheck source=./lib/swarm_core_discovery.sh
source "${SCRIPT_DIR}/lib/swarm_core_discovery.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_quickstart_step4.sh [--domain-id <id>] [--robot-name <name>]
                                 [--ui-url <url>]

Behavior:
  - Sources the current ROS/workspace overlay.
  - Prints the control-side discovery environment.
  - Prints the currently visible heartbeat/camera/cmd_vel topics and relevant nodes.
  - Polls the local FPV UI until a graph-live robot returns a fresh JPEG frame.
  - Requires a successful browser WebRTC offer for that robot and connected
    browser telemetry; server-side WebRTC availability alone does not pass.

Options:
  --robot-name <name>  Check only this approved robot. Other fleet members may be offline.
  --ui-url <url>       FPV UI base URL (default: http://127.0.0.1:8080).
USAGE
}

domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
robot_name=""
ui_url="http://127.0.0.1:8080"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain-id)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || swarm_core_qs_fail "--domain-id requires a value."
      shift
      domain_id="${1:-}"
      ;;
    --robot-name)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || swarm_core_qs_fail "--robot-name requires a value."
      shift
      robot_name="${1:-}"
      ;;
    --ui-url)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || swarm_core_qs_fail "--ui-url requires a value."
      shift
      ui_url="${1:-}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      swarm_core_qs_fail "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$ui_url" ]] || swarm_core_qs_fail "--ui-url requires a non-empty URL."
case "$ui_url" in
  http://*|https://*) ;;
  *) swarm_core_qs_fail "--ui-url must begin with http:// or https:// (got '${ui_url}')." ;;
esac
ui_url="${ui_url%/}"

fpv_timeout_s="${SWARM_CORE_FPV_ACCEPTANCE_TIMEOUT_S:-30}"
fpv_poll_interval_s="${SWARM_CORE_FPV_ACCEPTANCE_POLL_INTERVAL_S:-1}"
fpv_max_frame_age_s="${SWARM_CORE_FPV_MAX_FRAME_AGE_S:-2.0}"
[[ "$fpv_timeout_s" =~ ^[0-9]+$ ]] || swarm_core_qs_fail \
  "SWARM_CORE_FPV_ACCEPTANCE_TIMEOUT_S must be a non-negative integer."
[[ "$fpv_poll_interval_s" =~ ^[0-9]+([.][0-9]+)?$ ]] || swarm_core_qs_fail \
  "SWARM_CORE_FPV_ACCEPTANCE_POLL_INTERVAL_S must be a non-negative number."
[[ "$fpv_max_frame_age_s" =~ ^[0-9]+([.][0-9]+)?$ ]] || swarm_core_qs_fail \
  "SWARM_CORE_FPV_MAX_FRAME_AGE_S must be a non-negative number."

WS="$(swarm_core_qs_detect_workspace "${SWARM_CORE_WORKSPACE_ROOT:-}")"
swarm_core_qs_prepare_workspace_env "$WS"

export ROS_DOMAIN_ID="$domain_id"
swarm_core_qs_source_ros_overlay "$WS"
swarm_core_apply_discovery_env
swarm_core_stop_ros_daemon

echo "DISCOVERY ENVIRONMENT:"
env | rg -e '^(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|ROS_DISCOVERY_SERVER|RMW_IMPLEMENTATION|SWARM_DISCOVERY_MODE)=' || true

topics="$(ros2 topic list)" || swarm_core_qs_fail "ros2 topic list failed. Check the ROS overlay and RMW installation."
nodes="$(ros2 node list)" || swarm_core_qs_fail "ros2 node list failed. Check the ROS overlay and RMW installation."
topic_matches="$(printf '%s\n' "$topics" | rg -e '/.*/(heartbeat|camera/image_raw|cmd_vel)' || true)"
node_matches="$(printf '%s\n' "$nodes" | rg -e '(swarm_fpv_ui|motor_driver_node|heartbeat_node|unit_executor_action_server|camera)' || true)"
runtime_cfg_dir="${SWARM_CORE_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
registered_robots="$(python3 - "${runtime_cfg_dir}/robot_instances.yaml" <<'PY_ROBOTS'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
robots = data.get("robots", {}) if isinstance(data, dict) else {}
if isinstance(robots, dict):
    for name in sorted(str(name).strip() for name in robots if str(name).strip()):
        print(name)
PY_ROBOTS
)"

echo
echo "RELEVANT TOPICS:"
printf '%s\n' "${topic_matches:-(none)}"
echo
echo "RELEVANT NODES:"
printf '%s\n' "${node_matches:-(none)}"

missing_robot_graph="0"
declare -a live_graph_robots=()
if [[ -z "$registered_robots" ]]; then
  swarm_core_qs_warn "No approved robots exist in ${runtime_cfg_dir}/robot_instances.yaml. Complete onboarding first."
  missing_robot_graph="1"
else
  if [[ -n "$robot_name" ]] && ! printf '%s\n' "$registered_robots" | rg -Fxq "$robot_name"; then
    swarm_core_qs_fail "Robot '${robot_name}' is not approved in ${runtime_cfg_dir}/robot_instances.yaml."
  fi

  live_robot_count=0
  while IFS= read -r robot; do
    [[ -n "$robot" ]] || continue
    if [[ -n "$robot_name" && "$robot" != "$robot_name" ]]; then
      continue
    fi
    robot_ready="1"
    for expected in "/${robot}/heartbeat_node" "/${robot}/motor_driver_node"; do
      if ! printf '%s\n' "$nodes" | rg -Fxq "$expected"; then
        swarm_core_qs_warn "Approved robot '${robot}' is missing required node ${expected}."
        robot_ready="0"
      fi
    done
    if [[ "$robot_ready" == "1" ]]; then
      live_robot_count=$((live_robot_count + 1))
      live_graph_robots+=("$robot")
    fi
  done <<< "$registered_robots"
  if (( live_robot_count == 0 )); then
    if [[ -n "$robot_name" ]]; then
      swarm_core_qs_warn "Approved robot '${robot_name}' does not have both a heartbeat and motor-driver node in the graph."
    else
      swarm_core_qs_warn "No approved robot has both a heartbeat and motor-driver node in the graph."
    fi
    missing_robot_graph="1"
  else
    echo "LIVE ROBOTS: ${live_robot_count}"
  fi
fi

if [[ -z "$topic_matches" || -z "$node_matches" || "$missing_robot_graph" == "1" ]]; then
  swarm_core_qs_warn "Fleet graph is incomplete. This indicates a node-startup or DDS/runtime failure, not proof that .local/mDNS is broken."
  swarm_core_qs_warn "Confirm robot and control use domain ${ROS_DOMAIN_ID}, RMW ${RMW_IMPLEMENTATION}, and the peer list shown above."
  swarm_core_qs_warn "If IP ping works but multicast does not, rerun every host with SWARM_CORE_DISCOVERY_MODE=static; static mode requires configured peers."
  exit 1
fi

command -v curl >/dev/null 2>&1 || swarm_core_qs_fail "curl is required for the FPV acceptance check."
command -v python3 >/dev/null 2>&1 || swarm_core_qs_fail "python3 is required for the FPV acceptance check."
python3 -c 'from PIL import Image' >/dev/null 2>&1 || swarm_core_qs_fail \
  "python3-pil is required to validate the returned FPV JPEG."

fpv_tmp_dir="$(mktemp -d)"
cleanup_fpv_tmp() {
  rm -rf -- "$fpv_tmp_dir"
}
trap cleanup_fpv_tmp EXIT

fpv_jpeg_is_valid() {
  local path="${1:-}"
  python3 - "$path" <<'PY_JPEG'
from PIL import Image
import sys

try:
    with Image.open(sys.argv[1]) as image:
        if image.format != "JPEG" or image.width < 1 or image.height < 1:
            raise ValueError("not a non-empty JPEG")
        image.verify()
except Exception:
    raise SystemExit(1)
PY_JPEG
}

fpv_state_is_ready() {
  local state_path="${1:-}"
  local candidate="${2:-}"
  python3 - "$state_path" "$candidate" "$fpv_max_frame_age_s" <<'PY_STATE'
import json
import math
from pathlib import Path
import sys

path = Path(sys.argv[1])
robot = sys.argv[2]
max_age = float(sys.argv[3])
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"UI returned invalid /api/state JSON: {exc}")
    raise SystemExit(1)

if not isinstance(state, dict):
    print("UI returned a non-object /api/state response.")
    raise SystemExit(1)
features = state.get("features")
if not isinstance(features, dict) or features.get("webrtc") is not True:
    print("UI reports WebRTC disabled; install python3-aiortc and python3-av, rebuild, and restart Step 3.")
    raise SystemExit(1)
health_by_robot = state.get("robot_health")
health = health_by_robot.get(robot) if isinstance(health_by_robot, dict) else None
if not isinstance(health, dict):
    print(f"UI state has no camera health entry for {robot!r}.")
    raise SystemExit(1)
if health.get("has_frame") is not True:
    cause = str(health.get("probable_cause") or "no frame received yet")
    print(f"{robot}: UI has no decoded frame ({cause}).")
    raise SystemExit(1)
age_raw = health.get("frame_age_s")
try:
    age = float(age_raw)
except (TypeError, ValueError):
    print(f"{robot}: UI did not report a numeric frame age.")
    raise SystemExit(1)
if not math.isfinite(age) or age < 0.0 or age > max_age:
    print(f"{robot}: newest UI frame is stale ({age_raw!r}s; maximum {max_age:g}s).")
    raise SystemExit(1)

webrtc = state.get("webrtc")
telemetry = webrtc.get("telemetry") if isinstance(webrtc, dict) else None
if not isinstance(telemetry, dict):
    print(f"{robot}: UI state has no browser WebRTC telemetry. Open the browser, select this robot, and retry.")
    raise SystemExit(1)

def nonnegative_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)

offers_success = nonnegative_int(telemetry.get("offers_success"))
last_offer_robot = str(telemetry.get("last_offer_robot") or "").strip()
active_connections = nonnegative_int(telemetry.get("active_peer_connections"))
last_event = telemetry.get("last_client_event")
last_event = last_event if isinstance(last_event, dict) else {}
event_robot = str(last_event.get("robot") or "").strip()
connection_state = str(last_event.get("connection_state") or "").strip().lower()
ice_state = str(last_event.get("ice_connection_state") or "").strip().lower()

if offers_success < 1 or last_offer_robot != robot:
    print(
        f"{robot}: no successful browser WebRTC offer is recorded for this robot "
        f"(offers_success={offers_success}, last_offer_robot={last_offer_robot or '<none>'}). "
        "Open the browser, select this robot, and retry."
    )
    raise SystemExit(1)
if active_connections < 1:
    print(f"{robot}: the successful WebRTC offer has no active peer connection.")
    raise SystemExit(1)
if event_robot != robot:
    print(
        f"{robot}: the latest browser WebRTC telemetry belongs to "
        f"{event_robot or '<none>'}; select this robot and retry."
    )
    raise SystemExit(1)
if connection_state != "connected" and ice_state not in ("connected", "completed"):
    print(
        f"{robot}: browser WebRTC is not connected "
        f"(connection_state={connection_state or '<none>'}, "
        f"ice_connection_state={ice_state or '<none>'})."
    )
    raise SystemExit(1)

print(
    f"robot={robot} frame_age_s={age:.3f} webrtc_offer=ok "
    f"browser_connection={connection_state or ice_state}"
)
PY_STATE
}

echo
echo "FPV ACCEPTANCE: polling ${ui_url} for up to ${fpv_timeout_s}s"
fpv_deadline=$((SECONDS + fpv_timeout_s))
last_fpv_problem="The UI API has not responded yet."
while :; do
  for candidate in "${live_graph_robots[@]}"; do
    jpeg_path="${fpv_tmp_dir}/frame.jpg"
    state_path="${fpv_tmp_dir}/state.json"
    curl_error_path="${fpv_tmp_dir}/curl.err"

    jpeg_meta=""
    if jpeg_meta="$(curl --silent --show-error --connect-timeout 2 --max-time 4 \
      --output "$jpeg_path" --write-out '%{http_code}\t%{content_type}' \
      --get --data-urlencode "robot=${candidate}" "${ui_url}/api/jpeg" \
      2>"$curl_error_path")"; then
      jpeg_code="${jpeg_meta%%$'\t'*}"
      jpeg_type="${jpeg_meta#*$'\t'}"
      if [[ "$jpeg_code" != "200" ]]; then
        last_fpv_problem="${candidate}: /api/jpeg returned HTTP ${jpeg_code}."
        continue
      fi
      if [[ "$jpeg_type" != image/jpeg* ]]; then
        last_fpv_problem="${candidate}: /api/jpeg returned '${jpeg_type:-no content type}', not image/jpeg."
        continue
      fi
      if ! fpv_jpeg_is_valid "$jpeg_path"; then
        last_fpv_problem="${candidate}: /api/jpeg did not return a complete JPEG image."
        continue
      fi
    else
      last_fpv_problem="${candidate}: $(<"$curl_error_path")"
      continue
    fi

    state_code=""
    if ! state_code="$(curl --silent --show-error --connect-timeout 2 --max-time 4 \
      --output "$state_path" --write-out '%{http_code}' "${ui_url}/api/state" \
      2>"$curl_error_path")"; then
      last_fpv_problem="${candidate}: $(<"$curl_error_path")"
      continue
    fi
    if [[ "$state_code" != "200" ]]; then
      last_fpv_problem="${candidate}: /api/state returned HTTP ${state_code}."
      continue
    fi

    if fpv_summary="$(fpv_state_is_ready "$state_path" "$candidate")"; then
      echo "FPV ACCEPTANCE PASSED: ${fpv_summary}; jpeg=valid"
      echo "Open ${ui_url} in a browser, select '${candidate}', and verify motion is visibly live."
      exit 0
    else
      last_fpv_problem="$fpv_summary"
    fi
  done

  if (( SECONDS >= fpv_deadline )); then
    break
  fi
  sleep "$fpv_poll_interval_s"
done

swarm_core_qs_warn "FPV acceptance failed: ${last_fpv_problem}"
swarm_core_qs_warn "Keep Step 3 running, open ${ui_url}, select the intended robot, and distinguish camera/JPEG failures from browser WebRTC failures before retrying."
swarm_core_qs_fail "No approved graph-live robot produced both a fresh JPEG and a connected browser WebRTC session."
