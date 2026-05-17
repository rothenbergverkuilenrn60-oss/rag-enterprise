# =============================================================================
# services/memory/memory_service.py
# 记忆服务：短期记忆（Redis）+ 长期记忆（PostgreSQL）+ 用户画像
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

import asyncpg
import redis.asyncio
from loguru import logger
from pgvector.asyncpg import register_vector

from utils.asyncpg_helper import prepare_dsn
from utils.models import ExtractedFact


# ══════════════════════════════════════════════════════════════════════════════
# 类型化异常 / Typed exceptions
# ══════════════════════════════════════════════════════════════════════════════
class MemoryFactWriteError(Exception):
    """Typed error for save_fact embedding or persistence failure.

    Wraps either ``asyncpg.PostgresError`` OR an embedding-adapter exception
    so the ``dispatch_extraction`` wrapper can surface it via ``log_task_error``
    without conflating the two failure modes at the call site.
    """


class MemoryForgetError(Exception):
    """Typed error for forget_user DB failure.

    Wraps ``asyncpg.PostgresError`` so the controller can surface a sanitized
    500 without exposing DB internals. Mirrors ``MemoryFactWriteError``.
    """


# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class ConversationTurn:
    role:       str          # "user" | "assistant"
    content:    str
    timestamp:  float        = field(default_factory=time.time)
    intent:     str          = ""
    entities:   list[dict]   = field(default_factory=list)
    sources:    list[str]    = field(default_factory=list)   # 引用的文档 ID


@dataclass
class UserProfile:
    """用户画像：记录用户的兴趣、常用查询领域、反馈偏好。"""
    user_id:        str
    tenant_id:      str         = ""
    frequent_topics: list[str]  = field(default_factory=list)   # 常问领域
    preferred_detail: str       = "medium"   # "brief" | "medium" | "detailed"
    query_count:    int         = 0
    positive_count: int         = 0
    negative_count: int         = 0
    last_active:    float       = field(default_factory=time.time)
    metadata:       dict        = field(default_factory=dict)

    @property
    def satisfaction_rate(self) -> float:
        total = self.positive_count + self.negative_count
        return self.positive_count / total if total > 0 else 0.5


@dataclass
class MemoryContext:
    """传递给下游的完整记忆上下文。"""
    session_id:      str
    user_id:         str
    tenant_id:       str
    short_term:      list[ConversationTurn]   # 本次会话历史
    long_term_facts: list[str]                # 长期记忆中的相关事实
    user_profile:    UserProfile | None
    context_summary: str = ""                 # NLU 提炼的对话摘要


# ══════════════════════════════════════════════════════════════════════════════
# Phase 27 / TD-05 — SaveFactsResult for batch save_facts() API.
#
# Returned by ``LongTermMemory.save_facts`` so callers (ExtractorAgent + the
# D-12 ``save_fact`` wrapper) can observe how many facts were persisted vs.
# skipped because of embed failures or SK-01 silent-skip near-duplicate
# enforcement (v1.8 -- duplicates are filtered from rows_to_insert; audit row
# still emitted per dup for ops dashboard visibility).
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class SaveFactsResult:
    """Per-call summary from ``LongTermMemory.save_facts``.

    Fields:
        saved_count: rows actually executemany-INSERTed (= batch size
            minus embed failures minus near-duplicate skips).
        skipped_near_duplicates: how many facts in this batch were filtered
            from ``rows_to_insert`` by SK-01 silent-skip enforcement (v1.8).
            ``MEMORY_NEAR_DUPLICATE_SKIPPED`` audit row still emitted per skip
            for ops dashboard visibility (D-09 carry-forward).
        skipped_embed_failures: how many facts dropped because either embed_batch
            raised AND the per-item gather fallback also raised for that item
            (C2 fail-fast handling).
    """
    saved_count: int
    skipped_near_duplicates: int
    skipped_embed_failures: int


# Category → importance bucket lookup (mirrors utils.models.ExtractedFact
# cross-field validator). Used by ``_round_importance_to_literal`` so the
# D-12 ``save_fact`` wrapper can synthesize a valid ExtractedFact from raw
# (fact: str, importance: float) inputs without tripping the Pydantic
# ``@model_validator(mode="after")`` that requires the 1:1 mapping.
_IMPORTANCE_BUCKETS: tuple[
    tuple[float, Literal["stable_preferences", "recurring_topics", "transient_context"], Literal[0.2, 0.5, 0.8]],
    ...,
] = (
    # (upper_bound_exclusive, category, importance) — first match wins.
    (0.35, "transient_context",  0.2),
    (0.65, "recurring_topics",   0.5),
    (float("inf"), "stable_preferences", 0.8),
)


