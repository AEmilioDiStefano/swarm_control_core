#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
fleet_state.py

Additive builders for fleet-contract payloads generated from current
runtime state.
"""

from __future__ import annotations

from typing import Any, Mapping

from .fleet_contracts import (
    SCHEMA_ROBOT_HEALTH,
    SCHEMA_ROBOT_REGISTRY,
    SCHEMA_ROBOT_STATE,
    apply_defaults,
    build_envelope,
    normalize_capabilities,
)


def infer_capabilities_from_robot_caps(robot_caps: Mapping[str, Any]) -> list[str]:
    """
    Convert UI robot_caps shape into normalized capability vocabulary.
    """
    capabilities = ["navigation", "teleop"]

    can_strafe = bool(robot_caps.get("can_strafe", False))
    can_vertical = bool(robot_caps.get("can_vertical", False))
    if can_strafe:
        capabilities.append("obstacle_avoidance")
    if can_vertical:
        capabilities.append("mapping")

    # Camera-backed UI implies video capability.
    capabilities.append("video")
    return normalize_capabilities(capabilities)


def build_robot_registry_event(
    *,
    robot: str,
    source: str,
    robot_caps: Mapping[str, Any],
    profile: str = "",
    drive_type: str = "",
    hardware: str = "",
) -> dict:
    payload = {
        "robot": str(robot or "").strip(),
        "profile": str(profile or "").strip(),
        "drive_type": str(drive_type or "").strip(),
        "hardware": str(hardware or "").strip(),
        "capabilities": infer_capabilities_from_robot_caps(robot_caps),
    }
    apply_defaults(payload)
    return build_envelope(SCHEMA_ROBOT_REGISTRY, source, payload)


def build_robot_state_event(
    *,
    robot: str,
    source: str,
    control_mode: str = "manual",
    active: bool = False,
    lock_owner: str = "",
) -> dict:
    payload = {
        "robot": str(robot or "").strip(),
        "control_mode": str(control_mode or "").strip() or "manual",
        "active": bool(active),
        "lock_owner": str(lock_owner or "").strip(),
    }
    apply_defaults(payload)
    return build_envelope(SCHEMA_ROBOT_STATE, source, payload)


def build_robot_health_event(
    *,
    robot: str,
    source: str,
    robot_health: Mapping[str, Any],
) -> dict:
    status = str(robot_health.get("status", "")).strip().lower()
    readiness = "ready"
    failure_state = "none"
    if status in ("degraded", "stale", "no_frame"):
        readiness = "degraded"
    if status == "no_frame":
        failure_state = "recoverable"

    payload = {
        "robot": str(robot or "").strip(),
        "readiness": readiness,
        "failure_state": failure_state,
        "camera_status": status or "unknown",
        "camera_topic": str(robot_health.get("topic", "")).strip(),
        "has_frame": bool(robot_health.get("has_frame", False)),
        "publisher_count": int(robot_health.get("publisher_count", 0) or 0),
    }
    apply_defaults(payload)
    return build_envelope(SCHEMA_ROBOT_HEALTH, source, payload)
