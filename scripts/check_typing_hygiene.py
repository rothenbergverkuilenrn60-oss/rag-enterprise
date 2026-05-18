#!/usr/bin/env python3
"""Typing hygiene enforcement script (D1 + D3 from plan-eng-review).

Invariant 1 (D1 — stub parity):
    All *-stubs and types-* lines in pyproject.toml [dependency-groups].dev
    must be present in requirements-dev.txt (and vice versa) so CI's pip-based
    install path always sees the same stubs as the local uv-based path.

Invariant 2 (D3 — bare-ignore ban):
    No unbracketed mypy suppression comment (bare form without an error code)
    may exist in services/, tests/, utils/, config/, scripts/, or controllers/.

Exit codes:
    0  Both invariants pass.
    1  One or more invariants failed (details printed to stderr).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"

# Directories checked for bare ignores (mirrors D-VERIFY-01 MYPY-03 command)
BARE_IGNORE_DIRS = [
    "services",
    "tests",
    "utils",
    "config",
    "scripts",
    "controllers",
]

# Pattern matching *-stubs and types-* package names (with optional version spec)
_STUB_NAME_RE = re.compile(
    r"""
    (?:^|["'])               # start of line or opening quote
    (                        # capture group: package name + optional version
      (?:
        [\w.-]+-stubs        # *-stubs packages (e.g. asyncpg-stubs)
        | types-[\w.-]+      # types-* packages (e.g. types-requests)
      )
      [^"'\s,\]]*            # optional version specifier
    )
    """,
    re.VERBOSE,
)

# Matches bare unbracketed mypy suppression comments (coded form requires brackets)
_BARE_IGNORE_RE = re.compile(r"# type" + r": ignore(?!\[)")


def _extract_stubs_from_pyproject(content: str) -> set[str]:
    """Extract normalized stub package names from pyproject.toml."""
    in_dev_group = False
    stubs: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        # Detect entry into [dependency-groups] dev section
        if re.match(r"^\[dependency-groups\]", stripped):
            in_dev_group = False  # reset; look for dev = [
        if in_dev_group or re.match(r"^dev\s*=\s*\[", stripped):
            in_dev_group = True
            m = _STUB_NAME_RE.search(line)
            if m:
                # Normalize: lowercase, strip version specifier
                raw = m.group(1)
                name = re.split(r"[><=!~]", raw)[0].strip().lower()
                stubs.add(name)
        # Exit dev group on new section header
        if stripped.startswith("[") and not stripped.startswith("[dependency-groups]"):
            if in_dev_group and stripped != "[dependency-groups]":
                in_dev_group = False
    return stubs


def _extract_stubs_from_requirements(content: str) -> set[str]:
    """Extract normalized stub package names from requirements-dev.txt."""
    stubs: set[str] = set()
    for line in content.splitlines():
        # Strip inline comments and whitespace
        clean = line.split("#")[0].strip()
        if not clean:
            continue
        m = _STUB_NAME_RE.match(clean)
        if m:
            raw = m.group(1)
            name = re.split(r"[><=!~]", raw)[0].strip().lower()
            stubs.add(name)
    return stubs


def check_stub_parity() -> list[str]:
    """Invariant 1: pyproject.toml and requirements-dev.txt stub sets must match."""
    errors: list[str] = []
    if not PYPROJECT.exists():
        errors.append(f"MISSING: {PYPROJECT}")
        return errors
    if not REQUIREMENTS_DEV.exists():
        errors.append(f"MISSING: {REQUIREMENTS_DEV}")
        return errors

    pyproject_stubs = _extract_stubs_from_pyproject(PYPROJECT.read_text())
    req_stubs = _extract_stubs_from_requirements(REQUIREMENTS_DEV.read_text())

    only_in_pyproject = pyproject_stubs - req_stubs
    only_in_requirements = req_stubs - pyproject_stubs

    if only_in_pyproject:
        errors.append(
            "Stubs in pyproject.toml [dependency-groups].dev but NOT in requirements-dev.txt:\n"
            + "\n".join(f"  + {s}" for s in sorted(only_in_pyproject))
            + "\nFix: add the missing line(s) to requirements-dev.txt"
        )
    if only_in_requirements:
        errors.append(
            "Stubs in requirements-dev.txt but NOT in pyproject.toml [dependency-groups].dev:\n"
            + "\n".join(f"  + {s}" for s in sorted(only_in_requirements))
            + "\nFix: add the missing line(s) to pyproject.toml [dependency-groups].dev"
        )
    return errors


def check_bare_ignores() -> list[str]:
    """Invariant 2: no unbracketed mypy suppression comment in source dirs."""
    errors: list[str] = []
    matches: list[str] = []

    # Exclude this script itself to avoid false positives from docstrings/comments
    _self = Path(__file__).resolve()

    for dir_name in BARE_IGNORE_DIRS:
        dir_path = REPO_ROOT / dir_name
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if ".pyc" in str(py_file):
                continue
            if py_file.resolve() == _self:
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _BARE_IGNORE_RE.search(line):
                    rel = py_file.relative_to(REPO_ROOT)
                    matches.append(f"  {rel}:{lineno}: {line.strip()}")

    if matches:
        errors.append(
            "Bare unbracketed mypy suppression found — use coded form '[code]  # why: ...' instead:\n"
            + "\n".join(matches)
        )
    return errors


def main() -> int:
    all_errors: list[str] = []

    # Invariant 1
    parity_errors = check_stub_parity()
    if parity_errors:
        print("[FAIL] Invariant 1 — stub parity:", file=sys.stderr)
        for e in parity_errors:
            print(e, file=sys.stderr)
        all_errors.extend(parity_errors)
    else:
        print("[PASS] Invariant 1 — stub parity: pyproject.toml and requirements-dev.txt match")

    # Invariant 2
    bare_errors = check_bare_ignores()
    if bare_errors:
        print("[FAIL] Invariant 2 — bare-ignore ban:", file=sys.stderr)
        for e in bare_errors:
            print(e, file=sys.stderr)
        all_errors.extend(bare_errors)
    else:
        print("[PASS] Invariant 2 — bare-ignore ban: no unbracketed mypy suppressions found in source dirs")

    if all_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
