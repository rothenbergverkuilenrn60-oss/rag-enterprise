# Phase 33: Autouse-Mock Opt-Out + Order-Dependent Failures — Research

**Researched:** 2026-05-18
**Domain:** Test infra (pytest fixtures, autouse mocks, singleton reset semantics, random-order plugin)
**Status:** Ready for planning
**Confidence:** HIGH for Q1–Q5 (verified by direct repro on this checkout); MEDIUM for Q6–Q8 (planner-judgment territory)

---

## Summary

- **Root cause of TEST-09 failures is precisely identified.** 6 of 7 failures share one root cause: `tests/factories/app.py:42` lists `services.agent.tools.registry._registry` in `_SINGLETON_INVENTORY`. Whenever `_reset_singletons()` runs (via `app_factory` / `isolated_app` / `isolated_client` fixtures), the registry singleton is set to `None`. The next caller of `get_tool_registry()` constructs a fresh empty `ToolRegistry()` — but the `@get_tool_registry().register` decorators only ran at module-import time on the OLD registry instance. Result: `get_tool_registry().list() == []` for all subsequent tests, and any test asserting a tool name is registered fails.
- **The 7th failure (`test_long_term_save_fact_calls_insert`)** is the only true `embed_one`/`embed_batch` mock-shape bug — `tests/unit/test_memory_service_extra.py:235` mocks `embed_one=AsyncMock(...)` but NOT `embed_batch`. Production callsite `services/memory/memory_service.py:640` does `await embedder.embed_batch(texts)`, which fails with `TypeError: object MagicMock can't be used in 'await' expression`. **This is the only `embed_*` mock-shape fix needed.** Other tests with embedder mocks already supply both methods.
- **Random-order pre-flight surfaced 5 additional failure clusters** beyond the named 7: `test_agent_pipeline_refactor.py` (4 tests, all 3 seeds) — same `_registry`-empty root cause; `test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls` + `test_ocr_failure_modes.py` (3 tests, 2 of 3 seeds) — `asyncio.Semaphore` cross-loop binding, **NOT** registry/embed scope; pure Phase 31 EVT-02 residue. **Planner decision required**: do we absorb the 4 agent-pipeline failures (same root cause, free fix) and defer OCR semaphore? Recommended yes — the registry reset fixes them all in one go.
- **TEST-08 canary is feasible** with sync test (`HuggingFaceEmbedder.__init__` and `CrossEncoderReranker.__init__` are both sync). Exact branch insertion point identified: `tests/integration/conftest.py:55` — early-return inserted before the `with patch.object(...)` block. Env probe via `resolve_embedding_model_path("bge-m3").exists()` (config/settings.py:43, already used by `embedder_or_mock` fixture in tests/conftest.py:155). Canary should skip cleanly (not error) when models absent.
- **Dual-write target confirmed**: pyproject.toml lines 78–93 `[dependency-groups] dev`; insert `"pytest-randomly>=3.16.0",` after `"pytest-cov==6.0.0",` line (alphabetical position). requirements-dev.txt: append at EOF with mirror comment per line-13 convention. `scripts/check_typing_hygiene.py:_STUB_NAME_RE` matches only `*-stubs` and `types-*` patterns → pytest-randomly is NOT flagged.

**Primary recommendation:** Implement TEST-09 with a minimal autouse function-scope fixture in `tests/conftest.py` that targets exactly **3** module-attr resets: `services.agent.tools.registry._registry`, plus `embed_batch` parity fix at `test_memory_service_extra.py:235`. The registry-reset fix alone clears 6 of 7 named failures + 4 of 5 random-order-only failures = 10 tests. Defer OCR semaphore to Phase 31 carry-over (or a future Phase 36 sweep). Expand acceptance per D-SEEDS-01 to include the 4 `test_agent_pipeline_refactor` tests as additional green-gate (free win, no scope creep).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Autouse mock with marker-based opt-out (TEST-08) | tests/integration/conftest.py | pytest.ini (marker registration) | conftest scope-localizes to integration; marker is shared metadata |
| Function-scope singleton reset fixture (TEST-09) | tests/conftest.py | tests/factories/app.py | conftest.py is the unit-scope autouse landing pad; factories owns the canonical inventory |
| pytest plugin registration | pyproject.toml + requirements-dev.txt | pytest.ini (none needed — auto-discovered) | dual-write per Phase 32 CI-gap lesson |
| Test-infra documentation | docs/RUNBOOK.md | — | RUNBOOK is the established ops/test infra doc location (10.3 KB, 3 top-level sections existing: Local dev, Ops, Troubleshooting) |

---

## Q1 — TEST-09 Singleton Inventory (D-RESET-01 audit-mode-before-enforce)

**Evidence (verified by direct repro on commit at HEAD 2026-05-18):**

Running `uv run pytest tests/unit/ -m 'not integration' -q --tb=line` from a clean state produces exactly 7 failures:

```
FAILED tests/unit/test_memory_service_extra.py::test_long_term_save_fact_calls_insert
FAILED tests/unit/test_pipeline_tool_schema_regression.py::test_registry_anthropic_shape_satisfies_call_agentic_turn
FAILED tests/unit/test_recall_tool.py::test_recall_tool_registered_once
FAILED tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_retrieve_tool_registered
FAILED tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_refine_tool_registered
FAILED tests/unit/test_retrieve_tool.py::TestSchemasForParity::test_retrieve_tool_xml_format_parity
FAILED tests/unit/test_web_search_tool.py::TestWebSearchToolRegistration::test_web_search_tool_registered
```

**This differs from CONTEXT.md's enumeration.** CONTEXT.md lists `TestWebSearchToolRun` (3 cases) + `TestWebSearchToolHelpers` (1 case); those classes all pass cleanly here (24/24 in isolation, 0 failures in the full suite). The actual 4 web_search-related failures are 1 from `Registration` + 3 from OTHER files (`memory_service_extra`, `pipeline_tool_schema_regression`, `recall_tool`). The planner should reference the verified list above, not CONTEXT.md's draft list.

**Traceback inspection of the 6 registry-failures (all identical pattern):**

```
AssertionError: assert 'search_knowledge_base' in []
 +  where [] = list()
 +    where list = <services.agent.tools.registry.ToolRegistry object at 0x...>.list
 +      where <ToolRegistry object> = get_tool_registry()
```

