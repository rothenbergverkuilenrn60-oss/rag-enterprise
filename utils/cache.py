# =============================================================================
# utils/cache.py
# Redis 异步缓存工具
# 提供：get_redis 连接池 / cache_get / cache_set / cache_invalidate
# 缓存 key 格式：rag:{namespace}:{payload_hash}
# =============================================================================
from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

# Redis 客户端单例（进程级复用连接池）
_redis_client = None


async def get_redis():
    """
    获取 Redis 异步客户端单例。
    第一次调用时根据 settings.redis_url 创建连接，之后复用。
    使用 redis.asyncio 原生异步客户端，不阻塞事件循环。
    """
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import from_url
        from config.settings import settings
        _redis_client = await from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,   # 自动把 bytes 解码为 str
            max_connections=20,      # 连接池最大连接数
        )
        logger.info(f"Redis client initialized: {settings.redis_url}")
    return _redis_client


def _make_cache_key(namespace: str, payload: dict | str) -> str:
    """
    生成缓存 key。
    格式：rag:{namespace}:{payload 的 MD5 前 16 位}
    例：rag:query:a1b2c3d4e5f60789

    用 MD5 哈希是因为：
    - payload 可能很长（含 filters/top_k 等参数）
    - Redis key 有长度限制（建议不超过 512 字节）
    - MD5 已足够防碰撞（缓存场景对安全性无要求）
    """
    if isinstance(payload, dict):
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    else:
        payload_str = str(payload)
    digest = hashlib.md5(payload_str.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"rag:{namespace}:{digest}"


async def cache_get(namespace: str, payload: dict | str) -> Any | None:
    """
    从 Redis 读取缓存。
    返回反序列化后的 Python 对象，未命中或缓存关闭时返回 None。
    """
    from config.settings import settings
    if not settings.cache_enabled:
        return None

    try:
        r = await get_redis()
        key = _make_cache_key(namespace, payload)
        raw = await r.get(key)
        if raw is None:
            logger.debug(f"[Cache] MISS key={key}")
            return None
        logger.debug(f"[Cache] HIT key={key}")
        return json.loads(raw)
    except Exception as exc:
        # 缓存读取失败不应影响主流程，降级为缓存未命中
        logger.warning(f"[Cache] GET failed (non-fatal): {exc}")
        return None


async def cache_set(namespace: str, payload: dict | str, value: Any) -> bool:
    """
    写入 Redis 缓存。
    value 会被 JSON 序列化后存储；TTL 由 settings.cache_ttl_sec 控制。
    Pydantic 模型通过 model_dump(mode='json') 序列化。
    返回 True 表示写入成功，False 表示写入失败（不抛异常）。
    """
    from config.settings import settings
    if not settings.cache_enabled:
        return False

    try:
        r = await get_redis()
        key = _make_cache_key(namespace, payload)

        # Pydantic V2 模型需要先转字典再序列化
        from pydantic import BaseModel
        if isinstance(value, BaseModel):
            serializable = value.model_dump(mode="json")
        else:
            serializable = value

        raw = json.dumps(serializable, ensure_ascii=False)
        await r.setex(key, settings.cache_ttl_sec, raw)
        logger.debug(f"[Cache] SET key={key} ttl={settings.cache_ttl_sec}s")
        return True
    except Exception as exc:
        logger.warning(f"[Cache] SET failed (non-fatal): {exc}")
        return False


async def cache_invalidate(pattern: str) -> int:
    """
    批量删除匹配 pattern 的缓存 key（支持 Redis glob 通配符，如 'rag:*'）。
    返回删除的 key 数量。

    使用 SCAN 代替 KEYS：KEYS 在大量 key 时会独占 Redis 线程，阻塞所有其他命令；
    SCAN 迭代不阻塞，每次只处理少量 key，对生产环境更安全。
    """
    try:
        r = await get_redis()
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=200)
            if keys:
                deleted += await r.delete(*keys)
            if cursor == 0:
                break
        logger.info(f"[Cache] INVALIDATE pattern={pattern} deleted={deleted}")
        return deleted
    except Exception as exc:
        logger.warning(f"[Cache] INVALIDATE failed: {exc}")
        return 0
