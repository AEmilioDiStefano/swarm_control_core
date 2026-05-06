from __future__ import annotations

from pathlib import Path

import pytest

from swarm_control_core.drive_profiles import load_profile_registry, resolve_robot_profile
from swarm_control_core.hardware_interface import HardwareInterface
import swarm_control_core.hardware_interface as hardware_interface


class _FakePwm:
    def __init__(self, pin: int, hz: int):
        self.pin = pin
        self.hz = hz
        self.duty_cycles: list[float] = []

    def start(self, duty: float) -> None:
        self.duty_cycles.append(float(duty))

    def ChangeDutyCycle(self, duty: float) -> None:
        self.duty_cycles.append(float(duty))

    def stop(self) -> None:
        pass


class _FakeGpio:
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def __init__(self) -> None:
        self.outputs: dict[int, int] = {}
        self.pwms: dict[int, _FakePwm] = {}

    def setmode(self, mode: str) -> None:
        self.mode = mode

    def setwarnings(self, enabled: bool) -> None:
        self.warnings = enabled

    def setup(self, pin: int, mode: str) -> None:
        pass

    def PWM(self, pin: int, hz: int) -> _FakePwm:
        pwm = _FakePwm(pin, hz)
        self.pwms[pin] = pwm
        return pwm

    def output(self, pin: int, value: int) -> None:
        self.outputs[pin] = value

    def cleanup(self) -> None:
        pass


def test_robot4_resolves_to_4wheel_diff_l298n_2_profile() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "config"
    reg = load_profile_registry(str(config_dir / "robot_instances.yaml"))

    profile = resolve_robot_profile(reg, "robot4")

    assert profile["control_type"] == "diff_drive"
    assert profile["control_interface"] == "4wheel_diff_l298n_2"
    assert profile["gpio"]["fl_pwm"] == 12
    assert profile["gpio"]["rl_pwm"] == 18
    assert profile["gpio"]["fr_pwm"] == 13
    assert profile["gpio"]["rr_pwm"] == 26
    assert profile["drive_params"]["spin_speed_mult"] == 1.0


def test_mecanum_l298n_2_profile_resolves_four_wheel_gpio() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "config"
    reg = load_profile_registry(str(config_dir / "robot_instances.yaml"))
    reg["robots"]["robot_l298n_mecanum"] = {
        "control_type": "mecanum_drive",
        "control_interface": "mecanum_l298n_2",
    }

    profile = resolve_robot_profile(reg, "robot_l298n_mecanum")

    assert profile["control_type"] == "mecanum_drive"
    assert profile["control_interface"] == "mecanum_l298n_2"
    assert profile["drive_type"] == "mecanum"
    assert profile["gpio"]["fl_pwm"] == 12
    assert profile["gpio"]["fr_pwm"] == 13
    assert profile["gpio"]["rl_pwm"] == 18
    assert profile["gpio"]["rr_pwm"] == 26
    assert profile["hardware_params"]["pwm_ramp_ms"] == 40


def test_set_motor_mirrors_diff_command_to_four_l298n_channels(monkeypatch) -> None:
    fake_gpio = _FakeGpio()
    monkeypatch.setattr(hardware_interface, "GPIO_AVAILABLE", True)
    monkeypatch.setattr(hardware_interface, "GPIO", fake_gpio, raising=False)

    gpio_map = {
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
        "pwm_hz": 1000,
    }

    hw = HardwareInterface(gpio_map)
    hw.set_motor(left_duty=55.0, left_dir=1, right_duty=66.0, right_dir=-1)

    assert fake_gpio.outputs[5] == fake_gpio.HIGH
    assert fake_gpio.outputs[6] == fake_gpio.LOW
    assert fake_gpio.outputs[20] == fake_gpio.HIGH
    assert fake_gpio.outputs[21] == fake_gpio.LOW
    assert fake_gpio.outputs[16] == fake_gpio.LOW
    assert fake_gpio.outputs[19] == fake_gpio.HIGH
    assert fake_gpio.outputs[23] == fake_gpio.LOW
    assert fake_gpio.outputs[24] == fake_gpio.HIGH

    assert fake_gpio.pwms[12].duty_cycles[-1] == 55.0
    assert fake_gpio.pwms[18].duty_cycles[-1] == 55.0
    assert fake_gpio.pwms[13].duty_cycles[-1] == 66.0
    assert fake_gpio.pwms[26].duty_cycles[-1] == 66.0


def test_set_mecanum_honors_per_wheel_inversion(monkeypatch) -> None:
    fake_gpio = _FakeGpio()
    monkeypatch.setattr(hardware_interface, "GPIO_AVAILABLE", True)
    monkeypatch.setattr(hardware_interface, "GPIO", fake_gpio, raising=False)

    gpio_map = {
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
        "invert_rl": True,
        "invert_rr": True,
        "pwm_hz": 1000,
    }

    hw = HardwareInterface(gpio_map)
    hw.set_mecanum(
        fl_duty=25.0,
        fl_dir=1,
        fr_duty=25.0,
        fr_dir=-1,
        rl_duty=25.0,
        rl_dir=1,
        rr_duty=25.0,
        rr_dir=-1,
    )

    assert fake_gpio.outputs[5] == fake_gpio.HIGH
    assert fake_gpio.outputs[16] == fake_gpio.LOW
    assert fake_gpio.outputs[20] == fake_gpio.LOW
    assert fake_gpio.outputs[23] == fake_gpio.HIGH


def test_motor_driver_normalization_preserves_four_channel_diff_map() -> None:
    pytest.importorskip("rclpy")
    from swarm_control_core.motor_driver_node import MotorDriverNode

    gpio_map = {
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
    }

    normalized = MotorDriverNode._normalize_gpio_map(object(), gpio_map, "diff_drive")

    assert normalized["fl_pwm"] == 12
    assert normalized["rl_pwm"] == 18
    assert normalized["fr_pwm"] == 13
    assert normalized["rr_pwm"] == 26
