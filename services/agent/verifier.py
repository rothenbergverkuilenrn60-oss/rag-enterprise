"""Verifier sub-agent (Phase 21 / AGENT-05).

Single-pass verifier reads N peer answers + their cited evidence chunks and
emits a structured ``VerifierVerdict``. Text-only ``BaseLLMClient.call_agentic_turn``
invocation (CF-03 — no tools). System prompt forbids inventing facts and
instructs same-language ``proposed_answer`` (Pitfall P-08 carry-forward from
Phase 20 P-11).

CF-04 forced-disagree applied INSIDE ``verify()`` (Pitfall P-02): when
``verdict=="agree"`` AND ``evidence_chunk_ids`` is empty, the returned object
has ``verdict`` overridden to ``"disagree"`` so callers see a truthful object
before ``SwarmQueryPipeline.run`` consumes it.

D-07: NO tenacity wrapper at this class level — ``BaseLLMClient.call_agentic_turn``
inherits provider-side retry already; layering compounds latency on bad-provider
days.

P-09: provider override at ``__init__`` time bypasses the ``get_llm_client()``
singleton (which can't re-resolve once cached), instantiating fresh
``AnthropicLLMClient()`` / ``OpenAILLMClient()`` when ``settings.verifier_provider``
is set; default branch reuses the shared singleton.
"""
from __future__ import annotations  # MANDATORY — makes ALL annotations lazy strings

import json
import re
import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import (
    ValidationError,  # noqa: F401  # re-exported for caller try/except clarity
)

from config.settings import settings
from services.generator.llm_client import (
    AnthropicLLMClient,
    BaseLLMClient,
    OpenAILLMClient,
    get_llm_client,
)
from utils.models import RetrievedChunk, VerifierVerdict

# RESEARCH Open Question Q1 RESOLVED — accept ``_SubAgentResult`` directly (no alias).
# Circular-import guard: ``services/pipeline.py`` imports ``Verifier`` at module
# top (Plan 21-05). If we ran ``from services.pipeline import _SubAgentResult``
# at runtime here, importing pipeline would trigger this module load → which
# would re-enter pipeline mid-load → ``ImportError``. The TYPE_CHECKING block
# resolves only during static type-checking (mypy/IDE); at runtime the import
# never runs. The string forward-ref annotation
# ``peer_results: "list[_SubAgentResult]"`` below works because
# ``from __future__ import annotations`` makes every annotation a deferred string.
if TYPE_CHECKING:
    from services.pipeline import _SubAgentResult


_VERIFIER_SYSTEM = """\
你是一个证据验证子代理。你的任务是审查 N 个对等子代理的回答，并基于它们引用的证据片段，判定它们是否一致并能由证据支撑。

输入说明：
- 用户原始查询（user_query）：你的最终答案必须使用与该查询相同的语言。
- N 个对等回答（peer_answers）：每个包含 answer 文本和该子代理使用过的 chunk_ids 列表。
- 证据列表（evidence）：N 个对等回答合并后去重的 RetrievedChunk 集合，每个 chunk 含 chunk_id 与 content。

判定规则（严格）：
1. 仅可引用 evidence 中已列出的 chunk_id。任何不在 evidence 中的 chunk_id 视为不存在。
2. 不得编造 evidence 中未出现的事实。如证据不足以回答，verdict 必须为 "disagree"，并在 reasoning 中说明缺失。
3. verdict="agree" 仅在以下条件成立时返回：所有对等回答在事实层面一致，且每个关键事实都能由 evidence 中至少一个 chunk 支撑。
4. verdict="disagree" 用于：对等回答相互矛盾、或某个对等回答缺乏证据支撑、或证据本身不足。
5. proposed_answer 字段始终必填（包括 verdict="agree"）。该字段是你给用户的最终答案，必须：
   - 使用与 user_query 相同的语言；
   - 简洁直接（建议不超过 4 段或 8 行）；
   - 仅基于 evidence 中已列出的 chunk 内容；
   - 在事实后用 [来源N] 形式引用，N 对应 evidence_chunk_ids 中的索引。
6. evidence_chunk_ids 列出你在 proposed_answer 中实际引用的 chunk_id 子集。可以为空，但 verdict="agree" 且为空将被系统强制改为 disagree。
7. reasoning 字段：1-2 句中文，说明判定依据。
8. latency_ms 由调用方填充，你可以输出任意 int（推荐填 0）。

输出格式（严格）：
仅输出一个 JSON 对象，无任何前缀、后缀、解释、markdown 代码块。Schema：
{
  "verdict": "agree" | "disagree",
  "evidence_chunk_ids": [string],
  "reasoning": string,
  "proposed_answer": string,
  "latency_ms": int
}
"""


