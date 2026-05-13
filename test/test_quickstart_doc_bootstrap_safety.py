from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
DANGEROUS_SNIPPET = "return 1 2>/dev/null || exit 1"
DRP_MACHINE_LABELS = (
    "### CONTROL MACHINE",
    "### CONTROL MACHINE / ROBOT",
    "### ROBOT",
    "### AFFECTED ROBOT",
    "### SECOND ROBOT SSH TERMINAL",
)


def test_quickstart_docs_keep_shell_open_on_bootstrap_failure():
    docs = [
        CORE_ROOT / "DOCS" / "QUICKSTART.md",
        CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
        CORE_ROOT / "DOCS" / "git_workflow.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert DANGEROUS_SNIPPET not in text, f"{path} still contains a shell-closing bootstrap fallback"

    for relative in ("QUICKSTART.md", "LOCAL_FPV_runbook.md"):
        text = (CORE_ROOT / "DOCS" / relative).read_text(encoding="utf-8")
        assert "swarm_core_bootstrap_terminal() {" in text


def test_setup_instructions_use_idempotent_setup_bootstrap():
    path = CORE_ROOT / "DOCS" / "setup_instructions_SOFTWARE.md"
    text = path.read_text(encoding="utf-8")

    assert DANGEROUS_SNIPPET not in text
    assert "swarm_core_setup_bootstrap.sh" in text
    assert "## 1. Workspace Creation / Checkout" not in text
    assert "## 2. Workspace Bootstrap in Each Terminal" not in text
    assert "# Direct Run Path" in text
    assert "# Alternative/Debug/Fix Reference" in text
    assert "## Step 2: Prepare Each Robot and Add Its Local Profile" in text
    assert "## Step 4: Register and Approve Robots on the Control Machine" in text
    assert "registration/approval step confirms" in text
    assert "This is a local robot-profile step only" in text
    assert "Do not expect the robot SSH terminals to print the final Quickstart-ready" in text
    assert "message appears in the control-machine terminal" in text
    assert "Registered/approved robots are ready for QUICKSTART handoff" in text
    assert "After Step 4 registration/approval and Step 5 verification succeed" in text


def test_quickstart_ready_message_lives_after_control_machine_registration():
    add_robot_text = (CORE_ROOT / "swarm_control_core" / "configure_robot_profile.py").read_text(encoding="utf-8")
    sync_text = (CORE_ROOT / "swarm_control_core" / "sync_robot_entries.py").read_text(encoding="utf-8")

    assert "ready for QUICKSTART" not in add_robot_text
    assert "Registered/approved robots are ready for QUICKSTART handoff" in sync_text


def test_setup_instructions_label_every_bash_block_with_machine_type():
    path = CORE_ROOT / "DOCS" / "setup_instructions_SOFTWARE.md"
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
    docs = [
        CORE_ROOT / "DOCS" / "QUICKSTART.md",
        CORE_ROOT / "DOCS" / "setup_instructions_SOFTWARE.md",
        CORE_ROOT / "DOCS" / "setup_instructions_ASSEMBLY.md",
        CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
        CORE_ROOT / "DOCS" / "control_interface_profiles.md",
        CORE_ROOT / "DOCS" / "git_workflow.md",
    ]

    for path in docs:
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
