#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SC="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=./lib/swarm_core_workspace.sh
source "${SCRIPT_DIR}/lib/swarm_core_workspace.sh"
WS="$(swarm_core_detect_workspace_root "${SWARM_CORE_WORKSPACE_ROOT:-}" 2>/dev/null || true)"

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
  passwordless sudo via cloud-init. If password-based SSH was enabled instead,
  a missing key gets one password prompt for ssh-copy-id. Public-key-only
  images with a missing/wrong key must be reflashed or repaired at the console.

Options:
  --imager-checklist             Ask for the robot's Linux username and
                                 hostname, print the Imager settings, and exit
  --robot-name <name>            Robot name (onboarding: default is the user
                                 part of the target; checklist: used only for
                                 non-interactive runs — a terminal always
                                 prompts)
  --robot-hostname <host>        Checklist hostname for non-interactive runs
                                 (a terminal always prompts)
  --robot-ip <IPv4>              First-contact robot address. Stock Noble does
                                 not advertise .local before provisioning, so
                                 obtain this from the router/DHCP lease list
  --control-type <type>          Preselect control_type (e.g. diff_drive,
                                 mecanum_drive); omit to answer the profile
                                 prompts here in the control terminal
  --control-interface <iface>    Preselect control_interface
                                 (e.g. 4wheel_diff_l298n_2, mecanum_l298n_2)
  --skip-camera                  Skip camera discovery during onboarding; run
                                 save_camera_profile_core --require-camera later
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
  swarm_core_new_robot.sh robot4@legion4.local --robot-ip 10.42.0.89 \
    --control-type diff_drive --control-interface 4wheel_diff_l298n_2
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
robot_ip=""
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
    --robot-ip)
      shift
      robot_ip="${1:-}"
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
robot_ip="$(trim "$robot_ip")"
[[ "$boot_wait_timeout" =~ ^[0-9]+$ ]] || fail "--boot-wait-timeout must be integer seconds"
[[ "$cloud_init_timeout" =~ ^[0-9]+$ ]] || fail "--cloud-init-timeout must be integer seconds"
[[ "$domain_id" =~ ^[0-9]+$ ]] || fail "--domain-id must be an integer"

is_ipv4_address() {
  /usr/bin/python3 - "$1" <<'PY_IP' >/dev/null 2>&1
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
if address.version != 4 or address.is_unspecified or address.is_multicast or address.is_loopback:
    raise SystemExit(1)
PY_IP
}

if [[ -n "$robot_ip" ]] && ! is_ipv4_address "$robot_ip"; then
  fail "--robot-ip must be a usable IPv4 address (got '${robot_ip}')."
fi

ensure_ssh_key() {
  if [[ ! -f "$ssh_private_key" ]]; then
    mkdir -p "$(dirname "$ssh_private_key")"
    chmod 700 "$(dirname "$ssh_private_key")"
    log "No SSH key found at $ssh_private_key. Generating an automation-ready ed25519 key now."
    ssh-keygen -q -t ed25519 -a 100 -N "" \
      -C "swarm-control-core@$(hostname -s 2>/dev/null || echo control)" \
      -f "$ssh_private_key"
  fi
  [[ -f "${ssh_private_key}.pub" ]] || fail "Missing public key: ${ssh_private_key}.pub"
}

ensure_ssh_key_batch_ready() {
  # Unencrypted dedicated keys work directly. A caller-supplied encrypted key
  # is also supported when its exact public key is loaded in ssh-agent;
  # IdentitiesOnly below prevents unrelated agent keys from being offered.
  if ssh-keygen -y -P "" -f "$ssh_private_key" >/dev/null 2>&1; then
    return 0
  fi
  local expected_blob=""
  expected_blob="$(awk 'NF >= 2 {print $2; exit}' "${ssh_private_key}.pub")"
  if [[ -n "$expected_blob" ]] && ssh-add -L 2>/dev/null | awk 'NF >= 2 {print $2}' | grep -Fqx "$expected_blob"; then
    return 0
  fi
  fail "SSH key ${ssh_private_key} is passphrase-protected but its exact identity is not loaded. Run: ssh-add '${ssh_private_key}'"
}

