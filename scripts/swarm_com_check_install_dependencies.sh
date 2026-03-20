#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_com_check_install_dependencies.sh [options]

Options:
  --machine-role <control|robot>  Dependency profile (default: control)
  --summary-file <path>           Write dependency summary text to file
  --help                          Show this help

Notes:
  - Community edition is local-only.
  - This script intentionally does not install internet-ingress components
    (for example caddy/cloudflared/coturn).
USAGE
}

machine_role="control"
ros_distro="${ROS_DISTRO:-jazzy}"
apt_updated="0"
failures=()
already_installed=()
just_installed=()
summary_file=""

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
      echo "[swarm_com_check_install_dependencies] ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

case "$machine_role" in
  control|robot) ;;
  *)
    echo "[swarm_com_check_install_dependencies] ERROR: --machine-role must be control or robot." >&2
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
    print_dependency_summary "DEPENDENCIES ALREADY INSTALLED:" "${already_installed[@]}"
    print_dependency_summary "DEPENDENCIES JUST INSTALLED:" "${just_installed[@]}"
    if [[ ${#failures[@]} -gt 0 ]]; then
      print_dependency_summary "DEPENDENCIES FAILED TO INSTALL:" "${failures[@]}"
    fi
  } > "$out_file"
}

ensure_apt_update() {
  if [[ "$apt_updated" == "1" ]]; then
    return 0
  fi
  if sudo apt-get update; then
    apt_updated="1"
    return 0
  fi
  return 1
}

install_apt_packages() {
  if ! ensure_apt_update; then
    return 1
  fi
  sudo apt-get install -y "$@"
}

ensure_ros_apt_repository() {
  local setup_file="/opt/ros/${ros_distro}/setup.bash"
  if [[ -f "$setup_file" ]]; then
    return 0
  fi

  if [[ ! -f /etc/os-release ]]; then
    return 0
  fi

  # shellcheck disable=SC1091
  source /etc/os-release
  local os_id="${ID:-}"
  local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  if [[ "$os_id" != "ubuntu" || -z "$codename" ]]; then
    return 0
  fi

  local keyring="/usr/share/keyrings/ros-archive-keyring.gpg"
  local source_file="/etc/apt/sources.list.d/ros2.list"
  local arch
  arch="$(dpkg --print-architecture 2>/dev/null || echo arm64)"
  local repo_line="deb [arch=${arch} signed-by=${keyring}] http://packages.ros.org/ros2/ubuntu ${codename} main"
  local changed="0"

  if ! command -v add-apt-repository >/dev/null 2>&1; then
    install_apt_packages software-properties-common || return 1
  fi
  if sudo add-apt-repository -y universe >/dev/null 2>&1; then
    changed="1"
  fi

  if [[ ! -f "$keyring" ]]; then
    if ! install_apt_packages ca-certificates curl gnupg lsb-release; then
      return 1
    fi
    if ! curl -fsSL "https://raw.githubusercontent.com/ros/rosdistro/master/ros.key" \
      | sudo gpg --dearmor -o "$keyring"; then
      return 1
    fi
    changed="1"
  fi

  if ! sudo test -f "$source_file" || ! sudo grep -Fxq "$repo_line" "$source_file"; then
    echo "$repo_line" | sudo tee "$source_file" >/dev/null
    changed="1"
  fi

  if [[ "$changed" == "1" ]]; then
    apt_updated="0"
    ensure_apt_update || return 1
  fi
  return 0
}

check_cmd_dependency() {
  local dep="$1"
  local cmd="$2"
  shift 2
  local -a pkgs=("$@")
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "[$dep] is already installed."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is not installed. Installing now..."
  if install_apt_packages "${pkgs[@]}" && command -v "$cmd" >/dev/null 2>&1; then
    echo "[$dep] installation complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation failed."
  record_failure "$dep"
  return 1
}

check_colcon_dependency() {
  local dep="colcon"
  if command -v colcon >/dev/null 2>&1; then
    echo "[$dep] is already installed."
    record_already_installed "$dep"
    return 0
  fi

  echo "[$dep] is not installed. Installing now..."
  if install_apt_packages python3-colcon-common-extensions && command -v colcon >/dev/null 2>&1; then
    echo "[$dep] installation complete."
    record_just_installed "$dep"
    return 0
  fi

  # Some Ubuntu variants expose a plain colcon package instead.
  if install_apt_packages colcon && command -v colcon >/dev/null 2>&1; then
    echo "[$dep] installation complete."
    record_just_installed "$dep"
    return 0
  fi

  echo "[$dep] installation failed."
  record_failure "$dep"
  return 1
}

check_apt_package_dependency() {
  local dep="$1"
  local pkg="$2"
  if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    echo "[$dep] is already installed."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is not installed. Installing now..."
  if install_apt_packages "$pkg" && dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    echo "[$dep] installation complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation failed."
  record_failure "$dep"
  return 1
}

check_ros_setup_dependency() {
  local dep="ros-${ros_distro}-setup"
  local setup_file="/opt/ros/${ros_distro}/setup.bash"
  if [[ -f "$setup_file" ]]; then
    echo "[$dep] is already installed."
    record_already_installed "$dep"
    return 0
  fi
  echo "[$dep] is not installed. Installing now..."
  if install_apt_packages "ros-${ros_distro}-ros-base" && [[ -f "$setup_file" ]]; then
    echo "[$dep] installation complete."
    record_just_installed "$dep"
    return 0
  fi
  echo "[$dep] installation failed."
  record_failure "$dep"
  return 1
}

echo "[swarm_com_check_install_dependencies] machine_role=${machine_role}"

if ! ensure_ros_apt_repository; then
  record_failure "ros-apt-repository"
fi

check_cmd_dependency "git" "git" git || true
check_cmd_dependency "python3" "python3" python3 || true
check_cmd_dependency "curl" "curl" curl || true
check_cmd_dependency "jq" "jq" jq || true
check_cmd_dependency "rg (ripgrep)" "rg" ripgrep || true
check_colcon_dependency || true
check_ros_setup_dependency || true
check_apt_package_dependency "ros-${ros_distro}-cyclonedds" "ros-${ros_distro}-cyclonedds" || true
check_apt_package_dependency "ros-${ros_distro}-rmw-cyclonedds-cpp" "ros-${ros_distro}-rmw-cyclonedds-cpp" || true
check_apt_package_dependency "python3-yaml" "python3-yaml" || true
check_cmd_dependency "ffmpeg" "ffmpeg" ffmpeg || true
check_cmd_dependency "iw" "iw" iw || true
check_cmd_dependency "pytest" "pytest" python3-pytest || true
check_cmd_dependency "ssh (openssh-client)" "ssh" openssh-client || true
check_cmd_dependency "ssh-copy-id (openssh-client)" "ssh-copy-id" openssh-client || true
if [[ "$machine_role" == "control" ]]; then
  check_apt_package_dependency "python3-aiortc" "python3-aiortc" || true
  check_apt_package_dependency "python3-av" "python3-av" || true
fi

if [[ "$machine_role" == "robot" ]]; then
  check_apt_package_dependency "python3-rpi.gpio" "python3-rpi.gpio" || true
  check_apt_package_dependency "python3-opencv" "python3-opencv" || true
  check_cmd_dependency "v4l2-ctl (v4l-utils)" "v4l2-ctl" v4l-utils || true
  check_apt_package_dependency "ros-${ros_distro}-cv-bridge" "ros-${ros_distro}-cv-bridge" || true
  check_apt_package_dependency "ros-${ros_distro}-image-transport" "ros-${ros_distro}-image-transport" || true
fi

echo
print_dependency_summary "DEPENDENCIES ALREADY INSTALLED:" "${already_installed[@]}"
print_dependency_summary "DEPENDENCIES JUST INSTALLED:" "${just_installed[@]}"
if [[ ${#failures[@]} -gt 0 ]]; then
  print_dependency_summary "DEPENDENCIES FAILED TO INSTALL:" "${failures[@]}"
fi

if [[ -n "${summary_file}" ]]; then
  write_summary_file "$summary_file"
fi

if [[ ${#failures[@]} -eq 0 ]]; then
  echo
  echo "All community dependencies have been successfully installed."
  exit 0
fi

echo
for dep in "${failures[@]}"; do
  echo "[swarm_com_check_install_dependencies] FAILED: ${dep}" >&2
done
exit 1
