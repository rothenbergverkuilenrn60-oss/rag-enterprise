# =============================================================================
# utils/metrics.py
# Prometheus 指标导出
# 需要：pip install prometheus-client
# 端点：GET /metrics（在 main.py 中注册）
# =============================================================================
from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        Counter, Histogram, Gauge,
        generate_latest, CONTENT_TYPE_LATEST, REGISTRY,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


class _NoopMetric:
    """prometheus_client 未安装时的空操作占位符，保持调用接口一致。"""
    def labels(self, **kw: Any) -> "_NoopMetric":
        return self
    def inc(self, n: float = 1) -> None:
        pass
    def observe(self, v: float) -> None:
        pass
    def set(self, v: float) -> None:
        pass


def _noop() -> _NoopMetric:
    return _NoopMetric()


if _PROMETHEUS_AVAILABLE:
    # ── 查询指标 ────────────────────────────────────────────────────────────
    query_total = Counter(
        "rag_queries_total",
        "Total RAG queries",
        ["intent", "tenant_id", "result"],          # result: success | error | blocked
    )
    query_latency_seconds = Histogram(
        "rag_query_latency_seconds",
        "End-to-end query latency in seconds",
        ["intent", "tenant_id"],
        buckets=[0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )
    faithfulness_histogram = Histogram(
        "rag_faithfulness_score",
        "Distribution of faithfulness scores",
        ["tenant_id"],
        buckets=[0.1, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )
    retrieval_chunks_histogram = Histogram(
        "rag_retrieval_chunks_per_query",
        "Number of chunks retrieved per query",
        buckets=[1, 3, 5, 8, 10, 15, 20],
    )

    # ── 摄取指标 ────────────────────────────────────────────────────────────
    ingest_total = Counter(
        "rag_ingest_total",
        "Total document ingestion attempts",
        ["doc_type", "result"],
    )
    ingest_chunks_histogram = Histogram(
        "rag_ingest_chunks_per_doc",
        "Chunks produced per ingested document",
        buckets=[5, 10, 25, 50, 100, 250, 500],
    )
    pii_detected_total = Counter(
        "rag_pii_detected_total",
        "Total PII items detected during ingestion",
        ["pii_type"],
    )

    # ── 检索阶段延迟（P50/P95/P99 分布）────────────────────────────────
    retrieval_latency_seconds = Histogram(
        "rag_retrieval_latency_seconds",
        "Per-stage retrieval latency in seconds (dense/sparse/rrf/rerank/total)",
        ["stage"],          # dense | sparse | rrf | rerank | total
        buckets=[0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
    )

    # ── 系统与质量指标 ────────────────────────────────────────────────────
    vector_store_size_gauge = Gauge(
        "rag_vector_store_size",
        "Total vectors in the primary collection",
    )
    cache_hit_total = Counter(
        "rag_cache_hits_total",
        "Query cache hit/miss counts",
        ["result"],     # hit | miss
    )
    rule_trigger_total = Counter(
        "rag_rule_triggers_total",
        "Rules engine trigger counts",
        ["stage", "action"],    # stage: pre_query/post_answer  action: ALLOW/BLOCK/MODIFY
    )
    llm_tokens_total = Counter(
        "rag_llm_tokens_estimated_total",
        "Estimated LLM tokens consumed (input+output combined)",
        ["provider", "model", "token_type"],   # token_type: input | output
    )
    llm_cost_usd_total = Counter(
        "rag_llm_cost_usd_total",
        "Estimated LLM cost in USD",
        ["provider", "model"],
    )
    auth_attempts_total = Counter(
        "rag_auth_attempts_total",
        "Authentication attempt counts",
        ["result"],     # success | failure
    )

    # ── HTTP 请求指标（由 main.py trace_middleware 填充）───────────────────
    http_requests_total = Counter(
        "rag_requests_total",
        "Total HTTP requests by method, endpoint, and status code",
        ["method", "endpoint", "status"],
    )
    active_requests_gauge = Gauge(
        "rag_active_requests",
        "Currently in-flight HTTP requests",
    )
    rate_limit_hits_total = Counter(
        "rag_rate_limit_hits_total",
        "Total requests rejected by rate limiter",
    )

    # ── LLM 调用延迟 ──────────────────────────────────────────────────────
    llm_latency_seconds = Histogram(
        "rag_llm_latency_seconds",
        "LLM call latency in seconds",
        ["provider"],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    )
else:
    query_total               = _noop()  # type: ignore[assignment]
    query_latency_seconds     = _noop()  # type: ignore[assignment]
    faithfulness_histogram    = _noop()  # type: ignore[assignment]
    retrieval_chunks_histogram = _noop() # type: ignore[assignment]
    ingest_total              = _noop()  # type: ignore[assignment]
    ingest_chunks_histogram   = _noop()  # type: ignore[assignment]
    pii_detected_total        = _noop()  # type: ignore[assignment]
    vector_store_size_gauge   = _noop()  # type: ignore[assignment]
    cache_hit_total           = _noop()  # type: ignore[assignment]
    rule_trigger_total        = _noop()  # type: ignore[assignment]
    llm_tokens_total          = _noop()  # type: ignore[assignment]
    llm_cost_usd_total        = _noop()  # type: ignore[assignment]
    auth_attempts_total       = _noop()  # type: ignore[assignment]
    retrieval_latency_seconds = _noop()  # type: ignore[assignment]
    http_requests_total       = _noop()  # type: ignore[assignment]
    active_requests_gauge     = _noop()  # type: ignore[assignment]
    rate_limit_hits_total     = _noop()  # type: ignore[assignment]
    llm_latency_seconds       = _noop()  # type: ignore[assignment]


def get_metrics_response() -> tuple[bytes, str]:
    """
    返回 Prometheus 文本格式的指标数据和 Content-Type。
    用于 GET /metrics 端点。
    """
    if _PROMETHEUS_AVAILABLE:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    return b"# prometheus_client not installed\n", "text/plain; charset=utf-8"
