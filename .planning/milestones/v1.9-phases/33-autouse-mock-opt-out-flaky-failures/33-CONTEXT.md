# Phase 33: Autouse-Mock Opt-Out + Order-Dependent Failures - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Two independent test-infra workstreams that touch disjoint file sets:

1. **TEST-08** — Add `@pytest.mark.real_embedder` opt-out marker to Phase 30-02's autouse mock in `tests/integration/conftest.py`. Tests with the marker observe the real `HuggingFaceEmbedder` + `CrossEncoderReranker` classes (not the patched stand-ins). At least one minimal canary test exercises the opt-out path on PG host.

2. **TEST-09** — Eliminate the 7 order-dependent unit-test failures rooted in (a) registry-singleton pollution between tests and (b) `embed_one`/`embed_batch` mock-shape mismatch from the v1.7 batch API migration. The 7 failures are confirmed against current main as of Phase 32 close: 3 in `tests/unit/test_retrieve_tool.py` (Registration + SchemasForParity classes) + 4 in `tests/unit/test_web_search_tool.py` (Registration + Run + Helpers classes).

**In scope:** `tests/integration/conftest.py` (marker opt-out), `pytest.ini` (marker registration + `--random-order` plugin), `tests/conftest.py` (registry-singleton reset fixture), `tests/unit/test_retrieve_tool.py` + `tests/unit/test_web_search_tool.py` (mock-shape parity edits), `docs/RUNBOOK.md` (TEST-08 documentation), new minimal canary test under `tests/integration/`.

**Out of scope:** Driving full unit suite to `100% pass under any random seed` (acceptance is "3 distinct seeds, all green"; broader random-order hardening = future TEST phase). Rewriting Phase 30-02 autouse fixture from scratch (the patch-object approach is locked carry-forward — D-AUDIT-04 from Phase 31). Adding new singleton-tracking infrastructure beyond what the tests need (audit-mode-before-enforce — only reset singletons that demonstrably leak between the 7 failing tests + any nearby callers).

</domain>

<decisions>
## Implementation Decisions

### Plan structure
- **D-PLAN-01:** Split into two plans in Wave 1 — `33-00-PLAN.md` (TEST-08) + `33-01-PLAN.md` (TEST-09) — running in parallel worktrees. Zero file overlap between plans, so parallel execution is safe. Each plan is ~3-4 tasks, ~30-50 LOC of net diff. Wave 1 contains exactly two plans; no wave 2.

