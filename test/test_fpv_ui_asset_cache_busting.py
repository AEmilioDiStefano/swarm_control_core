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


def test_core_ui_asset_version_constants_are_defined_after_asset_strings():
    text = UI_PATH.read_text(encoding="utf-8")

    assert text.index("_STYLE_CSS = r") < text.index("_STYLE_ASSET_VERSION = ")
    assert text.index("_APP_JS = r") < text.index("_APP_ASSET_VERSION = ")


def test_core_ui_supports_server_injected_default_main_stream():
    text = UI_PATH.read_text(encoding="utf-8")

    assert '<meta name="swarm-fpv-default-main-stream" content="{default_main_stream}"/>' in text
    assert '<meta name="swarm-fpv-jpeg-poll-ms" content="{default_jpeg_poll_ms}"/>' in text
    assert '<meta name="swarm-fpv-jpeg-max-w" content="{default_jpeg_max_w}"/>' in text
    assert '<meta name="swarm-fpv-jpeg-max-h" content="{default_jpeg_max_h}"/>' in text
    assert '<meta name="swarm-fpv-jpeg-quality" content="{default_jpeg_quality}"/>' in text
    assert "const defaultMainStreamMeta = document.querySelector('meta[name=\"swarm-fpv-default-main-stream\"]');" in text
    assert '|| defaultMainStream' in text
    assert 'SWARM_CORE_TRYCLOUDFLARE_MAIN_STREAM' in text
    assert 'req_host.endswith(".trycloudflare.com")' in text
    assert 'const jpegMainPollMs = Math.max(40, _toInt(defaultJpegPollMs, 120));' in text
    assert 'next.src = buildMainJpegUrl(activeRobot);' in text
    assert 'max_w = _bounded_int(req.query.get("max_w")' in text
