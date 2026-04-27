# =============================================================================
# services/generator/generator.py
# STAGE 6b — 生成
# 职责：Prompt 构建 → LLM 调用（流式/非流式）→ 来源标注 → 忠实度评估
#
# 优化点：
#   1. XML 标签 Prompt 结构：替换 【】括号，Claude 对 XML 标签有原生优化
#   2. 精准 Token 计数：用 tiktoken cl100k_base，修复中文 "3字符/token" 的错误估算
#   3. LLM-as-Judge 忠实度：Anthropic provider 用 Haiku+Tool Use 替换 keyword overlap
# =============================================================================
from __future__ import annotations
import re
import time
import uuid
from typing import AsyncGenerator
from loguru import logger

from config.settings import settings
from utils.models import RetrievedChunk, GenerationRequest, GenerationResponse
from utils.logger import log_latency
from utils.metrics import llm_latency_seconds
from utils.observability import start_span
from services.generator.llm_client import get_llm_client


# ══════════════════════════════════════════════════════════════════════════════
# Token 计数（精准版）
# ══════════════════════════════════════════════════════════════════════════════
_tiktoken_enc = None


def _count_tokens(text: str) -> int:
    """精确 Token 计数。

    优先使用 tiktoken cl100k_base（GPT-4 / Claude 的近似 tokenizer）。
    中文字符平均约 1.5 token，不是原来错误的 3 chars/token。
    """
    global _tiktoken_enc
    if _tiktoken_enc is None:
        try:
            import tiktoken
            _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_enc = False  # 标记为不可用

    if _tiktoken_enc:
        try:
            return len(_tiktoken_enc.encode(text))
        except Exception:
            pass

    # Fallback：中文≈1.5 token/字，ASCII≈0.25 token/字
    chinese   = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_cnt = len(text) - chinese
    return int(chinese * 1.5 + ascii_cnt * 0.25)


# ══════════════════════════════════════════════════════════════════════════════
# Prompt Builder — XML 标签结构
# ══════════════════════════════════════════════════════════════════════════════
# XML 标签优势：
#   - Claude 的训练数据大量使用 XML，模型对此有原生理解
#   - 边界清晰，不会与文档内容中的【】混淆
#   - <document> 结构与 Anthropic Citations API 格式兼容
_SYSTEM_PROMPT = """\
你是严谨的企业级知识库问答助手。

<role>
  基于 <documents> 中检索到的文档片段回答问题。不引入文档之外的知识、推断或假设。
</role>

<rules>
  1. 仅使用 <documents> 中明确出现的信息作答。
  2. 文档片段不足以回答时，明确说明："根据现有文档资料，无法准确回答此问题。"
  3. 引用来源时使用 [来源N] 格式（N 为 document 的 index 编号）。
  4. 多个文档片段支持同一观点时，全部标注（如 [来源1][来源3]）。
  5. 不同文档片段出现矛盾时，如实指出矛盾并分别列出各方说法。
  6. 问题只有部分答案时，回答已知部分并说明哪些方面无法从现有资料确认。
  7. 回答简洁、准确、专业；避免重复、套话和无关内容。
</rules>
"""


