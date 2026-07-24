#!/usr/bin/env python3
"""
Safety-default resolution tests for the motor driver.

The in-place-rotate ramp/deadband bypass skips slew and deadband protection on
the motor path, so its profile default must be opt-in: an absent
allow_rotate_bypass_safety key resolves to False, and only an explicit
profile declaration enables it. (Historical default was True; flipped as a
safety hardening — PROGRESS.md BLS-07.)
"""

from swarm_control_core.motor_driver_node import _resolve_rotate_bypass_default


def test_absent_key_defaults_to_no_bypass():
    """An unset allow_rotate_bypass_safety must resolve to False (opt-in)."""
    assert _resolve_rotate_bypass_default({}) is False


def test_explicit_true_enables_bypass():
    """A profile may still opt in explicitly."""
    assert _resolve_rotate_bypass_default({"allow_rotate_bypass_safety": True}) is True


def test_explicit_false_stays_disabled():
    """An explicit False stays disabled."""
    assert _resolve_rotate_bypass_default({"allow_rotate_bypass_safety": False}) is False
