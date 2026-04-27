# Phase 6: Test Coverage and Eval — Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 13 (9 new test files + 1 CI edit + 1 new script + 1 eval model edit + 1 eval dataset)
**Analogs found:** 13 / 13

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/unit/test_memory_service.py` | test | request-response + Redis | `tests/unit/test_ingest_status.py` | role-match |
| `tests/unit/test_feedback_service.py` | test | event-driven | `tests/unit/test_oidc_auth_dependency.py` | role-match |
| `tests/unit/test_audit_service.py` | test | CRUD + file-I/O | `tests/unit/test_oidc_auth_dependency.py` | role-match |
| `tests/unit/test_tenant_service.py` | test | CRUD (pure) | `tests/unit/test_rules_engine_abc.py` | exact |
| `tests/unit/test_event_bus.py` | test | event-driven | `tests/unit/test_ingest_status.py` | role-match |
| `tests/unit/test_nlu_service.py` | test | request-response | `tests/unit/test_rules_engine_abc.py` | exact |
| `tests/unit/test_knowledge_service.py` | test | CRUD + DB mock | `tests/unit/test_oidc_auth_dependency.py` | role-match |
| `tests/unit/test_ab_test_service.py` | test | request-response + Redis | `tests/unit/test_ingest_status.py` | role-match |
| `tests/unit/test_embedder.py` | test | request-response + HTTP mock | `tests/unit/test_oidc_auth_dependency.py` | role-match |
| `.github/workflows/ci.yml` | config | CI | `.github/workflows/ci.yml` | exact (edit line 60) |
| `scripts/eval_ci_gate.py` | utility | batch | `eval/ragas_runner.py` (main() pattern) | role-match |
| `eval/models.py` | model | transform | `eval/models.py` (add fields) | exact (edit) |
| `eval/datasets/holdout_manifest.json` | config | — | `eval/datasets/qa_pairs.json` schema | exact |

---

## Pattern Assignments

### `tests/unit/test_tenant_service.py` (test, CRUD pure logic)

**Analog:** `tests/unit/test_rules_engine_abc.py`

**Env bootstrap + imports** (lines 1-18):
```python
from __future__ import annotations
import os
import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
```

**Core pattern — pure logic class, no mocks** (lines 22-55):
```python
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
```

**Note:** Use `class Test*` grouping. All imports inside test methods (avoids module-level side effects).

---

### `tests/unit/test_nlu_service.py` (test, request-response)

**Analog:** `tests/unit/test_rules_engine_abc.py`

**Core pattern — rule-based paths need no mock** (from RESEARCH.md verified patterns):
```python
class TestNLURuleBased:
    def test_rule_based_intent_chitchat(self):
        from services.nlu.nlu_service import _rule_based_intent, QueryIntent
        assert _rule_based_intent("你好") == QueryIntent.CHITCHAT

    def test_rule_based_intent_procedural(self):
        from services.nlu.nlu_service import _rule_based_intent, QueryIntent
        assert _rule_based_intent("怎么申请年假") == QueryIntent.PROCEDURAL

    def test_extract_entities_number(self):
        from services.nlu.nlu_service import _extract_entities_rule
        entities = _extract_entities_rule("请假3天")
        assert any(e.entity_type == "number" for e in entities)
```

**LLM path — monkeypatch mock_svc** (mirrors `test_oidc_auth_dependency.py` lines 13-15):
```python
async def test_analyze_with_llm_fallback(monkeypatch):
    mock_llm = AsyncMock(return_value={"intent": "FACTUAL", "entities": []})
    monkeypatch.setattr("services.nlu.nlu_service._call_llm", mock_llm)
    ...
```

---

### `tests/unit/test_memory_service.py` (test, Redis mock)

**Analog:** `tests/unit/test_ingest_status.py`

**fakeredis fixture** (lines 23-31 of test_ingest_status.py — adapt):
```python
import fakeredis
import pytest
import pytest_asyncio

@pytest_asyncio.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()
```

**Core async test pattern** (mirrors test_ingest_status.py lines 57-90):
```python
@pytest.mark.asyncio
async def test_short_term_memory_append_and_get(fake_redis, monkeypatch):
    from services.memory.memory_service import ShortTermMemory, ConversationTurn
    stm = ShortTermMemory()
    monkeypatch.setattr(stm, "_client", fake_redis)
    turn = ConversationTurn(role="user", content="hello")
    await stm.append("session-1", turn)
    history = await stm.get_history("session-1")
    assert len(history) == 1
    assert history[0].content == "hello"
