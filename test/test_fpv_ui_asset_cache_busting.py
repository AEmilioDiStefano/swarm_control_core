#!/usr/bin/env python3

from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def test_core_ui_index_uses_cache_busted_asset_urls_and_no_cache_headers():
    text = UI_PATH.read_text(encoding="utf-8")

    assert '{style_href}' in text
    assert '{app_href}' in text
    assert 'style_href=f"/style.css?v={_STYLE_ASSET_VERSION}"' in text
    assert 'app_href=f"/app.js?v={_APP_ASSET_VERSION}"' in text
    assert 'headers=_no_cache_headers()' in text
