#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional

import yaml

from .drive_profiles import load_profile_registry, resolve_robot_profile
from .hardware_interface import HardwareInterface
from .path_defaults import default_profiles_path, default_robot_name


WHEEL_ORDER = ("fl", "rl", "fr", "rr")
WHEEL_LABELS = {
    "fl": "FL",
    "rl": "BL",
    "fr": "FR",
    "rr": "BR",
}
INVERT_KEYS = {
    "fl": "invert_fl",
    "rl": "invert_rl",
    "fr": "invert_fr",
    "rr": "invert_rr",
}
CHANNEL_SUFFIXES = ("pwm", "in1", "in2")


@dataclass(frozen=True)
class TestCommand:
    name: str
    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0


@dataclass
class SpeedState:
    linear: float
    angular: float
    step: float
    slow_linear: float
    slow_angular: float
    medium_linear: float
    medium_angular: float
    fast_linear: float
    fast_angular: float


ARROW_KEY_TOKENS = {
    "\x1b[A": "8",
    "\x1b[B": "2",
    "\x1b[D": "4",
    "\x1b[C": "6",
}
LINE_KEY_ALIASES = {
    "up": "8",
    "arrowup": "8",
    "down": "2",
    "arrowdown": "2",
    "left": "4",
    "arrowleft": "4",
    "right": "6",
    "arrowright": "6",
    "space": " ",
    "stop": " ",
}
MOVEMENT_KEYS = {"8", "2", "4", "6", "7", "9", "1", "3"}
STOP_KEYS = {" ", "5", "s"}
STRAFE_TOGGLE_KEYS = {"0"}

NORMAL_COMMAND_NAMES = {
    "8": "FORWARD",
    "2": "BACKWARD",
    "4": "ROTATE LEFT",
    "6": "ROTATE RIGHT",
    "7": "ARC FORWARD-LEFT",
    "9": "ARC FORWARD-RIGHT",
    "1": "ARC BACKWARD-LEFT",
    "3": "ARC BACKWARD-RIGHT",
}
STRAFE_COMMAND_NAMES = {
    "8": "FORWARD",
    "2": "BACKWARD",
    "4": "STRAFE LEFT",
    "6": "STRAFE RIGHT",
    "7": "STRAFE FORWARD-LEFT",
    "9": "STRAFE FORWARD-RIGHT",
    "1": "STRAFE BACKWARD-LEFT",
    "3": "STRAFE BACKWARD-RIGHT",
}


def _is_mecanum_profile(profile: Dict[str, Any]) -> bool:
    drive_type = str(profile.get("drive_type") or "").strip().lower()
    return drive_type in ("mecanum", "omni", "omnidirectional", "mecanum_drive", "mecanum-drive")


def _speed_state_from_profile(profile: Dict[str, Any], fallback_linear: float, fallback_angular: float) -> SpeedState:
    drive_params = profile.get("drive_params", {}) or {}
    base_linear = float(drive_params.get("teleop_linear_mps") or fallback_linear)
    base_angular = float(drive_params.get("teleop_angular_rps") or fallback_angular)
    step = float(drive_params.get("teleop_speed_step") or 1.1)
    if step <= 1.0:
        step = 1.1
    medium_steps = int(drive_params.get("teleop_medium_steps") or 10)
    fast_linear_steps = int(drive_params.get("teleop_fast_linear_steps") or 15)
    fast_angular_steps = int(drive_params.get("teleop_fast_angular_steps") or 10)
    return SpeedState(
        linear=base_linear,
        angular=base_angular,
        step=step,
        slow_linear=base_linear,
        slow_angular=base_angular,
        medium_linear=base_linear * (step ** medium_steps),
        medium_angular=base_angular * (step ** medium_steps),
        fast_linear=base_linear * (step ** fast_linear_steps),
        fast_angular=base_angular * (step ** fast_angular_steps),
    )


def _speed_summary(speed: SpeedState) -> str:
    return f"Linear Speed: {speed.linear:.2f}  Angular Speed: {speed.angular:.2f}"


def _direction_label(value: Optional[float]) -> str:
    if value is None or abs(float(value)) < 1e-9:
        return "STOP"
    return "FORWARD" if float(value) > 0 else "REVERSE"