def build_rag_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    chat_history: list[dict[str, str]] | None = None,
    long_term_context: str = "",
) -> tuple[str, str]:
    """构建 RAG Prompt（XML 标签结构）。

    返回 (system_prompt, user_prompt)。
    Token 预算用精准计数，避免中文场景下大量浪费上下文窗口。
    """
    # 使用 effective_context_window 而非 llm_context_window（默认值 8192 会大幅低估 Claude 200k 窗口）
    # 参考 claude-code context.ts: getContextWindowForModel()
    token_budget = settings.effective_context_window - settings.llm_max_tokens - 512  # 保留回答空间
    used_tokens  = 0

    # ── 文档上下文（XML 结构） ────────────────────────────────────────────────
    doc_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        display_content = chunk.parent_content if chunk.parent_content else chunk.content
        title = chunk.metadata.title or chunk.doc_id
        entry = (
            f'<document index="{i + 1}" title="{title}">\n'
            f"{display_content}\n"
            f"</document>"
        )
        entry_tokens = _count_tokens(entry)
        if used_tokens + entry_tokens > token_budget:
            logger.debug(f"Token budget reached at document {i + 1}/{len(chunks)}")
            break
        doc_parts.append(entry)
        used_tokens += entry_tokens

    # ── 对话历史 ─────────────────────────────────────────────────────────────
    history_parts: list[str] = []
    if chat_history:
        for turn in chat_history[-6:]:
            role    = "用户" if turn.get("role") == "user" else "助手"
            content = turn.get("content", "")
            history_parts.append(f"  <turn role='{role}'>{content}</turn>")

    # ── 组装 user prompt ──────────────────────────────────────────────────────
    user_sections: list[str] = []

    if long_term_context:
        user_sections.append(
            f"<user_memory>\n{long_term_context}\n</user_memory>"
        )

    if history_parts:
        user_sections.append(
            "<conversation_history>\n"
            + "\n".join(history_parts)
            + "\n</conversation_history>"
        )

    if doc_parts:
        user_sections.append(
            "<documents>\n"
            + "\n\n".join(doc_parts)
            + "\n</documents>"
        )

    user_sections.append(f"<question>{query}</question>")

    return _SYSTEM_PROMPT, "\n\n".join(user_sections)


# ══════════════════════════════════════════════════════════════════════════════
# 忠实度评估
# ══════════════════════════════════════════════════════════════════════════════
_FAITHFULNESS_TOOL = {
    "name": "score_faithfulness",
    "description": "判断答案是否基于给定上下文，输出忠实度评分",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "0.0（完全不基于上下文）到 1.0（完全基于上下文）的忠实度分数",
            },
            "reason": {
                "type": "string",
                "description": "简短的评分理由（20字以内）",
            },
        },
        "required": ["score", "reason"],
    },
}

_FAITHFULNESS_SYSTEM = """\
你是严谨的答案忠实度评估专家。判断答案是否完全基于给定的上下文，不含外部知识或主观推断。

<scoring_criteria>
  1.0 = 答案每一句话都有上下文原文直接支撑，无推断。
  0.8 = 绝大部分基于上下文，含极少量合理推论（如根据明确数字做简单计算）。
  0.6 = 大部分基于上下文，含少量超出原文的推断或概括。
  0.4 = 约一半内容有上下文依据，一半来自模型已有知识或推断。
  0.2 = 仅少量内容有上下文依据，主要依赖外部知识。
  0.0 = 答案与上下文无实质关联，或完全依赖外部知识。
</scoring_criteria>

<key_signals>
  降分信号：出现上下文未提及的具体数字/日期/规定；使用"通常"/"一般来说"等模糊泛化语。
  加分信号：每个结论都有可追溯的上下文来源；明确标注引用位置。
</key_signals>
"""


async def estimate_faithfulness(
    answer: str,
    chunks: list[RetrievedChunk],
    llm_client=None,
) -> float:
    """忠实度评估。

    - Anthropic provider（支持 Tool Use）：用 Haiku 做 LLM-as-Judge，准确且成本极低
    - 其他 provider：降级为关键词重叠估算（原有逻辑，保留兼容性）
    """
    if not answer or not chunks:
        return 0.0

    # ── LLM-as-Judge（Anthropic Tool Use）────────────────────────────────────
    if llm_client and getattr(llm_client, "supports_tools", False):
        try:
            context_preview = "\n\n".join(c.content[:500] for c in chunks[:4])
            result = await llm_client.chat_with_tools(
                system=_FAITHFULNESS_SYSTEM,
                user=(
                    f"<context>\n{context_preview}\n</context>\n\n"
                    f"<answer>\n{answer}\n</answer>"
                ),
                tools=[_FAITHFULNESS_TOOL],
                task_type="evaluate",           # → Haiku 模型，成本极低
            )
            score = float(result.get("score", 0.5))
            reason = result.get("reason", "")
            logger.debug(f"[Faithfulness] LLM-as-Judge: {score:.2f} ({reason})")
            return round(min(score, 1.0), 3)
        except Exception as exc:
            logger.warning(f"[Faithfulness] LLM judge failed, fallback to keyword: {exc}")

    # ── Fallback：关键词重叠估算 ──────────────────────────────────────────────
    # 注意：此方法仅作兼容性保留，准确率有限
    context_text = " ".join(c.content for c in chunks).lower()
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{4,}", answer.lower())
    if not words:
        return 0.5
    match_count = sum(1 for w in words if w in context_text)
    return round(min(match_count / len(words), 1.0), 3)


