#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0
"""
drive_profiles.py

This module loads a YAML registry and resolves
robot profiles. Keeping it separate makes the rest of the code (teleop, motor driver,
heartbeat) easier to read and test.

Profile entrypoint:
`robot_instances.yaml` is the only supported registry entrypoint. It is resolved
with sibling split config files such as `control_types.yaml` and
`control_interfaces.yaml`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import os

import yaml
from .path_defaults import MissingConfigError, default_profiles_path
from .profile_metadata import canonical_profile_name


_BUILTIN_ADAPTER_PROFILE_NAME = "passthrough_local"
_BUILTIN_ADAPTER_PROFILES: Dict[str, Dict[str, Any]] = {
    _BUILTIN_ADAPTER_PROFILE_NAME: {
        "adapter": "passthrough",
        "description": "Built-in fallback adapter profile (no translation).",
        "transport": "ros2_local",
        "params": {},
    }
}

def _default_profiles_path() -> Path:
    """
    Resolve the robot profile entrypoint from explicit environment configuration.
    """
    try:
        return Path(default_profiles_path()).expanduser()
    except MissingConfigError as ex:
        raise FileNotFoundError(str(ex)) from ex


def load_profile_registry(profiles_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load the full robot profile registry from YAML.

    Args:
        profiles_path:
            Optional explicit path to `robot_instances.yaml`.
            If None/empty, we use a reasonable default.

    Returns:
        A dict with keys like:
            - defaults
            - robots
            - drive_profiles
            - hardware_profiles
    """
    path = Path(profiles_path).expanduser() if profiles_path else _default_profiles_path()
    if not path.exists():
        raise FileNotFoundError(
            f"robot profile registry not found: {path}\n"
            "Fix by passing `profiles_path:=/full/path/to/robot_instances.yaml` "
            "or ensure the file exists in swarm_control_core/config/."
        )

    data = _load_yaml_mapping(path, "profile entrypoint")
    reg = _load_split_registry(path, data)
    _assert_no_camera_settings_in_robot_registry(reg, path)
    return reg


def _load_yaml_mapping(path: Path, label: str) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{label} YAML must be a mapping (dict). Got: {type(data)}")
    return data