def _round_importance_to_literal(
    value: float,
) -> tuple[
    Literal["stable_preferences", "recurring_topics", "transient_context"],
    Literal[0.2, 0.5, 0.8],
]:
    """Bucket a raw float importance into the (category, importance) literal pair
    that satisfies the ``ExtractedFact`` cross-field validator.

    D-12 wrapper needs both the category AND the importance because
    ``utils.models.ExtractedFact`` enforces a 1:1 category↔importance map:
        stable_preferences → 0.8
        recurring_topics   → 0.5
        transient_context  → 0.2

    Mapping (RESEARCH §Theme 4 "Caveat for D-12 wrapper"):
        x < 0.35           → ("transient_context",   0.2)
        0.35 <= x < 0.65   → ("recurring_topics",    0.5)
        x >= 0.65          → ("stable_preferences",  0.8)

    The default ``importance=0.5`` from the singular ``save_fact`` signature
    maps to ``("recurring_topics", 0.5)`` — matches the Phase 23 default
    category used by ExtractorAgent when category is unspecified.
    """
    for upper_exclusive, category, literal_importance in _IMPORTANCE_BUCKETS:
        if value < upper_exclusive:
            return category, literal_importance
    # Unreachable — final bucket has upper=inf. mypy needs the explicit return.
    return "stable_preferences", 0.8


# ══════════════════════════════════════════════════════════════════════════════
# 短期记忆（Redis）
# ══════════════════════════════════════════════════════════════════════════════
class ShortTermMemory:
    """
    基于 Redis 的会话历史存储。
    Key: session:{session_id}:turns
    TTL: 会话超时时间（默认 2 小时）
    """

    def __init__(self, session_ttl: int = 7200) -> None:
        self._ttl = session_ttl
        self._client = None

    async def _get_client(self):
        # Plan 27-02 / TD-06 (D-19 follow-on): delegate to utils.cache.get_redis
        # so the singleton accessor is the sole Redis-construction path. Closes
        # the last bypass (RESEARCH §6) and enables single-target mocking.
        if self._client is None:
            from utils.cache import get_redis

            self._client = await get_redis()
        return self._client

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:turns"

    async def append(self, session_id: str, turn: ConversationTurn) -> None:
        r = await self._get_client()
        key = self._key(session_id)
        await r.rpush(key, json.dumps(asdict(turn), ensure_ascii=False))
        await r.expire(key, self._ttl)

    async def get_history(
        self, session_id: str, max_turns: int = 10
    ) -> list[ConversationTurn]:
        try:
            r = await self._get_client()
            key = self._key(session_id)
            raw_list = await r.lrange(key, -max_turns * 2, -1)
            return [ConversationTurn(**json.loads(s)) for s in raw_list]
        except redis.asyncio.RedisError as exc:
            logger.error("memory service failure", session_id=session_id, exc_info=exc)
            return []

    async def clear(self, session_id: str) -> None:
        r = await self._get_client()
        await r.delete(self._key(session_id))

    async def get_formatted_history(
        self, session_id: str, max_turns: int = 6
    ) -> list[dict[str, str]]:
        """返回符合 LLM chat 格式的历史列表。"""
        turns = await self.get_history(session_id, max_turns)
        return [{"role": t.role, "content": t.content} for t in turns]


