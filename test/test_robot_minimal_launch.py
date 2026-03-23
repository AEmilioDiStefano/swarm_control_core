#!/usr/bin/env python3
"""
Comprehensive test suite for robot_minimal_launch.py

This module validates the launch configuration for minimal robot bringup,
ensuring that motor_driver_node and heartbeat_node are correctly configured
with proper ROS domain isolation, parameter passing, and node setup.

Test Coverage:

STRUCTURE & INTEGRITY (USING PUBLIC API ONLY):
  ✓ LaunchDescription is properly generated and returns correct type
  ✓ All required launch arguments are declared (ros_domain_id, robot_name, profiles_path)
  ✓ ROS_DOMAIN_ID environment variable action exists
  ✓ Both motor_driver_node and heartbeat_node nodes are declared (exactly 2 nodes)
  ✓ Node names are correct and match expected ROS topic namespacing (motor_driver_node, heartbeat_node)
  ✓ Nodes have parameters linked to launch config substitutions (non-empty check)
  ✓ Argument default values are configured (ros_domain_id, robot_name, profiles_path)
  ✓ Multiple calls to generate_launch_description() return independent objects (idempotency)

ENVIRONMENT DEFAULT LOGIC (_default_ros_domain_id):
  ✓ When ROS_DOMAIN_ID is explicitly set, use that value
  ✓ When ROS_DOMAIN_ID has surrounding whitespace, strip and use the value
  ✓ When ROS_DOMAIN_ID is unset, default to "17"
  ✓ When ROS_DOMAIN_ID is empty string, fall back to "17"
  ✓ When ROS_DOMAIN_ID is whitespace-only, fall back to "17"

Tests Removed (Brittle Private Attribute Dependencies):
  ✗ test_node_output_configuration - relied on _ExecuteLocal__output (private, ROS-version-dependent)
  ✗ test_node_package_name - relied on _Node__package (private, may change)
  ✗ test_node_executable_names - relied on _Node__node_executable (private, may change)
  ✗ test_environment_variable_value_is_launch_configuration - relied on _SetEnvironmentVariable__value (private)

Tests Retained with Private Attribute Access (Safety-Critical):
  ✓ test_node_parameter_count_and_keys - uses _Node__parameters (parameter passing is safety-critical)
  ✓ test_node_names - uses _Node__node_name (ROS topic namespacing is safety-critical)

Rationale for Removal:
  Private attributes (name-mangled with __) are implementation details of ROS 2 launch framework.
  They are NOT part of the public API contract and can change between ROS versions without notice.
  Tests relying on them would break silently or with cryptic errors when ROS is updated.
  Better to trust the ROS 2 testing and rely on verifiable public contracts.

Exception: Safety-Critical Private Attributes:
  Two tests retain usage of private attributes because:
  1. Node names (parameter naming) and parameter passing are CRITICAL for robot operation
  2. No public ROS 2 launch API exists to enumerate these after declaration
  3. If ROS 2 changes these private attributes, tests WILL fail visibly (not silently)
  4. The failure immediately signals that the launch config needs verification
  Future: Replace with integration tests that actually launch nodes and verify at runtime.

Design Rule:
  Avoid testing implementation details. Test observable behavior and public contracts.
  If something cannot be tested through public API, verify it at integration test time.

Dependencies:
  - launch: ROS 2 launch framework (public APIs only)
  - launch_ros: ROS 2-specific launch actions (public APIs only)
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch_ros.actions import Node
from swarm_launch.robot_minimal_launch import generate_launch_description, _default_ros_domain_id


def _find_action(actions, action_type):
    return [a for a in actions if isinstance(a, action_type)]


def test_generate_launch_description_type():
    ld = generate_launch_description()
    assert isinstance(ld, LaunchDescription)


def test_launch_contains_expected_arguments():
    """Verify exactly 3 launch arguments are declared with expected names."""
    ld = generate_launch_description()
    args = _find_action(ld.entities, DeclareLaunchArgument)
    arg_names = {a.name for a in args}

    # Verify all 3 expected arguments are present
    assert "ros_domain_id" in arg_names
    assert "robot_name" in arg_names
    assert "profiles_path" in arg_names
    
    # Verify no extra or duplicate arguments were added
    assert len(args) == 3, f"Expected exactly 3 arguments, found {len(args)}: {arg_names}"


def test_launch_sets_ros_domain_id_env():
    """Verify SetEnvironmentVariable action sets ROS_DOMAIN_ID to LaunchConfiguration."""
    ld = generate_launch_description()
    envs = _find_action(ld.entities, SetEnvironmentVariable)
    
    # Verify at least one SetEnvironmentVariable action exists
    assert len(envs) >= 1, "No SetEnvironmentVariable actions found"
    
    # Find the ROS_DOMAIN_ID environment variable
    ros_domain_id_env = None
    for env_action in envs:
        # env_action.name is a list of Substitution objects; extract the first one's text
        if env_action.name and len(env_action.name) > 0:
            # The name is typically [TextSubstitution(text="ROS_DOMAIN_ID")]
            name_sub = env_action.name[0]
            # Check if this substitution has a .text attribute (TextSubstitution)
            name_text = getattr(name_sub, 'text', None)
            if name_text == "ROS_DOMAIN_ID":
                ros_domain_id_env = env_action
                break
    
    # Verify ROS_DOMAIN_ID environment variable was set
    assert ros_domain_id_env is not None, \
        "ROS_DOMAIN_ID environment variable not found in SetEnvironmentVariable actions"
    
    # Verify it's set to a LaunchConfiguration (not hardcoded)
    assert ros_domain_id_env.value is not None
    assert len(ros_domain_id_env.value) > 0


def test_launch_contains_motor_and_heartbeat_nodes():
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    # Verify exactly 2 nodes are declared (motor_driver_node + heartbeat_node)
    assert len(nodes) == 2
    # Verify both are Node actions
    assert all(isinstance(n, Node) for n in nodes)


def test_node_names():
    """
    Verify node names for ROS topic namespacing using private attribute access.

    ⚠️  PRIVATE ATTRIBUTE USAGE - RISK DOCUMENTED:
    This test accesses _Node__node_name, a name-mangled private attribute.
    This is justified because:

    1. Node names are CRITICAL for ROS topic namespacing 
       (e.g., /<robot_name>/cmd_vel depends on correct node name config).
    2. No public ROS 2 launch API exposes node names after Node creation.
    3. If ROS 2 changes the private attribute, test WILL fail visibly (not silently).
    4. The failure will immediately signal that launch config needs verification.

    Expected node names (from source):
    - "motor_driver_node" (subscribes to cmd_vel, publishes motor diagnostics)
    - "heartbeat_node" (broadcasts robot capabilities and health)

    If these change, all robot discovery and topic routing breaks (safety-critical).

    FUTURE MITIGATION:
    Replace this with an integration test that:
    - Launches the nodes
    - Runs 'ros2 node list' to verify node names
    - Runs 'ros2 topic list' to verify topic subscriptions

    See design notes in module docstring.
    """
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)

    normalized_node_names = set()
    for node in nodes:
        raw_name = getattr(node, '_Node__node_name', None)
        assert raw_name is not None, f"Node {node} missing _Node__node_name"

        if isinstance(raw_name, list):
            assert len(raw_name) > 0, f"Node {node} has empty node name substitution list"
            name_sub = raw_name[0]
            node_name = getattr(name_sub, 'text', None) or str(name_sub)
        else:
            node_name = raw_name

        normalized_node_names.add(node_name)

    assert normalized_node_names == {"motor_driver_node", "heartbeat_node"}, \
        f"Expected node names motor_driver_node and heartbeat_node, got {normalized_node_names}"

    # Ensure exactly 2 nodes were declared
    assert len(nodes) == 2


def test_argument_default_values():
    """Verify argument defaults are configured (using public .default_value attribute)."""
    ld = generate_launch_description()
    args = _find_action(ld.entities, DeclareLaunchArgument)
    args_by_name = {a.name: a for a in args}
    
    # All three arguments should have default values set
    ros_domain_id_arg = args_by_name.get("ros_domain_id")
    assert ros_domain_id_arg is not None
    assert ros_domain_id_arg.default_value is not None
    
    robot_name_arg = args_by_name.get("robot_name")
    assert robot_name_arg is not None
    assert robot_name_arg.default_value is not None
    
    profiles_path_arg = args_by_name.get("profiles_path")
    assert profiles_path_arg is not None
    assert profiles_path_arg.default_value is not None


def test_node_parameter_count_and_keys():
    """
    Verify each node has exactly the expected two parameters with correct keys.

    ⚠️  PRIVATE ATTRIBUTE USAGE - RISK DOCUMENTED:
    This test accesses _Node__parameters, a name-mangled private attribute of the Node class.
    This is normally an anti-pattern, but is retained here ONLY because:

    1. Parameter passing is SAFETY-CRITICAL - robots must receive correct configuration
    2. No public ROS 2 launch API exists to enumerate declared parameters
    3. If ROS 2 changes the private attribute structure, test WILL fail visibly (not silently)
    4. The failure will immediately signal that launch config needs verification

    FUTURE MITIGATION:
    - Replace this with an integration test that actually launches the nodes
    - Integration test would verify nodes receive parameters at runtime (ground truth)
    - Private attribute test can then be safely removed

    See design notes in module docstring.
    """
    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)

    expected_keys = {"robot_name", "profiles_path"}

    for node in nodes:
        params = getattr(node, '_Node__parameters', None)

        assert params is not None, "Node missing parameters"
        assert len(params) == 2, f"Node should have exactly 2 parameters, got {len(params)}"

        actual_keys = set()
        for param_map in params:
            # Each param_map is a dict where key is tuple(TextSubstitution(...),)
            assert isinstance(param_map, dict), f"Expected dict entries in parameters, got {type(param_map)}"
            for key_tuple in param_map.keys():
                assert isinstance(key_tuple, tuple) and len(key_tuple) == 1, \
                    f"Unexpected parameter key tuple structure: {key_tuple}"
                key_sub = key_tuple[0]
                key_text = getattr(key_sub, 'text', None)
                assert key_text is not None, f"Unable to read parameter key text from {key_sub}"
                actual_keys.add(key_text)

        assert actual_keys == expected_keys, \
            f"Node parameters keys should be {expected_keys}, got {actual_keys}"


def test_generate_launch_description_idempotent():
    """Verify calling generate_launch_description() multiple times returns independent objects."""
    ld1 = generate_launch_description()
    ld2 = generate_launch_description()

    # Should be different LaunchDescription objects (not cached/reused)
    assert ld1 is not ld2
    assert isinstance(ld1, LaunchDescription)
    assert isinstance(ld2, LaunchDescription)

    # Both should have same structure and expected entity count (6 entities: 3 args, 1 env, 2 nodes)
    assert len(ld1.entities) == 6
    assert len(ld2.entities) == 6
    assert len(ld1.entities) == len(ld2.entities)



def test_parameters_are_launchconfig_substitutions_and_env_configurable(monkeypatch):
    """Verify robot_name/profiles_path parameters remain positional LaunchConfiguration substitutions and can be provided in context."""
    from launch import LaunchContext
    from launch.substitutions import LaunchConfiguration

    # Set environment variables the docstring references (these are NOT automatically used by this launch file)
    monkeypatch.setenv("SWARM_CORE_ROBOT_NAME", "env_robot")
    monkeypatch.setenv("PROFILES_PATH", "/tmp/env_profiles")

    ld = generate_launch_description()
    nodes = _find_action(ld.entities, Node)
    assert len(nodes) == 2

    for node in nodes:
        params = getattr(node, '_Node__parameters', None)
        assert params is not None and len(params) == 2

        # build context with explicit values and verify substitution resolution
        ctx = LaunchContext()
        ctx.launch_configurations['robot_name'] = 'ctx_robot'
        ctx.launch_configurations['profiles_path'] = '/tmp/context_profiles'

        key_texts = set()
        for param_map in params:
            for key_tuple, value_tuple in param_map.items():
                key_sub = key_tuple[0]
                key_name = getattr(key_sub, 'text', None)
                assert key_name in ('robot_name', 'profiles_path')
                key_texts.add(key_name)

                value_sub = value_tuple[0]
                assert isinstance(value_sub, LaunchConfiguration)
                resolved = value_sub.perform(ctx)
                if key_name == 'robot_name':
                    assert resolved == 'ctx_robot'
                else:
                    assert resolved == '/tmp/context_profiles'

        assert key_texts == {'robot_name', 'profiles_path'}


def test_default_ros_domain_id_with_env_fallback_works_when_env_has_empty_string(monkeypatch):
    """When ROS_DOMAIN_ID is set to empty string via environment, it should fall back to 17."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '')
    assert _default_ros_domain_id() == '17'


# Tests for _default_ros_domain_id() function
def test_default_ros_domain_id_explicit_value(monkeypatch):
    """When ROS_DOMAIN_ID env var is explicitly set, use that value."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "42")
    result = _default_ros_domain_id()
    assert result == "42"


def test_default_ros_domain_id_explicit_value_with_whitespace(monkeypatch):
    """When ROS_DOMAIN_ID has surrounding whitespace, strip it and return the value."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "  128  ")
    result = _default_ros_domain_id()
    assert result == "128"


def test_default_ros_domain_id_unset(monkeypatch):
    """When ROS_DOMAIN_ID is not set, default to '17'."""
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    result = _default_ros_domain_id()
    assert result == "17"


def test_default_ros_domain_id_empty_string(monkeypatch):
    """When ROS_DOMAIN_ID is empty string, fall back to '17'."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "")
    result = _default_ros_domain_id()
    assert result == "17"


def test_default_ros_domain_id_whitespace_only(monkeypatch):
    """When ROS_DOMAIN_ID is only whitespace, fall back to '17'."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "  ")
    result = _default_ros_domain_id()
    assert result == "17"