```

**Singleton reset pattern** (teardown via monkeypatch — apply to all service tests):
```python
@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)
```

---

### `tests/unit/test_ab_test_service.py` (test, Redis mock)

**Analog:** `tests/unit/test_ingest_status.py`

Same `@pytest_asyncio.fixture async def fake_redis()` pattern as memory test.

**Core pattern — hash-based determinism**:
```python
@pytest.mark.asyncio
async def test_traffic_routing_determinism(fake_redis, monkeypatch):
    from services.ab_test.ab_test_service import ABTestService
    svc = ABTestService()
    monkeypatch.setattr(svc, "_redis", fake_redis)
    variant_a = await svc.get_variant("user-123", "experiment-1")
    variant_b = await svc.get_variant("user-123", "experiment-1")
    assert variant_a == variant_b  # same user always same variant
```

---

### `tests/unit/test_feedback_service.py` (test, event-driven)

**Analog:** `tests/unit/test_oidc_auth_dependency.py`

**monkeypatch dependency pattern** (lines 13-15 of test_oidc_auth_dependency.py):
```python
@pytest.mark.asyncio
async def test_submit_feedback_publishes_event(monkeypatch):
    import services.feedback.feedback_service as mod
    mock_bus = AsyncMock()
    monkeypatch.setattr(mod, "get_event_bus", lambda: mock_bus)

    from services.feedback.feedback_service import FeedbackService, FeedbackItem
    svc = FeedbackService()
    item = FeedbackItem(user_id="u1", doc_id="d1", rating=5)
    await svc.submit(item)
    mock_bus.publish.assert_awaited_once()
```

---

### `tests/unit/test_audit_service.py` (test, CRUD + settings mock)

**Analog:** `tests/unit/test_oidc_auth_dependency.py`

**settings attribute monkeypatch** (same pattern as monkeypatch.setattr on module):
```python
@pytest.mark.asyncio
async def test_audit_log_no_db_when_disabled(monkeypatch):
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", False)
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)

    svc = audit_mod.AuditService.__new__(audit_mod.AuditService)
    svc._buffer = []
    svc._last_flush = 0.0
    import asyncio
    svc._lock = asyncio.Lock()

    from services.audit.audit_service import AuditEvent
    event = AuditEvent(user_id="u1", tenant_id="t1", action="QUERY")
    await svc.log(event)  # must not raise
```

---

### `tests/unit/test_event_bus.py` (test, event-driven)

**Analog:** `tests/unit/test_ingest_status.py` (async fixture + asyncio.sleep pattern)

**InMemoryEventBus pattern** (from RESEARCH.md verified code):
```python
import asyncio
import pytest

@pytest.mark.asyncio
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
    await asyncio.sleep(0.05)
    bus.stop()
    assert len(received) == 1
```

**Critical:** Always `await bus.start()` before `await bus.publish()` — see RESEARCH.md Pitfall 4.

---

### `tests/unit/test_knowledge_service.py` (test, CRUD + DB mock)

**Analog:** `tests/unit/test_oidc_auth_dependency.py`

**asyncpg pool mock pattern**:
```python
@pytest.mark.asyncio
async def test_document_quality_checker_pure_logic():
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    # Pure logic — no DB mock needed
    result = checker.check("This is a valid document with enough content.")
    assert result.is_valid is True

@pytest.mark.asyncio
async def test_get_document_mocks_pool(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    import services.knowledge.knowledge_service as mod
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "d1", "title": "Doc 1"})
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn)
    mock_pool.acquire().__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire().__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "_pool", mock_pool, raising=False)
    ...