# ══════════════════════════════════════════════════════════════════════════════
# 长期记忆（PostgreSQL）
# ══════════════════════════════════════════════════════════════════════════════
class LongTermMemory:
    """
    基于 PostgreSQL 的持久化记忆存储。
    存储用户画像、重要事实、查询历史摘要。
    表结构在 create_tables() 中自动创建。
    """

    def __init__(self) -> None:
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            from config.settings import settings

            async def _init_conn(conn: "asyncpg.Connection") -> None:
                # Pitfall #1: register pgvector codec on every acquired connection
                # so $N::vector bindings in save_fact (Plan 23-02) resolve correctly.
                await register_vector(conn)

            # Plan 26-03 / TD-03: centralized DSN normalization (was 7-line inline strip).
            dsn, ssl_kwarg = prepare_dsn(settings.pg_dsn)
            self._pool = await asyncpg.create_pool(
                dsn, min_size=2, max_size=10, init=_init_conn, **ssl_kwarg,
            )
            await self._create_tables()
        return self._pool

    async def close(self) -> None:
        """Close the asyncpg pool. Idempotent — safe to call when pool was never built.

        Plan 26-03 / TD-03. Called from main.py lifespan shutdown by Plan 26-05.
        """
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _create_tables(self) -> None:
        from config.settings import settings

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id          TEXT PRIMARY KEY,
                    tenant_id        TEXT NOT NULL DEFAULT '',
                    frequent_topics  JSONB DEFAULT '[]',
                    preferred_detail TEXT DEFAULT 'medium',
                    query_count      INTEGER DEFAULT 0,
                    positive_count   INTEGER DEFAULT 0,
                    negative_count   INTEGER DEFAULT 0,
                    last_active      FLOAT DEFAULT 0,
                    metadata         JSONB DEFAULT '{}'
                );

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

                CREATE TABLE IF NOT EXISTS query_history (
                    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id      TEXT NOT NULL,
                    tenant_id    TEXT NOT NULL DEFAULT '',
                    session_id   TEXT NOT NULL,
                    query        TEXT NOT NULL,
                    intent       TEXT DEFAULT '',
                    answer_short TEXT DEFAULT '',
                    feedback     SMALLINT DEFAULT 0,   -- 1=positive, -1=negative, 0=none
                    created_at   TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS qh_user_idx ON query_history(user_id, tenant_id);
            """)

            # Phase 23 / MEM-01 — pgvector schema migration for long_term_facts.
            # Pure-additive idempotency: ALTER ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
            # Pattern map analog 2 forbids drop-rebuild here (no destructive index churn on this table).
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await conn.execute(
                f"ALTER TABLE long_term_facts ADD COLUMN IF NOT EXISTS embedding vector({settings.embedding_dim});"
            )
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx
                    ON long_term_facts USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64);
            """)

    async def get_user_profile(self, user_id: str, tenant_id: str = "") -> UserProfile:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM user_profiles WHERE user_id=$1 AND tenant_id=$2",
                    user_id, tenant_id,
                )
            if row:
                return UserProfile(
                    user_id=row["user_id"],
                    tenant_id=row["tenant_id"],
                    frequent_topics=json.loads(row["frequent_topics"] or "[]"),
                    preferred_detail=row["preferred_detail"],
                    query_count=row["query_count"],
                    positive_count=row["positive_count"],
                    negative_count=row["negative_count"],
                    last_active=row["last_active"],
                    metadata=json.loads(row["metadata"] or "{}"),
                )
        except asyncpg.PostgresError as exc:
            logger.error("memory service failure", operation="get_profile", exc_info=exc)
        return UserProfile(user_id=user_id, tenant_id=tenant_id)

    async def upsert_user_profile(self, profile: UserProfile) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_profiles
                        (user_id, tenant_id, frequent_topics, preferred_detail,
                         query_count, positive_count, negative_count, last_active, metadata)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (user_id) DO UPDATE SET
                        frequent_topics = EXCLUDED.frequent_topics,
                        preferred_detail= EXCLUDED.preferred_detail,
                        query_count     = EXCLUDED.query_count,
                        positive_count  = EXCLUDED.positive_count,
                        negative_count  = EXCLUDED.negative_count,
                        last_active     = EXCLUDED.last_active,
                        metadata        = EXCLUDED.metadata
                """,
                    profile.user_id, profile.tenant_id,
                    json.dumps(profile.frequent_topics, ensure_ascii=False),
                    profile.preferred_detail,
                    profile.query_count, profile.positive_count, profile.negative_count,
                    profile.last_active,
                    json.dumps(profile.metadata, ensure_ascii=False),
                )
        except asyncpg.PostgresError as exc:
            logger.error("memory service failure", operation="upsert_profile", exc_info=exc)

    async def get_relevant_facts(
        self, user_id: str, tenant_id: str, query: str, limit: int = 5
    ) -> list[str]:
        """Retrieve top-K facts semantically relevant to ``query`` (Phase 24 / MEM-06).

        Replaces the v1.0 popularity-ranked path (``ORDER BY importance DESC,
        created_at DESC``) with pgvector cosine-similarity recall inside an
        explicit transaction so ``SET LOCAL`` GUC changes take effect (Pitfall 2).

        HNSW tuning (D-A1 / D-A2):
        - ``hnsw.iterative_scan = 'strict_order'`` — exact top-K under pre-filter;
          slightly slower than ``relaxed_order`` but preserves ROADMAP SC-1
          cosine-quality contract.
        - ``hnsw.ef_search = settings.pgvector_ef_search_filtered`` — shared
          tuning knob with ``vector_store.py`` (T-08-01 precedent).

        ORDER BY: ``embedding <=> $3::vector, importance DESC, created_at DESC``
        (ROADMAP tie-break literal; cosine distance primary, then recency/quality).

        Returns ``[]`` on any failure — embedder down or DB unreachable — so the
        caller (RecallTool) receives a stable empty list rather than an exception
        (Pitfall 6 contract).

        Lazy imports inside method body for circular-import resilience (Phase 23
        convention shared with ``save_fact``, ``_get_pool``, ``_create_tables``).
        """
        # Lazy imports — circular-import resilience (Phase 23 convention)
        import httpx

        from config.settings import settings
        from services.vectorizer.embedder import get_embedder

        # Step 1: embed the query (separate try block — distinguish embedder vs DB)
        try:
            q_vec: list[float] = await get_embedder().embed_one(query)
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            # Narrow-exception tuple matches save_fact precedent (lines 303-313):
            #   RuntimeError    — OllamaEmbedder.embed_batch re-raise (embedder.py:68)
            #   httpx.HTTPError — Ollama + OpenAI transport failures
            #   OSError         — HuggingFace torch device / model-load failures
            logger.error(
                "memory service failure", operation="get_facts_embed", exc_info=exc,
            )
            return []

        # Step 2: HNSW filtered recall inside explicit txn (Pitfall 2 mitigation)
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
                    await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
                    await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
                    rows = await conn.fetch(
                        """SELECT fact FROM long_term_facts
                           WHERE user_id=$1 AND tenant_id=$2
                           ORDER BY embedding <=> $3::vector,
                                    importance DESC,
                                    created_at DESC
                           LIMIT $4""",
                        user_id, tenant_id, q_vec, limit,
                    )
            return [r["fact"] for r in rows]
        except asyncpg.PostgresError as exc:
            logger.error(
                "memory service failure", operation="get_facts_semantic", exc_info=exc,
            )
            return []

    async def _is_near_duplicate(
        self,
        conn: "asyncpg.Connection",
        *,
        user_id: str,
        tenant_id: str,
        embedding: list[float],
        threshold: float,
    ) -> tuple[bool, float | None]:
        """Cosine near-duplicate precheck for ``save_fact`` (Phase 27 / TD-04).

        Returns ``(is_duplicate, nearest_cosine_distance)``. Distance comes from
        pgvector's cosine operator (``<=>``): 0 = identical, 2 = opposite.

        Mirrors the GUC discipline from ``get_relevant_facts:336-352`` so the
        HNSW index ``ltf_emb_hnsw_idx`` participates under the per-(user,tenant)
        pre-filter (v1.1 Phase 8 / v1.6 Phase 24 carry-forward).

        Uses ``ORDER BY ... LIMIT 1`` (not ``WHERE ... < threshold LIMIT 1``)
        so the caller can surface the actual nearest distance in the audit row
        (D-08: ``detail.nearest_distance``).

        On empty table → ``(False, None)``. Caller wraps this method in
        ``try / except asyncpg.PostgresError`` for fail-OPEN semantics per
        RESEARCH §Theme 3 "Failure mode policy".
        """
        from config.settings import settings

        async with conn.transaction():
            ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
            await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
            row = await conn.fetchrow(
                """SELECT embedding <=> $3::vector AS dist
                   FROM long_term_facts
                   WHERE user_id=$1 AND tenant_id=$2
                   ORDER BY embedding <=> $3::vector
                   LIMIT 1""",
                user_id, tenant_id, embedding,
            )
        if row is None:
            return (False, None)
        dist = float(row["dist"])
        return (dist < threshold, dist)

    @staticmethod
    async def _fire_near_duplicate_audit(
        user_id: str, tenant_id: str, fact: str, dist: float | None,
    ) -> None:
        """Best-effort audit emit for near-duplicate detections (SK-01 v1.8).

        v1.8 SK-01 enforcement live: caller ``save_facts`` filters the duplicate
        from ``rows_to_insert``; this audit emit is now the sole DB-visible
        artifact of a skipped duplicate. Carry-forward from v1.6 Phase 25
        EVICT-02 audit-mode-before-enforce lifecycle.

        Audit-write failure is non-fatal (v1.6 GDPR T1 Pattern D): logged at
        warning level, swallowed so the caller's skip-INSERT can proceed.
        """
        from services.audit.audit_service import (
            AUDIT_DETAIL_TRUNCATE_LEN,
            AuditAction,
            AuditEvent,
            AuditResult,
            get_audit_service,
        )

        try:
            await get_audit_service().log(AuditEvent(
                user_id=user_id,
                tenant_id=tenant_id,
                action=AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED,
                resource_id="",
                result=AuditResult.SKIPPED,  # SK-01 v1.8 -- INSERT IS skipped by caller
                detail={
                    "fact_truncated": fact[:AUDIT_DETAIL_TRUNCATE_LEN],
                    "nearest_distance": dist,
                },
            ))
        except Exception as exc:  # noqa: BLE001 — audit-write failure must NOT block (v1.6 GDPR T1)
            logger.warning("audit write failed (non-fatal): {}", exc)

    async def _bulk_near_duplicate_check_raw(
        self,
        conn: "asyncpg.Connection",
        *,
        user_id: str,
        tenant_id: str,
        embeddings: list[list[float]],
        threshold: float,
    ) -> set[int]:
        """Bulk cosine near-duplicate check for save_facts batch path (Phase 27 / TD-05).

        Returns the set of zero-based indices in ``embeddings`` whose closest
        cosine distance to an existing (user_id, tenant_id) row is below
        ``threshold``. Implements C1 of plan 27-04: the SQL MUST use
        ``unnest($1::text[]) WITH ORDINALITY`` + inline ``vec_txt::vector`` cast
        because the ``pgvector.asyncpg`` codec registered in ``_get_pool._init_conn``
        hijacks ``$1::vector[]`` parameter binding (empirically validated against
        live PG — RESEARCH §10 lines 281-304 / D-13). Pass ``$1`` as a list of
        pgvector text literals: ``'[0.1,0.2,...]'``.

        GUC discipline (``hnsw.iterative_scan`` + ``hnsw.ef_search``) MUST be
        established by the CALLER before invoking this helper. This ``_raw``
        variant does NOT open a ``conn.transaction()`` and does NOT issue
        ``SET LOCAL`` — the caller owns the txn and GUCs (A1-A: SAVEPOINT release
        would revert ``SET LOCAL`` before the bulk SELECT runs, silently degrading
        the HNSW scan — plan-review finding 29-00).

        Caller MUST wrap the call in ``try / except asyncpg.PostgresError`` for
        fail-OPEN semantics (matches save_fact precheck contract).
        """
        # Build pgvector text literals for the bulk binding (C1).
        vec_literals = [
            "[" + ",".join(str(x) for x in vec) + "]" for vec in embeddings
        ]

        rows = await conn.fetch(
            """SELECT (idx - 1) AS zero_idx
               FROM unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)
               WHERE EXISTS (
                   SELECT 1 FROM long_term_facts
                   WHERE user_id = $2
                     AND tenant_id = $3
                     AND embedding <=> vec_txt::vector < $4
               )""",
            vec_literals, user_id, tenant_id, threshold,
        )
        return {row["zero_idx"] for row in rows}

    async def save_facts(
        self,
        facts: list[ExtractedFact],
        *,
        user_id: str,
        tenant_id: str,
        source_doc: str = "",
    ) -> SaveFactsResult:
        """Batch persist a list of ``ExtractedFact`` rows in O(1) PG round-trips
        (Phase 27 / TD-05 / SC-4).

        Wire shape (typical N=5, no duplicates, no embed failures):
            1× embed_batch ............ embedder (one call, all texts)
            1× pg_advisory_xact_lock .. PG (TOC-01 v1.8 lock — see below)
            1× bulk dedupe SELECT ..... PG (C1 unnest text[] cast)
            1× executemany INSERT ..... PG
            K× audit_log emit ......... K = duplicate count (D-09 best-effort)
        Total: 4 + K PG round-trips (was: 3 + K pre-29-00).

        Advisory-lock discipline (TOC-01 v1.8 / D-TOC-01):
            The precheck SELECT and executemany INSERT are wrapped in a single
            ``async with conn.transaction():`` that begins with
            ``SELECT pg_advisory_xact_lock(hashtext($1 || '|' || $2))``
            keyed on ``(user_id, tenant_id)``. Lock is auto-released at txn end.
            Granularity: per-(user_id, tenant_id) — writers for different pairs
            do NOT serialize. The ``'|'`` separator prevents prefix collision.
            See .planning/phases/29-toctou-silent-skip-enforcement/29-CONTEXT.md
            D-TOC-01 for full rationale.

        GUC discipline (A1-A inlining — plan-review finding 29-00):
            ``SET LOCAL hnsw.iterative_scan = 'strict_order'`` and
            ``SET LOCAL hnsw.ef_search`` are issued inside the OUTER advisory-lock
            transaction (NOT inside a nested SAVEPOINT). ``_bulk_near_duplicate_check_raw``
            runs inside the same outer txn — GUCs remain in effect. Moving these
            into an inner ``conn.transaction()`` (SAVEPOINT) would revert them at
            SAVEPOINT release, silently degrading the HNSW scan.

        Failure modes:
            - empty facts list:          early-return ``SaveFactsResult(0, 0, 0)``.
            - embed_batch raises:        C2 fallback to ``asyncio.gather(*embed_one,
                                         return_exceptions=True)``; per-item
                                         exceptions count as ``skipped_embed_failures``.
            - all embeds fail:           return ``SaveFactsResult(0, 0, N)``;
                                         executemany NOT called.
            - lock acquisition raises:   ``asyncpg.PostgresError`` → logged →
                                         re-raised as ``MemoryFactWriteError``
                                         (lock failure = persistence failure).
            - bulk dedupe SQL raises:    fail-OPEN (log warning, treat as no-dup);
                                         executemany still runs.
            - executemany raises:        re-raised as ``MemoryFactWriteError``;
                                         no partial-batch row count surfaced
                                         because asyncpg.executemany is atomic
                                         per-statement (whole batch fails together).

        SK-01 v1.8 silent-skip enforcement: duplicates are filtered from
        rows_to_insert before executemany; audit row still emitted per dup
        for ops dashboard visibility (D-09 audit emit preserved per D-SK-01).
        """
        # Early return — keep the contract observable from the test harness
        # (embedder NOT called, executemany NOT called).
        if not facts:
            return SaveFactsResult(0, 0, 0)

        # Lazy imports — circular-import resilience (Phase 23 convention).
        import httpx

        from config.settings import settings
        from services.vectorizer.embedder import get_embedder

        embedder = get_embedder()
        embed_failures = 0
        texts = [f.fact for f in facts]
        embeddings: list[list[float] | None]
        try:
            # Happy path — single batch call returns N vectors.
            embeddings = list(await embedder.embed_batch(texts))
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            # C2 fallback — all 3 embedders RAISE on first failed text (they do
            # NOT return per-item None). Fall back to per-item gather with
            # return_exceptions=True so partial-success is possible.
            logger.warning(
                "embed_batch failed; falling back per-item: {}", exc,
            )
            per_item: list[BaseException | list[float]] = list(
                await asyncio.gather(
                    *[embedder.embed_one(t) for t in texts],
                    return_exceptions=True,
                ),
            )
            embeddings = []
            for idx, result in enumerate(per_item):
                if isinstance(result, BaseException):
                    # A3 (eng-review) — per-text context for ops debugging;
                    # aggregate counter alone is insufficient signal.
                    logger.warning(
                        "embed_batch fallback: idx={} text_len={} exc={!r}",
                        idx, len(facts[idx].fact), result,
                    )
                    embeddings.append(None)
                    embed_failures += 1
                else:
                    embeddings.append(result)

        # Step 2 — drop embed-failed entries (preserves original positional
        # indexing inside ``indexed`` so dup_zero_idxs lines up with the
        # post-filter list passed to _bulk_near_duplicate_check_raw).
        indexed: list[tuple[int, ExtractedFact, list[float]]] = [
            (i, f, e)
            for i, (f, e) in enumerate(zip(facts, embeddings, strict=True))
            if e is not None
        ]
        if not indexed:
            # Every embed failed — nothing to persist, nothing to dedupe.
            return SaveFactsResult(0, 0, embed_failures)

        # Step 3 — acquire pool, then wrap precheck + INSERT in an advisory-lock
        # transaction to close the TOCTOU race (TOC-01 v1.8 / D-TOC-01).
        # embed_batch (Step 1) deliberately runs OUTSIDE the lock so per-user
        # write throughput is not serialized on the slow embedding step
        # (29-CONTEXT Open Risks #1).
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            valid_embeddings = [e for _, _, e in indexed]
            async with conn.transaction():
                # TOC-01 v1.8 — acquire per-(user_id, tenant_id) advisory lock.
                # '|' separator prevents prefix collision: ('alice','tcorp') ≠ ('alicetcorp','').
                try:
                    await conn.execute(  # TOC-01 v1.8
                        "SELECT pg_advisory_xact_lock(hashtext($1 || '|' || $2))",
                        user_id, tenant_id,
                    )
                except asyncpg.PostgresError as exc:
                    logger.error(
                        "memory service failure",
                        operation="save_facts_lock",
                        exc_info=exc,
                    )
                    raise MemoryFactWriteError("lock acquisition failed") from exc

                # A1-A inlined GUC — SET LOCAL inside the OUTER txn (NOT a nested
                # SAVEPOINT) so the GUCs are still in effect when the bulk SELECT runs.
                # A nested conn.transaction() (SAVEPOINT) would revert SET LOCAL at
                # SAVEPOINT release — plan-review finding 29-00 A1-A.
                ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
                await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")  # A1-A inlined GUC
                await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")  # A1-A inlined GUC

                try:
                    dup_zero_idxs = await self._bulk_near_duplicate_check_raw(
                        conn,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        embeddings=valid_embeddings,
                        threshold=settings.memory_near_duplicate_threshold,
                    )
                except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
                    # Fail-OPEN — mirrors save_fact precheck contract.
                    logger.warning(
                        "bulk dedupe check failed (fail-open): {}", exc,
                    )
                    dup_zero_idxs = set()

                # Step 4 — fire audit rows for each duplicate (D-09 audit emit,
                # preserved by SK-01 for ops dashboard visibility).
                # Best-effort, parallel via gather(return_exceptions=True). dist=None
                # on the bulk path because the bulk SELECT doesn't return per-row
                # distance (out of scope per RESEARCH; v1.8 follow-up).
                if dup_zero_idxs:
                    audit_tasks = [
                        self._fire_near_duplicate_audit(
                            user_id, tenant_id, indexed[local_i][1].fact, None,
                        )
                        for local_i in dup_zero_idxs
                    ]
                    await asyncio.gather(*audit_tasks, return_exceptions=True)

                # Step 5 — SK-01 silent-skip: filter duplicates from rows_to_insert
                # before executemany. Only non-duplicate rows are INSERTed.
                # INSERT SQL kept verbatim from the singular save_fact path so a
                # single bulk-cast precedent exists in the codebase.
                rows_to_insert = [
                    (user_id, tenant_id, f.fact, source_doc, f.importance, e)
                    for local_i, (_, f, e) in enumerate(indexed)
                    if local_i not in dup_zero_idxs
                ]
                if not rows_to_insert:
                    # Entire batch was duplicates -- skip executemany entirely.
                    # asyncpg behavior on empty executemany is implementation-defined;
                    # explicit short-circuit is safer + saves 1 RTT.
                    return SaveFactsResult(
                        saved_count=0,
                        skipped_near_duplicates=len(dup_zero_idxs),
                        skipped_embed_failures=embed_failures,
                    )
                try:
                    await conn.executemany(
                        """INSERT INTO long_term_facts
                           (user_id, tenant_id, fact, source_doc, importance, embedding)
                           VALUES ($1,$2,$3,$4,$5,$6::vector)""",
                        rows_to_insert,
                    )
                except asyncpg.PostgresError as exc:
                    logger.error(
                        "memory service failure",
                        operation="save_facts",
                        exc_info=exc,
                    )
                    raise MemoryFactWriteError("batch persistence failed") from exc

        return SaveFactsResult(
            saved_count=len(rows_to_insert),
            skipped_near_duplicates=len(dup_zero_idxs),
            skipped_embed_failures=embed_failures,
        )

    async def save_fact(
        self, user_id: str, tenant_id: str,
        fact: str, source_doc: str = "", importance: float = 0.5,
    ) -> None:
        """Singular save (D-12 wrapper around ``save_facts``).

        Phase 27 / TD-05: now a thin delegate to ``save_facts([ExtractedFact(...)])``
        so the batch path is the single source of truth for embed-on-write,
        near-duplicate audit emit, and INSERT. The pre-27-03 embed-failure
        raise contract is preserved: if the underlying ``save_facts`` returns
        ``saved_count == 0`` AND ``skipped_embed_failures > 0`` (sole row
        failed to embed), raise ``MemoryFactWriteError``.

        ``importance`` is bucketed to the nearest ``ExtractedFact.importance``
        Literal {0.2, 0.5, 0.8} via ``_round_importance_to_literal``; the
        matching category is paired so the ``ExtractedFact``
        ``@model_validator`` 1:1 mapping is satisfied (RESEARCH §Theme 4
        "Caveat for D-12 wrapper" lines 752-757).
        """
        category, rounded_importance = _round_importance_to_literal(importance)
        try:
            extracted = ExtractedFact(
                fact=fact, category=category, importance=rounded_importance,
            )
        except ValueError as exc:
            # ``ExtractedFact._fact_len`` rejects empty/over-200-char strings.
            # Preserve fail-fast semantics; do NOT wrap in MemoryFactWriteError
            # (that's reserved for embed/persistence failures).
            logger.error(
                "memory service failure", operation="save_fact_validate", exc_info=exc,
            )
            raise
        result = await self.save_facts(
            [extracted],
            user_id=user_id,
            tenant_id=tenant_id,
            source_doc=source_doc,
        )
        # Preserve pre-27-03 embed-failure contract for singular callers.
        if result.saved_count == 0 and result.skipped_embed_failures > 0:
            raise MemoryFactWriteError("embedding failed")

    async def forget_user(self, user_id: str, tenant_id: str) -> int:
        """Delete all long_term_facts rows for a (user_id, tenant_id) pair.

        Chunked at 1000 rows per txn (T7 — eng-review outside voice F1) to avoid
        statement_timeout on large buckets and reduce lock contention with the
        eviction CronJob. Each chunk is an implicit asyncpg txn (auto-commit), so
        a mid-loop failure leaves prior chunks committed; the next call resumes
        idempotently from the bucket's current state.

        Returns the number of rows deleted across all chunks (0 = idempotent no-op).
        Scope: long_term_facts ONLY (D-1.2). Short-term Redis and user_profile NOT cleared.

        Raises:
            MemoryForgetError: on asyncpg.PostgresError from any chunk (wraps DB
                error; caller -> 500). Partial deletions from earlier chunks remain
                committed (asyncpg auto-commits per execute).
        """
        BATCH = 1000  # T7 — mirror evict_bucket EVICT-01 chunk size
        total_deleted = 0
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                while True:
                    status = await conn.execute(
                        """DELETE FROM long_term_facts
                           WHERE id IN (
                             SELECT id FROM long_term_facts
                             WHERE user_id=$1 AND tenant_id=$2
                             LIMIT $3
                           )""",
                        user_id, tenant_id, BATCH,
                    )
                    deleted = int(status.split()[1])  # "DELETE N" -> N (Pitfall 2 / SP-5)
                    total_deleted += deleted
                    if deleted == 0:
                        break
            return total_deleted
        except asyncpg.PostgresError as exc:
            logger.error(
                "memory service failure",
                operation="forget_user",
                user_id=user_id,
                tenant_id=tenant_id,
                deleted_before_failure=total_deleted,
                exc_info=exc,
            )
            raise MemoryForgetError("forget failed") from exc

    async def save_query(
        self, user_id: str, tenant_id: str, session_id: str,
        query: str, intent: str, answer_short: str,
    ) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO query_history
                       (user_id, tenant_id, session_id, query, intent, answer_short)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    user_id, tenant_id, session_id, query, intent,
                    answer_short[:500],
                )
        except asyncpg.PostgresError as exc:
            logger.error("memory service failure", operation="save_query", exc_info=exc)

    async def update_feedback(
        self, user_id: str, session_id: str, feedback: int
    ) -> None:
        """更新最近一次查询的反馈（1=正向，-1=负向）。"""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE query_history SET feedback=$1
                       WHERE id = (
                           SELECT id FROM query_history
                           WHERE user_id=$2 AND session_id=$3
                           ORDER BY created_at DESC LIMIT 1
                       )""",
                    feedback, user_id, session_id,
                )
        except asyncpg.PostgresError as exc:
            logger.error("memory service failure", operation="update_feedback", exc_info=exc)

    async def update_profile_from_query(
        self, user_id: str, tenant_id: str, topic: str, feedback: int = 0
    ) -> None:
        """每次查询后更新用户画像的常用话题和统计数据。"""
        profile = await self.get_user_profile(user_id, tenant_id)
        profile.query_count += 1
        profile.last_active = time.time()
        if feedback > 0:
            profile.positive_count += 1
        elif feedback < 0:
            profile.negative_count += 1
        # 更新常用话题（最多保留 10 个）
        if topic and topic not in profile.frequent_topics:
            profile.frequent_topics.insert(0, topic)
            profile.frequent_topics = profile.frequent_topics[:10]
        await self.upsert_user_profile(profile)


