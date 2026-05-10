# =============================================================================
# services/pipeline.py
# 企业级 RAG 2.0 — 全链路编排器
#
# 摄取流水线（Ingestion）:
#   预处理 → 提取 → 质量校验 → 分块（四层叠加）→ 事务性向量化存储 → 事件发布
#
# 查询流水线（Query）:
#   多租户鉴权 → NLU（意图/实体/上下文感知）→ 规则引擎前置 →
#   记忆加载 → 四路混合检索 → RRF融合 → Cross-Encoder重排 →
#   父块回溯 → 上下文注入 → 生成 → 规则引擎后置 →
#   记忆保存 → 反馈准备 → 事件发布
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator

import anthropic                                          # noqa: F401 — referenced in narrow except in AgentQueryPipeline.run
import httpx                                              # noqa: F401 — referenced in narrow except in AgentQueryPipeline.run
import openai                                             # noqa: F401 — referenced in narrow except in AgentQueryPipeline.run
from loguru import logger

from config.settings import settings
from services.agent import get_executor, get_planner
from services.agent.tools import get_tool_registry
from services.agent.tools.retrieve import retrieve_impl as _shared_execute_tool_call
from services.audit.audit_service import AuditAction, AuditEvent, AuditResult, get_audit_service
from services.doc_processor.chunker import get_doc_processor
from services.events.event_bus import get_event_bus
from services.extractor.extractor import get_extractor
from services.generator.generator import get_generator
from services.generator.llm_client import get_llm_client
from services.knowledge.knowledge_service import get_knowledge_service
from services.knowledge.summary_indexer import get_summary_indexer
from services.memory.memory_service import (
    ConversationTurn,
    get_memory_service,
)
from services.nlu.filter_extractor import get_filter_extractor

# Core services
from services.nlu.nlu_service import QueryIntent, get_nlu_service

# Stage services
from services.preprocessor.cleaner import get_preprocessor

# Enterprise feature services
from services.preprocessor.pii_detector import get_pii_detector
from services.retriever.retriever import get_retriever
from services.rules.rules_engine import RuleAction, get_rules_engine
from services.tenant.tenant_service import get_tenant_service
from services.vectorizer.indexer import get_vectorizer
from utils.cache import cache_get, cache_set
from utils.logger import log_latency
from utils.metrics import (
    cache_hit_total,
    faithfulness_histogram,
    ingest_chunks_histogram,
    ingest_total,
    pii_detected_total,
    query_latency_seconds,
    query_total,
    retrieval_chunks_histogram,
    rule_trigger_total,
)
from utils.models import (
    AgentEvent,
    DocType,
    ExecutorParallelEvent,  # noqa: F401 — re-exported by event class hierarchy; consumed via SSE
    GenerationRequest,
    GenerationResponse,
    IngestionRequest,
    IngestionResponse,
    PlannerPlanEvent,
    RawDocument,
    RetrievedChunk,
    SynthesizerFinalEvent,
    ToolPlan,
    ToolResult,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
    VerifierVerdict,   # Phase 21 / Plan 21-02 — kwarg type for _synthesize (D-04)
)
from utils.observability import start_span


def _infer_doc_type(path: Path) -> DocType:
    m = {
        ".pdf": DocType.PDF, ".docx": DocType.DOCX, ".doc": DocType.DOCX,
        ".xlsx": DocType.XLSX, ".xls": DocType.XLSX, ".csv": DocType.CSV,
        ".html": DocType.HTML, ".htm": DocType.HTML, ".json": DocType.JSON,
        ".txt": DocType.TXT, ".md": DocType.MD,
        ".jpg": DocType.IMAGE, ".jpeg": DocType.IMAGE,
        ".png": DocType.IMAGE, ".webp": DocType.IMAGE,
    }
    return m.get(path.suffix.lower(), DocType.UNKNOWN)


