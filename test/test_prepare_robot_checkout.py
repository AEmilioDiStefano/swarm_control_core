import subprocess
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
PREPARE = CORE_ROOT / "scripts" / "swarm_core_prepare_robot_checkout.sh"


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def _origin_with_commit(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    _run(["git", "init", "-b", "main"], cwd=source)
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=source)
    _run(["git", "config", "user.name", "Checkout recovery test"], cwd=source)
    (source / "README.md").write_text("published\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=source)
    _run(["git", "commit", "-m", "published"], cwd=source)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=source).stdout.strip()

    origin = tmp_path / "origin.git"
    _run(["git", "init", "--bare", str(origin)], cwd=tmp_path)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=source)
    _run(["git", "push", "-u", "origin", "main"], cwd=source)
    return origin, commit


def _prepare(workspace: Path, origin: Path, commit: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [str(PREPARE), str(workspace), str(origin), "main", commit],
        cwd=workspace.parent,
    )


def test_partial_and_dirty_checkouts_are_preserved_and_recovered(tmp_path):
    origin, commit = _origin_with_commit(tmp_path)
    workspace = tmp_path / "robot_ws"
    package = workspace / "src" / "swarm_control_core"
    package.mkdir(parents=True)
    (package / "partial-download.txt").write_text("keep me\n", encoding="utf-8")

    first = _prepare(workspace, origin, commit)
    backups = sorted((workspace / "src").glob("swarm_control_core.recovery.*"))
    assert len(backups) == 1
    assert (backups[0] / "partial-download.txt").read_text(encoding="utf-8") == "keep me\n"
    assert "Preserved incomplete or corrupt checkout" in first.stderr
    assert _run(["git", "rev-parse", "HEAD"], cwd=package).stdout.strip() == commit

    (package / "local-note.txt").write_text("do not destroy\n", encoding="utf-8")
    second = _prepare(workspace, origin, commit)
    backups = sorted((workspace / "src").glob("swarm_control_core.recovery.*"))
    assert len(backups) == 2
    dirty_backup = next(path for path in backups if (path / "local-note.txt").exists())
    assert (dirty_backup / "local-note.txt").read_text(encoding="utf-8") == "do not destroy\n"
    assert "Preserved dirty checkout" in second.stderr
    assert _run(["git", "status", "--porcelain"], cwd=package).stdout == ""
    assert _run(["git", "rev-parse", "HEAD"], cwd=package).stdout.strip() == commit

    before = set((workspace / "src").glob("swarm_control_core.recovery.*"))
    _prepare(workspace, origin, commit)
    after = set((workspace / "src").glob("swarm_control_core.recovery.*"))
    assert after == before, "an already-correct checkout must be a no-op, not another backup"
