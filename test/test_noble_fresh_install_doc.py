import os
import re
import shutil
import subprocess
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
GUIDE = CORE_ROOT / "DOCS" / "NOBLE_FRESH_INSTALL.md"
SWARMC = CORE_ROOT / "scripts" / "swarmc"
SAFE_HELP_SCRIPTS = {
    "setup": CORE_ROOT / "scripts" / "swarm_core_bootstrap_machine.sh",
    "imager-checklist": CORE_ROOT / "scripts" / "swarm_core_new_robot.sh",
    "new-robot": CORE_ROOT / "scripts" / "swarm_core_new_robot.sh",
    "doctor": CORE_ROOT / "scripts" / "swarm_core_robot_doctor.sh",
    "wheel-test": CORE_ROOT / "scripts" / "swarm_core_wheel_test.sh",
    **{
        f"step{step}": CORE_ROOT
        / "scripts"
        / f"swarm_core_quickstart_step{step}.sh"
        for step in range(6)
    },
}


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.S)


def _logical_commands(text: str) -> list[str]:
    """Return copy/paste commands with backslash continuations joined."""
    commands: list[str] = []
    for block in _bash_blocks(text):
        pending = ""
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            pending = f"{pending} {line}".strip()
            if pending.endswith("\\"):
                pending = pending[:-1].rstrip()
                continue
            commands.append(pending)
            pending = ""
        if pending:
            commands.append(pending)
    return commands


def _swarmc_invocations(text: str) -> list[tuple[str, str]]:
    invocations: list[tuple[str, str]] = []
    for command in _logical_commands(text):
        match = re.search(
            r'(?:^|\s)(?:"?[^\s"]*/swarmc"?|swarmc)\s+([a-z][a-z0-9-]*)\b',
            command,
        )
        if match:
            invocations.append((match.group(1), command[match.start() :].strip()))
    return invocations