def _twist_like(command: TestCommand) -> Any:
    return SimpleNamespace(
        linear=SimpleNamespace(
            x=float(command.linear_x),
            y=float(command.linear_y),
            z=0.0,
        ),
        angular=SimpleNamespace(
            x=0.0,
            y=0.0,
            z=float(command.angular_z),
        ),
    )


def _mix_params(profile: Dict[str, Any]) -> Dict[str, float]:
    drive_params = profile.get("drive_params", {}) or {}
    wheel_sep = (
        drive_params.get("wheel_separation_m")
        or drive_params.get("wheel_base_m")
        or 0.18
    )
    return {
        "wheel_separation": float(wheel_sep),
        "wheel_base": float(drive_params.get("wheel_base_m") or wheel_sep),
        "track_width": float(drive_params.get("track_width_m") or wheel_sep),
        "max_linear_speed": float(drive_params.get("max_linear_mps") or 0.4),
        "max_angular_speed": float(drive_params.get("max_angular_rps") or 2.0),
        "spin_speed_mult": float(drive_params.get("spin_speed_mult") or 0.7),
    }


def _teleop_diff_arc_command(profile: Dict[str, Any], key: str, speed: SpeedState) -> TestCommand:
    params = _mix_params(profile)
    wheel_sep = float(params["wheel_separation"]) if float(params["wheel_separation"]) > 1e-6 else 0.18
    drive_params = profile.get("drive_params", {}) or {}
    inner_ratio = max(0.0, min(1.0, float(drive_params.get("teleop_diff_arc_inner_ratio") or 0.6)))
    outer = abs(float(speed.linear))
    inner = outer * inner_ratio

    if key == "7":
        left_value, right_value = inner, outer
    elif key == "9":
        left_value, right_value = outer, inner
    elif key == "1":
        left_value, right_value = -inner, -outer
    elif key == "3":
        left_value, right_value = -outer, -inner
    else:
        raise KeyError(key)

    linear_x = 0.5 * (left_value + right_value)
    angular_z = (right_value - left_value) / wheel_sep
    return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=linear_x, angular_z=angular_z)


def _teleop_omni_arc_command(profile: Dict[str, Any], key: str, speed: SpeedState) -> TestCommand:
    drive_params = profile.get("drive_params", {}) or {}
    turn_gain = float(drive_params.get("teleop_omni_turn_gain") or 0.5)
    yaw = turn_gain * abs(float(speed.angular))
    if key == "7":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=+speed.linear, angular_z=+yaw)
    if key == "9":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=+speed.linear, angular_z=-yaw)
    if key == "1":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=-speed.linear, angular_z=+yaw)
    if key == "3":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=-speed.linear, angular_z=-yaw)
    raise KeyError(key)


def _canonical_key(raw: str) -> str:
    key = str(raw or "")
    if key in ARROW_KEY_TOKENS:
        return ARROW_KEY_TOKENS[key]
    return LINE_KEY_ALIASES.get(key.strip().lower(), key)


def command_for_key(profile: Dict[str, Any], raw_key: str, *, strafe_mode: bool, speed: SpeedState) -> Optional[TestCommand]:
    key = _canonical_key(raw_key)
    if key not in MOVEMENT_KEYS:
        return None

    can_strafe = _is_mecanum_profile(profile)
    if strafe_mode and can_strafe:
        if key == "8":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=+speed.linear)
        if key == "2":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=-speed.linear)
        if key == "4":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_y=+speed.linear)
        if key == "6":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_y=-speed.linear)
        if key == "7":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=+speed.linear, linear_y=+speed.linear)
        if key == "9":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=+speed.linear, linear_y=-speed.linear)
        if key == "1":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=-speed.linear, linear_y=+speed.linear)
        if key == "3":
            return TestCommand(STRAFE_COMMAND_NAMES[key], linear_x=-speed.linear, linear_y=-speed.linear)

    if key == "8":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=+speed.linear)
    if key == "2":
        return TestCommand(NORMAL_COMMAND_NAMES[key], linear_x=-speed.linear)
    if key == "4":
        return TestCommand(NORMAL_COMMAND_NAMES[key], angular_z=+speed.angular)
    if key == "6":
        return TestCommand(NORMAL_COMMAND_NAMES[key], angular_z=-speed.angular)
    if key in ("7", "9", "1", "3"):
        if _is_mecanum_profile(profile):
            return _teleop_omni_arc_command(profile, key, speed)
        return _teleop_diff_arc_command(profile, key, speed)
    return None


