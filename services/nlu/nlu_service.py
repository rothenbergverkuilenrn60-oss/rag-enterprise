# =============================================================================
# services/nlu/nlu_service.py
# 自然语言理解层
# 覆盖：意图分类 / 实体识别与消歧 / 查询分解 / 查询扩展重写 / 上下文感知
#
# 优化点：
#   1. Tool Use 替换 JSON 文本解析：_llm_analyze / _llm_rewrite 用 chat_with_tools()
#      → 100% 结构化输出，消除 split("\n") / re.search(JSON) 脆性
#   2. 模型分层：NLU/改写任务自动路由到 Haiku（task_type="nlu"/"rewrite"）
#   3. Extended Thinking：multi_hop 意图时调用 chat_thinking()，提升复杂推理质量
# =============================================================================
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import openai
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from config.settings import settings
from services.nlu.entity_disambiguator import get_disambiguator


# ══════════════════════════════════════════════════════════════════════════════
# 意图枚举
# ══════════════════════════════════════════════════════════════════════════════
class QueryIntent(str, Enum):
    FACTUAL       = "factual"        # 事实查询：「产假多少天」
    PROCEDURAL    = "procedural"     # 流程查询：「请假怎么申请」
    COMPARISON    = "comparison"     # 对比查询：「年假和病假有什么区别」
    DEFINITION    = "definition"     # 定义查询：「什么是试用期」
    CALCULATION   = "calculation"    # 计算查询：「工龄3年年假几天」
    MULTI_HOP     = "multi_hop"      # 多跳查询：「满足哪些条件可以申请带薪年假」
    AMBIGUOUS     = "ambiguous"      # 模糊查询：需要澄清
    CHITCHAT      = "chitchat"       # 闲聊：「你好」
    OUT_OF_SCOPE  = "out_of_scope"   # 超出知识库范围


# ══════════════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Entity:
    """识别出的命名实体。"""
    text:        str
    entity_type: str
    normalized:  str   = ""
    confidence:  float = 1.0
    start:       int   = 0
    end:         int   = 0


@dataclass
class SubQuery:
    """查询分解后的子问题。"""
    text:       str
    intent:     QueryIntent    = QueryIntent.FACTUAL
    entities:   list[Entity]   = field(default_factory=list)
    depends_on: list[int]      = field(default_factory=list)


@dataclass
class NLUResult:
    """NLU 完整解析结果，贯穿整个查询流水线。"""
    original_query:     str
    intent:             QueryIntent
    entities:           list[Entity]
    sub_queries:        list[SubQuery]
    rewritten_queries:  list[str]
    context_summary:    str  = ""
    needs_clarification: bool = False
    clarification_hint:  str  = ""
    tenant_id:           str  = ""
    user_id:             str  = ""
    language:            str  = "zh"


# ══════════════════════════════════════════════════════════════════════════════
# 规则引擎辅助（快速路径，无需 LLM）
# ══════════════════════════════════════════════════════════════════════════════
_CHITCHAT_PATTERNS = re.compile(
    r"^(你好|hello|hi|嗨|在吗|再见|谢谢|thanks|thank you|好的|明白了)[\?？!！。]*$",
    re.IGNORECASE,
)
_FACTUAL_KEYWORDS     = re.compile(r"多少|几天|几个月|几年|金额|标准|规定|条款|第.*条|是否|能不能|可以吗")
_PROCEDURAL_KEYWORDS  = re.compile(r"怎么|如何|流程|步骤|申请|办理|手续|需要什么|提交")
_COMPARISON_KEYWORDS  = re.compile(r"区别|不同|对比|vs|versus|相比|差异|有什么不一样")
_CALCULATION_KEYWORDS = re.compile(r"计算|算出|工龄.*年假|年假.*工龄|满.*年|几天.*假|假.*几天")

_NUMBER_NORM = {
    "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
    "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
    "百": "100", "千": "1000",
}


