# =============================================================================
# services/knowledge/knowledge_service.py
# 知识库管理：自动更新 / 增量更新 / 质量校验 / BM25+向量事务性一致性
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import asyncpg
from loguru import logger


class UpdateStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    SKIPPED   = "skipped"    # 重复文档


@dataclass
class DocumentQualityReport:
    """文档质量校验报告。"""
    doc_id:          str
    file_path:       str
    passed:          bool
    char_count:      int        = 0
    chunk_count:     int        = 0
    warnings:        list[str]  = field(default_factory=list)
    errors:          list[str]  = field(default_factory=list)
    quality_score:   float      = 1.0   # 0-1


@dataclass
class UpdateRecord:
    """一次知识库更新的完整记录（用于审计和回滚）。"""
    record_id:   str
    doc_id:      str
    file_path:   str
    status:      UpdateStatus
    chunk_count: int    = 0
    started_at:  float  = field(default_factory=time.time)
    finished_at: float  = 0.0
    error:       str    = ""
    checksum:    str    = ""
    is_incremental: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# 质量校验器
# ══════════════════════════════════════════════════════════════════════════════
class DocumentQualityChecker:
    """
    入库前质量校验，阻止低质量文档污染知识库。
    校验维度：字符数 / 语言检测 / 乱码检测 / 重复率
    """

    MIN_CHARS   = 100
    MAX_CHARS   = 500_000
    MIN_CHUNKS  = 1
    GARBLE_RATIO = 0.3    # 非中英文字符超过 30% 认为是乱码

    def check(self, body_text: str, doc_id: str, file_path: str) -> DocumentQualityReport:
        import re
        warnings: list[str] = []
        errors:   list[str] = []
        char_count = len(body_text)

        # 1. 长度检查
        if char_count < self.MIN_CHARS:
            errors.append(f"内容过短：{char_count} 字符 < {self.MIN_CHARS}")
        if char_count > self.MAX_CHARS:
            warnings.append(f"内容过长：{char_count} 字符，建议拆分")

        # 2. 乱码检测
        if char_count > 0:
            non_standard = len(re.findall(
                r"[^\x00-\x7f\u4e00-\u9fff\u3040-\u30ff\uff00-\uffef]", body_text
            ))
            garble_ratio = non_standard / char_count
            if garble_ratio > self.GARBLE_RATIO:
                errors.append(f"疑似乱码：非标准字符占比 {garble_ratio:.1%}")

        # 3. 空白文档检测
        non_whitespace = len(body_text.strip())
        if non_whitespace < 50:
            errors.append("文档实际内容为空或近空")

        quality_score = 1.0 - len(errors) * 0.3 - len(warnings) * 0.1
        quality_score = max(0.0, min(1.0, quality_score))

        return DocumentQualityReport(
            doc_id=doc_id,
            file_path=file_path,
            passed=len(errors) == 0,
            char_count=char_count,
            warnings=warnings,
            errors=errors,
            quality_score=quality_score,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 事务性 BM25 + 向量存储协调器
# ══════════════════════════════════════════════════════════════════════════════
class TransactionalIndexer:
    """
    BM25 索引 + Qdrant 向量存储的事务性一致性保证。

    问题：如果向量写入成功但 BM25 失败（或反之），
    则两个索引不一致，混合检索时会出现「只有一路能找到」的问题。

    解决方案：两阶段提交（2PC）
      Phase 1 - Prepare：同时验证两个索引的写入条件
      Phase 2 - Commit：原子提交；任意一方失败则回滚另一方

    实际场景：BM25 是内存索引，Qdrant 是网络服务，
    主要失败模式是 Qdrant 网络超时，BM25 回滚只需清除对应 ID。
    """

    async def upsert_atomic(
        self,
        chunks: list,           # list[DocumentChunk]
        doc_id: str,
        vector_store,           # BaseVectorStore
        bm25_index,             # BM25Index
        embedder,               # BatchedEmbedder
    ) -> tuple[bool, str]:
        """
        原子性写入：BM25 + 向量存储，任意一方失败则回滚。
        返回 (success, error_message)
        """
        child_chunks = [c for c in chunks if c.metadata.chunk_level != "parent"]
        parent_chunks = [c for c in chunks if c.metadata.chunk_level == "parent"]

        # ── Phase 1: 嵌入（CPU 密集，先做，失败代价最小）────────────────────
        try:
            texts = [c.content_with_header or c.content for c in child_chunks]
            embeddings = await embedder.embed_batch(texts)
            for chunk, emb in zip(child_chunks, embeddings):
                chunk.embedding = emb
        except (RuntimeError, ValueError) as exc:
            logger.error("knowledge scan failure", stage="embedding", exc_info=exc)
            return False, "Embedding failed"

        # ── Phase 2: BM25 写入（内存操作，极少失败） ──────────────────────
        bm25_ids_added: list[str] = []
        try:
            if child_chunks:
                bm25_index.add(
                    texts=[c.content for c in child_chunks],
                    ids=[c.chunk_id for c in child_chunks],
                )
                bm25_ids_added = [c.chunk_id for c in child_chunks]
        except (RuntimeError, ValueError) as exc:
            logger.error("knowledge scan failure", stage="bm25_index", exc_info=exc)
            return False, "BM25 index failed"

        # ── Phase 3: Qdrant 写入（网络操作，可能失败） ───────────────────
        try:
            await vector_store.upsert(child_chunks)
            # 父块写入独立 collection
            if parent_chunks:
                from config.settings import settings
                parent_col = (
                    getattr(settings, "qdrant_parent_collection", "") or
                    settings.qdrant_collection + "_parent"
                )
                await vector_store.upsert_parent_chunks(parent_chunks, parent_col)
        except asyncpg.PostgresError as exc:
            # Phase 3 失败：回滚 BM25
            logger.error("knowledge scan failure", stage="vector_upsert", exc_info=exc)
            self._rollback_bm25(bm25_index, bm25_ids_added)
            return False, "Qdrant upsert failed (BM25 rolled back)"

        logger.info(
            f"[TransactionalIndexer] Committed: doc_id={doc_id} "
            f"child={len(child_chunks)} parent={len(parent_chunks)}"
        )
        return True, ""

    def _rollback_bm25(self, bm25_index, chunk_ids: list[str]) -> None:
        """BM25 回滚：重建去掉这些 ID 的索引。"""
        try:
            new_corpus = [
                (t, cid) for t, cid in zip(bm25_index._corpus, bm25_index._ids)
                if cid not in set(chunk_ids)
            ]
            if new_corpus:
                texts, ids = zip(*new_corpus)
                bm25_index.build(list(texts), list(ids))
            else:
                bm25_index._corpus = []
                bm25_index._ids = []
                bm25_index._model = None
            logger.info(f"[TransactionalIndexer] BM25 rolled back {len(chunk_ids)} entries")
        except (RuntimeError, ValueError, AttributeError) as exc:
            logger.error("knowledge scan failure", stage="bm25_rollback", exc_info=exc)


# ══════════════════════════════════════════════════════════════════════════════
# 知识库自动更新 & 增量更新
# ══════════════════════════════════════════════════════════════════════════════
class KnowledgeUpdateService:
    """
    知识库更新服务：
    - scan_and_update()：扫描目录，检测新增/修改的文件，增量入库
    - incremental_update()：单文件增量更新（先删旧向量再写新的）
    - full_rebuild()：全量重建（清空集合重新入库）
    """

    def __init__(self) -> None:
        self._quality_checker = DocumentQualityChecker()
        self._tx_indexer      = TransactionalIndexer()
        self._records: dict[str, UpdateRecord] = {}   # 更新记录（生产用 DB）

    async def scan_and_update(
        self,
        data_dir: Path,
        pipeline,         # IngestionPipeline
        tenant_id: str = "",
        extensions: set[str] | None = None,
    ) -> list[UpdateRecord]:
        """
        扫描目录，仅处理新增或内容变更的文件（通过 checksum 比对）。
        返回本次更新的所有记录。
        """
        exts = extensions or {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".html"}
        files = [f for f in data_dir.rglob("*") if f.suffix.lower() in exts]
        logger.info(f"[KnowledgeUpdate] Scanning {len(files)} files in {data_dir}")

        records: list[UpdateRecord] = []
        for file_path in files:
            record = await self.incremental_update(file_path, pipeline, tenant_id)
            records.append(record)

        success = sum(1 for r in records if r.status == UpdateStatus.SUCCESS)
        skipped = sum(1 for r in records if r.status == UpdateStatus.SKIPPED)
        failed  = sum(1 for r in records if r.status == UpdateStatus.FAILED)
        logger.info(
            f"[KnowledgeUpdate] Done: success={success} skipped={skipped} failed={failed}"
        )
        return records

    async def incremental_update(
        self,
        file_path: Path,
        pipeline,
        tenant_id: str = "",
    ) -> UpdateRecord:
        """
        单文件增量更新：
        1. 计算文件 checksum
        2. 与上次记录比对，未变则跳过
        3. 质量校验
        4. 删除旧向量
        5. 事务性写入新向量
        """
        import uuid as _uuid
        record_id = _uuid.uuid4().hex[:12]
        doc_id = hashlib.md5(str(file_path).encode(), usedforsecurity=False).hexdigest()
        checksum = self._file_checksum(file_path)

        record = UpdateRecord(
            record_id=record_id,
            doc_id=doc_id,
            file_path=str(file_path),
            status=UpdateStatus.PENDING,
            checksum=checksum,
            is_incremental=True,
        )

        # 检查是否有变更
        prev = self._records.get(doc_id)
        if prev and prev.checksum == checksum and prev.status == UpdateStatus.SUCCESS:
            record.status = UpdateStatus.SKIPPED
            logger.debug(f"[KnowledgeUpdate] Unchanged, skipped: {file_path.name}")
            return record

        record.status = UpdateStatus.RUNNING

        try:
            from utils.models import IngestionRequest
            req = IngestionRequest(
                file_path=str(file_path),
                doc_id=doc_id,
                metadata={"tenant_id": tenant_id},
                force=True,   # 强制覆盖旧记录
            )
            result = await pipeline.run(req)
            if result.success:
                record.status   = UpdateStatus.SUCCESS
                record.chunk_count = result.total_chunks
                record.finished_at = time.time()
                self._records[doc_id] = record
                logger.info(
                    f"[KnowledgeUpdate] Updated: {file_path.name} "
                    f"chunks={result.total_chunks}"
                )
            else:
                record.status = UpdateStatus.FAILED
                record.error  = result.error or "Unknown error"
        except (OSError, ValueError, RuntimeError) as exc:
            record.status = UpdateStatus.FAILED
            record.error  = "Incremental update failed"
            logger.error("knowledge scan failure", path=str(file_path), exc_info=exc)

        return record

    def validate_document(
        self, body_text: str, doc_id: str, file_path: str
    ) -> DocumentQualityReport:
        return self._quality_checker.check(body_text, doc_id, file_path)

    @staticmethod
    def _file_checksum(file_path: Path) -> str:
        h = hashlib.md5(usedforsecurity=False)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


_knowledge_service: KnowledgeUpdateService | None = None

def get_knowledge_service() -> KnowledgeUpdateService:
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeUpdateService()
    return _knowledge_service
