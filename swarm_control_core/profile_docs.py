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


def _fmt_list(values: Any) -> str:
    if isinstance(values, str):
        return values
    if isinstance(values, list):
        return ", ".join(str(value) for value in values)
    return ""


def render_control_interface_index(control_interfaces_path: Path) -> str:
    data = _load_yaml_mapping(control_interfaces_path)
    interfaces = data.get("control_interfaces", {}) or {}
    if not isinstance(interfaces, dict):
        raise ValueError("control_interfaces.yaml must contain a control_interfaces mapping")

    lines: List[str] = [
        "# Control Interface Index",
        "",
        "Generated from `config/control_interfaces.yaml`. Do not hand-maintain profile details here;",
        "update the YAML source of truth and regenerate this file.",
        "",
        "| Interface | Compatible Control Types | Backend | Layout | Controller | Wiring Doc |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, raw_entry in interfaces.items():
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        controller = entry.get("controller", {}) or {}
        controller_label = ""
        if isinstance(controller, dict):
            model = str(controller.get("model", "")).strip()
            count = str(controller.get("count", "")).strip()
            controller_label = f"{count} x {model}".strip()
        docs = entry.get("docs", {}) or {}
        wiring = str(docs.get("wiring", "")).strip() if isinstance(docs, dict) else ""
        if wiring.startswith("DOCS/GPIO/"):
            wiring_target = f"./{Path(wiring).name}"
        elif wiring.startswith("DOCS/"):
            wiring_target = f"../{wiring.removeprefix('DOCS/')}"
        else:
            wiring_target = wiring
        wiring_link = f"[`{wiring}`]({wiring_target})" if wiring else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{name}`",
                    _fmt_list(entry.get("compatible_control_types")),
                    str(entry.get("backend", "")).strip(),
                    str(entry.get("wheel_layout", "")).strip(),
                    controller_label,
                    wiring_link,
                ]
            )
            + " |"
        )
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
