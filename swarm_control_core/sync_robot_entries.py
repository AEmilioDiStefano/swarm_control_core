#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

from __future__ import annotations

import argparse
import getpass
import json
import socket
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .configure_robot_profile import (
    _config_dir,
    _default_workspace_root,
    _load_robot_registry,
    _append_robot_to_repo_file,
    _repo_robot_instances_path,
    _runtime_robot_instances_paths,
    _write_yaml,
    quarantine_invalid_runtime_robot_entries,
    repair_invalid_runtime_robot_entries,
    refresh_runtime_core_profiles,
)
from .drive_profiles import load_profile_registry
from .save_camera_profile import _acquire_prompt_input, _print_wrapped, _read_prompt_line


RobotEntry = Dict[str, Any]
SyncResult = Dict[str, Any]

_REMOTE_REGISTRY_QUERY = textwrap.dedent(
    """
    import getpass
    import json
    import socket
    import sys
    from pathlib import Path

    try:
        import yaml
    except Exception as exc:
        print(json.dumps({"error": f"PyYAML unavailable on remote host: {exc}"}))
        raise SystemExit(2)

    runtime_path = Path.home() / ".config" / "swarm_control_core" / "robot_instances.yaml"
    if not runtime_path.exists():
        print(json.dumps({"error": f"Runtime robot_instances.yaml not found: {runtime_path}"}))
        raise SystemExit(3)

    try:
        data = yaml.safe_load(runtime_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(json.dumps({"error": f"Unable to parse runtime robot_instances.yaml: {exc}"}))
        raise SystemExit(4)

    if not isinstance(data, dict):
        print(json.dumps({"error": "Runtime robot_instances.yaml must be a YAML mapping."}))
        raise SystemExit(5)

    print(json.dumps({
        "runtime_path": str(runtime_path),
        "remote_user": getpass.getuser(),
        "remote_host": socket.gethostname().split(".")[0],
        "registry": data,
    }))
    """
).strip()


def _parse_source_spec(spec: str) -> Tuple[str, str]:
    raw = str(spec or "").strip()
    if not raw:
        raise ValueError("Source spec cannot be empty.")
    if "=" in raw:
        robot_name, target = raw.split("=", 1)
        robot_name = str(robot_name).strip()
        target = str(target).strip()
        if not robot_name:
            raise ValueError(f"Invalid source spec '{spec}': robot name before '=' cannot be empty.")
        if not target:
            raise ValueError(f"Invalid source spec '{spec}': ssh target after '=' cannot be empty.")
        return robot_name, target
    return "", raw


def _normalize_ssh_target(value: Any) -> str:
    return str(value or "").strip().lower()