def mixed_wheel_values(
    profile: Dict[str, Any],
    command: TestCommand,
) -> Dict[str, float]:
    msg = _twist_like(command)
    params = _mix_params(profile)
    if _is_mecanum_profile(profile):
        max_linear = float(params["max_linear_speed"])
        max_angular = float(params["max_angular_speed"])
        wheel_base = float(params["wheel_base"])
        track_width = float(params["track_width"])
        linear_x = max(-max_linear, min(max_linear, float(msg.linear.x)))
        linear_y = max(-max_linear, min(max_linear, float(msg.linear.y)))
        angular_z = max(-max_angular, min(max_angular, float(msg.angular.z)))
        radius = (wheel_base + track_width) / 2.0 if (wheel_base + track_width) > 1e-6 else 0.18
        fl_value = linear_x - linear_y - angular_z * radius
        fr_value = linear_x + linear_y + angular_z * radius
        rl_value = linear_x + linear_y - angular_z * radius
        rr_value = linear_x - linear_y + angular_z * radius
        max_wheel = max(abs(fl_value), abs(fr_value), abs(rl_value), abs(rr_value), 1e-6)
        if max_wheel > max_linear:
            scale = max_linear / max_wheel
            fl_value *= scale
            fr_value *= scale
            rl_value *= scale
            rr_value *= scale
        return {
            "fl": fl_value,
            "rl": rl_value,
            "fr": fr_value,
            "rr": rr_value,
        }

    max_linear = float(params["max_linear_speed"])
    max_angular = float(params["max_angular_speed"])
    wheel_sep = float(params["wheel_separation"])
    spin_mult = float(params["spin_speed_mult"])
    linear_x = max(-max_linear, min(max_linear, float(msg.linear.x)))
    angular_z = max(-max_angular, min(max_angular, float(msg.angular.z)))
    if abs(linear_x) < 1e-3 and abs(angular_z) > 1e-3:
        spin_speed = spin_mult * max_linear
        direction = 1.0 if angular_z > 0.0 else -1.0
        left_value = -direction * spin_speed
        right_value = direction * spin_speed
    else:
        left_value = linear_x - (angular_z * wheel_sep / 2.0)
        right_value = linear_x + (angular_z * wheel_sep / 2.0)
    return {
        "fl": left_value,
        "rl": left_value,
        "fr": right_value,
        "rr": right_value,
    }


def expected_wheel_directions(
    profile: Dict[str, Any],
    command: TestCommand,
    *,
    linear_speed: Optional[float] = None,
    angular_speed: Optional[float] = None,
) -> Dict[str, str]:
    del linear_speed, angular_speed
    values = mixed_wheel_values(profile, command)
    return {wheel: _direction_label(values.get(wheel)) for wheel in WHEEL_ORDER}


def format_expected_block(command: TestCommand, directions: Dict[str, str]) -> str:
    lines = [
        "Command:",
        command.name,
        "",
        "Expected:",
    ]
    for wheel in WHEEL_ORDER:
        lines.append(f"{WHEEL_LABELS[wheel]} = {directions.get(wheel, 'STOP')}")
    return "\n".join(lines)


def _speed_to_duty(speed: float, max_linear: float, max_pwm: float, deadband: float) -> tuple[float, int]:
    ratio = float(speed) / float(max_linear) if float(max_linear) > 1e-9 else 0.0
    ratio = max(-1.0, min(1.0, ratio))
    direction = 1 if ratio >= 0.0 else -1
    duty = abs(ratio) * float(max_pwm)
    if 0.0 < duty < float(deadband):
        duty = 0.0
    return duty, direction


def _runtime_gpio(profile: Dict[str, Any], pending_gpio: Dict[str, Any]) -> Dict[str, Any]:
    hardware_params = profile.get("hardware_params", {}) or {}
    gpio_map = dict(profile.get("gpio", {}) or {})
    gpio_map.update(pending_gpio)
    gpio_map["pwm_hz"] = int(hardware_params.get("pwm_hz") or 1000)
    gpio_map["pwm_ramp_ms"] = float(hardware_params.get("pwm_ramp_ms") or 0.0)
    gpio_map["pwm_slew_pct_per_s"] = float(hardware_params.get("pwm_slew_pct_per_s") or 0.0)
    return gpio_map