persist_control_domain_id() {
  local config_dir tmp
  config_dir="${SWARM_CORE_CONFIG_DIR:-${HOME}/.config/swarm_control_core}"
  install -d -m 700 "$config_dir"
  tmp="$(mktemp "${config_dir}/ros_domain_id.tmp.XXXXXX")"
  printf '%s\n' "$domain_id" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "${config_dir}/ros_domain_id"
}

# Profile catalogs are the single source of truth for the checklist menus:
# entries added to these files appear as choices with no script changes.
control_types_file="${SWARM_CORE_CONTROL_TYPES_FILE:-$SC/config/control_types.yaml}"
control_interfaces_file="${SWARM_CORE_CONTROL_INTERFACES_FILE:-$SC/config/control_interfaces.yaml}"

core_list_control_types() {
  python3 - "$control_types_file" <<'PY_TYPES'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
for name in (data.get("control_types", data) or {}):
    print(name)
PY_TYPES
}

core_list_interfaces_for_type() {
  python3 - "$control_interfaces_file" "$1" <<'PY_IFACES'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
root = data.get("control_interfaces", data) or {}
for name, entry in root.items():
    if isinstance(entry, dict) and sys.argv[2] in (entry.get("compatible_control_types") or []):
        print(name)
PY_IFACES
}

core_wiring_doc_for_interface() {
  python3 - "$control_interfaces_file" "$1" <<'PY_WIRING'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
root = data.get("control_interfaces", data) or {}
entry = root.get(sys.argv[2], {}) if isinstance(root, dict) else {}
docs = entry.get("docs", {}) if isinstance(entry, dict) else {}
print(str(docs.get("wiring", "") or "").strip())
PY_WIRING
}

core_pick_from_list() {
  # $1 = prompt title; remaining args = options. Prints the choice. Options
  # arrive as arguments (not stdin) so the selection prompt reads the
  # terminal, never an exhausted pipe.
  local title="$1" choice count
  shift
  local options=("$@")
  count="${#options[@]}"
  (( count > 0 )) || fail "No options available for: ${title} (check the profile catalogs under $SC/config)."
  while :; do
    {
      echo
      echo "$title"
      echo
      local i
      for i in "${!options[@]}"; do
        printf '  %d) %s\n' $((i + 1)) "${options[$i]}"
      done
      echo
    } >&2
    read -r -p "Select [1-${count}]: " choice || fail "Input closed before a value was entered."
    choice="$(trim "$choice")"
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
      printf '%s' "${options[$((choice - 1))]}"
      return 0
    fi
    echo "Invalid selection '${choice}'. Enter a number from the menu." >&2
  done
}

