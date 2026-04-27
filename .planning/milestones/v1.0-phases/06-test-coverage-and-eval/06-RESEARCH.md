# Phase 6: Test Coverage and Eval — Research

**Researched:** 2026-04-27
**Domain:** pytest-cov, RAGAS eval, unit test patterns for async Python services
**Confidence:** HIGH

---

## Summary

Phase 6 has three distinct workstreams that can be parallelised across waves:

1. **TEST-01** — Unit tests for 11 uncovered service modules. The project already has working test patterns (monkeypatching, `AsyncMock`, `fakeredis`, `unittest.mock`). No new test infrastructure is needed; the patterns are already proven in `test_oidc_auth_dependency.py`, `test_ingest_status.py`, and `test_rules_engine_abc.py`.

2. **TEST-02** — Raise the pytest-cov `--cov-fail-under` threshold in `ci.yml` from 60 to 80. This is a single-line CI change, but it is blocked until TEST-01 tests actually drive coverage above 80%.

3. **TEST-03** — Expand `eval/datasets/qa_pairs.json` from 10 to ≥200 QA pairs. The eval infrastructure (`ragas_runner.py`, `models.py`, RAGAS 0.2.6) is fully built. The CI gate for RAGAS requires adding a CI step that asserts `faithfulness > 0.85` and `answer_relevancy > 0.80` from a `RagasEvaluator` run — and a 20% holdout discipline to prevent contamination.

The most critical planning constraint is: **generate QA pairs from holdout documents that are never ingested into the retrieval index** (explicit pitfall recorded in STATE.md).

**Primary recommendation:** Execute TEST-01 unit tests in Wave 1 (11 files, parallel authoring), then TEST-02 + TEST-03 in Wave 2 (CI gate + eval dataset expansion). TEST-02's threshold bump must be the last commit — only after coverage is confirmed ≥80%.

---

## Project Constraints (from CLAUDE.md)

- **No prototype code** — production-grade only; Pydantic V2, mypy --strict, ruff
- **No bare `except`** — narrow exception types only (ERR-01)
- **No blocking I/O** in async contexts
- **Adapters** for all external dependencies (LLMs, DBs, vector stores)
- **Tenacity** retry logic for all external calls
- **Structured logging** for every operation
- Three-layer architecture: `utils/` → `services/` → `controllers/`
- Environment: WSL2 + Miniconda `torch_env`; `MODEL_DIR` via env var

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEST-01 | Unit tests for all 11 uncovered service modules: auth, memory, feedback, audit, tenant, events, NLU, knowledge, ab_test, rules, vectorizer | Patterns verified from existing tests; mock strategies per service documented below |
| TEST-02 | Unit test coverage floor raised from 60% to 80%, enforced in CI | ci.yml line confirmed: `--cov-fail-under=60`; change to 80; requires TEST-01 first |
| TEST-03 | Eval dataset ≥200 QA pairs, stratified, 20% holdout, RAGAS CI gate faithfulness>0.85 / answer_relevancy>0.80 | ragas_runner.py, models.py, requirements-eval.txt all exist; CI step is missing; qa_pairs.json exists but is too large to read (29k tokens); dataset expansion approach documented below |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Unit tests for service logic | Services layer | utils/ | Tests live alongside services; no API layer needed |
| Coverage enforcement | CI (GitHub Actions) | pytest-cov config | `--cov-fail-under` in ci.yml; pytest.ini could also set it |
| Eval dataset generation | eval/ scripts | Offline / manual | QA pairs generated offline from holdout docs, never from the live index |
| RAGAS CI gate | CI (GitHub Actions) | eval/ragas_runner.py | New CI job calls `ragas_runner.py` in offline/mock mode with pre-built dataset |

---

## Standard Stack

### Core (already installed — verified in requirements-dev.txt / requirements-eval.txt)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.3 | Test runner | `[VERIFIED: requirements-dev.txt]` |
| pytest-asyncio | ≥1.3.0 | Async test support | `[VERIFIED: requirements-dev.txt]` |
| pytest-cov | 6.0.0 | Coverage reporting + enforcement | `[VERIFIED: requirements-dev.txt]` |
| pytest-timeout | 2.3.1 | Per-test timeout | `[VERIFIED: requirements-dev.txt]` |
| fakeredis | 2.35.1 | In-process Redis fake (no real Redis) | `[VERIFIED: requirements-dev.txt]` |
| ragas | 0.2.6 | RAG evaluation metrics | `[VERIFIED: requirements-eval.txt]` |
| datasets | 3.2.0 | HuggingFace Dataset builder | `[VERIFIED: requirements-eval.txt]` |