def _select_robot_entry_from_registry(
    registry: Dict[str, Any],
    *,
    used_target: str,
    remote_user: str,
    remote_host: str,
    requested_robot_name: str = "",
) -> Tuple[str, RobotEntry]:
    robots = registry.get("robots", {}) or {}
    if not isinstance(robots, dict) or not robots:
        raise ValueError("Remote robot_instances.yaml does not define any robots.")

    requested = str(requested_robot_name or "").strip()
    if requested:
        entry = robots.get(requested)
        if not isinstance(entry, dict):
            known = ", ".join(sorted(str(k) for k in robots.keys())) or "<none>"
            raise ValueError(
                f"Requested robot '{requested}' not found in remote robot_instances.yaml. Known robots: {known}"
            )
        return requested, dict(entry)

    expected_targets = {
        _normalize_ssh_target(used_target),
        _normalize_ssh_target(f"{remote_user}@{remote_host}.local"),
        _normalize_ssh_target(f"{remote_user}@{remote_host}"),
    }

    exact_matches: List[str] = []
    for name, entry in robots.items():
        if not isinstance(entry, dict):
            continue
        ssh_target = _normalize_ssh_target(entry.get("ssh_target", ""))
        if ssh_target and ssh_target in expected_targets:
            exact_matches.append(str(name))

    if len(exact_matches) == 1:
        match = exact_matches[0]
        return match, dict(robots[match])
    if len(exact_matches) > 1:
        raise ValueError(
            f"Remote robot selection is ambiguous for target '{used_target}'. Matches: {', '.join(sorted(exact_matches))}. "
            "Pass source as robot_name=ssh_target to disambiguate."
        )

    for candidate_name in (remote_user, remote_host):
        entry = robots.get(candidate_name)
        if isinstance(entry, dict):
            return str(candidate_name), dict(entry)

    broad_matches: List[str] = []
    expected_user = str(remote_user or "").strip().lower()
    expected_host = str(remote_host or "").strip().lower()
    for name, entry in robots.items():
        if not isinstance(entry, dict):
            continue
        ssh_target = _normalize_ssh_target(entry.get("ssh_target", ""))
        if ssh_target.startswith(f"{expected_user}@") and f"@{expected_host}" in ssh_target:
            broad_matches.append(str(name))

    if len(broad_matches) == 1:
        match = broad_matches[0]
        return match, dict(robots[match])
    if len(broad_matches) > 1:
        raise ValueError(
            f"Remote robot selection is ambiguous for remote host '{remote_user}@{remote_host}'. "
            f"Matches: {', '.join(sorted(broad_matches))}. Pass source as robot_name=ssh_target to disambiguate."
        )

    known = ", ".join(sorted(str(k) for k in robots.keys())) or "<none>"
    raise ValueError(
        f"Could not infer which remote robot entry belongs to '{used_target}'. "
        f"Pass source as robot_name=ssh_target. Known remote robots: {known}"
    )


def _format_ready_robot_label(name: str, entry: Dict[str, Any]) -> str:
    robot_name = str(name).strip()
    ssh_target = str((entry or {}).get("ssh_target", "")).strip()
    return ssh_target or robot_name or "<unknown>"


def _print_ready_robot_labels(prefix: str, labels: Sequence[str]) -> None:
    clean = [str(label).strip() for label in labels if str(label).strip()]
    print(prefix)
    if not clean:
        print(f"{prefix}   <none>")
        print(prefix)
        return
    for index, label in enumerate(clean):
        if index > 0:
            print(prefix)
        print(f"{prefix}   {label}")
    print(prefix)


def _collect_sources(initial_specs: Sequence[str], *, ready_robot_labels: Sequence[str]) -> List[str]:
    specs = [str(spec).strip() for spec in initial_specs if str(spec).strip()]
    if specs:
        return specs

    prompt_input = _acquire_prompt_input()
    if prompt_input is None:
        raise RuntimeError(
            "No --source values were provided and no interactive terminal is available. "
            "Pass one or more --source values like robot_name=robot_user@robot_host.local."
        )

    print("[SYNC] This command is intended to run on the control machine.")
    print("[SYNC] Check the list below for every robot you intend to control in this session.")
    print("[SYNC] If they are all listed, press Enter on a blank line.")
    print(
        "[SYNC] If any are missing, enter each missing robot as "
        "username@hostname.local or robot_name=username@hostname.local."
    )
    print("[SYNC] Press Enter on a blank line when finished.")
    print("[SYNC] Ready registered/trusted robots:")
    _print_ready_robot_labels("[SYNC]", ready_robot_labels)
    collected: List[str] = []
    while True:
        raw = _read_prompt_line(
            prompt_input=prompt_input,
            prompt="Missing robot source [Enter if all session robots are listed]: ",
        ).strip()
        if not raw:
            break
        collected.append(raw)

    if prompt_input is not sys.stdin:
        try:
            prompt_input.close()
        except Exception:
            pass

    return collected


def _known_runtime_robot_names(runtime_profiles_paths: Sequence[Path]) -> List[str]:
    names: set[str] = set()
    for path in runtime_profiles_paths:
        try:
            registry = _load_robot_registry(path)
        except Exception:
            continue
        robots = registry.get("robots", {}) or {}
        if not isinstance(robots, dict):
            continue
        for name in robots.keys():
            if str(name).strip():
                names.add(str(name).strip())
    return sorted(names)