# ══════════════════════════════════════════════════════════════════════════════
# 统一记忆服务入口
# ══════════════════════════════════════════════════════════════════════════════
class MemoryService:
    """
    统一入口，对 pipeline 屏蔽底层存储细节。
    短期：Redis（会话内对话历史）
    长期：PostgreSQL（用户画像、重要事实、历史摘要）
    """

    def __init__(self) -> None:
        self._short = ShortTermMemory()
        self._long  = LongTermMemory()

    async def load_context(
        self,
        session_id: str,
        user_id:    str,
        tenant_id:  str,
        query:      str,
    ) -> MemoryContext:
        """加载当前请求所需的全部记忆上下文。

        Phase 24 / T1 (Decision-1) — ``long_term_facts`` is NO LONGER auto-injected
        here. Planner reads long-term facts on opt-in via ``RecallTool``
        (services/agent/tools/recall.py). ``MemoryContext.long_term_facts`` is
        preserved as a typed field but always set to ``[]`` by this method;
        downstream code that referenced ``mem_ctx.long_term_facts`` continues
        to receive a typed empty list (no AttributeError).

        Pre-removal shape (v1.0-v1.5):           Post-removal shape (v1.6 Phase 24):
        ┌──────────────────────────────────┐    ┌──────────────────────────────────┐
        │ asyncio.gather(                  │    │ asyncio.gather(                  │
        │   _short.get_history(session),   │    │   _short.get_history(session),   │
        │   _long.get_relevant_facts(...),─┼──X │   _long.get_user_profile(u, t),  │
        │   _long.get_user_profile(u, t),  │    │   return_exceptions=True,        │
        │   return_exceptions=True,        │    │ )                                │
        │ )                                │    │                                  │
        │   ↓                              │    │   ↓                              │
        │ MemoryContext(                   │    │ MemoryContext(                   │
        │   short_term=[...],              │    │   short_term=[...],              │
        │   long_term_facts=[...],   ──────┼──X │   long_term_facts=[],   (always) │
        │   user_profile=...,              │    │   user_profile=...,              │
        │ )                                │    │ )                                │
        └──────────────────────────────────┘    └──────────────────────────────────┘
                                                 RecallTool (planner opt-in) is now
                                                 the sole reader of long_term_facts.

        See ``tests/integration/test_pipeline_load_context_audit.py`` (Plan 05)
        for the 4-call-site removal regression gate.
        """
        short_term, user_profile = await asyncio.gather(
            self._short.get_history(session_id),
            self._long.get_user_profile(user_id, tenant_id),
            return_exceptions=True,
        )
        return MemoryContext(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            short_term=short_term if isinstance(short_term, list) else [],
            long_term_facts=[],  # T1 (Decision-1) — RecallTool is sole read path
            user_profile=user_profile if isinstance(user_profile, UserProfile) else None,
        )

    async def save_turn(
        self,
        session_id: str,
        user_id:    str,
        tenant_id:  str,
        user_turn:  ConversationTurn,
        ai_turn:    ConversationTurn,
        intent:     str = "",
        feedback:   int = 0,
    ) -> None:
        """保存一轮对话到短期 + 更新长期画像。"""
        await asyncio.gather(
            self._short.append(session_id, user_turn),
            self._short.append(session_id, ai_turn),
            self._long.save_query(
                user_id, tenant_id, session_id,
                user_turn.content, intent, ai_turn.content[:300],
            ),
            self._long.update_profile_from_query(user_id, tenant_id, intent, feedback),
            return_exceptions=True,
        )

    async def save_feedback(
        self, user_id: str, session_id: str, feedback: int
    ) -> None:
        await self._long.update_feedback(user_id, session_id, feedback)

    async def get_relevant_facts(
        self,
        user_id: str,
        tenant_id: str,
        query: str,
        limit: int = 5,
    ) -> list[str]:
        """Public passthrough — semantic recall over long_term_facts.

        Added in Phase 24 / T2 (Decision-2). Plan 03 RecallTool calls this
        rather than reaching into the private ``_long`` attribute. Mirrors
        ``LongTermMemory.get_relevant_facts`` signature exactly.
        """
        return await self._long.get_relevant_facts(
            user_id, tenant_id, query, limit=limit,
        )

    async def get_formatted_history(
        self, session_id: str, max_turns: int = 6
    ) -> list[dict[str, str]]:
        return await self._short.get_formatted_history(session_id, max_turns)

    async def close(self) -> None:
        """Close inner pool resources. Idempotent.

        Plan 26-05 / TD-03. Called from main.py lifespan shutdown.
        Cascades to LongTermMemory (asyncpg pool); ShortTermMemory (Redis)
        owns its own client lifecycle and is not closed here.
        """
        if self._long is not None:
            await self._long.close()


_memory_service: MemoryService | None = None

def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
