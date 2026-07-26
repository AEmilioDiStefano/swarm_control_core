from pathlib import Path

import re


CORE_ROOT = Path(__file__).resolve().parents[1]
DANGEROUS_SNIPPET = "return 1 2>/dev/null || exit 1"
FIRST_CONTACT_URL = (
    "https://raw.githubusercontent.com/AEmilioDiStefano/swarm_control_core/"
    "main/scripts/swarm_core_first_contact.sh"
)
LAUNCHER = "~/.local/bin/swarmc"
DRP_MACHINE_LABELS = (
    "### CONTROL MACHINE",
    "### CONTROL MACHINE / ROBOT",
    "### ROBOT",
    "### AFFECTED ROBOT",
    "### SECOND ROBOT SSH TERMINAL",
)
OPERATOR_GUIDES = [
    CORE_ROOT / "DOCS" / "QUICKSTART.md",
    CORE_ROOT / "DOCS" / "ADD_robot_pi.md",
    CORE_ROOT / "DOCS" / "ADD_control_machine.md",
    CORE_ROOT / "DOCS" / "setup_instructions_ASSEMBLY.md",
    CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
    CORE_ROOT / "DOCS" / "control_interface_profiles.md",
    CORE_ROOT / "DOCS" / "git_workflow.md",
]
# Guides fully converted to launcher commands: user-facing bash blocks must
# stay short. The heavy lifting belongs in scripts/, not in copy-paste blocks.
SHORT_BLOCK_GUIDES = {
    CORE_ROOT / "DOCS" / "QUICKSTART.md",
    CORE_ROOT / "DOCS" / "ADD_robot_pi.md",
    CORE_ROOT / "DOCS" / "ADD_control_machine.md",
    CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
    CORE_ROOT / "DOCS" / "git_workflow.md",
}
MAX_BASH_BLOCK_LINES = 12


def _bash_blocks(text):
    return re.findall(r"```bash\n(.*?)```", text, re.S)


