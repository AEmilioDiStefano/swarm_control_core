import json
import os
import subprocess
from pathlib import Path

from PIL import Image


CORE_ROOT = Path(__file__).resolve().parents[1]
STEP4 = CORE_ROOT / "scripts" / "swarm_core_quickstart_step4.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_step4(
    tmp_path: Path,
    *,
    state: dict,
    args: tuple[str, ...] = (),
    registered: tuple[str, ...] = ("robot1", "robot2"),
) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "ros2_ws_dev"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "swarm_control_core").symlink_to(CORE_ROOT)
    (workspace / "install").mkdir()

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (workspace / "install" / "setup.bash").write_text(
        'export PATH="${FAKE_BIN}:$PATH"\n', encoding="utf-8"
    )

    _write_executable(
        fake_bin / "ros2",
        """#!/usr/bin/env bash
case "$*" in
  "topic list")
    printf '%s\n' /robot1/heartbeat /robot1/camera/image_raw/compressed /robot1/cmd_vel
    ;;
  "node list")
    printf '%s\n' /swarm_fpv_ui /robot1/heartbeat_node /robot1/motor_driver_node /robot1/camera
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
output=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      output="$2"
      shift 2
      ;;
    http://*|https://*)
      url="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done
printf '%s\n' "$url" >> "$FAKE_CURL_LOG"
case "$url" in
  */api/jpeg)
    cp "$FAKE_JPEG_PATH" "$output"
    printf '200\timage/jpeg'
    ;;
  */api/state)
    cp "$FAKE_STATE_PATH" "$output"
    printf '200'
    ;;
  *)
    printf '404\ttext/plain'
    ;;
esac
""",
    )

    camera = tmp_path / "frame.jpg"
    Image.new("RGB", (2, 2), color=(20, 80, 140)).save(camera, format="JPEG")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    curl_log = tmp_path / "curl.log"

    config_dir = tmp_path / "runtime"
    config_dir.mkdir()
    robot_lines = "\n".join(f"  {name}: {{}}" for name in registered)
    (config_dir / "robot_instances.yaml").write_text(
        f"robots:\n{robot_lines}\n", encoding="utf-8"
    )

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "FAKE_BIN": str(fake_bin),
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_JPEG_PATH": str(camera),
        "FAKE_STATE_PATH": str(state_path),
        "SWARM_CORE_CONFIG_DIR": str(config_dir),
        "SWARM_CORE_WORKSPACE_ROOT": str(workspace),
        "SWARM_CORE_FPV_ACCEPTANCE_TIMEOUT_S": "0",
        "SWARM_CORE_FPV_ACCEPTANCE_POLL_INTERVAL_S": "0",
    }
    return subprocess.run(
        [str(STEP4), *args],
        cwd=CORE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )


def _state(
    *,
    age: float = 0.1,
    has_frame: bool = True,
    webrtc: bool = True,
    offers_success: int = 1,
    last_offer_robot: str = "robot1",
    active_peer_connections: int = 1,
    event_robot: str = "robot1",
    connection_state: str = "connected",
    ice_connection_state: str = "connected",
) -> dict:
    return {
        "robots": ["robot1", "robot2"],
        "live_robots": ["robot1"],
        "features": {"webrtc": webrtc},
        "robot_health": {
            "robot1": {
                "has_frame": has_frame,
                "frame_age_s": age,
                "probable_cause": "camera stream healthy",
            }
        },
        "webrtc": {
            "telemetry": {
                "offers_success": offers_success,
                "last_offer_robot": last_offer_robot,
                "active_peer_connections": active_peer_connections,
                "last_client_event": {
                    "robot": event_robot,
                    "event": "connection_state",
                    "connection_state": connection_state,
                    "ice_connection_state": ice_connection_state,
                },
            }
        },
    }


def test_selected_robot_accepts_real_jpeg_and_ignores_offline_fleet_member(tmp_path):
    result = _run_step4(
        tmp_path,
        state=_state(),
        args=("--robot-name", "robot1", "--ui-url", "http://localhost:9090"),
    )

    assert result.returncode == 0, result.stderr
    assert "FPV ACCEPTANCE PASSED" in result.stdout
    assert "robot=robot1" in result.stdout
    assert "jpeg=valid" in result.stdout
    assert "webrtc_offer=ok" in result.stdout
    assert "browser_connection=connected" in result.stdout
    assert "WebRTC" not in result.stderr
    assert "robot2" not in result.stderr
    assert (tmp_path / "curl.log").read_text(encoding="utf-8").splitlines() == [
        "http://localhost:9090/api/jpeg",
        "http://localhost:9090/api/state",
    ]


def test_without_selection_one_healthy_robot_is_enough_for_partial_fleet(tmp_path):
    result = _run_step4(tmp_path, state=_state())

    assert result.returncode == 0, result.stderr
    assert "FPV ACCEPTANCE PASSED" in result.stdout
    assert "robot=robot1" in result.stdout
    assert "robot2" in result.stderr
    assert "missing required node" in result.stderr


def test_fpv_acceptance_rejects_a_stale_cached_frame(tmp_path):
    result = _run_step4(
        tmp_path,
        state=_state(age=9.0),
        args=("--robot-name", "robot1"),
    )

    assert result.returncode != 0
    assert "newest UI frame is stale" in result.stderr
    assert "No approved graph-live robot produced both a fresh JPEG" in result.stderr


def test_fpv_acceptance_requires_ui_webrtc_support(tmp_path):
    result = _run_step4(
        tmp_path,
        state=_state(webrtc=False),
        args=("--robot-name", "robot1"),
    )

    assert result.returncode != 0
    assert "WebRTC disabled" in result.stderr
    assert "python3-aiortc and python3-av" in result.stderr


def test_fpv_acceptance_rejects_server_support_without_a_browser_offer(tmp_path):
    result = _run_step4(
        tmp_path,
        state=_state(offers_success=0, last_offer_robot=""),
        args=("--robot-name", "robot1"),
    )

    assert result.returncode != 0
    assert "no successful browser WebRTC offer" in result.stderr
    assert "connected browser WebRTC session" in result.stderr


def test_fpv_acceptance_rejects_a_browser_peer_that_is_not_connected(tmp_path):
    result = _run_step4(
        tmp_path,
        state=_state(connection_state="connecting", ice_connection_state="checking"),
        args=("--robot-name", "robot1"),
    )

    assert result.returncode != 0
    assert "browser WebRTC is not connected" in result.stderr
    assert "connection_state=connecting" in result.stderr
