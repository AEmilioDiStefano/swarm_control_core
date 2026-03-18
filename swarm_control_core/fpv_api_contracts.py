#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
fpv_api_contracts.py

API contract constants and payload validators for browser FPV endpoints.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from .fleet_contracts import fleet_contract_manifest


API_SCHEMA_VERSION = "v1"
ROBOT_CAPABILITY_SCHEMA = "swarm_control_core.robot_capabilities.v1"
ROBOT_HEALTH_SCHEMA = "swarm_control_core.robot_health.v1"

VALID_HEALTH_STATES = frozenset(("live", "degraded", "stale", "no_frame"))


def api_schema_info() -> dict:
    return {
        "schema_version": API_SCHEMA_VERSION,
        "schemas": {
            "robot_capabilities": ROBOT_CAPABILITY_SCHEMA,
            "robot_health": ROBOT_HEALTH_SCHEMA,
        },
        "fleet_contract": fleet_contract_manifest(),
    }


def validate_robot_capability(payload: Mapping[str, Any]) -> Tuple[bool, str]:
    required_bool = ("can_strafe", "can_vertical", "can_yaw")
    required_float = ("teleop_linear_mps", "teleop_angular_rps")
    required_text = ("control_profile", "drive_type", "hardware")

    for key in required_bool:
        if key not in payload:
            return False, f"missing:{key}"
        if not isinstance(payload.get(key), bool):
            return False, f"type:{key}:bool"

    for key in required_float:
        if key not in payload:
            return False, f"missing:{key}"
        try:
            float(payload.get(key))
        except Exception:
            return False, f"type:{key}:float"

    for key in required_text:
        if not str(payload.get(key, "")).strip():
            return False, f"missing:{key}"

    return True, ""


def validate_robot_health(payload: Mapping[str, Any]) -> Tuple[bool, str]:
    topic = str(payload.get("topic", "")).strip()
    if not topic:
        return False, "missing:topic"

    if "has_frame" not in payload or not isinstance(payload.get("has_frame"), bool):
        return False, "type:has_frame:bool"

    status = str(payload.get("status", "")).strip().lower()
    if status not in VALID_HEALTH_STATES:
        return False, "value:status"

    if "publisher_count" in payload:
        try:
            int(payload.get("publisher_count"))
        except Exception:
            return False, "type:publisher_count:int"

    return True, ""
