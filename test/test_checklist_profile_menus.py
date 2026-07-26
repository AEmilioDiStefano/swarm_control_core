import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


CORE_ROOT = Path(__file__).resolve().parents[1]
NEW_ROBOT = CORE_ROOT / "scripts" / "swarm_core_new_robot.sh"
INTERFACES_FILE = CORE_ROOT / "config" / "control_interfaces.yaml"


def _fake_ssh_key(tmp_path):
    # CI containers may lack ssh-keygen; the checklist only needs the key
    # files to exist and prints the .pub contents verbatim.
    key = tmp_path / "id_ed25519"
    key.write_text("dummy private key\n")
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAATESTKEY test@ci\n")
    return key


def _run_checklist(user_input, key_path, env=None, timeout=60):
    env_prefix = " ".join(f'{k}="{v}"' for k, v in (env or {}).items())
    inner = (
        f'env {env_prefix} "{NEW_ROBOT}" --imager-checklist '
        f'--ssh-private-key "{key_path}"'
    ).replace("env  ", "env ").replace("env  ", "")
    return subprocess.run(
        ["script", "-qec", inner, "/dev/null"],
        input=user_input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.skipif(shutil.which("script") is None, reason="script(1) not available")
def test_checklist_menus_come_from_catalogs_and_filter_by_type(tmp_path):
    result = _run_checklist("rover1\nstation1\n2\n2\n", _fake_ssh_key(tmp_path))
    # mecanum type chosen -> only mecanum-compatible interfaces offered
    assert "mecanum_drive" in result.stdout
    assert "mecanum_l298n_2" in result.stdout
    assert "--control-type mecanum_drive" in result.stdout
    assert "--control-interface" in result.stdout
    # a diff-only interface must not appear in the mecanum menu section
    menu_after_type = result.stdout.split("--control-type")[0].split("hardware interface")[-1]
    assert "4wheel_diff_l298n_1" not in menu_after_type


@pytest.mark.skipif(shutil.which("script") is None, reason="script(1) not available")
def test_added_interface_appears_as_choice_end_to_end(tmp_path):
    """Add an interface to the catalog -> it is offered -> it lands in the command."""
    data = yaml.safe_load(INTERFACES_FILE.read_text())
    root = data.get("control_interfaces", data)
    root["hover_thrust_x1"] = {
        "compatible_control_types": ["diff_drive"],
        "backend": "test_only",
    }
    fake = tmp_path / "control_interfaces.yaml"
    fake.write_text(yaml.safe_dump(data, sort_keys=False))
    diff_count = sum(
        1
        for entry in root.values()
        if isinstance(entry, dict)
        and "diff_drive" in (entry.get("compatible_control_types") or [])
    )

    result = _run_checklist(
        f"rover2\nstation2\n1\n{diff_count}\n",
        _fake_ssh_key(tmp_path),
        env={"SWARM_CORE_CONTROL_INTERFACES_FILE": str(fake)},
    )
    assert "hover_thrust_x1" in result.stdout
    assert "--control-interface hover_thrust_x1" in result.stdout


@pytest.mark.skipif(shutil.which("script") is None, reason="script(1) not available")
def test_checklist_fails_fast_when_input_closes_mid_menu(tmp_path):
    """A drained terminal must abort with a clear error, never loop forever."""
    result = _run_checklist("rover3\nstation3\n99\n", _fake_ssh_key(tmp_path), timeout=30)
    assert "Input closed" in result.stdout or "Input closed" in result.stderr
