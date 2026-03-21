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
  - Installs gpiomem udev rule
  - Reloads udev rules
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

user_has_gpiomem_access_now() {
  local user_name="$1"
  if [[ ! -e /dev/gpiomem ]]; then
    return 1
  fi
  if [[ "${user_name}" == "${USER:-$(id -un)}" ]]; then
    [[ -r /dev/gpiomem && -w /dev/gpiomem ]]
    return $?
  fi
  sudo -u "$user_name" test -r /dev/gpiomem && sudo -u "$user_name" test -w /dev/gpiomem
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
RULE

run_root mkdir -p "$(dirname "$rule_file")"
run_root install -m 644 -o root -g root "$tmp_rule" "$rule_file"
run_root udevadm control --reload-rules
run_root udevadm trigger /dev/gpiomem || true

if [[ -e /dev/gpiomem ]]; then
  ls -l /dev/gpiomem || true
else
  log "NOTE: /dev/gpiomem is not present yet (hardware/driver dependent until reboot)."
fi

# Try to grant immediate session access without requiring reboot/new login.
if [[ -e /dev/gpiomem ]] && ! user_has_gpiomem_access_now "$target_user"; then
  if command -v setfacl >/dev/null 2>&1; then
    log "Applying immediate ACL on /dev/gpiomem for user '${target_user}'."
    run_root setfacl -m "u:${target_user}:rw" /dev/gpiomem || true
  fi
fi

echo
log "GPIO access configuration complete."
if user_has_gpiomem_access_now "$target_user"; then
  log "[OK] GPIO access is active in current session."
  log "No reboot required."
else
  log "GPIO access is not active in current session."
  log "Open a new SSH session (or run 'newgrp gpio'). Reboot only if /dev/gpiomem still absent."
fi
