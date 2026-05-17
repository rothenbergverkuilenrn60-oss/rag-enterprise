# Phase 23: Background Extractor + schema migration — Pattern Map

**Mapped:** 2026-05-15
**Files analyzed:** 11 (4 CREATE source, 1 CREATE-integration test, 3 CREATE-unit tests, 3 MODIFY)
**Analogs found:** 11 / 11

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/agent/extractor.py` (CREATE) | sub-agent (service) | request-response (LLM call, text-only) | `services/agent/verifier.py` | exact (line-for-line template) |
| `services/memory/memory_service.py::LongTermMemory._create_tables` (MODIFY) | model / DDL bootstrap | one-shot startup DDL | `services/vectorizer/vector_store.py::PgVectorStore.create_collection` (HNSW DDL precedent) + `services/memory/memory_service.py:143-182` (own current shape) | exact |
| `services/memory/memory_service.py::LongTermMemory._get_pool` (MODIFY) | DB pool init | connection-lifecycle | `services/vectorizer/vector_store.py::PgVectorStore._get_pool` (register_vector init callback) | exact |
| `services/memory/memory_service.py::save_fact` (MODIFY) | model writer | CRUD (single INSERT + embed) | `services/memory/memory_service.py:255-269` (own current shape) + `services/vectorizer/vector_store.py::PgVectorStore.upsert` ($N::vector cast precedent) | exact |
| `services/memory/memory_service.py` — `MemoryFactWriteError` class (MODIFY) | typed exception | error transport | (no existing typed-exception precedent in repo — define in-module per CONTEXT canonical_refs §Things to watch for / RESEARCH §Pattern 2) | none — inline definition |
| `services/pipeline.py::AgentQueryPipeline._persist_turn` (MODIFY) | controller wire-in | post-turn dispatch | `services/events/event_bus.py:132-133` (create_task + log_task_error wiring) + `services/agent/executor.py:187` (create_task pattern) | exact |
| `services/pipeline.py::SwarmQueryPipeline.run` post-`save_turn` (MODIFY) | controller wire-in | post-turn dispatch | same as above (single attach pattern reused) | exact |
| `config/settings.py` — `extractor_provider` / `extractor_model` / `extractor_enabled` (MODIFY) | config | config-load | `config/settings.py:288-294` (verifier_provider / verifier_model precedent) | exact |
| `utils/models.py` — `ExtractedFact` (MODIFY, append) | data model (Pydantic V2 frozen) | static schema | `utils/models.py:656-671` (`VerifierVerdict` frozen + cross-field convention) | exact |
| `tests/unit/test_extractor_*.py` (CREATE — categories / adversarial / dispatch / schema) | test | mock-at-consumer-path | `tests/unit/test_verifier.py` | exact |
| `tests/unit/test_save_fact_embed.py` (CREATE) | test | mock-at-consumer-path | `tests/unit/test_memory_service.py` (env-var setdefault + monkeypatch reset) + `tests/unit/test_verifier.py` (AsyncMock at consumer path) | role-match |
| `tests/integration/test_long_term_facts_schema.py` + `test_extractor_pipeline_wire.py` (CREATE) | test (integration) | pgvector marker, real PG | `tests/integration/test_pgvector_recall.py` / `test_swarm_pipeline_e2e.py` (existing pgvector-marked integration tests) | role-match |

---

## Pattern Assignments

### `services/agent/extractor.py` (CREATE — sub-agent)

**Analog:** `services/agent/verifier.py` (entire file is the template; ~199 LOC)

**Imports + module docstring shape** (`services/agent/verifier.py:1-42`):
```python
"""Verifier sub-agent (Phase 21 / AGENT-05).
... (multi-paragraph module docstring stating CF-rules, no-tenacity, provider override) ...
"""
from __future__ import annotations  # MANDATORY — makes ALL annotations lazy strings

import json
import re
import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import (
    ValidationError,  # noqa: F401  # re-exported for caller try/except clarity
)

