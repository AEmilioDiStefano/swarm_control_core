#!/usr/bin/env bash
# swarm_core_git.sh — protected-main git workflow for swarm_control_core.
#
# Subcommands (all accept --dry-run to print actions without mutating):
#   start   [topic]    new feature/YYYYMMDD-<topic> branch from synced main
#   save    [message]  commit (Conventional Commits enforced) + backup-push
#   publish            local gate -> push -> PR -> wait checks -> GitHub merge
#                      -> ff-only sync main -> optionally start next branch
#   tag     [vX.Y.Z]   annotated release tag from clean, synced main
#
# Modeled on the NeuroMux protected-main publisher pipeline.
# See DOCS/git_workflow.md for the operator guide. Direct pushes to main are
# retired; GitHub owns every merge into main once branch protection is on.
#
# Env overrides (for non-interactive use):
#   SWARM_GIT_TOPIC            topic for `start` / the post-publish next branch
#   SWARM_GIT_COMMIT_MESSAGE   commit message for `save`
#   SWARM_GIT_SKIP_GATE=1      skip the local build/test gate in `publish`
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_ROOT="$(cd "$REPO_ROOT/../.." && pwd)"
DRY_RUN=0

note() { printf '[swarm_core_git] %s\n' "$*"; }
fail() { printf '[swarm_core_git] ERROR: %s\n' "$*" >&2; exit 1; }

run() {
  printf '+ %s\n' "$*"
  if [[ "$DRY_RUN" != 1 ]]; then
    "$@"
  fi
}

current_branch() { git -C "$REPO_ROOT" branch --show-current; }

ensure_repo() {
  git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "not a git repository: $REPO_ROOT"
}

ensure_not_main() {
  local branch
  branch="$(current_branch)"
  [[ "$branch" != "main" ]] \
    || fail "refusing to $1 on main. Run: $0 start   (work happens on feature/* branches)"
}

