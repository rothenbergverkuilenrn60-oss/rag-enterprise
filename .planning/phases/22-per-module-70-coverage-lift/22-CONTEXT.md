# Phase 22: Per-Module 70% Coverage Lift - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Lift five large service modules — `services/pipeline.py`, `services/generator/llm_client.py`, `services/vectorizer/vector_store.py`, `services/retriever/retriever.py`, `services/extractor/extractor.py` — to per-module ≥70% line coverage via new unit tests only. Wire CI to enforce a per-module floor on combined coverage data so the 5 modules can no longer be averaged-around. NO production-code changes (v1.3 D-04 lock). Mock at consumer paths (`services.<mod>.<dep>`) per v1.3 Phase 13/15 pattern. Specific test branches per module are enumerated in ROADMAP SC1–SC5.

**Baseline (`tests/unit` only, coverage.py 7.13.5, 2026-05-10):**

| Module | Stmts | Miss | Cover | Gap to 70% |
|---|---|---|---|---|
| `services/pipeline.py` | 606 | 347 | 42.7% | ~165 stmts |
| `services/generator/llm_client.py` | 364 | 171 | 53.0% | ~62 stmts |
| `services/vectorizer/vector_store.py` | 190 | 106 | 44.2% | ~49 stmts |
| `services/retriever/retriever.py` | 307 | 201 | 34.5% | ~109 stmts |
| `services/extractor/extractor.py` | 306 | 192 | 37.3% | ~94 stmts |

Pipeline.py is ~4× the next-largest gap; expect plan 22-01 to be the longest plan.

**In scope:**
- 5 new test files: `tests/unit/test_pipeline_coverage.py`, `test_llm_client_coverage.py`, `test_vector_store_coverage.py`, `test_retriever_coverage.py`, `test_extractor_coverage.py` (D-09)
- `.github/workflows/ci.yml` `coverage-combine` job: 5 new per-module gate steps (warning-only at 22-00, hard-fail at 22-06) (D-01, D-08)
- Makefile target `coverage-per-module` (or `scripts/check-per-module-coverage.sh`) mirroring CI gates for local pre-flight (D-03)
- `README.md` Coverage section copy update for per-module floor (in 22-06)
- `.planning/STATE.md`: close TEST-08..TEST-12 + flip Open Q#5 to "resolved per D-05" (in 22-06)

**Out of scope:**
- Production code changes (v1.3 D-04 lock; reaffirmed by SC of TEST-08..12)
- Branch coverage activation (`branch = true` in `[tool.coverage.run]`) — Phase 15 D-08 line-only carry-forward; v1.6+ candidate
- Mutation testing — TEST-07 deferred to v1.6+
- Coverage shields.io badge in README — Phase 15 D-11 out-of-scope, reaffirmed
- Per-class coverage breakdown for pipeline.py — D-05 rejected per-class option
- Floor raise above 70% (e.g., 80%) — Phase 15 D-11 out-of-scope; v1.6+
- Backfill tests for modules outside the Phase-22 list of 5
- New features in `services/<mod>.py` masquerading as test infrastructure
- Pipeline.py split into sub-modules — v1.6+ refactor (mentioned as D-05 alternative)
- Refresh of `.planning/codebase/TESTING.md` — belongs in `/gsd-map-codebase`, not Phase 22

</domain>

<decisions>
## Implementation Decisions

### Per-Module Enforcement Mechanism
- **D-01:** Explicit per-module CI gates: 5 separate `coverage report --include=services/<mod>.py --fail-under=70` invocations in `coverage-combine` job (one per Phase-22 module). No averaging-mask; each module gates independently.
- **D-02:** Run-all-then-fail semantics: gates collect statuses (`set +e` + accumulated exit code, OR 5 GitHub-Action steps with `continue-on-error: true` followed by a final assertion step). Dev sees all failing modules in one CI run, not just the alphabetically-first.
- **D-03:** Logic lives inline in `ci.yml` AND mirrored as a `Makefile` target `coverage-per-module` (or shell script `scripts/check-per-module-coverage.sh`) so devs run the same check locally before pushing.
- **D-04:** Gates run against combined coverage data only (in `coverage-combine` job, after `coverage combine .coverage.unit .coverage.integration`). Carries forward Phase 15 D-05/D-06: combined is the single source of truth.

