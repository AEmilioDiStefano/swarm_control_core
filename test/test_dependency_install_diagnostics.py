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


def test_dependency_installer_checks_apt_candidate_versions_before_skipping():
    script = (CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh").read_text(
        encoding="utf-8"
    )

    assert "apt_candidate_version()" in script
    assert "apt_package_is_current()" in script
    assert "apt-cache policy" in script
    assert "dpkg --compare-versions" in script
    assert "ros-${ros_distro}-launch" in script
    assert "ros-${ros_distro}-launch-ros" in script
    assert "is already installed and up to date." in script
    assert "is missing or outdated. Installing/updating now..." in script
    assert "All dependencies are installed and up to date." in script


def test_dependency_installer_skips_universe_when_already_enabled():
    script = (CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh").read_text(
        encoding="utf-8"
    )

    assert "ubuntu_component_enabled()" in script
    assert "Ubuntu universe repository already enabled" in script
    assert "if ubuntu_component_enabled universe \"$codename\"; then" in script
