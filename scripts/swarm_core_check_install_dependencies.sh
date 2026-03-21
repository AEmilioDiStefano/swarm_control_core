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

repeat_char() {
  local char="$1"
  local count="${2:-0}"
  local out=""
  if (( count <= 0 )); then
    printf '%s' ""
    return 0
  fi
  printf -v out '%*s' "$count" ''
  printf '%s' "${out// /$char}"
}

truncate_for_progress() {
  local text="$1"
  local max_len="${2:-0}"
  if (( max_len <= 0 )); then
    printf '%s' ""
    return 0
  fi
  if (( ${#text} <= max_len )); then
    printf '%s' "$text"
    return 0
  fi
  if (( max_len <= 3 )); then
    printf '%.*s' "$max_len" "$text"
    return 0
  fi
  printf '%s...' "${text:0:max_len-3}"
}

progress_printf() {
  if [[ "$progress_fd" == "2" ]]; then
    printf "$@" >&2
  else
    printf "$@" >&1
  fi
}

progress_render() {
  local total=0
  local done=0
  local percent=0
  local bar_width=12
  local filled=0
  local complete=""
  local remaining=""
  local bar=""
  local percent_text=""
  local label_width=0
  local label=""
  local line=""

  [[ "$progress_enabled" == "1" ]] || return 0

  total=$((progress_total_weight))
  done=$((progress_completed_weight))
  if (( total > 0 )); then
    percent=$(( done * 100 / total ))
  fi
  if (( percent > 100 )); then
    percent=100
  fi

  if (( progress_cols >= 100 )); then
    bar_width=40
  elif (( progress_cols >= 80 )); then
    bar_width=30
  elif (( progress_cols >= 60 )); then
    bar_width=20
  fi

  if (( total > 0 )); then
    filled=$(( done * bar_width / total ))
  fi
  if (( filled > bar_width )); then
    filled=$bar_width
  fi

  complete="$(repeat_char '#' "$filled")"
  if (( done >= total )); then
    remaining="$(repeat_char '#' "$((bar_width - filled))")"
    bar="${complete}${remaining}"
  else
    remaining="$(repeat_char '.' "$((bar_width - filled - 1))")"
    bar="${complete}>${remaining}"
  fi

  printf -v percent_text '%3d%%' "$percent"
  label_width=$(( progress_cols - bar_width - ${#percent_text} - 6 ))
  if (( label_width < 0 )); then
    label_width=0
  fi
  label="$(truncate_for_progress "$progress_current_label" "$label_width")"
  line="[${bar}] ${percent_text}"
  if [[ -n "$label" ]]; then
    line="${line} ${label}"
  fi

  progress_printf '\0337'
  progress_printf '\033[%d;1H' "$progress_lines"
  progress_printf '\033[2K%s' "$line"
  progress_printf '\0338'
}

progress_cleanup() {
  [[ "$progress_enabled" == "1" ]] || return 0
  progress_printf '\0337'
  progress_printf '\033[%d;1H' "$progress_lines"
  progress_printf '\033[2K'
  progress_printf '\0338'
  progress_printf '\033[r\033[?25h'
  progress_enabled="0"
}

progress_init() {
  local tty_size=""

  if [[ -t 2 ]]; then
    progress_fd="2"
  elif [[ -t 1 ]]; then
    progress_fd="1"
  else
    return 0
  fi

  if [[ "$progress_fd" == "2" ]]; then
    tty_size="$(stty size <&2 2>/dev/null || true)"
  else
    tty_size="$(stty size <&1 2>/dev/null || true)"
  fi
  if [[ -z "$tty_size" ]]; then
    progress_fd=""
    return 0
  fi

  read -r progress_lines progress_cols <<<"$tty_size"
  if (( progress_lines < 4 || progress_cols < 40 )); then
    progress_fd=""
    progress_lines="0"
    progress_cols="0"
    return 0
  fi

  progress_enabled="1"
  trap progress_cleanup EXIT
  progress_printf '\033[?25l'
  progress_printf '\033[1;%dr' "$((progress_lines - 1))"
  progress_render
}

run_progress_step() {
  local weight="$1"
  local label="$2"
  shift 2
  local step_status=0

  progress_current_label="$label"
  progress_render

  if "$@"; then
    step_status=0
  else
    step_status=$?
  fi

  progress_completed_weight=$(( progress_completed_weight + weight ))
  progress_render
  return "$step_status"
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

echo "[swarm_core_check_install_dependencies] machine_role=${machine_role}"

progress_total_weight=50
if [[ "$machine_role" == "control" ]]; then
  progress_total_weight=$(( progress_total_weight + 12 ))
else
  progress_total_weight=$(( progress_total_weight + 26 ))
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
  run_progress_step 2 "Checking dependency: python3-rpi.gpio" check_apt_package_dependency "python3-rpi.gpio" "python3-rpi.gpio" || true
  run_progress_step 12 "Checking dependency: python3-opencv" check_apt_package_dependency "python3-opencv" "python3-opencv" || true
  run_progress_step 2 "Checking dependency: v4l2-ctl (v4l-utils)" check_cmd_dependency "v4l2-ctl (v4l-utils)" "v4l2-ctl" v4l-utils || true
  run_progress_step 6 "Checking dependency: ros-${ros_distro}-cv-bridge" check_apt_package_dependency "ros-${ros_distro}-cv-bridge" "ros-${ros_distro}-cv-bridge" || true
  run_progress_step 4 "Checking dependency: ros-${ros_distro}-image-transport" check_apt_package_dependency "ros-${ros_distro}-image-transport" "ros-${ros_distro}-image-transport" || true
fi

progress_current_label="Finalizing dependency summary"
progress_completed_weight="$progress_total_weight"
progress_render

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
  echo "All dependencies have been successfully installed."
  exit 0
fi

echo
for dep in "${failures[@]}"; do
  echo "[swarm_core_check_install_dependencies] FAILED: ${dep}" >&2
done
exit 1
