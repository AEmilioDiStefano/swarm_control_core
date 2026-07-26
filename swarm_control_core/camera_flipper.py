#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from .config_io import atomic_write_text, locked_config
from .path_defaults import MissingConfigError, default_camera_profiles_path, default_robot_name
from .save_camera_profile import CameraCandidate, _inventory_camera_candidates, _print_wrapped


FlipAction = str
EXIT_ACTIONS = ("exit", "exit")


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"defaults": {}, "profiles": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    defaults = data.get("defaults", {})
    profiles = data.get("profiles", {})
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(profiles, dict):
        profiles = {}
    data["defaults"] = defaults
    data["profiles"] = profiles
    return data


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    with locked_config(path):
        atomic_write_text(path, yaml.safe_dump(data, sort_keys=False))


def _resolved_device_path(device: str) -> str:
    value = str(device or "").strip()
    if not value:
        return ""
    try:
        path = Path(value).expanduser()
        if path.exists():
            return str(path.resolve())
    except Exception:
        return ""
    return ""


def camera_devices_match(left: str, right: str) -> bool:
    left_s = str(left or "").strip()
    right_s = str(right or "").strip()
    if not left_s or not right_s:
        return False
    if left_s == right_s:
        return True
    left_resolved = _resolved_device_path(left_s)
    right_resolved = _resolved_device_path(right_s)
    return bool(left_resolved and right_resolved and left_resolved == right_resolved)


def _find_current_camera(profile: Dict[str, Any], candidates: Sequence[CameraCandidate]) -> Optional[CameraCandidate]:
    profile_device = str(profile.get("device", "")).strip()
    for candidate in candidates:
        if camera_devices_match(profile_device, candidate.device):
            return candidate
    return None


