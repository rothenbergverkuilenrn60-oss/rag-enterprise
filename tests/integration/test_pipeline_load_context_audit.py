"""Phase 24 / Plan 24-05 — MEM-10 4-call-site REMOVAL regression audit.

T8 (eng-review 2026-05-16 / Decision-9): reshaped from popularity-vs-semantic
token-delta audit (methodologically moot) to a REMOVAL regression asserting
``mem_ctx.long_term_facts == []`` at every pipeline.py consumer post-Decision-1.

Background
----------
Decision-1 (Plan 02 Task 4 / T1) removed ``_long.get_relevant_facts`` from the
``asyncio.gather`` inside ``MemoryService.load_context``.  Long-term facts are
now surfaced exclusively via ``RecallTool`` (planner opt-in).  The
``MemoryContext.long_term_facts`` Pydantic V2 field remains in the model for
typed-shape stability — it is always ``[]`` when populated by ``load_context``.

Dropped (T8):
- Token-delta JSON artifact — methodology was moot; both paths used LIMIT 5 +
  same fact column → near-zero delta by construction.
- Popularity-baseline SELECT — the comparison subject no longer exists.

Parametrize traceability
------------------------
Test 1 is parametrized over 4 call-site labels mapping 1:1 to the 4 sites in
``services/pipeline.py``.  The underlying ``load_context`` call is identical;
the parametrize axis exists for documentation traceability in CI output.

  pipeline.py:429  — QueryPipeline.run (legacy non-agentic path)
  pipeline.py:608  — QueryPipeline.run_streaming
  pipeline.py:979  — AgentQueryPipeline.run
  pipeline.py:1070 — AgentQueryPipeline.run_streaming / SwarmQueryPipeline.run

Markers: ``integration`` + ``pgvector``.  SKIPs gracefully when PG unavailable.

See Also
--------
services/memory/memory_service.py::MemoryService.load_context (Plan 02 T1)
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping MEM-10 audit tests",
    ),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# User / tenant namespace scoped to this audit — avoids collisions with
# other integration tests (conftest clean_long_term_facts truncates all rows,
# but some tests may not use that fixture).
AUDIT_USER_ID = "test-mem10-u"
AUDIT_TENANT_ID = "test-mem10-t"
AUDIT_SESSION_ID = "test-mem10-session"

# 4 pipeline.py call sites to document in parametrize traceability.
CALL_SITES = [
    "pipeline.py:429 (QueryPipeline.run)",
    "pipeline.py:608 (QueryPipeline.run_streaming)",
    "pipeline.py:979 (AgentQueryPipeline.run)",
    "pipeline.py:1070 (AgentQueryPipeline.run_streaming)",
]

# Seed facts for Test 1 (12 rows — enough to confirm non-trivial recall result
# under old code but ALWAYS empty under Decision-1).
_SEED_FACTS_12 = [
    "user prefers React over Vue for frontend development",
    "user is proficient in Python and TypeScript",
    "user works on enterprise RAG systems",
    "user dislikes Java verbosity",
    "user prefers PostgreSQL over MySQL",
    "user lives in Berlin",
    "user's favorite framework is FastAPI",
    "user typically works on backend services",
    "user enjoys hiking on weekends",
    "user reads technical papers on LLMs",
    "user prefers dark mode in editors",
    "user uses uv for Python environment management",
]

# Seed facts for Test 2 (5 rows — typed-shape check).
_SEED_FACTS_5 = [
    "user likes TypeScript",
    "user builds RAG pipelines",
    "user prefers async Python",
    "user uses pgvector for embeddings",
    "user values code readability",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_facts(mem, user_id: str, tenant_id: str, facts: list[str]) -> None:
    """Insert facts via ``save_fact`` (embed-on-write) for the given user/tenant.

    ``LongTermMemory.save_fact`` is the production path; using it here ensures
    the vector column is populated correctly via ``embed_one`` (or the mock).
    """
    for fact in facts:
        await mem.save_fact(
            user_id=user_id,
            tenant_id=tenant_id,
            fact=fact,
            importance=0.5,
        )


async def _delete_audit_rows(pool) -> None:
    """Scoped DELETE — removes only rows seeded by this audit test suite.

    Does NOT drop the table (analog 13 anti-pattern prohibition).
    """
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM long_term_facts WHERE user_id LIKE 'test-mem10-%'"
            )
        except Exception:  # noqa: BLE001 — table may not exist in CI
            pass


# ---------------------------------------------------------------------------
# Test 1: 4-call-site removal regression (parametrized for traceability)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call_site", CALL_SITES)
async def test_load_context_long_term_facts_empty_all_four_callsites(
    pgvector_pool,
    embedder_or_mock,  # noqa: ARG001 — sets up embed mock before seed
    call_site: str,
) -> None:
    """Assert ``mem_ctx.long_term_facts == []`` at every pipeline call site.

    Seeds 12 facts for (AUDIT_USER_ID, AUDIT_TENANT_ID).  Under v1.0-v1.5
    behaviour, ``get_relevant_facts`` would return non-empty for a matching
    query.  Under Decision-1 (Plan 02 T1), ``load_context`` no longer calls
    ``get_relevant_facts`` → the field is ALWAYS ``[]`` regardless of seed.

    The ``call_site`` parameter is for documentation traceability: the same
    ``MemoryService.load_context`` method is called by all 4 sites; the
    parametrize axis documents which pipeline line is being exercised.
    """
    from services.memory.memory_service import LongTermMemory, MemoryService

    mem_long = LongTermMemory()
    mem_long._pool = pgvector_pool
    await mem_long._create_tables()

    # Clean before seeding.
    await _delete_audit_rows(pgvector_pool)

    try:
        # Seed 12 facts — under old code, a "frontend" query would return non-empty.
        await _seed_facts(mem_long, AUDIT_USER_ID, AUDIT_TENANT_ID, _SEED_FACTS_12)

        # Build MemoryService and pin its LongTermMemory to the shared pool.
        mem_svc = MemoryService()
        mem_svc._long._pool = pgvector_pool

        mem_ctx = await mem_svc.load_context(
            session_id=AUDIT_SESSION_ID,
            user_id=AUDIT_USER_ID,
            tenant_id=AUDIT_TENANT_ID,
            query="frontend",
        )

        # T8 / Decision-1 core assertion: field is always empty regardless of seed.
        assert mem_ctx.long_term_facts == [], (
            f"[{call_site}] Expected long_term_facts == [] after Decision-1 removal; "
            f"got {mem_ctx.long_term_facts!r}. "
            "Plan 02 Task 4 may not have landed correctly."
        )
    finally:
        await _delete_audit_rows(pgvector_pool)


# ---------------------------------------------------------------------------
# Test 2: typed-list shape preserved (always list, never None/missing)
# ---------------------------------------------------------------------------


async def test_load_context_long_term_facts_typed_list_preserved(
    pgvector_pool,
    embedder_or_mock,  # noqa: ARG001
) -> None:
    """Assert ``isinstance(mem_ctx.long_term_facts, list)`` post-Decision-1.

    The Pydantic V2 field ``MemoryContext.long_term_facts: list[str]`` must
    remain present and typed even though Decision-1 hardwires it to ``[]``.
    Consumers that iterate ``mem_ctx.long_term_facts`` must not receive
    AttributeError or None.
    """
    from services.memory.memory_service import LongTermMemory, MemoryService

    mem_long = LongTermMemory()
    mem_long._pool = pgvector_pool
    await mem_long._create_tables()

    await _delete_audit_rows(pgvector_pool)

    try:
        await _seed_facts(mem_long, AUDIT_USER_ID, AUDIT_TENANT_ID, _SEED_FACTS_5)

        mem_svc = MemoryService()
        mem_svc._long._pool = pgvector_pool

        mem_ctx = await mem_svc.load_context(
            session_id=AUDIT_SESSION_ID,
            user_id=AUDIT_USER_ID,
            tenant_id=AUDIT_TENANT_ID,
            query="Python async",
        )

        # Typed-shape contract: field exists and is a list (not None, not missing).
        assert isinstance(mem_ctx.long_term_facts, list), (
            f"Expected long_term_facts to be list; got {type(mem_ctx.long_term_facts)}"
        )
        # Confirm it is empty (redundant given Test 1, but explicit for shape audit).
        assert mem_ctx.long_term_facts == []
    finally:
        await _delete_audit_rows(pgvector_pool)


# ---------------------------------------------------------------------------
# Test 3: v1.5 baseline — no consumer regression (GenerationResponse still valid)
# ---------------------------------------------------------------------------


async def test_no_v1_5_regression(
    pgvector_pool,
    embedder_or_mock,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instantiate QueryPipeline + run a recorded request; assert valid GenerationResponse.

    Catches any consumer that was reading ``mem_ctx.long_term_facts`` expecting
    non-empty values.  Under Decision-1 the field is always ``[]``; if a
    consumer silently depended on non-empty facts this test will fail with a
    KeyError / AttributeError in the build-messages path.

    The pipeline is short-circuited at retriever + LLM layers (no real model
    needed) so the test is fast and CI-safe.  The memory layer runs end-to-end
    against the shared pgvector_pool.
    """
    from unittest.mock import AsyncMock, MagicMock

    from services.memory.memory_service import LongTermMemory
    from utils.models import GenerationRequest, GenerationResponse

    # Stub noisy I/O paths that don't exist in CI.
    monkeypatch.setattr(
        "services.pipeline._ab_assign_and_map",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "services.pipeline._store_last_qa", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "services.pipeline._ab_record", AsyncMock(return_value=None)
    )

    # Stub retriever to return empty chunks (no real embedder + index needed).
    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])
    monkeypatch.setattr("services.pipeline.get_retriever", lambda: mock_retriever)

    # Stub LLM to return a canned answer.
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(
        return_value=MagicMock(
            content="This is a test answer.",
            usage_input_tokens=10,
            usage_output_tokens=5,
        )
    )
    monkeypatch.setattr("services.pipeline.get_llm_client", lambda: mock_llm)

    # Stub audit / tenant / filter services.
    mock_audit = MagicMock()
    mock_audit.log_query = AsyncMock(return_value=None)
    mock_audit.log = AsyncMock(return_value=None)
    monkeypatch.setattr("services.pipeline.get_audit_service", lambda: mock_audit)

    mock_tenant = MagicMock()
    mock_tenant.get_tenant_filter = MagicMock(return_value={})
    monkeypatch.setattr("services.pipeline.get_tenant_service", lambda: mock_tenant)

    mock_filter_ext = MagicMock()
    mock_filter_ext.extract = AsyncMock(
        return_value=MagicMock(filters={}, semantic_query="test query")
    )
    monkeypatch.setattr(
        "services.pipeline.get_filter_extractor", lambda: mock_filter_ext
    )

    # Reset memory service singleton.
    import services.memory.memory_service as mem_mod
    monkeypatch.setattr(mem_mod, "_memory_service", None, raising=False)

    from services.pipeline import QueryPipeline

    pipeline = QueryPipeline()

    # Pin LongTermMemory pool to shared session pool.
    pipeline._memory._long._pool = pgvector_pool

    # Also ensure schema exists.
    mem_long = LongTermMemory()
    mem_long._pool = pgvector_pool
    await mem_long._create_tables()

    req = GenerationRequest(
        query="What does the user know about databases?",
        session_id=AUDIT_SESSION_ID,
        user_id=AUDIT_USER_ID,
        tenant_id=AUDIT_TENANT_ID,
    )

    result = await pipeline.run(req)

    assert isinstance(result, GenerationResponse), (
        f"Expected GenerationResponse; got {type(result)}"
    )
    # Confirm the answer field is a non-empty string (pipeline completed).
    assert isinstance(result.answer, str) and len(result.answer) > 0, (
        f"Expected non-empty answer string; got {result.answer!r}"
    )
