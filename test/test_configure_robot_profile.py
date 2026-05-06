from pathlib import Path

from swarm_control_core.configure_robot_profile import (
    _build_robot_entry,
    _suggest_control_machine_sync_specs,
    _compatible_control_interfaces,
    ensure_camera_profile,
    ensure_robot_entry,
    refresh_runtime_core_profiles,
    wiring_doc_for_interface,
)


CORE_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_configure_robot_profile_does_not_claim_quickstart_ready_before_control_registration() -> None:
    text = (CORE_ROOT / "swarm_control_core" / "configure_robot_profile.py").read_text(encoding="utf-8")

    assert "This robot is ready for QUICKSTART" not in text
    assert "Local robot profile is prepared on this robot" in text
    assert "Register/approve this robot on the control machine" in text


def test_ensure_robot_entry_creates_runtime_entry_without_dirtying_repo_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    control_types = workspace / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces = workspace / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot3:
    ssh_target: robot3@legion3.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )
    _write(
        control_types,
        """schema_version: "1.0"
control_types:
  diff_drive:
    type: diff_drive
    params: {}
  mecanum_drive:
    type: mecanum
    params: {}
""",
    )
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_l298n_1:
    gpio: {}
    params: {}
  4wheel_diff_tb6612fng_2:
    gpio: {}
    params: {}
  mecanum_tb6612fng_2:
    gpio: {}
    params: {}
""",
    )

    entry, created, sync_results = ensure_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        control_types_path=control_types,
        control_interfaces_path=control_interfaces,
        robot_name="robot_new",
        prompt_input=None,
        control_type="diff_drive",
        control_interface="4wheel_diff_tb6612fng_2",
        linux_username="robot_new",
        hostname="robot-new-pi",
    )

    assert created is True
    assert entry["ssh_target"] == "robot_new@robot-new-pi.local"
    assert entry["control_type"] == "diff_drive"
    assert entry["control_interface"] == "4wheel_diff_tb6612fng_2"
    assert len(sync_results) == 1
    assert sync_results[0]["path"] == runtime_profiles
    assert sync_results[0]["state"] == "missing_file"
    assert sync_results[0]["repaired"] is True

    repo_text = repo_profiles.read_text(encoding="utf-8")
    assert "robot_new:" not in repo_text

    runtime_text = runtime_profiles.read_text(encoding="utf-8")
    assert "robot_new:" in runtime_text
    assert "ssh_target: robot_new@robot-new-pi.local" in runtime_text


def test_ensure_robot_entry_can_update_source_baseline_when_requested(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    control_types = workspace / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces = workspace / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots: {}
""",
    )
    _write(
        control_types,
        """schema_version: "1.0"
control_types:
  diff_drive:
    type: diff_drive
    params: {}
""",
    )
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_tb6612fng_2:
    compatible_control_types:
      - diff_drive
    gpio: {}
    params: {}
""",
    )

    ensure_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        control_types_path=control_types,
        control_interfaces_path=control_interfaces,
        robot_name="robot_new",
        prompt_input=None,
        control_type="diff_drive",
        control_interface="4wheel_diff_tb6612fng_2",
        linux_username="robot_new",
        hostname="robot-new-pi",
        update_source_baseline=True,
    )

    repo_text = repo_profiles.read_text(encoding="utf-8")
    assert "robot_new:" in repo_text
    assert "control_interface: 4wheel_diff_tb6612fng_2" in repo_text


def test_ensure_robot_entry_reports_stale_runtime_entry(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    control_types = workspace / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces = workspace / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot_existing:
    ssh_target: robot_existing@robot-existing.local
    control_type: diff_drive
    control_interface: 4wheel_diff_tb6612fng_2
""",
    )
    _write(
        control_types,
        """schema_version: "1.0"
control_types:
  diff_drive:
    type: diff_drive
    params: {}
""",
    )
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_tb6612fng_2:
    gpio: {}
    params: {}
""",
    )
    _write(
        runtime_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot_existing:
    ssh_target: robot_existing@old-host.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )

    entry, created, sync_results = ensure_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        control_types_path=control_types,
        control_interfaces_path=control_interfaces,
        robot_name="robot_existing",
        prompt_input=None,
    )

    assert created is False
    assert entry["control_interface"] == "4wheel_diff_tb6612fng_2"
    assert sync_results[0]["state"] == "stale_entry"
    assert sync_results[0]["repaired"] is True

    runtime_text = runtime_profiles.read_text(encoding="utf-8")
    assert "ssh_target: robot_existing@robot-existing.local" in runtime_text
    assert "control_interface: 4wheel_diff_tb6612fng_2" in runtime_text


def test_ensure_robot_entry_can_update_existing_robot_runtime_when_explicit(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    control_types = workspace / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces = workspace / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot4:
    ssh_target: robot4@legion4.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )
    _write(
        control_types,
        """schema_version: "1.0"
control_types:
  diff_drive:
    type: diff_drive
    params: {}
""",
    )
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_l298n_1:
    gpio: {}
    params: {}
  4wheel_diff_l298n_2:
    gpio: {}
    params: {}
""",
    )

    entry, created, sync_results = ensure_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        control_types_path=control_types,
        control_interfaces_path=control_interfaces,
        robot_name="robot4",
        prompt_input=None,
        control_type="diff_drive",
        control_interface="4wheel_diff_l298n_2",
        update_existing=True,
    )

    assert created is False
    assert entry["ssh_target"] == "robot4@legion4.local"
    assert entry["control_interface"] == "4wheel_diff_l298n_2"
    assert sync_results[0]["repaired"] is True
    assert "control_interface: 4wheel_diff_l298n_1" in repo_profiles.read_text(encoding="utf-8")
    assert "control_interface: 4wheel_diff_l298n_2" in runtime_profiles.read_text(encoding="utf-8")


