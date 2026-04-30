from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_machine_uses_append_only_progress():
    script = (CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh").read_text(encoding="utf-8")

    assert "run_bootstrap_step_with_subprogress()" in script
    assert 'run_bootstrap_step_with_subprogress 55 "Installing dependencies"' in script
    assert "log \"START ($(" in script
    assert "log \"OK ($(" in script


def test_setup_progress_scripts_do_not_emit_cursor_control_sequences():
    scripts = [
        CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh",
        CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh",
    ]
    forbidden = [
        "\\033",
        "stty size",
        "?25l",
        "?25h",
        "[2K",
        "[1;%",
    ]

    for script_path in scripts:
        text = script_path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{script_path.name} contains cursor-control token {token!r}"