### pipeline.py Scope (Open Q#5 resolved)
- **D-05:** `services/pipeline.py` measured as a whole-file ≥70% target (literal ROADMAP interpretation). NO `omit` exclusions, NO `# pragma: no cover` blocks at class boundary, NO custom per-class breakdown. IngestionPipeline + QueryPipeline (v1.0 RAG) + AgentQueryPipeline + SwarmQueryPipeline all contribute to the same denominator. STATE.md Open Q#5 closes here.
- **D-06:** Measure-then-add coverage strategy for pipeline.py: Wave 1 lands SC1-prescribed branches (`AgentQueryPipeline.run`/`run_streaming` error branches, `SwarmQueryPipeline` synthesis path with `debate=False`, `_dedup_chunks`, `_build_initial_messages`); Wave 2 (if still <70%) backfills targeted tests against the highest-impact Missing line ranges from `coverage report --include=services/pipeline.py --show-missing`. Matches Phase 15 D-04 measure-then-plan precedent.

### Plan Decomposition + Gate Timing
- **D-07:** Seven plans:
  - **22-00 setup:** Install warning-only per-module CI gates + Makefile target + `.planning/phases/22-per-module-70-coverage-lift/22-BASELINE.md` snapshot. Unblocks parallel work on 22-01..22-05.
  - **22-01..22-05:** One plan per module, all parallel after 22-00. 22-01 (pipeline.py) ships FIRST in execute order — largest blast radius, surfaces gate-mechanism integration issues early.
    - 22-01 → `services/pipeline.py` → TEST-08 → SC1
    - 22-02 → `services/generator/llm_client.py` → TEST-09 → SC2
    - 22-03 → `services/vectorizer/vector_store.py` → TEST-10 → SC3
    - 22-04 → `services/retriever/retriever.py` → TEST-11 → SC4
    - 22-05 → `services/extractor/extractor.py` → TEST-12 → SC5
  - **22-06 finalize:** Flip all 5 CI gates from warning-only to `--fail-under=70` hard-fail; update README Coverage section copy; close TEST-08..12 in REQUIREMENTS.md; flip STATE Open Q#5 to "resolved per D-05". Single locking point — no per-plan ci.yml conflicts.
- **D-08:** Gate timing: 22-00 installs gates as warning-only (so CI stays green during the milestone window); 22-01..22-05 each assert their module's ≥70% target inside their own VERIFICATION.md (per-plan local enforcement); 22-06 flips all 5 gates to hard-fail in a single locked-down PR. Avoids merge-order conflicts on `ci.yml` and avoids "CI red the whole milestone."

### Test File Organization
- **D-09:** Strict new file per module: 5 new files at `tests/unit/test_<mod>_coverage.py` exactly (`test_pipeline_coverage.py`, `test_llm_client_coverage.py`, `test_vector_store_coverage.py`, `test_retriever_coverage.py`, `test_extractor_coverage.py`). Matches ROADMAP canonical-refs literal text. Existing helper-style files (`test_pipeline_helpers.py`, `test_llm_client_helpers.py`, etc.) stay untouched — clean diff per plan, clean PR-to-requirement mapping.
- **D-10:** Inline per-file fixtures: each `test_<mod>_coverage.py` defines its own `@pytest.fixture` stubs at the top (stub planner, stub LLM client, stub vector store, stub asyncpg connection, stub PyMuPDF document, etc.). NO shared `conftest.py` extension, NO new `tests/unit/coverage/` subdir. Zero coupling between coverage plans; small fixture duplication accepted.
- **D-11:** Function-style tests with grouping comments + `@pytest.mark.parametrize` for tables. `def test_<branch>(...)` plain functions; group related tests under `# --- AgentQueryPipeline.run error branches ---` comment headers. Use parametrize for table-driven cases (e.g., `_build_filter_where` int/string/null per SC3, `(client_factory, exception_class)` per SC2, OCR engine selection per SC5). Matches existing project style.
- **D-12:** Module docstring at top of each new file: `"""Coverage tests for services/<mod>.py per TEST-XX (Phase 22 SC<N>). Targets: <list of branches>."""`. Cheap traceability for reviewers and `/gsd-verify-work 22`.

