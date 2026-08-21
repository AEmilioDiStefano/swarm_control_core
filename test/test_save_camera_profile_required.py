from pathlib import Path

import yaml

from swarm_control_core import save_camera_profile
from swarm_control_core.save_camera_profile import CameraCandidate


CORE_ROOT = Path(__file__).resolve().parents[1]


def _write_existing_profile(path: Path, device: str = "/dev/video0") -> str:
    text = yaml.safe_dump(
        {
            "defaults": {},
            "profiles": {
                "robot5": {
                    "source": "usb",
                    "camera_name": "previous camera",
                    "device": device,
                    "width": 320,
                    "height": 240,
                    "fps": 10,
                    "fourcc": "MJPG",
                    "force_v4l2": True,
                }
            },
        },
        sort_keys=False,
    )
    path.write_text(text, encoding="utf-8")
    return text


def _required_args(path: Path) -> list[str]:
    return [
        "--robot",
        "robot5",
        "--camera-profiles",
        str(path),
        "--non-interactive",
        "--require-camera",
    ]


def test_require_camera_rejects_empty_inventory_without_changing_profile(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    original = _write_existing_profile(profiles_path)
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: [])

    rc = save_camera_profile.main(_required_args(profiles_path))

    assert rc == 2
    assert profiles_path.read_text(encoding="utf-8") == original
    stderr = capsys.readouterr().err
    assert "no capture-capable camera" in stderr
    assert "profile was not changed" in stderr


def test_require_camera_rejects_failed_stream_probe_without_changing_profile(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    original = _write_existing_profile(profiles_path)
    candidate = CameraCandidate(kind="usb", display_name="Camera", device="/dev/video2")
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: [candidate])
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "/dev/video2")
    monkeypatch.setattr(
        save_camera_profile,
        "_probe_v4l2_stream",
        lambda device: (False, "probe_stream_error"),
    )

    rc = save_camera_profile.main(_required_args(profiles_path))

    assert rc == 2
    assert profiles_path.read_text(encoding="utf-8") == original
    stderr = capsys.readouterr().err
    assert "probe_stream_error" in stderr
    assert "profile was not changed" in stderr


def test_require_camera_rejects_unavailable_stream_probe_without_changing_profile(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    original = _write_existing_profile(profiles_path)
    candidate = CameraCandidate(kind="usb", display_name="Camera", device="/dev/video2")
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: [candidate])
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "/dev/video2")
    monkeypatch.setattr(
        save_camera_profile,
        "_probe_v4l2_stream",
        lambda device: (None, "v4l2-ctl_missing"),
    )

    rc = save_camera_profile.main(_required_args(profiles_path))

    assert rc == 2
    assert profiles_path.read_text(encoding="utf-8") == original
    stderr = capsys.readouterr().err
    assert "v4l2-ctl_missing" in stderr


def test_require_camera_success_revalidates_and_overwrites_stale_profile(
    tmp_path: Path, monkeypatch
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    _write_existing_profile(profiles_path)
    candidate = CameraCandidate(
        kind="usb",
        display_name="Replacement Camera",
        device="/dev/video2",
    )
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: [candidate])
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "/dev/video2")
    monkeypatch.setattr(save_camera_profile, "_probe_v4l2_stream", lambda device: (True, "probe_ok"))
    monkeypatch.setattr(
        save_camera_profile,
        "_detect_v4l2_mode",
        lambda device: (640, 480, "MJPG", 15),
    )

    rc = save_camera_profile.main(_required_args(profiles_path))

    profile = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))["profiles"]["robot5"]
    assert rc == 0
    assert profile["camera_name"] == "Replacement Camera"
    assert profile["device"] == "/dev/video2"
    assert profile["width"] == 640
    assert profile["height"] == 480
    assert profile["fps"] == 15


def test_require_camera_accepts_a_fallback_only_after_its_probe_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    _write_existing_profile(profiles_path)
    candidates = [
        CameraCandidate(kind="usb", display_name="Bad Camera", device="/dev/video0"),
        CameraCandidate(kind="usb", display_name="Good Camera", device="/dev/video2"),
    ]
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: candidates)
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "/dev/video0")
    monkeypatch.setattr(
        save_camera_profile,
        "_probe_v4l2_stream",
        lambda device: (True, "probe_ok") if device == "/dev/video2" else (False, "probe_failed"),
    )
    monkeypatch.setattr(
        save_camera_profile,
        "_detect_v4l2_mode",
        lambda device: (1280, 720, "MJPG", 30),
    )

    rc = save_camera_profile.main(_required_args(profiles_path))

    profile = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))["profiles"]["robot5"]
    assert rc == 0
    assert profile["camera_name"] == "Good Camera"
    assert profile["device"] == "/dev/video2"


def test_default_mode_keeps_legacy_fallback_when_no_camera_is_detected(
    tmp_path: Path, monkeypatch
) -> None:
    profiles_path = tmp_path / "camera_profiles.yaml"
    monkeypatch.setattr(save_camera_profile, "_inventory_camera_candidates", lambda: [])
    monkeypatch.setattr(save_camera_profile, "_pick_device_from_system", lambda: "")
    monkeypatch.setattr(
        save_camera_profile,
        "_probe_v4l2_stream",
        lambda device: (None, "v4l2-ctl_missing"),
    )
    monkeypatch.setattr(
        save_camera_profile,
        "_detect_v4l2_mode",
        lambda device: (None, None, "", None),
    )

    rc = save_camera_profile.main(
        [
            "--robot",
            "robot5",
            "--camera-profiles",
            str(profiles_path),
            "--non-interactive",
        ]
    )

    profile = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))["profiles"]["robot5"]
    assert rc == 0
    assert profile["device"] == "/dev/video0"


def test_quickstart_step2_requires_camera_validation_unless_skipped() -> None:
    script = (CORE_ROOT / "scripts" / "swarm_core_quickstart_step2.sh").read_text(encoding="utf-8")

    assert (
        'ros2 run swarm_control_core save_camera_profile_core --robot "$robot_name" --require-camera'
        in script
    )
    assert 'if [[ "$skip_camera_profile" != "1" ]]' in script
