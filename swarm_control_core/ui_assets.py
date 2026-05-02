#!/usr/bin/env python3
"""
Optional external asset loading for the FPV UI.

The current UI keeps embedded CSS/JS fallbacks so installed packages work with
no extra files. Setting ``SWARM_CORE_FPV_ASSET_DIR`` lets developers override
``style.css`` or ``app.js`` from disk while preserving the existing routes.
"""

from __future__ import annotations

import os
from pathlib import Path


def _safe_asset_name(name: str) -> str:
    asset = Path(str(name or "")).name
    if asset not in {"style.css", "app.js"}:
        raise ValueError(f"Unsupported FPV UI asset: {name!r}")
    return asset


def asset_text(name: str, fallback: str, *, env: dict[str, str] | None = None) -> str:
    asset = _safe_asset_name(name)
    source_env = os.environ if env is None else env
    asset_dir = str(source_env.get("SWARM_CORE_FPV_ASSET_DIR", "")).strip()
    if not asset_dir:
        return fallback
    candidate = Path(asset_dir).expanduser() / asset
    if not candidate.is_file():
        return fallback
    return candidate.read_text(encoding="utf-8")
