#!/usr/bin/env python3

from swarm_control_core.camera_runtime_defaults import choose_adaptive_jpeg_quality


def test_adaptive_jpeg_quality_holds_when_disabled() -> None:
    out = choose_adaptive_jpeg_quality(
        enabled=False,
        current_quality=70,
        target_quality=70,
        min_quality=45,
        step=5,
        frame_period_s=1.0 / 15.0,
        cycle_elapsed_s=0.20,
        encode_elapsed_s=0.10,
        now_s=10.0,
        last_pressure_s=0.0,
        last_adjust_s=0.0,
        overload_ratio=0.85,
        encode_ratio=0.55,
        recover_after_s=6.0,
    )
    assert out == (70, 0.0, 0.0, "disabled")


def test_adaptive_jpeg_quality_steps_down_under_budget_pressure() -> None:
    next_quality, pressure_s, adjust_s, action = choose_adaptive_jpeg_quality(
        enabled=True,
        current_quality=70,
        target_quality=70,
        min_quality=45,
        step=5,
        frame_period_s=1.0 / 15.0,
        cycle_elapsed_s=0.08,
        encode_elapsed_s=0.05,
        now_s=20.0,
        last_pressure_s=0.0,
        last_adjust_s=0.0,
        overload_ratio=0.85,
        encode_ratio=0.55,
        recover_after_s=6.0,
    )
    assert next_quality == 65
    assert pressure_s == 20.0
    assert adjust_s == 20.0
    assert action == "decrease"


def test_adaptive_jpeg_quality_recovers_after_healthy_window() -> None:
    next_quality, pressure_s, adjust_s, action = choose_adaptive_jpeg_quality(
        enabled=True,
        current_quality=55,
        target_quality=70,
        min_quality=45,
        step=5,
        frame_period_s=1.0 / 15.0,
        cycle_elapsed_s=0.01,
        encode_elapsed_s=0.004,
        now_s=40.0,
        last_pressure_s=30.0,
        last_adjust_s=30.0,
        overload_ratio=0.85,
        encode_ratio=0.55,
        recover_after_s=6.0,
    )
    assert next_quality == 60
    assert pressure_s == 30.0
    assert adjust_s == 40.0
    assert action == "increase"


def test_adaptive_jpeg_quality_respects_floor() -> None:
    next_quality, pressure_s, adjust_s, action = choose_adaptive_jpeg_quality(
        enabled=True,
        current_quality=45,
        target_quality=70,
        min_quality=45,
        step=5,
        frame_period_s=1.0 / 15.0,
        cycle_elapsed_s=0.09,
        encode_elapsed_s=0.06,
        now_s=50.0,
        last_pressure_s=10.0,
        last_adjust_s=10.0,
        overload_ratio=0.85,
        encode_ratio=0.55,
        recover_after_s=6.0,
    )
    assert next_quality == 45
    assert pressure_s == 50.0
    assert adjust_s == 10.0
    assert action == "hold_over_budget"
