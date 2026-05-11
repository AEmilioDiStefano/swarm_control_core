#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_check_install_dependencies.sh [options]

Options:
  --machine-role <control|robot>  Dependency profile (default: control)
  --summary-file <path>           Write dependency summary text to file
  --help                          Show this help

Notes:
  - Community edition is local-only.
  - This script intentionally does not install internet-ingress components
    (for example reverse-proxy, tunnel, or TURN services).
USAGE
}

machine_role="control"
ros_distro="${ROS_DISTRO:-jazzy}"
apt_updated="0"
apt_http_timeout="${SWARM_APT_HTTP_TIMEOUT:-30}"
apt_retries="${SWARM_APT_RETRIES:-2}"
apt_force_ipv4="${SWARM_APT_FORCE_IPV4:-0}"
apt_lock_max_wait="${SWARM_APT_LOCK_MAX_WAIT:-1800}"
apt_lock_poll_s="${SWARM_APT_LOCK_POLL_S:-10}"
ubuntu_mirror_normalized="0"
failures=()
already_installed=()
just_installed=()
summary_file=""
progress_enabled="0"
progress_fd=""
progress_lines="0"
progress_cols="0"
progress_total_weight="0"
progress_completed_weight="0"
progress_current_label="Preparing dependency checks"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --machine-role)
      shift
      machine_role="${1:-}"
      ;;
    --summary-file)
      shift
      summary_file="${1:-}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[swarm_core_check_install_dependencies] ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

case "$machine_role" in
  control|robot) ;;
  *)
    echo "[swarm_core_check_install_dependencies] ERROR: --machine-role must be control or robot." >&2
    exit 2
    ;;
esac

record_failure() {
  failures+=("$1")
}

record_already_installed() {
  already_installed+=("$1")
}

record_just_installed() {
  just_installed+=("$1")
}

dependency_log() {
  echo "[swarm_core_check_install_dependencies] $*" >&2
}

dependency_status() {
  progress_current_label="$*"
  progress_render
  dependency_log "$*"
}

handle_interrupt() {
  dependency_log "Interrupted; stopping dependency checks now."
  exit 130
}

trap handle_interrupt INT TERM

