---
phase: 33-autouse-mock-opt-out-flaky-failures
verified: 2026-05-18T00:00:00Z
status: passed
score: 4/4 ROADMAP success criteria; 6/6 TEST-08 gates; 9/9 TEST-09 gates (1 deferred-legitimate)
overrides_applied: 0
re_verification: null
deferred:
  - truth: "TEST-09h integration baseline machine-verifiable on this WSL host"
    addressed_in: "Phase 34 (TEST-10/TEST-11) or v1.10 backlog"
    evidence: "Pre-existing /app PermissionError in eval/models.py:55 — reproduced at pre-phase commit 5c1905b before any plan-33 edit; eval/models.py untouched by phase 33; collection error happens at module-import time before pytest reads conftest.py, so it cannot be caused by phase-33 changes (pytest-randomly, _reset_tool_registry, embed_batch mock)."
human_verification:
  - test: "Real bge-m3 + bge-m3-rerank canary on PG host"
    expected: "uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q → 1 passed (not 1 skipped)"
    why_human: "Requires $APP_MODEL_DIR/BAAI/bge-m3 + bge-m3-rerank model files present on PG host; WSL verifier host lacks them. Already declared in 33-VALIDATION.md §Manual-Only Verifications."
---

# Phase 33: Autouse-Mock Opt-Out + Order-Dependent Failures — Verification Report

**Phase Goal:** Restore test-infra correctness on two fronts that v1.8 left unbalanced — real-embedder escape hatch from the autouse mock + kill 7 order-dependent unit failures rooted in registry-singleton pollution + `embed_one`/`embed_batch` mock-shape drift.
**Verified:** 2026-05-18
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### ROADMAP Success Criteria

