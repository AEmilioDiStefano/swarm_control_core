#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SC="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS="$(cd "${SC}/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_new_robot.sh --imager-checklist [--robot-name <name>] [--robot-hostname <host>]
  swarm_core_new_robot.sh <user@host> [options]

Purpose:
  Zero-touch onboarding of one freshly flashed robot Pi for swarm_control_core,
  entirely from the control machine. No manual SSH session on the robot is
  ever needed.

  Flow:
    A) --imager-checklist prints the exact Raspberry Pi Imager settings to use
       when flashing the SD card, including this control machine's SSH public
       key (generated now if missing). Flash with those settings, boot the Pi,
       then run mode B.
    B) <user@host> clears any stale known_hosts entry for the host (fresh
       flash = new host key), waits for SSH to come up, waits for cloud-init
       first-boot provisioning to finish, then over SSH: clones and builds the
       core workspace on the robot, prepares GPIO, adds the robot-local
       profile, and finally registers/approves the robot on this control
       machine (sync_robot_entries_core) so it is trusted for FPV control.

  If the Imager pre-seeded the control machine's public key, the whole run is
  password-free: fresh RPi-Imager Ubuntu images grant the created user
  passwordless sudo via cloud-init. Without a pre-seeded key you get one
  password prompt for ssh-copy-id, typed here on the control machine.

Options:
  --imager-checklist             Ask for the robot's Linux username and
                                 hostname, print the Imager settings, and exit
  --robot-name <name>            Robot name (onboarding: default is the user
                                 part of the target; checklist: used only for
                                 non-interactive runs — a terminal always
                                 prompts)
  --robot-hostname <host>        Checklist hostname for non-interactive runs
                                 (a terminal always prompts)
  --control-type <type>          Preselect control_type (e.g. diff_drive,
                                 mecanum_drive); omit to answer the profile
                                 prompts here in the control terminal
  --control-interface <iface>    Preselect control_interface
                                 (e.g. 4wheel_diff_l298n_2, mecanum_l298n_2)
  --skip-camera                  Skip camera discovery during onboarding; run
                                 save_camera_profile_core later
  --domain-id <id>               ROS_DOMAIN_ID (default: 17)
  --install-service              Also install+enable the robot systemd service
                                 (default: manual quickstart bringup)
  --ssh-private-key <path>       SSH private key (default: ~/.ssh/id_ed25519)
  --boot-wait-timeout <sec>      Max wait for first SSH contact (default: 600)
  --cloud-init-timeout <sec>     Max wait for first-boot provisioning (default: 300)
  --keep-known-hosts             Do not clear the stale known_hosts entry
  -h, --help                     Show this help

Examples:
  # 1) before flashing the SD card (asks for the robot's
  #    Linux username and hostname, then prints the settings):
  swarm_core_new_robot.sh --imager-checklist

  # 2) after the Pi boots (also correct for re-imaged robots):
  swarm_core_new_robot.sh robot4@legion4.local --control-type diff_drive \
    --control-interface 4wheel_diff_l298n_2
USAGE
}

log() {
  echo "[swarm_core_new_robot] $*" >&2
}

fail() {
  echo "[swarm_core_new_robot] ERROR: $*" >&2
  exit 1
}

trim() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

normalize_target() {
  local raw="$1"
  raw="$(trim "$raw")"
  [[ -n "$raw" ]] || return 1
  [[ "$raw" == *"@"* ]] || return 1
  local user="${raw%@*}"
  local host="${raw#*@}"
  [[ -n "$user" && -n "$host" ]] || return 1
  printf '%s@%s' "$user" "$host"
}

