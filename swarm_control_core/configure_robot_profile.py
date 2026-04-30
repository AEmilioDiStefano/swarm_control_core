#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import socket
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO

import yaml

from .path_defaults import (
    MissingConfigError,
    default_robot_name,
    detect_workspace_root,
)
from .profile_metadata import canonical_profile_name, compatible_interface_names
from .save_camera_profile import (
    _acquire_prompt_input,
    _print_wrapped,
    _read_prompt_line,
    main as save_camera_profile_main,
)


RobotEntry = Dict[str, Any]
RuntimeSyncResult = Dict[str, Any]

_FALLBACK_CONTROL_TYPES = ["diff_drive", "mecanum_drive"]
_FALLBACK_CONTROL_INTERFACES = [
    "l298n_diff",
    "dual_l298n_diff",
    "dual_l298n_mecanum",
    "dual_tb6612_diff",
    "dual_tb6612_mecanum",
]

_CORE_PROFILE_FILES = ("control_types.yaml", "control_interfaces.yaml")


def _config_dir() -> Path:
    raw = str(os.environ.get("SWARM_CORE_CONFIG_DIR", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "swarm_control_core"


def _repo_robot_instances_path(workspace_root: Path) -> Path:
    return workspace_root / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"


def _runtime_robot_instances_paths() -> List[Path]:
    targets: List[Path] = [_config_dir() / "robot_instances.yaml"]
    for env_key in ("PROFILES_PATH", "SWARM_CORE_PROFILES_PATH"):
        raw = str(os.environ.get(env_key, "")).strip()
        if raw:
            targets.append(Path(raw).expanduser())

    dedup: List[Path] = []
    seen = set()
    for target in targets:
        norm = str(target)
        if norm in seen:
            continue
        seen.add(norm)
        dedup.append(target)
    return dedup


def _active_camera_profiles_path() -> Path:
    for env_key in ("CAMERA_PROFILES_PATH", "SWARM_CORE_CAMERA_PROFILES_PATH"):
        raw = str(os.environ.get(env_key, "")).strip()
        if raw:
            return Path(raw).expanduser()
    return _config_dir() / "camera_profiles.yaml"


def _load_yaml_mapping(path: Path, label: str, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"Unable to parse {label}: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a YAML mapping: {path}")
    return data


def _empty_robot_registry() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "defaults": {
            "control_type": "diff_drive",
            "control_interface": "l298n_diff",
        },
        "robots": {},
    }


def _load_robot_registry(path: Path) -> Dict[str, Any]:
    data = _load_yaml_mapping(path, "robot_instances.yaml", _empty_robot_registry())
    defaults = data.get("defaults", {}) or {}
    robots = data.get("robots", {}) or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"robot_instances.yaml defaults must be a mapping: {path}")
    if not isinstance(robots, dict):
        raise ValueError(f"robot_instances.yaml robots must be a mapping: {path}")
    return {
        "schema_version": str(data.get("schema_version", "")).strip() or "1.0",
        "defaults": {
            "control_type": str(defaults.get("control_type", "")).strip() or "diff_drive",
            "control_interface": str(defaults.get("control_interface", "")).strip() or "l298n_diff",
        },
        "robots": robots,
    }


def _load_named_options(
    path: Path,
    mapping_key: str,
    fallback: Sequence[str],
) -> List[str]:
    data = _load_yaml_mapping(path, path.name, {"schema_version": "1.0", mapping_key: {}})
    mapping = data.get(mapping_key, {}) or {}
    if isinstance(mapping, dict) and mapping:
        return [str(k) for k in mapping.keys()]
    return [str(v) for v in fallback]


def _load_named_mapping(path: Path, mapping_key: str, fallback: Sequence[str]) -> Dict[str, Any]:
    data = _load_yaml_mapping(path, path.name, {"schema_version": "1.0", mapping_key: {}})
    mapping = data.get(mapping_key, {}) or {}
    if isinstance(mapping, dict) and mapping:
        return mapping
    return {str(v): {} for v in fallback}