Root cause source path (file:line evidence):
- `services/agent/tools/registry.py:106` — `_registry: ToolRegistry | None = None`
- `services/agent/tools/registry.py:109-118` — `get_tool_registry()` lazy-inits a fresh `ToolRegistry()` whenever `_registry is None`
- `services/agent/tools/retrieve.py:161` — `@get_tool_registry().register` runs at module-import time and registers `RetrieveTool` on the registry instance that existed THEN
- `services/agent/tools/retrieve.py:209` — same for `RefinedRetrieveTool`
- `services/agent/tools/web_search.py:208` — same for `WebSearchTool`
- `services/agent/tools/recall.py:39` — same for `RecallTool`
- `tests/factories/app.py:42` — `("services.agent.tools.registry", "_registry")` listed in `_SINGLETON_INVENTORY`
- `tests/factories/app.py:69-79` — `_reset_singletons()` sets each `(mod, attr)` to `None`

**The leak demonstrates from these tests** (verified by grep `tests/unit/`):
- `tests/unit/test_app_factory.py:42,46` — directly calls `_reset_singletons()`
- `tests/unit/test_parallel_contamination.py:32-104` — uses `app_factory` fixture (which transitively calls `_reset_singletons`)
- `tests/unit/test_redis_mock_fixture.py:114-123` — uses `app_factory`

Once any of these run BEFORE a registration test, the registry is empty for every subsequent test.

**Traceback inspection of the 7th failure (`test_long_term_save_fact_calls_insert`):**

```
E       TypeError: object MagicMock can't be used in 'await' expression
services/memory/memory_service.py:640: TypeError
```

File:line evidence:
- `tests/unit/test_memory_service_extra.py:235` — `fake_embedder = MagicMock(embed_one=AsyncMock(return_value=[0.1] * 1024))` — note: only `embed_one` provided
- `services/memory/memory_service.py:640` — `embeddings = list(await embedder.embed_batch(texts))` — production callsite uses `embed_batch`, not `embed_one`

This is a mock-shape parity bug, exactly as TEST-09 acceptance describes — but it's the ONLY one in the unit-test suite (verified by `grep -rn "embed_one=\|embed_batch=" tests/`).

**Recommendation — bounded reset list (audit-mode-before-enforce):**

The reset fixture in `tests/conftest.py` should target exactly these singletons (and document why each is in the list):

| Module | Attribute | Why it must reset between tests |
|--------|-----------|--------------------------------|
| `services.agent.tools.registry` | `_registry` | Fix all 6 registry-empty failures + 4 `test_agent_pipeline_refactor` random-order failures |

**This is a single-entry reset list.** Do NOT broaden to the full 34-entry `_SINGLETON_INVENTORY` — that's `tests/factories/app.py`'s job (called explicitly by `app_factory` fixture, not autouse). The audit-mode discipline says "reset only what demonstrates leak in the named failing tests."

**Critical caveat — registry reset alone is not enough.** Setting `_registry = None` causes the next `get_tool_registry()` call to instantiate an empty registry — the `@register` decorators won't re-run. The fixture must ALSO trigger re-registration. Two options for the planner to pick:

**Option A (recommended): import-induced re-registration.** After zeroing `_registry`, the fixture imports the four tool modules so their module-level `@get_tool_registry().register` decorators fire against the new instance:

```python
@pytest.fixture(autouse=True)
def _reset_tool_registry():
    import services.agent.tools.registry as _reg
    _reg._registry = None
    # Force re-registration by re-importing the side-effect modules.
    # `importlib.reload` is required — plain `import` is a no-op for
    # already-imported modules.
    import importlib
    import services.agent.tools.retrieve
    import services.agent.tools.web_search
    import services.agent.tools.recall
    importlib.reload(services.agent.tools.retrieve)
    importlib.reload(services.agent.tools.web_search)
    importlib.reload(services.agent.tools.recall)
    yield
```

Risk: `importlib.reload` is heavy-handed; some tests `monkeypatch.setattr` on `services.agent.tools.web_search.<x>` and a reload during teardown could break them. Planner should test ordering carefully.

**Option B (lighter, recommended for the actual implementation): seed the freshly-created registry.** After zeroing, the fixture pre-populates the registry from the known tool classes (no reload needed, no monkeypatch interference):

```python
@pytest.fixture(autouse=True)
def _reset_tool_registry():
    import services.agent.tools.registry as _reg
    from services.agent.tools.retrieve import RetrieveTool, RefinedRetrieveTool
    from services.agent.tools.web_search import WebSearchTool
    from services.agent.tools.recall import RecallTool
    _reg._registry = None
    reg = _reg.get_tool_registry()  # constructs fresh empty registry
    for tool_cls in (RetrieveTool, RefinedRetrieveTool, WebSearchTool, RecallTool):
        reg.register(tool_cls)
    yield
    _reg._registry = None  # leave clean for next test
```

Risk: tool inventory drift — if a new tool is added to `services/agent/tools/`, the fixture must be updated. Mitigate with a unit test that compares the fixture's inventory to a `pkgutil.iter_modules`-derived list.

**Planner picks A vs B.** The discuss-phase D-RESET-01 said "explicitly named singletons that the 7 failing tests demonstrate leak" — Option B matches that spirit (explicit, named, narrow).

---

## Q2 — TEST-09 Acceptance Seed Pre-Flight (D-SEEDS-01)

**Evidence — installed `pytest-randomly==4.1.0` for pre-flight, ran 3 acceptance seeds, then UNINSTALLED to restore baseline (verified `grep pytest-randomly pyproject.toml` returns nothing).**

Per-seed result against current main (no TEST-09 fix yet):

| Seed | Failed | Passed | Skipped |
|------|--------|--------|---------|
| 12345 | **12** | 1243 | 2 |
| 67890 | **12** | 1243 | 2 |
| 99999 | **11** | 1244 | 2 |

**Per-seed failure decomposition** (verified `grep "^FAILED"` output):

