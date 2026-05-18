from __future__ import annotations

import os
from collections.abc import Generator

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import asyncio

import asyncpg
import pytest

PG_DSN = "postgresql://rag:rag@localhost:5432/ragdb"


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable. Used at collection time."""
    try:
        async def _check() -> bool:
            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(PG_DSN), timeout=2.0
                )
                await conn.close()
                return True
            except Exception:
                return False
        return asyncio.run(_check())
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.fixture
async def pg_pool():
    """Function-scoped asyncpg pool with pgvector codec registered on every connection.

    Previously session-scoped; flipped to function-scope to match pytest-asyncio 1.x
    default function-scoped test event loop. Session-scoped pool + function-scoped
    test loop produced `InterfaceError: cannot perform operation: another operation
    is in progress` on every PG-gated integration test.

    Per-test pool overhead is ~50ms on a local pgvector instance — acceptable trade
    for correctness across all PG-gated integration suites.
    """
    if not PG_AVAILABLE:
        pytest.skip("PostgreSQL + pgvector not available")
    from pgvector.asyncpg import register_vector  # type: ignore[import-untyped]  # why: pgvector.asyncpg lacks py.typed marker and has no community stubs as of 2026-05; tracking: NA

    async def _init_conn(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    pool = await asyncpg.create_pool(
        PG_DSN,
        min_size=1,
        max_size=5,
        init=_init_conn,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def pg_store():
    """Function-scoped PgVectorStore with reset singleton."""
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    yield store
    vs_module._store_instance = None


@pytest.fixture(scope="module")
def pg_available() -> bool:
    """Module-scoped availability flag."""
    return PG_AVAILABLE


# ──────────────────────────────────────────────────────────────────────────────
# Phase 23 / Plan 23-06 — fixtures for the new extractor + LTF integration tests.
# REUSES the existing ``pg_pool`` session fixture above for the asyncpg pool;
# adds extractor-LLM mock + embedder mock + per-test fact table cleanup that
# the new integration tests under tests/integration/test_long_term_facts_schema.py
# + test_extractor_e2e.py + test_swarm_pipeline_extractor_e2e.py rely on.
#
# All fixtures defer the actual DB connect to the underlying ``pg_pool`` so they
# inherit its skip-if-PG-unavailable behavior — keeping CI green on hosts
# without PostgreSQL.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(name="pgvector_pool")
async def pgvector_pool_fixture(pg_pool):
    """Alias to ``pg_pool`` under the name the Plan 23-06 tests reference.

    Phase 1 named the fixture ``pg_pool``; Plan 23-06 PLAN.md prescribes
    ``pgvector_pool``. Both names point to the same session-scoped asyncpg
    pool with pgvector codec registered (see ``pg_pool`` above).
    """
    yield pg_pool


@pytest.fixture
def extractor_llm_mock(monkeypatch):
    """Function-scoped: patch ``get_llm_client`` at the extractor's consumer
    path + reset the module-level ``_extractor`` singleton so every test sees
    a fresh client.

    Returns the MagicMock so tests can chain:
        extractor_llm_mock.call_agentic_turn.return_value = AgenticTurn(...)
    """
    from unittest.mock import AsyncMock, MagicMock

    import services.agent.extractor as extractor_mod

    mock_client = MagicMock()
    mock_client.call_agentic_turn = AsyncMock()
    monkeypatch.setattr(
        "services.agent.extractor.get_llm_client", lambda: mock_client
    )
    # Reset cached extractor singleton — otherwise a prior test's mock leaks in.
    monkeypatch.setattr(extractor_mod, "_extractor", None, raising=False)
    # Pin extractor_enabled = True so kill-switch never short-circuits.
    monkeypatch.setattr(
        extractor_mod.settings, "extractor_enabled", True, raising=False
    )
    return mock_client


@pytest.fixture
def embedder_or_mock(monkeypatch):
    """Function-scoped: if ``MODEL_DIR`` (or ``APP_MODEL_DIR``) points to a
    real bge-m3 model directory, return the real ``HuggingFaceEmbedder``;
    otherwise patch ``services.vectorizer.embedder.get_embedder`` to return
    a MagicMock yielding a deterministic 1024-dim vector — avoids requiring
    a 2GB model download for CI.

    The mock is monkey-patched at BOTH the embedder module and at the consumer
    path inside ``services.memory.memory_service`` (which lazy-imports it
    inside ``save_fact``). The lazy import means ``monkeypatch.setattr`` on
    the ``embedder`` module is the correct injection point.
    """
    import os as _os
    from unittest.mock import AsyncMock, MagicMock

    model_dir = _os.environ.get("MODEL_DIR") or _os.environ.get("APP_MODEL_DIR")
    # Plan 26-02 / TD-07: delegate to the multi-layout resolver so the fixture
    # also honors `BAAI/bge-m3` (HF flat) + `models--BAAI--bge-m3/snapshots/*`
    # (HF hub cache) layouts, not just legacy `embedding_models/bge-m3`.
    real_bge = False
    if model_dir:
        from config.settings import resolve_embedding_model_path
        real_bge = resolve_embedding_model_path("bge-m3").exists()

    if real_bge:
        # Real embedder path — return the singleton factory's result.
        import services.vectorizer.embedder as emb_mod

        # Force factory reset so we instantiate fresh under test env.
        emb_mod._embedder_instance = None
        return emb_mod.get_embedder()

    mock_emb = MagicMock()
    mock_emb.embed_one = AsyncMock(return_value=[0.1] * 1024)

    # Phase 27 / TD-05 (plan 27-04): callers may invoke ``embed_batch`` with
    # an arbitrary number of texts (e.g., ``save_facts([5 facts])``). The
    # previous fixed ``return_value=[[0.1] * 1024]`` returned exactly 1 vector
    # regardless of input length and tripped ``zip(facts, embeddings,
    # strict=True)`` inside save_facts. Use ``side_effect`` so the mock
    # returns a list whose length matches the input.
    async def _mock_embed_batch(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]

    mock_emb.embed_batch = AsyncMock(side_effect=_mock_embed_batch)
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: mock_emb
    )
    # Reset the module-level singleton so the patch above wins on next call.
    import services.vectorizer.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "_embedder_instance", None, raising=False)
    return mock_emb


@pytest.fixture
async def clean_long_term_facts(pgvector_pool):
    """Function-scoped: truncate ``long_term_facts`` before each test so the
    user_id/tenant_id row counts assertions are deterministic.

    Runs BEFORE the test body. Does not truncate after — leaving rows visible
    if a failing test needs post-mortem inspection.

    Depends on ``pgvector_pool`` (which skips when PG unavailable), so this
    fixture inherits the same skip behavior.
    """
    async with pgvector_pool.acquire() as conn:
        # Best-effort: table may not exist yet on a first-call test that
        # itself invokes _create_tables. Swallow the missing-table error.
        try:
            await conn.execute("DELETE FROM long_term_facts;")
        except Exception:  # noqa: BLE001 — table may not exist on first call
            pass
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Phase 27 / Plan 27-00 — Test isolation + memory reliability scaffolding.
#
# Adds:
#   - `uses_redis` + `benchmark` pytest markers (registered via pytest_configure).
#   - `pytest_collection_modifyitems` hook that auto-attaches `redis_mock` to
#     every test marked `@pytest.mark.uses_redis` (D-18).
#   - `redis_mock` fixture backed by `fakeredis.aioredis.FakeRedis` (CONTEXT D-20
#     override per RESEARCH §Theme 2 — fakeredis has real list/sorted-set/hash/
#     pipeline semantics that a hand-rolled MagicMock would have to reimplement).
#     Patches BOTH `utils.cache.get_redis` (5 consumer services) AND
#     `redis.asyncio.from_url` (Pitfall 6 — ShortTermMemory bypass).
#   - `app_factory` + `isolated_app` + `isolated_client` fixtures for the
#     create_app() factory introduced in `tests/factories/app.py`.
# ──────────────────────────────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register Phase 27 markers so `@pytest.mark.uses_redis` / `@pytest.mark.benchmark`
    don't trigger ``PytestUnknownMarkWarning``."""
    config.addinivalue_line(
        "markers",
        "uses_redis: test exercises Redis path; redis_mock fixture auto-applied",
    )
    config.addinivalue_line(
        "markers",
        "benchmark: long-running latency benchmark; opt-in via -m benchmark",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-attach `redis_mock` to every test marked `@pytest.mark.uses_redis`.

    Implements D-18: tests opt-in to the fakeredis fixture via marker, not by
    explicitly listing `redis_mock` as a function argument. This keeps the
    marker single-source-of-truth for "this test path touches Redis."
    """
    for item in items:
        # `item.fixturenames` is the resolved fixture list pytest will inject.
        # The pytest stubs don't expose it on the `Item` base class; both the
        # `in`-check and `.append` need the attr-defined suppression.
        if (
            "uses_redis" in item.keywords
            and "redis_mock" not in item.fixturenames  # type: ignore[attr-defined]
        ):
            item.fixturenames.append("redis_mock")  # type: ignore[attr-defined]


@pytest.fixture
async def redis_mock(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """In-memory Redis double for unit tests.

    Backed by ``fakeredis.aioredis.FakeRedis`` (RESEARCH §Theme 2 — overrides
    CONTEXT D-20's MagicMock proposal because fakeredis correctly implements
    GET/SET, lists (RPUSH/LRANGE), sorted sets (ZADD/ZCOUNT), hashes (HSET/HGET/
    HGETALL/HDEL), EXPIRE, pipelines, and Lua ``eval`` out of the box).

    Patches both Redis-access paths so every service receives the fake:
      1. ``utils.cache.get_redis`` — canonical lazy accessor used by 5 services.
      2. ``redis.asyncio.from_url`` — direct path used by
         ``services.memory.memory_service.ShortTermMemory._get_client``
         (Pitfall 6; bonus refactor in plan 27-02 may delegate to ``get_redis``
         but the patch stays as a safety belt for unmigrated tests).

    Also resets ``utils.cache._redis_client`` so a prior test's real connection
    is not reused inside the same pytest process.
    """
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis_stub() -> fakeredis.aioredis.FakeRedis:
        return fake

    # Primary consumer-path patch.
    monkeypatch.setattr("utils.cache.get_redis", _get_redis_stub)

    # Reset cached singleton inside utils.cache so the patch above wins on next
    # lookup even if a prior test populated _redis_client.
    import utils.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_redis_client", None, raising=False)

    # Pitfall 6 — ShortTermMemory direct-from_url bypass. Patched here as a
    # safety belt; plan 27-02 may delegate ShortTermMemory through get_redis.
    async def _from_url_stub(*_args: object, **_kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    monkeypatch.setattr("redis.asyncio.from_url", _from_url_stub)

    yield fake

    # Explicit close — narrow exception tuple (no bare except per CLAUDE.md ERR-01).
    # FakeRedis.aclose() can raise RuntimeError on a closed event loop or
    # AttributeError on a partially-initialized client; either is non-fatal in
    # test teardown.
    try:
        await fake.aclose()
    except (RuntimeError, OSError, AttributeError) as exc:
        from loguru import logger as _logger

        _logger.debug(f"[redis_mock] aclose failed (non-fatal): {exc}")


@pytest.fixture
async def app_factory():  # type: ignore[no-untyped-def]
    """Yields a callable that builds isolated FastAPI apps via create_app().

    Each call resets the full singleton inventory (~34 entries) and constructs
    a fresh FastAPI instance. The teardown calls ``_reset_singletons()`` one
    more time so the next test starts with a clean slate.

    Requires ``main._configure_app`` (introduced in plan 27-01). Tests should
    gate via ``pytest.importorskip`` or a getattr check.
    """
    from tests.factories.app import _reset_singletons, create_app

    created: list[object] = []

    def _factory(**kwargs: object) -> object:
        app = create_app(**kwargs)  # type: ignore[arg-type]
        created.append(app)
        return app

    yield _factory
    # Teardown — leave singletons reset for the next test.
    _reset_singletons()


@pytest.fixture
async def isolated_app(app_factory):  # type: ignore[no-untyped-def]
    """Pre-built isolated FastAPI app for tests that don't need dependency overrides."""
    return app_factory()


@pytest.fixture
async def isolated_client(isolated_app):  # type: ignore[no-untyped-def]
    """ASGI httpx client bound to an isolated FastAPI app.

    Note: ASGITransport skips lifespan execution (Pitfall 4). Adequate for the
    SC-1 cross-contamination test which asserts at the singleton-reset level.
    Tests that need lifespan should use ``httpx.AsyncClient`` + ``LifespanManager``
    directly.
    """
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=isolated_app),
        base_url="http://test",
    ) as client:
        yield client