def run_direct_command(
    profile: Dict[str, Any],
    pending_gpio: Dict[str, Any],
    command: TestCommand,
    *,
    duration_s: float,
) -> None:
    hardware_params = profile.get("hardware_params", {}) or {}
    max_linear = float(_mix_params(profile)["max_linear_speed"])
    max_pwm = float(hardware_params.get("max_pwm") or 100.0)
    deadband = float(hardware_params.get("pwm_deadband_pct") or 0.0)
    values = mixed_wheel_values(profile, command)
    hardware = HardwareInterface(_runtime_gpio(profile, pending_gpio))
    try:
        if _is_mecanum_profile(profile):
            fl_duty, fl_dir = _speed_to_duty(values["fl"], max_linear, max_pwm, deadband)
            fr_duty, fr_dir = _speed_to_duty(values["fr"], max_linear, max_pwm, deadband)
            rl_duty, rl_dir = _speed_to_duty(values["rl"], max_linear, max_pwm, deadband)
            rr_duty, rr_dir = _speed_to_duty(values["rr"], max_linear, max_pwm, deadband)
            hardware.set_mecanum(
                fl_duty,
                fl_dir,
                fr_duty,
                fr_dir,
                rl_duty,
                rl_dir,
                rr_duty,
                rr_dir,
                bypass_ramp=True,
            )
            time.sleep(max(0.05, float(duration_s)))
            hardware.set_mecanum(0.0, 1, 0.0, 1, 0.0, 1, 0.0, 1, bypass_ramp=True)
            return

        left_duty, left_dir = _speed_to_duty(values["fl"], max_linear, max_pwm, deadband)
        right_duty, right_dir = _speed_to_duty(values["fr"], max_linear, max_pwm, deadband)
        hardware.set_motor(left_duty, left_dir, right_duty, right_dir, bypass_ramp=True)
        time.sleep(max(0.05, float(duration_s)))
        hardware.set_motor(0.0, 1, 0.0, 1, bypass_ramp=True)
    finally:
        hardware.stop()


class CmdVelPublisher:
    def __init__(self, robot_name: str) -> None:
        import rclpy
        from geometry_msgs.msg import Twist

        self.rclpy = rclpy
        self.twist_type = Twist
        self.node = rclpy.create_node("wheel_test_core")
        self.publisher = self.node.create_publisher(Twist, f"/{robot_name}/cmd_vel", 10)

    def run_command(
        self,
        command: TestCommand,
        *,
        duration_s: float,
    ) -> None:
        deadline = time.monotonic() + max(0.05, float(duration_s))
        while time.monotonic() < deadline:
            msg = self.twist_type()
            msg.linear.x = float(command.linear_x)
            msg.linear.y = float(command.linear_y)
            msg.angular.z = float(command.angular_z)
            self.publisher.publish(msg)
            self.rclpy.spin_once(self.node, timeout_sec=0.0)
            time.sleep(0.1)
        for _ in range(3):
            self.publisher.publish(self.twist_type())
            self.rclpy.spin_once(self.node, timeout_sec=0.0)
            time.sleep(0.05)

    def close(self) -> None:
        self.node.destroy_node()


def toggle_wheel_inversion(pending_gpio: Dict[str, Any], wheel: str) -> bool:
    key = INVERT_KEYS[wheel]
    pending_gpio[key] = not bool(pending_gpio.get(key, False))
    return bool(pending_gpio[key])


def swap_wheel_channels(pending_gpio: Dict[str, Any], wheel_a: str, wheel_b: str) -> None:
    if wheel_a not in WHEEL_ORDER or wheel_b not in WHEEL_ORDER or wheel_a == wheel_b:
        raise ValueError("Wheel swap expects two different wheel names: fl, bl/rl, fr, br/rr")
    left = "rl" if wheel_a == "bl" else "rr" if wheel_a == "br" else wheel_a
    right = "rl" if wheel_b == "bl" else "rr" if wheel_b == "br" else wheel_b
    for suffix in CHANNEL_SUFFIXES:
        left_key = f"{left}_{suffix}"
        right_key = f"{right}_{suffix}"
        pending_gpio[left_key], pending_gpio[right_key] = pending_gpio.get(right_key), pending_gpio.get(left_key)


