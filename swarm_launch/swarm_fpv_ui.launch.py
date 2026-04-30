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


def _default_thumb_refresh_hz() -> str:
    raw = str(os.environ.get("SWARM_CORE_THUMB_REFRESH_HZ", "0.5")).strip()
    if not raw:
        return "0.5"
    try:
        return str(float(raw))
    except ValueError:
        return "0.5"


def _default_image_subscription_mode() -> str:
    raw = str(os.environ.get("SWARM_CORE_IMAGE_SUBSCRIPTION_MODE", "active_only")).strip().lower()
    if raw in ("all", "all_robots", "full"):
        return "all"
    return "active_only"


def _default_image_thumb_interest_ttl_s() -> str:
    raw = str(os.environ.get("SWARM_CORE_IMAGE_THUMB_INTEREST_TTL_S", "0.75")).strip()
    if not raw:
        return "0.75"
    try:
        return str(float(raw))
    except ValueError:
        return "0.75"


def _default_thumb_robots_per_tick() -> str:
    raw = str(os.environ.get("SWARM_CORE_THUMB_ROBOTS_PER_TICK", "0")).strip()
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
        DeclareLaunchArgument("drive_cmd_rate_hz", default_value=_default_drive_cmd_rate_hz()),
        DeclareLaunchArgument("drive_hold_timeout_s", default_value=_default_drive_hold_timeout_s()),
        DeclareLaunchArgument(
            "profiles_path",
            default_value="",
            description="Path to robot_instances.yaml (or legacy robot_profiles.yaml). Set explicitly or via PROFILES_PATH.",
        ),
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
            {"drive_cmd_rate_hz": ParameterValue(LaunchConfiguration("drive_cmd_rate_hz"), value_type=float)},
            {"drive_hold_timeout_s": ParameterValue(LaunchConfiguration("drive_hold_timeout_s"), value_type=float)},
            {"profiles_path": LaunchConfiguration("profiles_path")},
        ],
    )

    return LaunchDescription(
        args
        + [
            SetEnvironmentVariable(name="ROS_DOMAIN_ID", value=LaunchConfiguration("ros_domain_id")),
            node,
        ]
    )
