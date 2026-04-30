#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import yaml

from .interface_backends import get_interface_backend, registered_backend_names
from .profile_metadata import profile_alias_map


class ProfileValidationError(ValueError):
    pass


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _load_yaml_mapping(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProfileValidationError(f"{path} must contain a YAML mapping")
    return data


def validate_control_types(control_types: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(control_types, dict) or not control_types:
        return ["control_types must be a non-empty mapping"]
    for name, raw_entry in control_types.items():
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        if not isinstance(raw_entry, dict):
            errors.append(f"control_types.{name} must be a mapping")
            continue
        if not str(entry.get("type", "")).strip():
            errors.append(f"control_types.{name}.type is required")
        params = entry.get("params", {}) or {}
        if not isinstance(params, dict):
            errors.append(f"control_types.{name}.params must be a mapping")
    try:
        profile_alias_map(control_types)
    except Exception as exc:
        errors.append(str(exc))
    return errors


def validate_control_interfaces(
    control_interfaces: Mapping[str, Any],
    *,
    control_types: Mapping[str, Any] | None = None,
    package_root: Path | None = None,
    check_docs_exist: bool = False,
) -> List[str]:
    errors: List[str] = []
    if not isinstance(control_interfaces, dict) or not control_interfaces:
        return ["control_interfaces must be a non-empty mapping"]

    known_control_types = set((control_types or {}).keys())
    for name, raw_entry in control_interfaces.items():
        if not isinstance(raw_entry, dict):
            errors.append(f"control_interfaces.{name} must be a mapping")
            continue
        entry = raw_entry
        compat = _as_list(entry.get("compatible_control_types"))
        if not compat:
            errors.append(f"control_interfaces.{name}.compatible_control_types is required")
        for control_type in compat:
            if known_control_types and control_type not in known_control_types:
                errors.append(
                    f"control_interfaces.{name}.compatible_control_types references unknown control_type '{control_type}'"
                )

        backend = str(entry.get("backend", "")).strip()
        backend_schema = get_interface_backend(backend)
        if backend_schema is None:
            errors.append(f"control_interfaces.{name}.backend must be one of {list(registered_backend_names())}")

        wheel_layout = str(entry.get("wheel_layout", "")).strip()
        required_keys = backend_schema.gpio_layouts.get(wheel_layout) if backend_schema is not None else None
        if backend_schema is not None and required_keys is None:
            errors.append(
                f"control_interfaces.{name}.wheel_layout must be one of {sorted(backend_schema.gpio_layouts)}"
            )
        gpio = entry.get("gpio", {}) or {}
        if not isinstance(gpio, dict):
            errors.append(f"control_interfaces.{name}.gpio must be a mapping")
        elif required_keys:
            missing = sorted(required_keys - set(gpio.keys()))
            if missing:
                errors.append(f"control_interfaces.{name}.gpio missing required keys: {', '.join(missing)}")
            for key, value in gpio.items():
                try:
                    pin = int(value)
                except Exception:
                    errors.append(f"control_interfaces.{name}.gpio.{key} must be an integer BCM pin")
                    continue
                if pin < 0:
                    errors.append(f"control_interfaces.{name}.gpio.{key} must be non-negative")

        params = entry.get("params", {}) or {}
        if not isinstance(params, dict):
            errors.append(f"control_interfaces.{name}.params must be a mapping")

        controller = entry.get("controller", {}) or {}
        if not isinstance(controller, dict):
            errors.append(f"control_interfaces.{name}.controller must be a mapping")
        else:
            if not str(controller.get("model", "")).strip():
                errors.append(f"control_interfaces.{name}.controller.model is required")
            try:
                count = int(controller.get("count"))
                if count <= 0:
                    raise ValueError
            except Exception:
                errors.append(f"control_interfaces.{name}.controller.count must be a positive integer")

        docs = entry.get("docs", {}) or {}
        if not isinstance(docs, dict) or not str(docs.get("wiring", "")).strip():
            errors.append(f"control_interfaces.{name}.docs.wiring is required")
        elif check_docs_exist and package_root is not None:
            wiring_path = package_root / str(docs.get("wiring", "")).strip()
            if not wiring_path.exists():
                errors.append(f"control_interfaces.{name}.docs.wiring does not exist: {wiring_path}")

    try:
        profile_alias_map(control_interfaces)
    except Exception as exc:
        errors.append(str(exc))
    return errors


def validate_profile_files(
    control_types_path: Path,
    control_interfaces_path: Path,
    *,
    package_root: Path | None = None,
    check_docs_exist: bool = False,
) -> List[str]:
    control_types_data = _load_yaml_mapping(control_types_path)
    control_interfaces_data = _load_yaml_mapping(control_interfaces_path)
    control_types = control_types_data.get("control_types", {}) or {}
    control_interfaces = control_interfaces_data.get("control_interfaces", {}) or {}
    errors = []
    errors.extend(validate_control_types(control_types))
    errors.extend(
        validate_control_interfaces(
            control_interfaces,
            control_types=control_types,
            package_root=package_root,
            check_docs_exist=check_docs_exist,
        )
    )
    return errors


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate swarm_control_core profile metadata.")
    parser.add_argument("--control-types", required=True, help="Path to control_types.yaml")
    parser.add_argument("--control-interfaces", required=True, help="Path to control_interfaces.yaml")
    parser.add_argument("--package-root", default="", help="Package root used to check wiring-doc paths")
    parser.add_argument("--check-docs-exist", action="store_true", help="Fail if docs.wiring files are missing")
    args = parser.parse_args(argv)

    package_root = Path(args.package_root).expanduser() if args.package_root else None
    errors = validate_profile_files(
        Path(args.control_types).expanduser(),
        Path(args.control_interfaces).expanduser(),
        package_root=package_root,
        check_docs_exist=bool(args.check_docs_exist),
    )
    if errors:
        for error in errors:
            print(f"[profile_validation] ERROR: {error}")
        return 2
    print("[profile_validation] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
