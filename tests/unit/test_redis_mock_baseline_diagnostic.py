"""
tests/unit/test_redis_mock_baseline_diagnostic.py

Phase 27 / Plan 27-02 / Task 2 — D-22 diagnostic regression gate.

Two tests:
  1. Static guard: the 4 known-failing unit-test files (per v1.6 Phase 24
     SUMMARY) carry `@pytest.mark.uses_redis` at file level after rollout.
  2. Subprocess regression gate: running pytest against the 4 marked files
     must NOT emit `redis.exceptions.ConnectionError` or
     `ConnectionError: Error 111 connecting to Redis` (the auto-applied
     redis_mock fixture intercepts the connection path).

Note (D-22 caveat documented in 27-02-DIAGNOSTIC.md): if the test host has
a live Redis on localhost:6379, the pre-rollout baseline may already report
0 Redis-mode failures because the live server serves the calls. The marker
rollout still matters — it ensures isolation when Redis is offline (CI) and
forecloses cross-test state-bleed from a shared Redis instance.

The openai-SDK-drift failures (APIError missing 'request') are documented as
an orthogonal v1.8+ todo (STATE.md); this diagnostic does NOT assert they
are gone.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import subprocess
import sys
from pathlib import Path

import pytest

# This test file itself touches Redis indirectly via subprocess — auto-attach
# the fixture so the parent process's monkeypatch state is consistent (the
# subprocess gets its own clean state).
pytestmark = pytest.mark.uses_redis


TARGET_FILES = (
    "tests/unit/test_agent_pipeline_refactor.py",
    "tests/unit/test_agent_sse.py",
    "tests/unit/test_feedback_ab_forward.py",
    "tests/unit/test_pipeline_coverage.py",
)


# -----------------------------------------------------------------------------
# Test 1 — static guard: marker applied to all 4 target files
# -----------------------------------------------------------------------------
def test_marker_applied_to_known_failing_files() -> None:
    """Each of the 4 v1.6-Phase-24-known Redis-baseline-failure files must
    carry `@pytest.mark.uses_redis` (file-level pytestmark, class-level
    marker, or per-test decorator). The fixture is auto-attached by the
    conftest.py:pytest_collection_modifyitems hook from plan 27-00."""
    missing: list[str] = []
    for rel_path in TARGET_FILES:
        path = Path(rel_path)
        assert path.is_file(), f"Target file missing: {rel_path}"
        body = path.read_text(encoding="utf-8")
        if "uses_redis" not in body:
            missing.append(rel_path)
    assert not missing, (
        "These files are missing the @pytest.mark.uses_redis marker rollout: "
        + ", ".join(missing)
    )


# -----------------------------------------------------------------------------
# Test 2 — subprocess regression gate: no Redis-ConnectionError in marked files
# -----------------------------------------------------------------------------
@pytest.mark.timeout(300)
def test_no_pre_existing_redis_connection_error_in_marked_files() -> None:
    """Spawn `python -m pytest <4 files>` as a subprocess and assert the
    output contains NO `redis.exceptions.ConnectionError` or `Error 111`
    strings. This validates that the marker rollout closes the Redis-mode
    failure class — even if a live Redis on localhost:6379 would mask it,
    the marker also enforces isolation (no real-Redis state-bleed).

    Subprocess pattern follows tests/integration/audit/* conventions —
    explicit narrow `subprocess.TimeoutExpired` + `OSError` exception
    handling, no bare except (CLAUDE.md ERR-01).

    NOTE: uses `sys.executable -m pytest` instead of `uv run pytest` so the
    diagnostic works in CI runners that don't have the `uv` binary on PATH
    (CI installs deps via `pip install -r requirements*.txt` per .github/
    workflows/ci.yml). Local dev still works because `sys.executable` resolves
    to the venv's python regardless of whether it was created by uv or venv."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *TARGET_FILES,
        "--timeout",
        "30",
        "-q",
        "--no-header",
        "--tb=line",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Subprocess pytest run timed out after 240s: {exc}")
    except OSError as exc:
        pytest.fail(f"Subprocess could not be launched (env issue): {exc}")

    combined = (result.stdout or "") + (result.stderr or "")
    forbidden_patterns = (
        "redis.exceptions.ConnectionError",
        "ConnectionError: Error 111",
        "Cannot connect to Redis",
    )
    hits = [pat for pat in forbidden_patterns if pat in combined]
    if hits:
        # Echo the relevant lines so the diagnostic captures real evidence.
        relevant = "\n".join(
            line
            for line in combined.splitlines()
            if any(pat in line for pat in hits)
        )
        sys.stderr.write(
            f"[27-02 diagnostic] Forbidden Redis-mode error patterns "
            f"found in subprocess output:\n{relevant}\n"
        )
        pytest.fail(
            "Marker rollout did NOT close Redis-mode failures. "
            f"Found patterns: {hits}"
        )
