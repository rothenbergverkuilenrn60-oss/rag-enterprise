# =============================================================================
# services/knowledge/version_service.py
# 文档版本控制：每次入库自动递增版本号，支持版本历史查询和版本回滚
#
# 存储方案：Redis Sorted Set
#   Key:   doc:versions:{doc_id}
#   Score: 版本号（整数）
#   Value: JSON 序列化的 DocumentVersion
#
# 优势：
#   - O(log N) 插入/查询，无需额外数据库
#   - 与现有 Redis 基础设施复用
#   - TTL 可控（按租户保留策略设置）
# =============================================================================
from __future__ import annotations

import json
import time

import redis.asyncio
from loguru import logger

from utils.models import DocumentVersion, VersionListResponse


_VERSION_KEY_PREFIX = "doc:versions:"
_MAX_VERSIONS = 50        # 每个文档最多保留50个版本


class VersionService:
    """
    文档版本管理服务。

    调用时机：
      - IngestionPipeline.run() 成功后调用 record_version()
      - GET /docs/{doc_id}/versions 调用 get_versions()
      - POST /docs/{doc_id}/rollback 调用 rollback()
    """

    async def _get_redis(self):
        from utils.cache import get_redis
        return await get_redis()

    def _key(self, doc_id: str) -> str:
        return f"{_VERSION_KEY_PREFIX}{doc_id}"

    async def record_version(
        self,
        doc_id: str,
        checksum: str,
        file_path: str,
        chunk_count: int,
        tenant_id: str = "",
        user_id: str = "",
        note: str = "",
    ) -> DocumentVersion:
        """
        记录一个新版本。每次成功入库后调用。
        若是首次入库则 version=1，否则在最新版本基础上 +1。
        """
        try:
            r = await self._get_redis()
            key = self._key(doc_id)

            # 查询当前最大版本号
            latest = await r.zrevrange(key, 0, 0, withscores=True)
            next_version = int(latest[0][1]) + 1 if latest else 1

            # 将旧版本标记为非当前版本
            if latest:
                old_data = json.loads(latest[0][0])
                old_data["is_current"] = False
                await r.zadd(key, {json.dumps(old_data, ensure_ascii=False): old_data["version"]})

            version = DocumentVersion(
                doc_id=doc_id,
                version=next_version,
                checksum=checksum,
                file_path=file_path,
                chunk_count=chunk_count,
                ingested_at=time.time(),
                note=note,
                tenant_id=tenant_id,
                user_id=user_id,
                is_current=True,
            )

            await r.zadd(key, {version.model_dump_json(): next_version})

            # 裁剪：保留最近 MAX_VERSIONS 个版本
            count = await r.zcard(key)
            if count > _MAX_VERSIONS:
                await r.zremrangebyrank(key, 0, count - _MAX_VERSIONS - 1)

            # TTL：180 天后自动清理
            await r.expire(key, 180 * 86400)

            logger.info(
                f"[Version] doc_id={doc_id} version={next_version} "
                f"chunks={chunk_count} tenant={tenant_id}"
            )
            return version

        except redis.asyncio.RedisError as exc:
            logger.error("version service failure", operation="record_version", doc_id=doc_id, exc_info=exc)
            # 版本记录失败不影响主流程
            return DocumentVersion(
                doc_id=doc_id, version=1, checksum=checksum,
                file_path=file_path, chunk_count=chunk_count,
            )

    async def get_versions(self, doc_id: str) -> VersionListResponse:
        """获取文档所有历史版本（从新到旧）。"""
        try:
            r = await self._get_redis()
            key = self._key(doc_id)
            # ZREVRANGE 从高分（新版本）到低分（旧版本）
            raw = await r.zrevrange(key, 0, -1, withscores=True)
            versions = []
            for data, score in raw:
                try:
                    v = DocumentVersion.model_validate_json(data)
                    versions.append(v)
                except (ValueError, KeyError) as exc:
                    logger.error("version service failure", operation="parse_version_entry", exc_info=exc)
            return VersionListResponse(doc_id=doc_id, versions=versions, total=len(versions))
        except redis.asyncio.RedisError as exc:
            logger.error("version service failure", operation="get_versions", doc_id=doc_id, exc_info=exc)
            return VersionListResponse(doc_id=doc_id)

    async def get_version(self, doc_id: str, version: int) -> DocumentVersion | None:
        """获取指定版本。"""
        try:
            r = await self._get_redis()
            key = self._key(doc_id)
            raw = await r.zrangebyscore(key, version, version)
            if raw:
                return DocumentVersion.model_validate_json(raw[0])
        except redis.asyncio.RedisError as exc:
            logger.error("version service failure", operation="get_version", doc_id=doc_id, exc_info=exc)
        return None

    async def get_current(self, doc_id: str) -> DocumentVersion | None:
        """获取当前最新版本。"""
        result = await self.get_versions(doc_id)
        if result.versions:
            return result.versions[0]
        return None

    async def rollback(
        self,
        doc_id: str,
        target_version: int,
        user_id: str = "",
    ) -> tuple[bool, str]:
        """
        回滚到指定版本：重新摄取该版本对应的文件。
        返回 (success, message)。
        """
        target = await self.get_version(doc_id, target_version)
        if not target:
            return False, f"Version {target_version} not found for doc_id={doc_id}"
        if not target.file_path:
            return False, f"Version {target_version} has no file_path, cannot rollback"

        try:
            from services.pipeline import get_ingest_pipeline
            from utils.models import IngestionRequest
            pipeline = get_ingest_pipeline()
            req = IngestionRequest(
                file_path=target.file_path,
                doc_id=doc_id,
                force=True,  # 跳过去重，强制重新入库
                metadata={
                    "user_id": user_id,
                    "rollback_from_version": target_version,
                    "note": f"Rollback to v{target_version}",
                },
            )
            result = await pipeline.run(req)
            if result.success:
                await self.record_version(
                    doc_id=doc_id,
                    checksum=target.checksum,
                    file_path=target.file_path,
                    chunk_count=result.total_chunks,
                    user_id=user_id,
                    note=f"Rollback to v{target_version}",
                )
                return True, f"Rolled back to version {target_version} successfully"
            return False, f"Re-ingestion failed: {result.error}"
        except (OSError, ValueError, RuntimeError) as exc:
            logger.error("version service failure", operation="rollback", doc_id=doc_id, exc_info=exc)
            return False, "Rollback failed"

    async def delete_versions(self, doc_id: str) -> int:
        """删除文档所有版本记录（文档删除时调用）。"""
        try:
            r = await self._get_redis()
            return await r.delete(self._key(doc_id))
        except redis.asyncio.RedisError as exc:
            logger.error("version service failure", operation="delete_versions", doc_id=doc_id, exc_info=exc)
            return 0


_version_service: VersionService | None = None


def get_version_service() -> VersionService:
    global _version_service
    if _version_service is None:
        _version_service = VersionService()
    return _version_service