def _loadable_runtime_robot_labels(runtime_profiles_paths: Sequence[Path]) -> List[str]:
    labels: Dict[str, str] = {}
    for path in runtime_profiles_paths:
        try:
            registry = load_profile_registry(str(path))
        except Exception:
            continue
        robots = registry.get("robots", {}) or {}
        if not isinstance(robots, dict):
            continue
        for name, entry in robots.items():
            robot_name = str(name).strip()
            if robot_name and isinstance(entry, dict):
                labels[robot_name] = _format_ready_robot_label(robot_name, entry)
    return [labels[name] for name in sorted(labels.keys())]


def _print_profile_wizard_hint(robot_name: str = "") -> None:
    prefix = f" for '{robot_name}'" if robot_name else ""
    print(
        f"[SYNC] If the missing robot has no local profile yet{prefix}, run this on that robot first:",
        file=sys.stderr,
    )
    print(
        "[SYNC]   export SWARM_CORE_ROBOT_NAME=\"${SWARM_CORE_ROBOT_NAME:-$(id -un)}\"",
        file=sys.stderr,
    )
    print("[SYNC]   export ROBOT_NAME=\"${ROBOT_NAME:-$SWARM_CORE_ROBOT_NAME}\"", file=sys.stderr)
    print("[SYNC]   \"$SC/scripts/swarm_core_quickstart_step2.sh\"", file=sys.stderr)
    print(
        "[SYNC] Then rerun this control-machine sync step and enter the source printed by the robot.",
        file=sys.stderr,
    )