### Wire-Fixture Extension for Failure Paths
- **D-13:** Inline `side_effect` raising the SDK exception (NO new JSON fixtures for failure responses). For SC2: `monkeypatch.setattr` the consumer-path attribute to a stub raising `anthropic.RateLimitError(message='429', response=Mock(status_code=429), body={})` / `anthropic.OverloadedError(...)` / `anthropic.APIConnectionError(...)` / `tenacity.RetryError(...)`. Existing `tests/unit/fixtures/agent_parity/{single_step,parallel_multi_step}.json` stay reserved for happy-path only (TEST-09 SC2 explicit).
- **D-14:** Parametrize across `(client_factory, exception_class, exception_kwargs)` pairs: ~6 parametrized tests covering the retry-then-success and raise-after-max-attempts contracts on both Anthropic and OpenAI clients. Parametrize IDs use `(client, exception)` form (e.g., `test_call_agentic_turn_retries_then_succeeds[anthropic-RateLimitError]`) for readable failure output.
- **D-15:** Monkeypatch tenacity `wait` to `tenacity.wait_none()` per retry test: `monkeypatch.setattr(<retry_decorator>.retry, 'wait', tenacity.wait_none())` (or `mock.patch.object(client._call_method.retry, 'wait', tenacity.wait_none())`). Real retry logic exercised (count, exception classification, final-failure path) without sleep cost — tests stay <1s. NO production-code env-var hooks (would violate D-04 NO production-code changes).
- **D-16:** Same inline-side_effect pattern uniformly across all 5 modules: `asyncpg.PostgresError` for vector_store + retriever `_expand_to_parent`; `asyncio.TimeoutError` for retriever `_rerank_with_sla`; PyMuPDF/Tesseract exceptions for extractor (mock `doc.load_page(i).get_text()` return values, NO binary PDF fixtures); planner/executor/tool failures for pipeline. NO new binary fixtures (`is_scanned_pdf` 3-page heuristic per SC5 mocked at PyMuPDF seam).

### Carrying Forward (locked by ROADMAP / STATE / prior phases — NOT re-asked)
- **CF-01:** NO production-code changes — v1.3 D-04 lock; SC of every TEST-08..12; NO `# pragma: no cover` additions to source files (subtle violation).
- **CF-02:** Mock at consumer path `services.<mod>.<dep>`, NOT at SDK source — v1.3 Phase 13 D-04 established; Phase 15 reuse; Phase 20 inheritance.
- **CF-03:** Reuse v1.2 wire fixtures `tests/unit/fixtures/agent_parity/{single_step,parallel_multi_step}.json` for happy-path LLM (TEST-09 explicit). Failure-path is D-13 inline.
- **CF-04:** `pyproject.toml [tool.coverage.run]` config locked: `parallel = false`, `branch = false`, `source = ["services", "utils"]`, `omit = ["*/__init__.py", "*/migrations/*", "*/tests/*"]`, existing `exclude_lines` (4 entries: `pragma: no cover`, `raise NotImplementedError`, `if __name__ == .__main__.:`, `if TYPE_CHECKING:`). Phase 15 D-08; NO Phase-22 changes.
- **CF-05:** `.github/workflows/ci.yml` `coverage-combine` job topology locked from Phase 15 D-02: `needs: [unit-tests, integration-tests]`, downloads both artifacts, runs `coverage combine` then `coverage report --fail-under=70` (global) then `coverage xml` then `diff-cover`. Phase 22 ADDS 5 per-module gate steps; does NOT modify upstream jobs.
- **CF-06:** `diff-cover --fail-under=80` on touched files (TEST-03 carry-forward). Applies to all 5 new test files + ci.yml + Makefile/script changes.
- **CF-07:** Specific test branches per module enumerated in ROADMAP SC1–SC5 — these are NOT re-asked or relitigated; planner consumes them directly:
  - SC1 pipeline: `AgentQueryPipeline.run`/`run_streaming` error branches; `SwarmQueryPipeline` synthesis (`debate=False`); `_dedup_chunks`; `_build_initial_messages`
  - SC2 llm_client: `RateLimitError` (429) / `OverloadedError` / `RetryError` / `APIConnectionError` across `AnthropicLLMClient.call_agentic_turn` + `OpenAILLMClient.call_agentic_turn`
  - SC3 vector_store: `_build_filter_where` table-driven (int/string/null `page_number`); JSONB `isinstance(metadata, str)` decoding (line 347); HNSW DDL idempotency
  - SC4 retriever: `_to_retrieved_chunk` `ChunkMetadata.model_validate` auto-passthrough (page_number / section_id round-trip); `_rerank_with_sla` SLA timeout fallback to `PassthroughReranker`; `_expand_to_parent` `asyncpg.PostgresError` non-fatal warning branch
  - SC5 extractor: `is_scanned_pdf` 3-page-sample heuristic (text-rich vs scanned); `_detect_header_footer_texts` 10-page-cap; OCR-vs-native-extract router; Tesseract OCR engine selection (v1.4.2 fix)