from config.settings import settings
from services.generator.llm_client import (
    AnthropicLLMClient,
    BaseLLMClient,
    OpenAILLMClient,
    get_llm_client,
)
from utils.models import RetrievedChunk, VerifierVerdict
```
**Extractor swap:** replace `VerifierVerdict` import with `ExtractedFact`; replace `RetrievedChunk` with `ConversationTurn` (`from services.memory.memory_service import ConversationTurn`). Drop the `TYPE_CHECKING` block (no circular import — pipeline does NOT import Extractor at top-level; only `dispatch_extraction` is called from `_persist_turn`).

**Provider-singleton + `_resolve_llm` pattern** (`services/agent/verifier.py:99-112`):
```python
class Verifier:
    def __init__(self) -> None:
        self._llm: BaseLLMClient = self._resolve_llm()

    @staticmethod
    def _resolve_llm() -> BaseLLMClient:
        """Pitfall P-09: bypass ``get_llm_client()`` singleton when
        ``verifier_provider`` is set so we don't accidentally route through
        the wrong provider's cached client.
        """
        if settings.verifier_provider == "anthropic":
            return AnthropicLLMClient()
        if settings.verifier_provider == "openai":
            return OpenAILLMClient()
        return get_llm_client()
```
**Extractor swap:** rename class to `Extractor`; replace `settings.verifier_provider` with `settings.extractor_provider` (new field — see settings.py edit below).

**`call_agentic_turn` invocation shape** (`services/agent/verifier.py:133-140`):
```python
turn = await self._llm.call_agentic_turn(
    messages=[{"role": "user", "content": user_prompt}],
    tools=[],                              # CF-03 — text-only
    system=_VERIFIER_SYSTEM,
    max_tokens=settings.llm_max_tokens,
    parallel_tool_calls=False,             # CF-09 explicit; text-only
)
```
**Extractor swap:** identical kwargs; substitute `_EXTRACTOR_SYSTEM`. NO `time.perf_counter()` wrap (extractor is fire-and-forget; latency metering happens at the dispatch wrapper if desired).

**Critical difference from Verifier — `except BaseException` INSIDE `run()`** (per RESEARCH §Pattern 3 / Reuse-map table). Verifier propagates; Extractor swallows-and-logs because extractor is best-effort. Use the v1.3 Phase 12 isolation contract:
```python
try:
    agentic_turn = await self._llm.call_agentic_turn(...)
except BaseException as exc:  # noqa: BLE001 — Phase 12 isolation contract
    logger.error("extractor LLM call failed", exc_info=exc)
    return []
return self._parse_and_truncate(agentic_turn.text)
```

**`_parse` defensive-JSON pattern** (`services/agent/verifier.py:172-199` — copy regex + json.loads guard, drop the evidence-filtering tail which is verifier-specific):
```python
match = re.search(r"\{.*\}", raw, re.DOTALL)
if match is None:
    raise ValueError(f"verifier returned no JSON object; raw={raw[:200]!r}")
try:
    parsed: dict[str, Any] = json.loads(match.group(0))
except json.JSONDecodeError as exc:
    raise ValueError(f"verifier JSON parse failed: {exc!r}") from exc
```
**Extractor swap:** replace `raise ValueError` with `return []` at both branches (best-effort semantics). Then iterate `parsed.get("facts", [])[:5]`, `try: out.append(ExtractedFact.model_validate(item))` with `except ValidationError: continue`. Sort by `-importance` and slice `[:3]`. Full body in RESEARCH §Pattern 3.

**System prompt placement convention** (`services/agent/verifier.py:57-88`): triple-quoted Chinese system prompt as a module-level `_VERIFIER_SYSTEM` constant immediately above the class. Extractor mirrors: `_EXTRACTOR_SYSTEM` constant above `class Extractor`, content per RESEARCH §Pattern 3 (whitelist categories + refusal clause + strict-JSON shape).

**Module-level singleton accessor (if adopted)** — verifier currently does NOT have `get_verifier()`; precedent for the helper exists at `services/memory/memory_service.py:395-401`:
```python
_memory_service: MemoryService | None = None

def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
```
Use this exact shape for `get_extractor()`.

---

### `services/agent/extractor.py::dispatch_extraction` (CREATE — module-level helper)

**Analog:** `services/events/event_bus.py:132-133` (exact `create_task` + `log_task_error` wiring)

**Source code excerpt** (`services/events/event_bus.py:124-133`):
```python
async def _consume():
    async for msg in consumer:
        try:
            event = Event.from_json(msg.value)
            await handler(event)
        except Exception as exc:
            logger.error(f"[Kafka] Handler error: {exc}")