| # | Criterion | Verdict | Rationale |
|---|-----------|---------|-----------|
| 1 | `@pytest.mark.real_embedder` registered + autouse fixture early-returns when marker present + canary integration test exists | VERIFIED | pytest.ini:14 registers marker; `uv run pytest --markers` lists it; tests/integration/conftest.py:55-59 calls `request.node.get_closest_marker("real_embedder")`; tests/integration/test_real_embedder_canary.py (59 LOC) exists; canary runs cleanly (1 skipped on WSL, 1 passed on PG host per plan-doc) |
| 2 | Marker behavior + opt-out documented in docs/RUNBOOK.md test-infra section | VERIFIED | docs/RUNBOOK.md:186 `## Test Infrastructure` + 209 `### Real-embedder opt-out` both present |
| 3 | Unit suite passes under `pytest -p randomly --randomly-seed=<fixed>` for 3 seeds; 7 named failures green every seed | VERIFIED | Seeds 12345/67890/99999 all report `1251 passed, 2 skipped, 4 deselected, 0 failed` (OCR Cluster C deselected per RESEARCH §Q2 deferral); 7 named failures + parametrized children = 16/16 sub-tests pass; runtime 19.15–20.00s (≤ 21s × 1.05) |
| 4 | Registry singletons reset via fixture in tests/conftest.py; `embed_one`/`embed_batch` consumer-path mocks shape-consistent | VERIFIED | tests/conftest.py:400-467 `_reset_tool_registry` autouse function-scope fixture with D1 idempotent guard (line 461) + D2 pkgutil walk (line 419) + `>= 4` sentinel (line 443); tests/unit/test_memory_service_extra.py:238-241 supplies both `embed_one` AND `embed_batch` AsyncMocks matching `services/memory/memory_service.py:640` (`embeddings = list(await embedder.embed_batch(texts))`) |

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T1 | Marker registered + discoverable | VERIFIED | `grep -q 'real_embedder:' pytest.ini` → match line 14; `uv run pytest --markers \| grep real_embedder` → 1 hit |
| T2 | Autouse mock honors opt-out | VERIFIED | `grep 'get_closest_marker("real_embedder")' tests/integration/conftest.py` → match line 55; opt-out branch yields-and-returns before patch.object block |
| T3 | Canary integration test exists | VERIFIED | tests/integration/test_real_embedder_canary.py present, 59 LOC, mypy --strict clean per 33-00 self-check |
| T4 | Canary skips/passes cleanly (env-dependent) | VERIFIED | `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → `1 skipped in 0.07s` (bge-m3 absent on WSL host); skipif precondition correctly routes through to skipped state, not error |
| T5 | RUNBOOK docs section exists | VERIFIED | `grep '^## Test Infrastructure' docs/RUNBOOK.md` → line 186; `grep '^### Real-embedder opt-out' docs/RUNBOOK.md` → line 209 |
| T6 | pytest-randomly dual-written + installed | VERIFIED | pyproject.toml:89 + requirements-dev.txt:14 both reference `pytest-randomly>=3.16.0`; `importlib.metadata.version('pytest-randomly')` → `4.1.0` |
| T7 | Registry reset fixture lands in tests/conftest.py | VERIFIED | tests/conftest.py:400 `@pytest.fixture(autouse=True) def _reset_tool_registry()`; D1 guard at line 461 (`if cls.name not in reg.list()`); D2 pkgutil walk at line 419 + `>= 4` sentinel at line 443 |
| T8 | 7 named failures + parametrized children green | VERIFIED | `uv run pytest <7 node-ids> -q` → `16 passed, 23 warnings in 1.07s` |
| T9 | 3 acceptance seeds green | VERIFIED | Seed 12345: 1251p/2s/4d/20.00s; Seed 67890: 1251p/2s/4d/19.63s; Seed 99999: 1251p/2s/4d/19.15s |
| T10 | Unit-suite runtime non-regression (TEST-09i) | VERIFIED | All 3 seed runs ≤ 22.05s ceiling (1.05× Phase 32 ~21s baseline); slowest seed 20.00s |
| T11 | Mock-shape parity matches production consumer | VERIFIED | tests/unit/test_memory_service_extra.py:238-241 provides both AsyncMock shapes; services/memory/memory_service.py:640 calls `embed_batch(texts)`; mock signature now mirrors v1.7 batch API |
| T12 | Phase 32 typing-hygiene carry-forward holds | VERIFIED | `uv run python scripts/check_typing_hygiene.py` → `[PASS] Invariant 1` + `[PASS] Invariant 2`; `git diff 5c1905b..HEAD -- '*.py' \| grep '^+.*type: ignore'` → 0 hits (no new ignores added in phase 33) |

**Score:** 12/12 truths verified

---

## Required Artifacts (Three-Level Check)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pytest.ini` | `real_embedder:` marker entry | VERIFIED | Line 14, exists + substantive + wired via pytest --markers discovery |
| `tests/integration/conftest.py` | opt-out branch with `get_closest_marker("real_embedder")` | VERIFIED | Line 55, exists + substantive + wired (autouse fixture body) |
| `tests/integration/test_real_embedder_canary.py` | new canary, ~30 LOC | VERIFIED | 59 LOC (slightly above estimate, includes skipif + async test); marker-stacked correctly |
| `docs/RUNBOOK.md` | new `## Test Infrastructure` + `### Real-embedder opt-out` | VERIFIED | Lines 186, 209 present |
| `pyproject.toml` | `pytest-randomly>=3.16.0` in [dependency-groups].dev | VERIFIED | Line 89 |
| `requirements-dev.txt` | mirror of pytest-randomly | VERIFIED | Line 14 |
| `tests/conftest.py` | `_reset_tool_registry` autouse fixture + D1 guard + D2 pkgutil/sentinel | VERIFIED | Lines 400-467, all three hardenings present and grep-confirmed |
| `tests/unit/test_memory_service_extra.py` | embed_batch parity mock | VERIFIED | Lines 238-241; +22/-2 (deviation justified — see below) |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| autouse fixture | marker registry | `request.node.get_closest_marker("real_embedder")` | WIRED | conftest.py:55 reads marker; pytest.ini:14 declares it |
| `_reset_tool_registry` fixture | `services.agent.tools.registry._registry` | `_reg._registry = None` + `reg.register(cls)` guard | WIRED | tests/conftest.py:451, 462; registry singleton resets via factory `get_tool_registry()` |
| mock-at-consumer | `services.memory.memory_service.get_embedder` | monkeypatch.setattr | WIRED | Line 243 patches consumer path (v1.3 D-mock convention); embedder.embed_batch returns `[[float]]` matching `memory_service.py:640` |
| pytest-randomly | pytest plugin auto-discovery | install via uv add --dev | WIRED | `uv run python -c "import pytest_randomly"` succeeds; CLI `-p randomly --randomly-seed=N` accepted in all 3 seed runs |

