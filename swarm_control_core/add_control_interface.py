#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .path_defaults import MissingConfigError, detect_workspace_root
from .profile_validation import validate_profile_files


PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _load_yaml_mapping(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _parse_csv(raw: str) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _parse_gpio(values: List[str]) -> Dict[str, int]:
    gpio: Dict[str, int] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"--gpio values must be KEY=PIN, got: {raw}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--gpio key cannot be empty: {raw}")
        gpio[key] = int(value.strip())
    return gpio


def _default_wiring_doc(name: str) -> str:
    return f"DOCS/GPIO/GPIO_for_{name}.md"


def _render_wiring_stub(name: str, entry: Dict[str, Any]) -> str:
    gpio = entry.get("gpio", {}) or {}
    rows = "\n".join(f"- `{key}` -> GPIO {value}" for key, value in sorted(gpio.items()))
    compat = ", ".join(entry.get("compatible_control_types", []) or [])
    controller = entry.get("controller", {}) or {}
    return f"""# GPIO wiring for `{name}`

This wiring guide was scaffolded from `config/control_interfaces.yaml`.

- compatible control types: {compat}
- backend: {entry.get("backend", "")}
- wheel layout: {entry.get("wheel_layout", "")}
- controller: {controller.get("count", "")} x {controller.get("model", "")}

## GPIO map

{rows or "- Add GPIO mappings here."}

## Operator notes

- Confirm every motor channel with `swarm_core_wheel_test.sh` before live operation.
- Keep robot wheels/tracks off the ground during first motion tests.
- Update this document with board-specific power, enable, standby, and ground wiring.
"""


def _append_interface_entry(config_path: Path, name: str, entry: Dict[str, Any]) -> None:
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if "control_interfaces:" not in existing:
        data = _load_yaml_mapping(config_path, {"schema_version": "1.0", "defaults": {}, "control_interfaces": {}})
        interfaces = data.setdefault("control_interfaces", {})
        interfaces[name] = entry
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return

    prepared = re.sub(r"(?m)^control_interfaces:\s*\{\}\s*$", "control_interfaces:", existing.rstrip())
    block = yaml.safe_dump({name: entry}, sort_keys=False).rstrip()
    config_path.write_text(
        prepared + "\n\n" + textwrap.indent(block, "  ") + "\n",
        encoding="utf-8",
    )


def _default_workspace_root(requested: str) -> Path:
    raw = str(requested or "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        return detect_workspace_root()
    except MissingConfigError as exc:
        raise RuntimeError(
            "Unable to detect workspace root. Pass --workspace or set SWARM_CORE_WORKSPACE_ROOT."
        ) from exc


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a reusable control interface profile.")
    parser.add_argument("--workspace", default="", help="Workspace root containing src/swarm_control_core")
    parser.add_argument("--name", required=True, help="Canonical lower_snake_case profile id, e.g. mecanum_l298n_2")
    parser.add_argument("--compatible-control-types", required=True, help="Comma-separated control types, e.g. mecanum_drive")
    parser.add_argument("--backend", default="gpio_hbridge", help="Backend schema name")
    parser.add_argument("--wheel-layout", required=True, choices=("side_pair", "front_pair", "four_wheel"))
    parser.add_argument("--controller-model", required=True, help="Controller model, e.g. L298N")
    parser.add_argument("--controller-count", required=True, type=int, help="Number of controller boards")
    parser.add_argument("--wiring-doc", default="", help="Wiring doc path relative to package root")
    parser.add_argument("--alias", action="append", default=[], help="Legacy alias to preserve")
    parser.add_argument("--gpio", action="append", default=[], help="GPIO mapping as KEY=PIN; repeat for each key")
    parser.add_argument("--param", action="append", default=[], help="Param mapping as KEY=VALUE; repeat for overrides")
    parser.add_argument("--force", action="store_true", help="Replace an existing profile")
    parser.add_argument("--generate-wiring-doc", action="store_true", help="Create a starter wiring doc if missing")
    args = parser.parse_args(argv)

    name = str(args.name or "").strip()
    if not PROFILE_ID_RE.match(name):
        print("[add_control_interface] ERROR: --name must be lower_snake_case")
        return 2

    try:
        workspace_root = _default_workspace_root(args.workspace)
        package_root = workspace_root / "src" / "swarm_control_core"
        config_path = package_root / "config" / "control_interfaces.yaml"
        control_types_path = package_root / "config" / "control_types.yaml"
        data = _load_yaml_mapping(config_path, {"schema_version": "1.0", "defaults": {}, "control_interfaces": {}})
        interfaces = data.setdefault("control_interfaces", {})
        if not isinstance(interfaces, dict):
            raise ValueError("control_interfaces.yaml key 'control_interfaces' must be a mapping")
        if name in interfaces and not args.force:
            raise ValueError(f"control interface '{name}' already exists; use --force to replace")

        params = {
            "pwm_hz": 1000,
            "max_pwm": 100,
            "pwm_ramp_ms": 0,
            "pwm_deadband_pct": 0,
            "cmd_rate_hz": 0,
            "pwm_slew_pct_per_s": 0,
        }
        for raw in args.param:
            if "=" not in raw:
                raise ValueError(f"--param values must be KEY=VALUE, got: {raw}")
            key, value = raw.split("=", 1)
            try:
                parsed_value: Any = int(value)
            except Exception:
                try:
                    parsed_value = float(value)
                except Exception:
                    parsed_value = value
            params[key.strip()] = parsed_value

        wiring_doc = str(args.wiring_doc or "").strip() or _default_wiring_doc(name)
        entry = {
            "aliases": [alias for alias in args.alias if str(alias).strip()],
            "compatible_control_types": _parse_csv(args.compatible_control_types),
            "backend": str(args.backend).strip(),
            "wheel_layout": str(args.wheel_layout).strip(),
            "controller": {
                "model": str(args.controller_model).strip(),
                "count": int(args.controller_count),
            },
            "docs": {
                "wiring": wiring_doc,
            },
            "gpio": _parse_gpio(args.gpio),
            "params": params,
        }
        if not entry["aliases"]:
            entry.pop("aliases")
        if args.force:
            interfaces[name] = entry
            config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        else:
            _append_interface_entry(config_path, name, entry)

        wiring_path = package_root / wiring_doc
        if args.generate_wiring_doc and not wiring_path.exists():
            wiring_path.parent.mkdir(parents=True, exist_ok=True)
            wiring_path.write_text(_render_wiring_stub(name, entry), encoding="utf-8")

        errors = validate_profile_files(
            control_types_path,
            config_path,
            package_root=package_root,
            check_docs_exist=bool(args.generate_wiring_doc),
        )
        if errors:
            for error in errors:
                print(f"[add_control_interface] ERROR: {error}")
            return 2
    except Exception as exc:
        print(f"[add_control_interface] ERROR: {exc}")
        return 2

    print(f"[add_control_interface] wrote profile '{name}' to {config_path}")
    if args.generate_wiring_doc:
        print(f"[add_control_interface] wiring doc: {package_root / wiring_doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