- **CF-08:** Combined data is single source of truth (Phase 15 D-05). Per-module gates run on combined `.coverage`, NOT unit-only.
- **CF-09:** Line coverage only; branch coverage `v1.4+` candidate (Phase 15 D-08). NOT activated in Phase 22.
- **CF-10:** `pytest.ini` config unchanged (`asyncio_mode = auto`, `addopts = -m "not integration"`, `timeout = 60`).
- **CF-11:** `pytest-cov`, `diff-cover`, `pytest-timeout` already in `[dependency-groups] dev` — no new dev dependencies needed for Phase 22.

### Claude's Discretion
- Specific `httpx.Response` mock construction shape for SDK exception constructors (`Mock(status_code=429, headers={}, request=Mock())` style) — match what the SDK constructor actually requires; planner consults Anthropic SDK source.
- Order of plans 22-02..22-05 within the parallel wave (alphabetical OR smallest-gap-first OR largest-gap-first) — no functional difference; planner picks.
- Specific `@pytest.fixture` names within each new file (e.g., `stub_planner` vs `mock_planner` vs `fake_planner`) — match house style observed in existing helper files.
- Whether 22-00 baseline measurement output goes to `22-BASELINE.md` (markdown) or `22-baseline-coverage.txt` (raw `coverage report` output) — markdown preferred for readability + diff-cover navigation; planner picks.
- Format of accumulated-status loop in CI (bash `set +e` + status array vs separate `continue-on-error` steps + final assert) — both satisfy D-02; planner picks based on ci.yml YAML clarity.
- Whether to add a `coverage report --include=services/<mod>.py --show-missing` log line per gate (verbose, useful) or strict pass/fail only (terse) — recommend verbose in warning-only phase, terse after 22-06 flip.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 22 source artifacts
- `.planning/ROADMAP.md` § "Phase 22: Per-Module 70% Coverage Lift" — locked Goal + Depends-on + Canonical refs + SC1–SC5
- `.planning/REQUIREMENTS.md` § "Coverage Lift (TEST)" — TEST-08, TEST-09, TEST-10, TEST-11, TEST-12 + Traceability table
- `.planning/PROJECT.md` § "Constraints" + "Key Decisions" — D-04 NO production-code lock context
- `.planning/STATE.md` § "Open Questions Carried into v1.5 Planning" Q#5 — pipeline.py per-class vs whole-file (resolved by D-05)

### Coverage configuration anchors (read before editing)
- `pyproject.toml` `[tool.coverage.run]` + `[tool.coverage.report]` blocks (locked by Phase 15 D-08; NO Phase-22 changes)
- `pytest.ini` (locked; NO Phase-22 changes)
- `.github/workflows/ci.yml` `coverage-combine` job (Phase 22 ADDS 5 per-module gate steps; does NOT modify `unit-tests` or `integration-tests` jobs)

### Code anchors (read before testing)
- `services/pipeline.py` (1578 lines) — `AgentQueryPipeline.run`/`run_streaming` (lines ~605-622, 658-735), `SwarmQueryPipeline` synthesis path (lines ~819-878 region for `debate=False`), `_dedup_chunks` (line ~710 region), `_build_initial_messages` (lines ~939-957 region). Confirm via `coverage report --show-missing` before writing tests.
- `services/generator/llm_client.py` (1049 lines) — `AnthropicLLMClient.call_agentic_turn` (lines ~286-302), `OpenAILLMClient.call_agentic_turn` (lines ~518-637), tenacity retry decorators (look for `@retry(...)` decorator above each provider call).
- `services/vectorizer/vector_store.py` (529 lines) — `_build_filter_where` (lines ~241-277 region), JSONB `isinstance(metadata, str)` decoding branch (line 347 per SC3), HNSW DDL idempotency (`CREATE INDEX IF NOT EXISTS` — lines ~134-156 region).
- `services/retriever/retriever.py` (683 lines) — `_to_retrieved_chunk` `ChunkMetadata.model_validate` auto-passthrough (lines ~256-273 region), `_rerank_with_sla` SLA timeout (lines ~414-538 region), `_expand_to_parent` `asyncpg.PostgresError` branch (lines ~635-662 region).
- `services/extractor/extractor.py` (630 lines) — `is_scanned_pdf` 3-page-sample heuristic (lines ~37-93 region), `_detect_header_footer_texts` 10-page-cap branch (lines ~213-225 region), OCR-vs-native-extract router (lines ~383-446 region), Tesseract engine selection (v1.4.2 fix region around line ~571-620).

