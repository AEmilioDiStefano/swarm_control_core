#!/usr/bin/env python3
"""
Documentation link integrity gate.

Every relative markdown link in the repo must resolve to an existing file or
directory. Links inside fenced code blocks are ignored (they are examples, not
navigation). External links (http/https/mailto) and pure anchors are ignored.
Targets that resolve outside this repository (cross-repo references to a
sibling checkout) are skipped so the gate stays hermetic for standalone
clones.
"""

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "build",
    "install",
    "log",
    "logs",
}
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _markdown_files():
    """Yield repo markdown files outside generated/vendored directories."""
    for md_path in sorted(REPO_ROOT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in md_path.parts):
            continue
        yield md_path


def _relative_link_targets(md_path):
    """Yield relative link targets from one markdown file."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    text = _FENCE_RE.sub("", text)
    for match in _LINK_RE.finditer(text):
        raw_target = match.group(1)
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = unquote(raw_target.split("#", 1)[0])
        if target:
            yield target


def test_relative_markdown_links_resolve():
    """Fail with a full list of any broken relative markdown links."""
    broken = []
    for md_path in _markdown_files():
        for target in _relative_link_targets(md_path):
            resolved = (md_path.parent / target).resolve()
            try:
                resolved.relative_to(REPO_ROOT.resolve())
            except ValueError:
                # Cross-repo reference (e.g. a sibling checkout); out of scope.
                continue
            if not resolved.exists():
                broken.append(
                    f"{md_path.relative_to(REPO_ROOT)} -> {target}"
                )
    assert not broken, (
        "Broken relative markdown links:\n" + "\n".join(broken)
    )