def _rule_based_intent(query: str) -> QueryIntent | None:
    """快速规则匹配意图，命中则跳过 LLM，提速约 300ms。"""
    if _CHITCHAT_PATTERNS.match(query.strip()):
        return QueryIntent.CHITCHAT
    if _COMPARISON_KEYWORDS.search(query):
        return QueryIntent.COMPARISON
    if _CALCULATION_KEYWORDS.search(query):
        return QueryIntent.CALCULATION
    if _PROCEDURAL_KEYWORDS.search(query):
        return QueryIntent.PROCEDURAL
    if _FACTUAL_KEYWORDS.search(query):
        return QueryIntent.FACTUAL
    return None


def _extract_entities_rule(query: str) -> list[Entity]:
    """基于正则的轻量实体抽取（数字、时间、金额、部门）。"""
    entities: list[Entity] = []

    for m in re.finditer(r"[一二三四五六七八九十百千\d]+\s*(天|个月|年|元|万元|小时|分钟)", query):
        text = m.group()
        norm = text
        for zh, num in _NUMBER_NORM.items():
            norm = norm.replace(zh, num)
        entities.append(Entity(text=text, entity_type="number",
                               normalized=norm, start=m.start(), end=m.end()))

    for m in re.finditer(
        r"(人事(行政)?部|财务部|总经理|部门主管|直属主管|HR|人力资源)", query
    ):
        entities.append(Entity(text=m.group(), entity_type="department",
                               start=m.start(), end=m.end()))

    for m in re.finditer(
        r"(年假|病假|事假|产假|陪产假|丧假|婚假|哺乳假|孕检假|工伤假|调休)", query
    ):
        entities.append(Entity(text=m.group(), entity_type="policy_term",
                               start=m.start(), end=m.end()))

    return entities


# ── BERT NER（HuggingFace fine-tuned，可选）────────────────────────────────
_ner_pipeline = None
_ner_available = False


def _init_bert_ner() -> None:
    """
    初始化 BERT NER 模型。
    模型路径由 settings.ner_model_path 配置（空字符串时跳过）。
    推荐模型：
      - 通用中文: hfl/chinese-bert-wwm-ext（需 fine-tune）
      - 开箱即用: shibing624/bert4ner-base-chinese
    """
    global _ner_pipeline, _ner_available
    model_path = getattr(settings, "ner_model_path", "")
    if not model_path:
        logger.info("[NER] BERT NER disabled (ner_model_path not set), using rule-based only")
        return
    try:
        from transformers import pipeline as hf_pipeline
        import torch
        device = 0 if torch.cuda.is_available() else -1
        _ner_pipeline = hf_pipeline(
            "ner",
            model=model_path,
            aggregation_strategy="simple",
            device=device,
        )
        _ner_available = True
        logger.info(f"[NER] BERT NER loaded: {model_path}")
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error("NLU service failure", stage="bert_ner_init", exc_info=exc)
        _ner_available = False


def _extract_entities_bert(query: str) -> list[Entity]:
    """
    BERT fine-tuned NER 实体抽取。
    标签映射：ORG→department, PER→person, LOC→location, MISC→policy_term
    降级：模型不可用时返回空列表，由调用方 merge 规则结果。
    """
    if not _ner_available or _ner_pipeline is None:
        return []
    try:
        results = _ner_pipeline(query)
        entities: list[Entity] = []
        _LABEL_MAP = {
            "ORG": "department", "PER": "person",
            "LOC": "location",   "MISC": "policy_term",
        }
        for r in results:
            label = _LABEL_MAP.get(r.get("entity_group", ""), r.get("entity_group", "misc"))
            entities.append(Entity(
                text=r["word"],
                entity_type=label,
                normalized=r["word"],
                confidence=round(float(r.get("score", 1.0)), 4),
                start=r.get("start", 0),
                end=r.get("end", 0),
            ))
        logger.debug(f"[NER] BERT extracted {len(entities)} entities from: {query[:50]}")
        return entities
    except (RuntimeError, ValueError) as exc:
        logger.error("NLU service failure", stage="bert_ner_inference", exc_info=exc)
        return []