def _compatible_control_interfaces(
    control_type: str,
    interfaces: Sequence[str],
    interface_metadata: Optional[Dict[str, Any]] = None,
) -> List[str]:
    return compatible_interface_names(control_type, interfaces, interface_metadata)


def _load_control_interface_metadata(path: Path, name: str) -> Dict[str, Any]:
    data = _load_yaml_mapping(path, path.name, {"schema_version": "1.0", "control_interfaces": {}})
    interfaces = data.get("control_interfaces", {}) or {}
    if not isinstance(interfaces, dict):
        return {}
    canonical_name = canonical_profile_name(interfaces, name)
    entry = interfaces.get(canonical_name, {}) or {}
    return entry if isinstance(entry, dict) else {}


def wiring_doc_for_interface(control_interfaces_path: Path, control_interface: str) -> str:
    entry = _load_control_interface_metadata(control_interfaces_path, control_interface)
    docs = entry.get("docs", {}) or {}
    if isinstance(docs, dict):
        value = str(docs.get("wiring", "") or "").strip()
        if value:
            return value
    return ""


def refresh_runtime_core_profiles(workspace_root: Path, runtime_profiles_paths: Sequence[Path]) -> List[RuntimeSyncResult]:
    """
    Refresh reusable core profile files next to runtime robot_instances.yaml.

    Camera profiles are intentionally excluded because they are generated from
    robot-local discovery and should not be overwritten by repo templates.
    """
    source_dir = workspace_root / "src" / "swarm_control_core" / "config"
    runtime_dirs = []
    seen = set()
    for runtime_path in runtime_profiles_paths:
        runtime_dir = Path(runtime_path).expanduser().parent
        key = str(runtime_dir)
        if key in seen:
            continue
        seen.add(key)
        runtime_dirs.append(runtime_dir)

    results: List[RuntimeSyncResult] = []
    for runtime_dir in runtime_dirs:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        for filename in _CORE_PROFILE_FILES:
            src = source_dir / filename
            dst = runtime_dir / filename
            if not src.exists():
                results.append({"path": dst, "state": "missing_source", "repaired": False})
                continue
            previous = dst.read_text(encoding="utf-8") if dst.exists() else None
            next_text = src.read_text(encoding="utf-8")
            if previous == next_text:
                results.append({"path": dst, "state": "already_synced", "repaired": False})
                continue
            shutil.copyfile(src, dst)
            try:
                dst.chmod(0o644)
            except Exception:
                pass
            results.append({
                "path": dst,
                "state": "missing_file" if previous is None else "stale_file",
                "repaired": True,
            })
    return results


def _prompt_choice(
    label: str,
    options: Sequence[str],
    default_value: str,
    prompt_input: TextIO,
) -> str:
    choices = [str(v) for v in options]
    if not choices:
        raise ValueError(f"No options available for {label}")

    default = default_value if default_value in choices else choices[0]
    print(f"[ROBOT PROFILE] Choose {label}:")
    for idx, option in enumerate(choices, start=1):
        marker = " (default)" if option == default else ""
        print(f"  {idx}. {option}{marker}")

    while True:
        raw = _read_prompt_line(
            prompt_input=prompt_input,
            prompt=f"Select {label} [1-{len(choices)}] (Enter for {default}): ",
        ).strip()
        if not raw:
            return default
        try:
            index = int(raw)
        except Exception:
            print("[WARN] Enter a number.")
            continue
        if 1 <= index <= len(choices):
            return choices[index - 1]
        print(f"[WARN] Enter a value between 1 and {len(choices)}.")


def _robot_entry_yaml(robot_name: str, entry: RobotEntry) -> str:
    return yaml.safe_dump({robot_name: entry}, sort_keys=False).rstrip()


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def _append_robot_to_repo_file(
    path: Path,
    robot_name: str,
    entry: RobotEntry,
    full_registry: Dict[str, Any],
) -> None:
    block = textwrap.indent(_robot_entry_yaml(robot_name, entry), "  ")
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if not original.strip():
        _write_yaml(path, full_registry)
        return
    candidate = original.rstrip() + ("\n\n" if original.strip() else "robots:\n") + block + "\n"
    try:
        parsed = yaml.safe_load(candidate) or {}
        robots = parsed.get("robots", {}) or {}
        if isinstance(parsed, dict) and isinstance(robots, dict) and robot_name in robots:
            path.write_text(candidate, encoding="utf-8")
            return
    except Exception:
        pass

    _write_yaml(path, full_registry)


