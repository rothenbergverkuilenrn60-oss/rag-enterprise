"""
tests/unit/test_retrieve_variant_top_k.py

Verifies _apply_variant_top_k in services/agent/tools/retrieve.py reads the
current_variant_config ContextVar and overrides the LLM-chosen top_k when
the running variant.config sets `top_k_rerank`.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def test_no_variant_returns_llm_choice():
    from services.ab_test.ab_test_service import current_variant_config
    from services.agent.tools.retrieve import _apply_variant_top_k

    tok = current_variant_config.set({})
    try:
        assert _apply_variant_top_k(7) == 7
    finally:
        current_variant_config.reset(tok)


def test_variant_top_k_overrides_llm_choice():
    from services.ab_test.ab_test_service import current_variant_config
    from services.agent.tools.retrieve import _apply_variant_top_k

    tok = current_variant_config.set({"top_k_rerank": 10, "reranker_type": "cross_encoder"})
    try:
        assert _apply_variant_top_k(3) == 10
        assert _apply_variant_top_k(99) == 10
    finally:
        current_variant_config.reset(tok)


def test_variant_without_top_k_field_returns_llm_choice():
    from services.ab_test.ab_test_service import current_variant_config
    from services.agent.tools.retrieve import _apply_variant_top_k

    tok = current_variant_config.set({"reranker_type": "passthrough"})
    try:
        assert _apply_variant_top_k(5) == 5
    finally:
        current_variant_config.reset(tok)


def test_variant_top_k_non_int_returns_llm_choice():
    """Defensive: malformed variant.config (top_k_rerank=str) → fallback to LLM choice."""
    from services.ab_test.ab_test_service import current_variant_config
    from services.agent.tools.retrieve import _apply_variant_top_k

    tok = current_variant_config.set({"top_k_rerank": "ten"})
    try:
        assert _apply_variant_top_k(4) == 4
    finally:
        current_variant_config.reset(tok)


@pytest.mark.asyncio
async def test_contextvar_isolation_across_tasks():
    """contextvar is async-safe — concurrent tasks see their own variant config."""
    import asyncio

    from services.ab_test.ab_test_service import current_variant_config
    from services.agent.tools.retrieve import _apply_variant_top_k

    results: dict[str, int] = {}

    async def worker(name: str, top_k_override: int) -> None:
        current_variant_config.set({"top_k_rerank": top_k_override})
        await asyncio.sleep(0.01)
        results[name] = _apply_variant_top_k(5)

    await asyncio.gather(worker("A", 6), worker("B", 10))
    assert results == {"A": 6, "B": 10}
