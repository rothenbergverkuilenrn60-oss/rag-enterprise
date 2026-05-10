# =============================================================================
# services/generator/llm_client.py
# STAGE 6a — LLM 客户端
# 支持：Ollama(本地) / OpenAI / Anthropic  |  流式 + 非流式
#
# Anthropic 专项优化：
#   - Prompt Caching：system prompt 自动加 cache_control，降低 60-90% Token 成本
#   - 模型分层：task_type 参数按任务路由到 Haiku / Sonnet / Opus
#       nlu / rewrite / evaluate → claude-haiku-4-5（快速、低成本）
#       generate（默认）         → settings.anthropic_model（Sonnet）
#       thinking                 → settings.anthropic_model（支持 Extended Thinking）
#   - Tool Use：chat_with_tools() 保证结构化 JSON 输出，消除字符串解析脆性
#   - Extended Thinking：chat_thinking() 用于多跳推理
#   - 错误分类：RateLimitError / OverloadedError 精确处理
# =============================================================================
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, ClassVar

import httpx
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from config.settings import settings
from utils.models import AgenticTurn


# ══════════════════════════════════════════════════════════════════════════════
# Token 用量上报（Prometheus + Langfuse）
# ══════════════════════════════════════════════════════════════════════════════
def _report_usage(response: Any, provider: str, model: str = "") -> None:
    """从 API 响应中提取 token 用量并上报到 Prometheus + Langfuse。

    model 参数用于精确成本核算（如区分 Haiku vs Sonnet vs Opus 的定价）。
    未传入时降级为按 provider 默认价格，成本估算会偏差。
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens  = getattr(usage, "input_tokens",  0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        total = input_tokens + output_tokens
        if total <= 0:
            return
        from utils.metrics import llm_tokens_total
        llm_tokens_total.labels(provider=provider).inc(total)
        # Langfuse 精确成本上报（传入 model 名称，匹配定价表）
        try:
            from utils.observability import record_llm_usage
            record_llm_usage(provider, input_tokens, output_tokens, model=model)
        except Exception:
            pass
    except Exception:
        pass


# ── Anthropic 专用错误类型（导入时延迟，避免未安装时崩溃）──────────────────
_anthropic_rate_limit_cls: type | None = None
_anthropic_overload_cls:   type | None = None


def _get_anthropic_retry_errors() -> tuple[type, ...]:
    global _anthropic_rate_limit_cls, _anthropic_overload_cls
    if _anthropic_rate_limit_cls is None:
        try:
            from anthropic import OverloadedError, RateLimitError
            _anthropic_rate_limit_cls = RateLimitError
            _anthropic_overload_cls   = OverloadedError
        except ImportError:
            _anthropic_rate_limit_cls = Exception
            _anthropic_overload_cls   = Exception
    return (_anthropic_rate_limit_cls, _anthropic_overload_cls)


# ══════════════════════════════════════════════════════════════════════════════
# Task type → Anthropic 模型映射
# ══════════════════════════════════════════════════════════════════════════════
# 模型分层策略：轻量任务用 Haiku（快 3-5 倍，成本 1/15），生成用 Sonnet
_HAIKU_MODEL  = "claude-haiku-4-5-20251001"


def _anthropic_model_for_task(task_type: str, default_model: str) -> str:
    """按任务类型选择 Anthropic 模型。

    轻量任务（毫秒级、无需深度推理）→ Haiku（速度快 3-5x，成本约 1/15）
    生成/推理任务 → 默认模型（Sonnet/Opus，由 settings.anthropic_model 决定）

    task_type 新增 "classify"（意图分类单独场景）→ Haiku
    """
    light_tasks = {"nlu", "rewrite", "evaluate", "summarize", "chitchat", "classify"}
    if task_type in light_tasks:
        return _HAIKU_MODEL
    return default_model  # generate / thinking / default → Sonnet/Opus（由配置决定）


def _translate_tool_result_message(
    message: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Translate Anthropic-shape tool_result message to OpenAI tool-message shape.

    v1.4.2 — fixes Groq/DeepSeek/Qwen HTTP 400 on iter≥2 of agent tool-use loop.

    Project convention (per pipeline.py:816 + Anthropic API): tool results are
    packed into a single ``user`` role message with ``content`` as a list of
    ``{type:"tool_result", tool_use_id, content}`` blocks.

    OpenAI Chat Completions API requires one ``{role:"tool", tool_call_id,
    content:str}`` message per tool result. Strict OpenAI-compat servers
    (Groq, DeepSeek, Qwen via DashScope) reject the Anthropic shape with::

        400 - "messages.N.content.0.type": value is not one of the allowed
              values ['text', 'image_url', 'document']

    Returns:
        ``None`` if the message is not an Anthropic tool_result wrapper —
        caller passes it through unchanged.
        A list of OpenAI tool messages (one per ``tool_result`` block) if the
        message IS a tool_result wrapper. Each output message has the shape::

            {"role": "tool", "tool_call_id": <str>, "content": <str>}

        Per OpenAI spec, ``content`` must be a string. If the inbound block's
        ``content`` is itself a list (Anthropic content blocks), the textual
        parts are joined; non-text blocks are stringified to their JSON.
    """
    if message.get("role") != "user":
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    if not all(
        isinstance(b, dict) and b.get("type") == "tool_result"
        for b in content
    ):
        return None

    out: list[dict[str, Any]] = []
    for block in content:
        tool_use_id = block.get("tool_use_id") or block.get("id") or ""
        block_content = block.get("content", "")
        if isinstance(block_content, str):
            text = block_content
        elif isinstance(block_content, list):
            parts: list[str] = []
            for inner in block_content:
                if isinstance(inner, dict) and inner.get("type") == "text":
                    parts.append(str(inner.get("text", "")))
                else:
                    parts.append(json.dumps(inner, ensure_ascii=False))
            text = "\n".join(parts)
        else:
            text = json.dumps(block_content, ensure_ascii=False)
        out.append({
            "role":         "tool",
            "tool_call_id": tool_use_id,
            "content":      text,
        })
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Abstract Base
# ══════════════════════════════════════════════════════════════════════════════
class BaseLLMClient(ABC):
    """所有 LLM 客户端的基类。

    子类必须实现 chat() 和 stream_chat()。
    chat_with_tools() 和 chat_thinking() 是可选扩展，默认回退到普通 chat()。
    """

    provider_name: ClassVar[str] = "anthropic"  # default; subclasses override

    @abstractmethod
    async def chat(
        self, system: str, user: str,
        temperature: float = 0.1,
        task_type: str = "generate",
    ) -> str: ...

    @abstractmethod
    async def stream_chat(
        self, system: str, user: str, temperature: float = 0.1
    ) -> AsyncGenerator[str, None]: ...

    async def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        task_type: str = "nlu",
    ) -> dict[str, Any]:
        """Tool Use 接口：保证结构化 JSON 输出。
        默认实现：回退到普通 chat() + JSON 解析（兼容不支持 Tool Use 的后端）。
        """
        import re
        resp = await self.chat(system=system, user=user, temperature=0.0, task_type=task_type)
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {}

    async def chat_thinking(
        self,
        system: str,
        user: str,
        budget_tokens: int = 8000,
    ) -> str:
        """Extended Thinking 接口（复杂推理）。
        默认实现：回退到普通 chat()。
        """
        return await self.chat(system=system, user=user, temperature=0.1, task_type="thinking")

    async def call_agentic_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        max_tokens: int = 1024,
        parallel_tool_calls: bool = True,
    ) -> AgenticTurn:
        """Provider-neutral single-turn agentic call (AGENT-01).

        Returns one ``AgenticTurn`` containing text content + zero-or-more
        ``ToolCall`` entries + a ``stop_reason``. Adapters override to absorb
        provider-specific wire formats (Anthropic ``tool_use`` blocks, OpenAI
        ``tool_calls`` array). The pipeline (``AgentQueryPipeline.run``) drives
        the multi-turn loop on top of this single-turn primitive.

        Default implementation raises ``NotImplementedError``. Providers that
        do not support tool-use (e.g. ``OllamaLLMClient`` — pending agentic
        backend in v1.3) inherit this default. The pipeline catches the
        ``NotImplementedError`` and falls back to ``QueryPipeline`` with a
        structured-log warning (D-03).
        """
        raise NotImplementedError(
            f"agent_mode not supported by {self.__class__.__name__}"
        )

    @property
    def supports_tools(self) -> bool:
        """是否原生支持 Tool Use（返回结构化 JSON）。"""
        return False

    @property
    def supports_thinking(self) -> bool:
        """是否支持 Extended Thinking。"""
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Ollama Client（默认，WSL2 本地部署）
# ══════════════════════════════════════════════════════════════════════════════
class OllamaLLMClient(BaseLLMClient):
    provider_name: ClassVar[str] = "openai"  # Ollama uses OpenAI-compatible tool format (RESEARCH A3)

    def __init__(self) -> None:
        self._base  = settings.ollama_base_url
        self._model = settings.ollama_model
        self._client = httpx.AsyncClient(timeout=settings.request_timeout_sec)
        logger.info(f"OllamaLLMClient: model={self._model} base={self._base}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logging.getLogger("tenacity"), logging.WARNING),
    )
    async def chat(
        self, system: str, user: str,
        temperature: float = 0.1,
        task_type: str = "generate",
    ) -> str:
        resp = await self._client.post(
            f"{self._base}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "options": {
                    "temperature": temperature,
                    "num_predict": settings.llm_max_tokens,
                },
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def stream_chat(
        self, system: str, user: str, temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        async with self._client.stream(
            "POST",
            f"{self._base}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "options": {"temperature": temperature},
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if token := data.get("message", {}).get("content", ""):
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


# ══════════════════════════════════════════════════════════════════════════════
# OpenAI Client
# ══════════════════════════════════════════════════════════════════════════════
class OpenAILLMClient(BaseLLMClient):
    provider_name: ClassVar[str] = "openai"

    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        self._model  = settings.openai_model
        logger.info(f"OpenAILLMClient: model={self._model} base_url={settings.openai_base_url or 'official'}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10))
    async def chat(
        self, system: str, user: str,
        temperature: float = 0.1,
        task_type: str = "generate",
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=settings.llm_max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def stream_chat(
        self, system: str, user: str, temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=settings.llm_max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if delta := chunk.choices[0].delta.content:
                yield delta

    async def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        task_type: str = "nlu",
    ) -> dict[str, Any]:
        """OpenAI function calling 实现。"""
        functions = [
            {"name": t["name"], "description": t["description"],
             "parameters": t["input_schema"]}
            for t in tools
        ]
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            functions=functions,
            function_call={"name": tools[0]["name"]},
            temperature=0.0,
        )
        msg = resp.choices[0].message
        if msg.function_call:
            try:
                return json.loads(msg.function_call.arguments)
            except json.JSONDecodeError:
                pass
        return {}

    async def chat_with_vision(
        self,
        system: str,
        image_b64: str,
        query: str,
        media_type: str = "image/png",
        task_type: str = "generate",
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
                        },
                        {"type": "text", "text": query},
                    ],
                },
            ],
            max_tokens=settings.llm_max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def call_agentic_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        max_tokens: int = 1024,
        parallel_tool_calls: bool = True,
    ) -> AgenticTurn:
        """OpenAI implementation of the provider-neutral agentic turn (AGENT-01).

        Wire mapping:
          - Project's tools list uses Anthropic shape ``{name, description,
            input_schema}``; this method converts to OpenAI shape
            ``{type:"function", function:{name, description, parameters}}``.
          - OpenAI returns ``choices[0].message.tool_calls[i].function.arguments``
            as a JSON-encoded STRING; this method ``json.loads``-decodes it
            into ``ToolCall.arguments`` dict.
          - finish_reason: ``stop`` → ``"text_only"``; ``tool_calls`` →
            ``"tool_use"``; ``length`` → ``"max_tokens"``; anything else →
            ``"error"`` (gotcha #6 mapping table — locked).
          - System prompt: OpenAI Chat Completions does not have a separate
            ``system=`` kwarg; it is the first message with ``role="system"``.
            The caller's ``messages`` list is assumed to NOT already contain a
            system message — this method prepends one.

        ``parallel_tool_calls=True`` is set explicitly per AGENT-02 acceptance
        #2 (default is True on OpenAI side; explicit makes the contract
        auditable).
        """
        # Local import avoids a circular at module load.
        from utils.models import ToolCall

        # Convert tools from project's Anthropic-shape to OpenAI-shape.
        openai_tools: list[dict[str, Any]] = []
        for t in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name":        t["name"],
                    "description": t["description"],
                    "parameters":  t.get("input_schema", t.get("parameters", {})),
                },
            })

        # OpenAI puts system in the messages list, not a separate kwarg.
        full_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # Translate Anthropic-shape tool_result messages to OpenAI tool-message
        # shape (v1.4.2): pipeline.py emits {role:"user", content:[{type:"tool_result",
        # tool_use_id, content}]} per project convention; OpenAI Chat Completions
        # requires {role:"tool", tool_call_id, content:str} — one message per result.
        # Strict OpenAI-compat servers (Groq, DeepSeek, Qwen) reject the
        # Anthropic shape with HTTP 400 ("content type tool_result not allowed").
        for m in messages:
            translated = _translate_tool_result_message(m)
            if translated is None:
                full_messages.append(m)
            else:
                full_messages.extend(translated)

        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            tools=openai_tools,
            parallel_tool_calls=parallel_tool_calls,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        _report_usage(resp, "openai", model=self._model)

        choice = resp.choices[0]
        msg    = choice.message

        # Parse tool calls (may be None / missing on text-only responses).
        tool_calls: list[ToolCall] = []
        raw_tool_calls_for_msg: list[dict[str, Any]] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                logger.warning(
                    f"[OpenAI] tool_call arguments not valid JSON: "
                    f"{tc.function.arguments!r}"
                )
                args = {}
            tool_calls.append(ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=args,
            ))
            raw_tool_calls_for_msg.append({
                "id":   tc.id,
                "type": "function",
                "function": {
                    "name":      tc.function.name,
                    # Keep STRING shape for next-turn replay — OpenAI's
                    # documented contract is `arguments` is a JSON string.
                    "arguments": tc.function.arguments,
                },
            })

        # Map finish_reason (gotcha #6 — locked).
        finish = getattr(choice, "finish_reason", None)
        stop_reason: str
        if finish == "stop":
            stop_reason = "text_only"
        elif finish == "tool_calls":
            stop_reason = "tool_use"
        elif finish == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "error"

        # raw_assistant_msg: pipeline appends this verbatim before tool result
        # messages.
        raw_assistant_msg: dict[str, Any] = {
            "role":    "assistant",
            "content": msg.content,                                  # may be None for tool-only responses
        }
        if raw_tool_calls_for_msg:
            raw_assistant_msg["tool_calls"] = raw_tool_calls_for_msg

        # OpenAI's `usage` field uses `prompt_tokens` / `completion_tokens`
        # (NOT Anthropic's `input_tokens` / `output_tokens`). We normalize.
        usage = getattr(resp, "usage", None)
        return AgenticTurn(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=stop_reason,                                 # type: ignore[arg-type]
            raw_assistant_msg=raw_assistant_msg,
            usage_input_tokens=getattr(usage, "prompt_tokens",     0) or 0,
            usage_output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    @property
    def supports_tools(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
# Anthropic Client — 带 Prompt Caching / 模型分层 / Tool Use / Extended Thinking
# ══════════════════════════════════════════════════════════════════════════════
class AnthropicLLMClient(BaseLLMClient):
    """
    Anthropic Claude 客户端。

    核心优化：
      1. Prompt Caching   — system prompt 自动标记 cache_control，命中后成本 -90%
      2. 模型分层          — task_type 参数决定使用 Haiku（轻量）或 Sonnet（生成）
      3. Tool Use         — chat_with_tools() 保证结构化输出，消除字符串解析脆性
      4. Extended Thinking — chat_thinking() 用于多跳推理，逐步分析复杂问题
      5. 错误分类          — RateLimitError / OverloadedError 分开处理
    """

    provider_name: ClassVar[str] = "anthropic"

    def __init__(self) -> None:
        import anthropic
        self._client       = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._default_model = settings.anthropic_model
        logger.info(f"AnthropicLLMClient: default_model={self._default_model}")

    def _model_for(self, task_type: str) -> str:
        return _anthropic_model_for_task(task_type, self._default_model)

    def _cached_system(self, system: str) -> list[dict]:
        """将 system prompt 包装为带 cache_control 的消息格式。
        Anthropic Prompt Caching：相同 prefix 首次计费，后续命中缓存成本降 90%。
        """
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        task_type: str = "generate",
    ) -> str:
        model = self._model_for(task_type)
        try:
            msg = await self._client.messages.create(
                model=model,
                max_tokens=settings.llm_max_tokens,
                system=self._cached_system(system),   # ← Prompt Caching
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
            )
            _report_usage(msg, "anthropic", model=model)
            # 参考 claude-code：stop_reason=max_tokens 说明回答被截断，记录警告
            if getattr(msg, "stop_reason", None) == "max_tokens":
                logger.warning(
                    f"[Anthropic] Response truncated (max_tokens={settings.llm_max_tokens}): "
                    f"model={model} task={task_type}"
                )
            texts = [b.text for b in msg.content if b.type == "text"]
            return "\n".join(texts) if texts else ""
        except Exception as exc:
            return await self._handle_error(exc, system, user, temperature, task_type)

    async def stream_chat(
        self, system: str, user: str, temperature: float = 0.1
    ) -> AsyncGenerator[str, None]:
        # 参考 claude-code withRetry.ts：SDK 在流式传输中有时无法正确传递 529 状态码，
        # 需要检查 error.message 中是否包含 '"type":"overloaded_error"' 来识别过载错误。
        # 流式传输出错时降级为非流式调用，保证响应完整性。
        try:
            async with self._client.messages.stream(
                model=self._model_for("generate"),
                max_tokens=settings.llm_max_tokens,
                system=self._cached_system(system),       # ← Prompt Caching
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            err_str = str(exc)
            # 识别流式过载错误（SDK 有时不传递 529 状态码，需检查消息内容）
            is_overloaded = (
                '"type":"overloaded_error"' in err_str
                or (hasattr(exc, "status_code") and exc.status_code == 529)
            )
            if is_overloaded:
                logger.warning("[Anthropic] Stream overloaded, falling back to non-streaming")
                import asyncio
                await asyncio.sleep(5)
                # 降级：非流式调用，整体返回
                fallback = await self.chat(system=system, user=user, temperature=temperature)
                yield fallback
            else:
                raise

    async def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        task_type: str = "nlu",
    ) -> dict[str, Any]:
        """Tool Use：强制模型调用指定工具，返回 JSON Schema 验证后的结构化数据。

        优势：
          - 100% 结构化输出，无需正则解析、无 JSON 解析失败风险
          - Haiku 模型处理 NLU/改写任务，成本约为 Sonnet 的 1/15
          - system prompt 自动缓存，重复调用成本趋近于 0
        """
        model = self._model_for(task_type)
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=1024,
                system=self._cached_system(system),
                tools=tools,
                tool_choice={"type": "any"},           # 强制调用工具（不允许纯文本回复）
                messages=[{"role": "user", "content": user}],
                temperature=0.0,                       # 结构化输出不需要随机性
            )
            for block in resp.content:
                if block.type == "tool_use":
                    return block.input                 # type: ignore[return-value]
            logger.warning("[AnthropicClient] chat_with_tools: no tool_use block in response")
            return {}
        except Exception as exc:
            logger.error(f"[AnthropicClient] chat_with_tools failed: {exc}")
            return {}

    async def call_agentic_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        max_tokens: int = 1024,
        parallel_tool_calls: bool = True,
    ) -> AgenticTurn:
        """Anthropic implementation of the provider-neutral agentic turn (AGENT-01).

        Wire mapping:
          - Anthropic content block ``{type:"tool_use", id, name, input}`` →
            ``ToolCall(id, name, arguments=input)``
          - Anthropic content block ``{type:"text", text}`` concatenated into
            ``AgenticTurn.text``
          - stop_reason: ``end_turn`` / ``stop_sequence`` → ``"text_only"``;
            ``tool_use`` → ``"tool_use"``; ``max_tokens`` → ``"max_tokens"``;
            anything else → ``"error"`` (gotcha #6 mapping table — locked).

        ``disable_parallel_tool_use`` is set explicitly per AGENT-02 acceptance
        #2 (default is False on Anthropic side; explicit makes the contract
        auditable). The caller's ``parallel_tool_calls`` flag is the project's
        provider-neutral name; on Anthropic's wire format the equivalent is
        the inverse-named ``disable_parallel_tool_use``.

        Preserves Prompt Caching via ``self._cached_system(system)``.
        Preserves token-usage metrics via ``_report_usage(resp, "anthropic", ...)``.
        """
        # Local import avoids a circular at module load (utils.models is
        # already imported at module top, but ToolCall is only needed here).
        from utils.models import ToolCall

        model = self._default_model
        # disable_parallel_tool_use is the OPPOSITE of the parallel_tool_calls
        # flag — caller passes parallel_tool_calls=True meaning "I want
        # parallelism", which maps to disable_parallel_tool_use=False on
        # Anthropic's wire format.
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=self._cached_system(system),                # Prompt Caching preserved
            tools=tools,
            messages=messages,
            disable_parallel_tool_use=(not parallel_tool_calls),
        )
        _report_usage(resp, "anthropic", model=model)

        # Parse content blocks
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=dict(block.input) if block.input else {},
                ))

        # Map stop_reason (gotcha #6 — locked)
        raw_stop = getattr(resp, "stop_reason", None)
        stop_reason: str
        if raw_stop in ("end_turn", "stop_sequence"):
            stop_reason = "text_only"
        elif raw_stop == "tool_use":
            stop_reason = "tool_use"
        elif raw_stop == "max_tokens":
            stop_reason = "max_tokens"
        else:
            stop_reason = "error"

        # raw_assistant_msg: pipeline appends this verbatim to next-turn
        # messages list. Anthropic shape:
        #     {"role": "assistant", "content": <list of content blocks>}
        # We serialize blocks to plain dicts so the pipeline can JSON-round-trip
        # if needed; the SDK accepts both block objects and dicts on subsequent
        # calls.
        raw_blocks: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                raw_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                raw_blocks.append({
                    "type":  "tool_use",
                    "id":    block.id,
                    "name":  block.name,
                    "input": dict(block.input) if block.input else {},
                })

        usage = getattr(resp, "usage", None)
        return AgenticTurn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,                            # type: ignore[arg-type]
            raw_assistant_msg={"role": "assistant", "content": raw_blocks},
            usage_input_tokens=getattr(usage, "input_tokens", 0) or 0,
            usage_output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )

    async def chat_with_citations(
        self,
        system: str,
        documents: list[dict],
        query: str,
    ) -> tuple[str, list[dict]]:
        """Anthropic 原生 Citations API。

        将文档以 document block 形式传入，Claude 自动生成精确的字符级引用。
        相比手动 [来源N]：
          - 引用精确到原文字符位置（start_char_index / end_char_index）
          - 结构化引用对象，前端可直接渲染原文高亮
          - 无需在 prompt 里消耗 token 描述引用规则

        documents: [{"title": str, "content": str}]
        返回: (answer_text, citations_list)
        """
        content_blocks: list[dict] = []
        for doc in documents:
            content_blocks.append({
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": "text/plain",
                    "data": doc["content"],
                },
                "title": doc.get("title", ""),
                "citations": {"enabled": True},
            })
        content_blocks.append({"type": "text", "text": query})

        resp = await self._client.messages.create(
            model=self._default_model,
            max_tokens=settings.llm_max_tokens,
            system=self._cached_system(system),
            messages=[{"role": "user", "content": content_blocks}],
        )

        answer_parts: list[str] = []
        all_citations: list[dict] = []
        for block in resp.content:
            if block.type == "text":
                answer_parts.append(block.text)
                for cit in getattr(block, "citations", None) or []:
                    all_citations.append({
                        "cited_text":       getattr(cit, "cited_text",       ""),
                        "document_index":   getattr(cit, "document_index",    0),
                        "document_title":   getattr(cit, "document_title",   ""),
                        "start_char_index": getattr(cit, "start_char_index",  0),
                        "end_char_index":   getattr(cit, "end_char_index",    0),
                    })

        _report_usage(resp, "anthropic", model=self._default_model)
        return "".join(answer_parts), all_citations

    async def chat_with_vision(
        self,
        system: str,
        image_b64: str,
        query: str,
        media_type: str = "image/png",
        task_type: str = "generate",
    ) -> str:
        """Vision API：传入 Base64 图像，让 Claude 理解并提取内容。

        适用场景：扫描件 PDF（替代 OCR）、含图表的报告、手写文档识别。
        """
        model = self._model_for(task_type)
        resp = await self._client.messages.create(
            model=model,
            max_tokens=settings.llm_max_tokens,
            system=self._cached_system(system),
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": query},
                ],
            }],
        )
        _report_usage(resp, "anthropic", model=model)
        return resp.content[0].text if resp.content else ""

    async def chat_thinking(
        self,
        system: str,
        user: str,
        budget_tokens: int = 8000,
    ) -> str:
        """Extended Thinking：适用于多跳推理、复杂比较等需要逐步分析的问题。

        Claude 会先生成不可见的思维链（thinking blocks），再输出最终答案。

        模型能力分层：
          - claude-sonnet-4-6 / claude-opus-4-6 → { type: "adaptive" }
            由模型自动决定 thinking 深度，比固定 budget 更高效
          - 其他（Haiku / 旧版 Sonnet）→ { type: "enabled", budget_tokens: N }
            显式指定 thinking 预算，兼容不支持 adaptive 的模型

        注意：Extended Thinking 要求 temperature=1（API 限制）。
        """
        model = self._default_model
        _adaptive_models = ("sonnet-4-6", "opus-4-6")
        supports_adaptive = any(m in model for m in _adaptive_models)
        thinking_config = (
            {"type": "adaptive"}
            if supports_adaptive
            else {"type": "enabled", "budget_tokens": budget_tokens}
        )
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=budget_tokens + 2048,
                thinking=thinking_config,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=1,                         # Extended Thinking 强制要求
            )
            # content 包含 thinking blocks（内部推理）和 text blocks（最终答案）
            # 只返回 text blocks，thinking blocks 不对外暴露
            texts = [b.text for b in resp.content if b.type == "text"]
            _report_usage(resp, "anthropic", model=model)
            return "\n".join(texts) if texts else ""
        except Exception as exc:
            logger.warning(f"[AnthropicClient] chat_thinking failed, fallback to chat: {exc}")
            return await self.chat(system=system, user=user, temperature=0.7, task_type="thinking")

    async def _handle_error(
        self, exc: Exception,
        system: str, user: str, temperature: float, task_type: str,
    ) -> str:
        """分类处理 Anthropic API 错误。"""
        import asyncio
        import re
        try:
            from anthropic import (
                APIStatusError,
                BadRequestError,
                OverloadedError,
                RateLimitError,
            )
            if isinstance(exc, RateLimitError):
                # 读取 Retry-After header，精确等待而非盲目指数退避
                retry_after = 60
                if hasattr(exc, "response") and exc.response:
                    retry_after = int(exc.response.headers.get("retry-after", 60))
                logger.warning(f"[Anthropic] Rate limited, waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self.chat(system, user, temperature, task_type)
            if isinstance(exc, OverloadedError):
                # 服务过载：等待后降级到 Haiku 重试
                logger.warning("[Anthropic] Service overloaded, retry with Haiku")
                await asyncio.sleep(5)
                msg = await self._client.messages.create(
                    model=_HAIKU_MODEL,
                    max_tokens=settings.llm_max_tokens,
                    system=self._cached_system(system),
                    messages=[{"role": "user", "content": user}],
                    temperature=temperature,
                )
                return msg.content[0].text
            if isinstance(exc, APIStatusError) and exc.status_code == 529:
                logger.warning("[Anthropic] API overloaded (529), retry after 10s")
                await asyncio.sleep(10)
                return await self.chat(system, user, temperature, task_type)
            # Context window overflow: "input length and `max_tokens` exceed context limit: X + Y > Z"
            # 参考 claude-code withRetry.ts：解析 token 计数，自动缩减 max_tokens 重试一次
            if isinstance(exc, BadRequestError):
                msg_text = getattr(exc, "message", "") or str(exc)
                m = re.search(
                    r"input length and `max_tokens` exceed context limit:\s*(\d+)\s*\+\s*(\d+)\s*>\s*(\d+)",
                    msg_text, re.IGNORECASE,
                )
                if m:
                    input_tokens  = int(m.group(1))
                    context_limit = int(m.group(3))
                    safety_buffer = 1000
                    adjusted = max(512, context_limit - input_tokens - safety_buffer)
                    logger.warning(
                        f"[Anthropic] Context overflow: input={input_tokens} limit={context_limit} "
                        f"→ adjusting max_tokens to {adjusted}"
                    )
                    model = self._model_for(task_type)
                    resp = await self._client.messages.create(
                        model=model,
                        max_tokens=adjusted,
                        system=self._cached_system(system),
                        messages=[{"role": "user", "content": user}],
                        temperature=temperature,
                    )
                    _report_usage(resp, "anthropic", model=model)
                    return resp.content[0].text
        except ImportError:
            pass
        # 其他错误直接上抛
        raise exc

    @property
    def supports_tools(self) -> bool:
        return True

    @property
    def supports_thinking(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════
_llm_instance: BaseLLMClient | None = None


def get_llm_client() -> BaseLLMClient:
    global _llm_instance
    if _llm_instance is None:
        provider = settings.llm_provider
        if provider == "ollama":
            _llm_instance = OllamaLLMClient()
        elif provider == "openai":
            _llm_instance = OpenAILLMClient()
        elif provider == "anthropic":
            _llm_instance = AnthropicLLMClient()
        elif provider == "azure":
            # Azure OpenAI 复用 OpenAI 客户端（openai SDK 原生支持 azure_endpoint）
            from openai import AsyncAzureOpenAI
            azure_client = OpenAILLMClient.__new__(OpenAILLMClient)
            azure_client._client = AsyncAzureOpenAI(
                api_key=settings.openai_api_key,
                azure_endpoint=getattr(settings, "azure_openai_endpoint", ""),
                api_version=getattr(settings, "azure_openai_api_version", "2024-02-01"),
            )
            azure_client._model = getattr(settings, "azure_openai_deployment", settings.openai_model)
            _llm_instance = azure_client
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        logger.info(f"LLM factory: provider={provider}")
    return _llm_instance