| Failure | seed 12345 | seed 67890 | seed 99999 | Root cause cluster |
|---------|:----------:|:----------:|:----------:|--------------------|
| `test_retrieve_tool.py::TestRetrieveToolRegistration::test_retrieve_tool_registered` | ✗ | ✗ | ✗ | A. `_registry` reset |
| `test_retrieve_tool.py::TestRetrieveToolRegistration::test_refine_tool_registered` | ✗ | ✗ | ✗ | A |
| `test_retrieve_tool.py::TestSchemasForParity::test_retrieve_tool_xml_format_parity` | ✗ | ✗ | ✗ | A |
| `test_web_search_tool.py::TestWebSearchToolRegistration::test_web_search_tool_registered` | ✗ | ✗ | ✗ | A |
| `test_recall_tool.py::test_recall_tool_registered_once` | ✗ | ✗ | ✗ | A |
| `test_pipeline_tool_schema_regression.py::test_registry_anthropic_shape_satisfies_call_agentic_turn` | ✗ | ✗ | ✗ | A |
| `test_memory_service_extra.py::test_long_term_save_fact_calls_insert` | ✗ | ✗ | ✗ | B. `embed_batch` mock-shape |
| `test_agent_pipeline_refactor.py::test_single_tool_call_uses_gather` | ✗ | ✗ | ✗ | A (transitive via Executor) |
| `test_agent_pipeline_refactor.py::test_chunk_dedup_runs_after_gather_not_inside` | ✗ | ✗ | ✗ | A |
| `test_agent_pipeline_refactor.py::test_two_tool_calls_run_concurrently` | ✗ | ✗ | ✗ | A |
| `test_agent_pipeline_refactor.py::test_tool_exception_becomes_is_error_tool_result` | ✗ | ✗ | ✗ | A |
| `test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls` | ✗ | ✗ | — | C. `asyncio.Semaphore` loop |
| `test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore` | — | — | ✗ | C |
| `test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error` | — | — | ✗ | C |
| `test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry` | — | — | ✗ | C |

**Cluster summary:**
- **Cluster A** (registry empty / `_registry` singleton pollution): 10 failures total — the 6 from the named-7 list + 4 from `test_agent_pipeline_refactor.py` (same root cause, transitively via `mock_pipeline` fixture which constructs an `Executor` that needs the tool registry). Fix once with Option B reset fixture above; all 10 turn green.
- **Cluster B** (`embed_batch` mock-shape): 1 failure (`test_memory_service_extra.py:235`). Fix locally by adding `embed_batch=AsyncMock(return_value=[[0.1] * 1024])` to the `MagicMock(...)` kwargs.
- **Cluster C** (OCR `asyncio.Semaphore` loop binding): 3 distinct failures in `test_ocr_engine.py` + `test_ocr_failure_modes.py`. **OUT OF SCOPE for TEST-09** — root cause is `services/extractor/ocr_engine.py:65 _sem` being bound to a stale event loop, not registry or embed-mock. This is Phase 31 EVT-02 territory (already shipped — the fact that this slipped through is a Phase 31 carry-over). Recommended planner action: surface in `## Open Questions` of the plan, defer to a follow-up phase (or amend Phase 31 retroactively), do NOT widen TEST-09 scope.

**Acceptance contract update — what the planner should bake into D-VERIFY-01b:**

After TEST-09 lands, acceptance is:
- `--randomly-seed=12345` → from 12 failed → at most 1 failed (OCR cluster C)
- `--randomly-seed=67890` → from 12 failed → at most 1 failed (OCR cluster C)
- `--randomly-seed=99999` → from 11 failed → at most 3 failed (OCR cluster C variants)

To make the acceptance gate machine-checkable and not paper over cluster C, the planner should use **deselection** for the OCR cluster: `-m 'not integration and not ocr_random_order_known_bug'` or `--deselect tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry`. This documents the deferral in the plan rather than hiding it.

**Recommendation:**

1. Expand the TEST-09 acceptance set to include the 4 `test_agent_pipeline_refactor.py` tests as "free wins" — the planner notes them explicitly as in-scope absorption.
2. Document the OCR cluster as out-of-scope in `33-01-PLAN.md` `<deferred>` (or `<out_of_scope>`) section. Add a new requirement candidate to `.planning/REQUIREMENTS.md` (e.g., `TEST-12` or amend EVT-02) for v1.10 — do NOT silently absorb.
3. The 3 acceptance seeds (12345, 67890, 99999) are valid — they all exhibit cluster A + cluster B + cluster C, so all 3 will validate the TEST-09 fix (after the cluster C deselection).

---

## Q3 — TEST-09 Mock-Shape Parity (D-MOCK-01 no compat shim)

**Evidence — exhaustive audit of all `embed_one=` / `embed_batch=` patterns in `tests/`:**

```
tests/integration/memory/test_save_facts_toctou.py:79-80     — provides BOTH
tests/unit/test_memory_save_fact.py:119                       — provides BOTH
tests/unit/test_memory_save_fact.py:189-190                   — provides BOTH (side_effect)
tests/unit/test_memory_service_extra.py:235                   — ONLY embed_one  ← BUG
tests/unit/memory/test_save_facts_batch.py:97-98              — provides BOTH
tests/unit/memory/test_save_facts_embed_batch_fallback.py:112 — provides BOTH
tests/unit/memory/test_save_facts_batch_dedupe.py:91-92       — provides BOTH
tests/unit/memory/test_save_facts_lock_failure.py:106-107     — provides BOTH
tests/unit/memory/test_save_fact_precheck_failure.py:117-118  — provides BOTH
tests/unit/memory/test_save_fact_precheck.py:119-120          — provides BOTH
```

**Single bug site confirmed: `tests/unit/test_memory_service_extra.py:235`.**

Consumer path walk (verified by `grep -rn "embed_one\b" services/`):

| Callsite | File:Line | Method | Notes |
|----------|-----------|--------|-------|
| `LongTermMemory.save_facts` | services/memory/memory_service.py:640 | `embed_batch` | Happy path (single call for all texts) |
| `LongTermMemory.save_facts` fallback | services/memory/memory_service.py:650 | `embed_one` | C2 fallback when `embed_batch` raises |
| `LongTermMemory.get_relevant_facts` | services/memory/memory_service.py:400 | `embed_one` | Query embed (single-text) — legitimate single-shot path |
| `Retriever._retrieve_chunks` | services/retriever/retriever.py:466 | `embed_one` | Single query embed |
| `Retriever._fan_out_queries` | services/retriever/retriever.py:561 | `embed_one` | Per-query embed (gather in loop) |
| `summary_indexer.search_summaries` | services/knowledge/summary_indexer.py:103 | `embed_one` | Single query |
| `summary_indexer.index_documents` | services/knowledge/summary_indexer.py:259 | `embed_batch` | Bulk embed |
| `knowledge_service.upsert_documents` | services/knowledge/knowledge_service.py:143 | `embed_batch` | Bulk embed |
| `indexer.index_chunks` | services/vectorizer/indexer.py:119 | `embed_batch` | Bulk embed |
| `extractor.dedupe_facts` (commented) | services/agent/extractor.py:257 | `embed_batch` | Doc reference |

