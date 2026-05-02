#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _default_bind_host() -> str:
    return str(os.environ.get("SWARM_CORE_BIND_HOST", "127.0.0.1")).strip() or "127.0.0.1"


def _default_bind_port() -> str:
    return str(os.environ.get("SWARM_CORE_BIND_PORT", "8080")).strip() or "8080"


def _default_ros_domain_id() -> str:
    return str(os.environ.get("ROS_DOMAIN_ID", "17")).strip() or "17"


def _default_webrtc_fps() -> str:
    raw = str(os.environ.get("SWARM_CORE_WEBRTC_FPS", "15.0")).strip()
    if not raw:
        return "15.0"
    try:
        return str(float(raw))
    except ValueError:
        return "15.0"


def _default_webrtc_main_only() -> str:
    raw = str(os.environ.get("SWARM_CORE_WEBRTC_MAIN_ONLY", "1")).strip().lower()
    return "true" if raw in ("1", "true", "yes", "on") else "false"


def _default_allow_unknown_robot_control() -> str:
    raw = str(os.environ.get("SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL", "0")).strip().lower()
    return "true" if raw in ("1", "true", "yes", "on") else "false"


def _normalize_fleet_preview_preset(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "focus": "single_robot_focus",
        "single": "single_robot_focus",
        "single_robot": "single_robot_focus",
        "small_lab": "small_lab_live",
        "lab": "small_lab_live",
        "live": "small_lab_live",
        "scalable": "scalable_fleet",
        "fleet": "scalable_fleet",
        "operator": "operator_focus",
    }
    value = aliases.get(value, value)
    if value in ("single_robot_focus", "small_lab_live", "scalable_fleet", "operator_focus"):
        return value
    return "scalable_fleet"


def _default_fleet_preview_preset() -> str:
    return _normalize_fleet_preview_preset(os.environ.get("SWARM_CORE_FLEET_PREVIEW_PRESET", "scalable_fleet"))


def _preview_preset_defaults() -> dict:
    preset = _default_fleet_preview_preset()
    return {
        "single_robot_focus": {
            "thumb_refresh_hz": "0.5",
            "image_subscription_mode": "active_only",
            "image_thumb_interest_ttl_s": "0.75",
            "thumb_robots_per_tick": "0",
        },
        "scalable_fleet": {
            "thumb_refresh_hz": "1.0",
            "image_subscription_mode": "active_only",
            "image_thumb_interest_ttl_s": "2.5",
            "thumb_robots_per_tick": "1",
        },
        "operator_focus": {
            "thumb_refresh_hz": "1.5",
            "image_subscription_mode": "active_only",
            "image_thumb_interest_ttl_s": "3.0",
            "thumb_robots_per_tick": "2",
        },
        "small_lab_live": {
            "thumb_refresh_hz": "2.0",
            "image_subscription_mode": "active_only",
            "image_thumb_interest_ttl_s": "4.0",
            "thumb_robots_per_tick": "4",
        },
    }[preset]


def _default_thumb_refresh_hz() -> str:
    raw = str(
        os.environ.get("SWARM_CORE_THUMB_REFRESH_HZ", _preview_preset_defaults()["thumb_refresh_hz"])
    ).strip()
    if not raw:
        return "0.5"
    try:
        return str(float(raw))
    except ValueError:
        return "0.5"


def _default_image_subscription_mode() -> str:
    raw = str(
        os.environ.get("SWARM_CORE_IMAGE_SUBSCRIPTION_MODE", _preview_preset_defaults()["image_subscription_mode"])
    ).strip().lower()
    if raw in ("all", "all_robots", "full"):
        return "all"
    return "active_only"


def _default_image_thumb_interest_ttl_s() -> str:
    raw = str(
        os.environ.get(
            "SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S",
            _preview_preset_defaults()["image_thumb_interest_ttl_s"],
        )
    ).strip()
    if not raw:
        return "0.75"
    try:
        return str(float(raw))
    except ValueError:
        return "0.75"