### No new packages needed

All test infrastructure is already present. The 11 new test files reuse existing patterns.

---

## Existing Test Coverage Map

### Already covered (do NOT duplicate)

| Module | Existing Test File |
|--------|-------------------|
| services/auth/oidc_auth.py | tests/unit/test_oidc_auth_dependency.py |
| services/rules/rules_engine.py | tests/unit/test_rules_engine_abc.py |
| services/doc_processor/chunker.py | tests/unit/test_chunker.py |
| services/vectorizer/vector_store.py | tests/unit/test_pgvector_store.py |
| services/retriever/retriever.py | tests/unit/test_retriever.py |
| services/preprocessor/pii_detector.py | tests/unit/test_pii_detector.py |
| services/preprocessor/cleaner.py | tests/unit/test_preprocessor.py |
| services/extractor/image_extractor.py | tests/unit/test_image_extractor.py |
| services/ingest_worker.py | tests/unit/test_ingest_worker.py |
| (async ingest API) | tests/unit/test_ingest_status.py |
| (generator) | tests/unit/test_generator_mock.py |
| (settings validators) | tests/unit/test_settings_validators.py |
| (rate limiting) | tests/unit/test_rate_limiting.py |
| (pipeline PII) | tests/unit/test_pipeline_pii_block.py |
| (tasks) | tests/unit/test_tasks.py |

### TEST-01 targets — 11 modules needing new test files

| Module | Test File to Create | Mock Strategy |
|--------|--------------------|-|
| services/auth/oidc_auth.py | PARTIAL — extend existing | Already covered above; rules confirms `monkeypatch` + `AsyncMock` |
| services/memory/memory_service.py | tests/unit/test_memory_service.py | `fakeredis.FakeAsyncRedis` for ShortTermMemory; `AsyncMock` for asyncpg pool for LongTermMemory |
| services/feedback/feedback_service.py | tests/unit/test_feedback_service.py | Mock `get_event_bus()` and `get_memory_service()` via monkeypatch |
| services/audit/audit_service.py | tests/unit/test_audit_service.py | Mock `settings.audit_db_enabled=False` to skip DB path; test buffer logic directly |
| services/tenant/tenant_service.py | tests/unit/test_tenant_service.py | Pure in-memory; mock `asyncpg.Connection` for `set_tenant_context` |
| services/events/event_bus.py | tests/unit/test_event_bus.py | Use `InMemoryEventBus` directly (no Kafka); test `publish` + `subscribe` + dispatch loop |
| services/nlu/nlu_service.py | tests/unit/test_nlu_service.py | Test rule-based paths (no LLM); mock `llm_client` for LLM paths; `_rule_based_intent`, `extract_entities` testable without mock |
| services/knowledge/knowledge_service.py | tests/unit/test_knowledge_service.py | Mock asyncpg pool; test `DocumentQualityChecker` (pure logic); mock pipeline for update path |
| services/ab_test/ab_test_service.py | tests/unit/test_ab_test_service.py | Mock Redis client; test traffic routing determinism (hash-based) |
| services/rules/rules_engine.py | ALREADY COVERED — skip | `test_rules_engine_abc.py` exists |
| services/vectorizer/embedder.py | tests/unit/test_embedder.py | Mock `httpx.AsyncClient` for `OllamaEmbedder`; test `embed_batch` retry + error path |

**Note on "rules":** `test_rules_engine_abc.py` already exists and covers `RulesEngine`. The 11-module list in TEST-01 includes `rules` generically — this is already satisfied. The planner should verify coverage metrics rather than create a duplicate file.

**Note on "auth":** `test_oidc_auth_dependency.py` already covers `get_current_user`. The TEST-01 count may refer to `OIDCAuthService.verify_token` internals not yet covered. The planner should check coverage for `services/auth/` and add tests only for uncovered lines.

---

## Architecture Patterns

