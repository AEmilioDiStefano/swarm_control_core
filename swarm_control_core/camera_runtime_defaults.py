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

