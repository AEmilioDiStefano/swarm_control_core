from __future__ import annotations

from typing import Any


def apply_frame_orientation(frame: Any, *, flip_horizontal: bool = False, flip_vertical: bool = False) -> Any:
    if flip_horizontal and flip_vertical:
        return frame[::-1, ::-1].copy()
    if flip_horizontal:
        return frame[:, ::-1].copy()
    if flip_vertical:
        return frame[::-1, :].copy()
    return frame