**Production `embed_one` is NOT a straggler — it has 5 legitimate single-shot consumers** (memory query, retriever query, fan-out queries, summary search, save_facts fallback). `BaseEmbedder.embed_one` is also defined in `services/vectorizer/embedder.py:32-34` and `BatchedEmbedder.embed_one` at line 152, both delegating to `embed_batch([text])[0]`. No compat shim is required because `embed_one` is the canonical name for single-text embedding — both methods are equally first-class in the production API.

**The `test_memory_service_extra.py:235` bug is NOT a fixture-design problem;** it's a stale per-test mock from before Phase 27 / TD-05 added the batch path inside `save_fact` → `save_facts`. The other 9 test files already supply both methods; only this one drifted.

**For the failing test specifically** — `test_long_term_save_fact_calls_insert` (`tests/unit/test_memory_service_extra.py:233-242`):

```python
fake_embedder = MagicMock(embed_one=AsyncMock(return_value=[0.1] * 1024))
monkeypatch.setattr(
    "services.vectorizer.embedder.get_embedder", lambda: fake_embedder
)
conn = MagicMock()
conn.execute = AsyncMock()
lt = _make_long(_make_pool(conn))
await lt.save_fact("u1", "t1", fact="xyz")
```

**Recommended fix (one line):**

```python
fake_embedder = MagicMock(
    embed_one=AsyncMock(return_value=[0.1] * 1024),
    embed_batch=AsyncMock(return_value=[[0.1] * 1024]),  # post-v1.7 batch API; save_fact → save_facts → embed_batch
)
```

Mock-at-consumer convention (v1.3 D-mock) is preserved — patches `services.vectorizer.embedder.get_embedder` (consumer path inside `services.memory.memory_service`).

**No production `embed_one` straggler exists, no compat shim is needed, no follow-up surfacing.** D-MOCK-01 holds verbatim.

---

## Q4 — TEST-08 Canary Feasibility

**Evidence:**

`tests/integration/conftest.py:55-58` (the autouse fixture body — current state):

```python
with (
    patch.object(_embedder_mod.HuggingFaceEmbedder, "__init__", _noop_embedder_init),
    patch.object(_retriever_mod.CrossEncoderReranker, "__init__", _noop_reranker_init),
):
    yield
```

The fixture signature on line 26 is currently `def _mock_local_model_inits() -> object:` (NO `request: pytest.FixtureRequest` parameter). **Adding the `request` parameter is the first edit** — it cannot detect the marker without it.

**Exact branch insertion point (between current lines 54 and 55):**

```python
@pytest.fixture(autouse=True)
def _mock_local_model_inits(request: pytest.FixtureRequest) -> object:  # NEW signature
    ...
    def _noop_reranker_init(...): ...

    # NEW BRANCH — TEST-08 opt-out
    if request.node.get_closest_marker("real_embedder") is not None:
        yield
        return

    with (
        patch.object(...),
        patch.object(...),
    ):
        yield
```

**Confirmed pattern (file:line):**

| Confirmation | Source |
|--------------|--------|
| `HuggingFaceEmbedder.__init__` is sync | services/vectorizer/embedder.py:106 (`def __init__(self) -> None:`) |
| `CrossEncoderReranker.__init__` is sync | services/retriever/retriever.py:138 (`def __init__(self) -> None:`) |
| `pytestmark = [pytest.mark.integration, pytest.mark.real_llm]` is established | tests/integration/test_filter_extractor_llm.py:21 |
| Path resolver for `bge-m3` exists + handles 3 layouts | config/settings.py:30-65 (`resolve_embedding_model_path(name)`) |
| Resolver is already used by a sibling fixture | tests/conftest.py:155 (`resolve_embedding_model_path("bge-m3").exists()`) |
| `embed_batch` on real `HuggingFaceEmbedder` is async | services/vectorizer/embedder.py:115 (`async def embed_batch(...)`) |
| `CrossEncoder.predict` is sync (called via `to_thread` if needed) | sentence_transformers convention; reranker doesn't expose async wrapper |
| `addopts = -m "not integration"` excludes integration by default | pytest.ini:15 |
| `real_llm` marker already excluded via `-m 'integration and not real_llm and not benchmark'` standard filter | per CONTEXT.md D-VERIFY-02 |

**Sync vs async canary decision: sync `def test_real_embedder_models_load_and_encode()`** is the safer choice for the `__init__` invocation + sync `predict`. But because `HuggingFaceEmbedder.embed_batch` is async, the canary needs at least an `async def` wrapper or `asyncio.run(...)` to call `encode`. Recommended shape: `async def test_real_embedder_models_load_and_encode():` (asyncio_mode=auto in pytest.ini line 2 means `pytest-asyncio` will auto-recognize). Use `await embedder.embed_batch(["hello"])` and `reranker._model.predict([("q", "d")])` (the `_model` is the bare `CrossEncoder` after real init, and its `.predict` is sync).

**Canary skip-on-missing-models logic:**

The autouse fixture won't mock when the marker is present, so `HuggingFaceEmbedder.__init__` will run the real `SentenceTransformer(model_path, device=...)` constructor — which raises `OSError` / `FileNotFoundError` when `embedding_model_path` doesn't exist. Two options:

**A (recommended): explicit skipif in the canary file.**
```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_embedder,
    pytest.mark.skipif(
        not _bge_m3_present(),
        reason="bge-m3 not present at APP_MODEL_DIR; see docs/RUNBOOK.md test infra section",
    ),
]
```
Where `_bge_m3_present()` calls `resolve_embedding_model_path("bge-m3").exists()` AND `resolve_embedding_model_path("bge-m3-rerank").exists()`. This makes the skip explicit and the reason scannable.

**B (relies on raised FileNotFoundError as signal):** Per D-OPTOUT-01 — "Acceptance test: a marked test sees the real HuggingFaceEmbedder.__init__ (which raises FileNotFoundError if bge-m3 absent — that's the expected, documented signal)". This is fine for the integration *fixture* contract but a poor user experience for the canary itself: a raised exception = test ERROR (not SKIP), which dirties the integration baseline (D-VERIFY-02). Recommended: pick A so the baseline stays clean.

**Recommendation — canary structure:**