def extract_entities(query: str) -> list[Entity]:
    """
    融合实体抽取：BERT NER（精准）+ 规则（高召回）去重合并。
    以 BERT 结果为主，规则结果补充 BERT 未覆盖的位置。
    """
    bert_entities = _extract_entities_bert(query)
    rule_entities = _extract_entities_rule(query)

    if not bert_entities:
        return rule_entities

    # 去重：规则实体与 BERT 实体重叠（字符位置）则丢弃规则结果
    covered_spans = {(e.start, e.end) for e in bert_entities}
    merged: list[Entity] = list(bert_entities)
    for re_ent in rule_entities:
        overlap = any(
            not (re_ent.end <= s or re_ent.start >= e)
            for s, e in covered_spans
        )
        if not overlap:
            merged.append(re_ent)

    merged.sort(key=lambda e: e.start)
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# Tool Use 定义（NLU 分析 + 查询改写）
# ══════════════════════════════════════════════════════════════════════════════
_NLU_TOOL = {
    "name": "analyze_query",
    "description": "分析用户查询的意图、实体和改写变体",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "factual", "procedural", "comparison", "definition",
                    "calculation", "multi_hop", "ambiguous", "chitchat", "out_of_scope",
                ],
                "description": "查询意图类型",
            },
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text":       {"type": "string"},
                        "type":       {"type": "string"},
                        "normalized": {"type": "string"},
                    },
                    "required": ["text", "type"],
                },
                "description": "识别到的命名实体",
            },
            "sub_queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "多跳问题拆解后的子问题列表，简单问题返回空列表",
            },
            "needs_clarification": {
                "type": "boolean",
                "description": "问题是否需要澄清",
            },
            "clarification_hint": {
                "type": "string",
                "description": "如需澄清，给出提示语；否则为空字符串",
            },
            "rewrite": {
                "type": "array",
                "items": {"type": "string"},
                "description": "改写后的查询变体列表（2-3 个）",
            },
        },
        "required": [
            "intent", "entities", "sub_queries",
            "needs_clarification", "clarification_hint", "rewrite",
        ],
    },
}

_REWRITE_TOOL = {
    "name": "generate_query_variants",
    "description": "为信息检索生成多个语义相近的查询变体，提升召回率",
    "input_schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "items": {"type": "string"},
                "description": "查询变体列表，每个变体都保持原始问题的语义",
            },
        },
        "required": ["variants"],
    },
}

# ── LLM Prompt（系统提示简化，结构化约束交给 Tool Use）─────────────────────
_NLU_SYSTEM = """\
你是企业内部知识库的查询理解引擎。
分析员工的查询问题，识别意图类型、提取关键实体（政策条款、假期类型、金额、时间、部门等），
并生成多个语义变体以提升检索召回率。
严格调用工具，以结构化格式输出分析结果，不输出解释文字。"""

_REWRITE_SYSTEM = """\
你是企业知识库检索专家，专门为内部政策/制度查询生成检索变体。
针对用户问题，生成多个语义等价但表达不同的查询变体：
- 展开口语化表达（如"产假"→"生育假期"、"调休"→"调休假期"）
- 替换指代词（如"这个"→具体政策名称、"它"→指代对象）
- 使用官方规范用词（如"年假"→"带薪年休假"）
- 从不同角度表达同一问题（条件式、结果式、程序式）
严格调用工具输出变体列表，不输出解释文字。"""

_HYDE_SYSTEM = """\
你是企业制度文件专家。根据员工的查询问题，生成一段假设性的官方制度条款原文（2-3句话）。

<requirements>
  - 使用正式的企业制度文件语言风格（"员工享有…"、"符合以下条件者…"）
  - 包含具体的数字、时间或条件（如"不超过X天"、"工龄满X年"）
  - 仿照制度条款格式书写，不用第一人称
  - 内容用于辅助向量相似度检索，无需与真实制度完全一致
</requirements>

只输出假设条款原文，不加任何说明或前缀。"""


