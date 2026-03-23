#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${script_dir}/lib/swarm_core_workspace.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_install_robot_service.sh [options]

Options:
  --workspace <path>               Workspace root (default: auto-detect)
  --service-name <name>            Community service name (default: swarm-core-robot)
  --service-user <user>            Service user (default: current user)
  --env-file <path>                Environment file (default: /etc/swarm_control_core/robot.env)
  --existing-service-name <name>   Existing robot service name to conflict with
                                   (default: swarm-robot)
  --robot-name <name>              Robot identity (default: $SWARM_CORE_ROBOT_NAME or $USER)
  --domain-id <id>                 ROS domain ID (default: 17)
  --profiles-path <path>           profiles file path (optional)
  --camera-profiles-path <path>    camera profiles file path (optional)
  --use-camera <true|false>        Launch camera node (default: true)
  --camera-pipeline <name>         Camera pipeline (default: adapter)
  --enable-now                     Enable and start service now
  -h, --help                       Show this help
USAGE
}

log() {
  echo "[swarm_core_install_robot_service] $*" >&2
}

fail() {
  echo "[swarm_core_install_robot_service] ERROR: $*" >&2
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

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

workspace=""
service_name="swarm-core-robot"
service_user="${USER:-$(id -un)}"
env_file="/etc/swarm_control_core/robot.env"
existing_service_name="${SWARM_CORE_EXISTING_ROBOT_SERVICE:-swarm-robot}"
robot_name="${SWARM_CORE_ROBOT_NAME:-${USER:-$(id -un)}}"
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
profiles_path="${PROFILES_PATH:-}"
camera_profiles_path="${CAMERA_PROFILES_PATH:-}"
use_camera="true"
camera_pipeline="adapter"
enable_now="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace="${1:-}"
      ;;
    --service-name)
      shift
      service_name="${1:-}"
      ;;
    --service-user)
      shift
      service_user="${1:-}"
      ;;
    --env-file)
      shift
      env_file="${1:-}"
      ;;
    --existing-service-name)
      shift
      existing_service_name="${1:-}"
      ;;
    --robot-name)
      shift
      robot_name="${1:-}"
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
      ;;
    --profiles-path)
      shift
      profiles_path="${1:-}"
      ;;
    --camera-profiles-path)
      shift
      camera_profiles_path="${1:-}"
      ;;
    --use-camera)
      shift
      use_camera="${1:-}"
      ;;
    --camera-pipeline)
      shift
      camera_pipeline="${1:-}"
      ;;
    --enable-now)
      enable_now="1"
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

workspace="$(trim "$workspace")"
workspace="$(swarm_core_detect_workspace_root "$workspace" || true)"
[[ -n "$workspace" ]] || fail "Unable to detect workspace root. Pass --workspace or set SWARM_CORE_WORKSPACE_ROOT."
service_name="$(trim "$service_name")"
service_user="$(trim "$service_user")"
env_file="$(trim "$env_file")"
existing_service_name="$(trim "$existing_service_name")"
robot_name="$(trim "$robot_name")"
domain_id="$(trim "$domain_id")"
profiles_path="$(trim "$profiles_path")"
camera_profiles_path="$(trim "$camera_profiles_path")"
use_camera="$(printf '%s' "$use_camera" | tr '[:upper:]' '[:lower:]')"
camera_pipeline="$(trim "$camera_pipeline")"

[[ -n "$workspace" ]] || fail "--workspace cannot be empty."
[[ -d "$workspace" ]] || fail "Workspace not found: $workspace"
[[ -n "$service_name" ]] || fail "--service-name cannot be empty."
[[ -n "$service_user" ]] || fail "--service-user cannot be empty."
[[ -n "$robot_name" ]] || fail "--robot-name cannot be empty."
[[ -n "$domain_id" ]] || fail "--domain-id cannot be empty."
[[ "$use_camera" == "true" || "$use_camera" == "false" ]] || fail "--use-camera must be true or false."

id "$service_user" >/dev/null 2>&1 || fail "Service user does not exist: $service_user"

tmp_env="$(mktemp)"
tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_env" "$tmp_unit"' EXIT

cat > "$tmp_env" <<ENV
WORKSPACE=${workspace}
ROS_DOMAIN_ID=${domain_id}
SWARM_CORE_ROBOT_NAME=${robot_name}
SWARM_CORE_USE_CAMERA=${use_camera}
SWARM_CORE_CAMERA_PIPELINE=${camera_pipeline}
SWARM_CORE_PROFILES_PATH=${profiles_path}
SWARM_CORE_CAMERA_PROFILES_PATH=${camera_profiles_path}
ENV

conflicts_line=""
if [[ -n "$existing_service_name" ]]; then
  conflicts_line="Conflicts=${existing_service_name}.service"
fi

cat > "$tmp_unit" <<UNIT
[Unit]
Description=swarm_control_core robot bringup (${robot_name})
After=network-online.target
Wants=network-online.target
${conflicts_line}

[Service]
Type=simple
User=${service_user}
WorkingDirectory=${workspace}
EnvironmentFile=${env_file}
ExecStart=/usr/bin/env bash -lc 'set -euo pipefail; source /opt/ros/\${ROS_DISTRO:-jazzy}/setup.bash; source "\${WORKSPACE}/install/setup.bash"; export ROS_DOMAIN_ID="\${ROS_DOMAIN_ID:-17}"; exec ros2 launch swarm_control_core swarm_bringup.launch.py robot_name:="\${SWARM_CORE_ROBOT_NAME}" ros_domain_id:="\${ROS_DOMAIN_ID}" use_camera:="\${SWARM_CORE_USE_CAMERA}" camera_pipeline:="\${SWARM_CORE_CAMERA_PIPELINE}" profiles_path:="\${SWARM_CORE_PROFILES_PATH}" camera_profiles_path:="\${SWARM_CORE_CAMERA_PROFILES_PATH}"'
Restart=always
RestartSec=2
KillSignal=SIGINT
TimeoutStopSec=20
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

run_root mkdir -p "$(dirname "$env_file")"
run_root install -m 640 -o root -g root "$tmp_env" "$env_file"
run_root install -m 644 -o root -g root "$tmp_unit" "/etc/systemd/system/${service_name}.service"
run_root systemctl daemon-reload

if [[ "$enable_now" == "1" ]]; then
  run_root systemctl enable --now "${service_name}.service"
fi

log "Installed ${service_name}.service"
log "Env file: ${env_file}"
if [[ "$enable_now" == "1" ]]; then
  run_root systemctl --no-pager --full status "${service_name}.service" || true
else
  log "Run: sudo systemctl enable --now ${service_name}.service"
fi