def save_gpio_overrides(profiles_path: Path, robot_name: str, pending_gpio: Dict[str, Any]) -> None:
    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profile file must be a YAML mapping: {profiles_path}")
    robots = data.get("robots", {}) or {}
    if not isinstance(robots, dict) or robot_name not in robots:
        raise KeyError(f"Robot '{robot_name}' is not present in {profiles_path}")
    entry = robots.get(robot_name) or {}
    if not isinstance(entry, dict):
        raise ValueError(f"robots.{robot_name} must be a YAML mapping")
    existing_gpio = entry.get("gpio", {}) or {}
    if not isinstance(existing_gpio, dict):
        existing_gpio = {}
    existing_gpio.update({key: value for key, value in pending_gpio.items() if value is not None})
    entry["gpio"] = existing_gpio
    robots[robot_name] = entry
    data["robots"] = robots
    profiles_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _canonical_wheel(raw: str) -> str:
    value = str(raw or "").strip().lower()
    aliases = {
        "front-left": "fl",
        "front_left": "fl",
        "left-front": "fl",
        "left_front": "fl",
        "back-left": "rl",
        "back_left": "rl",
        "rear-left": "rl",
        "rear_left": "rl",
        "bl": "rl",
        "front-right": "fr",
        "front_right": "fr",
        "right-front": "fr",
        "right_front": "fr",
        "back-right": "rr",
        "back_right": "rr",
        "rear-right": "rr",
        "rear_right": "rr",
        "br": "rr",
    }
    return aliases.get(value, value)


def help_text() -> str:
    return """
Wheel test keys:
  8 / ArrowUp     forward
  2 / ArrowDown   backward
  4 / ArrowLeft   rotate-left, or strafe-left when STRAFE mode is enabled
  6 / ArrowRight  rotate-right, or strafe-right when STRAFE mode is enabled
  7 / 9           arc forward-left / arc forward-right
  1 / 3           arc backward-left / arc backward-right
  0               toggle STRAFE mode for mecanum/omni robots
  space / s / 5   STOP/zero command

Speed keys match teleop/UI:
  i slow, o medium, p fast
  q or / linear+, r or * linear-
  w or + speed+,  e or - speed-

Calibration keys:
  v  choose a wheel and toggle inversion
  c  swap two wheel channel mappings, e.g. fl br
  P  print pending GPIO overrides
  S  save pending GPIO overrides into robot_instances.yaml
  h  help
  x  exit
""".strip()


class Terminal:
    def __init__(self) -> None:
        self.settings = None
        self.raw = False

    def __enter__(self) -> "Terminal":
        if sys.stdin.isatty():
            self.settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
            self.raw = True
        return self

    def __exit__(self, *_args: object) -> None:
        self.restore()

    def restore(self) -> None:
        if self.raw and self.settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
            self.raw = False

    def set_raw(self) -> None:
        if self.settings is not None and not self.raw:
            tty.setraw(sys.stdin.fileno())
            self.raw = True

    def print(self, text: str = "") -> None:
        self.restore()
        print(text, flush=True)
        self.set_raw()

    def prompt(self, text: str) -> str:
        self.restore()
        try:
            return input(text)
        finally:
            self.set_raw()

    def read_key(self) -> str:
        if not self.raw:
            return input("wheel-test> ").strip()
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if not ready:
            return ""
        key = sys.stdin.read(1)
        if key == "\x1b":
            ready, _, _ = select.select([sys.stdin], [], [], 0.02)
            if ready:
                key += sys.stdin.read(2)
        return key


def _pending_summary(pending_gpio: Dict[str, Any]) -> str:
    if not pending_gpio:
        return "(none)"
    rows = []
    for key in sorted(pending_gpio):
        rows.append(f"{key}: {pending_gpio[key]}")
    return "\n".join(rows)


def _seed_pending_gpio(profile: Dict[str, Any]) -> Dict[str, Any]:
    gpio = dict(profile.get("gpio", {}) or {})
    seeded: Dict[str, Any] = {}
    for wheel in WHEEL_ORDER:
        for suffix in CHANNEL_SUFFIXES:
            key = f"{wheel}_{suffix}"
            if key in gpio:
                seeded[key] = gpio[key]
        invert_key = INVERT_KEYS[wheel]
        if invert_key in gpio:
            seeded[invert_key] = bool(gpio[invert_key])
    return seeded


