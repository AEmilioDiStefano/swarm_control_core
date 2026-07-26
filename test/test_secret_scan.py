#!/usr/bin/env python3
"""
SEC-08: fail CI if a secret appears to be committed to the repository.

This is a high-signal scan over git-tracked text files, not a full DLP system.
It targets the mistakes that actually leak swarm credentials: pasted private
keys, hard-coded TURN/auth secrets, and real-looking passwords in tracked
files. Documentation placeholders and generated fixtures are allow-listed by
shape (angle-bracket markers, `example.*`, `changeme`, obvious dummies) so the
gate stays true-positive-oriented and does not train developers to ignore it.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Binary/asset extensions and paths we never scan as text.
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".whl",
    ".pyc", ".so", ".woff", ".woff2", ".ttf", ".mp4", ".bin",
}
SKIP_PATH_PARTS = {"build", "install", "log", "__pycache__", ".git"}

# High-signal secret patterns: (name, compiled regex).
SECRET_PATTERNS = [
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_api_key_assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9/+_-]{20,}['\"]")),
    ("turn_static_secret_assignment", re.compile(
        r"(?i)(?:static[_-]auth[_-]secret|turn[_-]?secret)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
    ("hardcoded_password_assignment", re.compile(
        r"(?i)(?:password|passwd|passphrase)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]

# Allow-list: a match is ignored if the matched line also contains any of
# these markers, i.e. it is a documented placeholder or a variable reference
# rather than a literal secret.
PLACEHOLDER_MARKERS = [
    "<", ">", "${", "$(", '="$', "='$", "example.com", "example.net",
    "example.org", "changeme", "change_me", "replace_with", "your-", "your_",
    "placeholder", "dummy", "redacted", "xxxxx", "test-secret", "testsecret",
    "unit-test", "REPLACE", "TODO", "os.environ", "getenv", "getpass",
    "read -", "prompt",
]

# Files known to legitimately contain secret-shaped test/dummy material.
ALLOWLISTED_FILES = {
    "test/test_secret_scan.py",
}


def _candidate_relpaths():
    """
    Return repo-relative paths to scan.

    Prefer git-tracked files (precise "committed secret" semantics). Fall back
    to a filesystem walk when git is unavailable or refuses to run — e.g. CI
    containers where `git ls-files` exits 128 on dubious-ownership — so the
    gate never silently no-ops.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        pass

    walked = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if set(rel.parts) & SKIP_PATH_PARTS:
            continue
        walked.append(str(rel))
    return walked


def _tracked_files():
    for rel in _candidate_relpaths():
        p = REPO_ROOT / rel
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        if set(Path(rel).parts) & SKIP_PATH_PARTS:
            continue
        if rel in ALLOWLISTED_FILES:
            continue
        yield rel, p


def _is_placeholder(line: str) -> bool:
    return any(marker in line for marker in PLACEHOLDER_MARKERS)


def test_no_committed_secrets():
    findings = []
    for rel, path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line) and not _is_placeholder(line):
                    findings.append(f"{rel}:{lineno} [{name}] {line.strip()[:120]}")
    assert not findings, "Possible committed secret(s):\n" + "\n".join(findings)
