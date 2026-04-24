# =============================================================================
# services/memory/memory_service.py
# 记忆服务：短期记忆（Redis）+ 长期记忆（PostgreSQL）+ 用户画像
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

import asyncpg
import redis.asyncio
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential


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
        if self._client is None:
            from redis.asyncio import from_url
            from config.settings import settings
            self._client = await from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
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
            import asyncpg
            from config.settings import settings
            dsn = settings.pg_dsn.replace("postgresql+asyncpg://", "postgresql://")
            self._pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
            await self._create_tables()
        return self._pool

    async def _create_tables(self) -> None:
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
        """检索用户的长期记忆中与当前查询相关的事实。"""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT fact FROM long_term_facts
                       WHERE user_id=$1 AND tenant_id=$2
                       ORDER BY importance DESC, created_at DESC
                       LIMIT $3""",
                    user_id, tenant_id, limit,
                )
            return [r["fact"] for r in rows]
        except asyncpg.PostgresError as exc:
            logger.error("memory service failure", operation="get_facts", exc_info=exc)
            return []

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
        """加载当前请求所需的全部记忆上下文。"""
        short_term, long_term_facts, user_profile = await asyncio.gather(
            self._short.get_history(session_id),
            self._long.get_relevant_facts(user_id, tenant_id, query),
            self._long.get_user_profile(user_id, tenant_id),
            return_exceptions=True,
        )
        return MemoryContext(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            short_term=short_term if isinstance(short_term, list) else [],
            long_term_facts=long_term_facts if isinstance(long_term_facts, list) else [],
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

    async def get_formatted_history(
        self, session_id: str, max_turns: int = 6
    ) -> list[dict[str, str]]:
        return await self._short.get_formatted_history(session_id, max_turns)


_memory_service: MemoryService | None = None

def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