class IngestionPipeline:
    def __init__(self) -> None:
        self._preprocessor   = get_preprocessor()
        self._extractor      = get_extractor()
        self._doc_processor  = get_doc_processor()
        self._vectorizer     = get_vectorizer()
        self._knowledge      = get_knowledge_service()
        self._event_bus      = get_event_bus()
        self._pii_detector   = get_pii_detector()
        self._audit          = get_audit_service()
        self._summary_indexer = get_summary_indexer()
        self._ingest_llm = (
            get_llm_client()
            if (
                getattr(settings, "contextual_retrieval_enabled", False)
                or getattr(settings, "summary_index_enabled", False)
            )
            else None
        )

    @log_latency
    async def run(self, req: IngestionRequest) -> IngestionResponse:
        with start_span("rag.ingest", {"file": req.file_path, "tenant_id": req.metadata.get("tenant_id", "")}):
            return await self._run_ingest(req)

    async def _run_ingest(self, req: IngestionRequest) -> IngestionResponse:
        pipeline_start = time.perf_counter()
        path      = Path(req.file_path)
        doc_id    = req.doc_id or hashlib.md5(req.file_path.encode(), usedforsecurity=False).hexdigest()
        tenant_id = req.metadata.get("tenant_id", "")
        user_id   = req.metadata.get("user_id", "")
        logger.info(f"[Ingest] START doc_id={doc_id} file={path.name}")

        raw_doc = RawDocument(raw_id=doc_id, file_path=req.file_path,
                              doc_type=_infer_doc_type(path))
        pre = await self._preprocessor.process(raw_doc)
        if pre.is_duplicate and not req.force:
            return IngestionResponse(doc_id=doc_id, total_chunks=0, success=True,
                                     error="Duplicate document skipped")

        extracted = await self._extractor.extract(raw_doc, llm_client=self._ingest_llm)
        if extracted.extraction_errors and not extracted.body_text and not extracted.images:
            err_msg = "; ".join(extracted.extraction_errors)
            await self._audit.log_ingest(
                user_id, tenant_id, doc_id, path.name,
                result=AuditResult.FAILED, error=err_msg,
            )
            return IngestionResponse(doc_id=doc_id, total_chunks=0, success=False,
                                     error=err_msg)
        if req.metadata.get("title"):
            extracted.title = req.metadata["title"]

        # ── PII 检测与脱敏 ────────────────────────────────────────────────────
        pii_detected = False
        if getattr(settings, "pii_detection_enabled", True) and extracted.body_text:
            pii_result = self._pii_detector.detect(extracted.body_text)
            if pii_result.has_pii:
                pii_detected = True
                await self._audit.log_pii_detected(
                    user_id, tenant_id, doc_id,
                    pii_types=pii_result.pii_types,
                    count=len(pii_result.findings),
                )
                for pii_type in pii_result.pii_types:
                    pii_detected_total.labels(pii_type=pii_type).inc()

                if getattr(settings, "pii_block_on_detect", True):
                    block_entities: set[str] = set(
                        getattr(settings, "pii_block_entities", [])
                    )
                    if block_entities and any(
                        t in block_entities for t in pii_result.pii_types
                    ):
                        await self._audit.log_ingest(
                            user_id, tenant_id, doc_id, path.name,
                            result=AuditResult.BLOCKED,
                            pii_detected=True,
                            error="Blocked: PII detected",
                        )
                        return IngestionResponse(doc_id=doc_id, total_chunks=0, success=False,
                                                 error="Document blocked: PII detected")
                # 脱敏后继续处理
                extracted.body_text = pii_result.masked_text
                logger.info(
                    f"[Ingest] PII masked: {len(pii_result.findings)} items "
                    f"types={pii_result.pii_types}"
                )

        if extracted.body_text:
            quality = self._knowledge.validate_document(
                extracted.body_text, doc_id, req.file_path)
            if not quality.passed:
                err_msg = f"Quality: {'; '.join(quality.errors)}"
                await self._audit.log_ingest(
                    user_id, tenant_id, doc_id, path.name,
                    result=AuditResult.FAILED, error=err_msg,
                )
                return IngestionResponse(doc_id=doc_id, total_chunks=0, success=False,
                                         error=err_msg)

        chunks = await self._doc_processor.process(
            extracted, doc_id, llm_client=self._ingest_llm)
        if not chunks:
            await self._audit.log_ingest(
                user_id, tenant_id, doc_id, path.name,
                result=AuditResult.FAILED, error="No valid chunks",
            )
            return IngestionResponse(doc_id=doc_id, total_chunks=0, success=False,
                                     error="No valid chunks produced")

        vr = await self._vectorizer.vectorize_and_store(chunks, doc_id)

        # ── 摘要索引（可选，需要 LLM client）────────────────────────────────
        if getattr(settings, "summary_index_enabled", False) and self._ingest_llm:
            try:
                await self._summary_indexer.build_summaries(
                    chunks=chunks,
                    doc_id=doc_id,
                    title=extracted.title or path.name,
                    llm_client=self._ingest_llm,
                    embedder=self._vectorizer.embedder,
                    vector_store=self._vectorizer.vector_store,
                )
            except (RuntimeError, ValueError) as exc:
                logger.warning("[Ingest] Summary index failed (non-fatal)", exc_info=exc)

        elapsed_ms = round((time.perf_counter() - pipeline_start) * 1000, 1)
        await self._event_bus.emit_doc_ingested(doc_id, vr.total_chunks, tenant_id)

        # 记录审计日志
        await self._audit.log_ingest(
            user_id, tenant_id, doc_id, path.name,
            result=AuditResult.SUCCESS,
            chunk_count=vr.total_chunks,
            pii_detected=pii_detected,
        )

        # 记录 Prometheus 指标
        ingest_total.labels(doc_type=str(raw_doc.doc_type), result="success").inc()
        ingest_chunks_histogram.observe(vr.total_chunks)

        # 记录文档版本（非阻塞，失败不影响主流程）
        try:
            from services.knowledge.version_service import get_version_service
            _raw = pre.cleaned_text
            if isinstance(_raw, bytes) and _raw:
                checksum = __import__("hashlib").sha256(_raw).hexdigest()[:16]
            elif isinstance(_raw, str) and _raw:
                checksum = __import__("hashlib").sha256(_raw.encode()).hexdigest()[:16]
            else:
                checksum = ""
            await get_version_service().record_version(
                doc_id=doc_id,
                checksum=checksum,
                file_path=req.file_path,
                chunk_count=vr.total_chunks,
                tenant_id=tenant_id,
                user_id=user_id,
                note=req.metadata.get("note", ""),
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning("[Ingest] Version record failed (non-fatal)", exc_info=exc)

        logger.info(f"[Ingest] DONE doc_id={doc_id} chunks={vr.total_chunks} {elapsed_ms}ms")
        return IngestionResponse(doc_id=doc_id, total_chunks=vr.total_chunks,
                                 success=True, elapsed_ms=elapsed_ms,
                                 extraction_errors=extracted.extraction_errors)


class QueryPipeline:
    def __init__(self) -> None:
        self._retriever       = get_retriever()
        self._generator       = get_generator()
        self._llm             = get_llm_client()
        self._nlu             = get_nlu_service()
        self._memory          = get_memory_service()
        self._rules           = get_rules_engine()
        self._event_bus       = get_event_bus()
        self._tenant_svc      = get_tenant_service()
        self._audit           = get_audit_service()
        self._summary_indexer = get_summary_indexer()

    @log_latency
    async def run(self, req: GenerationRequest) -> GenerationResponse:
        with start_span("rag.query", {"query.length": len(req.query), "session_id": req.session_id or ""}):
            return await self._run_query(req)

    async def _run_query(self, req: GenerationRequest) -> GenerationResponse:
        t0        = time.perf_counter()
        trace_id  = str(uuid.uuid4())[:8]
        tenant_id = getattr(req, "tenant_id", "")
        user_id   = getattr(req, "user_id", "")

        logger.info(f"[Query] START trace={trace_id} query=\'{req.query[:60]}\'")

        if tenant_id and not self._tenant_svc.check_permission(tenant_id, user_id):
            await self._audit.log_permission_denied(
                user_id, tenant_id, trace_id, reason="tenant permission check failed"
            )
            return self._simple(req, "权限不足：无法访问该租户的知识库", trace_id)

        pre_rule = self._rules.run("pre_query", {"query": req.query})
        if pre_rule.action == RuleAction.BLOCK:
            rule_trigger_total.labels(stage="pre_query", action="BLOCK").inc()
            await self._audit.log_rule_blocked(
                user_id, tenant_id, trace_id, "pre_query", pre_rule.message
            )
            return self._simple(req, pre_rule.message, trace_id)

        mem_ctx = await self._memory.load_context(
            req.session_id, user_id, tenant_id, req.query)
        # 截断每轮内容（防止长回答累积导致 context 溢出，参考 claude-code MEMORY.md 25KB 上限思路）
        _MAX_TURN_CHARS = 2000
        chat_history = [{"role": t.role, "content": t.content[:_MAX_TURN_CHARS]}
                        for t in mem_ctx.short_term[-6:]]

        # QUERY-01 (REQ A-5 #3, #4): regex-first filter extraction + strip semantic query.
        # `effective_query` feeds NLU + cache_key + embedding text; `extraction.filters`
        # merges into tf below with highest precedence (tenant < req.filters < extracted).
        # `req.query` (raw) is preserved for `original_query=` audit and memory turn save.
        extraction = await get_filter_extractor().extract(req.query)
        effective_query = extraction.semantic_query

        nlu = await self._nlu.analyze(
            effective_query, self._llm, chat_history, tenant_id, user_id)

        if nlu.intent == QueryIntent.CHITCHAT:
            reply = await self._llm.chat(
                system=(
                    "你是企业内部知识库的智能助手。"
                    "用户发来了问候或闲聊，请简短友好地回应，并引导其提出具体的业务问题。"
                    "不超过两句话，语气专业自然。"
                ),
                user=req.query, temperature=0.7, task_type="chitchat")
            return self._simple(req, reply, trace_id)

        if nlu.needs_clarification:
            return self._simple(req, nlu.clarification_hint, trace_id)

        # Cache key uses stripped query + merged filter set so that
        # "第63页X" (extraction → page=63) and "X" + explicit filters={page=63}
        # can collide cleanly when the effective search is identical, but stay
        # disjoint from the unfiltered "X" search (T-08-11 cache-poisoning guard).
        cache_key = {
            "q": effective_query,
            "top_k": req.top_k,
            "filters": {**(req.filters or {}), **extraction.filters},
            "tenant": tenant_id,
        }
        cached = await cache_get("query", cache_key)
        if cached:
            cache_hit_total.labels(result="hit").inc()
            return GenerationResponse(**cached)
        cache_hit_total.labels(result="miss").inc()

        # Merge order: tenant < client (req.filters) < extracted (highest priority).
        tf = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}
        if extraction.filters:
            tf = {**(tf or {}), **extraction.filters}

        # ── 动态 top_k：根据意图自动调整检索宽度 ────────────────────────────
        effective_top_k = self._nlu.recommend_top_k(nlu.intent, req.top_k)

        # ── 摘要层预检索（可选）：先定位相关 chunk 范围，再做精检索 ─────────
        summary_chunk_ids: list[str] = []
        if getattr(settings, "summary_search_enabled", False):
            try:
                summary_chunk_ids = await self._summary_indexer.search_summaries(
                    query=req.query,
                    embedder=self._retriever.embedder,
                    vector_store=self._retriever.vector_store,
                    top_k=5,
                    filters=tf,
                )
                if summary_chunk_ids:
                    logger.debug(
                        f"[Query] Summary search: {len(summary_chunk_ids)} candidate chunk_ids"
                    )
            except (RuntimeError, ValueError) as exc:
                logger.warning("[Query] Summary search failed (non-fatal)", exc_info=exc)

        chunks, latencies = await self._retriever.retrieve_multi_query(
            queries=nlu.rewritten_queries,
            original_query=req.query,
            top_k=effective_top_k,
            filters=tf,
            llm_client=self._llm,
        )

        long_ctx = ""
        if mem_ctx.long_term_facts:
            # XML 格式与 generator.build_rag_prompt 的 <user_memory> 包装保持一致
            long_ctx = "\n".join(f"- {f}" for f in mem_ctx.long_term_facts[:3])

        response = await self._generator.generate(
            req=req, chunks=chunks, stage_latencies=latencies,
            chat_history=chat_history, long_term_context=long_ctx,
            nlu_result=nlu, user_profile=mem_ctx.user_profile,
        )
        response.trace_id = trace_id

        for stage, ctx in [
            ("post_answer",   {"answer": response.answer, "sources": response.sources}),
            ("quality_check", {"answer": response.answer, "sources": response.sources,
                               "faithfulness_score": response.faithfulness_score}),
        ]:
            rule = self._rules.run(stage, ctx)
            if rule.action == RuleAction.MODIFY:
                response.answer = rule.modified
                rule_trigger_total.labels(stage=stage, action="MODIFY").inc()

        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        response.latency_ms = total_ms
        response.stage_latencies["total_ms"] = total_ms

        await cache_set("query", cache_key, response)

        # ── Prometheus 指标 ───────────────────────────────────────────────────
        query_total.labels(
            intent=str(nlu.intent), tenant_id=tenant_id, result="success"
        ).inc()
        query_latency_seconds.labels(
            intent=str(nlu.intent), tenant_id=tenant_id
        ).observe(total_ms / 1000)
        faithfulness_histogram.labels(tenant_id=tenant_id).observe(
            response.faithfulness_score
        )
        retrieval_chunks_histogram.observe(len(chunks))

        # ── 审计日志 ─────────────────────────────────────────────────────────
        await self._audit.log_query(
            user_id=user_id,
            tenant_id=tenant_id,
            query=req.query,
            trace_id=trace_id,
            result=AuditResult.SUCCESS,
            latency_ms=total_ms,
            sources_count=len(chunks),
            intent=str(nlu.intent),
        )

        await self._memory.save_turn(
            session_id=req.session_id, user_id=user_id, tenant_id=tenant_id,
            user_turn=ConversationTurn(role="user", content=req.query,
                intent=nlu.intent,
                entities=[{"text": e.text, "type": e.entity_type} for e in nlu.entities]),
            ai_turn=ConversationTurn(role="assistant", content=response.answer,
                sources=[c.doc_id for c in response.sources[:3]]),
            intent=nlu.intent,
        )
        await self._event_bus.emit_query_completed(
            req.query, len(response.answer), total_ms,
            response.faithfulness_score, tenant_id, user_id)

        logger.info(f"[Query] DONE trace={trace_id} {total_ms}ms sources={len(chunks)}")
        return response

    async def stream(self, req: GenerationRequest) -> AsyncGenerator[str, None]:
        tenant_id = getattr(req, "tenant_id", "")
        user_id   = getattr(req, "user_id", "")

        # 租户权限检查（与 run() 保持一致）
        if tenant_id and not self._tenant_svc.check_permission(tenant_id, user_id):
            yield "权限不足：无法访问该租户的知识库"
            return

        # 规则引擎前置（与 run() 保持一致）
        pre_rule = self._rules.run("pre_query", {"query": req.query})
        if pre_rule.action == RuleAction.BLOCK:
            yield pre_rule.message
            return

        mem_ctx      = await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)
        _MAX_TURN_CHARS = 2000
        chat_history = [{"role": t.role, "content": t.content[:_MAX_TURN_CHARS]} for t in mem_ctx.short_term[-6:]]

        # QUERY-01 mirror of _run_query: extract filters → tf merge (extracted wins)
        # → NLU runs against the stripped semantic query so rewritten_queries don't
        # carry "第63页"-style literals into the embedder.
        extraction = await get_filter_extractor().extract(req.query)
        effective_query = extraction.semantic_query

        tf           = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}
        if extraction.filters:
            tf = {**(tf or {}), **extraction.filters}
        nlu = await self._nlu.analyze(effective_query, self._llm, chat_history, tenant_id, user_id)

        # 与 run() 保持一致：动态 top_k + long_term_context
        effective_top_k = self._nlu.recommend_top_k(nlu.intent, req.top_k)
        chunks, _ = await self._retriever.retrieve_multi_query(
            queries=nlu.rewritten_queries, original_query=req.query,
            top_k=effective_top_k, filters=tf, llm_client=self._llm)

        long_ctx = ""
        if mem_ctx.long_term_facts:
            long_ctx = "\n".join(f"- {f}" for f in mem_ctx.long_term_facts[:3])

        # 收集完整回答，用于流结束后保存记忆和发布事件
        collected: list[str] = []
        async for token in self._generator.stream_generate(
            req=req, chunks=chunks, chat_history=chat_history,
            long_term_context=long_ctx):
            collected.append(token)
            yield token

        # 流结束后：保存对话记忆 + 发布事件（与 run() 保持一致）
        full_answer = "".join(collected)
        await self._memory.save_turn(
            session_id=req.session_id, user_id=user_id, tenant_id=tenant_id,
            user_turn=ConversationTurn(
                role="user", content=req.query,
                intent=nlu.intent,
                entities=[{"text": e.text, "type": e.entity_type} for e in nlu.entities],
            ),
            ai_turn=ConversationTurn(
                role="assistant", content=full_answer,
                sources=[c.doc_id for c in chunks[:3]],
            ),
            intent=nlu.intent,
        )
        await self._event_bus.emit_query_completed(
            req.query, len(full_answer), 0.0, 0.0, tenant_id, user_id,
        )

    def _simple(self, req: GenerationRequest, msg: str, trace_id: str) -> GenerationResponse:
        return GenerationResponse(
            answer=msg, sources=[], session_id=req.session_id,
            query=req.query, latency_ms=0.0, trace_id=trace_id,
            model=settings.active_model)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 查询流水线（Agentic RAG）
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class _SubAgentResult:
    """Internal: result of a single SwarmQueryPipeline sub-agent run.

    AGENT-03 — used only inside services/pipeline.py; not part of the public API.
    """
    answer: str
    turns: int
    tool_calls_count: int
    chunks: list[RetrievedChunk]