def _load_split_registry(entry_path: Path, instances_data: Dict[str, Any]) -> Dict[str, Any]:
    if "robots" not in instances_data:
        raise ValueError(
            "Split profile entrypoint must contain top-level key 'robots'. "
            f"File: {entry_path}"
        )

    config_dir = entry_path.parent

    control_types_path = _resolve_split_path(
        config_dir=config_dir,
        fallback_name="control_types.yaml",
        env_keys=("CONTROL_TYPES_PATH", "SWARM_CORE_CONTROL_TYPES_PATH"),
    )
    control_interface_path = _resolve_split_path(
        config_dir=config_dir,
        fallback_name="control_interfaces.yaml",
        env_keys=(
            "CONTROL_INTERFACES_PATH",
            "SWARM_CORE_CONTROL_INTERFACES_PATH",
            "CONTROL_INTERFACE_PATH",
            "SWARM_CORE_CONTROL_INTERFACE_PATH",
        ),
    )
    capability_profiles_path = _resolve_split_path_optional(
        config_dir=config_dir,
        fallback_name="capability_profiles.yaml",
        env_keys=("CAPABILITY_PROFILES_PATH", "SWARM_CORE_CAPABILITY_PROFILES_PATH"),
    )
    adapter_profiles_path = _resolve_split_path_optional(
        config_dir=config_dir,
        fallback_name="adapter_profiles.yaml",
        env_keys=("ADAPTER_PROFILES_PATH", "SWARM_CORE_ADAPTER_PROFILES_PATH"),
    )

    control_types_data = _load_yaml_mapping(control_types_path, "control_types")
    control_interface_data = _load_yaml_mapping(control_interface_path, "control_interface")
    capability_profiles_data = (
        _load_yaml_mapping(capability_profiles_path, "capability_profiles")
        if capability_profiles_path is not None
        else {
            "schema_version": "1.0",
            "defaults": {},
            "capability_profiles": {},
        }
    )
    adapter_profiles_data = (
        _load_yaml_mapping(adapter_profiles_path, "adapter_profiles")
        if adapter_profiles_path is not None
        else {
            "schema_version": "1.0",
            "defaults": {"adapter_profile": _BUILTIN_ADAPTER_PROFILE_NAME},
            "adapter_profiles": dict(_BUILTIN_ADAPTER_PROFILES),
        }
    )

    control_types = control_types_data.get("control_types", {}) or {}
    control_interfaces = control_interface_data.get("control_interfaces", {}) or {}
    capability_profiles = capability_profiles_data.get("capability_profiles", {}) or {}
    adapter_profiles = adapter_profiles_data.get("adapter_profiles", {}) or {}

    if not isinstance(control_types, dict) or not control_types:
        raise ValueError(
            f"control_types.yaml must define non-empty mapping 'control_types'. File: {control_types_path}"
        )
    if not isinstance(control_interfaces, dict) or not control_interfaces:
        raise ValueError(
            f"control_interfaces.yaml must define non-empty mapping 'control_interfaces'. File: {control_interface_path}"
        )
    if not isinstance(capability_profiles, dict):
        raise ValueError(
            f"capability_profiles.yaml must define mapping 'capability_profiles'. File: {capability_profiles_path}"
        )
    if not isinstance(adapter_profiles, dict) or not adapter_profiles:
        label = str(adapter_profiles_path) if adapter_profiles_path is not None else "<builtin>"
        raise ValueError(
            f"adapter_profiles.yaml must define non-empty mapping 'adapter_profiles'. File: {label}"
        )

    inst_defaults = instances_data.get("defaults", {}) or {}
    ct_defaults = control_types_data.get("defaults", {}) or {}
    ci_defaults = control_interface_data.get("defaults", {}) or {}
    cap_defaults = capability_profiles_data.get("defaults", {}) or {}
    adapter_defaults = adapter_profiles_data.get("defaults", {}) or {}

    default_control_type = (
        inst_defaults.get("control_type")
        or inst_defaults.get("drive_profile")
        or ct_defaults.get("control_type")
    )
    default_control_interface = (
        inst_defaults.get("control_interface")
        or inst_defaults.get("hardware_profile")
        or ci_defaults.get("control_interface")
    )
    default_control_type = canonical_profile_name(control_types, str(default_control_type or ""))
    default_control_interface = canonical_profile_name(control_interfaces, str(default_control_interface or ""))
    default_capability_profile = (
        inst_defaults.get("capability_profile")
        or cap_defaults.get("capability_profile")
    )
    default_adapter_profile = (
        inst_defaults.get("adapter_profile")
        or adapter_defaults.get("adapter_profile")
        or _BUILTIN_ADAPTER_PROFILE_NAME
    )

    if default_control_type and default_control_type not in control_types:
        raise KeyError(
            f"Default control_type '{default_control_type}' not found in control_types.yaml"
        )
    if default_control_interface and default_control_interface not in control_interfaces:
        raise KeyError(
            f"Default control_interface '{default_control_interface}' not found in control_interfaces.yaml"
        )
    if (
        capability_profiles_path is not None
        and default_capability_profile
        and default_capability_profile not in capability_profiles
    ):
        raise KeyError(
            f"Default capability_profile '{default_capability_profile}' not found in capability_profiles.yaml"
        )
    if default_adapter_profile and default_adapter_profile not in adapter_profiles:
        raise KeyError(
            f"Default adapter_profile '{default_adapter_profile}' not found in adapter_profiles.yaml"
        )

    robots_raw = instances_data.get("robots", {}) or {}
    if not isinstance(robots_raw, dict):
        raise ValueError(
            f"robot instances entrypoint expects mapping at 'robots'. File: {entry_path}"
        )

    robots: Dict[str, Any] = {}
    for robot_name, raw_entry in robots_raw.items():
        entry = raw_entry or {}
        if not isinstance(entry, dict):
            raise ValueError(
                f"robots.{robot_name} must be a mapping in {entry_path}"
            )
        control_type_name = (
            entry.get("control_type")
            or entry.get("drive_profile")
            or default_control_type
        )
        control_interface_name = (
            entry.get("control_interface")
            or entry.get("hardware_profile")
            or default_control_interface
        )
        control_type_name = canonical_profile_name(control_types, str(control_type_name or ""))
        control_interface_name = canonical_profile_name(control_interfaces, str(control_interface_name or ""))
        capability_name = (
            entry.get("capability_profile")
            or default_capability_profile
        )
        adapter_name = (
            entry.get("adapter_profile")
            or default_adapter_profile
        )

        if control_type_name and control_type_name not in control_types:
            raise KeyError(
                f"robots.{robot_name}.control_type '{control_type_name}' not found in control_types.yaml"
            )
        if control_interface_name and control_interface_name not in control_interfaces:
            raise KeyError(
                f"robots.{robot_name}.control_interface '{control_interface_name}' not found in control_interfaces.yaml"
            )
        if (
            capability_profiles_path is not None
            and capability_name
            and capability_name not in capability_profiles
        ):
            raise KeyError(
                f"robots.{robot_name}.capability_profile '{capability_name}' not found in capability_profiles.yaml"
            )
        if adapter_name and adapter_name not in adapter_profiles:
            raise KeyError(
                f"robots.{robot_name}.adapter_profile '{adapter_name}' not found in adapter_profiles.yaml"
            )

        robots[str(robot_name)] = {
            **entry,
            # Runtime key names used by existing nodes.
            "drive_profile": control_type_name,
            "hardware_profile": control_interface_name,
            # Canonical split-layout keys.
            "control_type": control_type_name,
            "control_interface": control_interface_name,
            "capability_profile": capability_name,
            "adapter_profile": adapter_name,
        }

    reg = {
        "schema_version": str(instances_data.get("schema_version", "")).strip() or "1.0",
        "defaults": {
            "drive_profile": default_control_type,
            "hardware_profile": default_control_interface,
            "control_type": default_control_type,
            "control_interface": default_control_interface,
            "capability_profile": default_capability_profile,
            "adapter_profile": default_adapter_profile,
        },
        "robots": robots,
        # Runtime key names used by current nodes.
        "drive_profiles": control_types,
        "hardware_profiles": control_interfaces,
        # Split-layout native names retained for future use.
        "control_types": control_types,
        "control_interfaces": control_interfaces,
        "capability_profiles": capability_profiles,
        "adapter_profiles": adapter_profiles,
        "source_files": {
            "robot_instances": str(entry_path),
            "control_types": str(control_types_path),
            "control_interfaces": str(control_interface_path),
            "control_interface": str(control_interface_path),
            "capability_profiles": (
                str(capability_profiles_path)
                if capability_profiles_path is not None
                else "<omitted>"
            ),
            "adapter_profiles": (
                str(adapter_profiles_path)
                if adapter_profiles_path is not None
                else "<builtin>"
            ),
        },
    }
    return reg


