from pathlib import Path

import yaml

from swarm_control_core import camera_flipper
from swarm_control_core import save_camera_profile
from swarm_control_core.save_camera_profile import CameraCandidate


class _TtyStdin:
    def isatty(self) -> bool:
        return True


def test_camera_devices_match_exact_and_resolved_symlink(tmp_path: Path) -> None:
    target = tmp_path / "video0"
    target.write_text("camera", encoding="utf-8")
    link = tmp_path / "by-id-camera"
    link.symlink_to(target)

    assert camera_flipper.camera_devices_match(str(target), str(target))
    assert camera_flipper.camera_devices_match(str(link), str(target))
    assert not camera_flipper.camera_devices_match(str(link), str(tmp_path / "missing"))


def test_update_orientation_profile_sets_guard_for_matched_camera() -> None:
    profile = {
        "device": "/dev/video0",
        "camera_name": "Old Camera",
        "flip_horizontal": False,
        "flip_vertical": False,
    }
    candidate = CameraCandidate(
        kind="usb",
        display_name="Robot5 Camera",
        device="/dev/v4l/by-id/usb-Robot5-video-index0",
    )

    updated = camera_flipper.update_orientation_profile(
        profile,
        horizontal_action="on",
        vertical_action="keep",
        matched_camera=candidate,
    )

    assert updated["flip_horizontal"] is True
    assert updated["flip_vertical"] is False
    assert updated["orientation_device"] == "/dev/v4l/by-id/usb-Robot5-video-index0"
    assert updated["orientation_camera_name"] == "Robot5 Camera"


def test_update_orientation_profile_clears_guard_when_no_flips() -> None:
    profile = {
        "device": "/dev/video0",
        "flip_horizontal": True,
        "flip_vertical": False,
        "orientation_device": "/dev/video0",
        "orientation_camera_name": "Robot5 Camera",
    }

    updated = camera_flipper.update_orientation_profile(
        profile,
        horizontal_action="off",
        vertical_action="off",
        matched_camera=None,
    )

    assert updated["flip_horizontal"] is False
    assert updated["flip_vertical"] is False
    assert updated["orientation_device"] == ""
    assert updated["orientation_camera_name"] == ""


def test_camera_flipper_main_writes_guarded_profile(tmp_path: Path, monkeypatch) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    profiles_path.write_text(
        yaml.safe_dump(
            {
                "defaults": {},
                "profiles": {
                    "robot5": {
                        "source": "usb",
                        "camera_name": "Robot5 Camera",
                        "device": "/dev/video0",
                        "flip_horizontal": False,
                        "flip_vertical": False,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        camera_flipper,
        "_inventory_camera_candidates",
        lambda: [
            CameraCandidate(
                kind="usb",
                display_name="Robot5 Camera",
                device="/dev/video0",
            )
        ],
    )

    rc = camera_flipper.main(
        [
            "--robot",
            "robot5",
            "--camera-profiles",
            str(profiles_path),
            "--set",
            "horizontal",
        ]
    )

    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    profile = data["profiles"]["robot5"]
    assert rc == 0
    assert profile["flip_horizontal"] is True
    assert profile["flip_vertical"] is False
    assert profile["orientation_device"] == "/dev/video0"
    assert profile["orientation_camera_name"] == "Robot5 Camera"


def test_camera_flipper_interactive_menu_toggles_and_exits(tmp_path: Path, monkeypatch) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    profiles_path.write_text(
        yaml.safe_dump(
            {
                "defaults": {},
                "profiles": {
                    "robot5": {
                        "source": "usb",
                        "camera_name": "Robot5 Camera",
                        "device": "/dev/video0",
                        "flip_horizontal": False,
                        "flip_vertical": False,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(camera_flipper.sys, "stdin", _TtyStdin())
    input_values = iter(["1", "", "5"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(input_values))
    monkeypatch.setattr(
        camera_flipper,
        "_inventory_camera_candidates",
        lambda: [CameraCandidate(kind="usb", display_name="Robot5 Camera", device="/dev/video0")],
    )

    rc = camera_flipper.main(["--robot", "robot5", "--camera-profiles", str(profiles_path)])

    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    profile = data["profiles"]["robot5"]
    assert rc == 0
    assert profile["flip_horizontal"] is True
    assert profile["flip_vertical"] is False
    assert profile["orientation_device"] == "/dev/video0"


def test_camera_flipper_refuses_unmatched_camera_without_force(tmp_path: Path, monkeypatch) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    profiles_path.write_text(
        yaml.safe_dump(
            {
                "defaults": {},
                "profiles": {
                    "robot5": {
                        "source": "usb",
                        "camera_name": "Robot5 Camera",
                        "device": "/dev/video0",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        camera_flipper,
        "_inventory_camera_candidates",
        lambda: [CameraCandidate(kind="usb", display_name="Other Camera", device="/dev/video2")],
    )

    rc = camera_flipper.main(
        [
            "--robot",
            "robot5",
            "--camera-profiles",
            str(profiles_path),
            "--set",
            "horizontal",
        ]
    )

    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    assert rc == 2
    assert "flip_horizontal" not in data["profiles"]["robot5"]


def test_save_camera_profile_drops_guarded_flip_when_camera_changes(tmp_path: Path, monkeypatch) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    profiles_path.write_text(
        yaml.safe_dump(
            {
                "defaults": {},
                "profiles": {
                    "robot5": {
                        "source": "usb",
                        "camera_name": "Robot5 Old Camera",
                        "device": "/dev/video0",
                        "flip_horizontal": True,
                        "flip_vertical": False,
                        "orientation_device": "/dev/video0",
                        "orientation_camera_name": "Robot5 Old Camera",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        save_camera_profile,
        "_inventory_camera_candidates",
        lambda: [CameraCandidate(kind="usb", display_name="Replacement Camera", device="/dev/video2")],
    )
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "/dev/video2")
    monkeypatch.setattr(save_camera_profile, "_probe_v4l2_stream", lambda device: (True, "probe_ok"))
    monkeypatch.setattr(save_camera_profile, "_detect_v4l2_mode", lambda device: (640, 480, "MJPG", 15))

    rc = save_camera_profile.main(
        [
            "--robot",
            "robot5",
            "--camera-profiles",
            str(profiles_path),
            "--non-interactive",
        ]
    )

    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    profile = data["profiles"]["robot5"]
    assert rc == 0
    assert profile["device"] == "/dev/video2"
    assert profile["flip_horizontal"] is False
    assert profile["flip_vertical"] is False
    assert profile["orientation_device"] == ""
    assert profile["orientation_camera_name"] == ""
