from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"
LAUNCH_PATH = CORE_ROOT / "swarm_launch" / "swarm_fpv_ui.launch.py"
RUN_UI_PATH = CORE_ROOT / "scripts" / "swarm_core_run_local_ui.sh"


def test_unknown_robot_control_is_blocked_by_default_in_ui():
    text = UI_PATH.read_text(encoding="utf-8")

    assert 'self.declare_parameter("allow_unknown_robot_control", False)' in text
    assert "def robot_control_allowed" in text
    assert '"control_allowed": bool(control_allowed)' in text
    assert "if not self.hub.robot_control_allowed(robot):" in text
    assert "visible but not trusted for control" in text
    assert "Read-only: this robot is visible on ROS" in text


def test_unknown_robot_control_override_is_explicit_launch_config():
    launch_text = LAUNCH_PATH.read_text(encoding="utf-8")
    run_text = RUN_UI_PATH.read_text(encoding="utf-8")

    assert "SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL" in launch_text
    assert "allow_unknown_robot_control" in launch_text
    assert 'SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL="${SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL:-0}"' in run_text
    assert 'allow_unknown_robot_control:="$SWARM_CORE_ALLOW_UNKNOWN_ROBOT_CONTROL"' in run_text
