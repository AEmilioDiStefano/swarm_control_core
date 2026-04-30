#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

from swarm_control_core.drive_profiles import load_profile_registry, resolve_robot_profile


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_split_registry_loads_without_optional_profile_files(tmp_path: Path) -> None:
    _write(
        tmp_path / "control_types.yaml",
        """
        schema_version: "1.0"
        defaults:
          control_type: diff_drive
        control_types:
          diff_drive:
            type: diff_drive
            params:
              max_linear_mps: 0.4
        """,
    )
    _write(
        tmp_path / "control_interfaces.yaml",
        """
        schema_version: "1.0"
        defaults:
          control_interface: test_gpio
        control_interfaces:
          test_gpio:
            gpio:
              en_left: 1
              in1_left: 2
              in2_left: 3
              en_right: 4
              in1_right: 5
              in2_right: 6
            params:
              max_pwm: 70
        """,
    )
    _write(
        tmp_path / "robot_instances.yaml",
        """
        schema_version: "1.0"
        defaults:
          control_type: diff_drive
          control_interface: test_gpio
        robots:
          robot_a:
            control_type: diff_drive
            control_interface: test_gpio
            params:
              control_type:
                max_linear_mps: 0.2
              control_interface:
                max_pwm: 50
        """,
    )

    reg = load_profile_registry(str(tmp_path / "robot_instances.yaml"))

    assert reg["capability_profiles"] == {}
    assert reg["source_files"]["capability_profiles"] == "<omitted>"
    assert reg["adapter_profiles"]["passthrough_local"]["adapter"] == "passthrough"

    prof = resolve_robot_profile(reg, "robot_a")
    assert prof["control_type"] == "diff_drive"
    assert prof["control_interface"] == "test_gpio"
    assert prof["capability_profile"] is None
    assert prof["capabilities"] == {}
    assert prof["adapter_profile"] == "passthrough_local"
    assert prof["adapter_name"] == "passthrough"
    assert prof["drive_params"]["max_linear_mps"] == 0.2
    assert prof["hardware_params"]["max_pwm"] == 50


def test_robot_instance_can_override_gpio_map(tmp_path: Path) -> None:
    _write(
        tmp_path / "control_types.yaml",
        """
        schema_version: "1.0"
        control_types:
          mecanum_drive:
            type: omni
            params:
              max_linear_mps: 0.4
        """,
    )
    _write(
        tmp_path / "control_interfaces.yaml",
        """
        schema_version: "1.0"
        control_interfaces:
          dual_test:
            gpio:
              fl_pwm: 12
              fl_in1: 5
              fl_in2: 6
              fr_pwm: 13
              fr_in1: 16
              fr_in2: 19
            params:
              max_pwm: 70
        """,
    )
    _write(
        tmp_path / "robot_instances.yaml",
        """
        schema_version: "1.0"
        defaults:
          control_type: mecanum_drive
          control_interface: dual_test
        robots:
          robot5:
            control_type: mecanum_drive
            control_interface: dual_test
            gpio:
              fl_pwm: 21
              invert_fl: true
            params:
              control_interface_gpio:
                fr_pwm: 22
                invert_fr: true
        """,
    )

    reg = load_profile_registry(str(tmp_path / "robot_instances.yaml"))
    prof = resolve_robot_profile(reg, "robot5")

    assert prof["gpio"]["fl_pwm"] == 21
    assert prof["gpio"]["fr_pwm"] == 22
    assert prof["gpio"]["invert_fl"] is True
    assert prof["gpio"]["invert_fr"] is True


def test_seed_runtime_config_requires_only_minimal_core_files(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src_config = workspace / "src" / "swarm_control_core" / "config"
    target_dir = tmp_path / "runtime_cfg"
    src_config.mkdir(parents=True)

    for filename in (
        "robot_instances.yaml",
        "control_types.yaml",
        "control_interfaces.yaml",
        "camera_profiles.yaml",
    ):
        (src_config / filename).write_text("schema_version: '1.0'\n", encoding="utf-8")

    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "swarm_core_seed_runtime_config.sh"
    )
    subprocess.run(
        ["bash", str(script), "--workspace", str(workspace), "--target-dir", str(target_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    for filename in (
        "robot_instances.yaml",
        "control_types.yaml",
        "control_interfaces.yaml",
        "camera_profiles.yaml",
    ):
        assert (target_dir / filename).is_file()

    assert not (target_dir / "capability_profiles.yaml").exists()
    assert not (target_dir / "adapter_profiles.yaml").exists()
