#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${script_dir}/lib/swarm_core_workspace.sh"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_bootstrap_machine.sh [options]

Options:
  --machine-role <control|robot>  Target machine role (default: robot)
  --workspace <path>              Workspace root (default: auto-detect)
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
  echo "[swarm_core_bootstrap_machine] $*" >&2
}

fail() {
  echo "[swarm_core_bootstrap_machine] ERROR: $*" >&2
  exit 1
}

bootstrap_progress_enabled="0"
bootstrap_progress_fd=""
bootstrap_progress_lines="0"
bootstrap_progress_cols="0"
bootstrap_progress_total_weight="0"
bootstrap_progress_completed_weight="0"
bootstrap_progress_current_label="Preparing bootstrap"

bootstrap_progress_percent() {
  local total=$((bootstrap_progress_total_weight))
  local done=$((bootstrap_progress_completed_weight))
  local percent=0
  if (( total > 0 )); then
    percent=$(( done * 100 / total ))
  fi
  if (( percent > 100 )); then
    percent=100
  fi
  printf '%d%%' "$percent"
}

bootstrap_progress_render() {
  return 0
}

bootstrap_progress_cleanup() {
  bootstrap_progress_enabled="0"
}

bootstrap_progress_init() {
  bootstrap_progress_enabled="1"
}

run_bootstrap_step() {
  local weight="$1"
  local label="$2"
  shift 2
  local step_status=0

  bootstrap_progress_current_label="$label"
  bootstrap_progress_render
  log "START ($(bootstrap_progress_percent)): ${label}"

  if "$@"; then
    step_status=0
  else
    step_status=$?
  fi

  if (( step_status == 0 )); then
    bootstrap_progress_completed_weight=$(( bootstrap_progress_completed_weight + weight ))
    bootstrap_progress_render
    log "OK ($(bootstrap_progress_percent)): ${label}"
  else
    log "FAILED ($(bootstrap_progress_percent), exit=${step_status}): ${label}"
  fi
  return "$step_status"
}

# Keep this wrapper name for the dependency step, but use the same append-only
# progress as every other bootstrap step.
run_bootstrap_step_with_subprogress() {
  run_bootstrap_step "$@"
}

current_step="initialization"

on_error() {
  local exit_code=$?
  bootstrap_progress_cleanup
  echo "[swarm_core_bootstrap_machine] ERROR: bootstrap failed during step: ${current_step}" >&2
  exit "$exit_code"
}

on_exit() {
  bootstrap_progress_cleanup
  rm -f "$dep_summary_file"
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
  if service_installed "swarm-core-robot"; then
    com_service_installed="yes"
    com_service_active="$(service_active_state "swarm-core-robot")"
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

machine_role="robot"
workspace=""
repo_url=""
clone_if_missing="0"
skip_gpio="0"
skip_build="0"
install_service="0"
enable_service_now="0"
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
robot_name="${SWARM_CORE_ROBOT_NAME:-$(id -un)}"
build_status="skipped"
gpio_status="skipped"
service_status="not-requested"
dep_summary_file="$(mktemp)"

trap on_error ERR
trap on_exit EXIT

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

[[ -n "$domain_id" ]] || fail "--domain-id cannot be empty"
[[ -n "$robot_name" ]] || fail "--robot-name cannot be empty"

workspace="$(swarm_core_detect_workspace_root "$workspace" || true)"
[[ -n "$workspace" ]] || fail "Unable to detect workspace root. Pass --workspace or set SWARM_CORE_WORKSPACE_ROOT."

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

if [[ ! -x "${target_pkg_dir}/scripts/swarm_core_check_install_dependencies.sh" ]]; then
  fail "Expected dependency script at ${target_pkg_dir}/scripts/swarm_core_check_install_dependencies.sh"
fi

if [[ ! -x "${target_pkg_dir}/scripts/swarm_core_seed_runtime_config.sh" ]]; then
  fail "Expected runtime config seed script at ${target_pkg_dir}/scripts/swarm_core_seed_runtime_config.sh"
fi

log "Workspace=${workspace}"
log "Role=${machine_role}"
log "Domain ID=${domain_id}"

bootstrap_progress_total_weight=68
if [[ "$machine_role" == "robot" && "$skip_gpio" != "1" ]]; then
  bootstrap_progress_total_weight=$(( bootstrap_progress_total_weight + 7 ))
fi
if [[ "$skip_build" != "1" ]]; then
  bootstrap_progress_total_weight=$(( bootstrap_progress_total_weight + 20 ))
fi
if [[ "$machine_role" == "robot" && "$install_service" == "1" ]]; then
  bootstrap_progress_total_weight=$(( bootstrap_progress_total_weight + 5 ))
fi
bootstrap_progress_init

current_step="dependency-check"
run_bootstrap_step_with_subprogress 55 "Installing dependencies" \
  "${target_pkg_dir}/scripts/swarm_core_check_install_dependencies.sh" \
  --machine-role "$machine_role" \
  --summary-file "$dep_summary_file"

current_step="seed-runtime-config"
run_bootstrap_step 8 "Seeding runtime configuration" \
  "${target_pkg_dir}/scripts/swarm_core_seed_runtime_config.sh" \
  --workspace "$workspace"

if [[ "$machine_role" == "robot" && "$skip_gpio" != "1" ]]; then
  current_step="gpio-setup"
  run_bootstrap_step 7 "Configuring GPIO access" \
    "${target_pkg_dir}/scripts/swarm_core_enable_gpio_access.sh" --user "${USER:-$(id -un)}"
  gpio_status="configured"
fi

if [[ "$skip_build" != "1" ]]; then
  current_step="build-swarm_control_core"
  log "Building package swarm_control_core"
  run_bootstrap_step 20 "Building swarm_control_core" bash -lc '
    set -euo pipefail
    cd "$1"
    set +u
    source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
    colcon build --base-paths "$2" --packages-select swarm_control_core
    set -u || true
  ' _ "$workspace" "$target_pkg_dir"
  build_status="completed"
fi

if [[ "$machine_role" == "robot" && "$install_service" == "1" ]]; then
  current_step="install-service"
  install_cmd=(
    "${target_pkg_dir}/scripts/swarm_core_install_robot_service.sh"
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
  run_bootstrap_step 5 "Installing robot service" "${install_cmd[@]}"
fi

bootstrap_progress_current_label="Finalizing bootstrap summary"
bootstrap_progress_completed_weight="$bootstrap_progress_total_weight"
bootstrap_progress_render

echo
echo "BOOTSTRAP DEPENDENCY SUMMARY:"
if [[ -s "$dep_summary_file" ]]; then
  cat "$dep_summary_file"
else
  echo "(dependency summary unavailable)"
fi

runtime_cfg_dir="${SWARM_CORE_CONFIG_DIR:-$HOME/.config/swarm_control_core}"
print_current_setup_summary "$runtime_cfg_dir" "$build_status" "$gpio_status" "$service_status"

current_step="complete"
log "Bootstrap complete."