_dispatch_task = asyncio.create_task(_consume(), name="event-dispatch")
_dispatch_task.add_done_callback(log_task_error)
```

**Import for `log_task_error`** (`services/events/event_bus.py:18`):
```python
from utils.tasks import log_task_error
```

**`log_task_error` contract** (`utils/tasks.py:14-34` — already handles `CancelledError` + `InvalidStateError`, never re-raises). Wrapper uses AS-IS — DO NOT modify, DO NOT replace with a local `try/except`.

**Auth-precondition log-then-skip pattern** — closest in-tree precedent is the `loguru` structured-log convention at `services/memory/memory_service.py:204-305`:
```python
logger.error("memory service failure", operation="get_profile", exc_info=exc)
```
**Extractor swap:** use `logger.info` (not error — log-then-skip is info-level per CONTEXT D); operation key is `"extractor_skipped"`; add `reason="missing_user_id"` / `reason="missing_tenant_id"` kwarg. Full wrapper body in RESEARCH §Pattern 4.

**Parallel precedent for `asyncio.create_task` inside a non-streaming code path** (`services/agent/executor.py:187`):
```python
tasks = [asyncio.create_task(_timed(idx)) for idx in group]
```
Confirms create_task is the correct call shape (named via `name="extractor"` per RESEARCH).

---

### `services/memory/memory_service.py::LongTermMemory._create_tables` (MODIFY)

**Analog 1 — own current shape** (`services/memory/memory_service.py:143-182`):
```python
async def _create_tables(self) -> None:
    pool = await self._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            ... existing user_profiles + long_term_facts + query_history DDL ...
            CREATE TABLE IF NOT EXISTS long_term_facts (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id     TEXT NOT NULL,
                tenant_id   TEXT NOT NULL DEFAULT '',
                fact        TEXT NOT NULL,
                source_doc  TEXT DEFAULT '',
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                importance  FLOAT DEFAULT 0.5
            );
            CREATE INDEX IF NOT EXISTS ltf_user_idx ON long_term_facts(user_id, tenant_id);
            ... query_history DDL ...
        """)
```
**Idempotency style established:** `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. Phase 23 ADDs preserve this — `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.

**Analog 2 — HNSW DDL precedent** (`services/vectorizer/vector_store.py:158-184`):
```python
async def create_collection(self) -> None:
    pool = await self._get_pool()
    async with pool.acquire() as conn:
        # Enable pgvector extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        # Main chunk table (tenant_id column for RLS)
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._table} (
                ...
                embedding vector({self._dim}),
                ...
            );
        """)
        # HNSW index — SET LOCAL work_mem inside transaction as defense-in-depth for index build
        async with conn.transaction():
            await conn.execute("SET LOCAL work_mem = '256MB'")
            await conn.execute(f"DROP INDEX IF EXISTS {self._table}_vec_idx;")
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {self._table}_vec_idx
                    ON {self._table} USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64);
            """)
```
**Copy verbatim** for Phase 23: `m = 16, ef_construction = 64`, `vector_cosine_ops`, `IF NOT EXISTS`. DO NOT include `DROP INDEX IF EXISTS` (chunks-table precedent drops to rebuild; for `long_term_facts` we want pure-additive idempotency — no drop). Phase 23 also does NOT set `iterative_scan` (Phase 24 owns recall-time tuning, per CONTEXT deferred §HNSW iterative_scan).

**Phase 23 additions to `_create_tables` (per RESEARCH §Pattern 1):**
```python
# After the existing CREATE TABLE/INDEX block, append:
await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
await conn.execute(
    f"ALTER TABLE long_term_facts "
    f"ADD COLUMN IF NOT EXISTS embedding vector({settings.embedding_dim});"
)
await conn.execute("""
    CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx
        ON long_term_facts USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