_COORDINATOR_SYSTEM: str = """\
你是一个查询分解协调器。

任务：将用户的多维度查询分解为独立的子问题列表，每个子问题对应一个可独立检索的维度。

严格规则：
1. 仅输出 JSON 数组，无任何前缀、后缀、解释、markdown 代码块。
2. 数组元素为字符串，每个元素是一个完整、自包含的子问题。
3. 如果输入查询只有一个维度（无法进一步分解），返回包含原始查询的单元素数组：["原始查询"]。
4. 子问题数量不得超过 5 个；超出时合并语义最相近的维度。
5. 子问题必须是中文（与输入语言一致）。

示例输入：审计上月所有未结案件的产假天数、病假规定、加班补偿政策
示例输出：["上月所有未结案件的产假天数", "上月所有未结案件的病假规定", "上月所有未结案件的加班补偿政策"]

示例单维度输入：什么是产假？
示例单维度输出：["什么是产假？"]
"""


_SYNTHESIS_SYSTEM: str = """\
你是一个答案综合器。

任务：根据多个子代理对原始查询不同维度的回答，合成一个连贯、完整、无重复的最终答案。

规则：
1. 保留所有子答案中的关键事实和具体数字、政策、条款。
2. 去除子答案之间的重复表述；按维度组织最终答案，可使用小标题或列表。
3. 若某子答案标记为失败（以 '[Sub-agent ' 开头并包含 'failed'），跳过该维度并在最终答案末尾以一行注明缺失维度（不暴露技术细节）。
4. 答案必须使用中文。
5. 不得编造未在子答案中出现的信息。
"""