imager_checklist="0"
target=""
robot_name=""
robot_hostname=""
control_type=""
control_interface=""
skip_camera="0"
domain_id="${SWARM_CORE_ROS_DOMAIN_ID:-17}"
install_service="0"
ssh_private_key="${HOME}/.ssh/id_ed25519"
boot_wait_timeout="600"
cloud_init_timeout="300"
keep_known_hosts="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --imager-checklist)
      imager_checklist="1"
      ;;
    --robot-name)
      shift
      robot_name="${1:-}"
      ;;
    --robot-hostname)
      shift
      robot_hostname="${1:-}"
      ;;
    --control-type)
      shift
      control_type="${1:-}"
      ;;
    --control-interface)
      shift
      control_interface="${1:-}"
      ;;
    --skip-camera)
      skip_camera="1"
      ;;
    --domain-id)
      shift
      domain_id="${1:-}"
      ;;
    --install-service)
      install_service="1"
      ;;
    --ssh-private-key)
      shift
      ssh_private_key="${1:-}"
      ;;
    --boot-wait-timeout)
      shift
      boot_wait_timeout="${1:-}"
      ;;
    --cloud-init-timeout)
      shift
      cloud_init_timeout="${1:-}"
      ;;
    --keep-known-hosts)
      keep_known_hosts="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      fail "Unknown option: $1"
      ;;
    *)
      [[ -z "$target" ]] || fail "Exactly one <user@host> target is accepted (got '$target' and '$1')."
      target="$1"
      ;;
  esac
  shift
done

robot_name="$(trim "$robot_name")"
control_type="$(trim "$control_type")"
control_interface="$(trim "$control_interface")"
ssh_private_key="$(trim "$ssh_private_key")"
[[ "$boot_wait_timeout" =~ ^[0-9]+$ ]] || fail "--boot-wait-timeout must be integer seconds"
[[ "$cloud_init_timeout" =~ ^[0-9]+$ ]] || fail "--cloud-init-timeout must be integer seconds"
[[ "$domain_id" =~ ^[0-9]+$ ]] || fail "--domain-id must be an integer"

ensure_ssh_key() {
  if [[ ! -f "$ssh_private_key" ]]; then
    mkdir -p "$(dirname "$ssh_private_key")"
    chmod 700 "$(dirname "$ssh_private_key")"
    log "No SSH key found at $ssh_private_key. Generating ed25519 key now."
    ssh-keygen -t ed25519 -a 100 -f "$ssh_private_key"
  fi
  [[ -f "${ssh_private_key}.pub" ]] || fail "Missing public key: ${ssh_private_key}.pub"
}

