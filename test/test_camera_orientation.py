import numpy as np
from pathlib import Path

from swarm_control_core.camera_orientation import apply_frame_orientation


CORE_ROOT = Path(__file__).resolve().parents[1]


def test_apply_frame_orientation_horizontal_flip() -> None:
    frame = np.array(
        [
            [[1], [2], [3]],
            [[4], [5], [6]],
        ],
        dtype=np.uint8,
    )

    out = apply_frame_orientation(frame, flip_horizontal=True)

    assert out[:, :, 0].tolist() == [[3, 2, 1], [6, 5, 4]]


def test_apply_frame_orientation_vertical_flip() -> None:
    frame = np.array(
        [
            [[1], [2], [3]],
            [[4], [5], [6]],
        ],
        dtype=np.uint8,
    )

    out = apply_frame_orientation(frame, flip_vertical=True)

    assert out[:, :, 0].tolist() == [[4, 5, 6], [1, 2, 3]]


def test_apply_frame_orientation_both_flips() -> None:
    frame = np.array(
        [
            [[1], [2], [3]],
            [[4], [5], [6]],
        ],
        dtype=np.uint8,
    )

    out = apply_frame_orientation(frame, flip_horizontal=True, flip_vertical=True)

    assert out[:, :, 0].tolist() == [[6, 5, 4], [3, 2, 1]]


def test_camera_orientation_plumbed_through_profile_launch_and_adapter() -> None:
    adapter = (CORE_ROOT / "swarm_control_core" / "camera_adapter.py").read_text(encoding="utf-8")
    launch = (CORE_ROOT / "swarm_launch" / "swarm_bringup.launch.py").read_text(encoding="utf-8")
    save_profile = (CORE_ROOT / "swarm_control_core" / "save_camera_profile.py").read_text(encoding="utf-8")
    flipper = (CORE_ROOT / "swarm_control_core" / "camera_flipper.py").read_text(encoding="utf-8")
    setup_py = (CORE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert 'self.declare_parameter("flip_horizontal", False)' in adapter
    assert "apply_frame_orientation(" in adapter
    assert '"flip_horizontal": camera_flip_horizontal' in launch
    assert "orientation ignored; guard device" in launch
    assert '"camera_flip_horizontal"' in launch
    assert '"flip_horizontal": flip_horizontal' in save_profile
    assert '"orientation_device": orientation_device' in save_profile
    assert "yaml.profiles.<robot>.flip_horizontal" in save_profile
    assert "camera_flipper_core = swarm_control_core.camera_flipper:main" in setup_py
    assert "orientation_device" in flipper
