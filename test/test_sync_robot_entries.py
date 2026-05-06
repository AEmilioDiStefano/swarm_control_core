from unittest.mock import patch

from pathlib import Path

from swarm_control_core.sync_robot_entries import (
    _detect_likely_local_robot_source,
    _merge_imported_robot_entry,
    _parse_source_spec,
    _select_robot_entry_from_registry,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_source_spec_supports_optional_robot_name() -> None:
    assert _parse_source_spec("robot3=robot3@legion3.local") == ("robot3", "robot3@legion3.local")
    assert _parse_source_spec("robot3@legion3.local") == ("", "robot3@legion3.local")


def test_select_robot_entry_prefers_exact_ssh_target_match() -> None:
    registry = {
        "robots": {
            "robot3": {
                "ssh_target": "robot3@legion3.local",
                "control_type": "diff_drive",
                "control_interface": "4wheel_diff_l298n_1",
            },
            "other": {
                "ssh_target": "other@other-host.local",
                "control_type": "diff_drive",
                "control_interface": "4wheel_diff_tb6612fng_2",
            },
        }
    }

    robot_name, entry = _select_robot_entry_from_registry(
        registry,
        used_target="robot3@legion3.local",
        remote_user="robot3",
        remote_host="legion3",
    )

    assert robot_name == "robot3"
    assert entry["control_interface"] == "4wheel_diff_l298n_1"


def test_merge_imported_robot_entry_updates_runtime_without_dirtying_repo_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot3:
    ssh_target: robot3@legion3.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )

    repo_state, runtime_results = _merge_imported_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        robot_name="robot_new",
        entry={
            "ssh_target": "robot_new@robot-new.local",
            "control_type": "mecanum_drive",
            "control_interface": "mecanum_tb6612fng_2",
        },
    )

    assert repo_state == "missing_entry"
    assert runtime_results[0]["state"] == "missing_file"

    repo_text = repo_profiles.read_text(encoding="utf-8")
    assert "robot_new:" not in repo_text

    runtime_text = runtime_profiles.read_text(encoding="utf-8")
    assert "robot_new:" in runtime_text
    assert "ssh_target: robot_new@robot-new.local" in runtime_text


def test_merge_imported_robot_entry_can_update_source_baseline_when_requested(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots: {}
""",
    )

    repo_state, runtime_results = _merge_imported_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        robot_name="robot_new",
        entry={
            "ssh_target": "robot_new@robot-new.local",
            "control_type": "mecanum_drive",
            "control_interface": "mecanum_l298n_2",
        },
        update_source_baseline=True,
    )

    assert repo_state == "missing_entry"
    assert runtime_results[0]["state"] == "missing_file"
    assert "robot_new:" in repo_profiles.read_text(encoding="utf-8")
    assert "robot_new:" in runtime_profiles.read_text(encoding="utf-8")


def test_detect_likely_local_robot_source_from_runtime_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots: {}
""",
    )
    _write(
        runtime_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot1:
    ssh_target: robot1@legion1.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )

    with patch("swarm_control_core.sync_robot_entries.getpass.getuser", return_value="robot1"):
        with patch("swarm_control_core.sync_robot_entries.socket.gethostname", return_value="legion1"):
            detected = _detect_likely_local_robot_source(
                repo_profiles_path=repo_profiles,
                runtime_profiles_paths=[runtime_profiles],
            )

    assert detected == ("robot1", "robot1@legion1.local")


def test_sync_command_refreshes_runtime_core_profiles_and_validates_registry() -> None:
    source = (Path(__file__).resolve().parents[1] / "swarm_control_core" / "sync_robot_entries.py").read_text(
        encoding="utf-8"
    )

    assert "refresh_runtime_core_profiles(workspace_root, runtime_profiles_paths)" in source
    assert "load_profile_registry(str(runtime_path))" in source
    assert "Control-machine trusted robot registry load check OK" in source
