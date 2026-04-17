from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
DANGEROUS_SNIPPET = "return 1 2>/dev/null || exit 1"


def test_quickstart_docs_keep_shell_open_on_bootstrap_failure():
    docs = [
        CORE_ROOT / "DOCS" / "QUICKSTART.md",
        CORE_ROOT / "DOCS" / "LOCAL_FPV_runbook.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert DANGEROUS_SNIPPET not in text, f"{path} still contains a shell-closing bootstrap fallback"
        assert "swarm_core_bootstrap_terminal() {" in text


def test_setup_instructions_use_idempotent_setup_bootstrap():
    path = CORE_ROOT / "DOCS" / "setup_instructions_SOFTWARE.md"
    text = path.read_text(encoding="utf-8")

    assert DANGEROUS_SNIPPET not in text
    assert "swarm_core_setup_bootstrap.sh" in text
    assert "## 1. Workspace Creation / Checkout" not in text
    assert "## 2. Workspace Bootstrap in Each Terminal" not in text


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
