#!/usr/bin/env python3

from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
STEP3_SCRIPT = CORE_ROOT / "scripts" / "swarm_core_quickstart_step3.sh"


def test_step3_preserves_cloudflare_ui_override_vars_across_reset():
    text = STEP3_SCRIPT.read_text(encoding="utf-8")

    assert 'SWARM_CORE_AUTH_MODE' in text
    assert 'SWARM_CORE_DEV_USERS_JSON' in text
    assert 'SWARM_CORE_WEBRTC_MAIN_ONLY' in text
    assert 'SWARM_CORE_FLEET_PREVIEW_PRESET' in text
    assert 'SWARM_CORE_GATEWAY_ID' in text
    assert 'SWARM_CORE_HUB_URL' in text
    assert 'declare -A preserved_env=()' in text
    assert 'export "$name=${preserved_env[$name]}"' in text


def test_step3_uses_defaults_only_when_ui_overrides_are_unset():
    text = STEP3_SCRIPT.read_text(encoding="utf-8")

    assert 'export SWARM_CORE_WEBRTC_FPS="${SWARM_CORE_WEBRTC_FPS:-15.0}"' in text
    assert 'export SWARM_CORE_FLEET_PREVIEW_PRESET="${SWARM_CORE_FLEET_PREVIEW_PRESET:-scalable_fleet}"' in text
    assert 'export SWARM_CORE_THUMB_REFRESH_HZ="${SWARM_CORE_THUMB_REFRESH_HZ:-1.0}"' in text
    assert 'export SWARM_CORE_IMAGE_SUBSCRIPTION_MODE="${SWARM_CORE_IMAGE_SUBSCRIPTION_MODE:-active_only}"' in text
    assert 'export SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S="${SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S:-2.5}"' in text
    assert 'export SWARM_CORE_THUMB_ROBOTS_PER_TICK="${SWARM_CORE_THUMB_ROBOTS_PER_TICK:-1}"' in text
    assert 'export SWARM_CORE_DRIVE_CMD_RATE_HZ="${SWARM_CORE_DRIVE_CMD_RATE_HZ:-20.0}"' in text
    assert 'export SWARM_CORE_DRIVE_HOLD_TIMEOUT_S="${SWARM_CORE_DRIVE_HOLD_TIMEOUT_S:-0.35}"' in text
