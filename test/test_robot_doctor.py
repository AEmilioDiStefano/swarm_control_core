from pathlib import Path

from swarm_control_core.robot_doctor import collect_report


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_robot_doctor_reports_stale_runtime_control_interface(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    config = workspace / "src" / "swarm_control_core" / "config"
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("SWARM_CORE_CONFIG_DIR", str(runtime))

    _write(
        config / "robot_instances.yaml",
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: L298N_diff
robots:
  robot4:
    ssh_target: robot4@legion4.local
    control_type: diff_drive
    control_interface: dual_L298N_diff
""",
    )
    _write(
        config / "control_interfaces.yaml",
        """schema_version: "1.0"
control_interfaces:
  dual_L298N_diff:
    docs:
      wiring: DOCS/GPIO/GPIO_for_differential_DUAL_L298N.md
    gpio: {}
    params: {}
""",
    )
    _write(config / "control_types.yaml", "schema_version: '1.0'\ncontrol_types: {}\n")
    _write(runtime / "robot_instances.yaml", (config / "robot_instances.yaml").read_text(encoding="utf-8"))
    _write(runtime / "control_types.yaml", (config / "control_types.yaml").read_text(encoding="utf-8"))
    _write(runtime / "control_interfaces.yaml", "schema_version: '1.0'\ncontrol_interfaces: {}\n")
    _write(runtime / "camera_profiles.yaml", "schema_version: '1.0'\nprofiles: {}\n")

    report = collect_report(workspace_root=workspace, robot_name="robot4")

    assert report["source_entry_state"] == "present"
    assert report["source_control_interface_state"] == "present"
    assert report["wiring_doc"] == "DOCS/GPIO/GPIO_for_differential_DUAL_L298N.md"
    assert report["camera_profile_state"] == "missing"
    assert report["runtime"][0]["robot_entry"] == "current"
    assert report["runtime"][0]["control_interfaces"] == "stale"
