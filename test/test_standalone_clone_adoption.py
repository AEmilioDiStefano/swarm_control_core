import os
import subprocess
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]


def test_swarmc_setup_adopts_standalone_clone_without_copying(tmp_path):
    standalone = tmp_path / "standalone" / "swarm_control_core"
    scripts = standalone / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "swarmc").write_text(
        (CORE_ROOT / "scripts" / "swarmc").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (scripts / "swarmc").chmod(0o755)
    workspace = tmp_path / "workspace"
    fake_bootstrap = scripts / "swarm_core_bootstrap_machine.sh"
    fake_bootstrap.write_text(
        "#!/usr/bin/env bash\nprintf 'bootstrap:%s\\n' \"$*\"\n", encoding="utf-8"
    )
    fake_bootstrap.chmod(0o755)

    result = subprocess.run(
        [str(standalone / "scripts" / "swarmc"), "setup", "--role", "control", "--skip-build"],
        env={**os.environ, "HOME": str(tmp_path), "SWARM_CORE_WORKSPACE_ROOT": str(workspace)},
        text=True,
        capture_output=True,
        check=True,
    )

    adopted = workspace / "src" / "swarm_control_core"
    assert adopted.is_symlink()
    assert adopted.resolve() == standalone.resolve()
    assert f"--workspace {workspace}" in result.stdout
    assert "Adopted existing checkout" in result.stderr


def test_first_contact_forwards_selected_workspace_to_adopted_swarmc():
    script = (CORE_ROOT / "scripts" / "swarm_core_first_contact.sh").read_text(
        encoding="utf-8"
    )
    assert 'SWARM_CORE_WORKSPACE_ROOT="$workspace"' in script
    assert '"${pkg_dir}/scripts/swarmc" setup' in script


def test_quickstart_reset_restores_structural_workspace_locator():
    script = (CORE_ROOT / "scripts" / "lib" / "swarm_core_quickstart_common.sh").read_text(
        encoding="utf-8"
    )
    reset_call = script.index('source "$reset_script"')
    restore_call = script.index('swarm_core_qs_prepare_workspace_env "$ws"', reset_call)
    assert restore_call > reset_call
