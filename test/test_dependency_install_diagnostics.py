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


def test_dependency_installer_repairs_duplicate_ros_apt_sources_before_update():
    script = (CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh").read_text(
        encoding="utf-8"
    )

    assert "disable_duplicate_ros_apt_sources()" in script
    assert "packages.ros.org/ros2/ubuntu" in script
    assert ".disabled-by-swarm-control" in script
    assert "Disabling duplicate ROS apt source" in script
    assert "[[ \"$(sudo cat \"$source_file\" 2>/dev/null)\" != \"$repo_line\" ]]" in script


def test_dependency_installer_covers_fresh_noble_mdns_and_ui_runtime():
    script = (CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh").read_text(
        encoding="utf-8"
    )

    for package in (
        "avahi-daemon",
        "libnss-mdns",
        "python3-aiohttp",
        "python3-numpy",
        "python3-pil",
    ):
        assert f'"{package}"' in script
    assert "systemctl enable --now avahi-daemon.service" in script
    assert "import aiohttp, av, aiortc, numpy; from PIL import Image" in script