if [[ "$imager_checklist" == "1" ]]; then
  # The checklist is per-robot: always ask for the identity on a terminal,
  # so values recalled from shell history can never silently reuse a name.
  if [[ -t 0 ]]; then
    while :; do
      read -r -p "Enter the Linux username for this robot (then press Enter): " robot_name
      robot_name="$(trim "$robot_name")"
      [[ "$robot_name" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] && break
      echo "Invalid Linux username: lowercase letters, digits, '-', '_'; start with a letter." >&2
    done
    while :; do
      read -r -p "Enter the hostname for this robot (then press Enter): " robot_hostname
      robot_hostname="$(trim "$robot_hostname")"
      [[ "$robot_hostname" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] && break
      echo "Invalid hostname: lowercase letters, digits, hyphens; start with a letter or digit." >&2
    done
  else
    [[ -n "$robot_name" && -n "$robot_hostname" ]] || \
      fail "--imager-checklist without a terminal requires --robot-name and --robot-hostname."
  fi
  ensure_ssh_key
  checklist_name="$robot_name"
  checklist_host="$robot_hostname"
  pub_key="$(cat "${ssh_private_key}.pub")"
  cat <<CHECKLIST

Raspberry Pi Imager settings for the new robot
(open "Edit Settings" before writing the card):

  OS: Ubuntu Server 24.04 LTS (64-bit)

  Username: ${checklist_name}

  Hostname: ${checklist_host}

  Password: choose one and record it
  (fallback only; the SSH key below makes
  normal onboarding password-free)

  Wi-Fi: your robot LAN SSID + password
  (skip if using Ethernet)

  Enable SSH: YES
  Allow public-key authentication only.
  Paste the key below into the Imager as
  ONE line (it may wrap in this window):

${pub_key}

After first boot
(give it a few minutes on first power-up),
RUN ON THE CONTROL MACHINE:

  ~/.local/bin/swarmc new-robot \\
    ${checklist_name}@${checklist_host}.local

(add --control-type and --control-interface
to preselect the drive/hardware profiles, or
answer the prompts interactively there)
CHECKLIST
  exit 0
fi

[[ -n "$target" ]] || { usage >&2; fail "Missing <user@host> target (or use --imager-checklist)."; }

# Onboarding must run ON the control machine, pointed AT the robot. Targeting
# this machine itself would write robot-side state into the control config.
target_host_short="${target#*@}"
target_host_short="${target_host_short%.local}"
case "$target_host_short" in
  localhost|127.*|"$(hostname -s 2>/dev/null || hostname)")
    fail "Target '$target' resolves to this machine. Run this command on the CONTROL machine and point it at the robot's hostname (see DOCS/ADD_robot_pi.md Step 3)."
    ;;
esac
target="$(normalize_target "$target")" || fail "Invalid target: expected user@host"
user="${target%@*}"
host="${target#*@}"
[[ -n "$robot_name" ]] || robot_name="$user"

command -v ssh >/dev/null 2>&1 || fail "ssh is required"
command -v ssh-keygen >/dev/null 2>&1 || fail "ssh-keygen is required"
command -v ssh-keyscan >/dev/null 2>&1 || fail "ssh-keyscan is required"
command -v ssh-copy-id >/dev/null 2>&1 || fail "ssh-copy-id is required"

[[ -f "$WS/install/setup.bash" ]] || fail "Control workspace is not built yet ($WS/install/setup.bash missing). Run scripts/swarm_core_bootstrap_machine.sh --machine-role control first (see DOCS/ADD_robot_pi.md Step 1)."

ensure_ssh_key

repo_url="$(git -C "$SC" remote get-url origin 2>/dev/null || echo "https://github.com/AEmilioDiStefano/swarm_control_core.git")"
case "$repo_url" in
  git@github.com:*)
    repo_url="https://github.com/${repo_url#git@github.com:}"
    ;;
esac

ws_basename="$(basename "$WS")"
remote_ws="\$HOME/${ws_basename}"

# A freshly flashed robot has a brand-new host key; the stale known_hosts
# entry from the previous image would otherwise hard-fail every SSH step with
# the host-key wall. This command is only for fresh/re-imaged robots, so
# clearing is the safe default.
if [[ "$keep_known_hosts" != "1" ]]; then
  ssh-keygen -R "$host" >/dev/null 2>&1 || true
  ssh-keygen -R "${host%.local}" >/dev/null 2>&1 || true
  log "Cleared any stale known_hosts entries for ${host}."
fi

log "Waiting for SSH to come up on ${host} (timeout ${boot_wait_timeout}s; first boot can take a few minutes)..."
deadline=$((SECONDS + boot_wait_timeout))
until ssh-keyscan -T 5 -H "$host" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    fail "SSH endpoint never came up on ${host}. Check power, network, and that the Imager settings (hostname, Wi-Fi, SSH) were applied."
  fi
  sleep 5
done
log "SSH endpoint reachable on ${host}."

declare -a ssh_batch_opts=(
  "-i" "$ssh_private_key"
  "-o" "ConnectTimeout=8"
  "-o" "BatchMode=yes"
  "-o" "PasswordAuthentication=no"
  "-o" "StrictHostKeyChecking=accept-new"
)
declare -a ssh_tty_opts=(
  "-i" "$ssh_private_key"
  "-o" "ConnectTimeout=8"
  "-o" "StrictHostKeyChecking=accept-new"
)