if [[ "$imager_checklist" == "1" ]]; then
  # The checklist is per-robot: always ask for the identity on a terminal,
  # so values recalled from shell history can never silently reuse a name.
  if [[ -t 0 ]]; then
    while :; do
      read -r -p "Linux username for this robot: " robot_name || fail "Input closed before a value was entered."
      robot_name="$(trim "$robot_name")"
      [[ "$robot_name" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] && break
      echo "Invalid Linux username: lowercase letters, digits, '-', '_'; start with a letter." >&2
    done
    while :; do
      read -r -p "Linux hostname for this robot: " robot_hostname || fail "Input closed before a value was entered."
      robot_hostname="$(trim "$robot_hostname")"
      [[ "$robot_hostname" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] && break
      echo "Invalid hostname: lowercase letters, digits, hyphens; start with a letter or digit." >&2
    done
    mapfile -t available_control_types < <(core_list_control_types)
    control_type="$(core_pick_from_list "Select the control type for this robot:" "${available_control_types[@]}")"
    mapfile -t available_interfaces < <(core_list_interfaces_for_type "$control_type")
    control_interface="$(core_pick_from_list "Select the hardware interface for '${control_type}':" "${available_interfaces[@]}")"
  else
    [[ -n "$robot_name" && -n "$robot_hostname" ]] || \
      fail "--imager-checklist without a terminal requires --robot-name and --robot-hostname."
  fi
  ensure_ssh_key
  checklist_name="$robot_name"
  checklist_host="$robot_hostname"
  checklist_key_arg="$(printf '%q' "$ssh_private_key")"
  checklist_wiring_doc=""
  if [[ -n "$control_interface" ]]; then
    checklist_wiring_doc="$(core_wiring_doc_for_interface "$control_interface")"
  fi
  if [[ -n "$control_type" && -n "$control_interface" ]]; then
    checklist_cmd="  read -r -p 'Robot IPv4 address from the router/DHCP list: ' ROBOT_IP
  ~/.local/bin/swarmc new-robot \\
    ${checklist_name}@${checklist_host}.local \\
    --robot-ip \"\$ROBOT_IP\" \\
    --ssh-private-key ${checklist_key_arg} \\
    --control-type ${control_type} \\
    --control-interface ${control_interface}"
  else
    checklist_cmd="  read -r -p 'Robot IPv4 address from the router/DHCP list: ' ROBOT_IP
  ~/.local/bin/swarmc new-robot \\
    ${checklist_name}@${checklist_host}.local \\
    --robot-ip \"\$ROBOT_IP\" \\
    --ssh-private-key ${checklist_key_arg}"
  fi
  pub_key="$(trim "$(cat "${ssh_private_key}.pub")")"
  cat <<CHECKLIST

Raspberry Pi Imager settings for the new robot
(open "Edit Settings" before writing the card):

  OS: Ubuntu Server 24.04 LTS (64-bit)

  Username: ${checklist_name}

  Hostname: ${checklist_host}

  Password: choose one and record it
  (local recovery; public-key-only SSH does
  not accept this password over the network)

  Wi-Fi: your robot LAN SSID + password
  (skip if using Ethernet)

  Hardware profile: ${control_type:-select during onboarding} / ${control_interface:-select during onboarding}
  Wiring guide: ${checklist_wiring_doc:-select the matching guide under DOCS/GPIO}
  Read and wire that exact guide before applying motor power. Do not copy a
  different L298N/TB6612 profile merely because its name looks similar.

  Camera: attach a USB UVC camera before onboarding. The onboarding command
  will stream-test it and fail without changing a successful camera profile
  if no usable camera is present.

  Enable SSH: YES
  Allow public-key authentication only.
  Paste the key below into the Imager as
  ONE line (it may wrap in this window):

${pub_key}

After first boot
(give it a few minutes on first power-up),

RUN ON THE CONTROL MACHINE:

${checklist_cmd}

Stock Noble normally does not advertise .local yet. Find this hostname in the
router/DHCP lease list. The copy/paste block prompts for that IPv4 address and
passes it with --robot-ip; the .local name is retained only as the expected
identity and is verified before the machine is changed.
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
[[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fail "Invalid SSH username '${user}'."
[[ "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]] || fail "Invalid SSH hostname '${host}'."
[[ "$robot_name" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$ ]] || fail "Invalid robot name '${robot_name}'."
if [[ -n "$control_type" && ! "$control_type" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]]; then
  fail "Invalid --control-type '${control_type}'."
fi
if [[ -n "$control_interface" && ! "$control_interface" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]]; then
  fail "Invalid --control-interface '${control_interface}'."
fi
logical_target="$target"
expected_hostname="${host%.local}"
expected_hostname="${expected_hostname%%.*}"
if is_ipv4_address "$host"; then
  [[ -n "$robot_ip" ]] || robot_ip="$host"
  expected_hostname=""
fi
ssh_host="${robot_ip:-$host}"
connect_target="${user}@${ssh_host}"

command -v ssh >/dev/null 2>&1 || fail "ssh is required"
command -v ssh-keygen >/dev/null 2>&1 || fail "ssh-keygen is required"
command -v ssh-keyscan >/dev/null 2>&1 || fail "ssh-keyscan is required"
command -v ssh-copy-id >/dev/null 2>&1 || fail "ssh-copy-id is required"

[[ -n "$WS" && -f "$WS/install/setup.bash" ]] || fail "Control workspace is not built or could not be detected (${WS:-<unknown>}/install/setup.bash missing). Run 'swarmc setup --role control' from this checkout first."

ensure_ssh_key
ensure_ssh_key_batch_ready

# The checklist-generated command always supplies --robot-ip. Keep an
# interactive recovery path for operators using an older saved command, but
# never scan the LAN or guess which SSH endpoint is the robot.
if [[ -z "$robot_ip" ]] && ! getent ahostsv4 "$ssh_host" >/dev/null 2>&1; then
  if [[ -t 0 ]]; then
    read -r -p "IPv4 address for ${expected_hostname:-$host} from the router/DHCP list: " robot_ip
    robot_ip="$(trim "$robot_ip")"
    is_ipv4_address "$robot_ip" \
      || fail "The entered robot address is not a usable IPv4 address: ${robot_ip:-<empty>}"
    ssh_host="$robot_ip"
    connect_target="${user}@${ssh_host}"
  else
    fail "${ssh_host} does not resolve. Stock Ubuntu Noble does not advertise .local before setup. Find the Pi in the router/DHCP lease list and rerun with --robot-ip <IPv4>."
  fi
fi

repo_url="$(git -C "$SC" remote get-url origin 2>/dev/null || echo "https://github.com/AEmilioDiStefano/swarm_control_core.git")"
case "$repo_url" in
  git@github.com:*)
    repo_url="https://github.com/${repo_url#git@github.com:}"
    ;;
esac
if [[ -n "$(git -C "$SC" status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
  fail "Control checkout has uncommitted or untracked files. Use a clean committed checkout so control and robot run identical code."
fi
repo_ref="$(git -C "$SC" branch --show-current 2>/dev/null || true)"
[[ -n "$repo_ref" ]] || fail "Control checkout is detached. Switch to the branch you intend to provision, then retry."
git check-ref-format --branch "$repo_ref" >/dev/null 2>&1 \
  || fail "Current git branch is not safe to provision: ${repo_ref}"
[[ "$repo_ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] \
  || fail "Current git branch contains characters unsupported by remote provisioning: ${repo_ref}"
repo_commit="$(git -C "$SC" rev-parse HEAD 2>/dev/null || true)"
[[ "$repo_commit" =~ ^[0-9a-f]{40}$ ]] || fail "Could not resolve the control checkout commit."
remote_ref_line="$(git ls-remote --exit-code "$repo_url" "refs/heads/${repo_ref}" 2>/dev/null)" \
  || fail "Branch '${repo_ref}' is not reachable at ${repo_url}. Push it before provisioning a robot."
remote_commit="${remote_ref_line%%[[:space:]]*}"
[[ "$remote_commit" == "$repo_commit" ]] \
  || fail "Control HEAD ${repo_commit:0:12} is not the published tip of '${repo_ref}' (${remote_commit:0:12}). Commit and push the exact control code first."
log "Robot checkout pinned to published ${repo_ref}@${repo_commit:0:12}."

ws_basename="$(basename "$WS")"
[[ "$ws_basename" =~ ^[A-Za-z0-9._-]+$ ]] \
  || fail "Workspace directory name contains unsupported characters: ${ws_basename}"
remote_ws=""

# A freshly flashed robot has a brand-new host key; the stale known_hosts
# entry from the previous image would otherwise hard-fail every SSH step with
# the host-key wall. This command is only for fresh/re-imaged robots, so
# clearing is the safe default.
if [[ "$keep_known_hosts" != "1" ]]; then
  ssh-keygen -R "$host" >/dev/null 2>&1 || true
  ssh-keygen -R "${host%.local}" >/dev/null 2>&1 || true
  if [[ -n "$robot_ip" ]]; then
    ssh-keygen -R "$robot_ip" >/dev/null 2>&1 || true
  fi
  log "Cleared any stale known_hosts entries for ${host}."
fi

log "Waiting for SSH to come up on ${ssh_host} (timeout ${boot_wait_timeout}s; first boot can take a few minutes)..."
deadline=$((SECONDS + boot_wait_timeout))
while ! ssh-keyscan -4 -p 22 -T 5 -H "$ssh_host" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    fail "SSH endpoint never came up for ${host}. Stock Ubuntu Noble does not guarantee .local before setup. Check power/Wi-Fi and rerun with --robot-ip <address-from-router> if the Imager key was not pre-seeded."
  fi
  sleep 5
done
log "SSH endpoint reachable on ${ssh_host}."

declare -a ssh_batch_opts=(
  "-F" "/dev/null"
  "-i" "$ssh_private_key"
  "-o" "IdentitiesOnly=yes"
  "-o" "AddressFamily=inet"
  "-o" "ConnectTimeout=8"
  "-o" "BatchMode=yes"
  "-o" "PasswordAuthentication=no"
  "-o" "StrictHostKeyChecking=accept-new"
)
declare -a ssh_tty_opts=(
  "-F" "/dev/null"
  "-i" "$ssh_private_key"
  "-o" "IdentitiesOnly=yes"
  "-o" "AddressFamily=inet"
  "-o" "ConnectTimeout=8"
  "-o" "StrictHostKeyChecking=accept-new"
)

if ! ssh "${ssh_batch_opts[@]}" "$connect_target" true >/dev/null 2>&1; then
  log "Key auth not active yet (Imager key not pre-seeded)."
  log "A password bootstrap is attempted only for images that explicitly allow password SSH."
  log "Public-key-only Imager setups with a missing/wrong key must be repaired at the Pi console or reflashed with the exact checklist key."
  ssh-copy-id -i "${ssh_private_key}.pub" \
    -F /dev/null \
    -o IdentitiesOnly=yes \
    -o IdentityAgent=none \
    -o AddressFamily=inet \
    -o PubkeyAuthentication=no \
    -o PreferredAuthentications=password,keyboard-interactive \
    -o PasswordAuthentication=yes \
    -o NumberOfPasswordPrompts=1 \
    -o StrictHostKeyChecking=accept-new \
    "$connect_target" \
    || fail "ssh-copy-id failed for ${connect_target}. For the documented public-key-only setup, repair the authorized key at the Pi console or reflash with the exact checklist key; then rerun this command. Password fallback works only when password SSH was explicitly enabled."
  ssh "${ssh_batch_opts[@]}" "$connect_target" true >/dev/null 2>&1 \
    || fail "Key auth still not working on ${connect_target} after ssh-copy-id."
fi

remote_hostname="$(ssh "${ssh_batch_opts[@]}" "$connect_target" 'hostname -s')" \
  || fail "Could not read the hostname from ${connect_target}."
remote_hostname="$(trim "$remote_hostname")"
if [[ -n "$expected_hostname" && "${remote_hostname,,}" != "${expected_hostname,,}" ]]; then
  fail "Address ${ssh_host} answered as hostname '${remote_hostname}', expected '${expected_hostname}'. Refusing to provision the wrong machine."
fi
if [[ -z "$expected_hostname" ]]; then
  expected_hostname="$remote_hostname"
fi

connection_info="$(ssh "${ssh_batch_opts[@]}" "$connect_target" 'printf "%s\n" "$SSH_CONNECTION"')" \
  || fail "Could not determine the robot/control LAN addresses from SSH."
read -r control_lan_ip _ robot_lan_ip _ <<< "$connection_info"
is_ipv4_address "$control_lan_ip" || fail "SSH reported an invalid control address: ${control_lan_ip:-<empty>}"
is_ipv4_address "$robot_lan_ip" || fail "SSH reported an invalid robot address: ${robot_lan_ip:-<empty>}"
if [[ "$keep_known_hosts" != "1" && "$ssh_host" != "$robot_lan_ip" ]]; then
  ssh-keygen -R "$robot_lan_ip" >/dev/null 2>&1 || true
fi
robot_ip="$robot_lan_ip"
connect_target="${user}@${robot_ip}"

remote_home_line="$(ssh "${ssh_batch_opts[@]}" "$connect_target" 'printf "SWARM_REMOTE_HOME=%s\n" "$HOME"')" \
  || fail "Could not determine the robot user's home directory."
remote_home="${remote_home_line#SWARM_REMOTE_HOME=}"
[[ "$remote_home_line" == SWARM_REMOTE_HOME=* && "$remote_home" =~ ^/[A-Za-z0-9._/-]+$ ]] \
  || fail "Robot reported an unsafe/unexpected home directory: ${remote_home:-<empty>}"
remote_ws="${remote_home}/${ws_basename}"

# First boot runs cloud-init (user creation, apt seeding); provisioning that
# races it hits apt locks or a half-created user.
log "Waiting for first-boot provisioning to finish (up to ${cloud_init_timeout}s)..."
ssh "${ssh_batch_opts[@]}" "$connect_target" "set -e; \
  if command -v cloud-init >/dev/null 2>&1; then \
    set +e; \
    timeout '${cloud_init_timeout}' cloud-init status --wait; cloud_rc=\$?; \
    set -e; \
    if [ \"\${cloud_rc}\" -eq 2 ]; then \
      echo 'WARNING: cloud-init completed with recoverable errors; apt/dpkg repair will run next.' >&2; \
    elif [ \"\${cloud_rc}\" -ne 0 ]; then \
      exit \"\${cloud_rc}\"; \
    fi; \
  else \
    echo 'cloud-init is not installed; no first-boot cloud-init job to wait for.'; \
  fi" \
  || fail "cloud-init did not finish cleanly within ${cloud_init_timeout}s. Leave the Pi powered, wait for first boot to settle, then rerun this exact new-robot command."
log "First-boot provisioning settled."

# A prior interrupted run may have left the managed service using an old
# checkout or holding the camera/GPIO devices. Stop it before touching code or
# profiles. Manual quickstart mode also disables it so it cannot return after
# a reboot and race Step 2.
if [[ "$install_service" == "1" ]]; then
  service_action="stop"
else
  service_action="disable --now"
fi
ssh "${ssh_batch_opts[@]}" "$connect_target" "set -e; \
  if systemctl list-unit-files swarm-core-robot.service --no-legend 2>/dev/null | grep -q '^swarm-core-robot.service'; then \
    sudo systemctl ${service_action} swarm-core-robot.service; \
  fi" \
  || fail "Could not stop the prior swarm-core-robot service on ${connect_target}."

log "Preparing the exact robot checkout on ${connect_target}."
ssh "${ssh_batch_opts[@]}" "$connect_target" "set -euo pipefail; \
  if ! command -v git >/dev/null 2>&1; then \
    initial_dpkg_status=0; \
    sudo env DEBIAN_FRONTEND=noninteractive dpkg --configure -a || initial_dpkg_status=\$?; \
    if [ \"\${initial_dpkg_status}\" -ne 0 ]; then echo 'Initial dpkg configuration needs dependency repair; continuing with apt --fix-broken.' >&2; fi; \
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=1800 --fix-broken install -y || exit \$?; \
    sudo env DEBIAN_FRONTEND=noninteractive dpkg --configure -a || exit \$?; \
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=1800 update || exit \$?; \
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=1800 install -y git || exit \$?; \
  fi" \
  || fail "Could not repair package state and install/verify git on ${connect_target}. Wait for any package job to finish and rerun this exact new-robot command."
printf -v checkout_command 'bash -s -- %q %q %q %q' \
  "$remote_ws" "$repo_url" "$repo_ref" "$repo_commit"
ssh "${ssh_batch_opts[@]}" "$connect_target" "$checkout_command" \
  < "${SCRIPT_DIR}/swarm_core_prepare_robot_checkout.sh" \
  || fail "Could not prepare the robot checkout. Any incomplete or dirty checkout was preserved under a .recovery.* path; rerun this exact new-robot command."

log "Provisioning robot dependencies, build, and GPIO on ${connect_target}. This takes a while on a Pi."
bootstrap_extra=""
if [[ "$install_service" == "1" ]]; then
  # Install now, but do not start until the robot profile and peer map exist.
  bootstrap_extra="--install-service --robot-name '${robot_name}'"
fi
ssh -tt "${ssh_tty_opts[@]}" "$connect_target" "set -euo pipefail; \
  remote_ws=\"${remote_ws}\"; \
  \"\${remote_ws}/src/swarm_control_core/scripts/swarm_core_bootstrap_machine.sh\" \
    --machine-role robot \
    --workspace \"\${remote_ws}\" \
    --domain-id '${domain_id}' ${bootstrap_extra}" \
  || fail "Remote robot bootstrap failed for ${connect_target}. Rerun this command after fixing the reported issue; every stage is safe to rerun."

log "Adding the robot-local profile on ${connect_target}."
profile_args="--name '${robot_name}' --host '${connect_target}' --skip-camera"
[[ -z "$control_type" ]] || profile_args="${profile_args} --control-type '${control_type}'"
[[ -z "$control_interface" ]] || profile_args="${profile_args} --control-interface '${control_interface}'"
ssh -tt "${ssh_tty_opts[@]}" "$connect_target" "set -euo pipefail; \
  remote_ws=\"${remote_ws}\"; \
  cd \"\${remote_ws}\"; \
  set +u; \
  source /opt/ros/\"\${ROS_DISTRO:-jazzy}\"/setup.bash; \
  source \"\${remote_ws}/install/setup.bash\"; \
  set -u || true; \
  ros2 run swarm_control_core add_robot_core --workspace \"\${remote_ws}\" ${profile_args}" \
  || fail "Robot-local profile step failed for ${connect_target}."

if [[ "$skip_camera" != "1" ]]; then
  log "Detecting and stream-testing the camera on ${connect_target}."
  ssh -tt "${ssh_tty_opts[@]}" "$connect_target" "set -euo pipefail; \
    remote_ws=\"${remote_ws}\"; \
    cd \"\${remote_ws}\"; \
    set +u; \
    source /opt/ros/\"\${ROS_DISTRO:-jazzy}\"/setup.bash; \
    source \"\${remote_ws}/install/setup.bash\"; \
    set -u || true; \
    ros2 run swarm_control_core save_camera_profile_core --robot '${robot_name}' --require-camera" \
    || fail "Camera validation failed for ${robot_name}. Connect a supported USB UVC camera, close anything using it, and rerun this exact new-robot command. No successful camera profile was overwritten."
fi

# Commit control-side state only after the robot checkout, dependencies,
# hardware profile, and required camera have succeeded. A failed earlier stage
# therefore cannot change this control machine's ROS domain or DDS peer list.
persist_control_domain_id
ssh "${ssh_batch_opts[@]}" "$connect_target" \
  "install -d -m 700 \"\$HOME/.config/swarm_control_core\"; printf '%s\\n' '${domain_id}' > \"\$HOME/.config/swarm_control_core/ros_domain_id\"; chmod 600 \"\$HOME/.config/swarm_control_core/ros_domain_id\"" \
  || fail "Could not persist ROS domain ${domain_id} on ${connect_target}."

# Record direct CycloneDDS peers in both directions. Hybrid mode continues to
# use multicast where it works and falls back to these unicast addresses where
# APs suppress multicast.
# shellcheck source=./lib/swarm_core_discovery.sh
source "${SCRIPT_DIR}/lib/swarm_core_discovery.sh"
swarm_core_add_static_peer "$robot_lan_ip" \
  || fail "Could not record robot DDS peer ${robot_lan_ip} on the control machine."
ssh "${ssh_batch_opts[@]}" "$connect_target" "set -euo pipefail; \
  source \"${remote_ws}/src/swarm_control_core/scripts/lib/swarm_core_discovery.sh\"; \
  swarm_core_add_static_peer '${control_lan_ip}'" \
  || fail "Could not record control DDS peer ${control_lan_ip} on the robot."

if [[ "$install_service" == "1" ]]; then
  log "Starting the robot service now that the profile and discovery peers exist."
  ssh "${ssh_batch_opts[@]}" "$connect_target" \
    'sudo systemctl enable swarm-core-robot.service && sudo systemctl restart swarm-core-robot.service && sudo systemctl --no-pager --full status swarm-core-robot.service' \
    || fail "Robot profile succeeded, but swarm-core-robot.service did not start cleanly."
fi

log "Registering/approving ${robot_name} on this control machine."
set +u
# shellcheck source=/dev/null
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
# shellcheck source=/dev/null
source "$WS/install/setup.bash"
set -u || true
ros2 run swarm_control_core sync_robot_entries_core \
  --workspace "$WS" \
  --source "${robot_name}=${connect_target}" \
  --ssh-private-key "$ssh_private_key" \
  || fail "Control-machine registration failed for ${robot_name}=${connect_target}."

echo
log "Verifying with robot_doctor_core."
ros2 run swarm_control_core robot_doctor_core --workspace "$WS" --robot "$robot_name" \
  || fail "Robot profile/runtime verification failed for ${robot_name}; onboarding is not complete."

echo
log "[OK] ${robot_name} (${logical_target}, transport ${connect_target}) is onboarded and registered/approved on this control machine."
log "DDS peers: control=${control_lan_ip}, robot=${robot_lan_ip}; discovery policy defaults to hybrid."
next_key="$(printf '%q' "$ssh_private_key")"
next_target="$(printf '%q' "$connect_target")"
log "NEXT: ssh -F /dev/null -i ${next_key} -o IdentitiesOnly=yes -o AddressFamily=inet ${next_target}"
log "Then follow DOCS/NOBLE_FRESH_INSTALL.md from the wheel test onward."