def _bool_from_profile(profile: Dict[str, Any], key: str) -> bool:
    raw = profile.get(key, False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def apply_flip_action(current: bool, action: FlipAction) -> bool:
    action = str(action or "keep").strip().lower()
    if action == "keep":
        return bool(current)
    if action == "on":
        return True
    if action == "off":
        return False
    if action == "toggle":
        return not bool(current)
    raise ValueError(f"unsupported flip action: {action}")


def actions_from_set_mode(set_mode: str) -> Tuple[FlipAction, FlipAction]:
    mode = str(set_mode or "").strip().lower()
    if not mode:
        return "keep", "keep"
    if mode == "none":
        return "off", "off"
    if mode == "horizontal":
        return "on", "off"
    if mode == "vertical":
        return "off", "on"
    if mode == "both":
        return "on", "on"
    raise ValueError(f"unsupported set mode: {set_mode}")


def update_orientation_profile(
    profile: Dict[str, Any],
    *,
    horizontal_action: FlipAction,
    vertical_action: FlipAction,
    matched_camera: Optional[CameraCandidate],
) -> Dict[str, Any]:
    updated = dict(profile)
    flip_horizontal = apply_flip_action(
        _bool_from_profile(profile, "flip_horizontal"),
        horizontal_action,
    )
    flip_vertical = apply_flip_action(
        _bool_from_profile(profile, "flip_vertical"),
        vertical_action,
    )
    updated["flip_horizontal"] = flip_horizontal
    updated["flip_vertical"] = flip_vertical

    guard_device = ""
    guard_name = ""
    if matched_camera is not None:
        guard_device = str(matched_camera.device or "").strip()
        guard_name = str(matched_camera.display_name or "").strip()
    else:
        guard_device = str(profile.get("device", "")).strip()
        guard_name = str(profile.get("camera_name", "")).strip()

    if flip_horizontal or flip_vertical:
        updated["orientation_device"] = guard_device
        updated["orientation_camera_name"] = guard_name
    else:
        updated["orientation_device"] = ""
        updated["orientation_camera_name"] = ""
    return updated


def _print_status(
    *,
    robot: str,
    profiles_path: Path,
    profile: Dict[str, Any],
    matched_camera: Optional[CameraCandidate],
    candidates: Sequence[CameraCandidate],
) -> None:
    print(f"[CAMERA FLIPPER] robot={robot}")
    _print_wrapped("  camera_profiles: ", profiles_path)
    _print_wrapped("  saved_device: ", profile.get("device", ""))
    _print_wrapped("  saved_camera: ", profile.get("camera_name", ""))
    _print_wrapped("  flip_horizontal: ", _bool_from_profile(profile, "flip_horizontal"))
    _print_wrapped("  flip_vertical: ", _bool_from_profile(profile, "flip_vertical"))
    _print_wrapped("  orientation_device: ", profile.get("orientation_device", ""))
    _print_wrapped("  orientation_camera_name: ", profile.get("orientation_camera_name", ""))
    if matched_camera is not None:
        _print_wrapped("  current_match: ", f"{matched_camera.display_name} ({matched_camera.device})")
    else:
        print("  current_match: no")
        if candidates:
            print("  detected_cameras:")
            for candidate in candidates:
                _print_wrapped("    - ", f"{candidate.display_name} ({candidate.device})")


def _print_menu_header(
    *,
    robot: str,
    profile: Dict[str, Any],
    matched_camera: Optional[CameraCandidate],
) -> None:
    current_h = _bool_from_profile(profile, "flip_horizontal")
    current_v = _bool_from_profile(profile, "flip_vertical")
    print()
    print("=== Camera Flipper Main Menu ===")
    print(f"Robot: {robot}")
    if matched_camera is not None:
        _print_wrapped("Camera: ", f"{matched_camera.display_name} ({matched_camera.device})")
    else:
        _print_wrapped("Camera: ", str(profile.get("device", "")))
    print(f"Current horizontal flip (left/right mirror): {current_h}")
    print(f"Current vertical flip (up/down): {current_v}")
    print()
    print("1) Flip horizontally / left-right mirror")
    print("2) Flip vertically / up-down")
    print("3) Clear all flips")
    print("4) Show status")
    print("5) Exit")


def _prompt_actions(
    *,
    robot: str,
    profile: Dict[str, Any],
    matched_camera: Optional[CameraCandidate],
) -> Tuple[FlipAction, FlipAction]:
    while True:
        _print_menu_header(robot=robot, profile=profile, matched_camera=matched_camera)
        raw = input("Select option [1-5]: ").strip().lower()
        if raw in ("5", "e", "exit", "q", "quit"):
            return EXIT_ACTIONS
        if raw in ("1", "h", "horizontal", "left", "right", "mirror"):
            return "toggle", "keep"
        if raw in ("2", "v", "vertical", "up", "down"):
            return "keep", "toggle"
        if raw in ("3", "n", "none", "clear", "reset"):
            return "off", "off"
        if raw in ("4", "s", "status"):
            print()
            _print_wrapped("saved_device: ", profile.get("device", ""))
            _print_wrapped("orientation_device: ", profile.get("orientation_device", ""))
            input("Press Enter to return to the camera flipper menu...")
            continue
        print("[WARN] Enter 1, 2, 3, 4, or 5.")


def _save_orientation_update(
    *,
    data: Dict[str, Any],
    profiles: Dict[str, Any],
    robot: str,
    profiles_path: Path,
    profile: Dict[str, Any],
    matched_camera: Optional[CameraCandidate],
    horizontal_action: FlipAction,
    vertical_action: FlipAction,
    dry_run: bool,
    show_menu_tip: bool = False,
) -> Dict[str, Any]:
    updated = update_orientation_profile(
        profile,
        horizontal_action=horizontal_action,
        vertical_action=vertical_action,
        matched_camera=matched_camera,
    )
    print(f"[CAMERA FLIPPER] robot={robot}")
    _print_wrapped("  camera_profiles: ", profiles_path)
    _print_wrapped("  current_camera: ", (
        f"{matched_camera.display_name} ({matched_camera.device})"
        if matched_camera is not None
        else f"forced profile device ({profile.get('device', '')})"
    ))
    _print_wrapped(
        "  flip_horizontal: ",
        f"{_bool_from_profile(profile, 'flip_horizontal')} -> {updated['flip_horizontal']}",
    )
    _print_wrapped(
        "  flip_vertical: ",
        f"{_bool_from_profile(profile, 'flip_vertical')} -> {updated['flip_vertical']}",
    )
    _print_wrapped("  orientation_device: ", updated.get("orientation_device", ""))

    if dry_run:
        print("[DRY RUN] No file was written.")
        return updated

    profiles[robot] = updated
    data["profiles"] = profiles
    _write_yaml(profiles_path, data)
    print("[OK] camera orientation saved.")
    print("[NEXT] Restart robot bringup so FPV reloads the camera profile.")
    if show_menu_tip:
        print("[TIP] Run camera_flipper_core without --set to open the interactive menu.")
    return updated


def _resolve_robot(raw_robot: str) -> str:
    robot = str(raw_robot or "").strip()
    if robot:
        return robot
    return default_robot_name()


def _resolve_profiles_path(raw_path: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        value = default_camera_profiles_path()
    return Path(value).expanduser()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Set software camera flips in camera_profiles.yaml, guarded to the "
            "currently plugged-in camera for this robot."
        )
    )
    parser.add_argument("--robot", default="", help="Robot profile name; defaults to this Linux user/robot.")
    parser.add_argument("--camera-profiles", default="", help="Path to camera_profiles.yaml.")
    parser.add_argument(
        "--horizontal",
        choices=("keep", "on", "off", "toggle"),
        default="keep",
        help="Set or toggle horizontal mirror correction.",
    )
    parser.add_argument(
        "--vertical",
        choices=("keep", "on", "off", "toggle"),
        default="keep",
        help="Set or toggle vertical flip correction.",
    )
    parser.add_argument(
        "--set",
        choices=("none", "horizontal", "vertical", "both"),
        default="",
        help="Convenience mode: set both axes at once.",
    )
    parser.add_argument("--status", action="store_true", help="Print current orientation settings and exit.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even when the saved camera profile does not match a currently detected camera.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the change without writing YAML.")
    args = parser.parse_args(argv)

    try:
        robot = _resolve_robot(args.robot)
        profiles_path = _resolve_profiles_path(args.camera_profiles)
    except MissingConfigError as ex:
        print(f"[ERROR] {ex}", file=sys.stderr)
        return 2

    data = _load_yaml(profiles_path)
    profiles = data.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        print("[ERROR] camera_profiles.yaml has invalid 'profiles' mapping.", file=sys.stderr)
        return 2

    profile = profiles.get(robot)
    if not isinstance(profile, dict):
        print(f"[ERROR] No camera profile exists for robot '{robot}'.", file=sys.stderr)
        print("Run save_camera_profile_core or quickstart step2 on the robot first.", file=sys.stderr)
        return 2
    if not str(profile.get("device", "")).strip():
        print(f"[ERROR] Camera profile for robot '{robot}' has no device.", file=sys.stderr)
        print("Run save_camera_profile_core or quickstart step2 on the robot first.", file=sys.stderr)
        return 2

    candidates = _inventory_camera_candidates()
    matched_camera = _find_current_camera(profile, candidates)

    if args.status:
        _print_status(
            robot=robot,
            profiles_path=profiles_path,
            profile=profile,
            matched_camera=matched_camera,
            candidates=candidates,
        )
        return 0

    set_h, set_v = actions_from_set_mode(args.set)
    horizontal_action = set_h if set_h != "keep" else str(args.horizontal or "keep")
    vertical_action = set_v if set_v != "keep" else str(args.vertical or "keep")

    interactive = False
    if horizontal_action == "keep" and vertical_action == "keep":
        _print_status(
            robot=robot,
            profiles_path=profiles_path,
            profile=profile,
            matched_camera=matched_camera,
            candidates=candidates,
        )
        if sys.stdin.isatty():
            interactive = True
        else:
            print("[NEXT] Add --set horizontal, --set vertical, --set both, or --set none to change orientation.")
            return 0

    if matched_camera is None and not args.force:
        _print_status(
            robot=robot,
            profiles_path=profiles_path,
            profile=profile,
            matched_camera=matched_camera,
            candidates=candidates,
        )
        print(
            "[ERROR] Refusing to save camera flips because the saved camera is not the current plugged-in camera.",
            file=sys.stderr,
        )
        print(
            "This prevents a flip needed by one camera from being inherited by another camera. "
            "Plug in the saved camera, re-run save_camera_profile_core for the new camera, or use --force.",
            file=sys.stderr,
        )
        return 2

    if interactive:
        while True:
            horizontal_action, vertical_action = _prompt_actions(
                robot=robot,
                profile=profile,
                matched_camera=matched_camera,
            )
            if (horizontal_action, vertical_action) == EXIT_ACTIONS:
                print("[OK] Exiting camera flipper.")
                return 0
            profile = _save_orientation_update(
                data=data,
                profiles=profiles,
                robot=robot,
                profiles_path=profiles_path,
                profile=profile,
                matched_camera=matched_camera,
                horizontal_action=horizontal_action,
                vertical_action=vertical_action,
                dry_run=args.dry_run,
                show_menu_tip=False,
            )
            if args.dry_run:
                return 0
            input("Press Enter to return to the camera flipper menu, or Ctrl-C to stop...")

    if horizontal_action == "keep" and vertical_action == "keep":
        print("[OK] No camera orientation changes requested.")
        return 0

    _save_orientation_update(
        data=data,
        profiles=profiles,
        robot=robot,
        profiles_path=profiles_path,
        profile=profile,
        matched_camera=matched_camera,
        horizontal_action=horizontal_action,
        vertical_action=vertical_action,
        dry_run=args.dry_run,
        show_menu_tip=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
