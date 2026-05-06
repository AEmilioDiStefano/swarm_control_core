#!/usr/bin/env python3

from swarm_control_core.gateway_routes import (
    build_gateway_public,
    build_local_gateway_routes,
    gateway_identity_from_env,
    normalize_gateway_id,
)


def test_normalize_gateway_id_is_url_and_topic_safe():
    assert normalize_gateway_id("Field Hub 01!") == "field-hub-01"
    assert normalize_gateway_id("", fallback="MR Roboto") == "mr-roboto"


def test_gateway_identity_prefers_env_prefix_order(monkeypatch):
    monkeypatch.setenv("SWARM_CORE_GATEWAY_ID", "core-hub")
    monkeypatch.setenv("SWARM_CORE_GATEWAY_NAME", "Core Hub")

    ident = gateway_identity_from_env(prefixes=("SWARM_CORE",))

    assert ident["id"] == "core-hub"
    assert ident["name"] == "Core Hub"
    assert ident["role"] == "local_gateway"
    assert ident["route_type"] == "local_gateway"


def test_local_gateway_routes_mark_live_and_control_allowed():
    gateway = build_gateway_public(
        gateway_id="base-01",
        gateway_name="Local Base 01",
        gateway_role="local_gateway",
    )

    routes = build_local_gateway_routes(
        robots=["robot4", "robot5"],
        live_robots=["robot5"],
        gateway=gateway,
        trusted_robots=["robot4", "robot5"],
        control_allowed_robots=["robot5"],
    )

    assert routes["robot5"]["route_status"] == "live"
    assert routes["robot5"]["gateway_name"] == "Local Base 01"
    assert routes["robot5"]["control_allowed"] is True
    assert routes["robot5"]["video_plane"] == "local_ros2_dds_to_ui_webrtc"
    assert routes["robot4"]["route_status"] == "visible_stale"
    assert routes["robot4"]["control_allowed"] is False