""")
```
Note: must `from config.settings import settings` at module top — currently imported lazily inside `_get_client` / `_get_pool`. Planner: either hoist the import or use `f"vector({settings.embedding_dim})"` inside the existing local import path. The chunks-table form uses `f"vector({self._dim})"` (vector_store.py:170) with `self._dim` captured at `__init__`; LongTermMemory has no `__init__`-captured dim — simplest is lazy local import inside `_create_tables`.

---

### `services/memory/memory_service.py::LongTermMemory._get_pool` (MODIFY — add `register_vector` init)

**Analog:** `services/vectorizer/vector_store.py:133-156` (exact `_init_conn` callback shape)

**Source code excerpt** (`services/vectorizer/vector_store.py:133-156`):
```python
async def _get_pool(self):
    if self._pool is None:
        import asyncpg as _asyncpg
        from pgvector.asyncpg import register_vector

        async def _init_conn(conn: _asyncpg.Connection) -> None:
            await register_vector(conn)

        dsn = self._dsn.replace("postgresql+asyncpg://", "postgresql://")
        ...
        self._pool = await _asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=10,
            init=_init_conn,
            ...
        )
    return self._pool
```

**LongTermMemory current shape** (`services/memory/memory_service.py:133-141`):
```python
async def _get_pool(self):
    if self._pool is None:
        import asyncpg

        from config.settings import settings
        dsn = settings.pg_dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        await self._create_tables()
    return self._pool
```

**Phase 23 patch:** insert `from pgvector.asyncpg import register_vector` + `_init_conn` callback + `init=_init_conn` kwarg into `asyncpg.create_pool`. Without this, the `$6::vector` binding in `save_fact` will raise asyncpg codec lookup error on first call (Pitfall #1).

---

### `services/memory/memory_service.py::save_fact` (MODIFY — embed-on-write rewrite)

**Analog 1 — own current shape** (`services/memory/memory_service.py:255-269`):
```python
async def save_fact(
    self, user_id: str, tenant_id: str,
    fact: str, source_doc: str = "", importance: float = 0.5,
) -> None:
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO long_term_facts
                   (user_id, tenant_id, fact, source_doc, importance)
                   VALUES ($1,$2,$3,$4,$5)""",
                user_id, tenant_id, fact, source_doc, importance,
            )
    except asyncpg.PostgresError as exc:
        logger.error("memory service failure", operation="save_fact", exc_info=exc)
```
**Critical contract change:** Phase 23 rewrite MUST raise `MemoryFactWriteError` instead of silently logging. The current "log-and-swallow" hides extractor write failures from `log_task_error`.

**Analog 2 — `$N::vector` cast precedent** (`services/vectorizer/vector_store.py:264-276`):
```python
await conn.executemany(
    f"""
    INSERT INTO {self._table}
        (chunk_id, doc_id, content, metadata, embedding, tenant_id)
    VALUES ($1, $2, $3, $4::jsonb, $5::vector, $6)
    ON CONFLICT(chunk_id) DO UPDATE
        ...
    """,
    records,
)
```
**Copy the `$N::vector` explicit cast** for the new `embedding` column. The new INSERT is at param position $6.

**Analog 3 — `Embedder.embed_one` ABC** (`services/vectorizer/embedder.py:32-34`):
```python
async def embed_one(self, text: str) -> list[float]:
    results = await self.embed_batch([text])
    return results[0]
```
Reused AS-IS via `get_embedder().embed_one(fact)`. Embedding adapter narrow-exception catch list comes from the three concrete embedders:
- `OllamaEmbedder.embed_batch` raises `RuntimeError` on failure (`services/vectorizer/embedder.py:68`)
- `OllamaEmbedder._embed_single` uses `httpx` (catches `httpx.HTTPError`)
- `HuggingFaceEmbedder` loads torch (`OSError` for device/file failures)

Full rewrite body in RESEARCH §Pattern 2.

---

### `services/memory/memory_service.py` — `MemoryFactWriteError` typed exception (MODIFY)

**No existing in-tree analog** — `utils/exceptions.py` does NOT exist (verified). Define in-module per RESEARCH §Pattern 2 + CONTEXT canonical_refs:
```python
class MemoryFactWriteError(Exception):
    """Typed error for save_fact embedding or persistence failure.

    Wraps either asyncpg.PostgresError OR an embedding-adapter exception
    so the dispatch_extraction wrapper can surface it via log_task_error
    without conflating the two failure modes at the call site.
    """
```
Placement: next to the dataclass imports at the top of `services/memory/memory_service.py` (after `from loguru import logger`, before the `# 数据结构` section header).

---

### `services/pipeline.py::AgentQueryPipeline._persist_turn` (MODIFY — single-line wire-in)

