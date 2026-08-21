#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  swarm_core_prepare_robot_checkout.sh <workspace> <repo-url> <branch> <commit>

Prepare the managed robot checkout at <workspace>/src/swarm_control_core.

An incomplete, corrupt, wrong-origin, or dirty checkout is never deleted. It
is moved to a timestamped .recovery.* path before a clean checkout is made.
The resulting checkout is detached at the exact published commit supplied by
the control machine, which makes interrupted onboarding safe to rerun.
USAGE
}

log() {
  printf '[swarm_core_prepare_robot_checkout] %s\n' "$*" >&2
}

fail() {
  printf '[swarm_core_prepare_robot_checkout] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 4 ]] || { usage >&2; exit 2; }

workspace="$1"
repo_url="$2"
repo_ref="$3"
repo_commit="$4"

[[ -n "$workspace" && "$workspace" == /* ]] \
  || fail "workspace must be an absolute path"
[[ -n "$repo_url" ]] || fail "repo URL cannot be empty"
git check-ref-format --branch "$repo_ref" >/dev/null 2>&1 \
  || fail "invalid branch: ${repo_ref}"
[[ "$repo_commit" =~ ^[0-9a-f]{40}$ ]] \
  || fail "commit must be a full lowercase Git object ID"

install -d "${workspace}/src"
remote_pkg="${workspace}/src/swarm_control_core"

checkout_needs_quarantine="0"
quarantine_reason=""
if [[ -e "$remote_pkg" ]]; then
  if ! git -C "$remote_pkg" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    checkout_needs_quarantine="1"
    quarantine_reason="incomplete or corrupt"
  elif [[ "$(git -C "$remote_pkg" remote get-url origin 2>/dev/null || true)" != "$repo_url" ]]; then
    checkout_needs_quarantine="1"
    quarantine_reason="wrong origin"
  elif [[ -n "$(git -C "$remote_pkg" status --porcelain --untracked-files=normal)" ]]; then
    checkout_needs_quarantine="1"
    quarantine_reason="dirty"
  fi
fi

if [[ "$checkout_needs_quarantine" == "1" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup="${remote_pkg}.recovery.${stamp}"
  suffix="0"
  while [[ -e "$backup" ]]; do
    suffix=$((suffix + 1))
    backup="${remote_pkg}.recovery.${stamp}.${suffix}"
  done
  mv "$remote_pkg" "$backup"
  log "Preserved ${quarantine_reason} checkout at ${backup}"
fi

if [[ ! -d "${remote_pkg}/.git" ]]; then
  git clone --no-checkout --branch "$repo_ref" --single-branch \
    "$repo_url" "$remote_pkg"
fi

git -C "$remote_pkg" fetch --no-tags origin "refs/heads/${repo_ref}"
git -C "$remote_pkg" cat-file -e "${repo_commit}^{commit}"
git -C "$remote_pkg" checkout --detach "$repo_commit"

[[ -z "$(git -C "$remote_pkg" status --porcelain --untracked-files=normal)" ]] \
  || fail "checkout became dirty while selecting the pinned commit"
[[ "$(git -C "$remote_pkg" rev-parse HEAD)" == "$repo_commit" ]] \
  || fail "checkout does not match the pinned commit"

log "Ready at ${remote_pkg}: ${repo_ref}@${repo_commit:0:12}"
