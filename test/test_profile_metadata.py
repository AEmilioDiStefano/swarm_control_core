from pathlib import Path

import yaml

from swarm_control_core.drive_profiles import load_profile_registry, resolve_robot_profile
from swarm_control_core.interface_backends import get_interface_backend
from swarm_control_core.profile_docs import render_control_interface_index
from swarm_control_core.profile_metadata import canonical_profile_name, compatible_interface_names
from swarm_control_core.profile_validation import validate_profile_files


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_control_interface_metadata_validates() -> None:
    errors = validate_profile_files(
        PACKAGE_ROOT / "config" / "control_types.yaml",
        PACKAGE_ROOT / "config" / "control_interfaces.yaml",
        package_root=PACKAGE_ROOT,
        check_docs_exist=True,
    )

    assert errors == []


def test_gpio_hbridge_backend_registry_exposes_layouts() -> None:
    backend = get_interface_backend("gpio_hbridge")

    assert backend is not None
    assert "four_wheel" in backend.gpio_layouts
    assert "rr_in2" in backend.gpio_layouts["four_wheel"]


def test_control_interface_names_are_canonical() -> None:
    reg = load_profile_registry(str(PACKAGE_ROOT / "config" / "robot_instances.yaml"))
    l298n_profile = resolve_robot_profile(
        {
            **reg,
            "robots": {
                "l298n_robot": {
                    "control_type": "diff_drive",
                    "control_interface": "4wheel_diff_l298n_2",
                }
            },
        },
        "l298n_robot",
    )
    tracked_profile = resolve_robot_profile(
        {
            **reg,
            "robots": {
                "tracked_robot": {
                    "control_type": "diff_drive",
                    "control_interface": "4wheel_diff_tb6612fng_2",
                }
            },
        },
        "tracked_robot",
    )

    assert l298n_profile["control_interface"] == "4wheel_diff_l298n_2"
    assert tracked_profile["control_interface"] == "4wheel_diff_tb6612fng_2"


def test_metadata_drives_control_interface_compatibility() -> None:
    data = yaml.safe_load((PACKAGE_ROOT / "config" / "control_interfaces.yaml").read_text(encoding="utf-8"))
    interfaces = data["control_interfaces"]

    assert canonical_profile_name(interfaces, "mecanum_l298n_2") == "mecanum_l298n_2"
    assert compatible_interface_names("mecanum_drive", list(interfaces), interfaces) == [
        "mecanum_l298n_2",
        "mecanum_tb6612fng_2",
    ]
    assert compatible_interface_names("diff_drive", list(interfaces), interfaces) == [
        "4wheel_diff_l298n_1",
        "4wheel_diff_l298n_2",
        "4wheel_diff_tb6612fng_2",
    ]


def test_4wheel_diff_tb6612fng_2_uses_four_independent_motor_channels() -> None:
    data = yaml.safe_load((PACKAGE_ROOT / "config" / "control_interfaces.yaml").read_text(encoding="utf-8"))
    profile = data["control_interfaces"]["4wheel_diff_tb6612fng_2"]

    assert profile["wheel_layout"] == "four_wheel"
    assert set(profile["gpio"]) >= {
        "fl_pwm",
        "fl_in1",
        "fl_in2",
        "fr_pwm",
        "fr_in1",
        "fr_in2",
        "rl_pwm",
        "rl_in1",
        "rl_in2",
        "rr_pwm",
        "rr_in1",
        "rr_in2",
    }


def test_control_interface_index_is_generated_from_yaml() -> None:
    rendered = render_control_interface_index(PACKAGE_ROOT / "config" / "control_interfaces.yaml")
    current = (PACKAGE_ROOT / "DOCS" / "GPIO" / "CONTROL_INTERFACE_INDEX.md").read_text(encoding="utf-8")

    assert rendered == current