def _resolve_split_path(config_dir: Path, fallback_name: str, env_keys: tuple[str, ...]) -> Path:
    for env_key in env_keys:
        raw = str(os.environ.get(env_key, "")).strip()
        if raw:
            p = Path(raw).expanduser()
            if p.exists():
                return p
            raise FileNotFoundError(
                f"{env_key} was set but file does not exist: {p}"
            )

    fallback = config_dir / fallback_name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Required split profile file not found: {fallback}. "
        f"Set {env_keys[0]} explicitly to override."
    )


def _resolve_split_path_optional(config_dir: Path, fallback_name: str, env_keys: tuple[str, ...]) -> Optional[Path]:
    for env_key in env_keys:
        raw = str(os.environ.get(env_key, "")).strip()
        if raw:
            p = Path(raw).expanduser()
            if p.exists():
                return p
            raise FileNotFoundError(
                f"{env_key} was set but file does not exist: {p}"
            )

    fallback = config_dir / fallback_name
    if fallback.exists():
        return fallback
    return None


def _assert_no_camera_settings_in_robot_registry(data: Dict[str, Any], path: Path) -> None:
    """
    Prevent conflicting camera config in the robot profile registry.

    Camera source-of-truth is config/camera_profiles.yaml (or explicit launch args).
    If camera keys are introduced in the robot profile registry they create ambiguity for
    operators, so we fail fast with a clear error.
    """
    forbidden_exact = {
        "video_device",
        "camera_device",
        "camera_profiles_path",
        "camera_profile_name",
        "camera_pipeline",
        "fourcc",
        "force_v4l2",
    }
    forbidden_param_like = {"device", "fps", "width", "height", "source"}

    offenders = []
    container_name_paths = {
        "robots",
        "drive_profiles",
        "hardware_profiles",
        "control_types",
        "control_interfaces",
        "capability_profiles",
        "adapter_profiles",
    }

    def _scan(node: Any, key_path: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                full = f"{key_path}.{key}" if key_path else key
                key_l = key.strip().lower()
                key_is_container_name = key_path in container_name_paths
                # Capability contract fields can legitimately include words like
                # "camera_required"; only runtime camera parameter keys must be blocked.
                under_capability_contracts = (
                    key_path == "capability_profiles"
                    or key_path.startswith("capability_profiles.")
                )
                if not key_is_container_name:
                    key_is_param_leaf = key_path.endswith(".params") or ".params." in key_path
                    if (
                        not under_capability_contracts
                        and (
                            key_l in forbidden_exact
                            or key_l.startswith("camera_")
                            or "camera" in key_l
                            or (key_is_param_leaf and key_l in forbidden_param_like)
                        )
                    ):
                        offenders.append(full)
                _scan(v, full)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                full = f"{key_path}[{i}]" if key_path else f"[{i}]"
                _scan(v, full)

    _scan(data, "")
    if offenders:
        preview = ", ".join(offenders[:8])
        more = "" if len(offenders) <= 8 else f" (+{len(offenders) - 8} more)"
        raise ValueError(
            "Camera-related keys are not allowed in the robot profile registry. "
            "Move camera settings to config/camera_profiles.yaml or pass explicit "
            "camera_* launch args. "
            f"File: {path}. Offending keys: {preview}{more}"
        )


def resolve_robot_profile(reg: Dict[str, Any], robot_name: str) -> Dict[str, Any]:
    """
    Resolve a robot into a concrete set of configuration fields.

    This takes:
      robots[robot_name] -> {control_type/drive_profile, control_interface/hardware_profile}
    then expands those names into actual config blocks.

    Returns a dict with:
        robot_name, drive_type, profile_name, hardware, drive, gpio, etc.
    """
    robot_name = str(robot_name).strip()
    if not robot_name:
        raise ValueError("resolve_robot_profile() requires a non-empty robot_name")

    robots = reg.get("robots", {})
    if robot_name not in robots:
        # Student-friendly error: show known robots
        known = ", ".join(sorted(robots.keys())) if robots else "<none>"
        raise KeyError(f"Unknown robot '{robot_name}'. Known robots: {known}")

    robot_entry = robots[robot_name] or {}
    defaults = reg.get("defaults", {}) or {}
    drive_profile_name = (
        robot_entry.get("control_type")
        or robot_entry.get("drive_profile")
        or defaults.get("control_type")
        or defaults.get("drive_profile")
    )
    hw_profile_name = (
        robot_entry.get("control_interface")
        or robot_entry.get("hardware_profile")
        or defaults.get("control_interface")
        or defaults.get("hardware_profile")
    )
    capability_profile_name = (
        robot_entry.get("capability_profile")
        or defaults.get("capability_profile")
    )
    adapter_profile_name = (
        robot_entry.get("adapter_profile")
        or defaults.get("adapter_profile")
        or _BUILTIN_ADAPTER_PROFILE_NAME
    )

    if not drive_profile_name:
        raise ValueError(
            f"No control_type/drive_profile resolved for robot '{robot_name}' "
            "(check defaults + robots section)"
        )
    if not hw_profile_name:
        raise ValueError(
            f"No control_interface/hardware_profile resolved for robot '{robot_name}' "
            "(check defaults + robots section)"
        )

    drive_profiles = (reg.get("drive_profiles", {}) or reg.get("control_types", {}) or {})
    hardware_profiles = (reg.get("hardware_profiles", {}) or reg.get("control_interfaces", {}) or {})
    capability_profiles = reg.get("capability_profiles", {}) or {}
    adapter_profiles = reg.get("adapter_profiles", {}) or {}
    drive_profile_name = canonical_profile_name(drive_profiles, str(drive_profile_name or ""))
    hw_profile_name = canonical_profile_name(hardware_profiles, str(hw_profile_name or ""))

    if drive_profile_name not in drive_profiles:
        raise KeyError(
            f"control_type/drive_profile '{drive_profile_name}' not found in drive_profiles/control_types"
        )
    if hw_profile_name not in hardware_profiles:
        raise KeyError(
            f"control_interface/hardware_profile '{hw_profile_name}' not found in hardware_profiles/control_interfaces"
        )
    if adapter_profile_name not in adapter_profiles:
        raise KeyError(
            f"adapter_profile '{adapter_profile_name}' not found in adapter_profiles"
        )

    drive = drive_profiles[drive_profile_name] or {}
    hw = hardware_profiles[hw_profile_name] or {}
    capabilities = capability_profiles.get(capability_profile_name, {}) if capability_profile_name else {}
    adapter_profile = adapter_profiles.get(adapter_profile_name, {}) or {}
    gpio_map = dict(hw.get("gpio", {}) or {})

    # Merge params with optional per-robot overrides (if present).
    drive_params = dict(drive.get("params", {}) or {})
    hw_params = dict(hw.get("params", {}) or {})
    adapter_params = dict(adapter_profile.get("params", {}) or {})
    robot_gpio = robot_entry.get("gpio") or {}
    if isinstance(robot_gpio, dict):
        gpio_map.update(robot_gpio)

    robot_params = robot_entry.get("params") or {}
    if isinstance(robot_params, dict):
        drive_params.update(robot_params.get("drive", {}) or {})
        drive_params.update(robot_params.get("control_type", {}) or {})
        hw_params.update(robot_params.get("hardware", {}) or {})
        hw_params.update(robot_params.get("control_interface", {}) or {})
        adapter_params.update(robot_params.get("adapter", {}) or {})
        adapter_params.update(robot_params.get("adapter_profile", {}) or {})
        for gpio_key in ("gpio", "hardware_gpio", "control_interface_gpio"):
            gpio_overrides = robot_params.get(gpio_key) or {}
            if isinstance(gpio_overrides, dict):
                gpio_map.update(gpio_overrides)

    _validate_params(drive_params, hw_params, drive_profile_name, hw_profile_name)

    drive_type = drive.get("type")
    if not drive_type:
        raise ValueError(f"drive_profiles.{drive_profile_name} missing required 'type' field")

    adapter_name = str(adapter_profile.get("adapter", "")).strip() or "passthrough"

    return {
        "robot_name": robot_name,
        "profile_name": drive_profile_name,
        "hardware": hw_profile_name,
        "control_type": drive_profile_name,
        "control_interface": hw_profile_name,
        "capability_profile": capability_profile_name,
        "adapter_profile": adapter_profile_name,
        "adapter_name": adapter_name,
        "drive_type": drive_type,
        "drive": drive,
        "hw": hw,
        "capabilities": capabilities if isinstance(capabilities, dict) else {},
        "adapter": adapter_profile if isinstance(adapter_profile, dict) else {},
        "gpio": gpio_map,
        "drive_params": drive_params,
        "hardware_params": hw_params,
        "adapter_params": adapter_params,
        "robot_params": robot_params if isinstance(robot_params, dict) else {},
    }


def _validate_params(drive_params: Dict[str, Any], hw_params: Dict[str, Any], drive_name: str, hw_name: str) -> None:
    """Basic range checks for common tuning parameters."""
    def _as_float(v):
        try:
            return float(v)
        except Exception:
            return None

    def _as_int(v):
        try:
            return int(v)
        except Exception:
            return None

    # Drive params
    positive_keys = ("wheel_base_m", "wheel_separation_m", "track_width_m", "watchdog_timeout_s", "fpv_lease_ttl_sec")
    nonneg_keys = ("max_linear_mps", "max_angular_rps", "teleop_linear_mps", "teleop_angular_rps", "teleop_mecanum_turn_gain")
    int_nonneg_keys = ("teleop_medium_steps", "teleop_fast_linear_steps", "teleop_fast_angular_steps")

    for k in positive_keys:
        if k in drive_params:
            v = _as_float(drive_params.get(k))
            if v is None or v <= 0:
                raise ValueError(f"drive_profiles.{drive_name}.params.{k} must be > 0 (got {drive_params.get(k)})")

    for k in nonneg_keys:
        if k in drive_params:
            v = _as_float(drive_params.get(k))
            if v is None or v < 0:
                raise ValueError(f"drive_profiles.{drive_name}.params.{k} must be >= 0 (got {drive_params.get(k)})")

    if "spin_speed_mult" in drive_params:
        v = _as_float(drive_params.get("spin_speed_mult"))
        if v is None or v < 0 or v > 1.0:
            raise ValueError(f"drive_profiles.{drive_name}.params.spin_speed_mult must be in [0, 1] (got {drive_params.get('spin_speed_mult')})")

    if "stall_timeout_s" in drive_params:
        v = _as_float(drive_params.get("stall_timeout_s"))
        if v is None or v < 0:
            raise ValueError(f"drive_profiles.{drive_name}.params.stall_timeout_s must be >= 0 (got {drive_params.get('stall_timeout_s')})")

    if "stall_duty_pct" in drive_params:
        v = _as_float(drive_params.get("stall_duty_pct"))
        if v is None or v < 0 or v > 100:
            raise ValueError(f"drive_profiles.{drive_name}.params.stall_duty_pct must be in [0, 100] (got {drive_params.get('stall_duty_pct')})")

    if "teleop_speed_step" in drive_params:
        v = _as_float(drive_params.get("teleop_speed_step"))
        if v is None or v <= 1.0:
            raise ValueError(f"drive_profiles.{drive_name}.params.teleop_speed_step must be > 1.0 (got {drive_params.get('teleop_speed_step')})")

    if "teleop_smoothing_alpha" in drive_params:
        v = _as_float(drive_params.get("teleop_smoothing_alpha"))
        if v is None or v < 0 or v > 1.0:
            raise ValueError(f"drive_profiles.{drive_name}.params.teleop_smoothing_alpha must be in [0, 1] (got {drive_params.get('teleop_smoothing_alpha')})")

    if "teleop_diff_arc_inner_ratio" in drive_params:
        v = _as_float(drive_params.get("teleop_diff_arc_inner_ratio"))
        if v is None or v < 0 or v > 1.0:
            raise ValueError(
                f"drive_profiles.{drive_name}.params.teleop_diff_arc_inner_ratio must be in [0, 1] "
                f"(got {drive_params.get('teleop_diff_arc_inner_ratio')})"
            )

    for k in int_nonneg_keys:
        if k in drive_params:
            v = _as_int(drive_params.get(k))
            if v is None or v < 0:
                raise ValueError(f"drive_profiles.{drive_name}.params.{k} must be >= 0 (got {drive_params.get(k)})")

    # Hardware params
    if "pwm_hz" in hw_params:
        v = _as_int(hw_params.get("pwm_hz"))
        if v is None or v <= 0:
            raise ValueError(f"hardware_profiles.{hw_name}.params.pwm_hz must be > 0 (got {hw_params.get('pwm_hz')})")

    if "max_pwm" in hw_params:
        v = _as_int(hw_params.get("max_pwm"))
        if v is None or v < 0 or v > 100:
            raise ValueError(f"hardware_profiles.{hw_name}.params.max_pwm must be in [0, 100] (got {hw_params.get('max_pwm')})")

    if "pwm_ramp_ms" in hw_params:
        v = _as_float(hw_params.get("pwm_ramp_ms"))
        if v is None or v < 0:
            raise ValueError(f"hardware_profiles.{hw_name}.params.pwm_ramp_ms must be >= 0 (got {hw_params.get('pwm_ramp_ms')})")

    if "pwm_deadband_pct" in hw_params:
        v = _as_float(hw_params.get("pwm_deadband_pct"))
        if v is None or v < 0 or v > 100:
            raise ValueError(f"hardware_profiles.{hw_name}.params.pwm_deadband_pct must be in [0, 100] (got {hw_params.get('pwm_deadband_pct')})")

    if "cmd_rate_hz" in hw_params:
        v = _as_float(hw_params.get("cmd_rate_hz"))
        if v is None or v < 0:
            raise ValueError(f"hardware_profiles.{hw_name}.params.cmd_rate_hz must be >= 0 (got {hw_params.get('cmd_rate_hz')})")

    if "pwm_slew_pct_per_s" in hw_params:
        v = _as_float(hw_params.get("pwm_slew_pct_per_s"))
        if v is None or v < 0:
            raise ValueError(f"hardware_profiles.{hw_name}.params.pwm_slew_pct_per_s must be >= 0 (got {hw_params.get('pwm_slew_pct_per_s')})")

    if "strict_single_cmd_vel_publisher" in hw_params:
        v = hw_params.get("strict_single_cmd_vel_publisher")
        if not isinstance(v, bool):
            raise ValueError(
                f"hardware_profiles.{hw_name}.params.strict_single_cmd_vel_publisher must be bool "
                f"(got {hw_params.get('strict_single_cmd_vel_publisher')})"
            )

    if "strict_cmd_vel_exempt_publishers" in hw_params:
        v = hw_params.get("strict_cmd_vel_exempt_publishers")
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(
                f"hardware_profiles.{hw_name}.params.strict_cmd_vel_exempt_publishers must be "
                f"list[str] (got {hw_params.get('strict_cmd_vel_exempt_publishers')})"
            )

    if "allow_rotate_bypass_safety" in hw_params:
        v = hw_params.get("allow_rotate_bypass_safety")
        if not isinstance(v, bool):
            raise ValueError(
                f"hardware_profiles.{hw_name}.params.allow_rotate_bypass_safety must be bool "
                f"(got {hw_params.get('allow_rotate_bypass_safety')})"
            )
