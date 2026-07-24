# Git Workflow (Protected `main` + Feature Branches + PR Publish)

`main` is the stable integration branch. Work happens on
`feature/YYYYMMDD-<topic>` branches; `main` is only advanced by GitHub-owned
merges of pull requests that pass the required CI check. Robots and other
consumer machines stay pull-only: they fast-forward `main` (or pin a release
tag) and rebuild — that part of the workflow is unchanged from before.

If this workspace also contains `swarm_control_pro`, use the paired workflow
in the pro package docs (`swarm_git.sh`) so both repos move together; the
commands below are for core-only work.

One-time prerequisites (per developer machine):

- GitHub CLI installed and authenticated: verify with
  `gh auth status --hostname github.com`
- One-time repo setup (maintainer, on GitHub): enable branch protection on
  `main` — require the `build-and-test` check (from
  `.github/workflows/ci.yml`), require branches up to date, disallow direct
  pushes. Until protection is enabled the scripts still work; protection is
  what makes the rules mechanical.

Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `chore:`, ...). The scripts reject the legacy
`"updates"` message.

Every consumer sync ends with an explicit rebuild on purpose: these are ROS 2
packages, so never trust runtime behavior after a `git pull` until the overlay
is rebuilt and re-sourced.

# Direct Run Path

## Step 0: Bootstrap Workspace Shell

### CONTROL MACHINE / ROBOT(S):

```bash
SWARM_CORE_BOOTSTRAP_ENV="$(find "${SWARM_SEARCH_ROOT:-$HOME}" -maxdepth 10 -type f -path "*/src/swarm_control_core/scripts/swarm_core_bootstrap_env.sh" 2>/dev/null | sort | head -n1)"
if [[ -z "${SWARM_CORE_BOOTSTRAP_ENV:-}" ]]; then
  echo "[FAIL] Could not locate swarm_control_core terminal bootstrap helper under ${SWARM_SEARCH_ROOT:-$HOME}." >&2
else
  source "$SWARM_CORE_BOOTSTRAP_ENV" --interactive
  unset SWARM_CORE_BOOTSTRAP_ENV
fi
```

This bootstrap exports `WS`, `WS_DEV`, `SC`, and `SWARM_CORE_WORKSPACE_ROOT`.

## Step 1: Start (or Resume) a Feature Branch

Never edit on `main`. Check where you are, then start a branch.

### CONTROL MACHINE:

```bash
git -C "$SC" branch --show-current
"$SC/scripts/swarm_core_git.sh" start
```

Expected: the script syncs `main` and leaves you on
`feature/YYYYMMDD-<topic>`.

### IF the printed branch is already a feature/* branch you want to continue

Stay on it and continue working; no new branch is needed. Return to
[Step 2](#step-2).

### IF the working tree is dirty on main

Go to [Fix Step 1.1](#ref-1-1), then return to [Step 1](#step-1).

<a id="step-2"></a>
## Step 2: Save Work (Backup Push)

Run as often as you like; it refuses to run on `main`.

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_git.sh" save
```

Expected: a Conventional Commit on your feature branch, pushed to `origin` as
a backup. Nothing touches `main`.

## Step 3: Publish to `main`

One command: local gate (build + tests + release gate) -> push -> PR ->
required checks -> GitHub merge -> fast-forward sync of local `main` -> offer
to start the next branch.

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_git.sh" publish
```

Expected final lines: `published feature/... into main.`

### IF publish stops because origin/main has new commits

Go to [Fix Step 3.1](#ref-3-1), then return to [Step 3](#step-3).

### IF publish stops on gh authentication

Go to [Fix Step 3.2](#ref-3-2), then return to [Step 3](#step-3).

### IF the required checks fail on the PR

Go to [Fix Step 3.3](#ref-3-3), then return to [Step 3](#step-3).

## Step 4: Update Consumer Machines and Robots

Use this on every other machine (control machines, robots) to consume the new
`main`. This is the only step robots ever run.

### CONTROL MACHINE / ROBOT(S):

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

Expected: fast-forward pull, clean rebuild, overlay re-sourced. If the robot
runs the managed service, restart it (or use the pro
`swarm_robot_admin.sh service-sync` flow, which does all of this per robot).

### IF you want a robot pinned to a known-good release instead of main tip

Go to [Alternative Step 4.1](#ref-4-1), then return to [Step 4](#step-4).

## Step 5: Tag a Release

After a set of published changes is validated, cut an annotated tag from
clean, synced `main`.

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_git.sh" tag
```

Expected: `tagged vX.Y.Z.` — tags replace the old `last_save`/`last_stable`
snapshot branches.

# Alternative/Debug/Fix Reference

<a id="ref-1-1"></a>
## Fix Step 1.1: Dirty Working Tree on `main`

Uncommitted work on `main` must move to a feature branch before anything else:

### CONTROL MACHINE:

```bash
cd "$SC"
git switch -c "feature/$(date +%Y%m%d)-rescued-work"
"$SC/scripts/swarm_core_git.sh" save
```

Then return to [Step 1](#step-1) (your work is now safe on a feature branch).

<a id="ref-3-1"></a>
## Fix Step 3.1: Feature Branch Is Behind `origin/main`

Someone published while you worked. Bring their commits into your branch:

### CONTROL MACHINE:

```bash
cd "$SC"
git fetch origin --prune
git merge --no-edit origin/main
```

Resolve any conflicts, run `save`, then return to [Step 3](#step-3).

<a id="ref-3-2"></a>
## Fix Step 3.2: GitHub CLI Not Authenticated

### CONTROL MACHINE:

```bash
gh auth login
gh auth status --hostname github.com
```

Then return to [Step 3](#step-3).

<a id="ref-3-3"></a>
## Fix Step 3.3: Required Checks Failed on the PR

Open the failing run, fix the reported build/test/release-gate problem
locally, then:

### CONTROL MACHINE:

```bash
"$SC/scripts/swarm_core_git.sh" save
"$SC/scripts/swarm_core_git.sh" publish
```

Then return to [Step 3](#step-3).

<a id="ref-4-1"></a>
## Alternative Step 4.1: Pin a Robot to a Release Tag

### ROBOT(S):

```bash
cd "$WS/src/swarm_control_core"
git fetch origin --prune --tags
git switch --detach vX.Y.Z
```

Then rebuild exactly as in [Step 4](#step-4). To return to tracking `main`,
run `git switch main` and repeat [Step 4](#step-4).

## Retired Flows (Do Not Use)

- Direct pushes to `main` (`git push origin main` from a working branch):
  retired — GitHub owns every merge into `main` through the publish flow.
- Mirror-all-branches force push
  (`git push --prune --force-with-lease origin 'refs/heads/*:refs/heads/*'`):
  retired — it could delete collaborators' remote branches.
- `git commit -m "updates"`: retired — the scripts reject it; write
  Conventional Commits.
- `last_save` / `last_stable` snapshot branches: replaced by annotated
  release tags ([Step 5](#step-5)).