def _build_robot_entry(
    robot_name: str,
    control_type: str,
    control_interface: str,
    *,
    linux_username: str,
    hostname: str,
) -> RobotEntry:
    host = str(hostname or "").strip() or robot_name
    if "." not in host and ":" not in host:
        host = f"{host}.local"
    ssh_target = f"{linux_username}@{host}"
    return {
        "ssh_target": ssh_target,
        "control_type": str(control_type).strip(),
        "control_interface": str(control_interface).strip(),
    }


def ensure_robot_entry(
    *,
    repo_profiles_path: Path,
    runtime_profiles_paths: Sequence[Path],
    control_types_path: Path,
    control_interfaces_path: Path,
    robot_name: str,
    prompt_input: Optional[TextIO] = None,
    control_type: str = "",
    control_interface: str = "",
    linux_username: str = "",
    hostname: str = "",
    update_existing: bool = False,
) -> tuple[RobotEntry, bool, List[RuntimeSyncResult]]:
    repo_registry = _load_robot_registry(repo_profiles_path)
    repo_robots = repo_registry.get("robots", {}) or {}
    if not isinstance(repo_robots, dict):
        raise ValueError(f"robots must be a mapping in {repo_profiles_path}")

    created = False
    entry = repo_robots.get(robot_name)
    if not isinstance(entry, dict):
        control_type_mapping = _load_named_mapping(
            control_types_path,
            "control_types",
            _FALLBACK_CONTROL_TYPES,
        )
        control_interface_mapping = _load_named_mapping(
            control_interfaces_path,
            "control_interfaces",
            _FALLBACK_CONTROL_INTERFACES,
        )
        control_type_names = [str(k) for k in control_type_mapping.keys()]
        control_interface_names = [str(k) for k in control_interface_mapping.keys()]
        selected_control_type = str(control_type or "").strip()
        if selected_control_type:
            selected_control_type = canonical_profile_name(control_type_mapping, selected_control_type)
        if not selected_control_type:
            if prompt_input is None:
                raise RuntimeError(
                    f"Robot '{robot_name}' does not exist in robot_instances.yaml and no interactive terminal is available."
                )
            default_control_type = canonical_profile_name(
                control_type_mapping,
                repo_registry["defaults"].get("control_type", control_type_names[0]),
            )
            selected_control_type = _prompt_choice(
                "control_type",
                control_type_names,
                default_control_type,
                prompt_input,
            )
        elif selected_control_type not in control_type_names:
            raise ValueError(
                f"Unsupported control_type '{selected_control_type}'. Valid options: {', '.join(control_type_names)}"
            )

        compatible_interfaces = _compatible_control_interfaces(
            selected_control_type,
            control_interface_names,
            control_interface_mapping,
        )
        selected_control_interface = str(control_interface or "").strip()
        if selected_control_interface:
            selected_control_interface = canonical_profile_name(control_interface_mapping, selected_control_interface)
        if not selected_control_interface:
            if prompt_input is None:
                raise RuntimeError(
                    f"Robot '{robot_name}' does not exist in robot_instances.yaml and no interactive terminal is available."
                )
            default_control_interface = canonical_profile_name(
                control_interface_mapping,
                repo_registry["defaults"].get("control_interface", compatible_interfaces[0]),
            )
            selected_control_interface = _prompt_choice(
                "control_interface",
                compatible_interfaces,
                default_control_interface,
                prompt_input,
            )
        elif selected_control_interface not in compatible_interfaces:
            valid = ", ".join(compatible_interfaces)
            raise ValueError(
                f"Unsupported control_interface '{selected_control_interface}' for control_type '{selected_control_type}'. "
                f"Valid options: {valid}"
            )

        username = str(linux_username or "").strip() or getpass.getuser()
        detected_host = str(hostname or "").strip() or socket.gethostname()
        entry = _build_robot_entry(
            robot_name,
            selected_control_type,
            selected_control_interface,
            linux_username=username,
            hostname=detected_host,
        )
        repo_robots[robot_name] = entry
        repo_registry["robots"] = repo_robots
        _append_robot_to_repo_file(repo_profiles_path, robot_name, entry, repo_registry)
        created = True
    else:
        entry = dict(entry)
        requested_control_type = str(control_type or "").strip()
        requested_control_interface = str(control_interface or "").strip()
        if update_existing and (requested_control_type or requested_control_interface):
            control_type_mapping = _load_named_mapping(
                control_types_path,
                "control_types",
                _FALLBACK_CONTROL_TYPES,
            )
            control_interface_mapping = _load_named_mapping(
                control_interfaces_path,
                "control_interfaces",
                _FALLBACK_CONTROL_INTERFACES,
            )
            control_type_names = [str(k) for k in control_type_mapping.keys()]
            control_interface_names = [str(k) for k in control_interface_mapping.keys()]
            selected_control_type = requested_control_type or str(entry.get("control_type", "")).strip()
            selected_control_type = canonical_profile_name(control_type_mapping, selected_control_type)
            if selected_control_type not in control_type_names:
                raise ValueError(
                    f"Unsupported control_type '{selected_control_type}'. Valid options: {', '.join(control_type_names)}"
                )
            compatible_interfaces = _compatible_control_interfaces(
                selected_control_type,
                control_interface_names,
                control_interface_mapping,
            )
            selected_control_interface = requested_control_interface or str(entry.get("control_interface", "")).strip()
            selected_control_interface = canonical_profile_name(control_interface_mapping, selected_control_interface)
            if selected_control_interface not in compatible_interfaces:
                valid = ", ".join(compatible_interfaces)
                raise ValueError(
                    f"Unsupported control_interface '{selected_control_interface}' for control_type '{selected_control_type}'. "
                    f"Valid options: {valid}"
                )
            entry["control_type"] = selected_control_type
            entry["control_interface"] = selected_control_interface
            if linux_username or hostname:
                username = str(linux_username or "").strip() or str(entry.get("ssh_target", "")).split("@")[0] or getpass.getuser()
                detected_host = str(hostname or "").strip() or socket.gethostname()
                entry["ssh_target"] = _build_robot_entry(
                    robot_name,
                    selected_control_type,
                    selected_control_interface,
                    linux_username=username,
                    hostname=detected_host,
                )["ssh_target"]
            repo_robots[robot_name] = entry
            repo_registry["robots"] = repo_robots
            _write_yaml(repo_profiles_path, repo_registry)

    sync_results: List[RuntimeSyncResult] = []
    for runtime_path in runtime_profiles_paths:
        runtime_exists = runtime_path.exists()
        runtime_registry = _load_robot_registry(runtime_path)
        runtime_registry["schema_version"] = repo_registry.get("schema_version", "1.0")
        runtime_registry["defaults"] = dict(repo_registry.get("defaults", {}) or {})
        runtime_robots = runtime_registry.get("robots", {}) or {}
        if not isinstance(runtime_robots, dict):
            runtime_robots = {}
        existing_runtime_entry = runtime_robots.get(robot_name)
        if not runtime_exists:
            sync_state = "missing_file"
        elif not isinstance(existing_runtime_entry, dict):
            sync_state = "missing_entry"
        elif dict(existing_runtime_entry) != dict(entry):
            sync_state = "stale_entry"
        else:
            sync_state = "already_synced"

        if sync_state != "already_synced":
            runtime_robots[robot_name] = dict(entry)
            runtime_registry["robots"] = runtime_robots
            _write_yaml(runtime_path, runtime_registry)

        sync_results.append(
            {
                "path": runtime_path,
                "state": sync_state,
                "repaired": sync_state != "already_synced",
            }
        )

    return dict(entry), created, sync_results


