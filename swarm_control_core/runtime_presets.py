#!/usr/bin/env python3
"""
Named runtime presets for Swarm Control terminals.

Presets compress the many FPV/network environment variables into a few
operator-facing modes. They intentionally emit environment variables only;
existing scripts and launch files remain the execution layer.
"""

from __future__ import annotations

import json
from typing import Dict, Mapping


PRESETS: Dict[str, Dict[str, str]] = {
    "local_lab": {
        "SWARM_CORE_AUTH_MODE": "off",
        "SWARM_CORE_ALLOW_LAN_BIND": "0",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "scalable_fleet",
        "SWARM_CORE_GATEWAY_ROLE": "local_gateway",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "local_gateway",
    },
    "cloudflare_remote": {
        "SWARM_CORE_AUTH_MODE": "dev",
        "SWARM_CORE_ALLOW_ANON_READONLY": "false",
        "SWARM_CORE_DEV_LOGIN_ENABLED": "true",
        "SWARM_CORE_TRYCLOUDFLARE_MAIN_STREAM": "jpeg",
        "SWARM_CORE_TRYCLOUDFLARE_JPEG_POLL_MS": "160",
        "SWARM_CORE_TRYCLOUDFLARE_JPEG_MAX_W": "424",
        "SWARM_CORE_TRYCLOUDFLARE_JPEG_MAX_H": "318",
        "SWARM_CORE_TRYCLOUDFLARE_JPEG_QUALITY": "45",
        "SWARM_CORE_ROBOT_PRESENCE_TIMEOUT_S": "15.0",
        "SWARM_CORE_ROBOT_PRESENCE_BOOTSTRAP_GRACE_S": "8.0",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "scalable_fleet",
        "SWARM_CORE_GATEWAY_ROLE": "cloudflare_gateway",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "local_gateway",
    },
    "field_gateway": {
        "SWARM_CORE_AUTH_MODE": "dev",
        "SWARM_CORE_ALLOW_ANON_READONLY": "false",
        "SWARM_CORE_DEV_LOGIN_ENABLED": "true",
        "SWARM_CORE_ALLOW_LAN_BIND": "1",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "operator_focus",
        "SWARM_CORE_ROBOT_PRESENCE_TIMEOUT_S": "10.0",
        "SWARM_CORE_ROBOT_PRESENCE_BOOTSTRAP_GRACE_S": "5.0",
        "SWARM_CORE_GATEWAY_ROLE": "field_gateway",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "local_gateway",
    },
    "direct_robot_agent": {
        "SWARM_CORE_AUTH_MODE": "dev",
        "SWARM_CORE_ALLOW_ANON_READONLY": "false",
        "SWARM_CORE_DEV_LOGIN_ENABLED": "true",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "operator_focus",
        "SWARM_CORE_GATEWAY_ROLE": "direct_robot_agent",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "direct_robot_agent",
    },
    "large_fleet": {
        "SWARM_CORE_AUTH_MODE": "dev",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "scalable_fleet",
        "SWARM_CORE_THUMB_REFRESH_HZ": "0.5",
        "SWARM_CORE_IMAGE_SUBSCRIPTION_MODE": "active_only",
        "SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S": "2.5",
        "SWARM_CORE_THUMB_ROBOTS_PER_TICK": "1",
        "SWARM_CORE_GATEWAY_ROLE": "fleet_gateway",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "local_gateway",
    },
}


ALIASES = {
    "local": "local_lab",
    "lab": "local_lab",
    "cloudflare": "cloudflare_remote",
    "remote": "cloudflare_remote",
    "field": "field_gateway",
    "gateway": "field_gateway",
    "direct": "direct_robot_agent",
    "agent": "direct_robot_agent",
    "fleet": "large_fleet",
    "large": "large_fleet",
}


def normalize_preset_name(name: str) -> str:
    value = str(name or "").strip().lower().replace("-", "_")
    return ALIASES.get(value, value)


def list_preset_names() -> list[str]:
    return sorted(PRESETS)


def list_preset_choices() -> list[str]:
    return sorted(set(PRESETS) | set(ALIASES))


def resolve_preset(name: str, *, overrides: Mapping[str, str] | None = None) -> Dict[str, str]:
    preset_name = normalize_preset_name(name)
    if preset_name not in PRESETS:
        choices = ", ".join(list_preset_names())
        raise ValueError(f"Unknown preset '{name}'. Expected one of: {choices}")
    out = dict(PRESETS[preset_name])
    for key, value in dict(overrides or {}).items():
        clean_key = str(key or "").strip()
        if clean_key:
            out[clean_key] = str(value)
    return out


def pro_env_aliases(core_env: Mapping[str, str]) -> Dict[str, str]:
    mapping = {
        "SWARM_CORE_AUTH_MODE": "SWARM_FPV_AUTH_MODE",
        "SWARM_CORE_ALLOW_ANON_READONLY": "SWARM_FPV_ALLOW_ANON_READONLY",
        "SWARM_CORE_DEV_LOGIN_ENABLED": "SWARM_FPV_DEV_LOGIN_ENABLED",
        "SWARM_CORE_WEBRTC_FPS": "SWARM_FPV_WEBRTC_FPS",
        "SWARM_CORE_WEBRTC_MAIN_ONLY": "SWARM_FPV_WEBRTC_MAIN_ONLY",
        "SWARM_CORE_FLEET_PREVIEW_PRESET": "SWARM_FPV_FLEET_PREVIEW_PRESET",
        "SWARM_CORE_GATEWAY_ID": "SWARM_FPV_GATEWAY_ID",
        "SWARM_CORE_GATEWAY_NAME": "SWARM_FPV_GATEWAY_NAME",
        "SWARM_CORE_GATEWAY_ROLE": "SWARM_FPV_GATEWAY_ROLE",
        "SWARM_CORE_GATEWAY_ROUTE_TYPE": "SWARM_FPV_GATEWAY_ROUTE_TYPE",
        "SWARM_CORE_HUB_URL": "SWARM_FPV_HUB_URL",
        "SWARM_CORE_SITE_ID": "SWARM_FPV_SITE_ID",
    }
    return {target: str(core_env[source]) for source, target in mapping.items() if source in core_env}


def shell_exports(env: Mapping[str, str], *, include_pro_aliases: bool = False) -> str:
    merged = dict(env)
    if include_pro_aliases:
        merged.update(pro_env_aliases(merged))
    lines = []
    for key in sorted(merged):
        value = str(merged[key]).replace("'", "'\"'\"'")
        lines.append(f"export {key}='{value}'")
    return "\n".join(lines)


def json_env(env: Mapping[str, str], *, include_pro_aliases: bool = False) -> str:
    merged = dict(env)
    if include_pro_aliases:
        merged.update(pro_env_aliases(merged))
    return json.dumps(merged, indent=2, sort_keys=True)


def apply_env_to_mapping(env: Mapping[str, str], target: Dict[str, str]) -> Dict[str, str]:
    for key, value in env.items():
        target[str(key)] = str(value)
    return target
