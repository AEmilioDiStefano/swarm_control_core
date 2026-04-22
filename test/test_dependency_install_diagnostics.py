from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]


def test_dependency_installer_makes_ros_apt_setup_diagnosable():
    script = (CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh").read_text(
        encoding="utf-8"
    )

    assert "dependency_status \"Enabling Ubuntu universe repository\"" in script
    assert "dependency_status \"Downloading ROS apt key from GitHub\"" in script
    assert "--connect-timeout 15 --max-time 60" in script
    assert "DPkg::Lock::Timeout=120" in script
    assert "sudo -v || exit 1" in script
    assert "add-apt-repository -y universe >/dev/null 2>&1" not in script
