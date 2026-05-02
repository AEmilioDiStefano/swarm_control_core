#!/usr/bin/env python3
"""
Gateway route descriptors for Swarm FPV sessions.

These helpers describe how an operator reaches a robot without requiring the
browser UI to know whether the robot is local-DDS-only, behind a gateway, or
eventually direct-connected through a cloud hub.
"""

from __future__ import annotations

import os
import socket
from typing import Any, Dict, Iterable, Mapping, Optional, Set


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_gateway_id(value: Any, *, fallback: Optional[str] = None) -> str:
    raw = _clean(value) or _clean(fallback) or _clean(socket.gethostname()) or "local-gateway"
    safe = []
    for ch in raw.lower():
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        elif ch.isspace():
            safe.append("-")
    out = "".join(safe).strip("-._")
    return out or "local-gateway"


def first_env(names: Iterable[str], default: str = "") -> str:
    for name in names:
        value = _clean(os.environ.get(name))
        if value:
            return value
    return default


def gateway_identity_from_env(
    *,
    prefixes: Iterable[str] = ("SWARM_CORE",),
    default_role: str = "local_gateway",
    default_route_type: str = "local_gateway",
) -> Dict[str, str]:
    prefix_list = [str(prefix or "").strip().upper() for prefix in prefixes if str(prefix or "").strip()]
    hostname = _clean(socket.gethostname()) or "local-gateway"
    id_names = [f"{prefix}_GATEWAY_ID" for prefix in prefix_list]
    name_names = [f"{prefix}_GATEWAY_NAME" for prefix in prefix_list]
    role_names = [f"{prefix}_GATEWAY_ROLE" for prefix in prefix_list]
    route_names = [f"{prefix}_GATEWAY_ROUTE_TYPE" for prefix in prefix_list]
    hub_names = [f"{prefix}_HUB_URL" for prefix in prefix_list]
    site_names = [f"{prefix}_SITE_ID" for prefix in prefix_list]

    gateway_id = normalize_gateway_id(first_env(id_names, hostname), fallback=hostname)
    return {
        "id": gateway_id,
        "name": first_env(name_names, hostname),
        "role": first_env(role_names, default_role),
        "route_type": first_env(route_names, default_route_type),
        "hub_url": first_env(hub_names, ""),
        "site_id": first_env(site_names, ""),
    }


def build_gateway_public(
    *,
    gateway_id: Any = "",
    gateway_name: Any = "",
    gateway_role: Any = "local_gateway",
    route_type: Any = "local_gateway",
    hub_url: Any = "",
    site_id: Any = "",
) -> Dict[str, Any]:
    gateway_id_clean = normalize_gateway_id(gateway_id, fallback=gateway_name)
    return {
        "id": gateway_id_clean,
        "name": _clean(gateway_name) or gateway_id_clean,
        "role": _clean(gateway_role) or "local_gateway",
        "route_type": _clean(route_type) or "local_gateway",
        "hub_url": _clean(hub_url),
        "site_id": _clean(site_id),
        "managed_by": "swarm_control_gateway",
    }


def build_local_gateway_robot_route(
    robot: Any,
    *,
    gateway: Mapping[str, Any],
    live: bool = False,
    visible: bool = True,
    trusted: bool = False,
    control_allowed: bool = False,
) -> Dict[str, Any]:
    robot_name = _clean(robot)
    gateway_id = _clean(gateway.get("id")) or "local-gateway"
    gateway_name = _clean(gateway.get("name")) or gateway_id
    route_status = "live" if live else ("visible_stale" if visible else "offline")
    return {
        "robot": robot_name,
        "route_type": "local_gateway",
        "route_status": route_status,
        "preferred": True,
        "active": bool(live),
        "visible": bool(visible),
        "trusted": bool(trusted),
        "control_allowed": bool(control_allowed),
        "gateway_id": gateway_id,
        "gateway_name": gateway_name,
        "gateway_role": _clean(gateway.get("role")) or "local_gateway",
        "control_plane": "local_ros2_dds",
        "data_plane": "local_ros2_dds",
        "video_plane": "local_ros2_dds_to_ui_webrtc",
        "discovery_plane": "local_ros2_dds_topic_graph",
        "direct_agent": False,
        "hub_url": _clean(gateway.get("hub_url")),
    }


def build_local_gateway_routes(
    *,
    robots: Iterable[Any],
    live_robots: Iterable[Any],
    gateway: Mapping[str, Any],
    trusted_robots: Optional[Iterable[Any]] = None,
    control_allowed_robots: Optional[Iterable[Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    live_set: Set[str] = {_clean(robot) for robot in live_robots if _clean(robot)}
    trusted_set: Set[str] = {_clean(robot) for robot in (trusted_robots or []) if _clean(robot)}
    control_set: Set[str] = {_clean(robot) for robot in (control_allowed_robots or []) if _clean(robot)}
    out: Dict[str, Dict[str, Any]] = {}
    for robot in robots:
        robot_name = _clean(robot)
        if not robot_name:
            continue
        out[robot_name] = build_local_gateway_robot_route(
            robot_name,
            gateway=gateway,
            live=robot_name in live_set,
            visible=True,
            trusted=robot_name in trusted_set,
            control_allowed=robot_name in control_set,
        )
    return out
