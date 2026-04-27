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

import hashlib
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger

from config.settings import settings
from utils.models import (
    RawDocument, DocType, IngestionRequest, IngestionResponse,
    GenerationRequest, GenerationResponse, RetrievedChunk,
)
from utils.cache import cache_get, cache_set
from utils.logger import log_latency

# Stage services
from services.preprocessor.cleaner import get_preprocessor
from services.extractor.extractor import get_extractor
from services.doc_processor.chunker import get_doc_processor
from services.vectorizer.indexer import get_vectorizer
from services.retriever.retriever import get_retriever
from services.generator.generator import get_generator
from services.generator.llm_client import get_llm_client

# Core services
from services.nlu.nlu_service import get_nlu_service, QueryIntent, NLUResult
from services.memory.memory_service import (
    get_memory_service, ConversationTurn, MemoryContext,
)
from services.rules.rules_engine import get_rules_engine, RuleAction
from services.events.event_bus import get_event_bus
from services.tenant.tenant_service import get_tenant_service
from services.knowledge.knowledge_service import get_knowledge_service

# Enterprise feature services
from services.preprocessor.pii_detector import get_pii_detector
from services.audit.audit_service import get_audit_service, AuditResult
from services.knowledge.summary_indexer import get_summary_indexer
from utils.metrics import (
    query_total, query_latency_seconds, faithfulness_histogram,
    retrieval_chunks_histogram, ingest_total, ingest_chunks_histogram,
    pii_detected_total, cache_hit_total, rule_trigger_total,
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
            checksum = pre.cleaned_text and __import__("hashlib").sha256(
                pre.cleaned_text.encode()).hexdigest()[:16] or ""
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

        nlu = await self._nlu.analyze(
            req.query, self._llm, chat_history, tenant_id, user_id)

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

        cache_key = {"q": req.query, "top_k": req.top_k,
                     "filters": req.filters, "tenant": tenant_id}
        cached = await cache_get("query", cache_key)
        if cached:
            cache_hit_total.labels(result="hit").inc()
            return GenerationResponse(**cached)
        cache_hit_total.labels(result="miss").inc()

        tf = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}

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
        tf           = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}
        nlu = await self._nlu.analyze(req.query, self._llm, chat_history, tenant_id, user_id)

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

    MAX_ITERATIONS = 5

    _AGENT_TOOLS = [
        {
            "name": "search_knowledge_base",
            "description": "在企业知识库中搜索相关信息",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词，应精确描述需要找到的信息",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量（1-10）",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "refine_search",
            "description": "用更精确的关键词细化搜索，适用于初次搜索结果不够具体时",
            "input_schema": {
                "type": "object",
                "properties": {
                    "refined_query": {
                        "type": "string",
                        "description": "更精确的搜索词",
                    },
                    "source_filter": {
                        "type": "string",
                        "description": "限定搜索的文档来源（可选）",
                    },
                },
                "required": ["refined_query"],
            },
        },
    ]

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
        self._retriever  = get_retriever()
        self._llm        = get_llm_client()
        self._memory     = get_memory_service()
        self._audit      = get_audit_service()
        self._tenant_svc = get_tenant_service()

    async def run(self, req: GenerationRequest) -> GenerationResponse:
        from services.generator.llm_client import AnthropicLLMClient

        # Agent 模式要求 Anthropic LLM（Tool Use 原生支持）
        if not isinstance(self._llm, AnthropicLLMClient):
            logger.warning("[Agent] Non-Anthropic provider, falling back to QueryPipeline")
            return await get_query_pipeline().run(req)

        import anthropic
        trace_id  = str(uuid.uuid4())[:8]
        tenant_id = getattr(req, "tenant_id", "")
        user_id   = getattr(req, "user_id",   "")
        t0        = time.perf_counter()

        mem_ctx      = await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)
        _MAX_TURN_CHARS = 2000
        chat_history = [{"role": t.role, "content": t.content[:_MAX_TURN_CHARS]} for t in mem_ctx.short_term[-6:]]
        tf           = self._tenant_svc.get_tenant_filter(tenant_id)
        if req.filters:
            tf = {**(tf or {}), **req.filters}

        # 构建初始 messages（含对话历史）
        messages: list[dict] = []
        for turn in chat_history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": req.query})

        all_chunks: list[RetrievedChunk] = []
        answer = ""

        from services.generator.llm_client import _report_usage
        for iteration in range(self.MAX_ITERATIONS):
            try:
                resp = await self._llm._client.messages.create(
                    model=self._llm._default_model,
                    max_tokens=settings.llm_max_tokens,
                    system=self._llm._cached_system(self._AGENT_SYSTEM),
                    tools=self._AGENT_TOOLS,
                    messages=messages,
                )
            except anthropic.APIError as exc:
                logger.error("[Agent] Anthropic API error", iteration=iteration + 1, exc_info=exc)
                answer = "抱歉，智能助手在处理您的请求时遇到了错误，请稍后重试。"
                break
            _report_usage(resp, "anthropic", model=self._llm._default_model)

            if resp.stop_reason == "end_turn":
                # Claude 已有足够信息，提取最终答案
                answer = " ".join(
                    b.text for b in resp.content if b.type == "text"
                )
                break

            if resp.stop_reason != "tool_use":
                answer = " ".join(b.text for b in resp.content if b.type == "text")
                break

            # 处理工具调用
            messages.append({"role": "assistant", "content": resp.content})
            tool_results: list[dict] = []

            for block in resp.content:
                if block.type != "tool_use":
                    continue
                tool_input = block.input
                query_str  = tool_input.get("query") or tool_input.get("refined_query", req.query)
                top_k      = min(int(tool_input.get("top_k", 5)), 10)
                src_filter = tool_input.get("source_filter")

                effective_filter = dict(tf or {})
                if src_filter:
                    effective_filter["source"] = src_filter

                logger.info(f"[Agent] iter={iteration+1} tool={block.name} query='{query_str[:50]}'")

                chunks, _ = await self._retriever.retrieve(
                    query=query_str,
                    top_k=top_k,
                    filters=effective_filter or None,
                    llm_client=self._llm,
                )
                all_chunks.extend(chunks)

                # 去重（按 chunk_id）
                seen_ids: set[str] = set()
                deduped: list[RetrievedChunk] = []
                for c in all_chunks:
                    if c.chunk_id not in seen_ids:
                        seen_ids.add(c.chunk_id)
                        deduped.append(c)
                all_chunks = deduped[:20]

                # 将检索结果序列化返回给 Claude（XML document 格式，与主 RAG prompt 一致）
                if chunks:
                    doc_blocks = "\n\n".join(
                        f'<document index="{i+1}" title="{c.metadata.title or c.doc_id}">\n'
                        f"{c.content}\n"
                        f"</document>"
                        for i, c in enumerate(chunks)
                    )
                    ctx_text = f"<search_results>\n{doc_blocks}\n</search_results>"
                else:
                    ctx_text = "未找到相关内容"
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     ctx_text,
                })

            messages.append({"role": "user", "content": tool_results})

        total_ms = round((time.perf_counter() - t0) * 1000, 1)

        # 保存记忆
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
            user_id=user_id, tenant_id=tenant_id,
            query=req.query, trace_id=trace_id,
            result=AuditResult.SUCCESS, latency_ms=total_ms,
            sources_count=len(all_chunks), intent="agent",
        )

        logger.info(f"[Agent] DONE trace={trace_id} {total_ms}ms chunks={len(all_chunks)}")
        return GenerationResponse(
            answer=answer,
            sources=all_chunks[:req.top_k],
            session_id=req.session_id,
            query=req.query,
            latency_ms=total_ms,
            trace_id=trace_id,
            model=settings.active_model,
        )


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
