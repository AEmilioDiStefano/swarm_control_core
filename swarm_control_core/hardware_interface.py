#!/usr/bin/env python3
"""
hardware_interface.py

Thin hardware abstraction layer for motor outputs.

Goals:
- Provide a consistent API for setting motor directions and PWM duty
- Allow a safe mock implementation when RPi.GPIO is not available (desktop)
- Keep behavior simple and well-documented for new engineers

Usage:
  from swarm_control_core.hardware_interface import HardwareInterface
  hw = HardwareInterface(gpio_map)
  hw.set_motor(left_duty, left_dir, right_duty, right_dir)
  hw.stop()

The gpio_map is a mapping of expected keys (names are flexible, see
drive_profiles.yaml) such as:
  {
    "en_left": 12,
    "in1_left": 23,
    "in2_left": 22,
    "en_right": 13,
    "in1_right": 27,
    "in2_right": 17,
  }

This module intentionally keeps hardware logic separated from motor mixing
so drive-type code can remain device-agnostic.
"""

from typing import Dict, Optional
import logging
import time

try:
    import RPi.GPIO as GPIO  # type: ignore
    GPIO_AVAILABLE = True
except Exception:
    GPIO_AVAILABLE = False

LOG = logging.getLogger("hardware_interface")


class HardwareInterface:
    """Abstraction for H-bridge motor outputs.

    This implementation focuses on the common H-bridge configurations used
    in our profiles. It exposes a minimal API so other modules need not
    import or depend on RPi.GPIO directly.
    """

    def __init__(self, gpio_map: Optional[Dict[str, int]] = None):
        self.gpio_map = gpio_map or {}
        self.left_pwm = None
        self.right_pwm = None
        self.pwm_hz = int(self.gpio_map.get("pwm_hz") or 1000)
        self.pwm_ramp_ms = float(self.gpio_map.get("pwm_ramp_ms") or 0.0)
        self.pwm_slew_pct_per_s = float(self.gpio_map.get("pwm_slew_pct_per_s") or 0.0)
        self._cur_left_duty = 0.0
        self._cur_right_duty = 0.0
        self._cur_fl_duty = 0.0
        self._cur_fr_duty = 0.0
        self._cur_rl_duty = 0.0
        self._cur_rr_duty = 0.0
        self._last_update = time.monotonic()
        # Allow side-level and per-wheel polarity inversion via profile flags.
        # Side-level flags preserve existing diff-drive behavior; per-wheel flags
        # let wheel-test calibration correct one miswired H-bridge channel.
        self.invert_left = self._bool_from_keys("invert_left", "left_inverted", "left_polarity_invert")
        self.invert_right = self._bool_from_keys("invert_right", "right_inverted", "right_polarity_invert")
        self.invert_fl = self.invert_left or self._bool_from_keys("invert_fl", "fl_inverted", "front_left_inverted")
        self.invert_rl = self.invert_left or self._bool_from_keys("invert_rl", "rl_inverted", "back_left_inverted", "rear_left_inverted", "bl_inverted", "invert_bl")
        self.invert_fr = self.invert_right or self._bool_from_keys("invert_fr", "fr_inverted", "front_right_inverted")
        self.invert_rr = self.invert_right or self._bool_from_keys("invert_rr", "rr_inverted", "back_right_inverted", "rear_right_inverted", "br_inverted", "invert_br")

        if GPIO_AVAILABLE and self.gpio_map:
            try:
                self._setup_gpio()
                LOG.info("GPIO hardware interface initialized")
                LOG.info(
                    "GPIO map keys: %s; invert_left=%s invert_right=%s invert_fl=%s invert_rl=%s invert_fr=%s invert_rr=%s",
                    list(self.gpio_map.keys()),
                    self.invert_left,
                    self.invert_right,
                    self.invert_fl,
                    self.invert_rl,
                    self.invert_fr,
                    self.invert_rr,
                )
            except Exception as e:
                LOG.warning("GPIO init failed: %s", e)
                self._mock_mode()
        else:
            self._mock_mode()

    def _bool_from_keys(self, *keys: str) -> bool:
        for key in keys:
            value = self.gpio_map.get(key)
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, (int, float)):
                if value != 0:
                    return True
                continue
            text = str(value or "").strip().lower()
            if text in ("1", "true", "yes", "y", "on"):
                return True
        return False

    @staticmethod
    def _apply_invert(direction: int, invert: bool) -> int:
        return -direction if invert else direction

    def _mock_mode(self):
        """Fallback that doesn't touch hardware; logs instead.
        This makes the package runnable on a laptop for development/testing.
        """
        self._mock = True
        if not GPIO_AVAILABLE:
            LOG.warning("RPi.GPIO not available - using mock hardware interface")
        else:
            LOG.warning("GPIO map empty - using mock hardware interface")

    def _setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # collect pins we expect for 2-channel and mirrored 4-channel H-bridges
        pins = [
            self.gpio_map.get("in1_left"),
            self.gpio_map.get("in2_left"),
            self.gpio_map.get("in1_right"),
            self.gpio_map.get("in2_right"),
            self.gpio_map.get("en_left"),
            self.gpio_map.get("en_right"),
            self.gpio_map.get("fl_in1"),
            self.gpio_map.get("fl_in2"),
            self.gpio_map.get("fr_in1"),
            self.gpio_map.get("fr_in2"),
            self.gpio_map.get("rl_in1"),
            self.gpio_map.get("rl_in2"),
            self.gpio_map.get("rr_in1"),
            self.gpio_map.get("rr_in2"),
            self.gpio_map.get("fl_pwm"),
            self.gpio_map.get("fr_pwm"),
            self.gpio_map.get("rl_pwm"),
            self.gpio_map.get("rr_pwm"),
        ]
        pins = [p for p in pins if p is not None]

        for pin in pins:
            GPIO.setup(pin, GPIO.OUT)

        # PWM channels
        if self.gpio_map.get("en_left") is not None and self.gpio_map.get("en_right") is not None:
            self.left_pwm = GPIO.PWM(self.gpio_map.get("en_left"), self.pwm_hz)
            self.right_pwm = GPIO.PWM(self.gpio_map.get("en_right"), self.pwm_hz)
            self.left_pwm.start(0)
            self.right_pwm.start(0)
        else:
            self.left_pwm = None
            self.right_pwm = None

        if self.gpio_map.get("fl_pwm") is not None:
            self.fl_pwm = GPIO.PWM(self.gpio_map.get("fl_pwm"), self.pwm_hz)
            self.fl_pwm.start(0)
        else:
            self.fl_pwm = None
        if self.gpio_map.get("fr_pwm") is not None:
            self.fr_pwm = GPIO.PWM(self.gpio_map.get("fr_pwm"), self.pwm_hz)
            self.fr_pwm.start(0)
        else:
            self.fr_pwm = None
        if self.gpio_map.get("rl_pwm") is not None:
            self.rl_pwm = GPIO.PWM(self.gpio_map.get("rl_pwm"), self.pwm_hz)
            self.rl_pwm.start(0)
        else:
            self.rl_pwm = None
        if self.gpio_map.get("rr_pwm") is not None:
            self.rr_pwm = GPIO.PWM(self.gpio_map.get("rr_pwm"), self.pwm_hz)
            self.rr_pwm.start(0)
        else:
            self.rr_pwm = None
        self._mock = False

    def set_motor(self, left_duty: float, left_dir: int, right_duty: float, right_dir: int, bypass_ramp: bool = False):
        """Set motor outputs.

        left_dir/right_dir: 1 for forward, -1 for reverse
        duty: 0..100
        """
        if getattr(self, "_mock", True):
            LOG.debug("MOCK set_motor: L(duty=%s,dir=%s) R(duty=%s,dir=%s)", left_duty, left_dir, right_duty, right_dir)
            return

        left_side_dir = self._apply_invert(left_dir, self.invert_left)
        right_side_dir = self._apply_invert(right_dir, self.invert_right)
        fl_dir = self._apply_invert(left_dir, self.invert_fl)
        rl_dir = self._apply_invert(left_dir, self.invert_rl)
        fr_dir = self._apply_invert(right_dir, self.invert_fr)
        rr_dir = self._apply_invert(right_dir, self.invert_rr)

        # Soft-start ramp / slew limiter (limits duty change per call)
        if not bypass_ramp and ((self.pwm_ramp_ms and self.pwm_ramp_ms > 0) or (self.pwm_slew_pct_per_s and self.pwm_slew_pct_per_s > 0)):
            now = time.monotonic()
            dt = max(0.0, now - self._last_update)
            self._last_update = now
            ramp_rate = 0.0
            if self.pwm_ramp_ms and self.pwm_ramp_ms > 0:
                ramp_rate = 100.0 / (self.pwm_ramp_ms / 1000.0)
            slew_rate = float(self.pwm_slew_pct_per_s or 0.0)
            if ramp_rate and slew_rate:
                rate_per_sec = min(ramp_rate, slew_rate)
            else:
                rate_per_sec = ramp_rate or slew_rate

            max_delta = rate_per_sec * dt if rate_per_sec > 0 else 100.0

            def _ramp(cur, target):
                if target > cur:
                    return min(target, cur + max_delta)
                if target < cur:
                    return max(target, cur - max_delta)
                return cur

            self._cur_left_duty = _ramp(self._cur_left_duty, float(left_duty))
            self._cur_right_duty = _ramp(self._cur_right_duty, float(right_duty))
        else:
            # Bypass ramp/slew (immediate response)
            if bypass_ramp:
                self._last_update = time.monotonic()
            self._cur_left_duty = float(left_duty)
            self._cur_right_duty = float(right_duty)

        def _set_dir(pin1, pin2, direction):
            if pin1 is None or pin2 is None:
                return
            GPIO.output(pin1, GPIO.HIGH if direction > 0 else GPIO.LOW)
            GPIO.output(pin2, GPIO.LOW if direction > 0 else GPIO.HIGH)

        def _set_pwm(pwm, duty):
            if pwm is None:
                return
            pwm.ChangeDutyCycle(max(0.0, min(100.0, float(duty))))

        _set_dir(self.gpio_map.get("in1_left"), self.gpio_map.get("in2_left"), left_side_dir)
        _set_dir(self.gpio_map.get("in1_right"), self.gpio_map.get("in2_right"), right_side_dir)
        _set_pwm(self.left_pwm, self._cur_left_duty)
        _set_pwm(self.right_pwm, self._cur_right_duty)

        _set_dir(self.gpio_map.get("fl_in1"), self.gpio_map.get("fl_in2"), fl_dir)
        _set_dir(self.gpio_map.get("rl_in1"), self.gpio_map.get("rl_in2"), rl_dir)
        _set_dir(self.gpio_map.get("fr_in1"), self.gpio_map.get("fr_in2"), fr_dir)
        _set_dir(self.gpio_map.get("rr_in1"), self.gpio_map.get("rr_in2"), rr_dir)
        _set_pwm(getattr(self, "fl_pwm", None), self._cur_left_duty)
        _set_pwm(getattr(self, "rl_pwm", None), self._cur_left_duty)
        _set_pwm(getattr(self, "fr_pwm", None), self._cur_right_duty)
        _set_pwm(getattr(self, "rr_pwm", None), self._cur_right_duty)

    def set_mecanum(
        self,
        fl_duty: float, fl_dir: int,
        fr_duty: float, fr_dir: int,
        rl_duty: float, rl_dir: int,
        rr_duty: float, rr_dir: int,
        bypass_ramp: bool = False,
    ):
        """Set outputs for a 4-channel mecanum/omni drivetrain."""
        if getattr(self, "_mock", True):
            LOG.debug(
                "MOCK set_mecanum: FL(duty=%s,dir=%s) FR(duty=%s,dir=%s) RL(duty=%s,dir=%s) RR(duty=%s,dir=%s)",
                fl_duty, fl_dir, fr_duty, fr_dir, rl_duty, rl_dir, rr_duty, rr_dir,
            )
            return

        fl_dir = self._apply_invert(fl_dir, self.invert_fl)
        rl_dir = self._apply_invert(rl_dir, self.invert_rl)
        fr_dir = self._apply_invert(fr_dir, self.invert_fr)
        rr_dir = self._apply_invert(rr_dir, self.invert_rr)

        # Hard-stop path: when all targets are zero, bypass ramp/slew so stop is immediate.
        # This prevents short residual motion at command end on mecanum platforms.
        all_zero = (
            abs(float(fl_duty)) < 1e-9
            and abs(float(fr_duty)) < 1e-9
            and abs(float(rl_duty)) < 1e-9
            and abs(float(rr_duty)) < 1e-9
        )

        # Soft-start ramp / slew limiter (limits duty change per call)
        if (not bypass_ramp) and (not all_zero) and (
            (self.pwm_ramp_ms and self.pwm_ramp_ms > 0)
            or (self.pwm_slew_pct_per_s and self.pwm_slew_pct_per_s > 0)
        ):
            now = time.monotonic()
            dt = max(0.0, now - self._last_update)
            self._last_update = now
            ramp_rate = 0.0
            if self.pwm_ramp_ms and self.pwm_ramp_ms > 0:
                ramp_rate = 100.0 / (self.pwm_ramp_ms / 1000.0)
            slew_rate = float(self.pwm_slew_pct_per_s or 0.0)
            if ramp_rate and slew_rate:
                rate_per_sec = min(ramp_rate, slew_rate)
            else:
                rate_per_sec = ramp_rate or slew_rate

            max_delta = rate_per_sec * dt if rate_per_sec > 0 else 100.0

            def _ramp(cur, target):
                if target > cur:
                    return min(target, cur + max_delta)
                if target < cur:
                    return max(target, cur - max_delta)
                return cur

            self._cur_fl_duty = _ramp(self._cur_fl_duty, float(fl_duty))
            self._cur_fr_duty = _ramp(self._cur_fr_duty, float(fr_duty))
            self._cur_rl_duty = _ramp(self._cur_rl_duty, float(rl_duty))
            self._cur_rr_duty = _ramp(self._cur_rr_duty, float(rr_duty))
        else:
            if bypass_ramp or all_zero:
                self._last_update = time.monotonic()
            self._cur_fl_duty = float(fl_duty)
            self._cur_fr_duty = float(fr_duty)
            self._cur_rl_duty = float(rl_duty)
            self._cur_rr_duty = float(rr_duty)

        # Direction pins
        def _set_dir(pin1, pin2, direction):
            if pin1 is None or pin2 is None:
                return
            GPIO.output(pin1, GPIO.HIGH if direction > 0 else GPIO.LOW)
            GPIO.output(pin2, GPIO.LOW if direction > 0 else GPIO.HIGH)

        _set_dir(self.gpio_map.get("fl_in1"), self.gpio_map.get("fl_in2"), fl_dir)
        _set_dir(self.gpio_map.get("fr_in1"), self.gpio_map.get("fr_in2"), fr_dir)
        _set_dir(self.gpio_map.get("rl_in1"), self.gpio_map.get("rl_in2"), rl_dir)
        _set_dir(self.gpio_map.get("rr_in1"), self.gpio_map.get("rr_in2"), rr_dir)

        # PWM duty
        if self.fl_pwm is not None:
            self.fl_pwm.ChangeDutyCycle(max(0.0, min(100.0, float(self._cur_fl_duty))))
        if self.fr_pwm is not None:
            self.fr_pwm.ChangeDutyCycle(max(0.0, min(100.0, float(self._cur_fr_duty))))
        if self.rl_pwm is not None:
            self.rl_pwm.ChangeDutyCycle(max(0.0, min(100.0, float(self._cur_rl_duty))))
        if self.rr_pwm is not None:
            self.rr_pwm.ChangeDutyCycle(max(0.0, min(100.0, float(self._cur_rr_duty))))
    def stop(self):
        """Stop motors and cleanup if using real GPIO"""
        if getattr(self, "_mock", True):
            LOG.debug("MOCK stop called")
            return
        try:
            if self.left_pwm is not None:
                self.left_pwm.stop()
            if self.right_pwm is not None:
                self.right_pwm.stop()
            if getattr(self, "fl_pwm", None) is not None:
                self.fl_pwm.stop()
            if getattr(self, "fr_pwm", None) is not None:
                self.fr_pwm.stop()
            if getattr(self, "rl_pwm", None) is not None:
                self.rl_pwm.stop()
            if getattr(self, "rr_pwm", None) is not None:
                self.rr_pwm.stop()
            GPIO.cleanup()
        except Exception as e:
            LOG.warning("Error cleaning up GPIO: %s", e)
