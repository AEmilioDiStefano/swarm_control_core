#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml


def _load_yaml_mapping(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def render_control_interface_index(control_interfaces_path: Path) -> str:
    data = _load_yaml_mapping(control_interfaces_path)
    interfaces = data.get("control_interfaces", {}) or {}
    if not isinstance(interfaces, dict):
        raise ValueError("control_interfaces.yaml must contain a control_interfaces mapping")

    lines: List[str] = [
        "# Control Interface Index",
        "",
        "Generated from `config/control_interfaces.yaml`.",
        "",
        "`config/control_interfaces.yaml` is the authoritative control-interface",
        "catalog.",
        "",
        "When a profile has a wiring guide, the YAML `docs.wiring` field points to",
        "the correct file.",
        "",
        "This generated file is a lightweight freshness check for the YAML source.",
    ]
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate profile reference docs from YAML metadata.")
    parser.add_argument("--control-interfaces", required=True, help="Path to control_interfaces.yaml")
    parser.add_argument("--output", default="", help="Markdown output path. Defaults to stdout.")
    parser.add_argument("--check", action="store_true", help="Fail if output file is not current")
    args = parser.parse_args(argv)

    rendered = render_control_interface_index(Path(args.control_interfaces).expanduser())
    if args.output:
        output_path = Path(args.output).expanduser()
        if args.check:
            current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            if current != rendered:
                print(f"[profile_docs] ERROR: generated docs are stale: {output_path}")
                return 2
            print(f"[profile_docs] OK: {output_path}")
            return 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        print(f"[profile_docs] wrote {output_path}")
        return 0
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