def test_ensure_robot_entry_update_preserves_explicit_ip_host(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    repo_profiles = workspace / "src" / "swarm_control_core" / "config" / "robot_instances.yaml"
    control_types = workspace / "src" / "swarm_control_core" / "config" / "control_types.yaml"
    control_interfaces = workspace / "src" / "swarm_control_core" / "config" / "control_interfaces.yaml"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"

    _write(
        repo_profiles,
        """schema_version: "1.0"
defaults:
  control_type: diff_drive
  control_interface: 4wheel_diff_l298n_1
robots:
  robot4:
    ssh_target: robot4@legion4.local
    control_type: diff_drive
    control_interface: 4wheel_diff_l298n_1
""",
    )
    _write(
        control_types,
        """schema_version: "1.0"
control_types:
  diff_drive:
    type: diff_drive
    params: {}
""",
    )
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_l298n_1:
    gpio: {}
    params: {}
  4wheel_diff_l298n_2:
    gpio: {}
    params: {}
""",
    )

    entry, _, _ = ensure_robot_entry(
        repo_profiles_path=repo_profiles,
        runtime_profiles_paths=[runtime_profiles],
        control_types_path=control_types,
        control_interfaces_path=control_interfaces,
        robot_name="robot4",
        prompt_input=None,
        control_type="diff_drive",
        control_interface="4wheel_diff_l298n_2",
        linux_username="robot4",
        hostname="10.42.0.44",
        update_existing=True,
    )

    assert entry["ssh_target"] == "robot4@10.42.0.44"


def test_refresh_runtime_core_profiles_copies_reusable_profile_files(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    source_config = workspace / "src" / "swarm_control_core" / "config"
    runtime_profiles = tmp_path / "runtime" / "robot_instances.yaml"
    _write(runtime_profiles, "schema_version: '1.0'\nrobots: {}\n")
    _write(source_config / "control_types.yaml", "schema_version: '1.0'\ncontrol_types: {}\n")
    _write(source_config / "control_interfaces.yaml", "schema_version: '1.0'\ncontrol_interfaces:\n  4wheel_diff_l298n_2: {}\n")

    results = refresh_runtime_core_profiles(workspace, [runtime_profiles])

    assert {Path(item["path"]).name for item in results} == {"control_types.yaml", "control_interfaces.yaml"}
    assert (tmp_path / "runtime" / "control_interfaces.yaml").read_text(encoding="utf-8").find("4wheel_diff_l298n_2") >= 0


def test_wiring_doc_for_interface_reads_profile_metadata(tmp_path: Path) -> None:
    control_interfaces = tmp_path / "control_interfaces.yaml"
    _write(
        control_interfaces,
        """schema_version: "1.0"
control_interfaces:
  4wheel_diff_l298n_2:
    docs:
      wiring: DOCS/GPIO/GPIO_for_differential_DUAL_L298N.md
    gpio: {}
    params: {}
  mecanum_l298n_2:
    docs:
      wiring: DOCS/GPIO/GPIO_for_mecanum_DUAL_L298N.md
    gpio: {}
    params: {}
""",
    )

    assert wiring_doc_for_interface(control_interfaces, "4wheel_diff_l298n_2") == "DOCS/GPIO/GPIO_for_differential_DUAL_L298N.md"
    assert wiring_doc_for_interface(control_interfaces, "mecanum_l298n_2") == "DOCS/GPIO/GPIO_for_mecanum_DUAL_L298N.md"


def test_ensure_camera_profile_uses_callback_when_profile_missing(tmp_path: Path) -> None:
    camera_profiles = tmp_path / "camera_profiles.yaml"

    def _save(robot: str, path: Path) -> int:
        _write(
            path,
            f"""schema_version: "1.0"
profiles:
  {robot}:
    source: usb
    device: /dev/video0
    width: 640
    height: 480
    fps: 15
    fourcc: MJPG
    force_v4l2: true
""",
        )
        return 0

    entry, created = ensure_camera_profile(
        camera_profiles_path=camera_profiles,
        robot_name="robot_new",
        save_callback=_save,
    )

    assert created is True
    assert entry["device"] == "/dev/video0"


def test_compatible_control_interfaces_prefers_matching_drive_family() -> None:
    interfaces = [
        "4wheel_diff_l298n_1",
        "4wheel_diff_l298n_2",
        "mecanum_l298n_2",
        "4wheel_diff_tb6612fng_2",
        "mecanum_tb6612fng_2",
    ]
    assert _compatible_control_interfaces("diff_drive", interfaces) == [
        "4wheel_diff_l298n_1",
        "4wheel_diff_l298n_2",
        "4wheel_diff_tb6612fng_2",
    ]
    assert _compatible_control_interfaces("mecanum_drive", interfaces) == [
        "mecanum_l298n_2",
        "mecanum_tb6612fng_2",
    ]


def test_suggest_control_machine_sync_specs_uses_robot_ssh_target() -> None:
    assert _suggest_control_machine_sync_specs(
        "my_robot",
        {"ssh_target": "robot1@legion1.local"},
    ) == [
        "robot1@legion1.local",
        "my_robot=robot1@legion1.local",
    ]


def test_build_robot_entry_preserves_explicit_host_suffix_or_address() -> None:
    assert _build_robot_entry(
        "robot4",
        "diff_drive",
        "4wheel_diff_l298n_2",
        linux_username="robot4",
        hostname="legion4.local",
    )["ssh_target"] == "robot4@legion4.local"
    assert _build_robot_entry(
        "robot4",
        "diff_drive",
        "4wheel_diff_l298n_2",
        linux_username="robot4",
        hostname="10.42.0.44",
    )["ssh_target"] == "robot4@10.42.0.44"