### pytest.ini current state

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
timeout = 60
log_cli = true
log_cli_level = INFO
```

`asyncio_mode = auto` is already set — no `@pytest.mark.asyncio` needed (though existing tests use it; it is harmless).

### Coverage configuration — TEST-02 change

The only change for TEST-02 is in `.github/workflows/ci.yml` line 61:

```yaml
# BEFORE (current):
--cov-fail-under=60

# AFTER (TEST-02):
--cov-fail-under=80
```

Also add `--cov=config` to cover the config layer, or keep as-is (`--cov=services --cov=utils`). The current scope excludes `config/` from coverage — acceptable given the phase scope.

Optionally add a `[coverage:run]` section to `pytest.ini` or a `.coveragerc` for branch coverage, but this is not required by TEST-02.

### Pattern: Pure logic service — no mocking needed

```python
# Source: observed in test_rules_engine_abc.py
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

class TestTenantService:
    def test_register_and_get(self):
        from services.tenant.tenant_service import TenantService, TenantConfig
        svc = TenantService()
        svc.register(TenantConfig(tenant_id="t1", name="Tenant One"))
        cfg = svc.get("t1")
        assert cfg.name == "Tenant One"

    def test_get_unknown_returns_default(self):
        from services.tenant.tenant_service import TenantService
        svc = TenantService()
        cfg = svc.get("unknown")
        assert cfg.tenant_id == "unknown"

    def test_check_permission_open_tenant(self):
        from services.tenant.tenant_service import TenantService, TenantConfig
        svc = TenantService()
        svc.register(TenantConfig(tenant_id="t2", allowed_users=[]))
        assert svc.check_permission("t2", "any-user") is True
```

### Pattern: Async service with Redis mock (fakeredis)

```python
# Source: observed in test_ingest_status.py, fakeredis docs
import fakeredis
import pytest

@pytest.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()

async def test_short_term_memory_append_and_get(fake_redis, monkeypatch):
    from services.memory.memory_service import ShortTermMemory, ConversationTurn
    stm = ShortTermMemory()
    monkeypatch.setattr(stm, "_client", fake_redis)
    # Bypass lazy _get_client by pre-setting _client
    turn = ConversationTurn(role="user", content="hello")
    await stm.append("session-1", turn)
    history = await stm.get_history("session-1")
    assert len(history) == 1
    assert history[0].content == "hello"
```

### Pattern: Async service with DB mock (AsyncMock pool)

```python
# Source: observed in test_oidc_auth_dependency.py pattern
from unittest.mock import AsyncMock, MagicMock

async def test_audit_log_file_path_no_db(monkeypatch):
    """When audit_db_enabled=False, log() only writes to file — no DB calls."""
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", False)
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)

    svc = audit_mod.AuditService.__new__(audit_mod.AuditService)
    svc._buffer = []
    svc._last_flush = 0.0
    svc._lock = asyncio.Lock()

    from services.audit.audit_service import AuditEvent
    event = AuditEvent(user_id="u1", tenant_id="t1", action="QUERY")
    await svc.log(event)
    # DB path never called — no assertion needed beyond no exception raised
```

### Pattern: Event-driven service — InMemoryEventBus

```python
async def test_event_bus_subscribe_and_dispatch():
    from services.events.event_bus import InMemoryEventBus, Event, EventType
    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(EventType.DOC_INGESTED, handler)
    await bus.start()
    await bus.publish(Event(
        event_type=EventType.DOC_INGESTED,
        payload={"doc_id": "d1", "chunk_count": 5},
    ))
    await asyncio.sleep(0.05)  # allow dispatch loop to process
    bus.stop()
    assert len(received) == 1
    assert received[0].payload["doc_id"] == "d1"
```

### Pattern: NLU rule-based path (no LLM)

```python
def test_rule_based_intent_chitchat():
    from services.nlu.nlu_service import _rule_based_intent, QueryIntent
    assert _rule_based_intent("你好") == QueryIntent.CHITCHAT

def test_rule_based_intent_procedural():
    from services.nlu.nlu_service import _rule_based_intent, QueryIntent
    assert _rule_based_intent("怎么申请年假") == QueryIntent.PROCEDURAL

def test_extract_entities_number():
    from services.nlu.nlu_service import _extract_entities_rule
    entities = _extract_entities_rule("请假3天")
    assert any(e.entity_type == "number" for e in entities)
