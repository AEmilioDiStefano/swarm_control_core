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


def test_legacy_control_interface_aliases_resolve_to_canonical_names() -> None:
    reg = load_profile_registry(str(PACKAGE_ROOT / "config" / "robot_instances.yaml"))
    l298n_profile = resolve_robot_profile(
        {
            **reg,
            "robots": {
                "legacy_robot": {
                    "control_type": "diff_drive",
                    "control_interface": "dual_L298N_diff",
                }
            },
        },
        "legacy_robot",
    )
    tracked_profile = resolve_robot_profile(
        {
            **reg,
            "robots": {
                "legacy_tracked_robot": {
                    "control_type": "diff_drive",
                    "control_interface": "dual_tb6612_diff",
                }
            },
        },
        "legacy_tracked_robot",
    )

    assert l298n_profile["control_interface"] == "dual_l298n_diff"
    assert tracked_profile["control_interface"] == "dual_tb6612_diff_4wheel_tracked"


def test_metadata_drives_control_interface_compatibility() -> None:
    data = yaml.safe_load((PACKAGE_ROOT / "config" / "control_interfaces.yaml").read_text(encoding="utf-8"))
    interfaces = data["control_interfaces"]

    assert canonical_profile_name(interfaces, "dual_L298N_mecanum") == "dual_l298n_mecanum"
    assert compatible_interface_names("mecanum_drive", list(interfaces), interfaces) == [
        "dual_l298n_mecanum",
        "dual_tb6612_mecanum",
    ]
    assert compatible_interface_names("diff_drive", list(interfaces), interfaces) == [
        "l298n_diff",
        "dual_l298n_diff",
        "dual_tb6612_diff_4wheel_tracked",
    ]


def test_control_interface_index_is_generated_from_yaml() -> None:
    rendered = render_control_interface_index(PACKAGE_ROOT / "config" / "control_interfaces.yaml")
    current = (PACKAGE_ROOT / "DOCS" / "GPIO" / "CONTROL_INTERFACE_INDEX.md").read_text(encoding="utf-8")

    assert rendered == current