def _run_command(
    *,
    mode: str,
    robot_name: str,
    profile: Dict[str, Any],
    pending_gpio: Dict[str, Any],
    command: TestCommand,
    duration_s: float,
    cmd_vel_publisher: Optional[CmdVelPublisher] = None,
) -> None:
    if mode == "cmd_vel":
        if cmd_vel_publisher is None:
            raise RuntimeError("cmd_vel mode requires an initialized CmdVelPublisher")
        cmd_vel_publisher.run_command(
            command,
            duration_s=duration_s,
        )
        return
    run_direct_command(
        profile,
        pending_gpio,
        command,
        duration_s=duration_s,
    )


def _apply_speed_key(key: str, speed: SpeedState) -> Optional[str]:
    canonical = _canonical_key(key).lower()
    if canonical == "i":
        speed.linear = speed.slow_linear
        speed.angular = speed.slow_angular
        return "slow"
    if canonical == "o":
        speed.linear = speed.medium_linear
        speed.angular = speed.medium_angular
        return "medium"
    if canonical == "p":
        speed.linear = speed.fast_linear
        speed.angular = speed.fast_angular
        return "fast"
    if canonical in ("w", "+"):
        speed.linear *= speed.step
        speed.angular *= speed.step
        return "speed+"
    if canonical in ("e", "-"):
        speed.linear /= speed.step
        speed.angular /= speed.step
        return "speed-"
    if canonical in ("q", "/"):
        speed.linear *= speed.step
        return "linear+"
    if canonical in ("r", "*"):
        speed.linear /= speed.step
        return "linear-"
    return None