def test_quickstart_docs_keep_shell_open_on_bootstrap_failure():
    docs = [
        CORE_ROOT / "DOCS" / "QUICKSTART.md",
        CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
        CORE_ROOT / "DOCS" / "git_workflow.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert DANGEROUS_SNIPPET not in text, f"{path} still contains a shell-closing bootstrap fallback"

    # The launcher pattern replaces the old sourced bootstrap function: a
    # launcher command is a child process, so a failure can never close the
    # operator's shell (including SSH sessions).
    for relative in ("QUICKSTART.md", "LOCAL_FPV_runbook.md"):
        text = (CORE_ROOT / "DOCS" / relative).read_text(encoding="utf-8")
        assert LAUNCHER in text, f"{relative} must use the swarmc launcher"

    runbook = (CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md").read_text(encoding="utf-8")
    assert 'eval "$(~/.local/bin/swarmc env)"' in runbook


def test_add_robot_guide_uses_first_contact_bootstrap():
    path = CORE_ROOT / "DOCS" / "ADD_robot_pi.md"
    text = path.read_text(encoding="utf-8")

    assert DANGEROUS_SNIPPET not in text
    assert FIRST_CONTACT_URL in text
    assert f"{LAUNCHER} new-robot" in text
    assert f"{LAUNCHER} imager-checklist" in text
    assert f"{LAUNCHER} verify-robots" in text
    assert "# Direct Run Path" in text
    assert "# Alternative/Debug/Fix Reference" in text
    assert "## Step 3: Onboard With One Command" in text
    assert "swarm_core_new_robot.sh" in text
    assert "Raspberry Pi Imager" in text
    assert "approved for FPV UI control until" in text
    assert "Registered/approved robots are ready for QUICKSTART handoff" in text
    assert "ADD_control_machine.md" in text


def test_first_contact_script_is_fresh_machine_safe():
    script = CORE_ROOT / "scripts" / "swarm_core_first_contact.sh"
    text = script.read_text(encoding="utf-8")

    # The one-liner is fetched before any checkout exists, so the clone must
    # live inside this script, and the script must delegate real logic to the
    # repo it clones.
    assert 'git clone "$repo_url"' in text
    assert "https://github.com/AEmilioDiStefano/swarm_control_core.git" in text
    assert "swarm_core_install_launchers.sh" in text
    assert "set -euo pipefail" in text


def test_launcher_installer_writes_both_shims():
    installer = CORE_ROOT / "scripts" / "swarm_core_install_launchers.sh"
    text = installer.read_text(encoding="utf-8")

    assert 'write_shim "swarmc" "src/swarm_control_core/scripts/swarmc"' in text
    assert 'write_shim "swarmp" "src/swarm_control_pro/scripts/swarmp"' in text


def test_quickstart_ready_message_lives_after_control_machine_registration():
    add_robot_text = (CORE_ROOT / "swarm_control_core" / "configure_robot_profile.py").read_text(encoding="utf-8")
    sync_text = (CORE_ROOT / "swarm_control_core" / "sync_robot_entries.py").read_text(encoding="utf-8")

    assert "ready for QUICKSTART" not in add_robot_text
    assert "Registered/approved robots are ready for QUICKSTART handoff" in sync_text


def test_add_robot_guide_labels_every_bash_block_with_machine_type():
    path = CORE_ROOT / "DOCS" / "ADD_robot_pi.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    allowed_labels = {"### CONTROL MACHINE:", "### ROBOT(S):"}

    for idx, line in enumerate(lines):
        if line != "```bash":
            continue

        probe = idx - 1
        while probe >= 0 and lines[probe].strip() == "":
            probe -= 1

        assert probe >= 0, f"{path} has a bash block without a preceding machine label"
        assert lines[probe] in allowed_labels, (
            f"{path} bash block on line {idx + 1} must be preceded by one of {sorted(allowed_labels)}"
        )


def test_core_operator_guides_follow_drp_structure():
    for path in OPERATOR_GUIDES:
        text = path.read_text(encoding="utf-8")
        assert "# Direct Run Path" in text, path
        assert "# Alternative/Debug/Fix Reference" in text, path

        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if line != "```bash":
                continue

            probe = idx - 1
            while probe >= 0 and lines[probe].strip() == "":
                probe -= 1

            assert probe >= 0, f"{path} has a bash block without a preceding machine label"
            assert lines[probe].startswith(DRP_MACHINE_LABELS), (
                f"{path} bash block on line {idx + 1} must be preceded by a DRP machine label"
            )


def test_converted_guides_keep_bash_blocks_short():
    for path in sorted(SHORT_BLOCK_GUIDES):
        text = path.read_text(encoding="utf-8")
        for block in _bash_blocks(text):
            block_lines = [line for line in block.strip().splitlines()]
            assert len(block_lines) <= MAX_BASH_BLOCK_LINES, (
                f"{path} has a {len(block_lines)}-line bash block; move the logic "
                f"into a script behind the swarmc launcher (limit "
                f"{MAX_BASH_BLOCK_LINES}):\n{block}"
            )


def test_drp_guide_format_exists_and_defines_branching_rules():
    path = CORE_ROOT / "DOCS" / "DRP_guide_format.md"
    text = path.read_text(encoding="utf-8")

    assert "DRP means **Direct Run Path**" in text
    assert "Every direct-path branch should start with `### IF`" in text
    assert "Alternative/Debug/Fix Reference" in text


def test_quickstart_uses_drp_top_and_bottom_sections():
    path = CORE_ROOT / "DOCS" / "QUICKSTART.md"
    text = path.read_text(encoding="utf-8")

    assert "[`DRP_guide_format.md`](./DRP_guide_format.md)" in text
    assert "# Direct Run Path" in text
    assert "# Alternative/Debug/Fix Reference" in text
    assert "## Step 2.5: Register/Verify Trusted Robots (Control Machine)" in text
    assert "Registered/approved robots are ready for QUICKSTART handoff" in text
    assert "### IF robots are visible but read-only/untrusted" in text
    assert "## Fix Step 3.2: Robots Are Visible but Read-Only/Untrusted" in text
    assert f"{LAUNCHER} register" in text
    assert f"{LAUNCHER} step2" in text