```

### Anti-Patterns to Avoid

- **Singleton leakage between tests:** Always reset module-level singletons (`_audit_service`, `_memory_service`, etc.) in teardown via `monkeypatch.setattr(module, '_service_var', None)` or explicit reset.
- **Testing implementation details:** Test public interface (`log()`, `submit()`, `analyze()`) not private helpers directly.
- **Blocking asyncio in sync tests:** Never call `asyncio.run()` inside a test that is already in async context — all service tests must be `async def` with `asyncio_mode = auto`.
- **Real Redis in unit tests:** Always use `fakeredis`; real Redis belongs in `tests/integration/`.
- **Real DB in unit tests:** Always mock `asyncpg.connect` / `asyncpg.create_pool`; real PostgreSQL belongs in integration tests.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Redis fake | Custom in-memory dict | `fakeredis.FakeAsyncRedis` | Handles TTL, RPUSH, LRANGE, async interface exactly |
| Coverage enforcement | Parse coverage.xml in CI | `--cov-fail-under=80` flag | pytest-cov exits non-zero automatically |
| RAGAS metrics | Custom faithfulness scorer | `ragas.metrics.Faithfulness` | Handles judge LLM calls, NaN handling, Dataset format |
| QA generation | Custom GPT prompt chain | LLM + existing `EvalSettings` config | `ragas_runner.py` already accepts any `EvalSettings`-driven judge |

---

## TEST-03: Eval Dataset Expansion Strategy

### Current state

- `eval/datasets/qa_pairs.json` exists (current content is large — likely ~10 pairs based on phase description)
- `eval/ragas_runner.py` loads `EvalDataset` from this file via `EvalDataset.model_validate(raw)`
- `eval/models.py` defines `QAPair`, `EvalDataset`
- RAGAS metrics: Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall

### Expansion approach

**Step 1 — Holdout discipline (CRITICAL)**

Per STATE.md pitfall: "never generate QA pairs from documents in the retrieval index; 20% holdout first."

The plan MUST include a task that:
1. Identifies the current document corpus
2. Tags 20% of documents as holdout (never ingested)
3. Generates QA pairs exclusively from holdout documents
4. Documents the holdout set in `eval/datasets/holdout_manifest.json`

**Step 2 — QA pair generation**

Generate 200+ pairs using an LLM (the existing `ragas_judge_provider` config supports openai/anthropic/ollama). Stratification required:

| Stratum | Target count | Document type |
|---------|-------------|---------------|
| Policy factual | ~60 | HR policy PDFs |
| Procedural | ~50 | Process documents |
| Comparison | ~40 | Multi-doc comparisons |
| Definition | ~30 | Glossary / definition docs |
| Multi-hop | ~20 | Cross-document reasoning |

**Step 3 — Dataset schema**

`QAPair` in `eval/models.py` already has `question`, `ground_truth` fields. Stratification requires adding `doc_type` and `topic` metadata fields — the planner must check whether `QAPair` has these or whether they need to be added.

**Step 4 — CI gate**

Add a new job to `.github/workflows/ci.yml`:

```yaml
eval-gate:
  name: RAGAS Eval Gate
  runs-on: ubuntu-latest
  needs: unit-tests
  if: github.ref == 'refs/heads/main'  # only on main, not every PR
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python 3.11
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Install eval dependencies
      run: pip install -r requirements-eval.txt
    - name: Run RAGAS gate
      env:
        RAG_API_BASE_URL: ${{ secrets.RAG_API_BASE_URL }}
        RAGAS_JUDGE_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        RAGAS_JUDGE_PROVIDER: openai
        RAGAS_JUDGE_MODEL: gpt-4o-mini
      run: python scripts/eval_ci_gate.py