print_dependency_summary() {
  local title="$1"
  shift
  local -a entries=("$@")
  local idx=1

  echo "$title"
  if [[ ${#entries[@]} -eq 0 ]]; then
    echo "(none)"
    echo
    return 0
  fi

  for dep in "${entries[@]}"; do
    echo "${idx}. ${dep}"
    idx=$((idx + 1))
  done
  echo
}

write_summary_file() {
  local out_file="$1"
  mkdir -p "$(dirname "$out_file")"
  {
    print_dependency_summary "DEPENDENCIES ALREADY INSTALLED AND UP TO DATE:" "${already_installed[@]}"
    print_dependency_summary "DEPENDENCIES INSTALLED OR UPDATED:" "${just_installed[@]}"
    if [[ ${#failures[@]} -gt 0 ]]; then
      print_dependency_summary "DEPENDENCIES FAILED TO INSTALL:" "${failures[@]}"
    fi
  } > "$out_file"
}

progress_percent() {
  local total=$((progress_total_weight))
  local done=$((progress_completed_weight))
  local percent=0
  if (( total > 0 )); then
    percent=$(( done * 100 / total ))
  fi
  if (( percent > 100 )); then
    percent=100
  fi
  printf '%d%%' "$percent"
}

progress_render() {
  return 0
}

progress_cleanup() {
  progress_enabled="0"
}

progress_init() {
  progress_enabled="1"
}

run_progress_step() {
  local weight="$1"
  local label="$2"
  shift 2
  local step_status=0

  progress_current_label="$label"
  progress_render
  dependency_log "START ($(progress_percent)): ${label}"

  if "$@"; then
    step_status=0
  else
    step_status=$?
  fi

  progress_completed_weight=$(( progress_completed_weight + weight ))
  progress_render
  if (( step_status == 0 )); then
    dependency_log "OK ($(progress_percent)): ${label}"
  else
    dependency_log "FAILED ($(progress_percent), exit=${step_status}): ${label}"
  fi
  if (( step_status == 130 || step_status == 131 || step_status == 143 )); then
    exit "$step_status"
  fi
  return "$step_status"
}

apt_network_options() {
  printf '%s\n' \
    -o DPkg::Lock::Timeout=120 \
    -o "Acquire::Retries=${apt_retries}" \
    -o "Acquire::http::Timeout=${apt_http_timeout}" \
    -o "Acquire::https::Timeout=${apt_http_timeout}"
  if [[ "$apt_force_ipv4" == "1" ]]; then
    printf '%s\n' -o Acquire::ForceIPv4=true
  fi
}

apt_lock_holders() {
  command -v fuser >/dev/null 2>&1 || return 0
  if [[ "$(id -u)" == "0" ]]; then
    fuser \
      /var/lib/dpkg/lock-frontend \
      /var/lib/dpkg/lock \
      /var/cache/apt/archives/lock \
      /var/lib/apt/lists/lock \
      2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -nu
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo fuser \
      /var/lib/dpkg/lock-frontend \
      /var/lib/dpkg/lock \
      /var/cache/apt/archives/lock \
      /var/lib/apt/lists/lock \
      2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -nu
    return 0
  fi
  fuser \
    /var/lib/dpkg/lock-frontend \
    /var/lib/dpkg/lock \
    /var/cache/apt/archives/lock \
    /var/lib/apt/lists/lock \
    2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -nu
}

wait_for_apt_locks() {
  local holders=""
  local deadline=$((SECONDS + apt_lock_max_wait))
  while holders="$(apt_lock_holders)" && [[ -n "${holders//[[:space:]]/}" ]]; do
    dependency_status "apt/dpkg is busy; waiting for lock holder(s): ${holders//$'\n'/, }"
    ps -o pid,ppid,etime,stat,comm,args -p "$(printf '%s' "$holders" | paste -sd, -)" >&2 || true
    if (( SECONDS >= deadline )); then
      dependency_status "ERROR: timed out waiting for apt/dpkg locks."
      dependency_log "Inspect the lock holder(s), then run the recovery commands only if they are stuck:"
      dependency_log "  sudo ps -fp $(printf '%s' "$holders" | paste -sd, -)"
      dependency_log "  sudo systemctl status unattended-upgrades apt-daily.service apt-daily-upgrade.service --no-pager"
      dependency_log "  sudo journalctl -u unattended-upgrades -n 80 --no-pager"
      dependency_log "  sudo systemctl stop unattended-upgrades apt-daily.service apt-daily-upgrade.service"
      dependency_log "  sudo dpkg --configure -a"
      dependency_log "  sudo apt-get --fix-broken install -y"
      dependency_log "After recovery, rerun this quickstart step."
      return 1
    fi
    sleep "$apt_lock_poll_s"
  done
  return 0
}

ensure_apt_update() {
  local apt_status=0
  local -a apt_opts=()

  if [[ "$apt_updated" == "1" ]]; then
    return 0
  fi
  if [[ "$ubuntu_mirror_normalized" != "1" && "${SWARM_CORE_SKIP_UBUNTU_MIRROR_NORMALIZE:-0}" != "1" ]]; then
    local mirror_helper=""
    mirror_helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/swarm_core_set_ubuntu_apt_mirror.sh"
    if [[ -x "$mirror_helper" ]]; then
      dependency_status "Normalizing Ubuntu apt mirror before apt-get update"
      "$mirror_helper" --no-update || return 1
    fi
    ubuntu_mirror_normalized="1"
  fi
  dependency_status "Running apt-get update"
  mapfile -t apt_opts < <(apt_network_options)
  wait_for_apt_locks || return 1
  sudo env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" update
  apt_status=$?
  if (( apt_status == 0 )); then
    apt_updated="1"
    return 0
  fi
  return "$apt_status"
}

install_apt_packages() {
  local -a apt_opts=()
  local update_status=0

  dependency_status "Installing apt packages: $*"
  ensure_apt_update
  update_status=$?
  if (( update_status != 0 )); then
    return "$update_status"
  fi
  mapfile -t apt_opts < <(apt_network_options)
  wait_for_apt_locks || return 1
  sudo env DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" install -y "$@"
}

apt_installed_version() {
  dpkg-query -W -f='${Version}' "$1" 2>/dev/null || true
}

apt_candidate_version() {
  apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ {print $2; exit}'
}

apt_package_is_current() {
  local pkg="$1"
  local installed_version=""
  local candidate_version=""

  installed_version="$(apt_installed_version "$pkg")"
  [[ -n "$installed_version" ]] || return 1

  ensure_apt_update
  local update_status=$?
  if (( update_status != 0 )); then
    return "$update_status"
  fi

  candidate_version="$(apt_candidate_version "$pkg")"
  if [[ -z "$candidate_version" || "$candidate_version" == "(none)" ]]; then
    dependency_status "${pkg} is installed at ${installed_version}; no apt candidate is available to compare"
    return 0
  fi

  dpkg --compare-versions "$installed_version" ge "$candidate_version"
}

apt_packages_are_current() {
  local pkg=""
  for pkg in "$@"; do
    apt_package_is_current "$pkg" || return 1
  done
  return 0
}

ubuntu_component_enabled() {
  local component="$1"
  local codename="$2"
  local apt_source_paths=(/etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources)
  local source_path=""

  for source_path in "${apt_source_paths[@]}"; do
    [[ -f "$source_path" ]] || continue
    if grep -Eq "^[[:space:]]*deb[[:space:]].*[[:space:]]${codename}([^[:space:]]*)?[[:space:]].*(^|[[:space:]])${component}($|[[:space:]])" "$source_path"; then
      return 0
    fi
    if grep -Eq "^[[:space:]]*Components:.*(^|[[:space:]])${component}($|[[:space:]])" "$source_path"; then
      return 0
    fi
  done

  return 1
}

disable_duplicate_ros_apt_sources() {
  local canonical_source_file="$1"
  local source_path=""
  local disabled_path=""
  local suffix=0
  local changed="0"
  local apt_source_paths=(/etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources)

  for source_path in "${apt_source_paths[@]}"; do
    [[ -f "$source_path" ]] || continue
    [[ "$source_path" == "$canonical_source_file" ]] && continue
    if ! grep -q "packages.ros.org/ros2/ubuntu" "$source_path"; then
      continue
    fi

    disabled_path="${source_path}.disabled-by-swarm-control"
    suffix=0
    while sudo test -e "$disabled_path"; do
      suffix=$((suffix + 1))
      disabled_path="${source_path}.disabled-by-swarm-control.${suffix}"
    done

    dependency_status "Disabling duplicate ROS apt source ${source_path}"
    if ! sudo mv "$source_path" "$disabled_path"; then
      return 2
    fi
    changed="1"
  done

  if [[ -f /etc/apt/sources.list ]] && grep -q "packages.ros.org/ros2/ubuntu" /etc/apt/sources.list; then
    dependency_status "WARNING: /etc/apt/sources.list contains a ROS apt source; disable that duplicate manually if apt still reports a Signed-By conflict"
  fi

  [[ "$changed" == "1" ]]
}

ensure_ros_apt_repository() {
  local setup_file="/opt/ros/${ros_distro}/setup.bash"
  if [[ ! -f /etc/os-release ]]; then
    dependency_status "Skipping ROS apt repository setup: /etc/os-release missing"
    return 0
  fi

  # shellcheck disable=SC1091
  dependency_status "Checking Ubuntu release for ROS apt repository"
  source /etc/os-release
  local os_id="${ID:-}"
  local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  if [[ "$os_id" != "ubuntu" || -z "$codename" ]]; then
    dependency_status "Skipping ROS apt repository setup: unsupported OS ${os_id:-unknown}"
    return 0
  fi

  local keyring="/usr/share/keyrings/ros-archive-keyring.gpg"
  local source_file="/etc/apt/sources.list.d/ros2.list"
  local arch
  arch="$(dpkg --print-architecture 2>/dev/null || echo arm64)"
  local repo_line="deb [arch=${arch} signed-by=${keyring}] http://packages.ros.org/ros2/ubuntu ${codename} main"
  local changed="0"

  if disable_duplicate_ros_apt_sources "$source_file"; then
    changed="1"
  else
    local disable_status=$?
    if (( disable_status != 1 )); then
      return "$disable_status"
    fi
  fi

  if ! command -v add-apt-repository >/dev/null 2>&1; then
    dependency_status "Installing software-properties-common for add-apt-repository"
    install_apt_packages software-properties-common || return 1
  fi

  if ubuntu_component_enabled universe "$codename"; then
    dependency_status "Ubuntu universe repository already enabled"
  else
    dependency_status "Enabling Ubuntu universe repository"
    if ! sudo env DEBIAN_FRONTEND=noninteractive add-apt-repository -y universe; then
      return 1
    fi
    changed="1"
  fi

  if [[ ! -f "$keyring" ]]; then
    dependency_status "Installing ROS apt key prerequisites"
    if ! install_apt_packages ca-certificates curl gnupg lsb-release; then
      return 1
    fi

    dependency_status "Downloading ROS apt key from GitHub"
    if ! curl --connect-timeout 15 --max-time 60 --retry 2 --retry-delay 2 -fsSL "https://raw.githubusercontent.com/ros/rosdistro/master/ros.key" \
      | sudo gpg --batch --yes --dearmor -o "$keyring"; then
      return 1
    fi
    changed="1"
  fi

  if ! sudo test -f "$source_file" || [[ "$(sudo cat "$source_file" 2>/dev/null)" != "$repo_line" ]]; then
    dependency_status "Writing ROS apt source list for ${codename}/${arch}"
    echo "$repo_line" | sudo tee "$source_file" >/dev/null
    changed="1"
  fi

  if [[ -f "$setup_file" && "$changed" != "1" ]]; then
    dependency_status "ROS ${ros_distro} setup already present"
    return 0
  fi

  if [[ "$changed" == "1" ]]; then
    apt_updated="0"
    dependency_status "Refreshing apt package lists after ROS repository changes"
    ensure_apt_update || return 1
  fi
  return 0
}

check_cmd_dependency() {
  local dep="$1"
  local cmd="$2"
  shift 2
  local -a pkgs=("$@")
  if command -v "$cmd" >/dev/null 2>&1 && apt_packages_are_current "${pkgs[@]}"; then
    echo "[$dep] is already installed and up to date."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is missing or outdated. Installing/updating now..."
  if install_apt_packages "${pkgs[@]}" && command -v "$cmd" >/dev/null 2>&1; then
    echo "[$dep] installation/update complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation/update failed."
  record_failure "$dep"
  return 1
}

check_colcon_dependency() {
  local dep="colcon"
  if command -v colcon >/dev/null 2>&1 && apt_packages_are_current python3-colcon-common-extensions; then
    echo "[$dep] is already installed and up to date."
    record_already_installed "$dep"
    return 0
  fi

  echo "[$dep] is missing or outdated. Installing/updating now..."
  if install_apt_packages python3-colcon-common-extensions && command -v colcon >/dev/null 2>&1; then
    echo "[$dep] installation/update complete."
    record_just_installed "$dep"
    return 0
  fi

  # Some Ubuntu variants expose a plain colcon package instead.
  if install_apt_packages colcon && command -v colcon >/dev/null 2>&1; then
    echo "[$dep] installation/update complete."
    record_just_installed "$dep"
    return 0
  fi

  echo "[$dep] installation/update failed."
  record_failure "$dep"
  return 1
}

check_apt_package_dependency() {
  local dep="$1"
  local pkg="$2"
  if apt_package_is_current "$pkg"; then
    echo "[$dep] is already installed and up to date."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is missing or outdated. Installing/updating now..."
  if install_apt_packages "$pkg" && dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    echo "[$dep] installation/update complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation/update failed."
  record_failure "$dep"
  return 1
}

check_ros_setup_dependency() {
  local dep="ros-${ros_distro}-setup"
  local setup_file="/opt/ros/${ros_distro}/setup.bash"
  if [[ -f "$setup_file" ]] && apt_package_is_current "ros-${ros_distro}-ros-base"; then
    echo "[$dep] is already installed and up to date."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is missing or outdated. Installing/updating now..."
  if install_apt_packages "ros-${ros_distro}-ros-base" && [[ -f "$setup_file" ]]; then
    echo "[$dep] installation/update complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation/update failed."
  record_failure "$dep"
  return 1
}

echo "[swarm_core_check_install_dependencies] machine_role=${machine_role}"
if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
  dependency_log "Checking sudo credentials before dependency installation."
  dependency_log "If prompted, enter the password once and wait for the script to continue."
  sudo -v || exit 1
fi

progress_total_weight=55
if [[ "$machine_role" == "control" ]]; then
  progress_total_weight=$(( progress_total_weight + 12 ))
else
  progress_total_weight=$(( progress_total_weight + 28 ))
fi
progress_init

if ! run_progress_step 8 "Checking ROS apt repository setup" ensure_ros_apt_repository; then
  record_failure "ros-apt-repository"
fi

run_progress_step 2 "Checking dependency: git" check_cmd_dependency "git" "git" git || true
run_progress_step 1 "Checking dependency: python3" check_cmd_dependency "python3" "python3" python3 || true
run_progress_step 1 "Checking dependency: curl" check_cmd_dependency "curl" "curl" curl || true
run_progress_step 1 "Checking dependency: jq" check_cmd_dependency "jq" "jq" jq || true
run_progress_step 1 "Checking dependency: rg (ripgrep)" check_cmd_dependency "rg (ripgrep)" "rg" ripgrep || true
run_progress_step 4 "Checking dependency: colcon" check_colcon_dependency || true
run_progress_step 18 "Checking dependency: ros-${ros_distro}-ros-base" check_ros_setup_dependency || true
run_progress_step 2 "Checking dependency: ros-${ros_distro}-launch" check_apt_package_dependency "ros-${ros_distro}-launch" "ros-${ros_distro}-launch" || true
run_progress_step 2 "Checking dependency: ros-${ros_distro}-launch-ros" check_apt_package_dependency "ros-${ros_distro}-launch-ros" "ros-${ros_distro}-launch-ros" || true
run_progress_step 4 "Checking dependency: ros-${ros_distro}-cyclonedds" check_apt_package_dependency "ros-${ros_distro}-cyclonedds" "ros-${ros_distro}-cyclonedds" || true
run_progress_step 4 "Checking dependency: ros-${ros_distro}-rmw-cyclonedds-cpp" check_apt_package_dependency "ros-${ros_distro}-rmw-cyclonedds-cpp" "ros-${ros_distro}-rmw-cyclonedds-cpp" || true
run_progress_step 1 "Checking dependency: python3-yaml" check_apt_package_dependency "python3-yaml" "python3-yaml" || true
run_progress_step 3 "Checking dependency: ffmpeg" check_cmd_dependency "ffmpeg" "ffmpeg" ffmpeg || true
run_progress_step 1 "Checking dependency: iw" check_cmd_dependency "iw" "iw" iw || true
run_progress_step 1 "Checking dependency: pytest" check_cmd_dependency "pytest" "pytest" python3-pytest || true
run_progress_step 1 "Checking dependency: ssh (openssh-client)" check_cmd_dependency "ssh (openssh-client)" "ssh" openssh-client || true
run_progress_step 1 "Checking dependency: ssh-copy-id (openssh-client)" check_cmd_dependency "ssh-copy-id (openssh-client)" "ssh-copy-id" openssh-client || true
if [[ "$machine_role" == "control" ]]; then
  run_progress_step 7 "Checking dependency: python3-aiortc" check_apt_package_dependency "python3-aiortc" "python3-aiortc" || true
  run_progress_step 5 "Checking dependency: python3-av" check_apt_package_dependency "python3-av" "python3-av" || true
fi

if [[ "$machine_role" == "robot" ]]; then
  run_progress_step 2 "Checking dependency: python3-lgpio" check_apt_package_dependency "python3-lgpio" "python3-lgpio" || true
  run_progress_step 2 "Checking dependency: python3-gpiozero" check_apt_package_dependency "python3-gpiozero" "python3-gpiozero" || true
  run_progress_step 12 "Checking dependency: python3-opencv" check_apt_package_dependency "python3-opencv" "python3-opencv" || true
  run_progress_step 2 "Checking dependency: v4l2-ctl (v4l-utils)" check_cmd_dependency "v4l2-ctl (v4l-utils)" "v4l2-ctl" v4l-utils || true
  run_progress_step 6 "Checking dependency: ros-${ros_distro}-cv-bridge" check_apt_package_dependency "ros-${ros_distro}-cv-bridge" "ros-${ros_distro}-cv-bridge" || true
  run_progress_step 4 "Checking dependency: ros-${ros_distro}-image-transport" check_apt_package_dependency "ros-${ros_distro}-image-transport" "ros-${ros_distro}-image-transport" || true
fi

progress_current_label="Finalizing dependency summary"
progress_completed_weight="$progress_total_weight"
progress_render

echo
print_dependency_summary "DEPENDENCIES ALREADY INSTALLED AND UP TO DATE:" "${already_installed[@]}"
print_dependency_summary "DEPENDENCIES INSTALLED OR UPDATED:" "${just_installed[@]}"
if [[ ${#failures[@]} -gt 0 ]]; then
  print_dependency_summary "DEPENDENCIES FAILED TO INSTALL:" "${failures[@]}"
fi

if [[ -n "${summary_file}" ]]; then
  write_summary_file "$summary_file"
fi

if [[ ${#failures[@]} -eq 0 ]]; then
  echo
  echo "All dependencies are installed and up to date."
  exit 0
fi

echo
for dep in "${failures[@]}"; do
  echo "[swarm_core_check_install_dependencies] FAILED: ${dep}" >&2
done
exit 1