ensure_clean() {
  [[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] \
    || fail "working tree is dirty. Commit it first ($0 save on a feature branch) or stash it."
}

ensure_gh() {
  command -v gh >/dev/null 2>&1 \
    || fail "GitHub CLI (gh) is required. Install it, then: gh auth login"
  gh auth status --hostname github.com >/dev/null 2>&1 \
    || fail "gh is not authenticated. Run: gh auth login"
}

normalize_topic() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

prompt_value() {
  # $1=env value  $2=prompt text  -> echoes result
  local value="$1"
  if [[ -z "$value" ]]; then
    read -r -p "$2" value
  fi
  printf '%s' "$value"
}

conventional_check() {
  local msg="$1"
  [[ ! "$msg" =~ ^updates?$ ]] \
    || fail "commit message 'updates' is retired. Describe the change (e.g. 'fix: ...')."
  [[ "$msg" =~ ^(feat|fix|docs|test|refactor|chore|perf|ci|build|style|revert)(\([a-zA-Z0-9_-]+\))?\!?:\ .+ ]] \
    || fail "commit message must follow Conventional Commits, e.g. 'feat: add wheel test presets' (got: '$msg')"
}

cmd_start() {
  ensure_repo
  ensure_clean
  local topic
  topic="$(prompt_value "${1:-${SWARM_GIT_TOPIC:-}}" "Feature topic (e.g. 'onboarding wizard'): ")"
  topic="$(normalize_topic "$topic")"
  [[ -n "$topic" ]] || fail "empty topic."
  local branch
  branch="feature/$(date +%Y%m%d)-$topic"
  run git -C "$REPO_ROOT" switch main
  run git -C "$REPO_ROOT" pull --ff-only origin main
  run git -C "$REPO_ROOT" switch -c "$branch"
  note "now on $branch. Next: edit, then '$0 save', then '$0 publish'."
}

cmd_save() {
  ensure_repo
  ensure_not_main "save"
  if [[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    note "nothing to commit."
  else
    git -C "$REPO_ROOT" status --short
    local msg
    msg="$(prompt_value "${1:-${SWARM_GIT_COMMIT_MESSAGE:-}}" "Conventional commit message: ")"
    conventional_check "$msg"
    run git -C "$REPO_ROOT" add -A
    run git -C "$REPO_ROOT" commit -m "$msg"
  fi
  run git -C "$REPO_ROOT" push -u origin "$(current_branch)"
}

local_gate() {
  if [[ "${SWARM_GIT_SKIP_GATE:-0}" == 1 ]]; then
    note "SWARM_GIT_SKIP_GATE=1 — skipping local gate (CI still gates the merge)."
    return 0
  fi
  if [[ "$DRY_RUN" == 1 ]]; then
    note "(dry-run) would run: colcon build + pytest + release gate"
    return 0
  fi
  note "local gate: colcon build + pytest + release gate"
  (
    cd "$WS_ROOT"
    set +u
    # shellcheck disable=SC1091
    source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
    colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
    # shellcheck disable=SC1091
    source "$WS_ROOT/install/setup.bash"
    set -u
    cd "$REPO_ROOT"
    python3 -m pytest -q test
    ./scripts/swarm_core_release_gate.sh
  )
}

cmd_publish() {
  ensure_repo
  ensure_not_main "publish"
  ensure_gh
  local branch head
  branch="$(current_branch)"

  # Commit anything outstanding through the same save flow.
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    cmd_save
  fi

  local_gate

  run git -C "$REPO_ROOT" push -u origin "$branch"
  run git -C "$REPO_ROOT" fetch origin --prune

  if [[ "$DRY_RUN" != 1 ]] && ! git -C "$REPO_ROOT" merge-base --is-ancestor origin/main HEAD; then
    fail "origin/main has commits not in $branch. Run: git merge --no-edit origin/main  then re-run publish."
  fi

  head="$(git -C "$REPO_ROOT" rev-parse HEAD)"

  if [[ "$DRY_RUN" == 1 ]]; then
    note "(dry-run) would: create/reuse PR for $branch -> main, wait for required checks,"
    note "(dry-run) merge with 'gh pr merge --merge --match-head-commit $head',"
    note "(dry-run) ff-only sync local main, then offer to start the next feature branch."
    return 0
  fi

  local pr_number
  pr_number="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number' 2>/dev/null || true)"
  if [[ -z "$pr_number" || "$pr_number" == "null" ]]; then
    run gh pr create --base main --head "$branch" \
      --title "$(git -C "$REPO_ROOT" log -1 --format=%s)" \
      --body "Published via swarm_core_git.sh (protected-main workflow)."
  else
    note "reusing open PR #$pr_number for $branch."
  fi
  gh pr ready "$branch" >/dev/null 2>&1 || true

  note "waiting for required checks..."
  run gh pr checks "$branch" --watch

  run gh pr merge "$branch" --merge --match-head-commit "$head"

  run git -C "$REPO_ROOT" switch main
  run git -C "$REPO_ROOT" pull --ff-only origin main
  git -C "$REPO_ROOT" merge-base --is-ancestor "$head" HEAD \
    || fail "merged commit $head not found in synced main; inspect before continuing."
  note "published $branch into main."

  local next_topic="${SWARM_GIT_TOPIC:-}"
  if [[ -z "$next_topic" ]]; then
    read -r -p "Next feature topic (empty to stay on main): " next_topic
  fi
  if [[ -n "$next_topic" ]]; then
    cmd_start "$next_topic"
  fi
}

cmd_tag() {
  ensure_repo
  ensure_clean
  [[ "$(current_branch)" == "main" ]] || fail "tags are cut from main only."
  run git -C "$REPO_ROOT" fetch origin --prune
  if [[ "$DRY_RUN" != 1 ]]; then
    [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$(git -C "$REPO_ROOT" rev-parse origin/main)" ]] \
      || fail "local main is not synced with origin/main. Run: git pull --ff-only origin main"
  fi
  local version
  version="$(prompt_value "${1:-}" "Release version (vX.Y.Z): ")"
  [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version must match vX.Y.Z (got: '$version')"
  run git -C "$REPO_ROOT" tag -a "$version" -m "swarm_control_core $version"
  run git -C "$REPO_ROOT" push origin "$version"
  note "tagged $version. Robots can pin with: git switch --detach $version"
}

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
  local args=()
  for arg in "$@"; do
    case "$arg" in
      --dry-run) DRY_RUN=1 ;;
      -h|--help) usage; exit 0 ;;
      *) args+=("$arg") ;;
    esac
  done
  set -- "${args[@]:-}"
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    start)   cmd_start "$@" ;;
    save)    cmd_save "$@" ;;
    publish) cmd_publish "$@" ;;
    tag)     cmd_tag "$@" ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
