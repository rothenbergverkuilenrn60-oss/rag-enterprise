"""tests/unit/memory/test_save_facts_embed_batch_fallback.py — Phase 27 / TD-05 / C2.

Pins the C2 embed_batch fail-fast fallback contract:

  All three embedders (Ollama/OpenAI/HuggingFace) RAISE on first failed text —
  they do NOT return per-item None. RESEARCH §9 lines 266-280 + adapter
  inspection confirms (services/vectorizer/embedder.py:65-68 for Ollama).

  save_facts MUST wrap embed_batch in
  ``try / except (httpx.HTTPError, RuntimeError, OSError)`` and on failure
  fall back to ``asyncio.gather(*[embed_one(t) for t in texts],
  return_exceptions=True)``. Per-item BaseExceptions count as None and
  contribute to skipped_embed_failures.

Test inventory:
  1. embed_batch raises → falls back to N parallel embed_one calls; all succeed
     → all 5 rows inserted; skipped_embed_failures == 0.
  2. embed_batch raises → embed_one fallback returns per-item; one item raises
     → 4 rows inserted; skipped_embed_failures == 1.
  3. embed_batch raises → loguru captures a per-text warning containing
     ``idx=`` + ``text_len=`` substrings for each failed item (A3 from
     /plan-eng-review — per-text context for ops debugging).
  4. Parametrize over (RuntimeError, httpx.HTTPError, OSError) — narrow
     exception tuple per RESEARCH §9.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from loguru import logger

from services.memory.memory_service import LongTermMemory
from utils.models import ExtractedFact


# -----------------------------------------------------------------------------
# Pattern B — autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# Loguru → caplog bridge — loguru does not propagate to the stdlib logging
# tree by default, so pytest's ``caplog`` fixture sees nothing without a
# bridging sink. Per loguru docs:
#   https://loguru.readthedocs.io/en/stable/resources/recipes.html
@pytest.fixture
def loguru_caplog(caplog):
    """Bridge loguru → caplog so logger.warning(...) is captured."""

    class _PropagateHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(_PropagateHandler(), format="{message}", level="DEBUG")
    caplog.set_level(logging.DEBUG)
    yield caplog
    logger.remove(handler_id)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool() -> tuple[MagicMock, MagicMock]:
    conn = MagicMock(
        execute=AsyncMock(),
        executemany=AsyncMock(),
        fetch=AsyncMock(return_value=[]),
    )
    conn.transaction = MagicMock(return_value=_AcquireCtx(conn))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


def _patch_embedder(
    monkeypatch, *, embed_batch_spy: AsyncMock, embed_one_spy: AsyncMock,
) -> MagicMock:
    fake = MagicMock(embed_batch=embed_batch_spy, embed_one=embed_one_spy)
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: fake,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder",
        lambda: fake,
        raising=False,
    )
    return fake


def _patch_audit(monkeypatch) -> MagicMock:
    mock_audit = MagicMock(log=AsyncMock())
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


def _make_facts(n: int) -> list[ExtractedFact]:
    return [
        ExtractedFact(
            fact=f"fallback test fact {i}",
            category="recurring_topics",
            importance=0.5,
        )
        for i in range(n)
    ]


# -----------------------------------------------------------------------------
# Test 1 — embed_batch raises → per-item gather fallback (all succeed)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc_cls",
    [RuntimeError, httpx.HTTPError, OSError],
)
@pytest.mark.asyncio
async def test_embed_batch_raises_falls_back_to_per_item_gather(monkeypatch, exc_cls):
    """C2 fallback: embed_batch raises → 5 parallel embed_one calls → all OK.

    Parametrize over the narrow exception tuple ``(RuntimeError,
    httpx.HTTPError, OSError)`` so any embedder adapter's failure mode is
    covered.
    """
    embed_batch_spy = AsyncMock(side_effect=exc_cls("Embedding failed for text[0]"))
    embed_one_spy = AsyncMock(return_value=[0.1] * 1024)
    _patch_embedder(
        monkeypatch, embed_batch_spy=embed_batch_spy, embed_one_spy=embed_one_spy,
    )
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)
    facts = _make_facts(5)

    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # embed_batch was attempted once.
    assert embed_batch_spy.call_count == 1
    # Fell back to 5 parallel embed_one calls.
    assert embed_one_spy.call_count == 5, (
        f"C2 fallback: expected 5 embed_one calls, got {embed_one_spy.call_count}"
    )
    # All 5 rows persisted; no embed failures.
    assert result.saved_count == 5
    assert result.skipped_embed_failures == 0
    # executemany called with all 5 rows.
    assert conn.executemany.call_count == 1
    assert len(conn.executemany.call_args.args[1]) == 5


# -----------------------------------------------------------------------------
# Test 2 — embed_batch raises + one per-item failure → partial success
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_embed_batch_fallback_with_one_per_item_failure(monkeypatch):
    """Per-item gather captures one BaseException → skipped_embed_failures == 1.

    asyncio.gather(*..., return_exceptions=True) wraps each per-item failure
    so the iteration finishes; save_facts then partitions per-item results
    by exception type and only INSERTs the successful ones.
    """
    embed_batch_spy = AsyncMock(side_effect=RuntimeError("batch raised"))
    # side_effect list of 5 — item index 2 raises.
    vec = [0.1] * 1024
    embed_one_spy = AsyncMock(
        side_effect=[vec, vec, RuntimeError("text[2] failed"), vec, vec],
    )
    _patch_embedder(
        monkeypatch, embed_batch_spy=embed_batch_spy, embed_one_spy=embed_one_spy,
    )
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)
    facts = _make_facts(5)

    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    assert result.saved_count == 4
    assert result.skipped_embed_failures == 1
    # executemany called with 4 surviving rows.
    assert conn.executemany.call_count == 1
    rows_inserted = conn.executemany.call_args.args[1]
    assert len(rows_inserted) == 4
    # The surviving rows preserve order (indices 0, 1, 3, 4).
    surviving_facts = [row[2] for row in rows_inserted]
    assert surviving_facts == [
        "fallback test fact 0",
        "fallback test fact 1",
        "fallback test fact 3",
        "fallback test fact 4",
    ]


# -----------------------------------------------------------------------------
# Test 3 — A3 per-text fallback log (idx + text_len)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_embed_batch_fallback_logged_per_text(monkeypatch, loguru_caplog):
    """A3 (eng-review): per-text logger.warning emit for each failed embed_one.

    Aggregate-only counter is insufficient signal for ops debugging — they
    need to see which text indices failed and how long they were so they can
    correlate with upstream LLM output. Pin the format string so a future
    refactor that drops idx= or text_len= breaks here.
    """
    embed_batch_spy = AsyncMock(side_effect=RuntimeError("batch raised"))
    vec = [0.1] * 1024
    # Items 1 and 3 fail.
    embed_one_spy = AsyncMock(
        side_effect=[vec, RuntimeError("text[1] failed"), vec, RuntimeError("text[3] failed"), vec],
    )
    _patch_embedder(
        monkeypatch, embed_batch_spy=embed_batch_spy, embed_one_spy=embed_one_spy,
    )
    _patch_audit(monkeypatch)

    pool, _ = _make_fake_pool()
    mem = _make_long(pool)
    facts = _make_facts(5)

    await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # Captured loguru output via the bridge.
    captured = loguru_caplog.text
    assert "embed_batch failed; falling back per-item" in captured, (
        "Top-level 'embed_batch failed' warning missing from log."
    )
    # Per-text emits include idx= + text_len= substrings.
    assert "idx=1" in captured, "Per-text emit for idx=1 missing"
    assert "idx=3" in captured, "Per-text emit for idx=3 missing"
    assert "text_len=" in captured, (
        "Per-text emit missing text_len= context (A3 from /plan-eng-review)."
    )
