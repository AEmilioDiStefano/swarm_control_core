#!/usr/bin/env python3

from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_PATH = CORE_ROOT / "swarm_launch" / "swarm_fpv_ui.launch.py"


def test_launch_file_does_not_hardcode_auth_mode_off():
    text = LAUNCH_PATH.read_text(encoding="utf-8")

    assert '{"auth_mode": "off"}' not in text
    assert '{"dev_login_enabled": False}' not in text
    assert '{"dev_users_json": ""}' not in text


def test_launch_file_passes_fleet_preview_preset_and_scalable_defaults():
    text = LAUNCH_PATH.read_text(encoding="utf-8")

    assert 'DeclareLaunchArgument("fleet_preview_preset", default_value=_default_fleet_preview_preset())' in text
    assert '{"fleet_preview_preset": LaunchConfiguration("fleet_preview_preset")}' in text
    assert '"scalable_fleet": {' in text
    assert '"thumb_robots_per_tick": "1"' in text
    assert '"image_thumb_interest_ttl_s": "2.5"' in text
