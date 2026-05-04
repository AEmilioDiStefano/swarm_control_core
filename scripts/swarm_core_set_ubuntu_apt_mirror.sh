#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_set_ubuntu_apt_mirror.sh [options]

Options:
  --mirror <url>           Ubuntu archive mirror URL.
                           Default: http://archive.ubuntu.com/ubuntu
                           On arm64/armhf, default: http://ports.ubuntu.com/ubuntu-ports
  --security-mirror <url>  Ubuntu security mirror URL. Default: same as --mirror.
  --dry-run                Show what would change without writing files.
  -h, --help               Show this help.

Purpose:
  Replace stalled Ubuntu apt mirror URLs in /etc/apt/sources.list and
  /etc/apt/sources.list.d with a known mirror. This only touches Ubuntu OS
  archive/security/ports source URLs and leaves third-party repositories alone.
USAGE
}

mirror=""
security_mirror=""
dry_run="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mirror)
      shift
      mirror="${1:-}"
      ;;
    --security-mirror)
      shift
      security_mirror="${1:-}"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[swarm_core_set_ubuntu_apt_mirror] ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
if [[ -z "$mirror" ]]; then
  case "$arch" in
    arm64|armhf|armel)
      mirror="http://ports.ubuntu.com/ubuntu-ports"
      ;;
    *)
      mirror="http://archive.ubuntu.com/ubuntu"
      ;;
  esac
fi
security_mirror="${security_mirror:-$mirror}"
mirror="${mirror%/}"
security_mirror="${security_mirror%/}"

if [[ "$dry_run" != "1" && "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo --preserve-env=PATH "$0" \
    --mirror "$mirror" \
    --security-mirror "$security_mirror" \
    ${dry_run:+--dry-run}
fi

rewrite_file() {
  local path="$1"
  local tmp=""
  local backup=""

  [[ -f "$path" ]] || return 0
  if ! grep -Eq '(archive\.ubuntu\.com/ubuntu|security\.ubuntu\.com/ubuntu|ports\.ubuntu\.com/ubuntu-ports)' "$path"; then
    return 0
  fi

  tmp="$(mktemp)"
  sed -E \
    -e "s#https?://([A-Za-z0-9.-]+\.)?archive\.ubuntu\.com/ubuntu/?#${mirror}#g" \
    -e "s#https?://security\.ubuntu\.com/ubuntu/?#${security_mirror}#g" \
    -e "s#https?://ports\.ubuntu\.com/ubuntu-ports/?#${mirror}#g" \
    "$path" > "$tmp"

  if cmp -s "$path" "$tmp"; then
    rm -f "$tmp"
    return 0
  fi

  echo "[swarm_core_set_ubuntu_apt_mirror] Updating $path"
  if [[ "$dry_run" == "1" ]]; then
    diff -u "$path" "$tmp" || true
    rm -f "$tmp"
    return 0
  fi

  backup="${path}.PRE_SWARM_MIRROR_$(date +%Y%m%d_%H%M%S)"
  cp -a "$path" "$backup"
  cat "$tmp" > "$path"
  rm -f "$tmp"
  echo "[swarm_core_set_ubuntu_apt_mirror] Backup: $backup"
}

rewrite_file /etc/apt/sources.list
for source_path in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [[ -f "$source_path" ]] || continue
  rewrite_file "$source_path"
done

echo "[swarm_core_set_ubuntu_apt_mirror] Ubuntu apt mirror set to: $mirror"
echo "[swarm_core_set_ubuntu_apt_mirror] Ubuntu security mirror set to: $security_mirror"

if [[ "$dry_run" != "1" ]]; then
  apt-get \
    -o DPkg::Lock::Timeout=120 \
    -o Acquire::Retries="${SWARM_APT_RETRIES:-1}" \
    -o Acquire::http::Timeout="${SWARM_APT_HTTP_TIMEOUT:-15}" \
    -o Acquire::https::Timeout="${SWARM_APT_HTTP_TIMEOUT:-15}" \
    update
fi
