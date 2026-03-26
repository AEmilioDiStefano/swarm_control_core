#!/usr/bin/env python3

from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_PATH = CORE_ROOT / "swarm_launch" / "swarm_fpv_ui.launch.py"


def test_launch_file_does_not_hardcode_auth_mode_off():
    text = LAUNCH_PATH.read_text(encoding="utf-8")

    assert '{"auth_mode": "off"}' not in text
    assert '{"dev_login_enabled": False}' not in text
    assert '{"dev_users_json": ""}' not in text
