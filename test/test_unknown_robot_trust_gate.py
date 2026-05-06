from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"
LAUNCH_PATH = CORE_ROOT / "swarm_launch" / "swarm_fpv_ui.launch.py"
RUN_UI_PATH = CORE_ROOT / "scripts" / "swarm_core_run_local_ui.sh"


def test_unknown_robot_control_is_blocked_by_default_in_ui():
    text = UI_PATH.read_text(encoding="utf-8")

    assert "def robot_control_allowed" in text
    assert '"control_allowed": bool(control_allowed)' in text
    assert "if not self.hub.robot_control_allowed(robot):" in text
    assert "visible but not trusted for control" in text
    assert "Read-only: this robot is visible on ROS" in text
    assert "unknown_control_allowed" not in text
    assert "SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL" not in text


def test_unknown_robot_control_override_is_not_exposed_by_launch_config():
    launch_text = LAUNCH_PATH.read_text(encoding="utf-8")
    run_text = RUN_UI_PATH.read_text(encoding="utf-8")

    assert "SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL" not in launch_text
    assert "allow_unknown_robot_control" not in launch_text
    assert "PROFILES_PATH" in launch_text
    assert "SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL" not in run_text
    assert "allow_unknown_robot_control" not in run_text
    assert "--overwrite-core-profiles" in run_text
    assert 'launch_args+=("profiles_path:=${PROFILES_PATH}")' in run_text
    assert "CONTROL_INTERFACES_PATH" in run_text