---

## Data-Flow Trace

| Artifact | Behavior | Source | Real Data Flows | Status |
|----------|----------|--------|-----------------|--------|
| `_reset_tool_registry` | populates `_registry` with 4 tool classes | pkgutil.iter_modules(services.agent.tools) → BaseTool subclasses | YES — 4 concrete tool classes resolved each test invocation (RetrieveTool, RefinedRetrieveTool, WebSearchTool, RecallTool); sentinel `>= 4` enforces it | FLOWING |
| canary test | `HuggingFaceEmbedder.encode(["hello"])` | real bge-m3 model load when present | Conditional — skipped on WSL (no models); flows on PG host per 33-00 SUMMARY | FLOWING (env-conditional) |
| `embed_batch` mock | `[[0.1] * 1024]` | AsyncMock | YES — production callsite at memory_service.py:640 receives list[list[float]] of correct outer/inner shape | FLOWING |

---

## Gate Matrix — TEST-08 (Plan 33-00)

| Gate | Authoritative Command | Result | Status |
|------|------------------------|--------|--------|
| TEST-08a | `grep -q 'real_embedder:' pytest.ini` | pytest.ini:14 match | PASS |
| TEST-08b | `grep -q 'get_closest_marker("real_embedder")' tests/integration/conftest.py` | conftest.py:55 match | PASS |
| TEST-08c | `test -f tests/integration/test_real_embedder_canary.py` | 59 LOC file present | PASS |
| TEST-08d | `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → 1 skipped OR 1 passed | `1 skipped in 0.07s` | PASS |
| TEST-08e | `grep -q '^## Test Infrastructure' docs/RUNBOOK.md` | line 186 match | PASS |
| TEST-08f | integration baseline `integration and not real_llm and not real_embedder and not benchmark` matches Phase 32 close 31p/9f/1s/3e | Actual: 33p/7f/1s/3e (with `--ignore=tests/integration/test_ragas_eval.py` for pre-existing /app PermissionError); **net improvement vs anchor** (+2 passes, −2 failures); failures are Phase 34 sentinel-drift candidates (TEST-10/11), pre-existing | PASS |

**Plus Phase 32 typing-hygiene gate:** PASS (`scripts/check_typing_hygiene.py` → both invariants green).

---

## Gate Matrix — TEST-09 (Plan 33-01)

| Gate | Authoritative Command | Result | Status |
|------|------------------------|--------|--------|
| TEST-09a | `uv pip show pytest-randomly` Version ≥ 3.16 | `4.1.0` via `importlib.metadata` (uv pip show reports not-found because virtualenv-shadowed query; verified import succeeds) | PASS |
| TEST-09b | `grep '^pytest-randomly' requirements-dev.txt` | line 14 match | PASS |
| TEST-09c | `grep '_reset_tool_registry' tests/conftest.py` | line 400 match, plus D1 guard line 461, D2 sentinel line 443, pkgutil walk line 419 | PASS |
| TEST-09d | seed 12345, OCR Cluster C deselected, 0 failed | `1251 passed, 2 skipped, 4 deselected in 20.00s` | PASS |
| TEST-09e | seed 67890, OCR Cluster C deselected, 0 failed | `1251 passed, 2 skipped, 4 deselected in 19.63s` | PASS |
| TEST-09f | seed 99999, OCR Cluster C deselected, 0 failed | `1251 passed, 2 skipped, 4 deselected in 19.15s` | PASS |
| TEST-09g | 7 named failures + parametrized children green | `16 passed, 23 warnings in 1.07s` | PASS |
| TEST-09h | integration baseline unchanged (per D-VERIFY-02) | Pre-existing `/app` PermissionError in `eval/models.py:55` blocks raw command on WSL; reproduced at pre-phase commit 5c1905b (eval/models.py untouched in phase 33); with `--ignore=tests/integration/test_ragas_eval.py` baseline shows 33p/7f/1s/3e (net better than anchor) | DEFERRED — legitimate (environment-only, pre-existing, not caused by phase 33) |
| TEST-09i | unit-suite runtime ≤ 1.05× Phase 32 baseline (~22.05s ceiling) | Slowest seed: 20.00s | PASS |

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| TEST-08 | Add `@pytest.mark.real_embedder` opt-out marker + canary + RUNBOOK docs | SATISFIED | All 6 gates green (TEST-08a–f); SC1 + SC2 both verified |
| TEST-09 | Fix 7 order-dependent unit failures; 3 seeds green; reset fixture + mock parity | SATISFIED | 8/9 gates PASS + 1 DEFERRED (TEST-09h env-only); SC3 + SC4 both verified |

---

## Deviation Review

### 33-01 Rule 1 deviation (+22/-2 instead of plan-spec +1/+2)

**Accepted.** Sibling pattern at `tests/unit/test_memory_service_extra.py:196-200` (`test_long_term_get_relevant_facts_*`) uses identical `_TxnCtx + AsyncMock` shape. Phase 27-04 commit refactored `save_fact` → `save_facts` (batch path) which now traverses `conn.transaction()` → `conn.fetch` (bulk dedupe at memory_service.py:552) → `conn.executemany` (the INSERT). The plan author's +1/+2 constraint assumed only the embed_batch mock shape was wrong; the actual fix surface is wider but stays inside one test function (lines 231-263) and mirrors a pre-existing canonical pattern in the same file. **Not scope-creep** — directly required for the named test to pass.

Code review:
- New conn.fetch (line 253), conn.executemany (line 254), _TxnCtx (lines 256-258), conn.transaction (line 260) all match sibling at 192-200.
- Assertion changed from `conn.execute.assert_awaited_once()` to `conn.executemany.assert_awaited_once()` — correct because save_facts now uses executemany as canonical write call.
- In-line documentation block (lines 245-250) explains the Phase 27-04 root cause and points at the sibling pattern.

### 33-01 TEST-09h deferral

**Accepted as legitimate.** Verification:

1. `eval/models.py` was NOT modified in phase 33 — `git diff 5c1905b..HEAD -- eval/models.py` returns empty.
2. At pre-phase commit `5c1905b` the `/app` hardcoded defaults already exist at `eval/models.py:36-37`, with `ensure_report_dir` calling `p.mkdir(parents=True, exist_ok=True)` at line 55 (Pydantic field_validator, mode="before") — fires at module import.
3. Current verifier reproduces the identical error: `PermissionError: [Errno 13] Permission denied: '/app'` at `pathlib.py:1311` → `os.mkdir(self, mode)`.
4. The collection error is at module-import time, BEFORE pytest reads `tests/conftest.py`, so the deferred-items.md analysis is correct: pytest-randomly, `_reset_tool_registry`, and embed_batch mock cannot be the cause.

Recommended path: Phase 34 picks up Phase 34 sentinel-drift (TEST-10/TEST-11) and/or v1.10 backlog ticket fixes `EvalSettings` env-var defaults (per deferred-items.md §Recommended fix).

---

## Out-of-Scope Guard

| Path | Expected | Actual | Status |
|------|----------|--------|--------|
| `services/agent/tools/registry.py` | NO writes (canonical) | `git diff 5c1905b..HEAD` empty | CLEAN |
| `services/vectorizer/embedder.py` | NO writes (canonical) | empty diff | CLEAN |
| `services/retriever/retriever.py` | NO writes (canonical) | empty diff | CLEAN |
| `services/extractor/ocr_engine.py` | NO writes (OCR Cluster C deferred) | empty diff | CLEAN |
| `services/extractor/ocr_failure_modes.py` | NO writes (OCR Cluster C deferred) | empty diff | CLEAN |
| `.github/` | NO writes (CI integration deferred per Q8) | empty diff | CLEAN |
| `Makefile` | NO writes | empty diff | CLEAN |
| Existing tests promoted to `@pytest.mark.real_embedder` beyond new canary | NONE | only `tests/integration/test_real_embedder_canary.py` carries the marker | CLEAN |

Phase 33 non-planning file delta:
```
docs/RUNBOOK.md
pyproject.toml
pytest.ini
requirements-dev.txt
tests/conftest.py
tests/integration/conftest.py
tests/integration/test_real_embedder_canary.py
tests/unit/test_memory_service_extra.py
uv.lock                  (side-effect of uv add)
```

Exactly the expected file set from 33-CONTEXT §Phase Boundary in-scope list.

---

## Anti-Patterns Scan

| File | Pattern | Severity | Finding |
|------|---------|----------|---------|
| (none) | TBD/FIXME/XXX in phase-33 diffs | n/a | `git diff 5c1905b..HEAD -- '*.py' \| grep -E '^\+.*\b(TBD\|FIXME\|XXX)\b'` returns 0 hits |
| (none) | New bare `# type: ignore` | n/a | 0 hits in phase-33 diff; Phase 32 hygiene gate green |
| `tests/conftest.py:_reset_tool_registry` | `assert len(tool_classes) >= 4` | Info | Sentinel is intentional D2 hardening; would fail loud on future tool-package refactor |

