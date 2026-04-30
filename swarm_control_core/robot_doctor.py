#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .configure_robot_profile import (
    _active_camera_profiles_path,
    _config_dir,
    _load_robot_registry,
    _load_yaml_mapping,
    _repo_robot_instances_path,
    _runtime_robot_instances_paths,
    _suggest_control_machine_sync_specs,
    ensure_robot_entry,
    refresh_runtime_core_profiles,
    wiring_doc_for_interface,
)
from .path_defaults import MissingConfigError, default_robot_name, detect_workspace_root
from .profile_metadata import canonical_profile_name


def _workspace(requested: str) -> Path:
    raw = str(requested or "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        return detect_workspace_root()
    except MissingConfigError as exc:
        raise RuntimeError(
            "Unable to detect workspace root. Pass --workspace or set SWARM_CORE_WORKSPACE_ROOT."
        ) from exc


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _installed_share_config(filename: str) -> Optional[Path]:
    try:
        from ament_index_python.packages import get_package_share_directory  # type: ignore

        path = Path(get_package_share_directory("swarm_control_core")) / "config" / filename
        return path if path.exists() else None
    except Exception:
        return None


def _file_state(source: Path, target: Path) -> str:
    if not target.exists():
        return "missing"
    if not source.exists():
        return "source_missing"
    try:
        return "current" if source.read_text(encoding="utf-8") == target.read_text(encoding="utf-8") else "stale"
    except Exception:
        return "unreadable"


def _camera_state(camera_profiles_path: Path, robot_name: str) -> str:
    data = _load_yaml(camera_profiles_path)
    profiles = data.get("profiles", {}) or {}
    if not isinstance(profiles, dict) or robot_name not in profiles:
        return "missing"
    entry = profiles.get(robot_name)
    if isinstance(entry, dict) and entry:
        return "generated"
    return "placeholder"


def collect_report(
    *,
    workspace_root: Path,
    robot_name: str,
) -> Dict[str, Any]:
    config_dir = workspace_root / "src" / "swarm_control_core" / "config"
    source_robot_instances = _repo_robot_instances_path(workspace_root)
    source_control_types = config_dir / "control_types.yaml"
    source_control_interfaces = config_dir / "control_interfaces.yaml"
    camera_profiles_path = _active_camera_profiles_path()
    runtime_robot_instances = [
        path for path in _runtime_robot_instances_paths()
        if path != source_robot_instances
    ] or [_config_dir() / "robot_instances.yaml"]

    source_registry = _load_robot_registry(source_robot_instances) if source_robot_instances.exists() else {"robots": {}}
    source_robots = source_registry.get("robots", {}) or {}
    source_entry = source_robots.get(robot_name, {}) if isinstance(source_robots, dict) else {}
    control_interface = str(source_entry.get("control_interface", "") if isinstance(source_entry, dict) else "").strip()

    interfaces_data = _load_yaml_mapping(
        source_control_interfaces,
        "control_interfaces.yaml",
        {"schema_version": "1.0", "control_interfaces": {}},
    )
    source_interfaces = interfaces_data.get("control_interfaces", {}) or {}
    canonical_control_interface = (
        canonical_profile_name(source_interfaces, control_interface)
        if isinstance(source_interfaces, dict)
        else control_interface
    )
    source_interface_exists = isinstance(source_interfaces, dict) and canonical_control_interface in source_interfaces

    runtime_reports = []
    for runtime_path in runtime_robot_instances:
        runtime_registry = _load_robot_registry(runtime_path) if runtime_path.exists() else {"robots": {}}
        runtime_robots = runtime_registry.get("robots", {}) or {}
        runtime_entry = runtime_robots.get(robot_name, {}) if isinstance(runtime_robots, dict) else {}
        runtime_dir = runtime_path.parent
        runtime_reports.append({
            "robot_instances": str(runtime_path),
            "robot_entry": "current" if runtime_entry == source_entry and source_entry else ("missing" if not runtime_entry else "stale"),
            "control_types": _file_state(source_control_types, runtime_dir / "control_types.yaml"),
            "control_interfaces": _file_state(source_control_interfaces, runtime_dir / "control_interfaces.yaml"),
        })

    installed_ci = _installed_share_config("control_interfaces.yaml")
    installed_state = "unavailable"
    if installed_ci is not None and control_interface:
        installed_data = _load_yaml(installed_ci)
        installed_interfaces = installed_data.get("control_interfaces", {}) or {}
        installed_state = (
            "has_selected_interface"
            if isinstance(installed_interfaces, dict)
            and canonical_profile_name(installed_interfaces, control_interface) in installed_interfaces
            else "missing_selected_interface"
        )

    return {
        "robot": robot_name,
        "workspace": str(workspace_root),
        "source_robot_instances": str(source_robot_instances),
        "source_entry_state": "present" if source_entry else "missing",
        "source_entry": source_entry if isinstance(source_entry, dict) else {},
        "selected_control_interface": canonical_control_interface,
        "source_control_interface_state": "present" if source_interface_exists else "missing",
        "wiring_doc": wiring_doc_for_interface(source_control_interfaces, control_interface) if control_interface else "",
        "runtime": runtime_reports,
        "camera_profiles_path": str(camera_profiles_path),
        "camera_profile_state": _camera_state(camera_profiles_path, robot_name),
        "installed_control_interfaces": str(installed_ci) if installed_ci is not None else "",
        "installed_control_interface_state": installed_state,
        "control_machine_sync_specs": _suggest_control_machine_sync_specs(robot_name, source_entry if isinstance(source_entry, dict) else {}),
    }


def _print_report(report: Dict[str, Any]) -> None:
    print(f"[ROBOT DOCTOR] robot={report['robot']}")
    print(f"  workspace: {report['workspace']}")
    print(f"  source_entry: {report['source_entry_state']}")
    print(f"  selected_control_interface: {report.get('selected_control_interface') or '<none>'}")
    print(f"  source_control_interface: {report['source_control_interface_state']}")
    if report.get("wiring_doc"):
        print(f"  wiring_doc: {report['wiring_doc']}")
    print(f"  camera_profile: {report['camera_profile_state']} ({report['camera_profiles_path']})")
    print(f"  installed_control_interface: {report['installed_control_interface_state']}")
    for item in report.get("runtime", []):
        print(f"  runtime: {item['robot_instances']}")
        print(f"    robot_entry: {item['robot_entry']}")
        print(f"    control_types.yaml: {item['control_types']}")
        print(f"    control_interfaces.yaml: {item['control_interfaces']}")
    sync_specs = report.get("control_machine_sync_specs") or []
    if sync_specs:
        print("  control_machine_sync:")
        for spec in sync_specs:
            print(f"    {spec}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose canonical robot/profile/runtime configuration state.")
    parser.add_argument("--workspace", default="", help="Workspace root containing src/swarm_control_core")
    parser.add_argument("--robot", default="", help="Robot name")
    parser.add_argument("--repair", action="store_true", help="Refresh runtime core profiles and robot entry from source.")
    parser.add_argument("--control-type", default="", help="Required to create a missing source robot during --repair.")
    parser.add_argument("--control-interface", default="", help="Required to create a missing source robot during --repair.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        robot_name = str(args.robot or "").strip() or default_robot_name()
        workspace_root = _workspace(str(args.workspace or "").strip())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    source_robot_instances = _repo_robot_instances_path(workspace_root)
    runtime_robot_instances = [
        path for path in _runtime_robot_instances_paths()
        if path != source_robot_instances
    ] or [_config_dir() / "robot_instances.yaml"]

    if args.repair:
        try:
            ensure_robot_entry(
                repo_profiles_path=source_robot_instances,
                runtime_profiles_paths=runtime_robot_instances,
                control_types_path=workspace_root / "src" / "swarm_control_core" / "config" / "control_types.yaml",
                control_interfaces_path=workspace_root / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml",
                robot_name=robot_name,
                prompt_input=None,
                control_type=str(args.control_type or "").strip(),
                control_interface=str(args.control_interface or "").strip(),
                update_existing=bool(args.control_type or args.control_interface),
            )
            refresh_runtime_core_profiles(workspace_root, runtime_robot_instances)
        except Exception as exc:
            print(f"[ERROR] repair failed: {exc}", file=sys.stderr)
            return 2

    try:
        report = collect_report(workspace_root=workspace_root, robot_name=robot_name)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_report(report)

    unhealthy = (
        report["source_entry_state"] != "present"
        or report["source_control_interface_state"] != "present"
        or any(
            item["robot_entry"] != "current"
            or item["control_types"] != "current"
            or item["control_interfaces"] != "current"
            for item in report.get("runtime", [])
        )
    )
    return 1 if unhealthy else 0


if __name__ == "__main__":
    raise SystemExit(main())
