#!/usr/bin/env bash
# shellcheck shell=bash

# Waits for apt/dpkg locks with readable status. On freshly imaged Ubuntu,
# unattended-upgrades can hold the package locks for many minutes; this gives
# quickstart users a clear picture instead of a mysterious hang.
#
# Exit code 0 when locks are clear, 1 when the wait timed out.

set -euo pipefail

max_wait="${SWARM_APT_LOCK_MAX_WAIT:-1800}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-wait)
      shift
      max_wait="${1:?--max-wait needs seconds}"
      ;;
    -h|--help)
      echo "Usage: swarm_core_apt_lock_wait.sh [--max-wait <seconds>]"
      exit 0
      ;;
    *)
      echo "[swarm_core_apt_lock_wait] ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift || true
done

lock_holders() {
  command -v fuser >/dev/null 2>&1 || return 0
  sudo fuser \
    /var/lib/dpkg/lock-frontend \
    /var/lib/dpkg/lock \
    /var/cache/apt/archives/lock \
    /var/lib/apt/lists/lock \
    2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -nu
}

deadline=$((SECONDS + max_wait))
while holders="$(lock_holders)" && [[ -n "${holders//[[:space:]]/}" ]]; do
  echo "[WAIT] apt/dpkg lock holder is still running:"
  ps -o pid,ppid,etime,stat,comm,args -p "$(printf '%s' "$holders" | paste -sd, -)" || true
  if (( SECONDS >= deadline )); then
    echo "[STOP] Timed out waiting for apt/dpkg locks. Inspect the process above, then run these only if it is stuck:" >&2
    echo "  sudo ps -fp $(printf '%s' "$holders" | paste -sd, -)" >&2
    echo "  sudo systemctl status unattended-upgrades apt-daily.service apt-daily-upgrade.service --no-pager" >&2
    echo "  sudo journalctl -u unattended-upgrades -n 80 --no-pager" >&2
    echo "  sudo systemctl stop unattended-upgrades apt-daily.service apt-daily-upgrade.service" >&2
    echo "  sudo dpkg --configure -a" >&2
    echo "  sudo apt-get --fix-broken install -y" >&2
    echo "[STOP] apt/dpkg locks did not clear. Run the recovery commands above, then rerun this command." >&2
    exit 1
  fi
  sleep 10
done

echo "[OK] apt/dpkg locks are clear."