def _fetch_remote_registry(target: str) -> Dict[str, Any]:
    proc = subprocess.run(
        ["ssh", target, "python3", "-"],
        input=_REMOTE_REGISTRY_QUERY,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"ssh exited with code {proc.returncode}"
        raise RuntimeError(f"Remote query failed for {target}: {detail}")

    payload = (proc.stdout or "").strip()
    if not payload:
        raise RuntimeError(f"Remote query for {target} returned no data.")

    try:
        data = json.loads(payload)
    except Exception as exc:
        raise RuntimeError(f"Remote query for {target} returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Remote query for {target} returned an invalid payload.")
    if str(data.get("error", "")).strip():
        raise RuntimeError(f"Remote query failed for {target}: {data['error']}")
    return data


def _merge_imported_robot_entry(
    *,
    repo_profiles_path: Path,
    runtime_profiles_paths: Sequence[Path],
    control_types_path: Path,
    control_interfaces_path: Path,
    robot_name: str,
    entry: RobotEntry,
    update_source_baseline: bool = False,
) -> Tuple[str, List[SyncResult]]:
    repo_registry = _load_robot_registry(repo_profiles_path)
    repo_robots = repo_registry.get("robots", {}) or {}
    if not isinstance(repo_robots, dict):
        repo_robots = {}

    existing_repo_entry = repo_robots.get(robot_name)
    if not isinstance(existing_repo_entry, dict):
        repo_state = "missing_entry"
    elif dict(existing_repo_entry) != dict(entry):
        repo_state = "stale_entry"
    else:
        repo_state = "already_synced"

    if update_source_baseline and repo_state != "already_synced":
        repo_robots[robot_name] = dict(entry)
        repo_registry["robots"] = repo_robots
        if repo_state == "missing_entry":
            _append_robot_to_repo_file(repo_profiles_path, robot_name, entry, repo_registry)
        else:
            _write_yaml(repo_profiles_path, repo_registry)

    runtime_results: List[SyncResult] = []
    for runtime_path in runtime_profiles_paths:
        runtime_exists = runtime_path.exists()
        runtime_registry = _load_robot_registry(runtime_path)
        runtime_registry["schema_version"] = repo_registry.get("schema_version", "1.0")
        runtime_registry["defaults"] = dict(repo_registry.get("defaults", {}) or {})
        repaired_invalid_entries = repair_invalid_runtime_robot_entries(
            runtime_registry=runtime_registry,
            repo_registry=repo_registry,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
        )
        quarantined_invalid_entries = quarantine_invalid_runtime_robot_entries(
            runtime_registry=runtime_registry,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
            skip_robot_names=(robot_name,),
        )
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
        if sync_state != "already_synced" or repaired_invalid_entries or quarantined_invalid_entries:
            _write_yaml(runtime_path, runtime_registry)

        runtime_results.append(
            {
                "path": runtime_path,
                "state": sync_state,
                "repaired": sync_state != "already_synced",
                "repaired_invalid_entries": repaired_invalid_entries,
                "quarantined_invalid_entries": quarantined_invalid_entries,
            }
        )

    return repo_state, runtime_results


def _print_sync_result(result: SyncResult, *, robot_name: str, prefix: str) -> None:
    path = result["path"]
    state = str(result.get("state", "")).strip()
    if state == "missing_file":
        print(f"[SYNC] {prefix} file was missing at {path}. Repairing now.")
        print(f"[SYNC] {prefix} file repaired successfully at {path}.")
    elif state == "missing_entry":
        print(f"[SYNC] {prefix} entry for '{robot_name}' was missing at {path}. Repairing now.")
        print(f"[SYNC] {prefix} entry repaired successfully at {path}.")
    elif state == "stale_entry":
        print(f"[SYNC] {prefix} entry for '{robot_name}' was stale at {path}. Repairing now.")
        print(f"[SYNC] {prefix} entry repaired successfully at {path}.")
    else:
        print(f"[SYNC] {prefix} entry already matched at {path}.")
    repaired_invalid_entries = result.get("repaired_invalid_entries", []) or []
    if repaired_invalid_entries:
        names = ", ".join(sorted(str(name) for name in repaired_invalid_entries))
        print(f"[SYNC] Repaired stale/invalid runtime entries from baseline at {path}: {names}")
    quarantined_invalid_entries = result.get("quarantined_invalid_entries", []) or []
    if quarantined_invalid_entries:
        names = ", ".join(sorted(str(name) for name in quarantined_invalid_entries))
        print(f"[SYNC] Quarantined invalid runtime entries that are not in the current baseline at {path}: {names}")


def _repair_runtime_registries_before_prompt(
    *,
    repo_profiles_path: Path,
    runtime_profiles_paths: Sequence[Path],
    control_types_path: Path,
    control_interfaces_path: Path,
) -> None:
    repo_registry = _load_robot_registry(repo_profiles_path)
    for runtime_path in runtime_profiles_paths:
        runtime_registry = _load_robot_registry(runtime_path)
        changed = False
        repo_defaults = dict(repo_registry.get("defaults", {}) or {})
        if runtime_registry.get("schema_version") != repo_registry.get("schema_version", "1.0"):
            runtime_registry["schema_version"] = repo_registry.get("schema_version", "1.0")
            changed = True
        if runtime_registry.get("defaults", {}) != repo_defaults:
            runtime_registry["defaults"] = repo_defaults
            changed = True
        repaired_invalid_entries = repair_invalid_runtime_robot_entries(
            runtime_registry=runtime_registry,
            repo_registry=repo_registry,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
        )
        if repaired_invalid_entries:
            names = ", ".join(sorted(str(name) for name in repaired_invalid_entries))
            print(f"[SYNC] Repaired stale/invalid runtime entries from baseline at {runtime_path}: {names}")
            changed = True
        quarantined_invalid_entries = quarantine_invalid_runtime_robot_entries(
            runtime_registry=runtime_registry,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
        )
        if quarantined_invalid_entries:
            names = ", ".join(sorted(str(name) for name in quarantined_invalid_entries))
            print(
                f"[SYNC] Quarantined invalid runtime entries that are not in the current baseline at "
                f"{runtime_path}: {names}"
            )
            print(
                "[SYNC] Quarantined robots are not ready for control until their local profile is regenerated "
                "on the robot and synced again."
            )
            changed = True
        if changed:
            _write_yaml(runtime_path, runtime_registry)


def _print_core_profile_result(result: SyncResult) -> None:
    path = result["path"]
    state = str(result.get("state", "")).strip()
    if state == "already_synced":
        print(f"[SYNC] Runtime core profile already current: {path}")
    elif result.get("repaired"):
        print(f"[SYNC] Runtime core profile refreshed: {path}")
    else:
        print(f"[SYNC] Runtime core profile check failed ({state}): {path}")


def _detect_likely_local_robot_source(
    *,
    repo_profiles_path: Path,
    runtime_profiles_paths: Sequence[Path],
) -> Optional[Tuple[str, str]]:
    current_user = str(getpass.getuser() or "").strip()
    current_host = str(socket.gethostname() or "").strip().split(".")[0]
    if not current_user or not current_host:
        return None

    expected_targets = {
        _normalize_ssh_target(f"{current_user}@{current_host}.local"),
        _normalize_ssh_target(f"{current_user}@{current_host}"),
    }

    matches: Dict[str, str] = {}
    seen_paths: List[Path] = []
    for path in list(runtime_profiles_paths) + [repo_profiles_path]:
        if path in seen_paths:
            continue
        seen_paths.append(path)
        registry = _load_robot_registry(path)
        robots = registry.get("robots", {}) or {}
        if not isinstance(robots, dict):
            continue
        for name, entry in robots.items():
            if not isinstance(entry, dict):
                continue
            robot_name = str(name).strip()
            ssh_target = str(entry.get("ssh_target", "")).strip()
            normalized_target = _normalize_ssh_target(ssh_target)
            if normalized_target in expected_targets or robot_name in {current_user, current_host}:
                matches[robot_name] = ssh_target or f"{current_user}@{current_host}.local"

    if len(matches) != 1:
        return None

    robot_name, ssh_target = next(iter(matches.items()))
    return robot_name, ssh_target


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull robot instance entries from robots and merge them into the control machine.",
    )
    parser.add_argument("--workspace", default="", help="Workspace root containing src/swarm_control_core")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Robot source as ssh_target or robot_name=ssh_target. Repeat for multiple robots.",
    )
    parser.add_argument(
        "--update-source-baseline",
        action="store_true",
        help=(
            "Also write src/swarm_control_core/config/robot_instances.yaml. "
            "Default registration writes runtime trust config only so git pulls stay clean."
        ),
    )
    args = parser.parse_args(argv)

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

    runtime_profiles_paths = [
        path for path in _runtime_robot_instances_paths()
        if path != repo_profiles_path
    ]
    if not runtime_profiles_paths:
        runtime_profiles_paths = [_config_dir() / "robot_instances.yaml"]

    refresh_runtime_core_profiles(workspace_root, runtime_profiles_paths)
    _repair_runtime_registries_before_prompt(
        repo_profiles_path=repo_profiles_path,
        runtime_profiles_paths=runtime_profiles_paths,
        control_types_path=control_types_path,
        control_interfaces_path=control_interfaces_path,
    )

    if not args.source:
        local_robot_hint = _detect_likely_local_robot_source(
            repo_profiles_path=repo_profiles_path,
            runtime_profiles_paths=runtime_profiles_paths,
        )
        if local_robot_hint is not None:
            local_robot_name, local_ssh_target = local_robot_hint
            print(
                f"[ERROR] This machine appears to be robot '{local_robot_name}' "
                f"with ssh_target '{local_ssh_target}'.",
                file=sys.stderr,
            )
            print(
                "[ERROR] sync_robot_entries_core is meant to run on the control machine, not on the robot itself.",
                file=sys.stderr,
            )
            print("[ERROR] On the control machine, run the same command and then enter one of these:", file=sys.stderr)
            print(f"[ERROR]   {local_ssh_target}", file=sys.stderr)
            print(f"[ERROR]   {local_robot_name}={local_ssh_target}", file=sys.stderr)
            return 2

    try:
        source_specs = _collect_sources(
            args.source,
            ready_robot_labels=_loadable_runtime_robot_labels(runtime_profiles_paths),
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    seen_robot_names: set[str] = set()

    for spec in source_specs:
        try:
            requested_robot_name, target = _parse_source_spec(spec)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2

        print(f"[SYNC] Pulling robot entry from {target}...")
        try:
            remote = _fetch_remote_registry(target)
            robot_name, entry = _select_robot_entry_from_registry(
                remote.get("registry", {}) or {},
                used_target=target,
                remote_user=str(remote.get("remote_user", "")).strip(),
                remote_host=str(remote.get("remote_host", "")).strip(),
                requested_robot_name=requested_robot_name,
            )
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            _print_profile_wizard_hint(requested_robot_name)
            return 2

        if robot_name in seen_robot_names:
            print(f"[SYNC] Robot '{robot_name}' was already synced earlier in this run. Skipping duplicate source {target}.")
            continue
        seen_robot_names.add(robot_name)

        print(f"[SYNC] Remote robot resolved as '{robot_name}'.")
        _print_wrapped("  remote_runtime_robot_instances: ", remote.get("runtime_path", ""))

        repo_state, runtime_results = _merge_imported_robot_entry(
            repo_profiles_path=repo_profiles_path,
            runtime_profiles_paths=runtime_profiles_paths,
            control_types_path=control_types_path,
            control_interfaces_path=control_interfaces_path,
            robot_name=robot_name,
            entry=entry,
            update_source_baseline=bool(args.update_source_baseline),
        )

        if repo_state == "already_synced":
            print(f"[SYNC] Control-machine baseline entry already matched in {repo_profiles_path}.")
        elif args.update_source_baseline and repo_state == "missing_entry":
            print(f"[SYNC] Control-machine baseline entry for '{robot_name}' was missing. Importing now.")
            print(f"[SYNC] Control-machine baseline entry imported successfully into {repo_profiles_path}.")
        elif args.update_source_baseline and repo_state == "stale_entry":
            print(f"[SYNC] Control-machine baseline entry for '{robot_name}' was stale. Updating now.")
            print(f"[SYNC] Control-machine baseline entry updated successfully in {repo_profiles_path}.")
        else:
            print(
                f"[SYNC] Control-machine baseline entry for '{robot_name}' is {repo_state}; "
                "leaving source baseline unchanged."
            )
            print("[SYNC] Runtime trust registry will be updated for control without dirtying the git checkout.")

        for result in runtime_results:
            _print_sync_result(result, robot_name=robot_name, prefix="control-machine runtime robot_instances.yaml")

        print("[SYNC] Imported robot entry:")
        print(textwrap.indent(json.dumps({robot_name: entry}, indent=2, sort_keys=False), "  "))

    _repair_runtime_registries_before_prompt(
        repo_profiles_path=repo_profiles_path,
        runtime_profiles_paths=runtime_profiles_paths,
        control_types_path=control_types_path,
        control_interfaces_path=control_interfaces_path,
    )

    core_results = refresh_runtime_core_profiles(workspace_root, runtime_profiles_paths)
    for result in core_results:
        _print_core_profile_result(result)

    for runtime_path in runtime_profiles_paths:
        try:
            registry = load_profile_registry(str(runtime_path))
        except Exception as exc:
            print(f"[ERROR] Control-machine runtime registry is not loadable at {runtime_path}: {exc}", file=sys.stderr)
            return 2
        robots = registry.get("robots", {}) or {}
        known = [
            _format_ready_robot_label(str(name), entry)
            for name, entry in sorted(robots.items(), key=lambda item: str(item[0]))
            if isinstance(entry, dict)
        ] if isinstance(robots, dict) else []
        print("[SYNC] Control-machine trusted robot registry load check OK:")
        _print_ready_robot_labels("[SYNC]", known)

    print("[OK] Control-machine robot registration/approval complete.")
    print("[OK] Registered/approved robots are ready for QUICKSTART handoff.")
    print("[NEXT] Restart the FPV UI so it reloads the trusted robot registry before driving.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
