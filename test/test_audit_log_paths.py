#!/usr/bin/env python3
"""
Audit sink location gate.

Audit JSONL records are traceability evidence: they must default to a durable
config-owned directory, honor the directory env override, and never fall back
to world-readable, reboot-volatile /tmp. A source scan keeps hardcoded /tmp
sinks from ever coming back into runtime modules.
"""

from pathlib import Path

from swarm_control_core.path_defaults import default_audit_log_path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "swarm_control_core"


def test_default_audit_path_is_durable_not_tmp(monkeypatch, tmp_path):
    """Default resolves under the user state dir, not /tmp, and creates it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SWARM_CORE_AUDIT_LOG_DIR", raising=False)
    resolved = Path(default_audit_log_path("robot_x_audit.jsonl"))
    # (tmp_path itself lives under /tmp, so the invariant proven here is the
    # HOME-relative state-dir layout; the source-scan test below guards the
    # literal-/tmp regression.)
    expected = tmp_path / ".local" / "state" / "swarm_control_core" / "audit"
    assert resolved == expected / "robot_x_audit.jsonl"
    assert resolved.parent.is_dir()


def test_env_dir_override_wins(monkeypatch, tmp_path):
    """SWARM_CORE_AUDIT_LOG_DIR redirects the sink directory and creates it."""
    target = tmp_path / "audit_override"
    monkeypatch.setenv("SWARM_CORE_AUDIT_LOG_DIR", str(target))
    resolved = Path(default_audit_log_path("teleop_audit.jsonl"))
    assert resolved == target / "teleop_audit.jsonl"
    assert target.is_dir()


def test_runtime_modules_contain_no_tmp_literals():
    """No runtime module may hardcode a /tmp path (audit sinks or otherwise)."""
    offenders = []
    for py_path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in py_path.parts:
            continue
        text = py_path.read_text(encoding="utf-8", errors="replace")
        if '"/tmp' in text or "'/tmp" in text:
            offenders.append(str(py_path.relative_to(PACKAGE_ROOT)))
    assert not offenders, (
        f"Hardcoded /tmp path literals in runtime modules: {offenders}"
    )
