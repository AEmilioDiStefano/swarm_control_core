#!/usr/bin/env python3

from __future__ import annotations

from typing import List, Tuple


def apply_low_latency_camera_clamp(
    *,
    camera_source: str,
    enabled: bool,
    width: int,
    height: int,
    fps: int,
    fourcc: str,
    width_overridden: bool,
    height_overridden: bool,
    fps_overridden: bool,
    fourcc_overridden: bool,
) -> Tuple[int, int, int, str, List[str]]:
    """
    Clamp camera settings to low-latency-safe defaults for USB-like sources.

    The clamp is intentionally conservative and only applies when values are
    not explicitly overridden by operator launch args or environment overrides.
    """
    notes: List[str] = []
    source = str(camera_source or "").strip().lower()
    out_w = int(width)
    out_h = int(height)
    out_fps = int(fps)
    out_fourcc = str(fourcc or "").strip().upper()

    if (not enabled) or source == "csi":
        return out_w, out_h, out_fps, out_fourcc, notes

    safe_w = 640
    safe_h = 480
    safe_fps = 15
    safe_fourcc = "MJPG"

    if (not width_overridden) and (not height_overridden):
        if (out_w > safe_w) or (out_h > safe_h):
            out_w = safe_w
            out_h = safe_h
            notes.append("size")

    if (not fps_overridden) and (out_fps > safe_fps):
        out_fps = safe_fps
        notes.append("fps")

    if (not fourcc_overridden) and (out_fourcc != safe_fourcc):
        out_fourcc = safe_fourcc
        notes.append("fourcc")

    return out_w, out_h, out_fps, out_fourcc, notes


def choose_adaptive_jpeg_quality(
    *,
    enabled: bool,
    current_quality: int,
    target_quality: int,
    min_quality: int,
    step: int,
    frame_period_s: float,
    cycle_elapsed_s: float,
    encode_elapsed_s: float,
    now_s: float,
    last_pressure_s: float,
    last_adjust_s: float,
    overload_ratio: float,
    encode_ratio: float,
    recover_after_s: float,
    min_adjust_interval_s: float = 1.0,
) -> Tuple[int, float, float, str]:
    """
    Choose the next JPEG quality for a soft per-robot video budget.

    The goal is to preserve the current quality for healthy robots, while
    allowing a struggling robot to shed video load before it harms control or
    other robots' operator experience.

    Returns:
      (next_quality, next_last_pressure_s, next_last_adjust_s, action)
    """
    target = max(30, min(95, int(target_quality)))
    current = max(30, min(95, int(current_quality)))
    floor = max(30, min(target, int(min_quality)))
    step_size = max(1, int(step))
    frame_budget = max(0.001, float(frame_period_s))
    cycle_elapsed = max(0.0, float(cycle_elapsed_s))
    encode_elapsed = max(0.0, float(encode_elapsed_s))
    pressure_s = max(0.0, float(last_pressure_s))
    adjust_s = max(0.0, float(last_adjust_s))
    recover_window_s = max(0.5, float(recover_after_s))
    min_adjust_s = max(0.1, float(min_adjust_interval_s))
    overrun_ratio = max(0.1, float(overload_ratio))
    enc_ratio = max(0.05, float(encode_ratio))

    if (not enabled) or target <= floor:
        clamped = max(floor, min(target, current))
        return clamped, pressure_s, adjust_s, "disabled"

    over_budget = (
        cycle_elapsed >= (frame_budget * overrun_ratio)
        or encode_elapsed >= (frame_budget * enc_ratio)
    )

    if over_budget:
        pressure_s = max(pressure_s, now_s)
        if current > floor and (now_s - adjust_s) >= min_adjust_s:
            next_quality = max(floor, current - step_size)
            return next_quality, pressure_s, now_s, "decrease"
        return current, pressure_s, adjust_s, "hold_over_budget"

    if current < target:
        if (now_s - pressure_s) >= recover_window_s and (now_s - adjust_s) >= recover_window_s:
            next_quality = min(target, current + step_size)
            return next_quality, pressure_s, now_s, "increase"

    return current, pressure_s, adjust_s, "hold"
