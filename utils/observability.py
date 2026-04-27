# =============================================================================
# utils/observability.py
# 可观测性基础设施：Langfuse LLM 追踪 + OpenTelemetry 分布式 Span + 成本追踪
#
# 原问题：
#   langfuse_enabled / otel_enabled 默认 False，生产环境运行完全无 LLM 可观测性，
#   无法排查幻觉、延迟异常、成本超支等问题。
#
# 解决方案：
#   setup_observability() 在 main.py lifespan 中主动调用，
#   根据配置自动初始化 Langfuse / OTel；未配置时静默降级（不报错）。
#
# 功能：
#   1. Langfuse Tracing   — 每次 LLM 调用自动记录 prompt/response/token/cost
#   2. OTel Spans         — 分布式追踪，关联 RAG pipeline 各阶段耗时
#   3. Token 成本追踪      — Prometheus + Langfuse 双路上报，按 provider/model 分维度
#   4. record_llm_usage() — 供 llm_client.py 调用，统一上报 token 用量
# =============================================================================
from __future__ import annotations

import time
from typing import Any
from loguru import logger

# ── 全局状态（延迟初始化，避免启动失败阻塞主服务）───────────────────────────
_langfuse_client = None
_otel_tracer     = None
_initialized     = False

# Anthropic token 定价（美元 / 1M tokens，2024 年底价格，可在 .env 中覆盖）
_PRICE_PER_M_INPUT: dict[str, float] = {
    "claude-opus-4-6":          15.0,
    "claude-sonnet-4-6":         3.0,
    "claude-haiku-4-5-20251001": 0.25,
    "gpt-4o":                    5.0,
    "gpt-4o-mini":               0.15,
    "default":                   3.0,
}
_PRICE_PER_M_OUTPUT: dict[str, float] = {
    "claude-opus-4-6":          75.0,
    "claude-sonnet-4-6":        15.0,
    "claude-haiku-4-5-20251001": 1.25,
    "gpt-4o":                   15.0,
    "gpt-4o-mini":               0.60,
    "default":                  15.0,
}


def setup_observability() -> None:
    """在应用启动时调用，按配置初始化 Langfuse 和 OpenTelemetry。

    设计原则：
      - 配置缺失 → 静默跳过，不影响主服务启动
      - 初始化失败 → 记录警告，不抛异常
      - 支持 Langfuse Cloud 和自托管实例
    """
    global _initialized
    if _initialized:
        return

    _setup_langfuse()
    _setup_otel()
    _initialized = True
    logger.info("[Observability] Initialized")


def _setup_langfuse() -> None:
    """初始化 Langfuse LLM 可观测性客户端。

    Langfuse 提供：
      - 每次 LLM 调用的完整 prompt/response 记录
      - Token 用量和成本追踪
      - 用户会话追踪（session_id）
      - 评分 / 反馈关联
      - 自定义 trace 标签（tenant_id、intent 等）
    """
    global _langfuse_client
    try:
        from config.settings import settings
        if not getattr(settings, "langfuse_enabled", False):
            logger.info("[Observability] Langfuse disabled (langfuse_enabled=False)")
            return
        if not settings.langfuse_public_key or not settings.langfuse_secret_key:
            logger.warning("[Observability] Langfuse keys missing, skipping")
            return

        from langfuse import Langfuse
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info(f"[Observability] Langfuse connected: {settings.langfuse_host}")
    except ImportError:
        logger.warning("[Observability] langfuse not installed (pip install langfuse)")
    except Exception as exc:
        logger.warning(f"[Observability] Langfuse init failed: {exc}")


