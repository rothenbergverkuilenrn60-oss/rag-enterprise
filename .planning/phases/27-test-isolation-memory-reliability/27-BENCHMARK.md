# Phase 27 SC-5 — save_facts batch vs. sequential save_fact

**Last run:** 2026-05-17T07:43:43.991367+00:00
**Trials per loop:** 10
**Facts per batch:** 5
**Floor:** speedup_ms ≥ 80.0ms (RESEARCH expected ~123ms)

## Results

| Metric | Baseline (5× save_fact) | New (1× save_facts) |
|--------|-------------------------|----------------------|
| p50    | 25.31ms    | 5.51ms      |
| p95    | 36.78ms    | 6.02ms      |

**Speedup (p50):** 19.80ms

## Interpretation

* speedup_ms > 0 → batch path is faster (expected).
* speedup_ms < 80.0ms → either a noisy runner (acceptable in CI;
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