# ──────────────────────────────────────────────────────────────────────────────
# Phase 33 / Plan 33-01 — TEST-09 reset fixture for the tool registry singleton.
#
# Eliminates order-dependent failures caused by `tests/factories/app.py:
# _reset_singletons()` zeroing `services.agent.tools.registry._registry` mid-suite
# without re-registering the canonical tools. RESEARCH §Q1 Option B
# (single-entry reset list, no importlib.reload — avoids monkeypatch
# interaction risk identified in TestWebSearchToolRun).
#
# Eng-review hardenings:
#   - D1: idempotent register guard `if cls.name not in reg.list()` —
#     ToolRegistry.register() (services/agent/tools/registry.py:39-40)
#     raises ValueError on duplicate; guard removes import-order coupling.
#   - D2: pkgutil-based package introspection auto-discovers future @register'd
#     tools instead of hardcoding the current 4-class list (self-healing).
#
# Acceptance seeds (per D-SEEDS-01): 12345, 67890, 99999. The OCR Cluster C
# (Phase 31 EVT-02 residue) is deferred to v1.10 / TEST-12 candidate; seeded
# runs deselect it via 4 explicit --deselect flags:
#   tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls
#   tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore
#   tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error
#   tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry
#
# Scope discipline (D-RESET-01 audit-mode-before-enforce): single-entry reset
# list = `_registry` only; do NOT broaden to the full `_SINGLETON_INVENTORY`
# in `tests/factories/app.py`. The pkgutil walk only enumerates BaseTool
# subclasses; it does NOT add singletons to the reset surface.
#
# Composition with tests/integration/conftest.py: that file owns its own
# autouse mock (`_mock_local_model_inits` from Phase 30-02) operating on a
# disjoint module surface (HuggingFaceEmbedder.__init__ +
# CrossEncoderReranker.__init__) — the two compose cleanly (RESEARCH §Q6 R2).
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_tool_registry() -> Generator[None, None, None]:
    """Reset services.agent.tools.registry._registry between unit tests.

    See module docstring header for the full TEST-09 / D-RESET-01 /
    RESEARCH §Q1 Option B rationale, eng-review D1+D2 hardenings, the
    three acceptance seeds (12345 / 67890 / 99999), and the four
    OCR Cluster C --deselect node-ids deferred to v1.10 / TEST-12.
    """
    import importlib
    import pkgutil

    import services.agent.tools as _tools_pkg
    import services.agent.tools.registry as _reg
    from services.agent.tools.base import BaseTool
    from services.agent.tools.registry import get_tool_registry

    # D2 — auto-enumerate concrete BaseTool subclasses via pkgutil walk.
    tool_classes: set[type[BaseTool]] = set()
    for modinfo in pkgutil.iter_modules(
        _tools_pkg.__path__, prefix="services.agent.tools."
    ):
        # Skip the abstractions; only concrete tool modules contribute classes.
        if modinfo.name in (
            "services.agent.tools.registry",
            "services.agent.tools.base",
        ):
            continue
        mod = importlib.import_module(modinfo.name)
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseTool)
                and obj is not BaseTool
                and getattr(obj, "name", None)
            ):
                tool_classes.add(obj)

    # Post-condition sentinel — guards against a future refactor that breaks
    # the package layout (e.g., someone moves all tools into a sibling
    # package). 4 = current canonical count (RetrieveTool, RefinedRetrieveTool,
    # WebSearchTool, RecallTool). Fewer = introspection broke; fail loud.
    assert len(tool_classes) >= 4, (
        f"_reset_tool_registry: discovered only {len(tool_classes)} tool "
        f"classes via pkgutil walk; expected >= 4. Package layout may have "
        f"changed under services/agent/tools/."
    )

    # Zero the singleton then re-init via the factory (constructs a fresh
    # empty ToolRegistry()).
    _reg._registry = None
    reg = get_tool_registry()

    # D1 — idempotent register guard. ToolRegistry.register() raises
    # ValueError on duplicate (services/agent/tools/registry.py:39-40).
    # If the tool module was first-imported during this fixture invocation,
    # its @register decorator already populated `reg`; the guard prevents
    # the duplicate. If modules were pre-imported during pytest collection,
    # `reg` is empty and the explicit register fires once. Either path safe.
    for cls in tool_classes:
        if cls.name not in reg.list():
            reg.register(cls)

    yield

    # Defensive teardown — leave clean for the next test's fixture setup.
    _reg._registry = None