# ══════════════════════════════════════════════════════════════════════════════
# GeneratorService
# ══════════════════════════════════════════════════════════════════════════════
class GeneratorService:
    """
    STAGE 6 入口：
    接收检索结果 + 用户请求 → 生成回答 → 附加来源 → 评估忠实度
    """

    def __init__(self) -> None:
        self._llm = get_llm_client()

    @log_latency
    async def generate(
        self,
        req: GenerationRequest,
        chunks: list[RetrievedChunk],
        stage_latencies: dict[str, float] | None = None,
        chat_history: list[dict] | None = None,
        long_term_context: str = "",
        nlu_result=None,
        user_profile=None,
    ) -> GenerationResponse:
        trace_id = str(uuid.uuid4())[:8]
        start    = time.perf_counter()

        if not chunks:
            return GenerationResponse(
                answer="根据现有资料，未找到与问题相关的内容，请补充更多资料或调整查询。",
                sources=[],
                session_id=req.session_id,
                query=req.query,
                latency_ms=0.0,
                trace_id=trace_id,
                model=settings.active_model,
            )

        # ── Prompt 构建 ──────────────────────────────────────────────────────
        effective_history = chat_history if chat_history is not None else req.chat_history
        system_prompt, user_prompt = build_rag_prompt(
            query=req.query,
            chunks=chunks,
            chat_history=effective_history,
            long_term_context=long_term_context,
        )

        # ── LLM 推理 ─────────────────────────────────────────────────────────
        # 多跳查询（multi_hop）优先使用 Extended Thinking
        intent = getattr(nlu_result, "intent", None)
        use_thinking = (
            getattr(self._llm, "supports_thinking", False)
            and intent is not None
            and str(intent) in ("multi_hop", "QueryIntent.MULTI_HOP")
        )

        _llm_t0 = time.perf_counter()
        with start_span("rag.llm_call", {"provider": settings.llm_provider, "thinking": use_thinking}):
            if use_thinking:
                logger.info(f"[Generate] multi_hop intent → Extended Thinking")
                answer = await self._llm.chat_thinking(
                    system=system_prompt,
                    user=user_prompt,
                    budget_tokens=8000,
                )
            else:
                answer = await self._llm.chat(
                    system=system_prompt,
                    user=user_prompt,
                    temperature=req.temperature,
                    task_type="generate",
                )
        llm_latency_seconds.labels(provider=settings.llm_provider).observe(
            time.perf_counter() - _llm_t0
        )

        # ── 忠实度评估（LLM-as-Judge 或 keyword fallback） ───────────────────
        faithfulness = await estimate_faithfulness(answer, chunks, self._llm)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        response = GenerationResponse(
            answer=answer,
            sources=chunks,
            session_id=req.session_id,
            query=req.query,
            latency_ms=elapsed_ms,
            stage_latencies=stage_latencies or {},
            faithfulness_score=faithfulness,
            trace_id=trace_id,
            model=settings.active_model,
        )

        logger.info(
            f"[Generate] DONE trace={trace_id} "
            f"latency={elapsed_ms}ms "
            f"sources={len(chunks)} "
            f"faithfulness={faithfulness} "
            f"thinking={use_thinking}"
        )
        return response

    async def stream_generate(
        self,
        req: GenerationRequest,
        chunks: list[RetrievedChunk],
        chat_history: list[dict] | None = None,
        long_term_context: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式 SSE 生成。"""
        if not chunks:
            yield "根据现有资料，未找到与问题相关的内容。"
            return

        effective_history = chat_history if chat_history is not None else req.chat_history
        system_prompt, user_prompt = build_rag_prompt(
            query=req.query,
            chunks=chunks,
            chat_history=effective_history,
            long_term_context=long_term_context,
        )
        async for token in self._llm.stream_chat(
            system=system_prompt,
            user=user_prompt,
            temperature=req.temperature,
        ):
            yield token


    async def generate_with_citations(
        self,
        req: GenerationRequest,
        chunks: list[RetrievedChunk],
        chat_history: list[dict] | None = None,
        long_term_context: str = "",
        nlu_result=None,
    ) -> GenerationResponse:
        """使用 Anthropic 原生 Citations API 生成答案（字符级精确引用）。

        仅在 llm_provider=anthropic 时生效；否则自动回退到标准 generate()。
        优势：
          - 引用精确到原文字符位置，而非块级 [来源N]
          - 结构化引用对象可直接用于前端高亮渲染
          - 无需在 prompt 里消耗 token 讲引用规则
        """
        from services.generator.llm_client import AnthropicLLMClient
        if not isinstance(self._llm, AnthropicLLMClient) or not chunks:
            return await self.generate(
                req=req, chunks=chunks,
                chat_history=chat_history,
                long_term_context=long_term_context,
                nlu_result=nlu_result,
            )

        trace_id = str(uuid.uuid4())[:8]
        start    = time.perf_counter()

        # 构建文档列表（优先使用父块内容）
        documents = [
            {
                "title":   chunk.metadata.title or chunk.doc_id,
                "content": chunk.parent_content or chunk.content,
            }
            for chunk in chunks
        ]

        # Citations 专用 system prompt（引用由 API 自动插入，无需在 prompt 里描述引用格式）
        citations_system = """\
你是严谨的企业级知识库问答助手。基于提供的文档内容回答问题。

<rules>
  1. 仅使用提供的文档内容作答，不引入外部知识或推断。
  2. 文档内容不足以回答时，明确说明："根据现有文档资料，无法准确回答此问题。"
  3. 不同文档出现矛盾时，如实指出并分别列出各方说法。
  4. 问题只有部分答案时，回答已知部分并说明哪些方面无法从现有资料确认。
  5. 回答简洁、准确、专业；系统会自动为你的陈述添加精确文献引用，无需手动标注。
</rules>
"""
        # 拼接对话历史 + 用户背景到 query 前面
        effective_history = chat_history if chat_history is not None else req.chat_history
        user_parts: list[str] = []
        if long_term_context:
            user_parts.append(f"<user_memory>\n{long_term_context}\n</user_memory>")
        if effective_history:
            turns = "\n".join(
                f"  <turn role='{'用户' if t.get('role')=='user' else '助手'}'>"
                f"{t.get('content','')}</turn>"
                for t in effective_history[-6:]
            )
            user_parts.append(f"<conversation_history>\n{turns}\n</conversation_history>")
        user_parts.append(req.query)
        full_query = "\n\n".join(user_parts)

        answer, citations = await self._llm.chat_with_citations(
            system=citations_system,
            documents=documents,
            query=full_query,
        )

        faithfulness = await estimate_faithfulness(answer, chunks, self._llm)
        elapsed_ms   = round((time.perf_counter() - start) * 1000, 1)

        logger.info(
            f"[Generate/Citations] DONE trace={trace_id} "
            f"latency={elapsed_ms}ms citations={len(citations)}"
        )
        return GenerationResponse(
            answer=answer,
            sources=chunks,
            session_id=req.session_id,
            query=req.query,
            latency_ms=elapsed_ms,
            faithfulness_score=faithfulness,
            trace_id=trace_id,
            model=settings.active_model,
            # 将结构化引用存入 extra_metadata（供前端使用）
            stage_latencies={"citations_count": len(citations)},
        )


_generator: GeneratorService | None = None


def get_generator() -> GeneratorService:
    global _generator
    if _generator is None:
        _generator = GeneratorService()
    return _generator
