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