# ══════════════════════════════════════════════════════════════════════════════
# LLM 辅助函数（Tool Use 版本 + Fallback）
# ══════════════════════════════════════════════════════════════════════════════
async def _llm_rewrite(query: str, llm_client, n: int = 3) -> list[str]:
    """多查询扩展重写：生成 n 个语义相近变体。

    优先用 Tool Use（Haiku 模型，保证 list 输出）；
    回退到文本解析（其他 provider）。
    """
    try:
        if getattr(llm_client, "supports_tools", False):
            # Tool Use 路径：100% 返回 list，无解析失败风险
            result = await llm_client.chat_with_tools(
                system=_REWRITE_SYSTEM,
                user=f"原始问题：{query}",
                tools=[_REWRITE_TOOL],
                task_type="rewrite",            # → Haiku 模型
            )
            variants = result.get("variants", [])
            return [v.strip() for v in variants if v.strip()][:n]
        else:
            # Fallback：文本解析（Ollama 等不支持 Tool Use 的后端）
            resp = await llm_client.chat(
                system=_REWRITE_SYSTEM,
                user=f"原始问题：{query}\n\n生成{n}个查询变体，每行一个，不加编号，不加解释。",
                temperature=0.4,
                task_type="rewrite",
            )
            variants = [l.strip() for l in resp.strip().split("\n") if l.strip()]
            return variants[:n]
    except openai.APIError as exc:
        logger.error("NLU service failure", stage="rewrite", exc_info=exc)
        return []


async def _llm_hyde(query: str, llm_client) -> str:
    """HyDE：生成假设性文档用于向量检索。"""
    try:
        return await llm_client.chat(
            system=_HYDE_SYSTEM,
            user=query,
            temperature=0.2,
            task_type="rewrite",                # → Haiku 模型
        )
    except openai.APIError as exc:
        logger.error("NLU service failure", stage="hyde", exc_info=exc)
        return query


async def build_quad_queries(
    query: str,
    llm_client,
    chat_history: list[dict] | None = None,
) -> dict[str, list[str]]:
    """四路混合检索查询构建。

    original  → 原始问题（用户原文）
    rewrite   → 扩展重写变体（3个，Tool Use 保证结构化）
    hyde      → 假设文档（1个，向量语义更强）
    context   → 融合对话历史的改写（如有历史则生成）
    """
    tasks = [_llm_rewrite(query, llm_client), _llm_hyde(query, llm_client)]

    if chat_history:
        history_str = "\n".join(
            f"{'用户' if t.get('role')=='user' else '助手'}：{t.get('content','')}"
            for t in chat_history[-4:]
        )
        tasks.append(llm_client.chat(
            system=(
                "根据对话历史，将用户当前问题改写为可独立理解的完整查询。"
                "补全省略的主语和指代词（如[它]/[这个]/[那条]等），保持原始意图不变。"
                "只输出改写后的问题，不加解释或前缀。"
            ),
            user=f"对话历史：\n{history_str}\n\n当前问题：{query}",
            temperature=0.1,
            task_type="rewrite",
        ))
    else:
        async def _identity() -> str:
            return query
        tasks.append(_identity())

    rewrite_variants, hyde_doc, context_query = await asyncio.gather(
        *tasks, return_exceptions=True
    )

    result = {
        "original": [query],
        "rewrite":  rewrite_variants if isinstance(rewrite_variants, list) else [],
        "hyde":     [hyde_doc]        if isinstance(hyde_doc, str)          else [query],
        "context":  [context_query]   if isinstance(context_query, str) and context_query != query else [],
    }
    total = sum(len(v) for v in result.values())
    logger.info(f"[NLU] QuadQuery built: {total} queries across 4 paths")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NLU Service 主类