```

---

### `tests/unit/test_embedder.py` (test, HTTP mock)

**Analog:** `tests/unit/test_oidc_auth_dependency.py`

**httpx.AsyncClient mock pattern**:
```python
@pytest.mark.asyncio
async def test_ollama_embedder_embed_batch(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "embeddings": [[0.1, 0.2, 0.3]]
    })
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: mock_client)

    from services.vectorizer.embedder import OllamaEmbedder
    embedder = OllamaEmbedder(base_url="http://localhost:11434", model="bge-m3")
    result = await embedder.embed_batch(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == 3
```

---

### `.github/workflows/ci.yml` (config, CI — single-line edit)

**Exact change** (line 60):
```yaml
# BEFORE:
--cov-fail-under=60

# AFTER (TEST-02):
--cov-fail-under=80
```

**New eval-gate job to append** after `docker-build` job (full block):
```yaml
  eval-gate:
    name: RAGAS Eval Gate
    runs-on: ubuntu-latest
    needs: unit-tests
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

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

---

### `scripts/eval_ci_gate.py` (utility, batch)

**Analog:** `eval/ragas_runner.py` lines 622-637 (main() + SystemExit pattern)

**Exit-code pattern from ragas_runner.py** (lines 622-637):
```python
async def main() -> None:
    evaluator = RagasEvaluator()
    report = await evaluator.run()
    overall = report.overall_score
    exit_code = 0 if (overall is not None and overall >= 0.6) else 1
    raise SystemExit(exit_code)

if __name__ == "__main__":
    asyncio.run(main())
```

**Gate script adapts this with stricter thresholds**:
```python
# scripts/eval_ci_gate.py
from __future__ import annotations
import asyncio
import sys
from eval.ragas_runner import RagasEvaluator

async def main() -> None:
    evaluator = RagasEvaluator()
    report = await evaluator.run()

    failures = []
    if report.avg_faithfulness is None or report.avg_faithfulness < 0.85:
        failures.append(f"faithfulness={report.avg_faithfulness} < 0.85")
    if report.avg_answer_relevancy is None or report.avg_answer_relevancy < 0.80:
        failures.append(f"answer_relevancy={report.avg_answer_relevancy} < 0.80")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        raise SystemExit(1)

    print("PASS: All RAGAS thresholds met.")

if __name__ == "__main__":
    asyncio.run(main())
```

---

### `eval/models.py` — QAPair stratification fields (edit)

**Analog:** `eval/models.py` lines 64-76 (existing QAPair model)

**Current QAPair** (lines 64-76):
```python
class QAPair(BaseModel):
    question: str = Field(..., description="评测问题")
    ground_truth: str | None = Field(None, description="参考答案（可选）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")
```

**Add stratification fields** (new fields after `ground_truth`):
```python
    doc_type: Literal[
        "policy_factual", "procedural", "comparison",
        "definition", "multi_hop"
    ] | None = Field(None, description="问题类型，用于分层统计")
    topic: str | None = Field(None, description="主题标签，如 leave_policy / reimbursement")
    source_doc: str | None = Field(None, description="来源文档路径（仅 holdout 文档）")
```

---

### `eval/datasets/holdout_manifest.json` (config)

**Schema to create** (JSON, no existing analog — derive from EvalDataset pattern):
```json
{
  "version": "1.0.0",
  "created_at": "2026-04-27T00:00:00Z",
  "description": "Documents reserved as holdout — never ingest these into pgvector",
  "holdout_docs": [
    {
      "path": "docs/hr_policy_2024.pdf",
      "doc_type": "policy_factual",
      "topic": "leave_policy"
    }
  ]
}
```

---

## Shared Patterns

### Env Bootstrap (ALL test files)
**Source:** `tests/unit/test_rules_engine_abc.py` lines 17-18
**Apply to:** Every new test file (place at module top, before any imports)
```python
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
```

### Async Test Declaration
**Source:** `tests/unit/test_ingest_status.py` lines 57, 97, 130
**Apply to:** All tests calling async service methods
```python
@pytest.mark.asyncio
async def test_something(...):
```
Note: `asyncio_mode = auto` in pytest.ini makes the decorator optional but harmless.

### monkeypatch.setattr for module-level singletons
**Source:** `tests/unit/test_oidc_auth_dependency.py` line 15
**Apply to:** All services with `get_X_service()` singleton getters
```python
monkeypatch.setattr("services.X.x_service.get_x_service", lambda: mock_svc)
```

### fakeredis fixture
**Source:** `tests/unit/test_ingest_status.py` lines 23-31
**Apply to:** `test_memory_service.py`, `test_ab_test_service.py`
```python
@pytest_asyncio.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()
```

### Singleton teardown (autouse fixture)
**Source:** RESEARCH.md Pitfall 2 (anti-pattern documented)
**Apply to:** All services with module-level `_service: X | None = None`
```python
@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.X.x_service as mod
    yield
    monkeypatch.setattr(mod, "_x_service", None, raising=False)
```

### Standard imports block
**Source:** `tests/unit/test_ingest_status.py` lines 9-16
**Apply to:** All new test files
```python
from __future__ import annotations
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
```

---

## No Analog Found

No files fall into this category — all patterns are derivable from existing analogs.

---

## Metadata

**Analog search scope:** `tests/unit/`, `eval/`, `.github/workflows/`
**Files read:** test_ingest_status.py, test_rules_engine_abc.py, test_oidc_auth_dependency.py, ci.yml, eval/ragas_runner.py, eval/models.py
**Pattern extraction date:** 2026-04-27
