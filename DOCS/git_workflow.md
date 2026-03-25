# Git Workflow (`WS` Source Of Truth + Immutable Demo Tags)

Use this workflow from:

```bash
SWARM_CORE_BOOTSTRAP_ENV="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_bootstrap_env.sh" 2>/dev/null | sort | head -n1)"
if [[ -z "${SWARM_CORE_BOOTSTRAP_ENV:-}" ]]; then
  echo "[FAIL] Could not locate swarm_control_core terminal bootstrap helper under ${SWARM_SEARCH_ROOT:-$HOME}." >&2
  return 1 2>/dev/null || exit 1
fi
source "$SWARM_CORE_BOOTSTRAP_ENV" --interactive
unset SWARM_CORE_BOOTSTRAP_ENV

cd "$WS/src/swarm_control_core"
```

This bootstrap exports `WS`, `WS_DEV`, `SC`, and `SWARM_CORE_WORKSPACE_ROOT`.

`swarm_control_core` is the GitHub repo.
`WS` is your active workspace.

If this workspace also contains `swarm_control_pro`, use the paired workflow in the pro package docs so both repos move together.

Every Git command block below ends with an explicit rebuild on purpose. These are ROS 2 packages, so do not stop at `git pull` or tag sync; rebuild the overlay before you trust runtime behavior.

## Model

- Develop in `WS/src/swarm_control_core` (usually `main` + feature branches).
- Publish normal work to `main`.
- For demos, create an immutable tag (`DEMO_REF`) from a known-good commit.
- All machines sync `WS/src/swarm_control_core` to that exact tag.

This replaces the older movable `last_stable` pointer workflow for demo execution.

## 1) Normal Development Push (`main`)

```bash
cd "$WS/src/swarm_control_core"
git switch main
git pull --ff-only origin main
git add -A
git commit -m "updates"
git push origin main

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

## 2) Normal Development Pull (`main`)

Use this on other machines to fast-forward local `main` to GitHub `main`.

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune
git switch main
git pull --ff-only origin main

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

## 3) Create And Publish Demo Snapshot Tag

Use this when you decide "this exact state is demo-stable".

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune --tags
git switch main
git pull --ff-only origin main

# Pick one immutable tag name for this demo run.
export DEMO_REF="demo-$(date +%Y%m%d-%H%M)"
# Optional explicit name:
# export DEMO_REF="demo-2026-03-24-a"

git tag -a "$DEMO_REF" -m "Demo snapshot $DEMO_REF"
git push origin "$DEMO_REF"

git show -s --format='DEMO_REF=%h %d %s' "$DEMO_REF"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

Important:
- Do not force-push demo tags.
- If a tag name is wrong, create a new tag name instead of rewriting the old one.

## 4) Verify Remote Tag Before Demo

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune --tags
git show-ref --verify --quiet "refs/tags/$DEMO_REF"
git ls-remote --tags origin "$DEMO_REF"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

## 5) Sync Workspace To Demo Tag (Any Machine)

Use this to guarantee identical demo code on every machine.

```bash
: "${DEMO_REF:?Set DEMO_REF first}"
cd "$WS/src/swarm_control_core"

git stash push -u -m "pre-demo-sync-$(date +%F-%H%M%S)" || true
git fetch origin --prune --tags
git show-ref --verify --quiet "refs/tags/$DEMO_REF" || {
  echo "[ERROR] Missing tag on this clone: $DEMO_REF" >&2
  exit 1
}

git switch --detach "$DEMO_REF"
git restore --staged --worktree .
git clean -fd

git status --short
git show -s --format='DEMO_REF=%h %d %s' "$DEMO_REF"

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

Expected:
- `git status --short` is empty.
- `HEAD` is detached at `DEMO_REF`.

## 6) Rules

1. Do Git development operations from `WS/src/swarm_control_core`.
2. After demo-tag testing (`git switch --detach "$DEMO_REF"`), switch back before development:

```bash
cd "$WS/src/swarm_control_core"
git switch main
git pull --ff-only origin main

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

3. Keep runtime-generated data (for example camera profiles) outside repo when possible.
4. Rebuild after any Git operation that can change runtime code, even if the diff "looks small":

```bash
cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```

## 7) Optional: Keep Legacy `last_stable` For Backward Compatibility

If older tooling still expects `last_stable`, you may keep updating it as a convenience pointer,
but do not use it as the primary source of demo truth.

```bash
cd "$WS/src/swarm_control_core"
git branch -f last_stable "$DEMO_REF"
git push --force-with-lease origin last_stable:last_stable

cd "$WS"
set +u
source /opt/ros/"${ROS_DISTRO:-jazzy}"/setup.bash
if [ -d "$WS/src/swarm_control_pro" ]; then
  colcon build --base-paths src/swarm_control_core src/swarm_control_pro --packages-up-to swarm_control_pro
else
  colcon build --base-paths src/swarm_control_core --packages-select swarm_control_core
fi
source "$WS/install/setup.bash"
set -u || true
```
