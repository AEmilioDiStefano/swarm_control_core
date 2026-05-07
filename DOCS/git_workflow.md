# Git Workflow (`WS` Source Of Truth + Branch Sync)

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

Every Git command block below ends with an explicit rebuild on purpose. These are ROS 2 packages, so do not stop at `git pull` or branch sync; rebuild the overlay before you trust runtime behavior.

## Model

- Develop in `WS/src/swarm_control_core` (usually `main` + feature branches).
- Publish normal work to `main`.
- When needed, mirror all local branches to GitHub so the remote branch
  structure matches this workspace.

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

## 3) Mirror All Local Branches To GitHub

Use this when the local branch structure is the source of truth and GitHub
should match it. This pushes every local branch and prunes GitHub branches that
do not exist locally. It does not mirror tags.

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune
echo "[INFO] local branches:"
git for-each-ref --format='  %(refname:short)' refs/heads
git push --prune --force-with-lease origin 'refs/heads/*:refs/heads/*'

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