def run_interactive(
    *,
    robot_name: str,
    profiles_path: Path,
    mode: str,
    linear_speed: float,
    angular_speed: float,
    duration_s: float,
    save_enabled: bool,
) -> int:
    registry = load_profile_registry(str(profiles_path))
    profile = resolve_robot_profile(registry, robot_name)
    speed = _speed_state_from_profile(profile, linear_speed, angular_speed)
    strafe_mode = False
    pending_gpio = _seed_pending_gpio(profile)
    cmd_vel_publisher: Optional[CmdVelPublisher] = None
    if mode == "cmd_vel":
        import rclpy

        rclpy.init(args=None)
        cmd_vel_publisher = CmdVelPublisher(robot_name)

    try:
        with Terminal() as terminal:
            terminal.print(f"[wheel_test] robot={robot_name} mode={mode} profiles={profiles_path}")
            terminal.print("[wheel_test] Put the robot on blocks / wheels clear before moving motors.")
            terminal.print(help_text())
            terminal.print(_speed_summary(speed))
            while True:
                key = terminal.read_key()
                if not key:
                    continue
                canonical_key = _canonical_key(key)
                if key == "\x03":
                    terminal.print("\n[wheel_test] interrupted")
                    return 130
                if key in ("x", "X"):
                    terminal.print("\n[wheel_test] done")
                    return 0
                if key in ("h", "H", "?"):
                    terminal.print("\n" + help_text())
                    terminal.print(_speed_summary(speed))
                    continue
                if canonical_key in STOP_KEYS:
                    terminal.print("\nCommand:\nSTOP\n\nExpected:\nFL = STOP\nBL = STOP\nFR = STOP\nBR = STOP")
                    continue
                if canonical_key in STRAFE_TOGGLE_KEYS:
                    if not _is_mecanum_profile(profile):
                        strafe_mode = False
                        terminal.print("\n[STRAFE] Disabled: this robot profile is not mecanum/omni.")
                        continue
                    strafe_mode = not strafe_mode
                    terminal.print(f"\n[STRAFE] {'ENABLED' if strafe_mode else 'DISABLED'}")
                    continue
                if key == "P":
                    terminal.print("\nPending GPIO overrides:\n" + _pending_summary(pending_gpio))
                    continue
                speed_label = _apply_speed_key(canonical_key, speed)
                if speed_label:
                    terminal.print(f"\n[SPEED] {speed_label}  {_speed_summary(speed)}")
                    continue
                command = command_for_key(profile, canonical_key, strafe_mode=strafe_mode, speed=speed)
                if command is not None:
                    directions = expected_wheel_directions(profile, command)
                    terminal.print("\n" + format_expected_block(command, directions))
                    _run_command(
                        mode=mode,
                        robot_name=robot_name,
                        profile=profile,
                        pending_gpio=pending_gpio,
                        command=command,
                        duration_s=duration_s,
                        cmd_vel_publisher=cmd_vel_publisher,
                    )
                    continue
                if canonical_key in ("v", "V"):
                    raw_wheel = terminal.prompt("\nToggle inversion for wheel [fl/bl/fr/br]: ")
                    wheel = _canonical_wheel(raw_wheel)
                    if wheel not in WHEEL_ORDER:
                        terminal.print("[wheel_test] inversion skipped; expected fl, bl, fr, or br.")
                        continue
                    state = toggle_wheel_inversion(pending_gpio, wheel)
                    terminal.print(f"[wheel_test] {WHEEL_LABELS[wheel]} inversion now {state}")
                    continue
                if canonical_key in ("c", "C"):
                    pair = terminal.prompt("\nSwap wheel channels (examples: fl br, bl fr): ").split()
                    if len(pair) != 2:
                        terminal.print("[wheel_test] swap skipped; enter exactly two wheel names.")
                        continue
                    try:
                        wheel_a = _canonical_wheel(pair[0])
                        wheel_b = _canonical_wheel(pair[1])
                        swap_wheel_channels(pending_gpio, wheel_a, wheel_b)
                        terminal.print(f"[wheel_test] swapped {WHEEL_LABELS[wheel_a]} and {WHEEL_LABELS[wheel_b]}")
                    except Exception as exc:
                        terminal.print(f"[wheel_test] swap failed: {exc}")
                    continue
                if key == "S":
                    if not save_enabled:
                        terminal.print("\n[wheel_test] save disabled by --no-save")
                        continue
                    answer = terminal.prompt(f"\nSave pending GPIO overrides to {profiles_path}? [y/N] ").strip().lower()
                    if answer not in ("y", "yes"):
                        terminal.print("[wheel_test] save skipped")
                        continue
                    try:
                        save_gpio_overrides(profiles_path, robot_name, pending_gpio)
                        terminal.print("[wheel_test] saved. Relaunch robot bringup for node mode to consume saved changes.")
                    except Exception as exc:
                        terminal.print(f"[wheel_test] save failed: {exc}")
                    continue
                terminal.print(f"\n[wheel_test] unknown key: {key!r} (press h for help)")
    finally:
        if cmd_vel_publisher is not None:
            cmd_vel_publisher.close()
            import rclpy

            rclpy.shutdown()


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive wheel direction/order test for robot motor profiles.")
    parser.add_argument("--robot", default="", help="Robot name. Defaults to SWARM_CORE_ROBOT_NAME/Linux username.")
    parser.add_argument("--profiles-path", default="", help="Path to robot_instances.yaml.")
    parser.add_argument("--mode", choices=("direct", "cmd_vel"), default="direct", help="direct uses GPIO; cmd_vel uses a running motor_driver_node.")
    parser.add_argument("--linear", type=float, default=0.12, help="Linear test speed in m/s.")
    parser.add_argument("--angular", type=float, default=0.6, help="Angular test speed in rad/s.")
    parser.add_argument("--duration", type=float, default=0.7, help="Seconds to pulse each command.")
    parser.add_argument("--no-save", action="store_true", help="Disable saving GPIO inversion/order overrides.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    robot_name = str(args.robot or "").strip() or default_robot_name()
    profiles_path = Path(str(args.profiles_path or "").strip() or default_profiles_path()).expanduser()
    if not profiles_path.exists():
        print(f"[wheel_test] ERROR: profiles file not found: {profiles_path}", file=sys.stderr)
        return 2
    return run_interactive(
        robot_name=robot_name,
        profiles_path=profiles_path,
        mode=str(args.mode),
        linear_speed=float(args.linear),
        angular_speed=float(args.angular),
        duration_s=float(args.duration),
        save_enabled=not bool(args.no_save),
    )


if __name__ == "__main__":
    raise SystemExit(main())
