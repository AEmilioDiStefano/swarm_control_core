import os
import subprocess
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = CORE_ROOT / "scripts" / "lib" / "swarm_core_discovery.sh"


def _source_discovery(tmp_path, mode="hybrid", peers=""):
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "SWARM_CORE_DISCOVERY_MODE": mode,
        "SWARM_CORE_STATIC_PEERS": peers,
        "ROS_LOCALHOST_ONLY": "1",
        "ROS_DISCOVERY_SERVER": "stale",
    }
    command = (
        f'source "{DISCOVERY}"; '
        "swarm_core_apply_discovery_env || exit $?; "
        "printf '%s|%s|%s|%s|%s' "
        '"$RMW_IMPLEMENTATION" "$ROS_AUTOMATIC_DISCOVERY_RANGE" '
        '"${ROS_STATIC_PEERS:-}" "${ROS_LOCALHOST_ONLY:-}" "$SWARM_DISCOVERY_MODE"'
    )
    return subprocess.run(["bash", "-c", command], env=env, text=True, capture_output=True)


def test_hybrid_discovery_keeps_subnet_and_adds_unicast_peers(tmp_path):
    result = _source_discovery(tmp_path, peers="10.42.0.89;10.42.0.90")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rmw_cyclonedds_cpp|SUBNET|10.42.0.89;10.42.0.90||hybrid"


def test_static_discovery_uses_localhost_not_off(tmp_path):
    result = _source_discovery(tmp_path, mode="static", peers="10.42.0.146")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rmw_cyclonedds_cpp|LOCALHOST|10.42.0.146||static"


def test_static_discovery_requires_a_peer(tmp_path):
    result = _source_discovery(tmp_path, mode="static")
    assert result.returncode != 0
    assert "requires at least one peer" in result.stderr


def test_discovery_rejects_cross_vendor_override(tmp_path):
    env = {**os.environ, "SWARM_CORE_RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"}
    result = subprocess.run(
        ["bash", "-c", f'source "{DISCOVERY}"; swarm_core_apply_discovery_env'],
        env={**env, "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "requires rmw_cyclonedds_cpp" in result.stderr


def test_peer_file_is_deduplicated(tmp_path):
    command = (
        f'source "{DISCOVERY}"; '
        "swarm_core_add_static_peer 10.42.0.89; "
        "swarm_core_add_static_peer 10.42.0.89; "
        "swarm_core_collect_static_peers"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "10.42.0.89"


def test_runtime_entrypoints_share_discovery_policy():
    for relative in (
        "scripts/swarm_core_run_robot.sh",
        "scripts/swarm_core_run_local_ui.sh",
        "scripts/swarm_core_quickstart_step4.sh",
        "scripts/swarm_core_quickstart_step5.sh",
    ):
        script = (CORE_ROOT / relative).read_text(encoding="utf-8")
        assert "swarm_core_discovery.sh" in script
        assert "swarm_core_apply_discovery_env" in script

    service = (CORE_ROOT / "scripts/swarm_core_install_robot_service.sh").read_text(
        encoding="utf-8"
    )
    assert "swarm_core_run_robot.sh" in service
