from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_machine_yields_terminal_to_dependency_subprogress():
    script = (CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh").read_text(encoding="utf-8")

    assert "run_bootstrap_step_with_subprogress()" in script
    assert "bootstrap_progress_cleanup" in script
    assert "bootstrap_progress_init" in script
    assert 'run_bootstrap_step_with_subprogress 55 "Installing dependencies"' in script