```python
# tests/integration/test_real_embedder_canary.py
"""TEST-08 canary — opt-out of autouse mock loads real bge-m3 + bge-m3-rerank.

Marker @pytest.mark.real_embedder triggers the early-return in
tests/integration/conftest.py::_mock_local_model_inits, exposing the
real HuggingFaceEmbedder.__init__ + CrossEncoderReranker.__init__ paths.

Default CI: skipped (bge-m3 absent OR not in `-m "real_embedder"`).
Run with: pytest tests/integration/test_real_embedder_canary.py -m real_embedder
"""
from __future__ import annotations

import pytest

from config.settings import resolve_embedding_model_path


def _models_present() -> bool:
    return (
        resolve_embedding_model_path("bge-m3").exists()
        and resolve_embedding_model_path("bge-m3-rerank").exists()
    )


pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_embedder,
    pytest.mark.skipif(
        not _models_present(),
        reason="bge-m3 / bge-m3-rerank not present at $APP_MODEL_DIR; see docs/RUNBOOK.md",
    ),
]


@pytest.mark.asyncio
async def test_real_embedder_models_load_and_encode() -> None:
    from services.retriever.retriever import CrossEncoderReranker
    from services.vectorizer.embedder import HuggingFaceEmbedder

    embedder = HuggingFaceEmbedder()
    vectors = await embedder.embed_batch(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024  # bge-m3 native dim

    reranker = CrossEncoderReranker()
    scores = reranker._model.predict([("q", "d")])
    assert len(scores) == 1
    assert isinstance(float(scores[0]), float)
```

**~30 LOC, matches D-CANARY-01 budget.**

---

## Q5 — Dual-Write CI Gap (Phase 32 carry-forward)

**Evidence (file:line):**

`pyproject.toml:78-93` current state:

```
[dependency-groups]
dev = [
    "asyncpg-stubs~=0.30.2",
    "bandit>=1.8.0",
    "diff-cover>=9.7.2",
    "fakeredis>=2.35.1",
    "mypy>=1.14.0",
    "pandas-stubs>=3.0.0.260204",
    "pytest==9.0.3",
    "pytest-asyncio>=1.3.0",
    "pytest-cov==6.0.0",
    "pytest-timeout==2.3.1",
    "python-pptx>=1.0.2",
    "ruff>=0.8.6",
    "types-requests>=2.32.0",
]
```

Alphabetical order. Insert `"pytest-randomly>=3.16.0",` between `"pytest-cov==6.0.0",` (line 88) and `"pytest-timeout==2.3.1",` (line 89). Final position after sort: `"pytest-cov" < "pytest-randomly" < "pytest-timeout"` ✓.

`requirements-dev.txt` current state (full file, 13 non-blank lines):

```
# 开发/CI 依赖（不包含在生产镜像中）
ruff==0.8.6
mypy==1.14.0
bandit==1.8.0
types-requests>=2.32.0
pytest==9.0.3
pytest-asyncio>=1.3.0
pytest-timeout==2.3.1
pytest-cov==6.0.0
diff-cover==9.7.2       # PR-only diff coverage gate (TEST-03 / D-04, D-05)
fakeredis==2.35.1       # In-process Redis fake for ARQ test fixtures (ASYNC-01/02)
asyncpg-stubs~=0.30.2  # Type stubs for asyncpg==0.30.0 runtime (MYPY-02/04 — mirrors pyproject.toml [dependency-groups].dev)
pandas-stubs>=3.0.0.260204  # Type stubs for pandas==3.0.2 runtime (MYPY-02 — mirrors pyproject.toml [dependency-groups].dev)
```

**Format observation:** `requirements-dev.txt` is NOT alphabetical — it's loosely grouped (lint/type first, test second, type-stubs last). The latest additions (asyncpg-stubs, pandas-stubs) appended at EOF with inline comments referencing the pyproject mirror. Follow that convention for pytest-randomly.

**Exact line to append to `requirements-dev.txt`:**

```
pytest-randomly>=3.16.0  # Random-order test plugin (TEST-09 — mirrors pyproject.toml [dependency-groups].dev)
```

**`scripts/check_typing_hygiene.py` regex verification (file:line):**

The regex at `_STUB_NAME_RE` (verified) matches:
- `[\w.-]+-stubs` (e.g., `asyncpg-stubs`, `pandas-stubs`)
- `types-[\w.-]+` (e.g., `types-requests`)

