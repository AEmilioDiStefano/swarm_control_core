#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
adapter_runtime.py

Runtime adapter-dispatch helpers.

These helpers resolve a robot's configured adapter profile, fetch the effective
adapter implementation from the registry, and execute task/state translation
with safe passthrough fallback behavior.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .adapters import get_adapter
from .drive_profiles import resolve_robot_profile


def _noop_log(_msg: str) -> None:
    return


def _safe_log(logger: Optional[Callable[[str], None]]) -> Callable[[str], None]:
    return logger if callable(logger) else _noop_log


def _as_mapping(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _adapter_context(
    *,
    robot: str,
    flow: str,
    binding: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "robot": str(robot or "").strip(),
        "flow": str(flow or "").strip(),
        "adapter_profile": str(binding.get("adapter_profile") or ""),
        "requested_adapter_name": str(binding.get("requested_adapter_name") or ""),
        "adapter_name": str(binding.get("adapter_name") or ""),
        "adapter_params": dict(binding.get("adapter_params", {}) or {}),
    }


def _normalize_translated_payload(
    *,
    translated: Any,
    original_payload: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Support two adapter return styles:
    - direct payload mapping
    - wrapped mapping with `payload` + optional `adapter_context`
    """
    if not isinstance(translated, Mapping):
        return dict(original_payload)
    data = dict(translated)
    wrapped_payload = data.get("payload")
    if isinstance(wrapped_payload, Mapping):
        out = dict(wrapped_payload)
        out.setdefault("adapter_context", context)
        return out
    out = data
    out.setdefault("adapter_context", context)
    return out


def resolve_robot_adapter_binding(
    profile_registry: Optional[Dict[str, Any]],
    robot: str,
    *,
    logger: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Resolve a robot adapter binding from profile registry with safe fallback.
    """
    log = _safe_log(logger)

    robot_name = str(robot or "").strip()
    fallback_adapter = get_adapter("passthrough")
    binding: Dict[str, Any] = {
        "robot": robot_name,
        "adapter_profile": "passthrough_local",
        "requested_adapter_name": "passthrough",
        "adapter_name": "passthrough",
        "adapter_params": {},
        "adapter": fallback_adapter,
        "robot_profile": {},
        "fallback_reason": "",
    }

    if not robot_name or not isinstance(profile_registry, dict):
        binding["fallback_reason"] = "missing_profile_registry_or_robot"
        return binding

    try:
        resolved = resolve_robot_profile(profile_registry, robot_name)
    except Exception as ex:
        binding["fallback_reason"] = f"profile_resolution_failed:{ex}"
        log(f"[adapter_runtime] robot={robot_name} fallback to passthrough ({ex})")
        return binding

    requested_name = str(resolved.get("adapter_name") or "passthrough").strip() or "passthrough"
    adapter_profile = str(resolved.get("adapter_profile") or "passthrough_local").strip() or "passthrough_local"
    adapter_params = dict(resolved.get("adapter_params", {}) or {})

    binding.update(
        {
            "adapter_profile": adapter_profile,
            "requested_adapter_name": requested_name,
            "adapter_params": adapter_params,
            "robot_profile": dict(resolved),
        }
    )

    try:
        adapter = get_adapter(requested_name)
        binding["adapter"] = adapter
        binding["adapter_name"] = str(adapter.name).strip() or requested_name
        return binding
    except Exception as ex:
        binding["fallback_reason"] = f"adapter_not_registered:{requested_name}:{ex}"
        log(
            f"[adapter_runtime] robot={robot_name} requested adapter '{requested_name}' not registered; "
            "using passthrough"
        )
        return binding


def translate_task_for_robot(
    profile_registry: Optional[Dict[str, Any]],
    robot: str,
    payload: Mapping[str, Any],
    *,
    flow: str = "",
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Apply robot-selected adapter task translation.
    """
    log = _safe_log(logger)
    binding = resolve_robot_adapter_binding(profile_registry, robot, logger=logger)
    adapter = binding.get("adapter")
    if adapter is None:
        return dict(_as_mapping(payload)), binding

    original_payload = _as_mapping(payload)
    context = _adapter_context(robot=str(robot), flow=flow, binding=binding)
    wrapped = {"payload": dict(original_payload), "adapter_context": context}

    try:
        translated = adapter.translate_external_task(wrapped)
    except Exception as ex:
        log(
            f"[adapter_runtime] task translation failed for robot={robot} "
            f"adapter={binding.get('adapter_name')}: {ex}"
        )
        out = dict(original_payload)
        out.setdefault("adapter_context", context)
        return out, binding

    return _normalize_translated_payload(
        translated=translated,
        original_payload=original_payload,
        context=context,
    ), binding


def translate_state_for_robot(
    profile_registry: Optional[Dict[str, Any]],
    robot: str,
    payload: Mapping[str, Any],
    *,
    flow: str = "",
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Apply robot-selected adapter state translation.
    """
    log = _safe_log(logger)
    binding = resolve_robot_adapter_binding(profile_registry, robot, logger=logger)
    adapter = binding.get("adapter")
    if adapter is None:
        return dict(_as_mapping(payload)), binding

    original_payload = _as_mapping(payload)
    context = _adapter_context(robot=str(robot), flow=flow, binding=binding)
    wrapped = {"payload": dict(original_payload), "adapter_context": context}

    try:
        translated = adapter.translate_external_state(wrapped)
    except Exception as ex:
        log(
            f"[adapter_runtime] state translation failed for robot={robot} "
            f"adapter={binding.get('adapter_name')}: {ex}"
        )
        out = dict(original_payload)
        out.setdefault("adapter_context", context)
        return out, binding

    return _normalize_translated_payload(
        translated=translated,
        original_payload=original_payload,
        context=context,
    ), binding

