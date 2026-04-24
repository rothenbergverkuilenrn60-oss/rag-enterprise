# =============================================================================
# services/knowledge/summary_indexer.py
# 摘要索引：三层索引体系（文档级 / 章节级 / chunk组级）
# 查询时先走摘要层快速定位相关文档范围，再下钻原文 chunk，降低无关 chunk 干扰
# =============================================================================
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import asyncpg
import openai
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from config.settings import settings


@dataclass
class SummaryEntry:
    """一条摘要索引记录。"""
    summary_id: str
    doc_id: str
    level: str                          # "document" | "section" | "chunk_group"
    summary_text: str
    chunk_ids: list[str] = field(default_factory=list)   # 该摘要覆盖的原始 chunk_id 列表
    section: str = ""
    title: str = ""
    embedding: list[float] | None = None


class SummaryIndexer:
    """
    三层摘要索引构建器。

    Level 1 — 文档级摘要：整个文档的 200 字概述，快速过滤不相关文档
    Level 2 — 章节级摘要：每个顶层章节的 100 字概述
    Level 3 — chunk 组摘要：每 5 个相邻 chunk 的 80 字概述（密集文档场景）

    检索策略（summary_search_enabled=True 时）：
      1. 先在摘要 collection 做向量搜索，命中哪些摘要
      2. 取摘要对应的 chunk_ids 列表
      3. 与常规混合检索结果 RRF 融合，提升召回准确率
    """

    SUMMARY_COLLECTION_SUFFIX = "_summary"
    CHUNK_GROUP_SIZE = 5

    def __init__(self) -> None:
        self._collection: str = settings.qdrant_collection + self.SUMMARY_COLLECTION_SUFFIX

    async def build_summaries(
        self,
        chunks: list,       # list[DocumentChunk]
        doc_id: str,
        title: str,
        llm_client,
        embedder,
        vector_store,
    ) -> list[SummaryEntry]:
        """
        为一批 chunk 构建三层摘要并写入独立 summary collection。
        返回生成的 SummaryEntry 列表。
        """
        entries: list[SummaryEntry] = []

        # ── Level 1: 文档级摘要 ─────────────────────────────────────────────
        doc_summary = await self._summarize_document(chunks, doc_id, title, llm_client)
        if doc_summary:
            entries.append(doc_summary)

        # ── Level 2: 章节级摘要 ─────────────────────────────────────────────
        section_summaries = await self._summarize_sections(chunks, doc_id, llm_client)
        entries.extend(section_summaries)

        # ── Level 3: chunk 组摘要 ────────────────────────────────────────────
        group_summaries = await self._summarize_chunk_groups(chunks, doc_id, llm_client)
        entries.extend(group_summaries)

        # ── 向量化并写入 summary collection ─────────────────────────────────
        await self._upsert_summaries(entries, embedder, vector_store)

        logger.info(
            f"[SummaryIndexer] doc_id={doc_id} "
            f"entries={len(entries)} "
            f"(doc=1 section={len(section_summaries)} group={len(group_summaries)})"
        )
        return entries

    async def search_summaries(
        self,
        query: str,
        embedder,
        vector_store,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[str]:
        """
        在摘要 collection 中检索，返回命中摘要覆盖的 chunk_id 列表。
        用于在常规混合检索之前快速缩小候选范围。
        """
        try:
            query_vec = await embedder.embed_one(query)
            results = await vector_store.search(
                query_vector=query_vec,
                top_k=top_k,
                filters=filters,
            )
            # 从 tags 中解析 chunk_ids（存储时用 "chunk_ids:id1,id2,..." 格式）
            all_chunk_ids: list[str] = []
            for r in results:
                tags = r.metadata.get("tags", [])
                for tag in tags:
                    if isinstance(tag, str) and tag.startswith("chunk_ids:"):
                        ids = tag[len("chunk_ids:"):].split(",")
                        all_chunk_ids.extend(ids)
            # 去重保序
            seen: set[str] = set()
            unique: list[str] = []
            for cid in all_chunk_ids:
                if cid and cid not in seen:
                    seen.add(cid)
                    unique.append(cid)
            return unique
        except asyncpg.PostgresError as exc:
            logger.error("summary indexer failure", stage="search", exc_info=exc)
            return []

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(2), wait=wait_random_exponential(multiplier=1, max=4))
    async def _call_llm(self, prompt: str, llm_client) -> str:
        return await llm_client.chat(
            system=(
                "你是企业文档摘要专家。"
                "生成简洁的中文摘要，覆盖核心规定、关键数字和主要结论。"
                "只输出摘要文本，不加前缀、标签或解释。"
            ),
            user=prompt,
            temperature=0.1,
            task_type="summarize",   # → Haiku，批量摘要生成成本极低
        )

    async def _summarize_document(
        self,
        chunks: list,
        doc_id: str,
        title: str,
        llm_client,
    ) -> SummaryEntry | None:
        if not chunks:
            return None
        sample_text = "\n".join(c.content for c in chunks[:10])[:2000]
        try:
            summary_text = await self._call_llm(
                f"请用200字以内概括以下文档的主要内容。文档标题：{title}\n\n{sample_text}",
                llm_client,
            )
            return SummaryEntry(
                summary_id=f"{doc_id}_doc",
                doc_id=doc_id,
                level="document",
                summary_text=summary_text,
                chunk_ids=[c.chunk_id for c in chunks],
                title=title,
            )
        except openai.APIError as exc:
            logger.error("summary indexer failure", stage="doc_summary", doc_id=doc_id, exc_info=exc)
            return None

    async def _summarize_sections(
        self,
        chunks: list,
        doc_id: str,
        llm_client,
    ) -> list[SummaryEntry]:
        """按顶层章节分组，每组生成一条摘要。"""
        from collections import defaultdict
        section_map: dict[str, list] = defaultdict(list)
        for c in chunks:
            section = c.metadata.section or "default"
            section_map[section].append(c)

        if len(section_map) <= 1:
            return []

        section_items = list(section_map.items())
        tasks = []
        for section, schunks in section_items:
            sample = "\n".join(c.content for c in schunks[:5])[:1000]
            tasks.append(self._call_llm(
                f"请用100字以内概括以下章节内容。章节标题：{section}\n\n{sample}",
                llm_client,
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        entries: list[SummaryEntry] = []
        for (section, schunks), result in zip(section_items, results):
            if isinstance(result, Exception):
                continue
            entries.append(SummaryEntry(
                summary_id=f"{doc_id}_sec_{abs(hash(section)) & 0xFFFF:04x}",
                doc_id=doc_id,
                level="section",
                summary_text=str(result),
                chunk_ids=[c.chunk_id for c in schunks],
                section=section,
            ))
        return entries

    async def _summarize_chunk_groups(
        self,
        chunks: list,
        doc_id: str,
        llm_client,
    ) -> list[SummaryEntry]:
        """每 CHUNK_GROUP_SIZE 个 chunk 生成一条 group 摘要。"""
        child_chunks = [c for c in chunks if c.metadata.chunk_level != "parent"]
        if len(child_chunks) <= self.CHUNK_GROUP_SIZE:
            return []

        groups = [
            child_chunks[i: i + self.CHUNK_GROUP_SIZE]
            for i in range(0, len(child_chunks), self.CHUNK_GROUP_SIZE)
        ]
        tasks = []
        for group in groups:
            sample = "\n".join(c.content for c in group)[:800]
            tasks.append(self._call_llm(
                f"请用80字以内概括以下段落的核心信息：\n\n{sample}",
                llm_client,
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        entries: list[SummaryEntry] = []
        for i, (group, result) in enumerate(zip(groups, results)):
            if isinstance(result, Exception):
                continue
            entries.append(SummaryEntry(
                summary_id=f"{doc_id}_grp_{i:04d}",
                doc_id=doc_id,
                level="chunk_group",
                summary_text=str(result),
                chunk_ids=[c.chunk_id for c in group],
            ))
        return entries

    async def _upsert_summaries(
        self,
        entries: list[SummaryEntry],
        embedder,
        vector_store,
    ) -> None:
        """将摘要条目向量化并写入 summary collection（复用主 collection 的 upsert 接口）。"""
        if not entries:
            return
        try:
            texts = [e.summary_text for e in entries]
            embeddings = await embedder.embed_batch(texts)
            for entry, emb in zip(entries, embeddings):
                entry.embedding = emb

            # 确保 summary collection 存在
            await vector_store.create_collection()

            # 将摘要封装为 DocumentChunk 写入（复用 upsert 接口）
            from utils.models import DocumentChunk, ChunkMetadata
            pseudo_chunks: list[DocumentChunk] = []
            for entry in entries:
                # chunk_ids 列表编码进 tags，检索结果解析时展开
                chunk_ids_tag = "chunk_ids:" + ",".join(entry.chunk_ids[:50])  # 最多50个ID
                meta = ChunkMetadata(
                    doc_id=entry.doc_id,
                    title=entry.title,
                    section=entry.section,
                    chunk_level=entry.level,
                    tags=["summary", entry.level, chunk_ids_tag],
                )
                pc = DocumentChunk(
                    chunk_id=entry.summary_id,
                    doc_id=entry.doc_id,
                    content=entry.summary_text,
                    content_with_header=entry.summary_text,
                    metadata=meta,
                    token_count=len(entry.summary_text) // 4,
                    embedding=entry.embedding,
                )
                pseudo_chunks.append(pc)

            await vector_store.upsert(pseudo_chunks)
            logger.debug(
                f"[SummaryIndexer] Upserted {len(pseudo_chunks)} summaries "
                f"to {self._collection}"
            )
        except asyncpg.PostgresError as exc:
            logger.error("summary indexer failure", stage="upsert", exc_info=exc)


_summary_indexer: SummaryIndexer | None = None


def get_summary_indexer() -> SummaryIndexer:
    global _summary_indexer
    if _summary_indexer is None:
        _summary_indexer = SummaryIndexer()
    return _summary_indexer
