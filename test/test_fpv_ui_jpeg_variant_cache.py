#!/usr/bin/env python3

from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def test_fpv_ui_offloads_transformed_jpeg_generation_and_caches_variants():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "asyncio.to_thread(" in text
    assert "_encode_rgb_to_jpeg_variant" in text
    assert "def get_cached_jpeg_variant(" in text
    assert "def cache_jpeg_variant(" in text
    assert "self._jpeg_variant_cache" in text
    assert "self._jpeg_variant_cache_stamp" in text
    assert "cached_variant = self.hub.get_cached_jpeg_variant(" in text
    assert "self.hub.cache_jpeg_variant(" in text