def _default_thumb_robots_per_tick() -> str:
    raw = str(
        os.environ.get("SWARM_CORE_THUMB_ROBOTS_PER_TICK", _preview_preset_defaults()["thumb_robots_per_tick"])
    ).strip()
    if not raw:
        return "0"
    try:
        return str(max(0, int(raw)))
    except ValueError:
        return "0"


def _default_drive_cmd_rate_hz() -> str:
    raw = str(os.environ.get("SWARM_CORE_DRIVE_CMD_RATE_HZ", "20.0")).strip()
    if not raw:
        return "20.0"
    try:
        return str(float(raw))
    except ValueError:
        return "20.0"


def _default_drive_hold_timeout_s() -> str:
    raw = str(os.environ.get("SWARM_CORE_DRIVE_HOLD_TIMEOUT_S", "0.35")).strip()
    if not raw:
        return "0.35"
    try:
        return str(float(raw))
    except ValueError:
        return "0.35"


def _default_robot_presence_timeout_s() -> str:
    raw = str(os.environ.get("SWARM_CORE_ROBOT_PRESENCE_TIMEOUT_S", "5.0")).strip()
    if not raw:
        return "5.0"
    try:
        return str(max(2.0, float(raw)))
    except ValueError:
        return "5.0"


def _default_robot_presence_bootstrap_grace_s() -> str:
    raw = str(os.environ.get("SWARM_CORE_ROBOT_PRESENCE_BOOTSTRAP_GRACE_S", "3.0")).strip()
    if not raw:
        return "3.0"
    try:
        return str(max(1.0, float(raw)))
    except ValueError:
        return "3.0"


def _default_profiles_path() -> str:
    for key in ("PROFILES_PATH", "SWARM_CORE_PROFILES_PATH"):
        raw = str(os.environ.get(key, "")).strip()
        if raw:
            return raw
    candidate = os.path.expanduser("~/.config/swarm_control_core/robot_instances.yaml")
    return candidate if os.path.exists(candidate) else ""


def _host_default() -> str:
    return str(getattr(os.uname(), "nodename", "") or "local-gateway").strip() or "local-gateway"


def _default_gateway_id() -> str:
    return str(os.environ.get("SWARM_CORE_GATEWAY_ID", _host_default())).strip() or _host_default()


def _default_gateway_name() -> str:
    return str(os.environ.get("SWARM_CORE_GATEWAY_NAME", _default_gateway_id())).strip() or _default_gateway_id()


def _default_gateway_role() -> str:
    return str(os.environ.get("SWARM_CORE_GATEWAY_ROLE", "local_gateway")).strip() or "local_gateway"


def _default_gateway_route_type() -> str:
    return str(os.environ.get("SWARM_CORE_GATEWAY_ROUTE_TYPE", "local_gateway")).strip() or "local_gateway"


def _default_hub_url() -> str:
    return str(os.environ.get("SWARM_CORE_HUB_URL", "")).strip()


def _default_gateway_site_id() -> str:
    return str(os.environ.get("SWARM_CORE_SITE_ID", "")).strip()


