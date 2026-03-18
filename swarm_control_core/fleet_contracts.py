#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
fleet_contracts.py

Formalized contract metadata and payload validators for the fleet-facing
boundary between control, orchestration, and adapters.

Design goals:
- Additive: does not replace current robot-scoped topics/actions.
- Explicit: standardized topic names, schema ids, and vocabularies.
- Testable: lightweight validators for conformance checks.
"""

from __future__ import annotations

from time import time
from typing import Any, Mapping, MutableMapping, Tuple


FLEET_CONTRACT_VERSION = "v1alpha1"

# Fleet topic namespace (forward-looking contract surface).
TOPIC_ROBOTS = "/fleet/robots"
TOPIC_ROBOT_STATE = "/fleet/robot_state"
TOPIC_ROBOT_HEALTH = "/fleet/robot_health"
TOPIC_COMMS_STATE = "/fleet/comms_state"
TOPIC_PAYLOAD_STATE = "/fleet/payload_state"
TOPIC_TASK_FEEDBACK = "/fleet/task_feedback"
TOPIC_VIDEO_STREAM_INFO = "/fleet/video_stream_info"
TOPIC_AUDIT_EVENTS = "/fleet/audit_events"
TOPIC_TELEOP_CMD = "/fleet/teleop_cmd"
TOPIC_TASK_ASSIGNMENT = "/fleet/task_assignment"
TOPIC_POLICY_CONSTRAINTS = "/fleet/policy_constraints"
TOPIC_CONTROL_MODE_REQUEST = "/fleet/control_mode_request"


SCHEMA_ROBOT_REGISTRY = "swarm_control_core.fleet.robot_registry.v1"
SCHEMA_ROBOT_STATE = "swarm_control_core.fleet.robot_state.v1"
SCHEMA_ROBOT_HEALTH = "swarm_control_core.fleet.robot_health.v1"
SCHEMA_COMMS_STATE = "swarm_control_core.fleet.comms_state.v1"
SCHEMA_PAYLOAD_STATE = "swarm_control_core.fleet.payload_state.v1"
SCHEMA_TASK_FEEDBACK = "swarm_control_core.fleet.task_feedback.v1"
SCHEMA_VIDEO_STREAM_INFO = "swarm_control_core.fleet.video_stream_info.v1"
SCHEMA_AUDIT_EVENT = "swarm_control_core.fleet.audit_event.v1"


# Controlled vocabularies (initial baseline).
CAPABILITY_VOCAB = frozenset(
    (
        "navigation",
        "teleop",
        "video",
        "obstacle_avoidance",
        "payload_delivery",
        "mapping",
    )
)
CONTROL_MODE_VOCAB = frozenset(("manual", "autonomy", "playbook", "safe_hold"))
READINESS_STATE_VOCAB = frozenset(("ready", "degraded", "unavailable"))
FAILURE_STATE_VOCAB = frozenset(("none", "recoverable", "critical"))
PAYLOAD_EFFECT_VOCAB = frozenset(("none", "camera_rgb", "camera_thermal", "lidar", "manipulator"))


def fleet_contract_manifest() -> dict:
    """Return machine-readable contract metadata."""
    return {
        "version": FLEET_CONTRACT_VERSION,
        "topics": {
            "robots": TOPIC_ROBOTS,
            "robot_state": TOPIC_ROBOT_STATE,
            "robot_health": TOPIC_ROBOT_HEALTH,
            "comms_state": TOPIC_COMMS_STATE,
            "payload_state": TOPIC_PAYLOAD_STATE,
            "task_feedback": TOPIC_TASK_FEEDBACK,
            "video_stream_info": TOPIC_VIDEO_STREAM_INFO,
            "audit_events": TOPIC_AUDIT_EVENTS,
            "teleop_cmd": TOPIC_TELEOP_CMD,
            "task_assignment": TOPIC_TASK_ASSIGNMENT,
            "policy_constraints": TOPIC_POLICY_CONSTRAINTS,
            "control_mode_request": TOPIC_CONTROL_MODE_REQUEST,
        },
        "schemas": {
            "robot_registry": SCHEMA_ROBOT_REGISTRY,
            "robot_state": SCHEMA_ROBOT_STATE,
            "robot_health": SCHEMA_ROBOT_HEALTH,
            "comms_state": SCHEMA_COMMS_STATE,
            "payload_state": SCHEMA_PAYLOAD_STATE,
            "task_feedback": SCHEMA_TASK_FEEDBACK,
            "video_stream_info": SCHEMA_VIDEO_STREAM_INFO,
            "audit_event": SCHEMA_AUDIT_EVENT,
        },
        "vocabularies": {
            "capabilities": sorted(CAPABILITY_VOCAB),
            "control_modes": sorted(CONTROL_MODE_VOCAB),
            "readiness_states": sorted(READINESS_STATE_VOCAB),
            "failure_states": sorted(FAILURE_STATE_VOCAB),
            "payload_effects": sorted(PAYLOAD_EFFECT_VOCAB),
        },
    }


def build_envelope(schema: str, source: str, payload: Mapping[str, Any], *, ts: float | None = None) -> dict:
    """Create a normalized contract envelope."""
    return {
        "schema_version": FLEET_CONTRACT_VERSION,
        "schema": str(schema or "").strip(),
        "source": str(source or "").strip(),
        "ts": float(time() if ts is None else ts),
        "payload": dict(payload or {}),
    }


def _validate_envelope_shape(envelope: Mapping[str, Any], expected_schema: str) -> Tuple[bool, str]:
    if not isinstance(envelope, Mapping):
        return False, "type:envelope:mapping"
    if str(envelope.get("schema_version", "")).strip() != FLEET_CONTRACT_VERSION:
        return False, "value:schema_version"
    if str(envelope.get("schema", "")).strip() != expected_schema:
        return False, "value:schema"
    if not str(envelope.get("source", "")).strip():
        return False, "missing:source"
    try:
        float(envelope.get("ts"))
    except Exception:
        return False, "type:ts:float"
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return False, "type:payload:mapping"
    return True, ""


def _validate_robot_id(payload: Mapping[str, Any]) -> Tuple[bool, str]:
    if not str(payload.get("robot", "")).strip():
        return False, "missing:robot"
    return True, ""


def validate_robot_registry_event(envelope: Mapping[str, Any]) -> Tuple[bool, str]:
    ok, reason = _validate_envelope_shape(envelope, SCHEMA_ROBOT_REGISTRY)
    if not ok:
        return ok, reason
    payload = envelope["payload"]
    ok, reason = _validate_robot_id(payload)
    if not ok:
        return ok, reason
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        return False, "type:capabilities:list"
    for cap in capabilities:
        if str(cap).strip() not in CAPABILITY_VOCAB:
            return False, "value:capabilities"
    return True, ""


def validate_robot_state_event(envelope: Mapping[str, Any]) -> Tuple[bool, str]:
    ok, reason = _validate_envelope_shape(envelope, SCHEMA_ROBOT_STATE)
    if not ok:
        return ok, reason
    payload = envelope["payload"]
    ok, reason = _validate_robot_id(payload)
    if not ok:
        return ok, reason
    mode = str(payload.get("control_mode", "")).strip()
    if mode and mode not in CONTROL_MODE_VOCAB:
        return False, "value:control_mode"
    return True, ""


def validate_robot_health_event(envelope: Mapping[str, Any]) -> Tuple[bool, str]:
    ok, reason = _validate_envelope_shape(envelope, SCHEMA_ROBOT_HEALTH)
    if not ok:
        return ok, reason
    payload = envelope["payload"]
    ok, reason = _validate_robot_id(payload)
    if not ok:
        return ok, reason
    readiness = str(payload.get("readiness", "")).strip()
    if readiness and readiness not in READINESS_STATE_VOCAB:
        return False, "value:readiness"
    failure = str(payload.get("failure_state", "")).strip()
    if failure and failure not in FAILURE_STATE_VOCAB:
        return False, "value:failure_state"
    return True, ""


def validate_task_feedback_event(envelope: Mapping[str, Any]) -> Tuple[bool, str]:
    ok, reason = _validate_envelope_shape(envelope, SCHEMA_TASK_FEEDBACK)
    if not ok:
        return ok, reason
    payload = envelope["payload"]
    ok, reason = _validate_robot_id(payload)
    if not ok:
        return ok, reason
    if not str(payload.get("task_id", "")).strip():
        return False, "missing:task_id"
    status = str(payload.get("status", "")).strip()
    if status not in ("accepted", "running", "succeeded", "failed", "aborted"):
        return False, "value:status"
    return True, ""


def normalize_capabilities(raw_values: Any) -> list[str]:
    """
    Normalize capability values into ordered unique vocabulary entries.
    Unknown values are dropped (non-fatal).
    """
    out: list[str] = []
    seen = set()

    values = raw_values
    if isinstance(values, str):
        values = [v.strip() for v in values.replace(",", " ").split()]
    if not isinstance(values, (list, tuple, set, frozenset)):
        values = []

    for value in values:
        cap = str(value or "").strip()
        if not cap or cap not in CAPABILITY_VOCAB or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def apply_defaults(payload: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """
    Populate optional fields with safe defaults.
    """
    payload.setdefault("control_mode", "manual")
    payload.setdefault("readiness", "ready")
    payload.setdefault("failure_state", "none")
    return payload