**Analog:** `services/events/event_bus.py:132-133` (already cited above for `dispatch_extraction`)

**Current `_persist_turn` body** (`services/pipeline.py:915-948`):
```python
async def _persist_turn(
    self,
    req: GenerationRequest,
    answer: str,
    all_chunks: list[RetrievedChunk],
    trace_id: str,
    t0: float,
    parallelism_factors: list[int],
) -> GenerationResponse:
    """Save memory, write audit log, return GenerationResponse."""
    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    user_id, tenant_id = getattr(req, "user_id", ""), getattr(req, "tenant_id", "")
    await self._memory.save_turn(
        session_id=req.session_id, user_id=user_id, tenant_id=tenant_id,
        user_turn=ConversationTurn(role="user", content=req.query),
        ai_turn=ConversationTurn(
            role="assistant", content=answer,
            sources=[c.doc_id for c in all_chunks[:3]],
        ),
        intent=None,
    )
    # ← Phase 23 insertion point: dispatch_extraction(turn=ai_turn, user_id=user_id, tenant_id=tenant_id)
    await self._audit.log_query(...)
```
**Wire-in (per RESEARCH §Pattern 5):** immediately after the `save_turn` await, before the `audit.log_query` await:
```python
from services.agent.extractor import dispatch_extraction
dispatch_extraction(
    turn=ConversationTurn(
        role="assistant", content=answer,
        sources=[c.doc_id for c in all_chunks[:3]],
    ),
    user_id=user_id,
    tenant_id=tenant_id,
)
```
Note: `user_id` / `tenant_id` come from `req` (already extracted at line 926), NOT from `turn` (Pitfall #6). Single attach point covers both `run` and `run_streaming` because both call `_persist_turn`.

---

### `services/pipeline.py::SwarmQueryPipeline.run` post-`save_turn` (MODIFY)

**Current post-`save_turn` block** (`services/pipeline.py:1616-1626`):
```python
total_ms = round((time.perf_counter() - t0) * 1000, 1)

# Persist memory turn (mirrors AgentQueryPipeline pattern).
await self._memory.save_turn(
    session_id=req.session_id,
    user_id=user_id,
    tenant_id=tenant_id,
    user_turn=ConversationTurn(role="user", content=req.query),
    ai_turn=ConversationTurn(role="assistant", content=final_answer),
    intent=None,
)
# ← Phase 23 insertion point
```
**Wire-in:** same `dispatch_extraction(turn=<ai_turn>, user_id=user_id, tenant_id=tenant_id)` shape inserted immediately after the `save_turn` await, before the `audit.log` block at line 1633. `user_id` / `tenant_id` are already in scope (lines 1621-1622).

---

### `config/settings.py` — `extractor_provider` / `extractor_model` / `extractor_enabled` (MODIFY)

**Analog:** `config/settings.py:288-294`:
```python
# Verifier sub-agent (Phase 21, AGENT-05) ──────────────────────────────────
# verifier_provider="openai"|"anthropic" overrides peer provider; None = reuse.
# verifier_model is reserved (per-call model override not wired in v1.5; see
# 21-RESEARCH.md Pitfall P-09 / Assumption A3). Plan 21-05 logs it in audit
# metadata; Plan 21-03 does NOT consume verifier_model in v1.5.
verifier_model:    str | None = None
verifier_provider: Literal["openai", "anthropic"] | None = None
```
**Extractor swap (per RESEARCH §Open Question Q1 recommendation):** append directly after verifier_provider:
```python
# Extractor sub-agent (Phase 23, MEM-03) ───────────────────────────────────
# extractor_enabled=False kill-switch (default True — always-on per Q1).
# extractor_provider override mirrors verifier_provider; extractor_model
# reserved for future cheaper-model swap (gpt-4o-mini / claude-haiku-4-5).
extractor_enabled:  bool = True
extractor_model:    str | None = None
extractor_provider: Literal["openai", "anthropic"] | None = None
```

---

### `utils/models.py` — `ExtractedFact` (MODIFY — append)

**Analog:** `utils/models.py:656-671` (`VerifierVerdict` frozen Pydantic V2 model)

**Source code excerpt**:
```python
class VerifierVerdict(BaseModel):
    """Verifier sub-agent verdict (AGENT-05).

    Frozen — Verifier emits once; SwarmQueryPipeline reads (and may
    ``.model_copy(update=...)`` for CF-04 forced-disagree override per
    21-RESEARCH.md Pitfall P-02).

    Per CONTEXT D-02, ``proposed_answer`` is ALWAYS populated (both verdicts).
    """
    model_config = ConfigDict(frozen=True)

    verdict:            Literal["agree", "disagree"]
    evidence_chunk_ids: list[str]
    reasoning:          str
    proposed_answer:    str
    latency_ms:         int
```
**Imports available at top of utils/models.py** (line 13):
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```
All required decorators (`field_validator`, `model_validator`) and `ConfigDict` are already imported. Append `ExtractedFact` immediately after `VerifierVerdict` (line 671), before `VerifierStartEvent` (line 674) so both verifier and extractor sub-agent return types live in the same section. Full body in RESEARCH §Pattern 3 (with `@field_validator("fact")` length check + `@model_validator(mode="after")` cross-field bucket-mapping check).

---

### `tests/unit/test_extractor_*.py` (CREATE — 4 files: schema / categories / adversarial / dispatch)

**Analog:** `tests/unit/test_verifier.py` (full mock-at-consumer-path pattern, ≥7 reusable harness functions)

**Module docstring + imports pattern** (`tests/unit/test_verifier.py:1-25`):
```python
"""Phase 21 AGENT-05 — Verifier unit tests (RESEARCH §tdd-2; covers B-01..B-15).

RED gate per Plan 21-03 Task 1. Each test fails on first run with
``ImportError: cannot import name 'Verifier'`` (file doesn't exist yet).

Mocks at the consumer path (``services.agent.verifier.<dep>``) per CONTEXT
§"Established Patterns" — tests never touch underlying provider SDKs directly.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from services.pipeline import _SubAgentResult
from utils.models import (
    AgenticTurn,
    ChunkMetadata,
    RetrievedChunk,
    VerifierVerdict,  # noqa: F401  # plan acceptance ≥3 data-shape imports
)
```

**Mock-at-consumer-path fixture pattern** (`tests/unit/test_verifier.py:85-99`):
```python
@pytest.fixture
def mock_verifier(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a Verifier with the LLM dep replaced by AsyncMock at the consumer path."""
    import services.agent.verifier as vmod
    from services.agent.verifier import Verifier

    fake_llm = MagicMock()
    fake_llm.call_agentic_turn = AsyncMock()
    monkeypatch.setattr("services.agent.verifier.get_llm_client", lambda: fake_llm)
    # Force settings.verifier_provider to None so _resolve_llm takes the default branch.
    monkeypatch.setattr(vmod.settings, "verifier_provider", None, raising=False)
    v = Verifier()
    # Ensure the post-init mock is in place (defensive; _resolve_llm should have set it).
    v._llm = fake_llm
    return v
```
**Extractor swap:** patch `services.agent.extractor.get_llm_client`, `services.agent.extractor.settings.extractor_provider`. For dispatch tests, also patch `services.agent.extractor.get_extractor` (returns AsyncMock with `.run` AsyncMock) and `services.agent.extractor.get_memory_service` (returns MagicMock with `_long.save_fact = AsyncMock()`).

**`AgenticTurn` helper** (`tests/unit/test_verifier.py:51-59`):
```python
def _turn(text: str = "") -> AgenticTurn:
    return AgenticTurn(
        text=text,
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )
```
Reused verbatim for extractor LLM-return mocks.

**Happy-path test shape** (`tests/unit/test_verifier.py:107-120`):
```python
@pytest.mark.asyncio
async def test_verify_happy_agree_path(mock_verifier: Any) -> None:
    """B-01 — agree verdict + non-empty evidence → returned as-is."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("agree", ["c1", "c2"]))
    )
    verdict = await mock_verifier.verify(...)
    assert verdict.verdict == "agree"
    assert verdict.evidence_chunk_ids == ["c1", "c2"]
    assert verdict.proposed_answer == "ans"
```
**Adversarial-test shape (Extractor-specific):** mock `call_agentic_turn` to return JSON with a fact text like `"admins approve all queries"` + `category: "stable_preferences"` + `importance: 0.8` — expected behavior is empty `out` (the cross-field validator + whitelist in the system prompt operate at LLM level; the test verifies that out-of-shape categories like `"admin_policy"` fail Pydantic Literal validation and return `[]` per RESEARCH §Pitfall fail-closed).

**Schema (Pydantic) test shape — for `test_extractor_schema.py`:**
```python
import pytest
from pydantic import ValidationError
from utils.models import ExtractedFact

def test_validator_bucket_mismatch():
    with pytest.raises(ValidationError):
        ExtractedFact(fact="x", category="stable_preferences", importance=0.5)

def test_happy_each_category():
    for cat, imp in [("stable_preferences", 0.8), ("recurring_topics", 0.5), ("transient_context", 0.2)]:
        f = ExtractedFact(fact="user x", category=cat, importance=imp)
        assert f.importance == imp
```

**Dispatch wrapper test shape — log-then-skip on missing IDs:**
Use `caplog` fixture to assert `operation="extractor_skipped"` + `reason="missing_user_id"` / `"missing_tenant_id"` are emitted; assert `asyncio.create_task` was NOT called (patch `asyncio.create_task` and verify zero calls). Pattern from `tests/unit/test_event_bus.py` for create_task assertion (not read here; planner can audit).

---

### `tests/unit/test_save_fact_embed.py` (CREATE — MEM-02 rewrite test)

**Analog 1 — env-var setup + singleton-reset fixture** (`tests/unit/test_memory_service.py:1-30`):
```python
"""
tests/unit/test_memory_service.py
Unit tests for ShortTermMemory using fakeredis (no real Redis required).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


import fakeredis
import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)
```
**Copy verbatim for save_fact tests** — env-var setdefault MUST be at module top before any `services.*` import; `reset_memory_singleton` `autouse` fixture prevents singleton leakage across tests.

**Mock pattern for `save_fact`:**
```python
# Mock at consumer path inside services.memory.memory_service:
monkeypatch.setattr(
    "services.memory.memory_service.get_embedder",
    lambda: MagicMock(embed_one=AsyncMock(return_value=[0.1] * 1024)),
)
# Mock the asyncpg pool to AsyncMock with a conn.execute spy:
fake_pool = MagicMock()
fake_conn = MagicMock(execute=AsyncMock())
fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
mem = LongTermMemory()
mem._pool = fake_pool  # bypass _get_pool
```
**Failure-mode tests:**
- `embed_one` raises `RuntimeError` → assert `MemoryFactWriteError` raised, `conn.execute` NEVER called (zero partial-write rows).
- `conn.execute` raises `asyncpg.PostgresError` → assert `MemoryFactWriteError` raised with `__cause__` set.

---

### `tests/integration/test_long_term_facts_schema.py` + `test_extractor_pipeline_wire.py` (CREATE — integration)

**Analog:** `tests/integration/test_pgvector_recall.py` / `test_swarm_pipeline_e2e.py` (existing `pgvector`-marked tests, identifiable in repo).

**Marker convention** (from RESEARCH §Validation Architecture + pytest.ini): use `@pytest.mark.pgvector` + `@pytest.mark.integration`. Default test runs (per `pytest.ini` line 13: `-m "not integration"`) skip these; manual invocation per RESEARCH:
```bash
uv run pytest tests/integration/test_long_term_facts_schema.py -m pgvector -x
```

**MEM-01 idempotency test shape:**
1. Run `_create_tables()` twice; assert second call is no-op (no errors).
2. `EXPLAIN SELECT … ORDER BY embedding <=> $1::vector LIMIT 5` references `ltf_emb_hnsw_idx`.

**MEM-04 latency-delta + isolation integration test shape (SC4 + SC5):**
1. Patch `get_extractor()` to return an Extractor whose `run` sleeps 500ms (slower than user turn).
2. Run `AgentQueryPipeline.run(req)` end-to-end; measure wall-clock.
3. Assert wall-clock < (baseline_without_extractor + 50ms) — extractor latency hidden by `create_task`.
4. Patch `Extractor.run` to raise; assert pipeline still returns `GenerationResponse` normally.

---

## Shared Patterns

### Structured logging (loguru kwargs)
**Source:** `services/memory/memory_service.py:204, 234, 252, 269, 286, 305` (consistent shape).
**Apply to:** all new logger calls in `extractor.py`, `dispatch_extraction`, `save_fact` rewrite.
```python
logger.error("memory service failure", operation="<op_name>", exc_info=exc)
logger.info("extractor skipped", operation="extractor_skipped", reason="missing_user_id")
```
Loguru accepts arbitrary kwargs (confirmed Assumption A3 promoted to VERIFIED in RESEARCH).

### `from __future__ import annotations`
**Source:** `services/agent/verifier.py:23`, `services/memory/memory_service.py:5`, `utils/tasks.py:7`, `services/events/event_bus.py:6`.
**Apply to:** every new `.py` file in this phase. MANDATORY per repo convention (lazy string annotations enable circular-import resilience).

### `asyncio.create_task` + `log_task_error` background-isolation
**Source:** `services/events/event_bus.py:132-133` + `services/events/event_bus.py:171-172` (twice in same file), `services/agent/executor.py:187` (within `_timed` wrapper that catches BaseException internally).
**Apply to:** `dispatch_extraction` wrapper. AS-IS — do not wrap with additional `try/except`.

### Provider-singleton bypass for sub-agents (`_resolve_llm` pattern)
**Source:** `services/agent/verifier.py:102-112`.
**Apply to:** `services/agent/extractor.py::Extractor._resolve_llm`. Mirrors verifier 1:1 — only the settings field name differs (`extractor_provider` vs `verifier_provider`).

### Defensive JSON extraction from LLM output
**Source:** `services/agent/verifier.py:181-187` (regex `r"\{.*\}"` + `re.DOTALL` + `json.JSONDecodeError` catch).
**Apply to:** `Extractor._parse_and_truncate`. Same regex; on failure, return `[]` (not raise — extractor is best-effort).

### Pydantic V2 frozen schema with cross-field validator
**Source:** `utils/models.py:656-671` (`VerifierVerdict`) — but no cross-field validator there. Closest cross-field validator precedent is the `@model_validator(mode="after")` convention already imported at `utils/models.py:13`. Phase 21 used `model_validate` post-parse filtering instead. Extractor introduces the first sub-agent-output `@model_validator(mode="after")` use; pattern is standard Pydantic V2 idiom — full body in RESEARCH §Pattern 3.

### Test mock-at-consumer-path (v1.3 D-08)
**Source:** `tests/unit/test_verifier.py:85-99` (lines 88, 93 use `services.agent.verifier.<dep>` paths).
**Apply to:** all new extractor + dispatch tests. Patch:
- `services.agent.extractor.get_llm_client` (LLM)
- `services.agent.extractor.get_embedder` (embedding — appears via `save_fact`, but extractor unit tests should not exercise embedder; only `test_save_fact_embed.py` does)
- `services.agent.extractor.get_memory_service` (dispatch wrapper consumer)

### Lazy `from config.settings import settings` inside method bodies
**Source:** `services/memory/memory_service.py:79, 137` (already lazy-imported for ShortTermMemory + LongTermMemory).
**Apply to:** new code added to `_create_tables` if hoisting settings would force a circular-import (planner: verify with quick `python -c` after editing).

---

## No Analog Found

| File / Element | Role | Data Flow | Reason |
|---|---|---|---|
| `MemoryFactWriteError` typed exception | error transport | sync raise | No prior typed-exception class in tree (no `utils/exceptions.py` exists; verified). Define in-module per RESEARCH §Pattern 2 — no analog to copy from. |

(All other Phase 23 surfaces have at least one role+data-flow exact analog.)

---

## Metadata

**Analog search scope:**
- `services/agent/` (verifier, executor, planner)
- `services/memory/` (memory_service)
- `services/events/` (event_bus)
- `services/vectorizer/` (vector_store, embedder)
- `services/pipeline.py` (AgentQueryPipeline._persist_turn, SwarmQueryPipeline.run)
- `services/generator/llm_client.py` (BaseLLMClient.call_agentic_turn contract)
- `utils/` (tasks, models, exceptions [absent])
- `config/settings.py`
- `tests/unit/` (test_verifier, test_memory_service)
- `tests/integration/` (pgvector-marked tests)

**Files scanned (read for excerpt extraction):** 11 source + 2 test
**Pattern extraction date:** 2026-05-15