### Existing test patterns (read for style + reuse)
- `tests/unit/test_pipeline_helpers.py` (94 L), `test_pipeline_pii_block.py` (160 L), `test_pipeline_tool_schema_regression.py` (207 L) — pipeline test conventions
- `tests/unit/test_llm_client_agentic.py` (299 L) — v1.2 wire-fixture consumer pattern; happy-path baseline for SC2
- `tests/unit/test_llm_client_helpers.py` (133 L) — llm_client helper test conventions
- `tests/unit/test_vector_store_filter_where.py` (86 L) — existing `_build_filter_where` parametrize table; SC3 extends this pattern
- `tests/unit/test_retriever.py` (143 L), `test_retriever_helpers.py` (162 L) — retriever test conventions
- `tests/unit/test_extractor_helpers.py` (153 L), `test_extractor_ocr_routing.py` (179 L) — extractor test conventions; OCR routing already partially covered

### Wire fixtures (happy-path reuse, do NOT duplicate)
- `tests/unit/fixtures/agent_parity/single_step.json` (TEST-09 happy-path, single tool call)
- `tests/unit/fixtures/agent_parity/parallel_multi_step.json` (TEST-09 happy-path, parallel tool calls)
- `tests/unit/fixtures/agent_parity/__init__.py`

### Precedent CONTEXT.md (read once for orientation)
- `.planning/milestones/v1.3-phases/13-llm-filter-fallback/13-CONTEXT.md` — D-04 mock-at-consumer-path established (CF-02 source)
- `.planning/milestones/v1.3-phases/15-coverage-combine-and-70-floor/15-CONTEXT.md` — D-01..D-11 coverage config + CI topology (CF-04, CF-05, CF-08, CF-09 source)
- `.planning/phases/20-websearchtool-real-implementation-tavily/20-CONTEXT.md` — Phase 20 deferred-to-22 note (web_search.py NOT in Phase 22 module list — confirms 5-module scope)
- `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-CONTEXT.md` — Phase 21 deferred-to-22 (verifier paths now live in pipeline.py SwarmQueryPipeline; debate=False is what SC1 covers)

### Codebase maps (read once for orientation)
- `.planning/codebase/STRUCTURE.md` — service layer file layout
- `.planning/codebase/CONVENTIONS.md` — async-throughout, Pydantic V2 frozen, mypy --strict expectations
- `.planning/codebase/TESTING.md` — ⚠ OUT OF DATE (lists 4 test files; current is 622+ unit tests). Do NOT trust counts; read `pytest.ini` + actual `tests/unit/` for ground truth. Refresh deferred to `/gsd-map-codebase`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **v1.2 wire fixtures** (`tests/unit/fixtures/agent_parity/single_step.json`, `parallel_multi_step.json`): TEST-09 SC2 happy-path consumed via the existing `tests/unit/test_llm_client_agentic.py` pattern (`json.loads(Path(...).read_text())`). NO new happy-path fixtures needed.
- **Existing `tests/unit/test_<mod>_helpers.py` files**: Show monkeypatch + AsyncMock conventions in active use. Read `test_vector_store_filter_where.py` first — its parametrize table directly inspires SC3's table-driven `_build_filter_where` extension.
- **`pyproject.toml [tool.coverage.report] exclude_lines`**: Already 4 entries (`pragma: no cover`, `raise NotImplementedError`, `if __name__ == .__main__.:`, `if TYPE_CHECKING:`). NO Phase-22 extension; CF-04.
- **`pytest-cov`, `diff-cover`, `pytest-timeout`** already in `[dependency-groups] dev` (Phase 15 baseline). CF-11.
- **`coverage report --include=...`** works against combined `.coverage` data file out-of-the-box (verified by Phase 15 ci.yml). D-01 mechanism is standard coverage.py invocation, no custom tooling.
- **`coverage-combine` job in `.github/workflows/ci.yml`** (Phase 15 D-02): single insertion point for D-01 per-module gates; downstream of `coverage combine` step.