```

The `scripts/eval_ci_gate.py` script runs `RagasEvaluator().run()` and asserts:
- `report.avg_faithfulness >= 0.85`
- `report.avg_answer_relevancy >= 0.80`
- Exit code 1 if either fails

**IMPORTANT:** The eval gate requires a live RAG API. For CI, either:
a) Run against a staging deployment (requires `RAG_API_BASE_URL` secret), or
b) Run in offline mode against cached responses (requires pre-collected `rag_responses.json`)

Option (b) is safer for reproducible CI. The planner should decide and document this.

---

## Common Pitfalls

### Pitfall 1: Eval contamination
**What goes wrong:** QA pairs generated from documents already in the retrieval index. RAGAS scores are artificially inflated because the system has "seen" the source material.
**Why it happens:** Convenience — existing documents are available, holdout set requires extra work.
**How to avoid:** Create `eval/datasets/holdout_manifest.json` listing holdout doc paths BEFORE generating any QA pairs. Never ingest listed documents.
**Warning signs:** RAGAS scores improve dramatically after adding new documents to the index.

### Pitfall 2: Singleton leakage in unit tests
**What goes wrong:** Module-level `_service: Service | None = None` singletons from one test contaminate the next.
**Why it happens:** `get_X_service()` caches instance at module level; test isolation requires reset.
**How to avoid:** In test teardown (or `monkeypatch`), set `module._service = None`. Alternatively use `autouse` fixture for cleanup.
**Warning signs:** Test ordering matters; tests pass solo but fail in suite.

### Pitfall 3: Coverage below 80% after writing tests
**What goes wrong:** Tests are written but hit only happy paths; branches / error handlers not covered.
**Why it happens:** Services like `audit_service.py` have DB flush paths, error re-queue logic, and `_flush_to_db` with connection errors — all need tests.
**How to avoid:** Run `pytest --cov=services --cov-report=term-missing` after each test file; check missing lines explicitly.
**Warning signs:** `--cov-fail-under=80` fails after merging TEST-01 tests.

### Pitfall 4: asyncio.TimeoutError in event bus tests
**What goes wrong:** `InMemoryEventBus._dispatch_loop()` uses `wait_for(queue.get(), timeout=1.0)` — tests that don't call `bus.start()` first hang.
**Why it happens:** Forgetting to `await bus.start()` before `await bus.publish()`.
**How to avoid:** Always `await bus.start()` in test setup; `bus.stop()` in teardown.

### Pitfall 5: RAGAS judge model cost in CI
**What goes wrong:** RAGAS CI gate calls GPT-4o on every push, costs escalate.
**Why it happens:** `evaluate()` calls judge LLM for each of 200+ QA pairs.
**How to avoid:** Run eval gate on `main` branch only (not every PR). Use `gpt-4o-mini` as judge. Or use pre-collected responses (offline mode).

---

## CI Changes Summary

Two changes to `.github/workflows/ci.yml`:

1. **Line 61:** `--cov-fail-under=60` → `--cov-fail-under=80`
2. **New job:** `eval-gate` (as shown above; only on `main`)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pytest.ini` (root) |
| Quick run command | `pytest tests/unit/ --asyncio-mode=auto --timeout=30 -x -q` |
| Full suite command | `pytest tests/unit/ --asyncio-mode=auto --timeout=30 --cov=services --cov=utils --cov-report=term-missing -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-01 | Unit tests for 11 service modules | unit | `pytest tests/unit/test_{service}.py -x` | ❌ Wave 1 |
| TEST-02 | CI enforces 80% coverage floor | CI config change | `pytest --cov-fail-under=80` | ❌ Wave 2 (after TEST-01) |
| TEST-03 | 200+ QA pairs + RAGAS CI gate | eval + CI | `python scripts/eval_ci_gate.py` | ❌ Wave 2 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_{new_file}.py -x --asyncio-mode=auto`
- **Per wave merge:** `pytest tests/unit/ --cov=services --cov-report=term-missing --cov-fail-under=80`
- **Phase gate:** Full suite green + eval gate green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_memory_service.py` — covers TEST-01 (memory)
- [ ] `tests/unit/test_feedback_service.py` — covers TEST-01 (feedback)
- [ ] `tests/unit/test_audit_service.py` — covers TEST-01 (audit)
- [ ] `tests/unit/test_tenant_service.py` — covers TEST-01 (tenant)
- [ ] `tests/unit/test_event_bus.py` — covers TEST-01 (events)
- [ ] `tests/unit/test_nlu_service.py` — covers TEST-01 (NLU)
- [ ] `tests/unit/test_knowledge_service.py` — covers TEST-01 (knowledge)
- [ ] `tests/unit/test_ab_test_service.py` — covers TEST-01 (ab_test)
- [ ] `tests/unit/test_embedder.py` — covers TEST-01 (vectorizer)
- [ ] `eval/datasets/holdout_manifest.json` — holdout discipline for TEST-03
- [ ] `scripts/eval_ci_gate.py` — CI gate script for TEST-03

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest + pytest-cov | TEST-01, TEST-02 | ✓ | 9.0.3 / 6.0.0 | — |
| fakeredis | TEST-01 (memory, ab_test) | ✓ | 2.35.1 | — |
| ragas | TEST-03 | ✓ | 0.2.6 | — |
| OpenAI API key | TEST-03 eval gate | ❌ (CI secret) | — | Use ollama locally; CI needs secret |
| Live RAG API | TEST-03 CI gate | ❌ (staging) | — | Pre-collected responses for offline mode |

**Missing with no fallback for local dev:**
- None — all unit tests run without network access.

**Missing with fallback:**
- OpenAI API key: use `RAGAS_JUDGE_PROVIDER=ollama` locally; CI uses GitHub secret.
- Live RAG API: eval gate can use pre-collected `rag_responses.json` in offline mode.

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a (test-only phase) |
| V5 Input Validation | yes | Test files must not hardcode real secrets; use `os.environ.setdefault` with test values |
| V6 Cryptography | no | n/a |

**Key constraint:** Test files must use `os.environ.setdefault("SECRET_KEY", "test-key-32-chars-minimum-length-x")` — the existing test files (`test_rules_engine_abc.py`) demonstrate this pattern.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `eval/datasets/qa_pairs.json` currently has ~10 pairs (too large to read, 29k tokens) | TEST-03 | If it already has 200+, TEST-03 only needs the CI gate; planner should verify count |
| A2 | The "rules" module in TEST-01's 11 modules is already covered by `test_rules_engine_abc.py` | TEST-01 Coverage Map | If rules coverage is still below 80%, additional rules tests needed |
| A3 | "auth" in TEST-01 refers to uncovered internals of `OIDCAuthService.verify_token`, not `get_current_user` | TEST-01 Coverage Map | If entire auth/ is already at 80%+ coverage, no new test file needed |
| A4 | `eval_ci_gate.py` script does not exist; needs to be created | TEST-03 | If it exists elsewhere in scripts/, planner should reuse it |

---

## Open Questions

1. **Eval gate: online vs offline mode**
   - What we know: `ragas_runner.py` calls a live RAG API; CI currently has no eval job
   - What's unclear: Does the team want per-PR eval (expensive) or main-only (safe)?
   - Recommendation: Main-branch-only gate with `gpt-4o-mini` judge; document cost estimate

2. **QA pair generation: synthetic vs real documents**
   - What we know: STATE.md notes "20% of current documents available, or entirely synthetic bootstrap needed?" as an open question
   - What's unclear: Are holdout documents available, or is synthetic generation required?
   - Recommendation: Planner should ask user; synthetic bootstrap (LLM generates both Q and A from a hypothetical policy corpus) is viable for v1

3. **Auth coverage gap**
   - What we know: `test_oidc_auth_dependency.py` covers `get_current_user`; `OIDCAuthService` may have uncovered `verify_token` internals
   - What's unclear: Exact line coverage of `services/auth/`
   - Recommendation: Run `pytest --cov=services/auth --cov-report=term-missing` first in Wave 1

---

## Sources

### Primary (HIGH confidence)
- `[VERIFIED: project codebase]` — all service file structures, existing test patterns, CI config, requirements files read directly
- `[VERIFIED: pytest.ini]` — `asyncio_mode = auto`, testpaths, timeout=60
- `[VERIFIED: ci.yml]` — `--cov-fail-under=60`, `--cov=services --cov=utils`, unit-tests job structure
- `[VERIFIED: requirements-dev.txt]` — pytest 9.0.3, pytest-cov 6.0.0, fakeredis 2.35.1
- `[VERIFIED: requirements-eval.txt]` — ragas 0.2.6, datasets 3.2.0
- `[VERIFIED: eval/ragas_runner.py]` — full evaluator implementation, judge LLM factory, CI exit code pattern

### Secondary (MEDIUM confidence)
- `[ASSUMED]` — qa_pairs.json current count (~10 pairs): file was too large to read, count inferred from phase description

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified in requirements files
- Architecture: HIGH — all service files read; patterns verified from existing tests
- Pitfalls: HIGH — singleton leakage and eval contamination both recorded in STATE.md
- TEST-03 offline strategy: MEDIUM — approach is sound but exact qa_pairs.json schema for stratification fields needs planner verification

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (stable stack; ragas 0.2.x API unlikely to change)