def _help_for(subcommand: str) -> str:
    script = SAFE_HELP_SCRIPTS[subcommand]
    result = subprocess.run(
        [str(script), "--help"],
        cwd=CORE_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout + result.stderr


def test_noble_guide_uses_a_normal_clone_inside_the_ros_workspace():
    text = GUIDE.read_text(encoding="utf-8")
    commands = _logical_commands(text)

    clone_commands = [command for command in commands if "git clone" in command]
    assert clone_commands, "The fresh-machine guide must include the initial git clone."
    assert any(
        "ros2_ws_dev/src/swarm_control_core" in command for command in clone_commands
    ), "Clone swarm_control_core directly under the documented ROS 2 workspace."


def test_primary_documentation_routes_fresh_noble_users_to_this_guide():
    readme = (CORE_ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (CORE_ROOT / "DOCS" / "QUICKSTART.md").read_text(encoding="utf-8")
    assembly = (CORE_ROOT / "DOCS" / "setup_instructions_ASSEMBLY.md").read_text(
        encoding="utf-8"
    )

    for text in (readme, quickstart, assembly):
        assert "NOBLE_FRESH_INSTALL.md" in text
    assert "ADD_control_machine.md" not in readme


def test_every_documented_swarmc_command_and_option_matches_its_help():
    text = GUIDE.read_text(encoding="utf-8")
    invocations = _swarmc_invocations(text)
    assert invocations, "The Noble guide must use the swarmc launcher."

    top_level_help = subprocess.run(
        [str(SWARMC), "help"],
        cwd=CORE_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout

    help_cache: dict[str, str] = {}
    for subcommand, command in invocations:
        assert re.search(rf"\b{re.escape(subcommand)}\b", top_level_help), (
            f"NOBLE_FRESH_INSTALL.md uses unknown swarmc subcommand: {subcommand}"
        )
        options = re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", command)
        if not options:
            continue
        assert subcommand in SAFE_HELP_SCRIPTS, (
            f"Add a non-mutating --help mapping before documenting options for {subcommand}"
        )
        if subcommand not in help_cache:
            help_cache[subcommand] = _help_for(subcommand)
        help_text = help_cache[subcommand]
        for option in options:
            # `setup --role` is translated by the facade to the bootstrap
            # script's `--machine-role`, and is documented by facade help.
            assert option in help_text or option in top_level_help, (
                f"{subcommand} command uses {option}, but its help does not list it"
            )


def test_onboarding_commands_are_ip_first_and_do_not_hardcode_hardware():
    text = GUIDE.read_text(encoding="utf-8")
    onboarding_script = (CORE_ROOT / "scripts" / "swarm_core_new_robot.sh").read_text(
        encoding="utf-8"
    )

    # The guide intentionally tells the operator to run the personalized block
    # printed by the checklist instead of publishing a copyable wrong-hardware
    # example. Contract-test the generated block as part of the guide.
    assert 'read -r -p \'Robot IPv4 address from the router/DHCP list:' in onboarding_script
    assert r'--robot-ip \"\$ROBOT_IP\"' in onboarding_script
    assert "--control-type ${control_type}" in onboarding_script
    assert "--control-interface ${control_interface}" in onboarding_script

    for command in _logical_commands(text):
        for option in ("--control-type", "--control-interface"):
            match = re.search(rf"{option}\s+([^\s\\]+)", command)
            if match:
                value = match.group(1).strip("'\"")
                assert value.startswith("$") or value.startswith("<"), (
                    f"Do not hardcode {option}={value} in a copy/paste command; "
                    "the operator must use the hardware selected by the checklist."
                )

    lower = text.lower()
    assert re.search(r"exact .*command.*printed by step 1", lower)
    assert "hardware" in lower and "do not copy" in lower


def test_noble_guide_obeys_drp_structure_and_machine_labels():
    text = GUIDE.read_text(encoding="utf-8")
    assert "# Direct Run Path" in text
    assert "# Alternative/Debug/Fix Reference" in text
    direct, reference = text.split("# Alternative/Debug/Fix Reference", 1)
    assert "SWARM_CORE_DISCOVERY_MODE=static" not in direct

    anchors = set(re.findall(r'<a id="([^"]+)"></a>', text))
    links = set(re.findall(r"\]\(#([^)]+)\)", text))
    assert links <= anchors, f"Unresolved guide anchors: {sorted(links - anchors)}"

    for match in re.finditer(r"```bash\n", text):
        prefix = text[: match.start()].rstrip().splitlines()
        assert prefix and re.fullmatch(r"### [A-Z][A-Z ()/<>-]*:", prefix[-1]), (
            "Every executable block must be immediately preceded by an uppercase "
            f"machine/context heading; got {prefix[-1] if prefix else '<none>'!r}"
        )

    for block in _bash_blocks(text):
        syntax = subprocess.run(
            ["bash", "-n"], input=block, text=True, capture_output=True
        )
        assert syntax.returncode == 0, syntax.stderr

    assert "### IF " in direct
    assert "Then return to [Step" in reference or "then return to [Step" in reference
    assert "--allow-lan-bind" not in text
    assert not re.search(r"\bswarmc\s+step5\b", text)

    step3_help = _help_for("step3")
    assert "--allow-lan-bind" not in step3_help


def test_recovery_transport_never_depends_on_dot_local():
    text = GUIDE.read_text(encoding="utf-8")
    commands = _logical_commands(text)

    for command in commands:
        if re.search(r"(?:^|\s)(?:ssh|scp|rsync)(?:\s|$)", command):
            assert ".local" not in command, (
                f"Fresh-card SSH/recovery must use the robot IPv4 address: {command}"
            )

    lower = text.lower()
    assert "router" in lower or "dhcp" in lower
    assert "--robot-ip" in text


def test_browser_acceptance_requires_a_real_live_camera_frame():
    text = GUIDE.read_text(encoding="utf-8")
    lower = text.lower()

    assert "http://127.0.0.1:8080" in text
    assert re.search(r"open\s+.*http://127\.0\.0\.1:8080", lower)
    assert re.search(
        r"(?:live|moving)\s+(?:camera\s+)?(?:frame|video)|"
        r"(?:camera\s+)?(?:frame|video)\s+.*(?:live|moving)",
        lower,
    ), "Graph visibility alone is not FPV acceptance; require a visibly live frame."
    assert "step4" in lower and "not" in lower and "proof" in lower


def test_retry_path_is_explicit_and_non_destructive():
    text = GUIDE.read_text(encoding="utf-8")
    lower = text.lower()

    assert "safe to rerun" in lower
    assert re.search(r"rerun\s+(?:the\s+)?(?:same|exact).*new-robot", lower, re.S)
    assert "start over" in lower or "retry" in lower

    for block in _bash_blocks(text):
        assert "rm -rf" not in block
        assert "git reset --hard" not in block
        assert "git clean -" not in block

    onboarding_script = (
        CORE_ROOT / "scripts" / "swarm_core_new_robot.sh"
    ).read_text(encoding="utf-8")
    for retry_contract in (
        "ssh-keygen -R",
        "swarm_core_prepare_robot_checkout.sh",
        "every stage is safe to rerun",
        "swarm_core_add_static_peer",
    ):
        assert retry_contract in onboarding_script


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_new_robot_orchestration_can_be_rerun_without_duplicate_peer_state(tmp_path):
    """Exercise two complete shell passes while replacing only network/ROS edges."""
    workspace = tmp_path / "ros2_ws_dev"
    checkout = workspace / "src" / "swarm_control_core"
    scripts = checkout / "scripts"
    lib = scripts / "lib"
    lib.mkdir(parents=True)
    for relative in (
        "scripts/swarm_core_new_robot.sh",
        "scripts/swarm_core_prepare_robot_checkout.sh",
        "scripts/lib/swarm_core_workspace.sh",
        "scripts/lib/swarm_core_discovery.sh",
    ):
        source = CORE_ROOT / relative
        destination = checkout / relative
        shutil.copy2(source, destination)

    install = workspace / "install"
    install.mkdir()
    (install / "setup.bash").write_text("true\n", encoding="utf-8")

    _run(["git", "init", "-b", "main"], cwd=checkout)
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=checkout)
    _run(["git", "config", "user.name", "Noble retry test"], cwd=checkout)
    _run(["git", "add", "scripts"], cwd=checkout)
    _run(["git", "commit", "-m", "test fixture"], cwd=checkout)

    origin = tmp_path / "origin.git"
    _run(["git", "init", "--bare", str(origin)], cwd=tmp_path)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=checkout)
    _run(["git", "push", "-u", "origin", "main"], cwd=checkout)

    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    key = ssh_dir / "id_ed25519"
    _run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        cwd=tmp_path,
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env bash
case "$*" in
  *"hostname -s"*)
    printf '%s\n' legion4
    ;;
  *"SSH_CONNECTION"*)
    printf '%s\n' '10.42.0.1 45678 10.42.0.89 22'
    ;;
  *"SWARM_REMOTE_HOME"*)
    printf '%s\n' 'SWARM_REMOTE_HOME=/home/robot4'
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    for name in ("ssh-keyscan", "ros2"):
        stub = fake_bin / name
        stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SWARM_CORE_CONFIG_DIR": str(home / ".config" / "swarm_control_core"),
    }
    command = [
        str(scripts / "swarm_core_new_robot.sh"),
        "robot4@legion4.local",
        "--robot-ip",
        "10.42.0.89",
        "--control-type",
        "diff_drive",
        "--control-interface",
        "4wheel_diff_l298n_2",
        "--boot-wait-timeout",
        "1",
        "--cloud-init-timeout",
        "1",
    ]

    first = _run(command, cwd=checkout, env=env)
    second = _run(command, cwd=checkout, env=env)

    assert "is onboarded and registered/approved" in first.stderr
    assert "is onboarded and registered/approved" in second.stderr
    peer_file = home / ".config" / "swarm_control_core" / "discovery_peers"
    assert peer_file.read_text(encoding="utf-8").splitlines() == ["10.42.0.89"]