# Phase 21 / D-03 / Pitfall P-08 — locked Chinese disagreement banner.
# Hoisted to a module-level constant so a future v1.6+ i18n routing change
# is a single-symbol edit (no scattered string literals to chase).
# Test contract (`test_format_disagree_exact_template_substitution`) asserts
# byte-identity against this exact string; do not edit without updating tests.
_DISAGREE_BANNER_TEMPLATE: str = (
    "⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。"
    "以上回答基于验证者引用的证据（{chunk_count} 个块）。"
)

# Module-level constant (AGENT-06 / CONTEXT.md D-12).
# The cap is enforced by the orchestrator outer loop; Executor runs exactly
# one ToolPlan per call and does NOT enforce this limit internally.
MAX_ITERATIONS: int = 5

# Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
# Phase 20: web_search joins the allowlist with the real Tavily impl
# (services/agent/tools/web_search.py). Empty TAVILY_API_KEY is a runtime
# short-circuit per CONTEXT D-03 — no startup-time filtering here.
AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]


class AgentQueryPipeline:
    """
    Agentic RAG：Claude 通过 Tool Use 自主决策检索策略。

    与固定 Pipeline 的区别：
      - 固定 Pipeline：预设 NLU → 检索 → 生成 顺序，Claude 只负责生成
      - Agentic Pipeline：Claude 自主决定何时检索、检索什么、是否需要追加检索
        适用场景：复杂多跳问题、需要多次检索才能构建完整答案

    工具循环（最多 MAX_ITERATIONS 轮）：
      1. Claude 收到用户问题
      2. 如需要信息 → 调用 search_knowledge_base 工具
      3. 收到检索结果后继续推理
      4. 直到 stop_reason == "end_turn"（Claude 认为信息充足）
    """

    _AGENT_SYSTEM = """\
你是企业知识库的智能问答助手。通过工具自主检索知识库，逐步构建完整回答。

<strategy>
  1. 先拆解问题：识别需要回答哪些子问题，每个子问题对应一次工具调用。
  2. 搜索词要具体：用关键术语而非完整句子（如"产假天数"优于"员工产假有多少天"）。
  3. 初次结果不够时：换角度用 refine_search 缩小范围（换词、加限定词）。
  4. 收集到足够信息后再回答，不要在信息不完整时提前作答。
  5. 多跳问题需多轮检索：先找前提条件，再找具体规定。
</strategy>

<rules>
  1. 仅基于检索结果作答，不引入外部知识。
  2. 每个结论标注来源（如 [来源1]）。
  3. 知识库中确实没有相关信息时，明确说明，不猜测。
  4. 回答简洁准确，避免重复已知信息。
</rules>
"""

    def __init__(self) -> None:
        self._retriever        = get_retriever()
        self._llm              = get_llm_client()
        self._memory           = get_memory_service()
        self._audit            = get_audit_service()
        self._tenant_svc       = get_tenant_service()
        self._filter_extractor = get_filter_extractor()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_initial_messages(
        self,
        req: GenerationRequest,
        mem_ctx: Any,
    ) -> list[dict[str, Any]]:
        """Build the opening messages list from chat history + user query."""
        _MAX_TURN_CHARS = 2000
        messages: list[dict[str, Any]] = [
            {"role": t.role, "content": t.content[:_MAX_TURN_CHARS]}
            for t in mem_ctx.short_term[-6:]
        ]
        messages.append({"role": "user", "content": req.query})
        return messages

    @staticmethod
    def _build_tool_results(
        plan: ToolPlan,
        raw_outputs: list[ToolResult | BaseException],
        all_chunks: list[RetrievedChunk],
    ) -> list[dict[str, Any]]:
        """Convert Executor output to provider tool_result dicts.

        Appends successfully retrieved chunks to ``all_chunks`` in-place.
        Returns the tool_results list for the next user message.

        Handles three cases:
          1. BaseException — escape (CancelledError / TimeoutError from gather)
          2. ToolResult with is_error=True — controlled error from tool (e.g. RetrieveTool)
          3. ToolResult success — extend all_chunks + build tool_result dict
        """
        tool_results: list[dict[str, Any]] = []
        for tc, output in zip(plan.steps, raw_outputs):
            if isinstance(output, BaseException):
                logger.error(
                    f"[Agent] tool_call_id={tc.id} name={tc.name} failed: {output!r}"
                )
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     f"工具执行失败:{type(output).__name__}: {output}",
                    "is_error":    True,
                })
            elif output.is_error:
                logger.error(
                    f"[Agent] tool_call_id={tc.id} name={tc.name} returned is_error: {output.content}"
                )
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     output.content,
                    "is_error":    True,
                })
            else:
                all_chunks.extend(output.chunks)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     output.content,
                })
        return tool_results

    @staticmethod
    def _dedup_chunks(
        all_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Dedup by chunk_id (ONCE per turn, post-gather — gotcha #1)."""
        seen: set[str] = set()
        deduped: list[RetrievedChunk] = []
        for c in all_chunks:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                deduped.append(c)
        return deduped[:20]

    async def _build_tf(
        self,
        req: GenerationRequest,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Build the merged tenant + request + extracted filter dict."""
        extraction = await self._filter_extractor.extract(req.query)
        tf: dict[str, Any] = self._tenant_svc.get_tenant_filter(tenant_id) or {}
        if req.filters:
            tf = {**tf, **req.filters}
        if extraction.filters:
            tf = {**tf, **extraction.filters}
        return tf

    async def _persist_turn(
        self,
        req: GenerationRequest,
        answer: str,
        all_chunks: list[RetrievedChunk],
        trace_id: str,
        t0: float,
        parallelism_factors: list[int],
    ) -> GenerationResponse:
        """Save memory, write audit log, return GenerationResponse."""
        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        user_id, tenant_id = getattr(req, "user_id", ""), getattr(req, "tenant_id", "")
        await self._memory.save_turn(
            session_id=req.session_id, user_id=user_id, tenant_id=tenant_id,
            user_turn=ConversationTurn(role="user", content=req.query),
            ai_turn=ConversationTurn(
                role="assistant", content=answer,
                sources=[c.doc_id for c in all_chunks[:3]],
            ),
            intent=None,
        )
        await self._audit.log_query(
            user_id=user_id, tenant_id=tenant_id, query=req.query, trace_id=trace_id,
            result=AuditResult.SUCCESS, latency_ms=total_ms,
            sources_count=len(all_chunks), intent="agent",
        )
        max_par = max(parallelism_factors) if parallelism_factors else 0
        logger.info(f"[Agent] DONE trace={trace_id} {total_ms}ms chunks={len(all_chunks)} "
                    f"max_parallelism={max_par} turns={len(parallelism_factors)}")
        return GenerationResponse(
            answer=answer, sources=all_chunks[:req.top_k],
            session_id=req.session_id, query=req.query,
            latency_ms=total_ms, trace_id=trace_id, model=settings.active_model,
        )

    # ── main entry point ─────────────────────────────────────────────────────

    async def run(self, req: GenerationRequest) -> GenerationResponse:
        trace_id = str(uuid.uuid4())[:8]
        tenant_id, user_id = getattr(req, "tenant_id", ""), getattr(req, "user_id", "")
        t0 = time.perf_counter()
        tf = await self._build_tf(req, tenant_id)
        mem_ctx = await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)
        messages = self._build_initial_messages(req, mem_ctx)
        planner, executor = get_planner(), get_executor()
        all_chunks: list[RetrievedChunk] = []
        parallelism_factors: list[int] = []
        answer = ""

        for iteration in range(MAX_ITERATIONS):
            try:
                plan: ToolPlan = await planner.plan_from_messages(
                    messages,
                    tools=get_tool_registry().schemas_for(
                        "anthropic",
                        names=AGENT_TOOL_ALLOWLIST,
                    ),
                    system=self._AGENT_SYSTEM,
                )
            except NotImplementedError:
                logger.warning(f"[Agent] provider lacks call_agentic_turn — falling back: "
                               f"provider={type(self._llm).__name__}")
                return await get_query_pipeline().run(req)
            except (anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
                logger.error(f"[Agent] call_agentic_turn failed iter={iteration+1}: {exc!r}")
                answer = "抱歉，智能助手在处理您的请求时遇到了错误，请稍后重试。"
                break

            if not plan.steps:  # terminal: plan.rationale IS the final answer (D-10)
                answer = plan.rationale or answer
                if plan.stop_reason == "max_tokens":
                    logger.warning(f"[Agent] iter={iteration+1} stop_reason=max_tokens (response truncated)")
                break

            messages.append(plan.raw_assistant_msg)
            parallelism = len(plan.steps)
            parallelism_factors.append(parallelism)
            logger.info(f"[Agent] iter={iteration+1} parallel_factor={parallelism} "
                        f"tools={[tc.name for tc in plan.steps]}")
            raw_outputs = await executor.execute_plan(plan, tf, req)
            tool_results = self._build_tool_results(plan, raw_outputs, all_chunks)
            all_chunks = self._dedup_chunks(all_chunks)  # dedup ONCE per turn, post-gather
            messages.append({"role": "user", "content": tool_results})

        return await self._persist_turn(req, answer, all_chunks, trace_id, t0, parallelism_factors)

    # ── streaming entry point (Phase 18 AGENT-04) ───────────────────────────

    async def run_streaming(
        self,
        req: GenerationRequest,
    ) -> AsyncIterator[AgentEvent]:
        """Streaming sibling of ``run`` — yields AgentEvent per planner/tool/synthesizer step.

        Mirrors the ``run`` loop body verbatim except:
          - Yields ``PlannerPlanEvent`` immediately after each successful
            planner call (D-06).
          - Replaces ``executor.execute_plan(...)`` with
            ``executor.execute_plan_streaming(...)``, forwarding the events
            it emits and collecting the bare ``ToolResult`` /
            ``BaseException`` results.
          - Yields ``SynthesizerFinalEvent`` after the iteration loop
            finishes (D-07).
          - Calls ``_persist_turn`` AFTER the synthesizer.final event so
            audit / memory logging is unchanged (security_gate).

        Existing ``run`` is byte-identical and remains for the legacy
        non-streaming path (``/query?agent_mode=true``).
        """
        trace_id = uuid.uuid4().hex[:8]
        seq_counter = itertools.count()

        tenant_id, user_id = getattr(req, "tenant_id", ""), getattr(req, "user_id", "")
        t0 = time.perf_counter()
        tf = await self._build_tf(req, tenant_id)
        mem_ctx = await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)
        messages = self._build_initial_messages(req, mem_ctx)
        planner, executor = get_planner(), get_executor()
        all_chunks: list[RetrievedChunk] = []
        parallelism_factors: list[int] = []
        answer = ""

        for iteration in range(MAX_ITERATIONS):
            try:
                plan: ToolPlan = await planner.plan_from_messages(
                    messages,
                    tools=get_tool_registry().schemas_for(
                        "anthropic",
                        names=AGENT_TOOL_ALLOWLIST,
                    ),
                    system=self._AGENT_SYSTEM,
                )
            except NotImplementedError:
                logger.warning(
                    f"[Agent:stream] provider lacks call_agentic_turn — "
                    f"provider={type(self._llm).__name__}"
                )
                answer = "智能助手在当前模型上不可用，请切换 provider 后重试。"
                break
            except (anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
                logger.error(f"[Agent:stream] call_agentic_turn failed iter={iteration+1}: {exc!r}")
                answer = "抱歉，智能助手在处理您的请求时遇到了错误，请稍后重试。"
                break

            if not plan.steps:  # terminal: plan.rationale IS the final answer (D-06)
                answer = plan.rationale or answer
                if plan.stop_reason == "max_tokens":
                    logger.warning(
                        f"[Agent:stream] iter={iteration+1} stop_reason=max_tokens "
                        f"(response truncated)"
                    )
                break

            # Emit planner.plan ONLY for plans that have steps
            # (D-06: event mirrors planner-action boundary).
            yield PlannerPlanEvent(
                trace_id=trace_id,
                seq=next(seq_counter),
                ts_ms=int(time.time() * 1000),
                plan=plan,
            )

            messages.append(plan.raw_assistant_msg)
            parallelism = len(plan.steps)
            parallelism_factors.append(parallelism)
            logger.info(
                f"[Agent:stream] iter={iteration+1} parallel_factor={parallelism} "
                f"tools={[tc.name for tc in plan.steps]}"
            )

            # ──────────────────────────────────────────────────────────────
            # Span-id pairing (Task 2b refactor).
            # Executor contract (plan 18-02):
            #   1. ToolSpanStartEvent emit in flat parallel-group iteration
            #      order — bind span_id → step idx as each start arrives.
            #   2. ToolSpanEndEvent / ToolSpanErrorEvent for span S is yielded
            #      IMMEDIATELY before the bare result/exception for span S.
            #   3. Bare results may arrive in as_completed order WITHIN a
            #      group — NOT necessarily plan.steps order.
            # Strategy: track (span_id → step_idx) on each start event; on
            # each end/error event, buffer the resolved step_idx in
            # `_pending_idx` so the very next bare-result yield slots into
            # raw_outputs at the correct index.
            # ──────────────────────────────────────────────────────────────
            raw_outputs: list[ToolResult | BaseException | None] = [None] * len(plan.steps)
            flat_idx_order: list[int] = [idx for group in plan.parallel_groups for idx in group]
            flat_pos: int = 0
            span_id_to_step_idx: dict[str, int] = {}
            _pending_idx: int = -1   # step idx whose bare result arrives next

            async for item in executor.execute_plan_streaming(
                plan, tf, req,
                trace_id=trace_id,
                seq_counter=seq_counter,
            ):
                if isinstance(item, AgentEvent):
                    yield item
                    if isinstance(item, ToolSpanStartEvent):
                        # Executor emits start events in flat_idx_order — bind span_id.
                        if flat_pos < len(flat_idx_order):
                            span_id_to_step_idx[item.span_id] = flat_idx_order[flat_pos]
                            flat_pos += 1
                    elif isinstance(item, (ToolSpanEndEvent, ToolSpanErrorEvent)):
                        # Buffer the step idx whose bare result arrives next.
                        _pending_idx = span_id_to_step_idx.get(item.span_id, -1)
                else:
                    # Bare ToolResult or BaseException — pair with most-recently-resolved span.
                    if 0 <= _pending_idx < len(raw_outputs):
                        raw_outputs[_pending_idx] = item
                        _pending_idx = -1   # reset; next end/error event will set the next idx
                    # else: contract violation — drop result; defensive None below
                    #       converts to RuntimeError so _build_tool_results contract holds.

            collected: list[ToolResult | BaseException] = [
                r if r is not None else RuntimeError("missing executor result")
                for r in raw_outputs
            ]
            tool_results = self._build_tool_results(plan, collected, all_chunks)
            all_chunks = self._dedup_chunks(all_chunks)
            messages.append({"role": "user", "content": tool_results})

        # Synthesizer.final — emitted regardless of how loop ended
        # (terminal-plan, error, max-iter).
        yield SynthesizerFinalEvent(
            trace_id=trace_id,
            seq=next(seq_counter),
            ts_ms=int(time.time() * 1000),
            answer=answer,
            sources_count=len(all_chunks),
        )

        # Audit log + memory persistence — unchanged shape (security_gate).
        await self._persist_turn(req, answer, all_chunks, trace_id, t0, parallelism_factors)


_ingest_pipeline = None
_query_pipeline  = None
_agent_pipeline  = None

def get_ingest_pipeline():
    global _ingest_pipeline
    if _ingest_pipeline is None:
        _ingest_pipeline = IngestionPipeline()
    return _ingest_pipeline

def get_query_pipeline():
    global _query_pipeline
    if _query_pipeline is None:
        _query_pipeline = QueryPipeline()
    return _query_pipeline

def get_agent_pipeline():
    global _agent_pipeline
    if _agent_pipeline is None:
        _agent_pipeline = AgentQueryPipeline()
    return _agent_pipeline


# ══════════════════════════════════════════════════════════════════════════════
# Swarm 查询流水线（Fork-Agent — AGENT-03）
# ══════════════════════════════════════════════════════════════════════════════
class SwarmQueryPipeline:
    """Fork-Agent Swarm pipeline (AGENT-03).

    Decomposes a multi-dimension query into N independent sub-questions
    (D-02), runs each as an isolated AgentQueryPipeline-style sub-agent
    with its own short tool loop (D-05), then synthesizes their answers
    (D-04). N=1 short-circuits to AgentQueryPipeline (D-03). The agent
    class is unmodified (D-01).
    """

    MAX_SWARM_AGENTS: int = int(getattr(settings, "max_swarm_agents", 5))
    MAX_SWARM_TURNS_PER_AGENT: int = int(getattr(settings, "max_swarm_turns_per_agent", 5))

    def __init__(self) -> None:
        self._retriever        = get_retriever()
        self._llm              = get_llm_client()
        self._memory           = get_memory_service()
        self._audit            = get_audit_service()
        self._tenant_svc       = get_tenant_service()
        self._filter_extractor = get_filter_extractor()

    async def _decompose(self, query: str) -> list[str]:
        """Decompose a multi-dimension query into independent sub-questions (D-02).

        Returns single-element list `[query]` when:
          - LLM output cannot be parsed as JSON
          - Parsed result is not a list
          - Parsed list is empty after strip+dedup
        """
        raw: str = await self._llm.chat(
            system=_COORDINATOR_SYSTEM,
            user=query,
            temperature=0.0,
            task_type="generate",   # main model — see Pitfall 4
        )

        # Extract first JSON array substring (LLM may wrap in prose despite instruction).
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match is None:
            logger.warning(f"[Swarm] coordinator returned no JSON array; falling back to N=1. raw={raw[:200]!r}")
            return [query]

        try:
            parsed = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(f"[Swarm] coordinator JSON parse failed: {exc!r}; falling back to N=1. raw={match.group(0)[:200]!r}")
            return [query]

        if not isinstance(parsed, list):
            logger.warning(f"[Swarm] coordinator returned non-list ({type(parsed).__name__}); falling back to N=1.")
            return [query]

        # Strip + dedup while preserving order; drop empty/non-string entries.
        seen: set[str] = set()
        sub_questions: list[str] = []
        for item in parsed:
            if not isinstance(item, str):
                continue
            stripped = item.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            sub_questions.append(stripped)

        if not sub_questions:
            logger.warning("[Swarm] coordinator returned empty list after cleanup; falling back to N=1.")
            return [query]

        # Cap at MAX_SWARM_AGENTS (D-09).
        return sub_questions[: self.MAX_SWARM_AGENTS]

    async def _run_sub_agent(
        self,
        agent_index: int,
        sub_question: str,
        tf: dict[str, Any],
        req: GenerationRequest,
    ) -> _SubAgentResult:
        """Run a single sub-agent — bounded tool loop, isolated state (Pitfall 1, D-06)."""
        # Fresh messages list per coroutine — never shared (Pitfall 1).
        # Sub-agents receive ONLY their sub-question; chat history is excluded (D-06).
        messages: list[dict[str, Any]] = [{"role": "user", "content": sub_question}]
        answer: str = ""
        turns: int = 0
        tool_calls_count: int = 0
        all_chunks: list[RetrievedChunk] = []

        for iteration in range(self.MAX_SWARM_TURNS_PER_AGENT):
            turns = iteration + 1
            try:
                turn = await self._llm.call_agentic_turn(
                    messages=messages,
                    tools=get_tool_registry().schemas_for(
                        "anthropic",
                        names=AGENT_TOOL_ALLOWLIST,
                    ),
                    system=AgentQueryPipeline._AGENT_SYSTEM,
                    max_tokens=settings.llm_max_tokens,
                    parallel_tool_calls=True,
                )
            except (
                anthropic.APIError,
                openai.APIError,
                httpx.HTTPError,
                asyncio.TimeoutError,
            ) as exc:
                logger.error(f"[Swarm] sub-agent {agent_index} call_agentic_turn failed iter={turns}: {exc!r}")
                answer = f"[Sub-agent {agent_index} failed: {exc!r}]"
                break

            # Terminal stop reasons → take the text and exit.
            if turn.stop_reason in ("text_only", "max_tokens", "error"):
                answer = turn.text or answer
                break

            if not turn.tool_calls:
                answer = turn.text or answer
                break

            # Append assistant's tool-use message; gather tool results concurrently.
            messages.append(turn.raw_assistant_msg)
            tool_calls_count += len(turn.tool_calls)

            tool_coros = [
                _shared_execute_tool_call(tc, tf, req, self._retriever, self._llm)
                for tc in turn.tool_calls
            ]
            tool_outputs = await asyncio.gather(*tool_coros, return_exceptions=True)

            tool_results: list[dict[str, Any]] = []
            for tc, output in zip(turn.tool_calls, tool_outputs):
                if isinstance(output, BaseException):
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": tc.id,
                        "content":     f"工具执行失败:{type(output).__name__}: {output}",
                        "is_error":    True,
                    })
                else:
                    chunks, ctx_text = output
                    all_chunks.extend(chunks)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": tc.id,
                        "content":     ctx_text,
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            # Loop exited via for-else → max turns reached without break.
            logger.warning(f"[Swarm] sub-agent {agent_index} hit MAX_SWARM_TURNS_PER_AGENT={self.MAX_SWARM_TURNS_PER_AGENT}")
            answer = answer or f"[Sub-agent {agent_index} reached max turns without final answer]"

        return _SubAgentResult(
            answer=answer,
            turns=turns,
            tool_calls_count=tool_calls_count,
            chunks=all_chunks,
        )

    async def _synthesize(
        self,
        original_query: str,
        sub_questions: list[str],
        answers: list[str],
        verifier_verdict: VerifierVerdict | None = None,   # Phase 21 / D-04
    ) -> str:
        """Synthesize sub-agent answers into final response (D-04, Pitfall 5).

        Short-circuits to graceful-degradation string when all sub-agents failed,
        avoiding a wasted LLM call (Pitfall 5).

        Phase 21 / D-04: when ``verifier_verdict`` is supplied AND its verdict
        is ``"disagree"``, short-circuit to ``_format_disagree`` (zero LLM
        calls — the verifier's ``proposed_answer`` IS the user-visible answer
        per D-01/D-02). All other branches (kwarg omitted, kwarg ``None``,
        verdict ``"agree"``) fall through to the EXISTING synthesis body so
        SC5/CF-08 byte-identity holds for the non-debate path.
        """
        # Phase 21 / D-04 — divergence dispatch (zero LLM calls; uses
        # verifier.proposed_answer as the user-visible answer per D-01/D-02).
        # Runs BEFORE the Pitfall-5 graceful-degrade check: a verifier verdict
        # supersedes the all-sub-agents-failed fallback (in practice Plan 21-05
        # only invokes the verifier when at least one peer succeeded, so the
        # ordering is observationally equivalent — this is just cleaner to read).
        if verifier_verdict is not None and verifier_verdict.verdict == "disagree":
            # D-04 verbatim signature: _format_disagree(verdict, sub_results).
            # Reconstruct minimal _SubAgentResult placeholders from the answers
            # list so peer_count == len(answers). The chunks/turns/tool_calls_count
            # fields are not consumed by _format_disagree (only len(sub_results)
            # is read), so empty placeholders suffice. This keeps Plan 21-05's
            # call site simple — no need to plumb the original `successful` list.
            sub_results = [
                _SubAgentResult(answer=a, turns=0, tool_calls_count=0, chunks=[])
                for a in answers
            ]
            return self._format_disagree(verifier_verdict, sub_results)

        # Pitfall 5: skip LLM if every sub-agent failed.
        if answers and all(
            a.startswith("[Sub-agent ") and " failed:" in a
            for a in answers
        ):
            logger.error("[Swarm] all sub-agents failed; returning graceful degradation string without synthesis call")
            return "抱歉，所有子代理处理失败，无法生成答案。"

        # Format: numbered (sub_question, answer) pairs for the synthesizer.
        sections: list[str] = [f"原始查询：{original_query}", ""]
        for idx, (q, a) in enumerate(zip(sub_questions, answers), start=1):
            sections.append(f"=== 子问题 {idx} ===")
            sections.append(f"问：{q}")
            sections.append(f"答：{a}")
            sections.append("")
        formatted = "\n".join(sections).rstrip()

        return await self._llm.chat(
            system=_SYNTHESIS_SYSTEM,
            user=formatted,
            temperature=0.1,
            task_type="generate",
        )

    @staticmethod
    def _format_disagree(
        verdict: VerifierVerdict,
        sub_results: list[_SubAgentResult],
    ) -> str:
        """Phase 21 / D-04 / D-03 / P-08 — format the divergence answer.

        Signature matches CONTEXT D-04 verbatim (``_format_disagree(verdict,
        sub_results)``); ``peer_count`` is computed inside as
        ``len(sub_results)``. Returns ``f"{verdict.proposed_answer}\\n\\n{banner}"``
        where the banner is the locked ``_DISAGREE_BANNER_TEMPLATE`` constant
        with ``N`` / ``M`` / ``chunk_count`` substituted.

        N=M is intentional in v1.5: every successful peer is treated as having
        "diverged from the verified consensus" (coarse-grain count). Per-peer
        divergence tracking is a v1.6+ topic per CONTEXT deferred-list.
        """
        peer_count = len(sub_results)
        banner = _DISAGREE_BANNER_TEMPLATE.format(
            N=peer_count,
            M=peer_count,
            chunk_count=len(verdict.evidence_chunk_ids),
        )
        return f"{verdict.proposed_answer}\n\n{banner}"

    async def run(self, req: GenerationRequest) -> GenerationResponse:
        """Top-level swarm execution (AGENT-03).

        Sequence:
          1. Decompose query into sub-questions (D-02).
          2. N=1 → delegate to AgentQueryPipeline (D-03).
          3. Fan out N sub-agents concurrently (D-05).
          4. Collect results; replace exceptions with error markers (Pitfall 2).
          5. Synthesize final answer (D-04).
          6. Persist memory + audit; return response.
        """
        trace_id  = str(uuid.uuid4())[:8]
        tenant_id = getattr(req, "tenant_id", "")
        user_id   = getattr(req, "user_id",   "")
        t0        = time.perf_counter()

        extraction = await self._filter_extractor.extract(req.query)
        tf = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}
        if extraction.filters:
            tf = {**(tf or {}), **extraction.filters}

        sub_questions = await self._decompose(req.query)

        # D-03: N=1 short-circuit — delegate to AgentQueryPipeline.
        if len(sub_questions) <= 1:
            logger.info(
                f"[Swarm] N=1 fallback (sub_questions={sub_questions!r}); delegating to AgentQueryPipeline. trace_id={trace_id}"
            )
            return await get_agent_pipeline().run(req)

        # D-05: fan out concurrently; isolate failures.
        swarm_t0 = time.perf_counter()
        sub_coros = [
            self._run_sub_agent(i, q, tf or {}, req)
            for i, q in enumerate(sub_questions)
        ]
        raw_results = await asyncio.gather(*sub_coros, return_exceptions=True)
        swarm_latency_ms = round((time.perf_counter() - swarm_t0) * 1000, 1)

        answers: list[str] = []
        per_agent_turns: list[int] = []
        per_agent_tool_calls: list[int] = []
        all_swarm_chunks: list[RetrievedChunk] = []
        for i, res in enumerate(raw_results):
            # Pitfall 2: BaseException (covers asyncio.CancelledError, TimeoutError),
            # NOT Exception.
            if isinstance(res, BaseException):
                logger.error(f"[Swarm] sub-agent {i} raised: {res!r}")
                answers.append(f"[Sub-agent {i} failed: {res!r}]")
                per_agent_turns.append(0)
                per_agent_tool_calls.append(0)
                continue
            # res is _SubAgentResult
            answers.append(res.answer)
            per_agent_turns.append(res.turns)
            per_agent_tool_calls.append(res.tool_calls_count)
            all_swarm_chunks.extend(res.chunks)

        synth_t0 = time.perf_counter()
        final_answer = await self._synthesize(req.query, sub_questions, answers)
        synthesis_latency_ms = round((time.perf_counter() - synth_t0) * 1000, 1)

        total_ms = round((time.perf_counter() - t0) * 1000, 1)

        # Persist memory turn (mirrors AgentQueryPipeline pattern).
        await self._memory.save_turn(
            session_id=req.session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            user_turn=ConversationTurn(role="user", content=req.query),
            ai_turn=ConversationTurn(role="assistant", content=final_answer),
            intent=None,
        )

        # CRITICAL: audit via log() directly with AuditEvent — log_query has a
        # FIXED signature and cannot accept swarm_n/per_agent_*/etc.
        await self._audit.log(AuditEvent(
            action=AuditAction.QUERY,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_id=hashlib.sha256(req.query.encode()).hexdigest()[:16],
            result=AuditResult.SUCCESS,
            detail={
                "latency_ms":           total_ms,
                "sources_count":        len(all_swarm_chunks),
                "query_len":            len(req.query),
                "intent":               "swarm",
                "swarm_n":              len(sub_questions),
                "per_agent_turns":      per_agent_turns,
                "per_agent_tool_calls": per_agent_tool_calls,
                "swarm_latency_ms":     swarm_latency_ms,
                "synthesis_latency_ms": synthesis_latency_ms,
            },
            trace_id=trace_id,
        ))

        return GenerationResponse(
            answer=final_answer,
            sources=all_swarm_chunks[:req.top_k],
            session_id=req.session_id,
            query=req.query,
            latency_ms=total_ms,
            trace_id=trace_id,
            model=settings.active_model,
        )


_swarm_pipeline = None
def get_swarm_pipeline():
    global _swarm_pipeline
    if _swarm_pipeline is None:
        _swarm_pipeline = SwarmQueryPipeline()
    return _swarm_pipeline
