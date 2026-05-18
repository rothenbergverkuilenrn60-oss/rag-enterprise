# Phase 33: Autouse-Mock Opt-Out + Order-Dependent Failures - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 33-autouse-mock-opt-out-flaky-failures
**Areas discussed:** Plan structure, TEST-09 mock-shape parity, --random-order plugin choice, TEST-08 canary scope

---

## Area A — Plan structure: single vs split

| Option | Description | Selected |
|--------|-------------|----------|
| A) Split 33-00 (TEST-08) + 33-01 (TEST-09) same wave (Recommended) | Parallel-safe (zero file overlap); 2 atomic lineages; each plan ~3-4 tasks. | ✓ |
| B) Single 33-00 covering both | 1 lineage; simpler tracking; loses parallelism. | |
| C) Sequence 33-00 (TEST-09) → 33-01 (TEST-08) in waves 1+2 | Fix unit suite first; slowest, 2 waves. | |

**User's choice:** Split into two parallel-safe plans in Wave 1.
**Notes:** Zero file overlap confirmed during analyze step — integration/conftest.py + pytest.ini (marker only) + docs vs tests/conftest.py + unit test files + new plugin dep. Plans can run in parallel worktrees.

---

## Area B — TEST-09 mock-shape parity

| Option | Description | Selected |
|--------|-------------|----------|
| A) Align mocks to canonical embed_batch (Recommended) | Update test mocks to patch `embed_batch` directly; mirrors current production API; mock-at-consumer preserved. | ✓ |
| B) Compat shim — embed_one wraps embed_batch | Add `embed_one(text)` method that wraps `embed_batch([text])[0]`. Tests keep old shape. Production debt smell. | |
| C) Mixed — align consumer mocks + shim for genuine single-use callsites | Researcher inspects callsites; conditional. Adds research scope. | |

**User's choice:** Align mocks to canonical `embed_batch` (no shim).
**Notes:** D-MOCK-01 makes researcher verify production callers genuinely use batch (no stragglers). If straggler exists, executor surfaces — does NOT silently shim.

---

## Area C — `--random-order` plugin choice

| Option | Description | Selected |
|--------|-------------|----------|
| A) pytest-randomly (Recommended) | ~1M downloads/month; seed in pytest header; minimal config; faker integration. | ✓ |
| B) pytest-random-order | More bucket-control knobs; explicit `--random-order-seed` flag. Smaller community. | |
| C) Custom shuffler in conftest.py | Zero new deps; reinvents wheel. Against Layer 1 (built-in/established) principle. | |

**User's choice:** pytest-randomly.
**Notes:** D-PLUGIN-01 pins ≥3.16.0; dual-write to pyproject.toml + requirements-dev.txt per Phase 32 CI-gap carry-forward. D-SEEDS-01 fixes 3 acceptance seeds (12345, 67890, 99999).

---

## Area D — TEST-08 canary scope

| Option | Description | Selected |
|--------|-------------|----------|
| A) Minimal canary only (Recommended) | 1 new test ~30 LOC; instantiates real classes; asserts shapes. Skipped by default CI filter. | ✓ |
| B) Minimal + promote existing test (extractor_e2e) | Same as A plus retag 1 real-pipeline test. Heavier; bigger flake surface. | |
| C) Promote-only | Skip minimal canary. Risks silent opt-out failure if existing test passes for unrelated reasons. | |

**User's choice:** Minimal canary only.
**Notes:** D-CANARY-01 enumerates exact assertions (1024-d vector + scalar predict). No existing test promoted. Promotion deferred to future phase if minimal canary surfaces a gap.

---

## Claude's Discretion

- Specific docstring wording for `_mock_local_model_inits` opt-out branch.
- Canary test sync vs async (planner decides based on `HuggingFaceEmbedder.__init__` semantics).
- Order of execution within each plan.

## Deferred Ideas

- Full unit suite random-order hardening (>3 seeds, nightly CI).
- Promote `extractor_e2e` to `@pytest.mark.real_embedder` — reconsider only if minimal canary surfaces gap.
- Broad singleton-tracking infrastructure (decorator-based auto-reset).
- Compat shim for `embed_one` — reconsider only if production callers genuinely need single-shot.
- Adding `pytest-randomly` to CI as default run.