if ! ssh "${ssh_batch_opts[@]}" "$target" true >/dev/null 2>&1; then
  log "Key auth not active yet (Imager key not pre-seeded)."
  log "ACTION REQUIRED: enter the password set in the Imager once for ssh-copy-id."
  ssh-copy-id -i "${ssh_private_key}.pub" -o StrictHostKeyChecking=accept-new "$target" \
    || fail "ssh-copy-id failed for ${target} (verify the Imager username/password)."
  ssh "${ssh_batch_opts[@]}" "$target" true >/dev/null 2>&1 \
    || fail "Key auth still not working on ${target} after ssh-copy-id."
fi

# First boot runs cloud-init (user creation, apt seeding); provisioning that
# races it hits apt locks or a half-created user.
log "Waiting for first-boot provisioning to finish (up to ${cloud_init_timeout}s)..."
ssh "${ssh_batch_opts[@]}" "$target" \
  "command -v cloud-init >/dev/null 2>&1 && timeout ${cloud_init_timeout} cloud-init status --wait >/dev/null 2>&1 || true" \
  || log "cloud-init wait was inconclusive; continuing."
log "First-boot provisioning settled."

log "Provisioning robot workspace on ${target} (clone + dependencies + build + GPIO). This takes a while on a Pi."
bootstrap_extra=""
if [[ "$install_service" == "1" ]]; then
  bootstrap_extra="--enable-service-now --robot-name '${robot_name}'"
fi
ssh -tt "${ssh_tty_opts[@]}" "$target" "set -euo pipefail; \
  if ! command -v git >/dev/null 2>&1; then \
    sudo apt-get -o DPkg::Lock::Timeout=1800 update; \
    sudo apt-get -o DPkg::Lock::Timeout=1800 install -y git; \
  fi; \
  remote_ws=\"${remote_ws}\"; \
  install -d \"\${remote_ws}/src\"; \
  if [ ! -d \"\${remote_ws}/src/swarm_control_core/.git\" ]; then \
    git clone '${repo_url}' \"\${remote_ws}/src/swarm_control_core\"; \
  fi; \
  \"\${remote_ws}/src/swarm_control_core/scripts/swarm_core_bootstrap_machine.sh\" \
    --machine-role robot \
    --workspace \"\${remote_ws}\" \
    --domain-id '${domain_id}' ${bootstrap_extra}" \
  || fail "Remote robot bootstrap failed for ${target}. Rerun this command after fixing the reported issue; every stage is safe to rerun."

log "Adding the robot-local profile on ${target}."
profile_args="--name '${robot_name}' --host '${target}'"
[[ -z "$control_type" ]] || profile_args="${profile_args} --control-type '${control_type}'"
[[ -z "$control_interface" ]] || profile_args="${profile_args} --control-interface '${control_interface}'"
[[ "$skip_camera" != "1" ]] || profile_args="${profile_args} --skip-camera"
ssh -tt "${ssh_tty_opts[@]}" "$target" "set -euo pipefail; \
  remote_ws=\"${remote_ws}\"; \
  cd \"\${remote_ws}\"; \
  set +u; \
  source /opt/ros/\"\${ROS_DISTRO:-jazzy}\"/setup.bash; \
  source \"\${remote_ws}/install/setup.bash\"; \
  set -u || true; \
  ros2 run swarm_control_core add_robot_core --workspace \"\${remote_ws}\" ${profile_args}" \
  || fail "Robot-local profile step failed for ${target}."

log "Registering/approving ${robot_name} on this control machine."
set +u
# shellcheck source=/dev/null
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
# shellcheck source=/dev/null
source "$WS/install/setup.bash"
set -u || true
ros2 run swarm_control_core sync_robot_entries_core \
  --workspace "$WS" \
  --source "${robot_name}=${target}" \
  || fail "Control-machine registration failed for ${robot_name}=${target}."

echo
log "Verifying with robot_doctor_core."
ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot "$robot_name" || true

echo
log "[OK] ${robot_name} (${target}) is onboarded and registered/approved on this control machine."
log "Registered/approved robots are ready for QUICKSTART handoff (DOCS/QUICKSTART.md)."