def _load_camera_profile_entry(camera_profiles_path: Path, robot_name: str) -> Dict[str, Any]:
    data = _load_yaml_mapping(
        camera_profiles_path,
        "camera_profiles.yaml",
        {"schema_version": "1.0", "defaults": {}, "profiles": {}},
    )
    profiles = data.get("profiles", {}) or {}
    if not isinstance(profiles, dict):
        return {}
    entry = profiles.get(robot_name, {}) or {}
    return entry if isinstance(entry, dict) else {}


def ensure_camera_profile(
    *,
    camera_profiles_path: Path,
    robot_name: str,
    save_callback: Callable[[str, Path], int],
) -> tuple[Dict[str, Any], bool]:
    existing = _load_camera_profile_entry(camera_profiles_path, robot_name)
    if str(existing.get("device", "")).strip():
        return existing, False

    rc = save_callback(robot_name, camera_profiles_path)
    if rc != 0:
        raise RuntimeError(f"Camera profile configuration failed with exit code {rc}")

    created = _load_camera_profile_entry(camera_profiles_path, robot_name)
    if not str(created.get("device", "")).strip():
        raise RuntimeError(
            f"Camera profile for robot '{robot_name}' was still missing after configuration."
        )
    return created, True


def _print_yaml_block(title: str, data: Dict[str, Any]) -> None:
    print(title)
    print(textwrap.indent(yaml.safe_dump(data, sort_keys=False).rstrip(), "  "))