class Verifier:
    """AGENT-05 verifier sub-agent — single-pass evidence verification.

    Per CONTEXT D-04, lives outside ``Synthesizer`` (no ``Synthesizer`` class
    extracted in v1.5; deferred to v1.6+). The class is instantiated once
    per ``SwarmQueryPipeline`` at ``__init__`` time (Open Question Q2 resolution).
    """

    def __init__(self) -> None:
        self._llm: BaseLLMClient = self._resolve_llm()

    @staticmethod
    def _resolve_llm() -> BaseLLMClient:
        """Pitfall P-09: bypass ``get_llm_client()`` singleton when
        ``verifier_provider`` is set so we don't accidentally route through
        the wrong provider's cached client.
        """
        if settings.verifier_provider == "anthropic":
            return AnthropicLLMClient()
        if settings.verifier_provider == "openai":
            return OpenAILLMClient()
        return get_llm_client()

    async def verify(
        self,
        *,
        peer_results: "list[_SubAgentResult]",   # forward-ref string; resolves under TYPE_CHECKING only
        evidence: list[RetrievedChunk],
        user_query: str,
    ) -> VerifierVerdict:
        """Run a single-pass verifier LLM call; return parsed VerifierVerdict.

        Raises:
            ValueError: if the LLM output contains no ``{...}`` JSON block or
                ``json.loads`` fails (Pattern 6).
            pydantic.ValidationError: if the parsed JSON does not match the
                ``VerifierVerdict`` schema (e.g. missing required field).
            BaseException: anything the underlying LLM client raises propagates;
                D-06 catch lives at ``SwarmQueryPipeline.run`` (Plan 21-05).
        """
        user_prompt = self._build_prompt(user_query, peer_results, evidence)

        t0 = time.perf_counter()
        turn = await self._llm.call_agentic_turn(
            messages=[{"role": "user", "content": user_prompt}],
            tools=[],                              # CF-03 — text-only
            system=_VERIFIER_SYSTEM,
            max_tokens=settings.llm_max_tokens,
            parallel_tool_calls=False,             # CF-09 explicit; text-only
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        verdict = self._parse(turn.text, evidence)
        # Override LLM-emitted latency_ms with the measured wall-clock value.
        verdict = verdict.model_copy(update={"latency_ms": latency_ms})

        # CF-04 forced-disagree (Pitfall P-02 — override INSIDE Verifier so
        # the returned object is truthful before SwarmQueryPipeline.run sees it).
        if verdict.verdict == "agree" and not verdict.evidence_chunk_ids:
            verdict = verdict.model_copy(update={"verdict": "disagree"})
        return verdict

    @staticmethod
    def _build_prompt(
        user_query: str,
        peer_results: "list[_SubAgentResult]",   # forward-ref string; resolves under TYPE_CHECKING only
        evidence: list[RetrievedChunk],
    ) -> str:
        """Format the verifier user-prompt: query + N peer answers + dedup evidence list."""
        lines: list[str] = [f"user_query: {user_query}", "", "peer_answers:"]
        for i, pr in enumerate(peer_results):
            cited = [c.chunk_id for c in pr.chunks]
            lines.append(f"  [{i}] answer: {pr.answer}")
            lines.append(f"      cited_chunk_ids: {cited}")
        lines.append("")
        lines.append("evidence (deduped, applied by caller before invoking verify):")
        for c in evidence:
            lines.append(f"  - chunk_id={c.chunk_id} | content={c.content[:200]}")
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str, evidence: list[RetrievedChunk]) -> VerifierVerdict:
        """Pattern 6 — extract first ``{...}`` block, parse JSON, defensively
        filter ``evidence_chunk_ids`` against the supplied evidence set, and
        validate against ``VerifierVerdict``.

        Raises ``ValueError`` on parse failures; ``pydantic.ValidationError``
        on shape mismatch. Caller (``SwarmQueryPipeline.run``) catches both
        via D-06's ``except BaseException``.
        """
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match is None:
            raise ValueError(f"verifier returned no JSON object; raw={raw[:200]!r}")
        try:
            parsed: dict[str, Any] = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"verifier JSON parse failed: {exc!r}") from exc

        # Defensive filter (Claude's-discretion bullet) — drop chunk_ids not
        # in the supplied evidence set. Mirrors the set-membership filter
        # spirit of services/pipeline.py:1050-1059 dedup.
        valid_ids = {c.chunk_id for c in evidence}
        raw_ids = parsed.get("evidence_chunk_ids", [])
        filtered = [cid for cid in raw_ids if cid in valid_ids]
        dropped = len(raw_ids) - len(filtered)
        if dropped > 0:
            logger.warning(f"[Verifier] dropped {dropped} chunk_id(s) not in supplied evidence")
        parsed["evidence_chunk_ids"] = filtered
        return VerifierVerdict.model_validate(parsed)
