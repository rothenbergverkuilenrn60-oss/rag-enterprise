# =============================================================================
# services/rules/rules_engine.py
# 规则引擎：在检索和生成之前/之后执行业务规则
# 覆盖：前置规则（查询过滤）/ 后置规则（答案后处理）/ 质量校验
# =============================================================================
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Awaitable

from loguru import logger


class RuleAction(str, Enum):
    PASS     = "pass"      # 放行
    BLOCK    = "block"     # 拦截（返回固定回复）
    REDIRECT = "redirect"  # 重定向到其他意图
    MODIFY   = "modify"    # 修改查询/答案


@dataclass
class RuleResult:
    action:   RuleAction
    message:  str   = ""    # BLOCK 时的回复内容
    modified: str   = ""    # MODIFY 时的新内容
    rule_id:  str   = ""


# ── 规则类型 ─────────────────────────────────────────────────────────────────
class Rule(ABC):
    """Abstract base class for all rules. Subclasses MUST implement check()."""

    def __init__(
        self,
        rule_id: str,
        description: str,
        stage: str,
        priority: int = 100,
        enabled: bool = True,
    ) -> None:
        self.rule_id = rule_id
        self.description = description
        self.stage = stage
        self.priority = priority
        self.enabled = enabled

    @abstractmethod
    def check(self, context: dict[str, Any]) -> RuleResult:
        """Execute this rule against the given context. Must return a RuleResult."""
        ...


