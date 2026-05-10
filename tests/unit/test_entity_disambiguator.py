"""tests/unit/test_entity_disambiguator.py — Phase 15 backfill.

Covers EntityDisambiguator (normalize, hint extraction, resolve scoring,
batch and clarification helpers) and RedisEntityLookup (find with alias /
type-specific / fallback / tenant filtering, upsert, delete, enrich).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch):
    import services.nlu.entity_disambiguator as mod
    yield
    monkeypatch.setattr(mod, "_disambiguator", None, raising=False)
    monkeypatch.setattr(mod, "_entity_lookup", None, raising=False)


# ── EntityDisambiguator ────────────────────────────────────────────────────

@pytest.mark.unit
def test_disambiguate_passthrough_for_non_disambiguatable_type():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("Q1", "page_number", query_context="第Q1页")
    assert out.confidence == 1.0
    assert out.disambiguation_method == "exact"
    assert out.needs_clarification is False


@pytest.mark.unit
def test_disambiguate_low_confidence_triggers_clarification():
    """Error/edge path: no hints → confidence < 0.65 → needs_clarification."""
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("张伟", "person", query_context="who is 张伟")
    assert out.confidence < 0.65
    assert out.needs_clarification is True
    assert out.disambiguation_method == "fallback"


@pytest.mark.unit
def test_disambiguate_dept_hint_lifts_confidence():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("张伟", "person", query_context="HR部门的张伟")
    assert out.confidence >= 0.85
    assert out.disambiguation_method == "context"
    assert out.needs_clarification is False


@pytest.mark.unit
def test_disambiguate_role_hint_alone_lifts_confidence():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("李总", "person", query_context="李总监说的话")
    assert out.confidence >= 0.85


@pytest.mark.unit
def test_disambiguate_user_profile_path():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    profile = {"frequent_topics": ["关于张伟的政策"]}
    out = d.disambiguate("张伟", "person", query_context="who is 张伟", user_profile=profile)
    assert out.confidence >= 0.75
    assert out.disambiguation_method in ("profile", "tenant_scope", "fallback", "context")


@pytest.mark.unit
def test_disambiguate_tenant_scope_path():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("张伟", "person", query_context="who is 张伟", tenant_id="acme")
    assert out.disambiguation_method == "tenant_scope"


@pytest.mark.unit
def test_disambiguate_policy_strips_year_version():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    out = d.disambiguate("年假管理办法（2024）", "policy", query_context="2023年的年假")
    assert "2024" not in out.resolved_name


@pytest.mark.unit
def test_disambiguate_batch_runs_each_entity():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    e1 = MagicMock(text="张伟", entity_type="person")
    e2 = MagicMock(text="假期", entity_type="policy_term")
    out = d.disambiguate_batch([e1, e2], query_context="HR")
    assert len(out) == 2


@pytest.mark.unit
def test_build_clarification_hint_empty_list_returns_empty():
    from services.nlu.entity_disambiguator import EntityDisambiguator
    d = EntityDisambiguator()
    assert d.build_clarification_hint([]) == ""


@pytest.mark.unit
def test_build_clarification_hint_lists_entities():
    from services.nlu.entity_disambiguator import (
        DisambiguatedEntity,
        EntityDisambiguator,
    )
    d = EntityDisambiguator()
    e = DisambiguatedEntity(
        original_text="张伟", entity_type="person",
        resolved_id="x", resolved_name="张伟",
        confidence=0.5, needs_clarification=True,
    )
    out = d.build_clarification_hint([e])
    assert "张伟" in out
    assert "person" in out


@pytest.mark.unit
def test_get_disambiguator_singleton():
    from services.nlu.entity_disambiguator import get_disambiguator
    a = get_disambiguator()
    b = get_disambiguator()
    assert a is b


# ── RedisEntityLookup ──────────────────────────────────────────────────────

def _make_lookup(redis_mock):
    from services.nlu.entity_disambiguator import RedisEntityLookup
    lk = RedisEntityLookup.__new__(RedisEntityLookup)

    async def _r():
        return redis_mock

    lk._get_redis = _r
    lk._redis = redis_mock
    return lk


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_find_via_alias():
    record = {"canonical_name": "人力资源部", "entity_type": "department", "tenant_ids": []}
    r = MagicMock()
    r.get = AsyncMock(return_value=b"\xe4\xba\xba\xe5\x8a\x9b\xe8\xb5\x84\xe6\xba\x90\xe9\x83\xa8")  # "人力资源部"
    r.hget = AsyncMock(return_value=json.dumps(record))
    lk = _make_lookup(r)
    out = await lk.find("HR", entity_type="department")
    assert out is not None
    assert out["canonical_name"] == "人力资源部"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_find_falls_back_to_full_scan():
    record = {"canonical_name": "年假", "entity_type": "policy_term", "tenant_ids": []}
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    call_count = {"n": 0}

    async def hget(key, _name):
        call_count["n"] += 1
        if "policy_term" in key:
            return json.dumps(record)
        return None

    r.hget = hget
    lk = _make_lookup(r)
    out = await lk.find("年假")  # no entity_type → scan
    assert out is not None
    assert out["canonical_name"] == "年假"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_find_returns_none_for_missing():
    """Error path: not in any KB → None."""
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.hget = AsyncMock(return_value=None)
    lk = _make_lookup(r)
    out = await lk.find("nonexistent")
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_tenant_filter_blocks_unauthorized():
    """Error path: tenant_id not in record's tenant_ids → not returned."""
    record = {"canonical_name": "x", "entity_type": "policy_term", "tenant_ids": ["acme"]}
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.hget = AsyncMock(return_value=json.dumps(record))
    lk = _make_lookup(r)
    out = await lk.find("x", entity_type="policy_term", tenant_id="other")
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_upsert_pipelines_writes():
    r = MagicMock()
    pipe = MagicMock()
    pipe.hset = MagicMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock()
    r.pipeline = MagicMock(return_value=pipe)
    lk = _make_lookup(r)
    await lk.upsert(
        "person", "张伟",
        aliases=["小张", "Z. Wang"],
        description="HR Manager",
    )
    pipe.hset.assert_called_once()
    assert pipe.set.call_count == 2
    pipe.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_delete_calls_hdel():
    r = MagicMock()
    r.hdel = AsyncMock()
    lk = _make_lookup(r)
    await lk.delete("person", "张伟")
    r.hdel.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_enrich_when_found():
    record = {
        "canonical_name": "人力资源部",
        "entity_type": "department",
        "description": "管理 HR 事务",
        "metadata": {"head": "李四"},
        "tenant_ids": [],
    }
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.hget = AsyncMock(return_value=json.dumps(record))
    lk = _make_lookup(r)
    out = await lk.enrich_entity("人力资源部", "department")
    assert out["source"] == "entity_kb"
    assert out["canonical_name"] == "人力资源部"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_lookup_enrich_when_missing():
    """Error path: not found → returns basic info with source=not_found."""
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.hget = AsyncMock(return_value=None)
    lk = _make_lookup(r)
    out = await lk.enrich_entity("nope", "person")
    assert out["source"] == "not_found"


@pytest.mark.unit
def test_get_entity_lookup_singleton():
    from services.nlu.entity_disambiguator import get_entity_lookup
    a = get_entity_lookup()
    b = get_entity_lookup()
    assert a is b
