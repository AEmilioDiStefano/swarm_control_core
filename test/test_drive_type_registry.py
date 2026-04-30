import pytest

pytest.importorskip("geometry_msgs")

from swarm_control_core.drive_types import DiffDrive, MecanumDrive, get_drive_type


def test_drive_type_registry_resolves_known_aliases() -> None:
    assert isinstance(get_drive_type("diff_drive"), DiffDrive)
    assert isinstance(get_drive_type("diff"), DiffDrive)
    assert isinstance(get_drive_type("mecanum_drive"), MecanumDrive)
    assert isinstance(get_drive_type("omni"), MecanumDrive)