Both patterns. `pytest-randomly` matches NEITHER (it's not `*-stubs` nor `types-*`). Confirmed safe — the hygiene gate will not flag this addition. The dual-write discipline still applies (per CONTEXT D-PLUGIN-01) but for hygiene of the dev-deps surface, not because the script enforces it for non-stub packages.

**Confirmed dual-write strategy:**

1. Edit `pyproject.toml` line 89 (insert).
2. Edit `requirements-dev.txt` EOF (append).
3. Run `uv lock --check` after to confirm no drift.

---

## Q6 — Risk + Sequencing

**Within `33-00-PLAN.md` (TEST-08) — recommended task order:**

1. **Task 1: Register `real_embedder` marker in `pytest.ini`** (lines 10-14). Single-line append. **No new test depends on this yet** — safe to land first, but also could be combined with task 2 since neither depends on the other.
2. **Task 2: Edit `tests/integration/conftest.py`** to add `request` parameter + opt-out branch (lines 25-26 + insert at 55). Verify integration suite still green via `uv run pytest -m 'integration and not real_llm and not benchmark' -q` — no test in the suite carries `real_embedder` marker yet, so behavior should be UNCHANGED.
3. **Task 3: Add canary `tests/integration/test_real_embedder_canary.py`** (~30 LOC). The skipif gate makes it safe to land without bge-m3 models present.
4. **Task 4: Document in `docs/RUNBOOK.md`** under new `## Test Infrastructure` section (file currently has 3 top-level sections: Local dev, Ops, Troubleshooting — insert new section between Ops and Troubleshooting at line ~185).

**Why this order:** marker before fixture so the fixture edit can be validated end-to-end (run canary with marker → fixture sees marker → real embedder hit). Canary 3rd: depends on both 1 and 2. Docs last: pure prose.

**Within `33-01-PLAN.md` (TEST-09) — recommended task order:**

1. **Task 1: Install `pytest-randomly`** (dual-write `pyproject.toml` + `requirements-dev.txt`). Lands first so subsequent tasks can validate against random-order runs immediately.
2. **Task 2: Fix `embed_batch` mock-shape parity** at `tests/unit/test_memory_service_extra.py:235`. One-line change; verifies cluster B turns green in isolation.
3. **Task 3: Add registry reset fixture** in `tests/conftest.py` (Option B from Q1). The fixture lands here, not in `tests/factories/app.py`, because (a) `tests/conftest.py` is the unit-scope autouse landing pad, and (b) it's already where the existing autouse `pytest_collection_modifyitems` hook lives (line 238+). Document the 3 acceptance seeds in a docstring per D-SEEDS-01.
4. **Task 4: Run acceptance seeds + verify** — three `pytest -p randomly --randomly-seed=N` invocations + deselect the OCR cluster (per Q2 recommendation). Plan should specify the exact `--deselect` args so plan-checker can verify.

**Why this order:** plugin first → mock fix second (lowest-risk, narrow scope) → fixture third (highest-impact change) → verify last. Risk-ascending order limits blast radius on any single task failure.

**Risk callouts for the planner:**

- **R1 (fixture interaction):** The reset fixture is autouse function-scope at `tests/conftest.py` root scope, so it fires for ALL unit tests (1248 tests). Even adding 1ms of overhead × 1248 = 1.2 seconds added to suite runtime. Option B's per-test re-registration is ~4 imports + 4 register calls — should be sub-ms in practice. **Validate runtime cost** in plan acceptance: full unit suite runtime should not regress >5%.
- **R2 (integration suite blind spot):** The reset fixture in `tests/conftest.py` is automatically inherited by `tests/integration/conftest.py` (subdirectory). Verify this doesn't conflict with the integration suite's own autouse `_mock_local_model_inits` fixture (Phase 30-02). They operate on disjoint module surfaces (`services.agent.tools.registry` vs `services.vectorizer.embedder.HuggingFaceEmbedder.__init__`), so they should compose cleanly. **Plan should include `uv run pytest -m 'integration and not real_llm' -q` as a non-regression gate.**
- **R3 (plan-checker may flag the failure-list discrepancy):** CONTEXT.md enumerates a partially-wrong failure list. Plan should reference the verified list from this RESEARCH.md (Q1) and add a one-line note: "Failing-test inventory verified at 2026-05-18 HEAD; supersedes CONTEXT.md `<canonical_refs>` block which lists outdated `TestWebSearchToolRun` + `TestWebSearchToolHelpers` entries."

---

## Validation Architecture

> Q7 — Nyquist gates for both plans

Per `.planning/STATE.md` Phase 33 is in the v1.9 Hardening Round 3 milestone which runs Nyquist validation. Both plans need Nyquist gates.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 |
| Config file | `pytest.ini` (5 lines of markers + 1 line addopts) |
| Quick run command | `uv run pytest tests/unit/test_<file>.py -q` |
| Full suite command | `uv run pytest tests/unit/ -m 'not integration' -q` |

### TEST-08 — Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-08a | `real_embedder` marker registered | smoke | `grep -q 'real_embedder:' pytest.ini` | ❌ Wave 0 (pytest.ini edit) |
| TEST-08b | Autouse fixture honors marker | unit | `grep -q 'get_closest_marker("real_embedder")' tests/integration/conftest.py` | ❌ Wave 0 (conftest edit) |
| TEST-08c | Canary file exists + structured correctly | smoke | `test -f tests/integration/test_real_embedder_canary.py` | ❌ Wave 0 (new file) |
| TEST-08d | Canary skips cleanly when models absent | integration | `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → 1 skipped OR 1 passed | ❌ Wave 0 |
| TEST-08e | Docs section exists | smoke | `grep -q '^## Test Infrastructure' docs/RUNBOOK.md` | ❌ Wave 0 (RUNBOOK edit) |
| TEST-08f | Integration baseline unchanged | regression | `uv run pytest -m 'integration and not real_llm and not real_embedder and not benchmark' --tb=no -q` → matches 31 passed / 9 failed / 1 skipped / 3 errors (per Phase 32 close) | ✅ existing |

### TEST-09 — Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-09a | pytest-randomly installed (pyproject) | smoke | `uv pip show pytest-randomly \| grep -q 'Version: 3.16'` (or ≥3.16) | ❌ Wave 0 (dep install) |
| TEST-09b | pytest-randomly in requirements-dev.txt | smoke | `grep -q '^pytest-randomly' requirements-dev.txt` | ❌ Wave 0 (dep mirror) |
| TEST-09c | Reset fixture lands in tests/conftest.py | smoke | `grep -q '_reset_tool_registry\|reset_tool_registry' tests/conftest.py` | ❌ Wave 0 (new fixture) |
| TEST-09d | Seed 12345 green (minus OCR cluster) | unit suite | `uv run pytest tests/unit/ -m 'not integration' -p randomly --randomly-seed=12345 --deselect tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error --deselect tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry -q` → 0 failed | ✅ via plugin |
| TEST-09e | Seed 67890 green (minus OCR cluster) | unit suite | same as 09d with `--randomly-seed=67890` | ✅ via plugin |
| TEST-09f | Seed 99999 green (minus OCR cluster) | unit suite | same as 09d with `--randomly-seed=99999` | ✅ via plugin |
| TEST-09g | 7 named failures resolved | unit | `uv run pytest tests/unit/test_memory_service_extra.py::test_long_term_save_fact_calls_insert tests/unit/test_pipeline_tool_schema_regression.py::test_registry_anthropic_shape_satisfies_call_agentic_turn tests/unit/test_recall_tool.py::test_recall_tool_registered_once tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration tests/unit/test_retrieve_tool.py::TestSchemasForParity tests/unit/test_web_search_tool.py::TestWebSearchToolRegistration -q` → all green | ✅ existing |
| TEST-09h | Integration baseline unchanged | regression | same as TEST-08f (per D-VERIFY-02) | ✅ existing |
| TEST-09i | Unit-suite runtime non-regression | perf | full suite < 1.05× Phase 32 baseline (~20 sec) | ✅ existing |

### Sampling Rate
- **Per task commit (unit work):** `uv run pytest tests/unit/<touched_file>.py -q` (~1-3 sec per file)
- **Per wave merge:** `uv run pytest tests/unit/ -m 'not integration' -q` (~20 sec)
- **Phase gate:** TEST-08a-f + TEST-09a-i all pass before `/gsd:verify-work`

### Wave 0 Gaps (for 33-00 TEST-08)
- [ ] `tests/integration/test_real_embedder_canary.py` — new file (~30 LOC)
- [ ] `docs/RUNBOOK.md` — new `## Test Infrastructure` section
- [ ] `tests/integration/conftest.py` — edit fixture signature + add opt-out branch
- [ ] `pytest.ini` — append `real_embedder:` marker entry

### Wave 0 Gaps (for 33-01 TEST-09)
- [ ] `tests/conftest.py` — add `_reset_tool_registry` autouse fixture
- [ ] `tests/unit/test_memory_service_extra.py` — line 235 mock-shape patch
- [ ] `pyproject.toml` + `requirements-dev.txt` — pytest-randomly dual-write
- [ ] Framework install: `uv add --dev "pytest-randomly>=3.16.0"`

---

## Q8 — Out-of-Scope Guardrails

**Reproducing the `<deferred>` block from CONTEXT.md** (the planner must not violate any of these):

| Deferred item | Why deferred | Tempting expansion to AVOID |
|---------------|--------------|------------------------------|
| Full unit suite random-order hardening (all seeds, not just 3) | TEST-09 acceptance is bounded to 3 seeds | Planner must NOT add seeds 4..N or nightly multi-seed CI |
| Promote existing tests to `@pytest.mark.real_embedder` | D-CANARY-01 explicitly minimal | Planner must NOT touch `extractor_e2e`, `test_filter_extractor_llm`, or any other existing integration test |
| Broad singleton-tracking infrastructure (decorator-based auto-reset) | D-RESET-01 explicit | Planner must NOT use `_SINGLETON_INVENTORY` as the reset target; must keep the autouse fixture's reset list narrow (single entry: `_registry`) |
| Compat shim for `embed_one` | D-MOCK-01 rejects | Planner must NOT add a wrapper that makes `embed_one` and `embed_batch` interchangeable in tests |
| Adding `pytest-randomly` to CI as default | TEST-09 is local + on-demand | Planner must NOT modify `.github/workflows/*.yml` or `Makefile` CI targets |

**Newly-surfaced guardrail (from Q2 findings):**

| New deferral | Reason | Tempting expansion to AVOID |
|--------------|--------|------------------------------|
| OCR semaphore loop-binding fix (`test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls` + 3 `test_ocr_failure_modes.py` variants) | Root cause is `asyncio.Semaphore` on stale loop; squarely Phase 31 EVT-02 territory, not registry or embed scope | Planner must NOT add OCR semaphore handling to TEST-09. Document the 4 failures in `<deferred>` / `<open_questions>` block of `33-01-PLAN.md` and recommend amending REQUIREMENTS.md with a `TEST-12` candidate (or expanding EVT-02 in v1.10) |

**Planner verification checklist** (paste verbatim into PLAN.md as a footer):

- [ ] Plan files touch ONLY: `pytest.ini`, `tests/integration/conftest.py`, `tests/integration/test_real_embedder_canary.py`, `docs/RUNBOOK.md` (TEST-08) ∪ `pyproject.toml`, `requirements-dev.txt`, `tests/conftest.py`, `tests/unit/test_memory_service_extra.py` (TEST-09). Any other file = scope violation.
- [ ] Reset fixture inventory has ≤ 2 entries (recommended: 1 — `services.agent.tools.registry._registry`).
- [ ] No `--randomly-seed` value other than 12345, 67890, 99999 in acceptance commands.
- [ ] No `.github/`, `Makefile`, or CI-config file touched.
- [ ] No existing test (other than `test_memory_service_extra.py:235` mock-shape line) is modified.

---

## Acceptance Pre-Flight Results

Captured via `uv add --dev "pytest-randomly>=3.16.0"` (subsequently removed to restore baseline).

| Seed | Total tests | Failed | Passed | Skipped | Failure cluster summary |
|------|------------:|-------:|-------:|--------:|-------------------------|
| 12345 | 1257 | 12 | 1243 | 2 | A=10, B=1, C=1 |
| 67890 | 1257 | 12 | 1243 | 2 | A=10, B=1, C=1 |
| 99999 | 1257 | 11 | 1244 | 2 | A=7, B=1, C=3 |

**After expected TEST-09 fix (Option B reset fixture + `embed_batch` mock parity), projected:**

| Seed | Failed (TOTAL) | Failed (excl. cluster C deselect) |
|------|---------------:|----------------------------------:|
| 12345 | 1 (OCR) | **0** |
| 67890 | 1 (OCR) | **0** |
| 99999 | 3 (OCR) | **0** |

Cluster C (OCR `asyncio.Semaphore` loop-binding) is deselected per Q2 recommendation; documented as deferred carry-over.

---

## Project Constraints (from CLAUDE.md)

| Directive | How TEST-09 honors it |
|-----------|------------------------|
| Production-grade only; no prototype code | Reset fixture is narrow + documented; not a sketch |
| No bare `except`; narrow exception types | N/A (no exception handling added) |
| Adapter pattern for external deps | N/A (test-infra only) |
| Tenacity retry for external calls | N/A |
| Structured logging | N/A (test fixtures don't emit logs to prod sinks) |
| Mock at consumer path (v1.3 D-mock) | `embed_batch` mock-fix patches `services.vectorizer.embedder.get_embedder` (already consumer-path); reset fixture re-registers tool classes onto the registry — no monkeypatch on production code |
| `# type: ignore[code]  # why:` if mypy silence needed | Unlikely needed; if reset fixture adds `# type: ignore[attr-defined]` (e.g., for setting `_registry = None`), follow Phase 32 form |
| Phase 32 typing-hygiene gate | `pytest-randomly` is not a `*-stubs` package → script's `_STUB_NAME_RE` does NOT match → safe to add to both files |

| Directive | How TEST-08 honors it |
|-----------|------------------------|
| Production-grade | Canary is minimal but production-quality (skipif guard, dual marker, type annotations) |
| Narrow exception types | N/A |
| Mock at consumer path | Autouse fixture continues to `patch.object(<mod>.<Class>, "__init__", ...)` per Phase 30-02 |

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | `_reset_singletons()` in `tests/factories/app.py` is the trigger for `_registry = None` | Q1 | Low — verified via grep + `_SINGLETON_INVENTORY` listing line 42 |
| A2 | Option B (re-register via explicit class imports) won't conflict with `monkeypatch.setattr` patterns in TestWebSearchToolRun | Q1 / Q6 R1 | MEDIUM — recommend planner add a probe task: run TestWebSearchToolRun after Task 3 to confirm |
| A3 | Cluster C (OCR Semaphore) is Phase 31 EVT-02 residue and not new debt introduced post-Phase 31 close | Q2 / Q8 | LOW — OCR `_sem` is at services/extractor/ocr_engine.py:65; Phase 31 inventory work covered ~10 sites; this is plausibly one of the deferred ~10 |
| A4 | `pytest-randomly` 4.1.0 (latest stable) is compatible with `pytest 9.0.3` + `pytest-asyncio 1.3.0` already in the lockfile | Q5 / Q6 | LOW — pre-flight install succeeded; 1257 tests collected and ran; no plugin-conflict errors. CONTEXT.md asked for `>=3.16.0`; 4.1.0 satisfies. Planner may pin to `>=3.16.0` (open upper) per CONTEXT |
| A5 | The 4 `test_agent_pipeline_refactor` failures will resolve cleanly via the registry-reset fixture (cluster A transitive) | Q2 | LOW — verified the mock_pipeline fixture constructs Executor which uses get_tool_registry(); if registry empty, no tools dispatched, `_retriever.retrieve.await_count == 0` — exactly matches the assert failure observed |
| A6 | Skipping the canary via `pytest.mark.skipif` is cleaner than letting `HuggingFaceEmbedder.__init__` raise `FileNotFoundError` | Q4 | LOW — `skipif` produces `skipped` status; raise produces `error` status which dirties D-VERIFY-02 baseline. Recommendation aligns with D-VERIFY-01c which explicitly says "exit 0 OR skip with reason" |

---

## Open Questions (RESOLVED)

> All three resolved during planning. Decisions traceable to plan tasks below.

1. **OCR Cluster C disposition** — RESOLVED: deferred to v1.10 / TEST-12 candidate. 4 OCR tests explicitly `--deselect`'d from TEST-09d/e/f gates in 33-01-04 + listed in 33-VALIDATION.md §"OCR Cluster C — Authoritative Deselect List". Carry-forward note belongs in 33-01-SUMMARY at execution.
   - Source: 4 tests (`test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls`, `test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore`, `..._timeout_retries_once_then_surfaces_error`, `..._timeout_then_success_on_retry`) fail under random-order due to `services/extractor/ocr_engine.py:65 _sem` being bound to a stale event loop. NOT TEST-09's root cause.

2. **Option A vs Option B for reset fixture** — RESOLVED: Option B (explicit `register(cls)` re-population after `_registry.clear()`). 33-01-03 implements B. Avoids `importlib.reload` × `monkeypatch.setattr` collision risk.

3. **Canary test sync vs async** — RESOLVED: `async def` with `await embed_batch(["hello"])` + `predict([("q","d")])` + 1024-d shape assertion. Implemented in 33-00-03. Matches CONTEXT D-CANARY-01 spec ("calls encode(['hello']) + predict([('q','d')]), asserts output shapes").

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| pytest | both plans | ✓ | 9.0.3 | — |
| pytest-asyncio | both plans | ✓ | 1.3.0 | — |
| pytest-randomly | TEST-09 only | ✗ (intentionally removed after pre-flight) | — (will install via Task 1) | — |
| uv | both plans | ✓ | (system uv) | — |
| bge-m3 / bge-m3-rerank model files | TEST-08 canary (real-path execution only) | site-dependent | — | Canary `skipif` produces `skipped` status — does NOT block plan completion |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** bge-m3 models (acceptable — canary skip is the documented behavior per D-VERIFY-01c).

---

## Sources

### Primary (HIGH confidence — direct repo evidence)
- `tests/integration/conftest.py` (lines 25-60) — autouse fixture body
- `tests/conftest.py` (lines 36-360) — unit-scope fixtures + `pytest_configure`
- `tests/factories/app.py` (lines 31-79) — `_SINGLETON_INVENTORY` + `_reset_singletons()`
- `services/agent/tools/registry.py` (lines 100-118) — `_registry` singleton + `get_tool_registry()`
- `services/agent/tools/retrieve.py:161,209` — `@register` decorator sites
- `services/agent/tools/web_search.py:208` — `@register` decorator site
- `services/agent/tools/recall.py:39` — `@register` decorator site
- `services/memory/memory_service.py:640,650` — `embed_batch` / `embed_one` consumer
- `services/vectorizer/embedder.py:29-33, 105-127, 132-154, 218-220` — embedder API definitions
- `services/retriever/retriever.py:138-144` — `CrossEncoderReranker.__init__` (sync)
- `tests/unit/test_memory_service_extra.py:235-242` — the single embed_one-only mock
- `tests/unit/test_retrieve_tool.py:134,138,388-393` — failure assertions
- `tests/unit/test_web_search_tool.py:124` — failure assertion
- `tests/unit/test_agent_pipeline_refactor.py:83-152` — `mock_pipeline` fixture (transitive registry dependency)
- `pytest.ini:1-15` — markers + addopts
- `pyproject.toml:78-93` — `[dependency-groups] dev`
- `requirements-dev.txt:1-13` — full file content
- `scripts/check_typing_hygiene.py:_STUB_NAME_RE` — regex verified to not match `pytest-randomly`
- `config/settings.py:30-65` — `resolve_embedding_model_path()`
- `.planning/REQUIREMENTS.md` — TEST-08 / TEST-09 acceptance text
- `.planning/ROADMAP.md` lines 70-79 — Phase 33 Goal / Success Criteria
- `.planning/STATE.md` — current phase position + Nyquist requirement
- Direct pytest invocations (verified output):
  - `uv run pytest tests/unit/ -m 'not integration' -q` — 7 failures
  - `uv run pytest ... -p randomly --randomly-seed=12345 -q` — 12 failures
  - `uv run pytest ... -p randomly --randomly-seed=67890 -q` — 12 failures
  - `uv run pytest ... -p randomly --randomly-seed=99999 -q` — 11 failures

### Secondary (MEDIUM confidence — inferred from primary evidence)
- Cluster C (OCR Semaphore) root cause as `asyncio.Semaphore` loop binding — based on file:line evidence (`services/extractor/ocr_engine.py:65`) + autouse reset visible in `test_ocr_engine.py:50-59`, but exact loop-binding race not traced through pytest-asyncio internals

### Tertiary (no LOW-confidence claims in this research)

---

## Metadata

**Confidence breakdown:**
- Q1 singleton inventory: HIGH — direct grep + traceback evidence + `_SINGLETON_INVENTORY` cross-ref
- Q2 acceptance seeds: HIGH — three live runs captured, full failure decomposition tabulated
- Q3 mock-shape parity: HIGH — exhaustive `grep -rn "embed_one=\|embed_batch="` audit; only 1 bug confirmed
- Q4 canary feasibility: HIGH — both `__init__` signatures verified sync, env-resolver path verified, pattern mirror confirmed
- Q5 dual-write: HIGH — line-exact insertion points for both files, hygiene-script regex verified non-matching
- Q6 sequencing: MEDIUM — judgment call; recommendation backed by risk decomposition but planner may legitimately choose differently
- Q7 validation architecture: HIGH — gates are mechanical; planner just transcribes
- Q8 guardrails: HIGH — CONTEXT.md `<deferred>` reproduced verbatim + one new guardrail surfaced via Q2

**Research date:** 2026-05-18
**Valid until:** 2026-06-17 (30 days; test-infra changes are stable, registry-pattern hasn't shifted in 5+ phases)

---

## RESEARCH COMPLETE
