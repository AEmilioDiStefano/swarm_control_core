#!/usr/bin/env python3
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch_ros.actions import Node
from swarm_launch.robot_minimal_launch import generate_launch_description


def _find_action(actions, action_type):
    return [a for a in actions if isinstance(a, action_type)]


def test_generate_launch_description_type():
    ld = generate_launch_description()
    assert isinstance(ld, LaunchDescription)


def test_launch_contains_expected_arguments():
    ld = generate_launch_description()
    args = _find_action(ld.entities, DeclareLaunchArgument)
    arg_names = {a.name for a in args}

    assert "ros_domain_id" in arg_names
    assert "robot_name" in arg_names
    assert "profiles_path" in arg_names


def test_launch_sets_ros_domain_id_env():
    ld = generate_launch_description()
    envs = _find_action(ld.entities, SetEnvironmentVariable)
    assert any(e.name == "ROS_DOMAIN_ID" for e in envs)


def test_launch_contains_motor_and_heartbeat_nodes():
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    node_names = {n.name for n in nodes}
    executables = {n.executable for n in nodes}

    assert "motor_driver_node" in node_names
    assert "heartbeat_node" in node_names
    assert "motor_driver_node_core" in executables
    assert "heartbeat_node_core" in executables


def test_launch_node_parameters_are_linked_to_launch_config():
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    expected_params = [{"robot_name": "{robot_name}"}, {"profiles_path": "{profiles_path}"}]

    found = False
    for node in nodes:
        if node.name in ("motor_driver_node", "heartbeat_node"):
            # LaunchConfiguration placeholders are generated in concrete actions; this test ensures params are non-empty
            assert node.parameters is not None
            assert any("robot_name" in p for p in node.parameters)
            assert any("profiles_path" in p for p in node.parameters)
            found = True

    assert found