def generate_launch_description() -> LaunchDescription:
    args = [
        DeclareLaunchArgument(
            "ros_domain_id",
            default_value=_default_ros_domain_id(),
            description="ROS 2 domain ID for community stack (default: 17).",
        ),
        DeclareLaunchArgument("bind_host", default_value=_default_bind_host()),
        DeclareLaunchArgument("bind_port", default_value=_default_bind_port()),
        DeclareLaunchArgument("webrtc_fps", default_value=_default_webrtc_fps()),
        DeclareLaunchArgument("webrtc_main_only", default_value=_default_webrtc_main_only()),
        DeclareLaunchArgument("allow_unknown_robot_control", default_value=_default_allow_unknown_robot_control()),
        DeclareLaunchArgument("thumb_refresh_hz", default_value=_default_thumb_refresh_hz()),
        DeclareLaunchArgument("image_subscription_mode", default_value=_default_image_subscription_mode()),
        DeclareLaunchArgument("image_thumb_interest_ttl_s", default_value=_default_image_thumb_interest_ttl_s()),
        DeclareLaunchArgument("thumb_robots_per_tick", default_value=_default_thumb_robots_per_tick()),
        DeclareLaunchArgument("fleet_preview_preset", default_value=_default_fleet_preview_preset()),
        DeclareLaunchArgument("drive_cmd_rate_hz", default_value=_default_drive_cmd_rate_hz()),
        DeclareLaunchArgument("drive_hold_timeout_s", default_value=_default_drive_hold_timeout_s()),
        DeclareLaunchArgument("robot_presence_timeout_s", default_value=_default_robot_presence_timeout_s()),
        DeclareLaunchArgument(
            "robot_presence_bootstrap_grace_s",
            default_value=_default_robot_presence_bootstrap_grace_s(),
        ),
        DeclareLaunchArgument(
            "profiles_path",
            default_value=_default_profiles_path(),
            description="Path to robot_instances.yaml (or legacy robot_profiles.yaml). Set explicitly or via PROFILES_PATH.",
        ),
        DeclareLaunchArgument("gateway_id", default_value=_default_gateway_id()),
        DeclareLaunchArgument("gateway_name", default_value=_default_gateway_name()),
        DeclareLaunchArgument("gateway_role", default_value=_default_gateway_role()),
        DeclareLaunchArgument("gateway_route_type", default_value=_default_gateway_route_type()),
        DeclareLaunchArgument("hub_url", default_value=_default_hub_url()),
        DeclareLaunchArgument("gateway_site_id", default_value=_default_gateway_site_id()),
    ]

    node = Node(
        package="swarm_control_core",
        executable="swarm_fpv_ui_core",
        name="swarm_fpv_ui",
        output="screen",
        parameters=[
            {"bind_host": LaunchConfiguration("bind_host")},
            {"bind_port": LaunchConfiguration("bind_port")},
            {"webrtc_fps": ParameterValue(LaunchConfiguration("webrtc_fps"), value_type=float)},
            {"webrtc_main_only": ParameterValue(LaunchConfiguration("webrtc_main_only"), value_type=bool)},
            {
                "allow_unknown_robot_control": ParameterValue(
                    LaunchConfiguration("allow_unknown_robot_control"),
                    value_type=bool,
                )
            },
            {"thumb_refresh_hz": ParameterValue(LaunchConfiguration("thumb_refresh_hz"), value_type=float)},
            {"image_subscription_mode": LaunchConfiguration("image_subscription_mode")},
            {
                "image_thumb_interest_ttl_s": ParameterValue(
                    LaunchConfiguration("image_thumb_interest_ttl_s"),
                    value_type=float,
                )
            },
            {
                "thumb_robots_per_tick": ParameterValue(
                    LaunchConfiguration("thumb_robots_per_tick"),
                    value_type=int,
                )
            },
            {"fleet_preview_preset": LaunchConfiguration("fleet_preview_preset")},
            {"drive_cmd_rate_hz": ParameterValue(LaunchConfiguration("drive_cmd_rate_hz"), value_type=float)},
            {"drive_hold_timeout_s": ParameterValue(LaunchConfiguration("drive_hold_timeout_s"), value_type=float)},
            {
                "robot_presence_timeout_s": ParameterValue(
                    LaunchConfiguration("robot_presence_timeout_s"),
                    value_type=float,
                )
            },
            {
                "robot_presence_bootstrap_grace_s": ParameterValue(
                    LaunchConfiguration("robot_presence_bootstrap_grace_s"),
                    value_type=float,
                )
            },
            {"profiles_path": LaunchConfiguration("profiles_path")},
            {"gateway_id": LaunchConfiguration("gateway_id")},
            {"gateway_name": LaunchConfiguration("gateway_name")},
            {"gateway_role": LaunchConfiguration("gateway_role")},
            {"gateway_route_type": LaunchConfiguration("gateway_route_type")},
            {"hub_url": LaunchConfiguration("hub_url")},
            {"gateway_site_id": LaunchConfiguration("gateway_site_id")},
        ],
    )

    return LaunchDescription(
        args
        + [
            SetEnvironmentVariable(name="ROS_DOMAIN_ID", value=LaunchConfiguration("ros_domain_id")),
            node,
        ]
    )