def _setup_otel() -> None:
    """初始化 OpenTelemetry 分布式追踪。

    OTel 提供：
      - RAG pipeline 各阶段的 Span（NLU / Retrieval / Generation / etc.）
      - 跨服务追踪（配合 X-Trace-ID header）
      - 与 Jaeger / Zipkin / Grafana Tempo 等后端集成
    """
    global _otel_tracer
    try:
        from config.settings import settings
        if not getattr(settings, "otel_enabled", False):
            logger.info("[Observability] OTel disabled (otel_enabled=False)")
            return
        if not getattr(settings, "otel_endpoint", ""):
            logger.warning("[Observability] OTel endpoint missing, skipping")
            return

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource(attributes={"service.name": settings.app_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _otel_tracer = trace.get_tracer(settings.app_name)
        logger.info(f"[Observability] OTel connected: {settings.otel_endpoint}")
    except ImportError:
        logger.warning("[Observability] opentelemetry not installed (pip install opentelemetry-sdk opentelemetry-exporter-otlp)")
    except Exception as exc:
        logger.warning(f"[Observability] OTel init failed: {exc}")


# ── 对外接口 ──────────────────────────────────────────────────────────────────

def record_llm_usage(
    provider: str,
    input_tokens: int,
    output_tokens: int,
    model: str = "",
    trace_id: str = "",
    session_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """记录 LLM token 用量：Prometheus + Langfuse 双路上报。

    由 llm_client.py 的 _report_usage() 调用。
    """
    # ── 成本估算 ──────────────────────────────────────────────────────────────
    model_key = model or provider
    price_in  = _PRICE_PER_M_INPUT.get(model_key,  _PRICE_PER_M_INPUT["default"])
    price_out = _PRICE_PER_M_OUTPUT.get(model_key, _PRICE_PER_M_OUTPUT["default"])
    cost_usd  = (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    logger.debug(
        f"[LLM Usage] provider={provider} model={model_key} "
        f"in={input_tokens} out={output_tokens} cost=${cost_usd:.6f}"
    )

    # ── Prometheus token 计数 + 成本指标 ─────────────────────────────────────
    try:
        from utils.metrics import llm_tokens_total, llm_cost_usd_total
        llm_tokens_total.labels(provider=provider, model=model_key, token_type="input").inc(input_tokens)
        llm_tokens_total.labels(provider=provider, model=model_key, token_type="output").inc(output_tokens)
        llm_cost_usd_total.labels(provider=provider, model=model_key).inc(cost_usd)
    except Exception:
        pass

    # ── Langfuse 记录 ─────────────────────────────────────────────────────────
    if _langfuse_client is None:
        return
    try:
        generation = _langfuse_client.generation(
            trace_id=trace_id or None,
            name=f"{provider}/{model_key}",
            model=model_key,
            usage={
                "input":           input_tokens,
                "output":          output_tokens,
                "total":           input_tokens + output_tokens,
                "input_cost":      input_tokens  * price_in  / 1_000_000,
                "output_cost":     output_tokens * price_out / 1_000_000,
                "total_cost":      cost_usd,
                "unit":            "TOKENS",
            },
            metadata=extra or {},
        )
        generation.end()
    except Exception as exc:
        logger.debug(f"[Observability] Langfuse record failed: {exc}")


def start_span(name: str, attributes: dict[str, Any] | None = None):
    """开启 OTel Span（上下文管理器）。未初始化时返回空 contextmanager。

    用法：with start_span("rag.retrieval", {"top_k": 10}): ...

    原实现的 bug：手动调用 __enter__ 设置 attributes 后，with 语句又调用一次
    __enter__，导致 span 被进入两次（double-entry），OTel 可能创建嵌套 span。
    修复：通过 start_as_current_span(attributes=...) 在创建时直接注入 attributes，
    返回的 context manager 由 with 语句统一管理入/出。
    """
    if _otel_tracer is None:
        from contextlib import nullcontext
        return nullcontext()
    # OTel SDK 接受 {str: AttributeValue} 格式；统一转为 str 保证兼容性
    otel_attrs = {k: str(v) for k, v in attributes.items()} if attributes else None
    return _otel_tracer.start_as_current_span(name, attributes=otel_attrs)


def flush() -> None:
    """应用关闭前 flush 所有缓冲数据。"""
    if _langfuse_client:
        try:
            _langfuse_client.flush()
            logger.info("[Observability] Langfuse flushed")
        except Exception as exc:
            logger.warning(f"[Observability] Langfuse flush failed: {exc}")
