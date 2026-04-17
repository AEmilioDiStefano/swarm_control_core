import os
import shutil
import subprocess
from pathlib import Path

import pytest


CORE_ROOT = Path(__file__).resolve().parents[1]
SETUP_BOOTSTRAP = CORE_ROOT / "scripts" / "swarm_core_setup_bootstrap.sh"


def run_cmd(cmd, cwd=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def create_origin_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin_repo"
    scripts_dir = origin / "scripts"
    scripts_dir.mkdir(parents=True)

    workspace_bootstrap = scripts_dir / "swarm_core_workspace_bootstrap.sh"
    workspace_bootstrap.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

workspace=""
emit_shell="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      shift
      workspace="${1:-}"
      ;;
    --emit-shell)
      emit_shell="1"
      ;;
    --non-interactive|--interactive)
      ;;
    *)
      ;;
  esac
  shift
done

pkg_dir="${workspace%/}/src/swarm_control_core"

if [[ "$emit_shell" == "1" ]]; then
  printf 'export WS=%q\\n' "$workspace"
  printf 'export SC=%q\\n' "$pkg_dir"
  printf 'export SWARM_CORE_WORKSPACE_ROOT=%q\\n' "$workspace"
  printf 'export WS_DEV=%q\\n' "$workspace"
  printf 'export SWARM_CORE_WORKSPACE_NAME=%q\\n' "$(basename "$workspace")"
else
  printf '[stub] workspace=%s\\n' "$workspace"
fi
""",
        encoding="utf-8",
    )
    workspace_bootstrap.chmod(0o755)

    run_cmd(["git", "init"], cwd=origin)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=origin)
    run_cmd(["git", "config", "user.name", "Test User"], cwd=origin)
    run_cmd(["git", "add", "."], cwd=origin)
    run_cmd(["git", "commit", "-m", "init"], cwd=origin)
    return origin


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for bootstrap script tests")
def test_setup_bootstrap_creates_missing_workspace_and_checkout(tmp_path: Path):
    origin = create_origin_repo(tmp_path)
    workspace = tmp_path / "ros2_ws_dev"

    result = run_cmd(
        [
            "bash",
            str(SETUP_BOOTSTRAP),
            "--workspace",
            str(workspace),
            "--repo-url",
            str(origin),
            "--emit-shell",
        ],
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )

    assert (workspace / "src" / "swarm_control_core" / ".git").exists()
    assert f"export WS={workspace}" in result.stdout
    assert f"export SC={workspace / 'src' / 'swarm_control_core'}" in result.stdout
    assert "Bootstrap completed at" in result.stderr
    assert "Cloned swarm_control_core into" in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for bootstrap script tests")
def test_setup_bootstrap_reports_noop_when_workspace_is_already_complete(tmp_path: Path):
    origin = create_origin_repo(tmp_path)
    workspace = tmp_path / "ros2_ws_dev"
    env = {**os.environ, "HOME": str(tmp_path / "home")}

    run_cmd(
        [
            "bash",
            str(SETUP_BOOTSTRAP),
            "--workspace",
            str(workspace),
            "--repo-url",
            str(origin),
            "--emit-shell",
        ],
        env=env,
    )

    result = run_cmd(
        [
            "bash",
            str(SETUP_BOOTSTRAP),
            "--workspace",
            str(workspace),
            "--repo-url",
            str(origin),
            "--emit-shell",
        ],
        env=env,
    )

    assert "Bootstrap already complete at" in result.stderr
    assert "No workspace checkout changes were needed." in result.stderr
    assert "Cloned swarm_control_core into" not in result.stderr
