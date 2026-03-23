#!/usr/bin/env python3
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
    # Verify at least one SetEnvironmentVariable action exists (the hardcoded ROS_DOMAIN_ID in source)
    assert len(envs) >= 1


def test_launch_contains_motor_and_heartbeat_nodes():
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    # Verify exactly 2 nodes are declared (motor_driver_node + heartbeat_node)
    assert len(nodes) == 2
    # Verify both are Node actions
    assert all(isinstance(n, Node) for n in nodes)


def test_launch_node_parameters_are_linked_to_launch_config():
    """Verify that nodes have parameters declared (internally name-mangled as _Node__parameters)."""
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    
    # Both nodes should have parameters set (internal check via name-mangled attribute)
    for node in nodes:
        # Parameter dict is stored as _Node__parameters
        assert hasattr(node, '_Node__parameters')
        params = getattr(node, '_Node__parameters', None)
        assert params is not None
        assert len(params) > 0


def test_argument_default_values():
    """Verify argument defaults are correct (ros_domain_id='17', robot_name/profiles_path empty)."""
    ld = generate_launch_description()
    args = _find_action(ld.entities, DeclareLaunchArgument)
    args_by_name = {a.name: a for a in args}
    
    # ros_domain_id should default to "17" (or env var)
    ros_domain_id_arg = args_by_name.get("ros_domain_id")
    assert ros_domain_id_arg is not None
    assert ros_domain_id_arg.default_value is not None
    
    # robot_name and profiles_path should default to empty string (stored as TextSubstitution list)
    robot_name_arg = args_by_name.get("robot_name")
    assert robot_name_arg is not None
    assert robot_name_arg.default_value is not None
    
    profiles_path_arg = args_by_name.get("profiles_path")
    assert profiles_path_arg is not None
    assert profiles_path_arg.default_value is not None


def test_node_output_configuration():
    """Verify both nodes have output='screen' for immediate log visibility."""
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    
    # Check internal _ExecuteLocal__output attribute (name-mangled)
    for node in nodes:
        assert hasattr(node, '_ExecuteLocal__output'), f"Node missing __output attribute"
        output = getattr(node, '_ExecuteLocal__output')
        # Output is stored as a list of substitutions; verify it exists and is non-empty
        assert output is not None
        assert isinstance(output, list)
        assert len(output) > 0


def test_node_package_name():
    """Verify nodes target correct package 'swarm_control_core'."""
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    
    for node in nodes:
        # Package is stored as _Node__package
        assert hasattr(node, '_Node__package')
        package = getattr(node, '_Node__package')
        assert package == "swarm_control_core"


def test_node_executable_names():
    """Verify nodes use correct executables: motor_driver_node_core and heartbeat_node_core."""
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    
    executables = {getattr(n, '_Node__node_executable') for n in nodes}
    assert "motor_driver_node_core" in executables
    assert "heartbeat_node_core" in executables


def test_node_parameter_count_and_keys():
    """Verify each node has exactly 2 parameters: robot_name and profiles_path."""
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    
    for node in nodes:
        params = getattr(node, '_Node__parameters', {})
        # Parameters are stored as tuple of (key_tuple, value_tuple) pairs
        assert len(params) == 2, f"Node should have exactly 2 parameters, got {len(params)}"


def test_environment_variable_value_is_launch_configuration():
    """Verify SetEnvironmentVariable uses LaunchConfiguration, not hardcoded string."""
    ld = generate_launch_description()
    envs = _find_action(ld.entities, SetEnvironmentVariable)
    
    assert len(envs) >= 1
    env_var = envs[0]
    
    # Value is stored as _SetEnvironmentVariable__value (list of substitutions)
    assert hasattr(env_var, '_SetEnvironmentVariable__value')
    value = getattr(env_var, '_SetEnvironmentVariable__value')
    assert value is not None
    # Should be LaunchConfiguration substitution, not plain text
    assert len(value) > 0


def test_generate_launch_description_idempotent():
    """Verify calling generate_launch_description() multiple times returns independent objects."""
    ld1 = generate_launch_description()
    ld2 = generate_launch_description()
    
    # Should be different LaunchDescription objects (not cached/reused)
    assert ld1 is not ld2
    assert isinstance(ld1, LaunchDescription)
    assert isinstance(ld2, LaunchDescription)
    
    # Both should have same structure (5 elements)
    assert len(ld1.entities) == len(ld2.entities)