No blockers, no warnings.

---

## Human Verification Required

### 1. Real-embedder canary on PG host

**Test:** On PG host with `$APP_MODEL_DIR/BAAI/bge-m3` + `$APP_MODEL_DIR/BAAI/bge-m3-rerank` files present, run:
```
uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q
```
**Expected:** `1 passed` (not `1 skipped`) — confirms the opt-out branch actually routes through real `HuggingFaceEmbedder.__init__` + `CrossEncoderReranker.__init__` and produces a 1024-d vector + scalar predict score.
**Why human:** WSL verifier host lacks bge-m3 / bge-m3-rerank files (per 33-VALIDATION.md §Manual-Only Verifications). On this verifier run the canary correctly skipped via `pytest.mark.skipif(not _models_present())`, which is the documented in-environment behavior.

---

## Verdict

**PASSED** — all 4 ROADMAP success criteria, all 12 observable truths, all 6 TEST-08 gates, 8/9 TEST-09 gates green + 1 legitimately deferred (TEST-09h environment-only blocker confirmed pre-existing and uncaused by phase 33). Rule 1 deviation in 33-01-02 is justified (sibling pattern parity for Phase 27-04 batch path). Out-of-scope guard clean. Phase 32 typing-hygiene carry-forward holds. One human verification item (canary on PG host) remains but does NOT block phase completion — it is a documented manual-only verification per 33-VALIDATION.md.

Per Step 9 decision tree: status is `passed` for goal-achievement but a human verification item exists for full real-embedder canary confirmation. Phase goal is observably achieved in the codebase via the WSL-equivalent skip path; the PG-host pass is corroborating evidence, not a blocker.

---

_Verified: 2026-05-18 — gsd-verifier_