# ══════════════════════════════════════════════════════════════════════════════
class NLUService:
    """
    查询理解服务，在检索之前运行。

    流程：
      1. 规则引擎快速路径（无需 LLM，< 1ms）
      2. 实体抽取（规则 + 可选 LLM 增强）
      3. 上下文感知（融合对话历史）
      4. 意图分类（规则未命中时调用 LLM）
         → Anthropic：Tool Use + Haiku，保证结构化 + 成本极低
         → multi_hop：Extended Thinking，复杂推理质量更高
      5. 查询分解（多跳问题拆解为子问题）
      6. 四路查询构建（原始 + 重写 + HyDE + 上下文）
    """

    def __init__(self) -> None:
        self._use_llm_nlu = getattr(settings, "nlu_llm_enabled", True)

    async def analyze(
        self,
        query: str,
        llm_client=None,
        chat_history: list[dict] | None = None,
        tenant_id: str = "",
        user_id:   str = "",
    ) -> NLUResult:

        # ── Step 1: 规则快速路径 + BERT NER ────────────────────────────────────
        rule_intent = _rule_based_intent(query)
        entities    = extract_entities(query)   # BERT NER + 规则融合

        if rule_intent == QueryIntent.CHITCHAT:
            return NLUResult(
                original_query=query,
                intent=QueryIntent.CHITCHAT,
                entities=entities,
                sub_queries=[],
                rewritten_queries=[query],
                tenant_id=tenant_id,
                user_id=user_id,
            )

        # ── Step 2: 上下文感知 ───────────────────────────────────────────────
        context_summary = ""
        if chat_history and llm_client:
            context_summary = await self._summarize_context(chat_history, llm_client)

        # ── Step 3: LLM 深度解析 ─────────────────────────────────────────────
        intent              = rule_intent or QueryIntent.FACTUAL
        sub_queries: list[SubQuery] = []
        needs_clarification = False
        clarification_hint  = ""

        if llm_client and self._use_llm_nlu and rule_intent is None:
            try:
                nlu_data = await self._llm_analyze(query, context_summary, llm_client)
                intent              = QueryIntent(nlu_data.get("intent", "factual"))
                needs_clarification = nlu_data.get("needs_clarification", False)
                clarification_hint  = nlu_data.get("clarification_hint", "")

                for e in nlu_data.get("entities", []):
                    if not any(ex.text == e.get("text") for ex in entities):
                        entities.append(Entity(
                            text=e.get("text", ""),
                            entity_type=e.get("type", "unknown"),
                            normalized=e.get("normalized", e.get("text", "")),
                        ))

                for sq_text in nlu_data.get("sub_queries", []):
                    if sq_text.strip():
                        sub_queries.append(SubQuery(text=sq_text.strip()))

            except openai.APIError as exc:
                logger.error("NLU service failure", stage="intent", exc_info=exc)

        # ── Step 4: 四路查询构建 ─────────────────────────────────────────────
        rewritten: list[str] = [query]
        if llm_client and not needs_clarification:
            quad = await build_quad_queries(query, llm_client, chat_history)
            rewritten = (
                quad["original"] + quad["rewrite"] + quad["hyde"] + quad["context"]
            )
            seen: set[str] = set()
            rewritten = [q for q in rewritten if q not in seen and not seen.add(q)]  # type: ignore

        # ── Step 5: 实体消歧 ─────────────────────────────────────────────────
        if entities and getattr(settings, "entity_disambiguation_enabled", True):
            try:
                disambiguator = get_disambiguator()
                disambiguated = disambiguator.disambiguate_batch(
                    entities, query, None, tenant_id
                )
                ambiguous = [d for d in disambiguated if d.needs_clarification]
                if ambiguous and not needs_clarification:
                    hint = disambiguator.build_clarification_hint(ambiguous)
                    if hint:
                        clarification_hint  = hint
                        needs_clarification = True
                        logger.debug(
                            f"[NLU] Entity disambiguation triggered clarification: "
                            f"{[d.original_text for d in ambiguous]}"
                        )
            except (RuntimeError, ValueError) as exc:
                logger.error("NLU service failure", stage="entity", exc_info=exc)

        result = NLUResult(
            original_query=query,
            intent=intent,
            entities=entities,
            sub_queries=sub_queries,
            rewritten_queries=rewritten,
            context_summary=context_summary,
            needs_clarification=needs_clarification,
            clarification_hint=clarification_hint,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        logger.info(
            f"[NLU] query='{query[:40]}' intent={intent} "
            f"entities={len(entities)} rewrites={len(rewritten)} "
            f"sub_queries={len(sub_queries)}"
        )
        return result

    @retry(stop=stop_after_attempt(2), wait=wait_random_exponential(multiplier=1, max=4))
    async def _llm_analyze(
        self, query: str, context: str, llm_client
    ) -> dict[str, Any]:
        """LLM 深度解析意图 + 实体 + 改写。

        优先用 Tool Use（Anthropic）：保证 JSON Schema 输出，无解析失败风险。
        回退到文本解析（其他 provider）：正则提取 JSON block。
        """
        user_msg = (
            f"<context>{context}</context>\n\n<query>{query}</query>"
            if context
            else f"<query>{query}</query>"
        )

        if getattr(llm_client, "supports_tools", False):
            # Tool Use 路径（Anthropic Haiku）
            result = await llm_client.chat_with_tools(
                system=_NLU_SYSTEM,
                user=user_msg,
                tools=[_NLU_TOOL],
                task_type="nlu",                # → Haiku 模型
            )
            if result:
                return result
            raise ValueError("Tool Use returned empty result")
        else:
            # Fallback：文本 + JSON 解析（不支持 Tool Use 的后端）
            resp = await llm_client.chat(
                system=_NLU_SYSTEM + "\n\n输出格式：只输出一个 JSON 对象，不加 markdown 代码块，不加任何解释文字。",
                user=user_msg,
                temperature=0.0,
                task_type="nlu",
            )
            m = re.search(r"\{.*\}", resp, re.DOTALL)
            if not m:
                raise ValueError("No JSON in NLU response")
            return json.loads(m.group())

    def recommend_top_k(self, intent: "QueryIntent", default: int) -> int:
        """根据查询意图推荐最优 top_k，动态调整检索宽度。"""
        if not getattr(settings, "dynamic_top_k_enabled", True):
            return default
        mapping = {
            QueryIntent.FACTUAL:     getattr(settings, "top_k_factual",     3),
            QueryIntent.PROCEDURAL:  getattr(settings, "top_k_procedural",  5),
            QueryIntent.COMPARISON:  getattr(settings, "top_k_comparison",  8),
            QueryIntent.MULTI_HOP:   getattr(settings, "top_k_multi_hop",  12),
            QueryIntent.CALCULATION: getattr(settings, "top_k_calculation", 5),
            QueryIntent.DEFINITION:  getattr(settings, "top_k_definition",  4),
        }
        recommended = mapping.get(intent, default)
        logger.debug(f"[NLU] dynamic top_k: intent={intent} → top_k={recommended}")
        return recommended

    async def _summarize_context(
        self, chat_history: list[dict], llm_client
    ) -> str:
        """提炼对话历史中的关键上下文。"""
        if len(chat_history) < 2:
            return ""
        try:
            history_str = "\n".join(
                f"{'用户' if t.get('role')=='user' else '助手'}：{t.get('content','')[:200]}"
                for t in chat_history[-6:]
            )
            return await llm_client.chat(
                system=(
                    "从对话历史中提炼1句关键背景信息，帮助理解当前问题的指代词和省略内容。"
                    "格式：用户正在询问[主题]，已了解[背景]。"
                    "只输出这一句，不加解释或其他内容。"
                ),
                user=history_str,
                temperature=0.0,
                task_type="nlu",                # → Haiku 模型
            )
        except openai.APIError as exc:
            logger.error("NLU service failure", stage="context_summary", exc_info=exc)
            return ""


# 单例
_nlu_service: NLUService | None = None


def get_nlu_service() -> NLUService:
    global _nlu_service
    if _nlu_service is None:
        _nlu_service = NLUService()
    return _nlu_service
