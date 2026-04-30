#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return [str(item) for item in value if str(item).strip()]
    return []


def profile_alias_map(profiles: Mapping[str, Any]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for canonical_name, raw_entry in profiles.items():
        canonical = str(canonical_name).strip()
        if not canonical:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        names = [canonical, *_as_list(entry.get("aliases"))]
        for name in names:
            key = str(name).strip()
            if not key:
                continue
            existing = alias_map.get(key)
            if existing and existing != canonical:
                raise ValueError(
                    f"Profile alias '{key}' is ambiguous: {existing!r} and {canonical!r}"
                )
            alias_map[key] = canonical
    return alias_map


def canonical_profile_name(profiles: Mapping[str, Any], requested_name: str) -> str:
    name = str(requested_name or "").strip()
    if not name:
        return ""
    return profile_alias_map(profiles).get(name, name)


def compatible_control_types(interface_entry: Mapping[str, Any]) -> List[str]:
    return _as_list(interface_entry.get("compatible_control_types"))


def interface_is_compatible(
    control_type: str,
    interface_name: str,
    interface_entry: Mapping[str, Any] | None,
) -> bool:
    control_type_l = str(control_type or "").strip().lower()
    if not control_type_l:
        return True
    entry = interface_entry or {}
    explicit = {name.strip().lower() for name in compatible_control_types(entry)}
    if explicit:
        return control_type_l in explicit

    # Legacy fallback for old profile files that predate explicit metadata.
    interface_l = str(interface_name or "").strip().lower()
    if "mecanum" in control_type_l or "omni" in control_type_l:
        return "mecanum" in interface_l or "omni" in interface_l
    if "diff" in control_type_l:
        return "diff" in interface_l
    return True


def compatible_interface_names(
    control_type: str,
    interfaces: Sequence[str],
    interface_metadata: Mapping[str, Any] | None = None,
) -> List[str]:
    metadata = interface_metadata or {}
    matches = [
        name
        for name in interfaces
        if interface_is_compatible(
            control_type,
            name,
            metadata.get(name) if isinstance(metadata, dict) else None,
        )
    ]
    return matches or [str(name) for name in interfaces]