def _suggest_control_machine_sync_specs(robot_name: str, entry: Dict[str, Any]) -> List[str]:
    ssh_target = str(entry.get("ssh_target", "")).strip()
    if not ssh_target:
        return []
    return [ssh_target, f"{robot_name}={ssh_target}"]


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ensure this robot has a swarm_control_core robot instance and camera profile.",
    )
    parser.add_argument("--workspace", default="", help="Workspace root containing src/swarm_control_core")
    parser.add_argument("--robot", default="", help="Robot name (defaults to SWARM_CORE_ROBOT_NAME / Linux username)")
    parser.add_argument("--linux-username", default="", help="Linux username for ssh_target when creating/updating entry")
    parser.add_argument("--hostname", default="", help="Hostname for ssh_target when creating/updating entry")
    parser.add_argument("--control-type", default="", help="Preselect control_type when creating a new robot entry")
    parser.add_argument(
        "--control-interface",
        default="",
        help="Preselect control_interface when creating a new robot entry",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Apply explicit --control-type/--control-interface values to an existing robot entry.",
    )
    parser.add_argument(
        "--skip-camera-profile",
        action="store_true",
        help="Do not launch camera profile discovery if this robot has no camera profile yet.",
    )
    parser.add_argument(
        "--no-refresh-core-profiles",
        action="store_true",
        help="Do not refresh runtime control_types.yaml/control_interfaces.yaml from the source tree.",
    )
    args = parser.parse_args(argv)

    try:
        robot_name = str(args.robot or "").strip() or default_robot_name()
    except MissingConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    try:
        workspace_root = _default_workspace_root(str(args.workspace or "").strip())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    repo_profiles_path = _repo_robot_instances_path(workspace_root)
    control_types_path = workspace_root / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces_path = workspace_root / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    if not repo_profiles_path.exists():
        print(f"[ERROR] Missing repository baseline file: {repo_profiles_path}", file=sys.stderr)
        return 2
    if not control_types_path.exists() or not control_interfaces_path.exists():
        print("[ERROR] Missing control type/interface template files in workspace config.", file=sys.stderr)
        return 2

    runtime_robot_instances = [
        path for path in _runtime_robot_instances_paths()
        if path != repo_profiles_path
    ]
    if not runtime_robot_instances:
        runtime_robot_instances = [_config_dir() / "robot_instances.yaml"]

    prompt_input = _acquire_prompt_input()
    try:
        entry, created_robot, sync_results = ensure_robot_entry(
            repo_profiles_path=repo_profiles_path,
            runtime_profiles_paths=runtime_robot_instances,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
            robot_name=robot_name,
            prompt_input=prompt_input,
            control_type=str(args.control_type or "").strip(),
            control_interface=str(args.control_interface or "").strip(),
            linux_username=str(args.linux_username or "").strip(),
            hostname=str(args.hostname or "").strip(),
            update_existing=bool(args.update_existing),
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        if prompt_input is not None and prompt_input is not sys.stdin:
            try:
                prompt_input.close()
            except Exception:
                pass
        return 2

    if prompt_input is not None and prompt_input is not sys.stdin:
        try:
            prompt_input.close()
        except Exception:
            pass

    core_profile_results: List[RuntimeSyncResult] = []
    if not args.no_refresh_core_profiles:
        core_profile_results = refresh_runtime_core_profiles(workspace_root, runtime_robot_instances)

    camera_profiles_path = _active_camera_profiles_path()

    def _save_camera(robot: str, path: Path) -> int:
        return save_camera_profile_main(["--robot", robot, "--camera-profiles", str(path)])

    camera_entry: Dict[str, Any] = {}
    created_camera = False
    if not args.skip_camera_profile:
        try:
            camera_entry, created_camera = ensure_camera_profile(
                camera_profiles_path=camera_profiles_path,
                robot_name=robot_name,
                save_callback=_save_camera,
            )
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2

    state_text = "created" if created_robot else "already present"
    print(f"[ROBOT PROFILE] robot={robot_name}")
    _print_wrapped("  baseline_state: ", state_text)
    _print_wrapped("  workspace: ", workspace_root)
    _print_wrapped("  baseline_robot_instances: ", repo_profiles_path)
    for result in sync_results:
        runtime_path = result["path"]
        state = str(result.get("state", "")).strip()
        if state == "missing_file":
            print(f"[ROBOT PROFILE] Runtime robot_instances.yaml was missing at {runtime_path}. Repairing now.")
            print(f"[ROBOT PROFILE] Runtime robot_instances.yaml repaired successfully at {runtime_path}.")
        elif state == "missing_entry":
            print(
                f"[ROBOT PROFILE] Runtime robot entry for '{robot_name}' was missing at {runtime_path}. "
                "Repairing now."
            )
            print(f"[ROBOT PROFILE] Runtime robot entry repaired successfully at {runtime_path}.")
        elif state == "stale_entry":
            print(
                f"[ROBOT PROFILE] Runtime robot entry for '{robot_name}' was stale at {runtime_path}. "
                "Repairing now."
            )
            print(f"[ROBOT PROFILE] Runtime robot entry repaired successfully at {runtime_path}.")
        else:
            print(f"[ROBOT PROFILE] Runtime robot entry already matched baseline at {runtime_path}.")
    for result in core_profile_results:
        path = result["path"]
        state = str(result.get("state", "")).strip()
        if state == "already_synced":
            print(f"[ROBOT PROFILE] Runtime core profile already current: {path}")
        elif result.get("repaired"):
            print(f"[ROBOT PROFILE] Runtime core profile refreshed: {path}")
        else:
            print(f"[ROBOT PROFILE] Runtime core profile check failed ({state}): {path}")
    _print_yaml_block("[ROBOT PROFILE] robot_instances.yaml entry:", {robot_name: entry})

    wiring_doc = wiring_doc_for_interface(control_interfaces_path, str(entry.get("control_interface", "")).strip())
    if wiring_doc:
        _print_wrapped("  wiring_doc: ", wiring_doc)

    if args.skip_camera_profile:
        _print_wrapped("  camera_profile_state: ", "skipped")
        _print_wrapped("  camera_profiles_path: ", camera_profiles_path)
    else:
        camera_state = "created" if created_camera else "already present"
        _print_wrapped("  camera_profile_state: ", camera_state)
        _print_wrapped("  camera_profiles_path: ", camera_profiles_path)
        _print_yaml_block("[ROBOT PROFILE] camera profile:", {robot_name: camera_entry})

    sync_specs = _suggest_control_machine_sync_specs(robot_name, entry)
    if sync_specs:
        print("[ROBOT PROFILE] Control-machine registration/approval source for this robot:")
        print(f"  {sync_specs[0]}")
        print("[ROBOT PROFILE] Explicit sync form if you want to force the robot name:")
        print(f"  {sync_specs[1]}")

    print("[OK] Local robot profile is prepared on this robot.")
    print(
        "[NEXT] Register/approve this robot on the control machine with "
        "sync_robot_entries_core before expecting FPV UI drive/autonomy control."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
