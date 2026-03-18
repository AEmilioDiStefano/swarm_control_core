#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_com_bootstrap_machine.sh [options]

Options:
  --machine-role <control|robot>  Target machine role (default: robot)
  --workspace <path>              Workspace root (default: ~/ros2_ws_dev)
  --repo-url <url>                Clone URL if package dir is missing and --clone-if-missing is set
  --clone-if-missing              Clone package into <workspace>/src/swarm_control_core if absent
  --skip-gpio                     Skip GPIO setup (robot role only)
  --skip-build                    Skip colcon build step
  --install-service               Install robot systemd service (robot role only)
  --enable-service-now            Enable/start robot systemd service now (implies --install-service)
  --domain-id <id>                ROS_DOMAIN_ID value for build/service (default: 17)
  --robot-name <name>             Robot name for service install (default: current Linux username)
  -h, --help                      Show this help

Behavior:
  - Runs dependency installer script for the selected role.
  - (Robot role) configures GPIO access unless --skip-gpio is used.
  - Builds swarm_control_core in the given workspace unless --skip-build is used.
  - Optionally installs/enables the robot service.
USAGE
}

log() {
  echo "[swarm_com_bootstrap_machine] $*" >&2
}

fail() {
  echo "[swarm_com_bootstrap_machine] ERROR: $*" >&2
  exit 1
}

current_step="initialization"

on_error() {
  local exit_code=$?
  echo "[swarm_com_bootstrap_machine] ERROR: bootstrap failed during step: ${current_step}" >&2
  exit "$exit_code"
}

service_installed() {
  local service_name="$1"
  if ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "${service_name}.service"
}

service_active_state() {
  local service_name="$1"
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl-unavailable"
    return 0
  fi
  systemctl is-active "${service_name}.service" 2>/dev/null || true
}

print_current_setup_summary() {
  local runtime_cfg_dir="$1"
  local build_status="$2"
  local gpio_status="$3"
  local service_status="$4"

  local robot_instances_file="${runtime_cfg_dir}/robot_instances.yaml"
  local camera_profiles_file="${runtime_cfg_dir}/camera_profiles.yaml"
  local control_types_file="${runtime_cfg_dir}/control_types.yaml"
  local control_interfaces_file="${runtime_cfg_dir}/control_interfaces.yaml"
  local capability_profiles_file="${runtime_cfg_dir}/capability_profiles.yaml"
  local adapter_profiles_file="${runtime_cfg_dir}/adapter_profiles.yaml"

  local git_head="unknown"
  if command -v git >/dev/null 2>&1; then
    git_head="$(git -C "$target_pkg_dir" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi

  local gpio_membership="unknown"
  if id -nG "${USER:-$(id -un)}" | tr ' ' '\n' | grep -qx gpio; then
    gpio_membership="yes"
  else
    gpio_membership="no"
  fi

  local gpiomem_state="missing"
  if [[ -e /dev/gpiomem ]]; then
    gpiomem_state="$(ls -l /dev/gpiomem 2>/dev/null || echo present_unreadable)"
  fi

  local swarm_service_installed="no"
  local swarm_service_active="n/a"
  if service_installed "swarm-robot"; then
    swarm_service_installed="yes"
    swarm_service_active="$(service_active_state "swarm-robot")"
  fi

  local com_service_installed="no"
  local com_service_active="n/a"
  if service_installed "com-swarm-robot"; then
    com_service_installed="yes"
    com_service_active="$(service_active_state "com-swarm-robot")"
  fi

  echo
  echo "CURRENT SETUP:"
  echo "MACHINE_ROLE = ${machine_role}"
  echo "WORKSPACE = ${workspace}"
  echo "PACKAGE_DIR = ${target_pkg_dir}"
  echo "PACKAGE_GIT_HEAD = ${git_head}"
  echo "USER = ${USER:-$(id -un)}"
  echo "ROBOT_NAME = ${robot_name}"
  echo "ROS_DISTRO = ${ROS_DISTRO:-jazzy}"
  echo "ROS_DOMAIN_ID_TARGET = ${domain_id}"
  echo "RUNTIME_CONFIG_DIR = ${runtime_cfg_dir}"
  echo "ROBOT_INSTANCES_FILE = ${robot_instances_file} (exists=$( [[ -f "$robot_instances_file" ]] && echo yes || echo no ))"
  echo "CAMERA_PROFILES_FILE = ${camera_profiles_file} (exists=$( [[ -f "$camera_profiles_file" ]] && echo yes || echo no ))"
  echo "CONTROL_TYPES_FILE = ${control_types_file} (exists=$( [[ -f "$control_types_file" ]] && echo yes || echo no ))"
  echo "CONTROL_INTERFACES_FILE = ${control_interfaces_file} (exists=$( [[ -f "$control_interfaces_file" ]] && echo yes || echo no ))"
  echo "CAPABILITY_PROFILES_FILE = ${capability_profiles_file} (exists=$( [[ -f "$capability_profiles_file" ]] && echo yes || echo no ))"
  echo "ADAPTER_PROFILES_FILE = ${adapter_profiles_file} (exists=$( [[ -f "$adapter_profiles_file" ]] && echo yes || echo no ))"
  echo "BUILD_STATUS = ${build_status}"
  echo "GPIO_STATUS = ${gpio_status}"
  echo "GPIO_GROUP_MEMBER = ${gpio_membership}"
  echo "GPIOMEM = ${gpiomem_state}"
  echo "SERVICE_INSTALL_STATUS = ${service_status}"
  echo "SWARM_SERVICE_INSTALLED = ${swarm_service_installed}"
  echo "SWARM_SERVICE_ACTIVE = ${swarm_service_active:-unknown}"
  echo "COMMUNITY_SERVICE_INSTALLED = ${com_service_installed}"
  echo "COMMUNITY_SERVICE_ACTIVE = ${com_service_active:-unknown}"
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

machine_role="robot"
workspace="${HOME}/ros2_ws_dev"
repo_url=""
clone_if_missing="0"
skip_gpio="0"
skip_build="0"
install_service="0"
enable_service_now="0"
domain_id="${SWARM_COM_ROS_DOMAIN_ID:-17}"
robot_name="${SWARM_COM_ROBOT_NAME:-$(id -un)}"
build_status="skipped"
gpio_status="skipped"
service_status="not-requested"
dep_summary_file="$(mktemp)"

trap on_error ERR
trap 'rm -f "$dep_summary_file"' EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --machine-role)
      shift
      machine_role="${1:-}"
      ;;
    --workspace)
      shift
      workspace="${1:-}"
      ;;
    --repo-url)
      shift
      repo_url="${1:-}"
      ;;
    --clone-if-missing)
      clone_if_missing="1"
      ;;
    --skip-gpio)
      skip_gpio="1"
      ;;
    --skip-build)
      skip_build="1"
      ;;
    --install-service)
      install_service="1"
      ;;
    --enable-service-now)
      install_service="1"
      enable_service_now="1"
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
      fail "Unknown argument: $1"
      ;;
  esac
  shift
