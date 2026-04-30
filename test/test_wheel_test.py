from __future__ import annotations

from pathlib import Path

import yaml

from swarm_control_core.wheel_test import (
    SpeedState,
    command_for_key,
    expected_wheel_directions,
    format_expected_block,
    save_gpio_overrides,
    swap_wheel_channels,
    toggle_wheel_inversion,
)


TEST_SPEED = SpeedState(
    linear=0.12,
    angular=0.6,
    step=1.1,
    slow_linear=0.12,
    slow_angular=0.6,
    medium_linear=0.2,
    medium_angular=1.0,
    fast_linear=0.4,
    fast_angular=2.0,
)


def _mecanum_profile() -> dict:
    return {
        "drive_type": "omni",
        "drive_params": {
            "wheel_base_m": 0.18,
            "track_width_m": 0.18,
            "max_linear_mps": 0.4,
            "max_angular_rps": 2.0,
        },
        "hardware_params": {
            "max_pwm": 100,
        },
        "gpio": {
            "fl_pwm": 12,
            "fl_in1": 5,
            "fl_in2": 6,
            "fr_pwm": 13,
            "fr_in1": 16,
            "fr_in2": 19,
            "rl_pwm": 18,
            "rl_in1": 20,
            "rl_in2": 21,
            "rr_pwm": 26,
            "rr_in1": 23,
            "rr_in2": 24,
        },
    }


def test_expected_block_for_forward_mecanum_command() -> None:
    command = command_for_key(_mecanum_profile(), "8", strafe_mode=False, speed=TEST_SPEED)
    assert command is not None
    directions = expected_wheel_directions(
        _mecanum_profile(),
        command,
    )

    assert directions == {
        "fl": "FORWARD",
        "rl": "FORWARD",
        "fr": "FORWARD",
        "rr": "FORWARD",
    }
    assert "Command:\nFORWARD" in format_expected_block(command, directions)
    assert "BL = FORWARD" in format_expected_block(command, directions)


def test_expected_block_for_strafe_right_mecanum_command() -> None:
    command = command_for_key(_mecanum_profile(), "6", strafe_mode=True, speed=TEST_SPEED)
    assert command is not None
    directions = expected_wheel_directions(
        _mecanum_profile(),
        command,
    )

    assert directions == {
        "fl": "FORWARD",
        "rl": "REVERSE",
        "fr": "REVERSE",
        "rr": "FORWARD",
    }


def test_mecanum_strafe_mode_all_movement_keys_have_expected_outputs() -> None:
    expected = {
        "8": ("FORWARD", {"fl": "FORWARD", "rl": "FORWARD", "fr": "FORWARD", "rr": "FORWARD"}),
        "2": ("BACKWARD", {"fl": "REVERSE", "rl": "REVERSE", "fr": "REVERSE", "rr": "REVERSE"}),
        "4": ("STRAFE LEFT", {"fl": "REVERSE", "rl": "FORWARD", "fr": "FORWARD", "rr": "REVERSE"}),
        "6": ("STRAFE RIGHT", {"fl": "FORWARD", "rl": "REVERSE", "fr": "REVERSE", "rr": "FORWARD"}),
        "7": ("STRAFE FORWARD-LEFT", {"fl": "STOP", "rl": "FORWARD", "fr": "FORWARD", "rr": "STOP"}),
        "9": ("STRAFE FORWARD-RIGHT", {"fl": "FORWARD", "rl": "STOP", "fr": "STOP", "rr": "FORWARD"}),
        "1": ("STRAFE BACKWARD-LEFT", {"fl": "REVERSE", "rl": "STOP", "fr": "STOP", "rr": "REVERSE"}),
        "3": ("STRAFE BACKWARD-RIGHT", {"fl": "STOP", "rl": "REVERSE", "fr": "REVERSE", "rr": "STOP"}),
    }
    for key, (name, directions) in expected.items():
        command = command_for_key(_mecanum_profile(), key, strafe_mode=True, speed=TEST_SPEED)
        assert command is not None
        assert command.name == name
        assert expected_wheel_directions(_mecanum_profile(), command) == directions


def test_arrow_keys_match_teleop_movement_tokens() -> None:
    profile = _mecanum_profile()
    assert command_for_key(profile, "\x1b[A", strafe_mode=False, speed=TEST_SPEED) == command_for_key(profile, "8", strafe_mode=False, speed=TEST_SPEED)
    assert command_for_key(profile, "\x1b[B", strafe_mode=False, speed=TEST_SPEED) == command_for_key(profile, "2", strafe_mode=False, speed=TEST_SPEED)
    assert command_for_key(profile, "\x1b[D", strafe_mode=True, speed=TEST_SPEED) == command_for_key(profile, "4", strafe_mode=True, speed=TEST_SPEED)
    assert command_for_key(profile, "\x1b[C", strafe_mode=True, speed=TEST_SPEED) == command_for_key(profile, "6", strafe_mode=True, speed=TEST_SPEED)


def test_pending_gpio_inversion_and_swap_helpers() -> None:
    pending_gpio = {
        "fl_pwm": 12,
        "fl_in1": 5,
        "fl_in2": 6,
        "rr_pwm": 26,
        "rr_in1": 23,
        "rr_in2": 24,
    }

    assert toggle_wheel_inversion(pending_gpio, "fl") is True
    swap_wheel_channels(pending_gpio, "fl", "rr")

    assert pending_gpio["rr_pwm"] == 12
    assert pending_gpio["fl_pwm"] == 26
    assert pending_gpio["invert_fl"] is True


def test_save_gpio_overrides_writes_robot_entry(tmp_path: Path) -> None:
    profiles_path = tmp_path / "robot_instances.yaml"
    profiles_path.write_text(
        """schema_version: "1.0"
defaults:
  control_type: mecanum_drive
  control_interface: dual_l298n_mecanum
robots:
  robot5:
    ssh_target: robot5@legion5.local
    control_type: mecanum_drive
    control_interface: dual_l298n_mecanum
""",
        encoding="utf-8",
    )

    save_gpio_overrides(
        profiles_path,
        "robot5",
        {
            "invert_fl": True,
            "fl_pwm": 21,
        },
    )

    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    assert data["robots"]["robot5"]["gpio"]["invert_fl"] is True
    assert data["robots"]["robot5"]["gpio"]["fl_pwm"] == 21
