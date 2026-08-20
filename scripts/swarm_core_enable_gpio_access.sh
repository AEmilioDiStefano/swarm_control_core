#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_enable_gpio_access.sh [options]

Options:
  --rule-file <path>   udev rule file path (default: /etc/udev/rules.d/99-gpiomem.rules)
  --user <name>        User to add to gpio group (default: current user)
  -h, --help           Show this help.

Behavior:
  - Ensures gpio group exists
  - Adds user to gpio group
  - Installs gpiochip + gpiomem udev rules
  - Reloads udev rules
  - Verifies the actual lgpio gpiochip open/close path as the target user
  - Prints current-session access guidance (re-login/reboot only if needed)
USAGE
}

log() {
  echo "[swarm_core_enable_gpio_access] $*" >&2
}

fail() {
  echo "[swarm_core_enable_gpio_access] ERROR: $*" >&2
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

run_as_user() {
  local user_name="$1"
  shift
  if [[ "${EUID:-$(id -u)}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$user_name" -- "$@"
  elif command -v sudo >/dev/null 2>&1; then
    # sudo initializes supplementary groups from the updated group database,
    # even when target_user is the current login whose shell predates usermod.
    sudo -u "$user_name" "$@"
  elif [[ "${user_name}" == "${USER:-$(id -un)}" ]]; then
    "$@"
  else
    return 1
  fi
}

gpiochip_devices() {
  local device
  for device in /dev/gpiochip*; do
    [[ -e "$device" ]] && printf '%s\n' "$device"
  done
}

probe_lgpio_as_user() {
  local user_name="$1" device chip_number
  while IFS= read -r device; do
    [[ -n "$device" ]] || continue
    chip_number="${device##*/gpiochip}"
    if run_as_user "$user_name" /usr/bin/python3 - "$chip_number" <<'PY_LGPIO' >/dev/null 2>&1
import lgpio
import sys

handle = lgpio.gpiochip_open(int(sys.argv[1]))
lgpio.gpiochip_close(handle)
PY_LGPIO
    then
      log "[OK] target user '${user_name}' opened and closed ${device} through lgpio."
      return 0
    fi
  done < <(gpiochip_devices)
  return 1
}

rule_file="/etc/udev/rules.d/99-gpiomem.rules"
target_user="${USER:-$(id -un)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rule-file)
      shift
      rule_file="${1:-}"
      ;;
    --user)
      shift
      target_user="${1:-}"
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

[[ -n "$rule_file" ]] || fail "--rule-file cannot be empty"
[[ -n "$target_user" ]] || fail "--user cannot be empty"
id "$target_user" >/dev/null 2>&1 || fail "User does not exist: $target_user"

if ! getent group gpio >/dev/null 2>&1; then
  log "Creating gpio group."
  run_root groupadd --system gpio
fi

log "Adding user '${target_user}' to gpio group."
run_root usermod -aG gpio "$target_user"

tmp_rule="$(mktemp)"
trap 'rm -f "$tmp_rule"' EXIT
cat > "$tmp_rule" <<'RULE'
KERNEL=="gpiomem", GROUP="gpio", MODE="0660"
SUBSYSTEM=="gpio", KERNEL=="gpiochip[0-9]*", GROUP="gpio", MODE="0660"
RULE

run_root mkdir -p "$(dirname "$rule_file")"
run_root install -m 644 -o root -g root "$tmp_rule" "$rule_file"
run_root udevadm control --reload-rules
run_root udevadm trigger /dev/gpiomem || true
run_root udevadm trigger --subsystem-match=gpio --action=add || true

devices_found="0"
for device in /dev/gpiomem /dev/gpiochip*; do
  if [[ -e "$device" ]]; then
    devices_found="1"
    ls -l "$device" || true
  fi
done
if [[ ! -e /dev/gpiomem ]]; then
  log "NOTE: /dev/gpiomem is not present yet (hardware/driver dependent until reboot)."
fi

# Try to grant immediate session access without requiring reboot/new login.
if command -v setfacl >/dev/null 2>&1; then
  for device in /dev/gpiomem /dev/gpiochip*; do
    [[ -e "$device" ]] || continue
    log "Applying immediate ACL on ${device} for user '${target_user}'."
    run_root setfacl -m "u:${target_user}:rw" "$device" || true
  done
fi

echo
log "GPIO access configuration complete."
if probe_lgpio_as_user "$target_user"; then
  log "[OK] gpiochip access is active for the runtime user."
  log "No reboot required."
else
  if [[ "$devices_found" == "1" ]]; then
    fail "GPIO devices exist, but none could be opened through lgpio as '${target_user}'. Re-login or reboot once, rerun this script, and do not drive motors while the backend is mock."
  elif [[ -r /proc/device-tree/model ]] && grep -aqi 'Raspberry Pi' /proc/device-tree/model; then
    fail "No /dev/gpiochip device could be opened through lgpio as '${target_user}'. Reboot once, rerun this script, and do not drive motors while the backend is mock."
  else
    log "NOTE: no GPIO character devices are present on this non-Raspberry-Pi host."
  fi
fi