done

case "$machine_role" in
  control|robot) ;;
  *)
    fail "--machine-role must be control or robot"
    ;;
esac

[[ -n "$workspace" ]] || fail "--workspace cannot be empty"
[[ -n "$domain_id" ]] || fail "--domain-id cannot be empty"
[[ -n "$robot_name" ]] || fail "--robot-name cannot be empty"

if [[ "${workspace}" == "~/"* ]]; then
  workspace="${HOME}/${workspace#~/}"
fi
if [[ "${workspace}" == '$HOME/'* ]]; then
  workspace="${HOME}/${workspace#\$HOME/}"
fi

target_pkg_dir="${workspace}/src/swarm_control_core"
if [[ ! -d "$target_pkg_dir" ]]; then
  if [[ "$clone_if_missing" != "1" ]]; then
    fail "Package directory not found: ${target_pkg_dir}. Use --clone-if-missing with --repo-url."
  fi
  [[ -n "$repo_url" ]] || fail "--repo-url is required when using --clone-if-missing."
  if ! command -v git >/dev/null 2>&1; then
    if command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y git
    else
      fail "git is required for --clone-if-missing and could not be auto-installed (missing sudo)."
    fi
  fi
  mkdir -p "${workspace}/src"
  log "Cloning ${repo_url} into ${target_pkg_dir}"
  git clone "$repo_url" "$target_pkg_dir"
fi

if [[ ! -x "${target_pkg_dir}/scripts/swarm_com_check_install_dependencies.sh" ]]; then
  fail "Expected dependency script at ${target_pkg_dir}/scripts/swarm_com_check_install_dependencies.sh"
fi

if [[ ! -x "${target_pkg_dir}/scripts/swarm_com_seed_runtime_config.sh" ]]; then
  fail "Expected runtime config seed script at ${target_pkg_dir}/scripts/swarm_com_seed_runtime_config.sh"
fi

log "Workspace=${workspace}"
log "Role=${machine_role}"
log "Domain ID=${domain_id}"

current_step="dependency-check"
"${target_pkg_dir}/scripts/swarm_com_check_install_dependencies.sh" \
  --machine-role "$machine_role" \
  --summary-file "$dep_summary_file"

current_step="seed-runtime-config"
"${target_pkg_dir}/scripts/swarm_com_seed_runtime_config.sh" \
  --workspace "$workspace"

if [[ "$machine_role" == "robot" && "$skip_gpio" != "1" ]]; then
  current_step="gpio-setup"
  "${target_pkg_dir}/scripts/swarm_com_enable_gpio_access.sh" --user "${USER:-$(id -un)}"
  gpio_status="configured"
fi

if [[ "$skip_build" != "1" ]]; then
  current_step="build-swarm_control_core"
  log "Building package swarm_control_core"
  (
    cd "$workspace"
    set +u
    source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
    colcon build --packages-select swarm_control_core
    set -u || true
  )
  build_status="completed"
fi

if [[ "$machine_role" == "robot" && "$install_service" == "1" ]]; then
  current_step="install-service"
  install_cmd=(
    "${target_pkg_dir}/scripts/swarm_com_install_robot_service.sh"
    --workspace "$workspace"
    --domain-id "$domain_id"
    --robot-name "$robot_name"
  )
  if [[ "$enable_service_now" == "1" ]]; then
    install_cmd+=(--enable-now)
    service_status="installed+enabled"
  else
    service_status="installed"
  fi
  "${install_cmd[@]}"
fi

echo
echo "BOOTSTRAP DEPENDENCY SUMMARY:"
if [[ -s "$dep_summary_file" ]]; then
  cat "$dep_summary_file"
else
  echo "(dependency summary unavailable)"
fi

runtime_cfg_dir="${SWARM_COM_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
print_current_setup_summary "$runtime_cfg_dir" "$build_status" "$gpio_status" "$service_status"

current_step="complete"
log "Bootstrap complete."
