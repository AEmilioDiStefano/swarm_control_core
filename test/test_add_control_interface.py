from pathlib import Path

from swarm_control_core.add_control_interface import main as add_control_interface_main


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_add_control_interface_appends_profile_and_wiring_doc(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    package_root = workspace / "src" / "swarm_control_core"
    _write(
        package_root / "config" / "control_types.yaml",
        """schema_version: "1.0"
control_types:
  mecanum_drive:
    type: omni
    params: {}
""",
    )
    _write(
        package_root / "config" / "control_interfaces.yaml",
        """# keep me
schema_version: "1.0"
defaults: {}
control_interfaces: {}
""",
    )

    rc = add_control_interface_main(
        [
            "--workspace",
            str(workspace),
            "--name",
            "dual_test_mecanum",
            "--compatible-control-types",
            "mecanum_drive",
            "--wheel-layout",
            "four_wheel",
            "--controller-model",
            "TEST",
            "--controller-count",
            "2",
            "--gpio",
            "fl_pwm=12",
            "--gpio",
            "fl_in1=5",
            "--gpio",
            "fl_in2=6",
            "--gpio",
            "fr_pwm=13",
            "--gpio",
            "fr_in1=16",
            "--gpio",
            "fr_in2=19",
            "--gpio",
            "rl_pwm=18",
            "--gpio",
            "rl_in1=20",
            "--gpio",
            "rl_in2=21",
            "--gpio",
            "rr_pwm=26",
            "--gpio",
            "rr_in1=23",
            "--gpio",
            "rr_in2=24",
            "--generate-wiring-doc",
        ]
    )

    assert rc == 0
    config_text = (package_root / "config" / "control_interfaces.yaml").read_text(encoding="utf-8")
    assert "# keep me" in config_text
    assert "dual_test_mecanum:" in config_text
    assert (package_root / "DOCS" / "GPIO" / "GPIO_for_dual_test_mecanum.md").exists()