### Established Patterns
- **Mock at consumer path**: `monkeypatch.setattr("services.pipeline.get_planner", stub)`, NOT `services.agent.planner.create_planner` etc. (v1.3 Phase 13 D-04, Phase 15 reuse, Phase 20 inheritance, Phase 21 inheritance). CF-02.
- **Async-throughout**: `pytest-asyncio asyncio_mode = auto` (pytest.ini) — async tests need NO marker; use `AsyncMock` for awaitable stubs.
- **Frozen Pydantic V2 models on the agent surface**: `RetrievedChunk`, `ToolResult`, `AgentEvent` etc. constructed directly from local Python dicts in tests (no `model_validate` boilerplate when fixture is in-process).
- **AAA-style without explicit comment markers**: existing helper-style files don't use `# Arrange / # Act / # Assert` headers. D-11 follows.
- **Wire-fixture loading**: `json.loads(Path("tests/unit/fixtures/agent_parity/single_step.json").read_text())` (existing `test_llm_client_agentic.py` pattern). D-13 keeps this for happy-path; failure-path uses inline raise instead.
- **Coverage data file naming**: `.coverage.unit` (unit job) + `.coverage.integration` (integration job) → combined to `.coverage` in coverage-combine job (Phase 15 D-10). D-04 gates run on combined `.coverage`.
- **`continue-on-error: true`** on integration-tests job (Phase 15 D-03) — if integration job fails, only `.coverage.unit` is in combined data; per-module gate still runs on what's available.
- **`mypy --strict` + `ruff` clean** — Phase 22 must match v1.4 close baseline (296 errors = baseline; 0 new) on any file it touches. New test files included in this discipline.

### Integration Points
- **`.github/workflows/ci.yml` `coverage-combine` job**: SINGLE insertion point for D-01 per-module gates (5 new steps) + D-08 warning-only-vs-hard-fail flip. Plan 22-00 adds warning-only steps; plan 22-06 flips them. Atomic per-plan.
- **`Makefile` (or new `scripts/check-per-module-coverage.sh`)**: NEW target/script `coverage-per-module` mirroring CI gates for local pre-flight (D-03). Plan 22-00.
- **`pyproject.toml`**: NO changes (CF-04). Confirm at plan-checker.
- **`pytest.ini`**: NO changes (CF-10). Confirm at plan-checker.
- **5 new test files in `tests/unit/`**: NO subdir changes; existing flat `tests/unit/test_*.py` layout preserved (D-09).
- **`README.md` Coverage section** (Phase 15 referenced lines 241-273): copy update at plan 22-06 to mention per-module floor.
- **`.planning/STATE.md`**: at plan 22-06 — Open Q#5 flipped from "open" to "resolved per Phase 22 D-05"; TEST-08..12 marked complete; Carry-Forward Decisions section gets a new entry "Per-module ≥70% floor on the 5 v1.5-locked modules (Phase 22 D-01..D-08)".
- **`.planning/REQUIREMENTS.md` Traceability table**: at plan 22-06 — TEST-08..12 `tbd` columns updated to actual plan IDs (22-01..22-05).

</code_context>

<specifics>
## Specific Ideas

- **Pipeline.py is the giant.** 1578 lines / 606 stmts / 42.7% baseline. ~165 stmts to add. ~4× the next-largest gap. Plan 22-01 (pipeline) is the longest plan; should ship FIRST in the parallel wave to surface gate-mechanism + measurement-flow integration issues early. Other 4 plans can be re-ordered by gsd-planner.
- **Plan 22-00 has dual responsibility:** install warning-only gates + measure baseline. Recommended: write `.planning/phases/22-per-module-70-coverage-lift/22-BASELINE.md` snapshot (per-module current Cover% + Missing line ranges) so plans 22-01..22-05 have a concrete "stmts to add" budget. Cheap, high-value waypoint.
- **Plan 22-06 milestone-close responsibilities (single PR):**
  - Flip 5 CI gates to `--fail-under=70` (remove warning-only wrappers)
  - Update `README.md` Coverage section copy
  - Mark TEST-08..12 complete in REQUIREMENTS.md
  - Flip STATE Q#5 to resolved per D-05
  - Add new Carry-Forward Decisions entry for the per-module floor
  - Run final `make coverage-per-module` locally to confirm green
