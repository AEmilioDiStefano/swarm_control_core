from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]


def _function_body(script: str, name: str, following_marker: str) -> str:
    start = script.index(f"{name}() {{")
    end = script.index(following_marker, start)
    return script[start:end]


def test_robot_upgrade_repairs_before_and_after_and_never_masks_failure():
    script = (CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh").read_text(
        encoding="utf-8"
    )
    body = _function_body(script, "robot_system_update_upgrade", "\ncurrent_step=")

    first_configure = body.index("dpkg --configure -a")
    first_fix = body.index("--fix-broken install -y")
    update = body.index("DPkg::Lock::Timeout=1800 update")
    upgrade = body.index("DPkg::Lock::Timeout=1800 upgrade -y")
    second_configure = body.index("dpkg --configure -a", first_configure + 1)
    second_fix = body.index("--fix-broken install -y", first_fix + 1)

    assert first_configure < first_fix < update < upgrade < second_configure < second_fix
    assert body.count("dpkg --configure -a") >= 2
    assert body.count("--fix-broken install -y") == 2

    guarded_commands = [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith(("wait_for_package_manager", "sudo dpkg", "sudo env"))
    ]
    assert guarded_commands
    initial_configure = next(line for line in guarded_commands if "initial_dpkg_status=$?" in line)
    assert initial_configure.endswith("|| initial_dpkg_status=$?")
    assert all(
        line.endswith("|| return $?")
        for line in guarded_commands
        if line != initial_configure
    )


def test_control_package_repair_runs_before_dependencies_and_propagates_failures():
    script = (CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh").read_text(
        encoding="utf-8"
    )
    body = _function_body(
        script,
        "repair_package_state_before_dependencies",
        "\nrobot_system_update_upgrade()",
    )

    first_configure = body.index("dpkg --configure -a")
    fix_broken = body.index("--fix-broken install -y")
    second_configure = body.index("dpkg --configure -a", first_configure + 1)
    assert first_configure < fix_broken < second_configure

    guarded_commands = [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith(("wait_for_package_manager", "sudo env"))
    ]
    assert guarded_commands
    initial_configure = next(line for line in guarded_commands if "initial_dpkg_status=$?" in line)
    assert initial_configure.endswith("|| initial_dpkg_status=$?")
    assert all(
        line.endswith("|| return $?")
        for line in guarded_commands
        if line != initial_configure
    )

    repair_call = script.index(
        'run_bootstrap_step 5 "Repairing interrupted apt/dpkg package state"'
    )
    dependency_call = script.index('current_step="dependency-check"')
    assert repair_call < dependency_call


def test_pre_git_robot_recovery_repairs_dpkg_before_apt_and_never_masks_failure():
    script = (CORE_ROOT / "scripts" / "swarm_core_new_robot.sh").read_text(
        encoding="utf-8"
    )
    start = script.index('log "Preparing the exact robot checkout')
    end = script.index("printf -v checkout_command", start)
    block = script[start:end]

    first_configure = block.index("dpkg --configure -a")
    fix_broken = block.index("--fix-broken install -y")
    second_configure = block.index("dpkg --configure -a", first_configure + 1)
    update = block.index("DPkg::Lock::Timeout=1800 update")
    install_git = block.index("DPkg::Lock::Timeout=1800 install -y git")
    assert first_configure < fix_broken < second_configure < update < install_git

    package_commands = [
        line.strip().rstrip("\\").strip()
        for line in block.splitlines()
        if "DEBIAN_FRONTEND=noninteractive" in line
    ]
    assert len(package_commands) == 5
    initial_configure = next(command for command in package_commands if "initial_dpkg_status=\\$?" in command)
    assert initial_configure.endswith("|| initial_dpkg_status=\\$?;")
    assert all(
        command.endswith("|| exit \\$?;")
        for command in package_commands
        if command != initial_configure
    )


def test_ros_key_and_source_are_validated_and_replaced_atomically():
    script = (
        CORE_ROOT / "scripts" / "swarm_core_check_install_dependencies.sh"
    ).read_text(encoding="utf-8")

    assert "ros_apt_keyring_is_valid()" in script
    assert 'gpg --batch --quiet --show-keys "$keyring_path"' in script
    assert "install_ros_apt_keyring_atomically()" in script
    assert 'install_ros_apt_keyring_atomically "$keyring"' in script
    assert 'atomic_install_as_root "$dearmored_tmp" "$destination_path" 0644' in script
    assert 'write_text_file_atomically_as_root "$source_file" "$repo_line"' in script
    assert 'sudo mktemp "${destination_path}.tmp.XXXXXX"' in script
    assert 'sudo mv -f "$destination_tmp" "$destination_path"' in script
    assert "disabled-by-swarm-control-key-repair" in script

    assert 'echo "$repo_line" | sudo tee "$source_file"' not in script
    assert '| sudo gpg --batch --yes --dearmor -o "$keyring"' not in script
