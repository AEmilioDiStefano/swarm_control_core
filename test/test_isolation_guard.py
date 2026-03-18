from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "swarm_control_core"
LAUNCH_ROOT = REPO_ROOT / "launch"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
CONFIG_ROOT = REPO_ROOT / "config"
PACKAGE_XML = REPO_ROOT / "package.xml"
SETUP_PY = REPO_ROOT / "setup.py"
TARGET_TOKEN_RE = re.compile(r"\bswarm_control\b")

TEXT_SUFFIXES = {
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
    ".cfg",
    ".ini",
    ".js",
}


def _iter_python_files():
    for root in (PACKAGE_ROOT, LAUNCH_ROOT):
        if not root.exists():
            continue
        yield from root.rglob("*.py")


def _collect_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(str(alias.name or ""))
        elif isinstance(node, ast.ImportFrom):
            imports.append(str(node.module or ""))
    return imports


def _iter_runtime_text_files():
    roots = (PACKAGE_ROOT, LAUNCH_ROOT, SCRIPTS_ROOT, CONFIG_ROOT)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def test_no_runtime_imports_from_proprietary_package():
    violations = []
    for path in _iter_python_files():
        rel = path.relative_to(REPO_ROOT)
        for imp in _collect_imports(path):
            if imp == "swarm_control" or imp.startswith("swarm_control."):
                violations.append(f"{rel}: {imp}")
    assert not violations, "Cross-package import(s) found:\n" + "\n".join(violations)


def test_no_package_metadata_dependency_on_proprietary_package():
    pkg = PACKAGE_XML.read_text(encoding="utf-8")
    dep_re = re.compile(
        r"<(?:depend|exec_depend|build_depend|buildtool_depend|test_depend)>\s*swarm_control\s*</",
        re.IGNORECASE,
    )
    assert dep_re.search(pkg) is None, "package.xml declares dependency on swarm_control"

    setup_txt = SETUP_PY.read_text(encoding="utf-8")
    setup_dep_re = re.compile(r"(?<![A-Za-z0-9_])swarm_control(?![A-Za-z0-9_])")
    assert setup_dep_re.search(setup_txt) is None, "setup.py references swarm_control"


def test_no_direct_script_invocation_of_proprietary_package():
    """
    Compatibility kill-pattern regexes (e.g. .*swarm_control.*) are allowed.
    Direct runtime invocations are not.
    """
    bad = []
    direct_patterns = [
        re.compile(r"\bros2\s+run\s+swarm_control\b"),
        re.compile(r"\bros2\s+launch\s+swarm_control\b"),
        re.compile(r"/src/swarm_control/scripts/"),
    ]
    for path in SCRIPTS_ROOT.rglob("*.sh"):
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pat in direct_patterns:
                if pat.search(line):
                    bad.append(f"{rel}:{lineno}: {line.strip()}")
    assert not bad, "Direct proprietary package invocation(s) found:\n" + "\n".join(bad)


def test_no_cross_package_runtime_tokens_outside_compat_patterns():
    """
    Catch stale runtime references to the proprietary package name.
    Compatibility kill-pattern regexes in scripts are allowed.
    """
    bad = []
    compat_allow_re = re.compile(r"\.\*swarm_control\.\*")
    for path in _iter_runtime_text_files():
        rel = path.relative_to(REPO_ROOT)
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if TARGET_TOKEN_RE.search(line) is None:
                continue
            if _is_under(path, SCRIPTS_ROOT) and compat_allow_re.search(line):
                continue
            bad.append(f"{rel}:{lineno}: {line.strip()}")
    assert not bad, "Cross-package runtime token(s) found:\n" + "\n".join(bad)
