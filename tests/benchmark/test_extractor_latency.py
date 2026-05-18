"""tests/benchmark/test_extractor_latency.py — Phase 27 / TD-05 / SC-5.

Relative latency benchmark: 5× sequential save_fact (the D-12 wrapper path
looped) vs. 1× save_facts([5]) on the SAME branch. Asserts the batch path
is faster by ≥80ms median (RESEARCH expects ~123ms; 80ms gives ~30% margin
for noisy machines).

CI gating policy (plan-checker resolution, plan_specific_notes lines 56-62):
  * The assertion stays HARD inside this file so a green local run is a real
    signal.
  * The benchmark is marked ``@pytest.mark.benchmark`` and the default pytest
    invocation uses ``-m 'not benchmark'`` so CI is not gated on absolute
    latency in untrusted runners.
  * Phase 27 acceptance bar is "benchmark recorded in 27-BENCHMARK.md with the
    4 numbers", NOT "speedup_ms ≥ 80 on every machine". The verifier reads
    27-BENCHMARK.md and accepts if numbers are present + speedup is positive.

Skip-gated on PG_AVAILABLE (Pattern E). The benchmark writes its 4 numbers
+ speedup to ``.planning/phases/27-test-isolation-memory-reliability/27-BENCHMARK.md``
so the verifier can ingest the results from the worktree merge.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.integration,
    pytest.mark.skipif(not PG_AVAILABLE, reason="needs live PostgreSQL"),
]


_TRIALS = 10
_N = 5
# Tolerant floor — RESEARCH §"Latency baseline measurement" expects ~123ms
# speedup; 80ms gives ~30% margin for variance on busy machines.
_SPEEDUP_FLOOR_MS = 80.0

_BENCHMARK_FILE = Path(
    ".planning/phases/27-test-isolation-memory-reliability/27-BENCHMARK.md",
)


def _p95(timings: list[float]) -> float:
    """p95 of a 10-sample list. Index int(0.95 * 10) = 9 — the maximum."""
    return sorted(timings)[int(0.95 * len(timings))] if len(timings) >= 2 else float(
        timings[0]
    )


def _write_benchmark_md(
    baseline_p50: float,
    baseline_p95: float,
    new_p50: float,
    new_p95: float,
    speedup_ms: float,
    trials: int,
    n_facts: int,
) -> None:
    """Record results to 27-BENCHMARK.md. Overwrite-on-each-run (latest wins).

    The verifier ingests this file to validate SC-5 — the assertion below
    is a local-dev tripwire, NOT the CI acceptance gate.
    """
    _BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    content = f"""# Phase 27 SC-5 — save_facts batch vs. sequential save_fact

**Last run:** {timestamp}
**Trials per loop:** {trials}
**Facts per batch:** {n_facts}
**Floor:** speedup_ms ≥ {_SPEEDUP_FLOOR_MS}ms (RESEARCH expected ~123ms)

## Results

| Metric | Baseline (5× save_fact) | New (1× save_facts) |
|--------|-------------------------|----------------------|
| p50    | {baseline_p50:.2f}ms    | {new_p50:.2f}ms      |
| p95    | {baseline_p95:.2f}ms    | {new_p95:.2f}ms      |

**Speedup (p50):** {speedup_ms:.2f}ms

## Interpretation

* speedup_ms > 0 → batch path is faster (expected).
* speedup_ms < {_SPEEDUP_FLOOR_MS}ms → either a noisy runner (acceptable in CI;
  the benchmark is excluded from default `-m 'not benchmark'` runs) OR a
  regression in save_facts/extractor wiring (investigate locally).
* speedup_ms < 0 → batch path is SLOWER than the loop. Investigate
  immediately — likely a regression in save_facts bulk dedupe or executemany
  shape.

## CI gating

* Hard assertion lives in tests/benchmark/test_extractor_latency.py.
* Default `pytest` invocation uses `-m 'not benchmark'` → this file is NOT
  in the CI gate.