# ── 内置规则示例 ──────────────────────────────────────────────────────────────
class PromptInjectionRule(Rule):
    """
    Prompt 注入攻击检测与拦截。

    覆盖的攻击类型：
      1. 直接指令注入：试图覆盖系统 prompt（"忽略之前的指令"）
      2. 角色扮演越狱：要求模型扮演没有限制的角色（DAN / 开发者模式）
      3. 分隔符注入：通过插入 <|im_end|> 等特殊 token 截断对话
      4. 编码绕过：base64 / unicode 逃逸指令
      5. 间接注入：通过 URL / 文件路径指向外部恶意内容
    """

    # 中英文 prompt 注入特征
    _INJECTION_PATTERNS = re.compile(
        r"(ignore\s+(all\s+)?(previous|above|prior)\s+instructions?"
        r"|forget\s+(everything|all|your|the)\s*(above|previous|instructions?|rules?)"
        r"|you\s+are\s+now\s+(DAN|an?\s+AI\s+without\s+restrictions?|jailbreak)"
        r"|act\s+as\s+(if\s+you\s+have\s+no\s+limits?|a\s+?different\s+AI)"
        r"|developer\s+mode|jailbreak\s+mode|do\s+anything\s+now"
        r"|忽略(所有|之前|前面|上面)(的)?(指令|限制|规则|约束|系统提示)"
        r"|你现在是(一个没有限制|DAN|无限制版本)"
        r"|扮演一个(没有道德|无限制|不受约束)"
        r"|system\s*prompt|<\s*system\s*>|<\s*/\s*system\s*>"
        r"|<\|im_(start|end|sep)\|>"           # ChatML 分隔符注入
        r"|\[INST\]|\[/INST\]|\[SYS\]"         # Llama 格式分隔符
        r"|###\s*(Instruction|System|Human|Assistant)\s*:"  # 提示格式注入
        r")",
        re.IGNORECASE | re.UNICODE,
    )

    # 可疑的编码绕过（长 base64 块或 unicode 转义序列）
    _ENCODING_BYPASS = re.compile(
        r"([A-Za-z0-9+/]{60,}={0,2})"  # base64 block > 60 chars
        r"|(\\u[0-9a-fA-F]{4}){5,}",   # 5+ consecutive unicode escapes
    )

    # URL 间接注入（外部指令加载）
    _URL_INJECTION = re.compile(
        r"(https?://|ftp://|file://)\S+\.(txt|md|json|py|sh|ps1)",
        re.IGNORECASE,
    )

    def check(self, ctx: dict) -> RuleResult:
        query = ctx.get("query", "")

        if self._INJECTION_PATTERNS.search(query):
            logger.warning(f"[Security] Prompt injection detected: {query[:100]!r}")
            return RuleResult(
                action=RuleAction.BLOCK,
                message="输入包含不允许的指令模式，已被安全策略拦截。",
                rule_id=self.rule_id,
            )

        if self._ENCODING_BYPASS.search(query):
            logger.warning(f"[Security] Encoding bypass attempt detected")
            return RuleResult(
                action=RuleAction.BLOCK,
                message="输入包含异常编码内容，已被安全策略拦截。",
                rule_id=self.rule_id,
            )

        if self._URL_INJECTION.search(query):
            logger.warning(f"[Security] URL injection attempt detected")
            return RuleResult(
                action=RuleAction.BLOCK,
                message="输入包含外部资源引用，已被安全策略拦截。",
                rule_id=self.rule_id,
            )

        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class InputSanitizationRule(Rule):
    """
    输入净化：清除查询中的 HTML/JS 注入、SQL 注入特征。
    不拦截，而是 MODIFY（原地净化后放行）。
    """
    _HTML_TAGS   = re.compile(r"<[^>]{1,200}>")
    _SQL_PATTERN = re.compile(
        r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC|xp_|sp_)\b",
        re.IGNORECASE,
    )

    def check(self, ctx: dict) -> RuleResult:
        query = ctx.get("query", "")
        cleaned = self._HTML_TAGS.sub("", query)
        if self._SQL_PATTERN.search(cleaned):
            # SQL 关键词出现在查询中可能是合法的（如询问数据库问题），
            # 仅记录告警，不拦截
            logger.info(f"[Security] SQL keywords in query (non-blocking): {cleaned[:80]!r}")
        if cleaned != query:
            return RuleResult(
                action=RuleAction.MODIFY,
                modified=cleaned.strip(),
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class LLMOutputSafetyRule(Rule):
    """
    LLM 输出安全检查：拦截包含系统信息泄露迹象的回答。
    防止模型被诱导输出 system prompt 或内部配置。
    """
    _LEAK_PATTERNS = re.compile(
        r"(my\s+system\s+prompt\s+is|you\s+are\s+an?\s+AI\s+assistant\s+called"
        r"|here\s+is\s+my\s+(system|instruction)\s+prompt"
        r"|系统提示词(是|为|如下)|我的(系统|初始)指令(是|如下))",
        re.IGNORECASE | re.UNICODE,
    )

    def check(self, ctx: dict) -> RuleResult:
        answer = ctx.get("answer", "")
        if self._LEAK_PATTERNS.search(answer):
            logger.warning("[Security] Potential system prompt leak in LLM output, blocking")
            return RuleResult(
                action=RuleAction.BLOCK,
                message="系统检测到异常输出，已拦截。请重新提问。",
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class SensitiveContentRule(Rule):
    """拦截包含敏感词的查询。"""
    _SENSITIVE = re.compile(r"(竞争对手|薪资泄露|违规操作|内部价格)")

    def check(self, ctx: dict) -> RuleResult:
        query = ctx.get("query", "")
        if self._SENSITIVE.search(query):
            return RuleResult(
                action=RuleAction.BLOCK,
                message="抱歉，该问题涉及敏感内容，无法回答。请联系人事行政部获取帮助。",
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class OutOfScopeRule(Rule):
    """超出知识库范围时给出引导。"""
    _OOS_PATTERNS = re.compile(r"(股票|投资理财|医疗诊断|法律诉讼|天气预报)")

    def check(self, ctx: dict) -> RuleResult:
        query = ctx.get("query", "")
        if self._OOS_PATTERNS.search(query):
            return RuleResult(
                action=RuleAction.BLOCK,
                message="该问题超出企业知识库的范围，建议通过专业渠道咨询。",
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class AnswerQualityRule(Rule):
    """答案质量检查：过短或不包含来源标注时降级处理。"""

    def check(self, ctx: dict) -> RuleResult:
        answer = ctx.get("answer", "")
        sources = ctx.get("sources", [])
        if len(answer) < 20:
            return RuleResult(
                action=RuleAction.MODIFY,
                modified="根据现有资料，暂未找到与该问题相关的具体条款，建议直接咨询人事行政部。",
                rule_id=self.rule_id,
            )
        if sources and "[来源" not in answer:
            # 答案没有标注来源，在末尾补充
            source_note = "\n\n（以上信息来源于企业内部制度文件，如有疑问请以最新版本为准）"
            return RuleResult(
                action=RuleAction.MODIFY,
                modified=answer + source_note,
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


class FaithfulnessRule(Rule):
    """忠实度过低时给出免责声明。"""
    _THRESHOLD = 0.4

    def check(self, ctx: dict) -> RuleResult:
        score = ctx.get("faithfulness_score", 1.0)
        if score < self._THRESHOLD:
            answer = ctx.get("answer", "")
            disclaimer = "\n\n⚠️ 注意：以上回答的置信度较低，建议核实原始文件或咨询相关部门。"
            return RuleResult(
                action=RuleAction.MODIFY,
                modified=answer + disclaimer,
                rule_id=self.rule_id,
            )
        return RuleResult(action=RuleAction.PASS, rule_id=self.rule_id)


# ══════════════════════════════════════════════════════════════════════════════
# 规则引擎
# ══════════════════════════════════════════════════════════════════════════════
class RulesEngine:
    """
    规则引擎：在各阶段对查询/答案执行业务规则。

    stage 说明：
      pre_query      在检索之前运行（过滤、拦截、重定向）
      post_answer    在生成答案之后运行（修改、免责、质量注入）
      quality_check  在答案返回前运行（忠实度、来源标注检查）
    """

    def __init__(self) -> None:
        self._rules: list[Rule] = []
        self._register_builtin_rules()

    def _register_builtin_rules(self) -> None:
        # ── 安全规则（最高优先级，最先执行）──────────────────────────────────
        self.add(PromptInjectionRule(
            rule_id="S001", description="Prompt 注入攻击检测", stage="pre_query", priority=1,
        ))
        self.add(InputSanitizationRule(
            rule_id="S002", description="输入净化（HTML/XSS）", stage="pre_query", priority=2,
        ))
        self.add(LLMOutputSafetyRule(
            rule_id="S003", description="LLM输出安全（防泄露）", stage="post_answer", priority=1,
        ))
        # ── 业务规则 ──────────────────────────────────────────────────────────
        self.add(SensitiveContentRule(
            rule_id="R001", description="敏感内容过滤", stage="pre_query", priority=10,
        ))
        self.add(OutOfScopeRule(
            rule_id="R002", description="超范围引导", stage="pre_query", priority=20,
        ))
        self.add(AnswerQualityRule(
            rule_id="R003", description="答案质量检查", stage="post_answer", priority=10,
        ))
        self.add(FaithfulnessRule(
            rule_id="R004", description="忠实度校验", stage="quality_check", priority=20,
        ))

    def add(self, rule: Rule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def remove(self, rule_id: str) -> None:
        self._rules = [r for r in self._rules if r.rule_id != rule_id]

    def run(self, stage: str, context: dict[str, Any]) -> RuleResult:
        """
        执行指定阶段的所有规则，返回第一个非 PASS 结果。
        全部通过则返回 PASS。
        """
        for rule in self._rules:
            if rule.rule_id != stage and rule.stage != stage:
                continue
            if not rule.enabled:
                continue
            result = rule.check(context)
            if result.action != RuleAction.PASS:
                logger.info(
                    f"[RulesEngine] stage={stage} rule={rule.rule_id} "
                    f"action={result.action}"
                )
                return result
        return RuleResult(action=RuleAction.PASS)


_rules_engine: RulesEngine | None = None

def get_rules_engine() -> RulesEngine:
    global _rules_engine
    if _rules_engine is None:
        _rules_engine = RulesEngine()
    return _rules_engine