### TEST-08 — real_embedder marker + canary
- **D-MARKER-01:** Register `real_embedder` marker in `pytest.ini` `[pytest] markers` block immediately after the existing `real_llm` entry. Marker description: `"integration tests requiring real local model files (bge-m3 / bge-m3-rerank); skipped in default CI without the files present"`.
- **D-OPTOUT-01:** Modify `_mock_local_model_inits` autouse fixture in `tests/integration/conftest.py` to early-return when `request.node.get_closest_marker("real_embedder")` is non-None. Acceptance test: a marked test sees the real `HuggingFaceEmbedder.__init__` (which raises `FileNotFoundError` if bge-m3 absent — that's the expected, documented signal).
- **D-CANARY-01:** Minimal canary only — 1 new test file (e.g., `tests/integration/test_real_embedder_canary.py`, ~30 LOC). Imports real `HuggingFaceEmbedder` + `CrossEncoderReranker`, marks `@pytest.mark.real_embedder` + `@pytest.mark.integration`, instantiates each, calls `encode(["hello"])` + `predict([("q","d")])`, asserts output shapes (1024-d vector, scalar float). Skipped by default integration filter (real_embedder marker excluded same way `real_llm` is excluded). Does NOT promote any existing test to the marker — keeps blast radius minimal.
- **D-DOCS-01:** Documentation lands in `docs/RUNBOOK.md` under a new `## Test Infrastructure` section (create if absent). Sections: "Default integration suite behavior" (autouse mock active), "Real-embedder opt-out" (when + how to mark a test, what env requires — bge-m3 + bge-m3-rerank files at `$APP_MODEL_DIR`).

### TEST-09 — registry reset + mock-shape parity + random-order plugin
- **D-RESET-01:** Add a function-scope autouse reset fixture in `tests/conftest.py` (unit-test scope only — does NOT bleed into integration via integration/conftest.py inheritance, which already has its own autouse mock fixture). Surgical reset only — explicitly named singletons that the 7 failing tests demonstrate leak. Audit-mode-before-enforce: planner's research step enumerates which singletons actually pollute (via failing-test traceback inspection + grep for `_<name>_instance` patterns); only those are reset. Do NOT introduce a broad-sweep "reset all singletons" mechanism (over-engineering risk + slows the 1248-test unit suite).
- **D-MOCK-01:** Align mocks to the canonical `embed_batch([text]) -> [vector]` API (post-v1.7 batch migration). NO compat shim. Mocks in `tests/unit/test_retrieve_tool.py` + `tests/unit/test_web_search_tool.py` patch `embed_batch` directly, asserting batch shape. Mock-at-consumer convention preserved (v1.3 D-mock carry-forward) — patch at `services.<mod>.<dep>` import path, not at source. Researcher confirms the production callsites genuinely use `embed_batch` (no straggler `embed_one` usage in production code). If any straggler exists, that's a separate finding the executor surfaces, not silently shims around.
- **D-PLUGIN-01:** Install `pytest-randomly` via `uv add --dev "pytest-randomly>=3.16.0"` (latest stable as of 2026-05). Most popular plugin (~1M downloads/month); seeds via pytest header for CI-log triage; minimal config. Add to `requirements-dev.txt` too (carry-forward of Phase 32 D1+D3 typing-hygiene script will enforce parity automatically — `pytest-randomly` is not a `*-stubs` package so the script's stub-line regex won't match, but the lesson stands: dual-write all dev deps).
- **D-SEEDS-01:** Acceptance command set — `pytest tests/unit/ -p randomly --randomly-seed=12345`, `--randomly-seed=67890`, `--randomly-seed=99999`. All three must pass. Document the seeds + invocation in `tests/conftest.py` docstring near the reset fixture so future contributors know the regression net exists.

### Verification / acceptance contract
- **D-VERIFY-01:** Per-requirement acceptance commands:
  - TEST-08: (a) `grep -q 'real_embedder:' pytest.ini` → exit 0; (b) `grep -q 'get_closest_marker("real_embedder")' tests/integration/conftest.py` → exit 0; (c) `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder --asyncio-mode=auto -q` → exit 0 OR skip with reason "bge-m3 not present" (env-dependent); (d) `grep -q '^## Test Infrastructure' docs/RUNBOOK.md` → exit 0.
  - TEST-09: (a) `uv pip show pytest-randomly` → version ≥ 3.16; (b) `uv run pytest tests/unit/ -m 'not integration' --randomly-seed=12345 -q`, `--randomly-seed=67890 -q`, `--randomly-seed=99999 -q` — all three return `0 failed / 0 errors`; (c) `tests/unit/test_retrieve_tool.py` + `tests/unit/test_web_search_tool.py` previously-failing tests all green (per Phase 32 SUMMARY = 7 named cases).
- **D-VERIFY-02:** Integration suite baseline does NOT regress vs Phase 32 close: 31 passed / 9 failed (pre-existing per Phase 32 truth-corrected baseline) / 1 skipped / 3 errors under standard filter `-m 'integration and not real_llm and not benchmark'`. The added canary test is `-m 'integration and not real_embedder ...'` so it's deselected by default and doesn't affect the count.

### Claude's Discretion
- Specific docstring wording for `_mock_local_model_inits` opt-out branch.
- Whether to write canary as async (`async def test_...`) or sync — planner picks based on `HuggingFaceEmbedder.__init__` blocking nature.
- Order of execution within each plan (marker register → fixture edit → canary → docs, or interleave). Planner picks.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plan / requirements / state
- `.planning/REQUIREMENTS.md` — TEST-08, TEST-09 acceptance criteria
- `.planning/ROADMAP.md` §Phase 33 — Goal, Success Criteria, Canonical refs, Depends on
- `.planning/PROJECT.md` §Active — v1.9 in-flight requirement list

### Locked carry-forward patterns (read before touching test infra)
- `tests/integration/conftest.py` — Phase 30-02 `_mock_local_model_inits` autouse fixture; the opt-out branch is added to THIS file, not a replacement
- `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-02-SUMMARY.md` — Why the autouse mock exists + what it patches
- v1.3 D-mock convention (mock-at-consumer `services.<mod>.<dep>` not at source) — applies to all TEST-09 mock-shape edits
- v1.7 Phase 27 batch API (`embed_batch([text]) -> [vector]`) — canonical shape; mocks must match

### TEST-09 failing test inventory (verified vs Phase 32 close commit `c261bb1`)
- `tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_retrieve_tool_registered`
- `tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_refine_tool_registered`
- `tests/unit/test_retrieve_tool.py::TestSchemasForParity::test_retrieve_tool_xml_format_parity`
- `tests/unit/test_web_search_tool.py::TestWebSearchToolRegistration::test_web_search_tool_registered`
- `tests/unit/test_web_search_tool.py::TestWebSearchToolRun::test_*` (3 cases — see Phase 32 32-00-SUMMARY.md T7 closeout for exact node ids)
- `tests/unit/test_web_search_tool.py::TestWebSearchToolHelpers::test_*` (1 case)

### Test-infra files (anchor points for downstream edits)
- `tests/integration/conftest.py` (autouse fixture; TEST-08 opt-out lands here)
- `tests/conftest.py` (unit-scope conftest; TEST-09 reset fixture lands here)
- `pytest.ini` (markers block + addopts; TEST-08 + TEST-09 both edit)
- `docs/RUNBOOK.md` (TEST-08 docs; create section if absent)
- `pyproject.toml [dependency-groups].dev` + `requirements-dev.txt` (TEST-09 plugin install — dual-write per Phase 32 CI-gap lesson)
- `services/agent/tools.py` + `services/vectorizer/embedder.py` (canonical `embed_batch` signature reference — DO NOT modify; read-only for parity check)

### Phase 32 carry-forward (this phase inherits)
- `# type: ignore[code]  # why:` silence convention (Phase 30-03 locked)
- `scripts/check_typing_hygiene.py` (Phase 32 T1.5) — TEST-09 must not introduce any bare ignores; the gate will fail PR if violated
- Phase 32 corrected integration baseline (31 passed / 9 failed / 1 skipped / 3 errors) — D-VERIFY-02 must not regress this

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_mock_local_model_inits` autouse fixture (tests/integration/conftest.py:26) — TEST-08 adds an early-return branch, does NOT replace.
- `pg_pool` + `pg_store` function-scope fixtures (tests/conftest.py:38-80) — pattern for TEST-09 singleton reset (function-scope, autouse, explicit yield + cleanup).
- `pytest.ini` markers block (lines 11-14) — TEST-08 appends one entry following the existing format.
- `pytestmark = [pytest.mark.integration, pytest.mark.real_llm]` pattern (Phase 31's chinese_section marker fix, `tests/integration/test_filter_extractor_llm.py:21`) — TEST-08 canary uses the same pattern.

### Established Patterns
- Mock-at-consumer (v1.3 D-mock): patch `services.<mod>.<dep>` not the source module. All TEST-09 mock-shape edits follow this verbatim.
- Audit-mode-before-enforce (v1.6 EVICT-02 + v1.8 30-03 + Phase 31 + Phase 32): surface the metric, then act. TEST-09 reset fixture must only reset singletons demonstrated to leak — not a broad sweep.
- Phase 32 D1+D3 typing-hygiene gate: any new silence introduced by TEST-09 mocks MUST follow `[code]  # why:` form or the pre-commit/CI gate will block the PR.

### Integration Points
- `tests/integration/conftest.py` opt-out: integrates with Phase 30-02's existing fixture body — branch, don't fork.
- `tests/conftest.py` reset: integrates with existing `pg_pool` + `pg_store` fixtures — sibling fixture, not interleaved.
- `pytest.ini` plugin registration: `pytest-randomly` auto-registers when installed (no `[pytest] plugins =` edit needed); seed surfaces in CLI header automatically.
- `pyproject.toml [dependency-groups].dev` + `requirements-dev.txt`: must be dual-written (carry-forward from Phase 32 RESEARCH §Q9 CI gap). The Phase 32 typing-hygiene script (`scripts/check_typing_hygiene.py`) checks `*-stubs` and `types-*` packages only — `pytest-randomly` won't trip the gate, but the dual-write discipline still applies.

</code_context>

<specifics>
## Specific Ideas

- User picked recommended option in all 4 areas — strong signal to favor surgical-not-broad, canonical-not-shim, popular-not-bespoke, minimal-not-promote.
- Researcher should run the 3 acceptance seeds (12345, 67890, 99999) at plan time to surface any seed-specific issues before execution.
- Canary test naming: `tests/integration/test_real_embedder_canary.py::test_real_embedder_models_load_and_encode` (or similar) — keeps purpose obvious + greppable.

</specifics>

<deferred>
## Deferred Ideas

- **Full unit suite random-order hardening** (all seeds, not just 3) — TEST-09 acceptance is bounded to 3 distinct seeds; broader hardening (e.g., `n=100` random seeds in nightly CI) is a future test-infra phase.
- **Promote `extractor_e2e` or other existing tests to `@pytest.mark.real_embedder`** — D-CANARY-01 explicitly defers this. Reconsider if minimal canary surfaces a gap where opt-out passes in isolation but fails in a real pipeline.
- **Broad singleton-tracking infrastructure** (e.g., decorator-based registry that auto-resets) — D-RESET-01 explicitly defers. Reconsider if a future phase surfaces >3 new flaky tests from singleton pollution.
- **Compat shim for `embed_one`** — D-MOCK-01 rejects. Reconsider only if researcher finds production callers genuinely require single-shot semantics that batch-wrapping degrades.
- **Adding `pytest-randomly` to CI as a default run** — TEST-09 acceptance is local + on-demand. CI default integration is a future test-infra phase.

</deferred>

---

*Phase: 33-autouse-mock-opt-out-flaky-failures*
*Context gathered: 2026-05-18*
