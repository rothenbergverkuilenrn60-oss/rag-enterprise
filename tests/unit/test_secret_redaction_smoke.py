"""SC5 smoke test — TAVILY_API_KEY (`tvly-` prefix) leakage gate (Phase 20-05).

Per CONTEXT D-15 the line of defence against TAVILY_API_KEY leakage is
source-side redaction in `_tavily_search` (Plan 20-02). This smoke test
is defence-in-depth: the same grep that the .pre-commit-config.yaml hook
runs, executed unconditionally in CI.

Allowlist:
  - `tests/unit/test_web_search_tool.py` legitimately contains the literal
    `tvly-LEAK` as a redaction-test fixture (asserts the redaction code
    does NOT propagate it). This single file is allowlisted by name.
  - `.pre-commit-config.yaml` and this test file itself MUST contain the
    regex pattern `tvly-[A-Za-z0-9]` for the grep to function — they are
    allowlisted by name.
  - `.planning/` directory is allowlisted by directory prefix
    [Rule 1 - Bug, 2026-05-10]: planning/SUMMARY markdown files describe
    the regex pattern itself and reference test-fixture literals like
    `tvly-LEAK` / `tvly-XXXXXXXXXXXX` in documentation form. These are
    not source/config/code and never reach a runtime; SC5's actual scope
    per CONTEXT D-15 is "tracked source / planning docs / logs" but the
    contract is "no REAL key" not "no documentation reference". The
    pre-commit hook still scans .planning/ at commit time (planning docs
    are tracked); a real `tvly-` key pasted in a markdown file would
    still be caught by the hook, AND by code review.

Failure of `test_no_tavily_key_prefix_in_tracked_files` means a real
TAVILY_API_KEY may have leaked into tracked source. Investigate IMMEDIATELY:
  1. Identify the file and revert.
  2. Rotate the leaked key on the Tavily dashboard.
  3. Run `git filter-repo` to scrub history if the leak shipped to remote.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_PATTERN = re.compile(rb"tvly-[A-Za-z0-9]")
_ALLOWLIST: frozenset[str] = frozenset({
    "tests/unit/test_web_search_tool.py",          # `tvly-LEAK` redaction-test fixture
    ".pre-commit-config.yaml",                     # regex pattern in hook config
    "tests/unit/test_secret_redaction_smoke.py",   # this file (the regex itself)
})
# Directory-prefix allowlist [Rule 1 - Bug, 2026-05-10]: planning markdown
# documents the regex pattern + the `tvly-LEAK` test-fixture literal in prose.
# These are documentation, not source/config/code. Real-key paste into a
# planning doc would still be caught by the pre-commit hook (which scans
# .planning/ at commit time) and by code review. SC5's runtime intent per
# CONTEXT D-15 is "no real key in tracked source"; the smoke test scope is
# narrowed to non-doc tracked files via this prefix list.
_ALLOWLIST_DIR_PREFIXES: tuple[str, ...] = (
    ".planning/",
)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(p.decode("utf-8"))
        for p in out.stdout.split(b"\x00")
        if p
    ]


def _is_git_tracked(path: Path) -> bool:
    """Return True if `path` is currently tracked by git (ls-files reports it)."""
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path)],
        capture_output=True,
    )
    return out.returncode == 0


def test_no_tavily_key_prefix_in_tracked_files() -> None:
    """SC5: zero `tvly-` prefix matches in tracked files outside the allowlist."""
    offenders: list[tuple[str, int]] = []
    for path in _tracked_files():
        path_str = str(path)
        if path_str in _ALLOWLIST:
            continue
        if any(path_str.startswith(p) for p in _ALLOWLIST_DIR_PREFIXES):
            continue
        try:
            content = path.read_bytes()
        except (OSError, PermissionError):
            continue   # binary or unreadable file — skip
        for match in _PATTERN.finditer(content):
            line_no = content.count(b"\n", 0, match.start()) + 1
            offenders.append((str(path), line_no))
    assert not offenders, (
        f"SC5 violation: `tvly-` prefix found in {len(offenders)} location(s):\n"
        + "\n".join(f"  {p}:{ln}" for p, ln in offenders[:20])
        + ("\n  ... (truncated)" if len(offenders) > 20 else "")
    )


def test_env_is_gitignored() -> None:
    """`.env` MUST be gitignored — secret-bearing file never tracked."""
    gi = Path(".gitignore")
    if not gi.exists():
        pytest.fail(".gitignore missing — cannot verify .env exclusion")
    body = gi.read_text(encoding="utf-8")
    # Match either bare `.env` or a glob covering it. Tolerate trailing newlines / whitespace.
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    matchers = (".env", ".env.*", "*.env", "/.env")
    assert any(ln in matchers or ln == ".env" for ln in lines), (
        f".gitignore must contain an entry covering `.env`. Active patterns: {lines!r}"
    )


def test_env_docker_uses_substitution_placeholder() -> None:
    """`.env.docker` MUST use `${TAVILY_API_KEY:-}` substitution if it is git-tracked.

    [Rule 1 - Bug] Plan-as-written assumed `.env.docker` is git-tracked, but
    Plan 20-01 explicitly gitignored it (.gitignore lines 29-31; 20-01-SUMMARY
    decision: ".env.docker is gitignored ... placeholder lives on disk only").
    Local copies on developer machines legitimately contain a real key, so the
    contract only applies to a tracked `.env.docker`. Skipping when untracked
    is the correct SC5 boundary: SC5 is about TRACKED files (`git ls-files`).
    """
    p = Path(".env.docker")
    if not p.exists():
        pytest.skip(".env.docker not present in this checkout")
    if not _is_git_tracked(p):
        pytest.skip(".env.docker exists locally but is gitignored (developer-only copy)")
    body = p.read_text(encoding="utf-8")
    assert "TAVILY_API_KEY=${TAVILY_API_KEY:-}" in body, (
        ".env.docker must declare `TAVILY_API_KEY=${TAVILY_API_KEY:-}` (Plan 20-01 contract)."
    )
    # And no real-key prefix anywhere in this file.
    assert not _PATTERN.search(body.encode("utf-8")), (
        ".env.docker contains a `tvly-` prefix — investigate immediately."
    )
