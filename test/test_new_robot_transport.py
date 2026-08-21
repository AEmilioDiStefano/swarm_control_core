import subprocess
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
NEW_ROBOT = CORE_ROOT / "scripts" / "swarm_core_new_robot.sh"


def test_invalid_robot_ip_fails_before_network_contact():
    result = subprocess.run(
        [str(NEW_ROBOT), "robot4@legion4.local", "--robot-ip", "not-an-ip"],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "--robot-ip must be a usable IPv4 address" in result.stderr


def test_onboarding_hardens_ssh_and_records_bidirectional_dds_peers():
    script = NEW_ROBOT.read_text(encoding="utf-8")
    for setting in (
        "IdentitiesOnly=yes",
        "AddressFamily=inet",
        "PubkeyAuthentication=no",
        "NumberOfPasswordPrompts=1",
    ):
        assert setting in script
    assert 'swarm_core_add_static_peer "$robot_lan_ip"' in script
    assert "swarm_core_add_static_peer '${control_lan_ip}'" in script
    assert "getent ahostsv4" in script
    assert "git ls-remote --exit-code" in script
    assert "repo_commit" in script
    assert "ros_domain_id" in script
    assert "swarm_core_prepare_robot_checkout.sh" in script
    assert "--require-camera" in script
    assert '--ssh-private-key "$ssh_private_key"' in script


def test_onboarding_respects_the_workspace_selected_by_swarmc():
    script = NEW_ROBOT.read_text(encoding="utf-8")
    assert "swarm_core_detect_workspace_root" in script
    assert 'SWARM_CORE_WORKSPACE_ROOT:-' in script


def test_requested_service_starts_only_after_profile_is_written():
    script = NEW_ROBOT.read_text(encoding="utf-8")
    profile = script.index("ros2 run swarm_control_core add_robot_core")
    service_start = script.index("systemctl restart swarm-core-robot.service")
    assert service_start > profile
    assert "--enable-service-now --robot-name" not in script


def test_onboarding_stops_stale_service_and_does_not_swallow_cloud_init_timeout():
    script = NEW_ROBOT.read_text(encoding="utf-8")
    checkout = script.index("swarm_core_prepare_robot_checkout.sh")
    service_stop = script.index("service_action=\"stop\"")
    assert service_stop < checkout
    assert "cloud-init did not finish cleanly" in script
    assert "cloud-init status --wait >/dev/null 2>&1 || true" not in script


def test_gpio_setup_probes_the_backend_device_not_only_gpiomem():
    script = (CORE_ROOT / "scripts" / "swarm_core_enable_gpio_access.sh").read_text(
        encoding="utf-8"
    )
    assert 'KERNEL=="gpiochip[0-9]*"' in script
    assert "lgpio.gpiochip_open" in script
    assert "lgpio.gpiochip_close" in script