- **TEST-09 parametrize ID format:** `(client, exception)` form for readable failure output, e.g., `test_call_agentic_turn_retries_then_succeeds[anthropic-RateLimitError]`. Do NOT use bare exception class names — readability suffers under tenacity's deep stack traces.
- **TEST-10 `_build_filter_where` table-driven:** D-09 says strict new file `test_vector_store_coverage.py`. Existing `test_vector_store_filter_where.py` parametrize table inspires the new table; planner should consider whether to mark some old tests as redundant (and remove) OR keep both as defense-in-depth. Recommend keep — old tests enforce existing fix; new tests close per-module 70% gate.
- **TEST-12 `is_scanned_pdf` 3-page sample heuristic:** PyMuPDF `doc.load_page(i).get_text()` is the seam to mock. Stub returns `"a" * 200` (text-rich) for one variant, `""` (scanned) for the other. NO real PDF binary needed. Confirms D-16.
- **TEST-12 Tesseract engine selection (v1.4.2 fix):** test must mock at the consumer path where extractor calls `pytesseract.image_to_string(..., config=...)` or equivalent — NOT `pytesseract` source. Per CF-02.
- **Failure path for `_rerank_with_sla` (SC4):** `asyncio.wait_for(..., timeout=N)` raises `asyncio.TimeoutError`; the fallback branch returns `PassthroughReranker(...)` output. Mock the underlying reranker call to `side_effect=asyncio.sleep(timeout + 1)` OR raise `TimeoutError` directly — directly raising is faster.
- **Failure path for `_expand_to_parent` (SC4):** `asyncpg.PostgresError` non-fatal warning branch — must assert that the warning is logged (caplog) AND that the function returns the partial result (does NOT raise). Mock the asyncpg connection's `fetch` method to raise `asyncpg.PostgresError("simulated")`.
- **Diff-cover ≥80% on touched files (CF-06):** applies to the 5 new test files + `ci.yml` patches + Makefile/script changes. Since new test files are 100% new code, they trivially pass diff-cover. ci.yml patches are config; diff-cover may not enforce on YAML — verify in plan-checker.
- **22-00 OUT — small risk:** if 22-00 measurement reveals a module is already ≥70% (none currently are, per baseline table — but if integration tests close a gap), the corresponding 22-0X plan still ships its SC-prescribed tests AND closes its TEST-XX requirement. The ROADMAP SC says "≥70%", not "raise from <70%"; SC-listed branches must be tested regardless of starting cover.

</specifics>

<deferred>
## Deferred Ideas

### To v1.6+ (or later milestone)
- **Branch coverage activation** (`branch = true` in `[tool.coverage.run]`) — Phase 15 D-08 line-only carry-forward; v1.6+ candidate per Phase 15 commentary.
- **Mutation testing** (`mutmut` or `cosmic-ray`) — TEST-07 deferred to v1.4+ originally; still deferred. Phase 22 uses pure coverage as proxy.
- **Coverage shields.io / codecov badge in README** — Phase 15 D-11 explicitly out-of-scope; Phase 22 reaffirms.
- **Per-class coverage breakdown for pipeline.py** — D-05 rejected per-class option. If desired, future v1.6+ refactor splits pipeline.py into sub-modules (Ingestion, Query, AgentQuery, SwarmQuery as separate files); per-module 70% target then naturally met without the bundled-file mental gymnastics.
- **Floor raise above 70%** (e.g., 80%) — Phase 15 D-11 out-of-scope; v1.6+ candidate. Phase 22 stays at 70%.
- **`.planning/codebase/TESTING.md` refresh** — out-of-date map (lists 4 test files; current is 622+). Belongs in `/gsd-map-codebase` cycle, NOT Phase 22.
- **Coverage tracking dashboard** — out of scope; deferred indefinitely.
- **diff-cover threshold raise** (≥80% → ≥90% on touched files) — possible v1.6+ tightening; not in Phase 22.
- **PyMuPDF AGPL license resolution** — carry-forward todo from STATE; orthogonal to Phase 22 coverage work.

### To other phases (within v1.5 if any open)
- None — Phase 22 is the last v1.5 phase; no inter-phase carry remains.

### Reviewed Todos (not folded)
None — `cross_reference_todos` step found 0 phase-matched todos; nothing to review.

</deferred>

---

*Phase: 22 — Per-Module 70% Coverage Lift*
*Context gathered: 2026-05-10*
