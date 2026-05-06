#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0
"""
robot_minimal_launch.py

Minimal “make it drivable” launch:
  - motor_driver_node
  - heartbeat_node

Use this when:
  - You do NOT need playbooks/action execution on the robot yet.
  - You want the smallest possible set of nodes for reliability.

This still supports heterogeneous fleets, because:
  - motor_driver_node picks control type from profiles YAML
  - heartbeat_node advertises the chosen drive_type so teleop can adapt
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _default_ros_domain_id() -> str:
    return str(os.environ.get("ROS_DOMAIN_ID", "17")).strip() or "17"


def generate_launch_description() -> LaunchDescription:
    ros_domain_id_arg = DeclareLaunchArgument(
        "ros_domain_id",
        default_value=_default_ros_domain_id(),
        description="ROS 2 domain ID for community stack (default: 17).",
    )

    robot_name_arg = DeclareLaunchArgument(
        "robot_name",
        default_value="",
        description="Robot identity name. Set explicitly or via SWARM_CORE_ROBOT_NAME/ROBOT_NAME.",
    )

    profiles_path_arg = DeclareLaunchArgument(
        "profiles_path",
        default_value="",
        description="Path to robot_instances.yaml. Set explicitly or via PROFILES_PATH.",
    )

    common_params = [
        {"robot_name": LaunchConfiguration("robot_name")},
        {"profiles_path": LaunchConfiguration("profiles_path")},
    ]

    motor_driver = Node(
        package="swarm_control_core",
        executable="motor_driver_node_core",
        name="motor_driver_node",
        output="screen",
        parameters=common_params,
    )

    heartbeat = Node(
        package="swarm_control_core",
        executable="heartbeat_node_core",
        name="heartbeat_node",
        output="screen",
        parameters=common_params,
    )

    return LaunchDescription(
        [
            ros_domain_id_arg,
            robot_name_arg,
            profiles_path_arg,
            SetEnvironmentVariable(name="ROS_DOMAIN_ID", value=LaunchConfiguration("ros_domain_id")),
            motor_driver,
            heartbeat,
        ]
    )
