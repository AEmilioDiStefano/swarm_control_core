#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

"""
Shared runtime defaults for workspace paths and robot identity.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


class MissingConfigError(RuntimeError):
    """Raised when required swarm runtime configuration is missing."""


def sanitize_ros_name(name: str, fallback: str = "") -> str:
    """
    Return a ROS-safe name (alphanumeric + underscore).
    """
    value = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip())
    value = value.strip("_")
    return value or str(fallback or "")


def _first_env_value(env_keys: tuple[str, ...]) -> str:
    for env_key in env_keys:
        value = str(os.environ.get(env_key, "")).strip()
        if value:
            return value
    return ""


def _workspace_from_config_path(raw_path: str) -> Optional[Path]:
    path = Path(str(raw_path).strip()).expanduser()
    if (
        path.parent.name == "config"
        and path.parent.parent.name == "swarm_control_core"
        and path.parent.parent.parent.name == "src"
    ):
        return path.parent.parent.parent.parent
    return None


def _community_config_dir() -> Path:
    value = _first_env_value(("SWARM_COM_CONFIG_DIR",))
    if value:
        return Path(value).expanduser()
    return Path.home() / ".config" / "swarm_control_core"


def _source_tree_config_file(filename: str) -> Optional[Path]:
    """
    Return config file path from source tree when available:
      <workspace>/src/swarm_control_core/config/<filename>
    """
    candidate = Path(__file__).resolve().parent.parent / "config" / filename
    if candidate.exists():
        return candidate
    return None


def _installed_share_config_file(filename: str) -> Optional[Path]:
    """
    Return config file path from installed share directory when available:
      <install>/share/swarm_control_core/config/<filename>
    """
    try:
        from ament_index_python.packages import get_package_share_directory  # type: ignore

        candidate = Path(get_package_share_directory("swarm_control_core")) / "config" / filename
        if candidate.exists():
            return candidate
    except Exception:
        pass
    return None


def detect_workspace_root() -> Path:
    """
    Resolve workspace root only from explicit configuration.
    """
    workspace_env = _first_env_value(("SWARM_COM_WORKSPACE_ROOT",))
    if workspace_env:
        return Path(workspace_env).expanduser()

    for env_key in (
        "PROFILES_PATH",
        "CAMERA_PROFILES_PATH",
        "SWARM_COM_PROFILES_PATH",
        "SWARM_COM_CAMERA_PROFILES_PATH",
        "CONTROL_TYPES_PATH",
        "CONTROL_INTERFACES_PATH",
        "CONTROL_INTERFACE_PATH",
        "CAPABILITY_PROFILES_PATH",
        "ADAPTER_PROFILES_PATH",
        "SWARM_COM_CONTROL_TYPES_PATH",
        "SWARM_COM_CONTROL_INTERFACES_PATH",
        "SWARM_COM_CONTROL_INTERFACE_PATH",
        "SWARM_COM_CAPABILITY_PROFILES_PATH",
        "SWARM_COM_ADAPTER_PROFILES_PATH",
    ):
        from_config = _workspace_from_config_path(os.environ.get(env_key, ""))
        if from_config is not None:
            return from_config

    raise MissingConfigError(
        "Missing workspace root configuration. Set SWARM_COM_WORKSPACE_ROOT "
        "or provide PROFILES_PATH/CAMERA_PROFILES_PATH under "
        "<workspace>/src/swarm_control_core/config/."
    )


def default_profiles_path() -> str:
    value = _first_env_value(("PROFILES_PATH", "SWARM_COM_PROFILES_PATH"))
    if value:
        return str(Path(value).expanduser())

    config_dir = _community_config_dir()
    new_path = config_dir / "robot_instances.yaml"
    if new_path.exists():
        return str(new_path)
    legacy_path = config_dir / "robot_profiles.yaml"
    if legacy_path.exists():
        return str(legacy_path)

    source_default = _source_tree_config_file("robot_instances.yaml")
    if source_default is not None:
        return str(source_default)

    share_default = _installed_share_config_file("robot_instances.yaml")
    if share_default is not None:
        return str(share_default)

    return str(new_path)


def default_camera_profiles_path() -> str:
    value = _first_env_value(("CAMERA_PROFILES_PATH", "SWARM_COM_CAMERA_PROFILES_PATH"))
    if value:
        return str(Path(value).expanduser())

    runtime_path = _community_config_dir() / "camera_profiles.yaml"
    if runtime_path.exists():
        return str(runtime_path)

    source_default = _source_tree_config_file("camera_profiles.yaml")
    if source_default is not None:
        return str(source_default)

    share_default = _installed_share_config_file("camera_profiles.yaml")
    if share_default is not None:
        return str(share_default)

    return str(runtime_path)


def default_presets_dir() -> str:
    presets_env = _first_env_value(("SWARM_COM_PRESETS_DIR",))
    if presets_env:
        return str(Path(presets_env).expanduser())

    workspace_env = _first_env_value(("SWARM_COM_WORKSPACE_ROOT",))
    if workspace_env:
        return str(Path(workspace_env).expanduser() / "src" / "swarm_control_core" / "config" / "presets")

    profiles_path = _first_env_value(("PROFILES_PATH", "SWARM_COM_PROFILES_PATH"))
    from_config = _workspace_from_config_path(profiles_path)
    if from_config is not None:
        return str(from_config / "src" / "swarm_control_core" / "config" / "presets")

    source_tree_presets = Path(__file__).resolve().parent.parent / "config" / "presets"
    if source_tree_presets.exists():
        return str(source_tree_presets)

    try:
        from ament_index_python.packages import get_package_share_directory  # type: ignore

        share_presets = Path(get_package_share_directory("swarm_control_core")) / "config" / "presets"
        if share_presets.exists():
            return str(share_presets)
    except Exception:
        pass

    raise MissingConfigError(
        "Missing presets directory configuration. Set SWARM_COM_PRESETS_DIR, "
        "or set SWARM_COM_WORKSPACE_ROOT, or set PROFILES_PATH."
    )


def default_robot_name() -> str:
    value = _first_env_value(("SWARM_COM_ROBOT_NAME", "ROBOT_NAME"))
    sanitized = sanitize_ros_name(value)
    if sanitized:
        return sanitized

    raise MissingConfigError(
        "Missing robot identity. Set SWARM_COM_ROBOT_NAME (or ROBOT_NAME), "
        "or pass robot_name explicitly."
    )