* Phase 27 verifier accepts the phase if this file exists and `speedup_ms > 0`.
"""
    _BENCHMARK_FILE.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_save_facts_batch_beats_singular_loop_by_at_least_80ms(
    pg_pool: Any,
    app_factory: Any,
    embedder_or_mock: Any,  # provides real or mock embedder
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loop A: 5× sequential save_fact (D-12 wrapper path).
    Loop B: 1× save_facts([5]).
    Assert median(A) - median(B) ≥ 80ms when running against the REAL bge-m3
    embedder (where embed_batch(N=5) saves ~5× the embedder cost over N×embed_one).

    When the embedder is the function-scoped MagicMock (CI default — no bge-m3
    model present), embeds are ~free and the only delta is PG RTT
    consolidation (~20ms on a local pgvector). In that case the floor relaxes
    to "speedup_ms > 0" because the absolute saving is a function of the
    embedder's real cost, not the batch wiring's correctness.

    Either way, the 4 numbers + speedup are recorded in 27-BENCHMARK.md and
    that's the artifact the Phase 27 verifier ingests.
    """
    # Detect mock-vs-real embedder via the MagicMock spec. The fixture returns
    # the singleton's actual embedder when bge-m3 exists; otherwise returns a
    # MagicMock(spec=None) instance.
    from unittest.mock import MagicMock
    embedder_is_mock = isinstance(embedder_or_mock, MagicMock)
    # Build isolated app — resets memory singleton.
    app = app_factory()
    assert app is not None

    from services.memory.memory_service import get_memory_service
    from utils.models import ExtractedFact

    mem = get_memory_service()
    ltm = mem._long
    ltm._pool = pg_pool
    await ltm._create_tables()

    # Build distinct fact strings (use trial-suffix so each trial inserts
    # fresh rows after we DELETE between trials).
    def _build_facts(trial: int) -> list[ExtractedFact]:
        return [
            ExtractedFact(
                fact=f"benchmark trial {trial} fact {i} unique-suffix",
                category="recurring_topics",
                importance=0.5,
            )
            for i in range(_N)
        ]

    async def _wipe(conn: Any) -> None:
        await conn.execute(
            "DELETE FROM long_term_facts WHERE user_id = 'bench_u'",
        )

    # Loop A — baseline: 5× sequential save_fact via the D-12 wrapper path.
    baseline_timings_ms: list[float] = []
    for trial in range(_TRIALS):
        async with pg_pool.acquire() as conn:
            await _wipe(conn)
        facts = _build_facts(trial)
        t0 = time.perf_counter()
        for f in facts:
            await ltm.save_fact(
                user_id="bench_u",
                tenant_id="bench_t",
                fact=f.fact,
                importance=f.importance,
            )
        baseline_timings_ms.append((time.perf_counter() - t0) * 1000)

    # Loop B — new: 1× save_facts([5]).
    new_timings_ms: list[float] = []
    for trial in range(_TRIALS, _TRIALS * 2):
        async with pg_pool.acquire() as conn:
            await _wipe(conn)
        facts = _build_facts(trial)
        t0 = time.perf_counter()
        await ltm.save_facts(facts, user_id="bench_u", tenant_id="bench_t")
        new_timings_ms.append((time.perf_counter() - t0) * 1000)

    baseline_p50 = statistics.median(baseline_timings_ms)
    baseline_p95 = _p95(baseline_timings_ms)
    new_p50 = statistics.median(new_timings_ms)
    new_p95 = _p95(new_timings_ms)
    speedup_ms = baseline_p50 - new_p50

    # Record to 27-BENCHMARK.md (the verifier reads this file).
    _write_benchmark_md(
        baseline_p50=baseline_p50,
        baseline_p95=baseline_p95,
        new_p50=new_p50,
        new_p95=new_p95,
        speedup_ms=speedup_ms,
        trials=_TRIALS,
        n_facts=_N,
    )

    # Hard assertion — local-dev tripwire only. CI uses `-m 'not benchmark'`.
    # Mock embedder: relax to "positive speedup" (embeds are ~free; the only
    # delta is PG RTT consolidation, which varies by ~20ms on a local pgvector).
    # Real embedder: enforce the 80ms tolerant floor (RESEARCH expects ~123ms).
    floor = 0.0 if embedder_is_mock else _SPEEDUP_FLOOR_MS
    assert speedup_ms > floor, (
        f"SC-5 speedup floor breach: speedup_ms={speedup_ms:.2f} <= "
        f"{floor}ms (embedder_is_mock={embedder_is_mock}). "
        f"baseline_p50={baseline_p50:.2f}ms, new_p50={new_p50:.2f}ms. "
        f"See 27-BENCHMARK.md for full numbers; investigate save_facts "
        f"wiring if speedup <= 0 (regression — batch path should never be "
        f"slower than the loop)."
    )
