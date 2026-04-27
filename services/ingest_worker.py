"""ARQ worker module for async document ingestion.

Run worker:
    arq services.ingest_worker.WorkerSettings

Phase 5 — ASYNC-01, ASYNC-02. Status TTL = settings.arq_keep_result_sec (86400 = 24h).
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings
from loguru import logger

from config.settings import settings


async def ingest_task(ctx: dict[str, Any], req_data: dict[str, Any]) -> dict[str, Any]:
    """ARQ worker task — wraps IngestionPipeline.run().

    Args:
        ctx: ARQ-injected job metadata (job_id, enqueue_time, etc.). Not used directly.
        req_data: IngestionRequest.model_dump(mode='json') — JSON-serializable dict.

    Returns:
        dict with keys: doc_id, success, error, tenant_id. ARQ stores this in
        Redis at arq:result:{job_id} with TTL = WorkerSettings.keep_result.

    Raises:
        Any exception from IngestionPipeline.run(); ARQ catches and serializes
        the exception automatically. Do NOT add a broad except clause here
        (ERR-01 + breaks ARQ failure tracking — see RESEARCH.md pitfall 1).
    """
    # Lazy import to avoid circular imports at worker startup
    from services.pipeline import get_ingest_pipeline
    from utils.models import AsyncIngestRequest

    tenant_id = req_data.get("tenant_id", "")
    doc_id = req_data.get("doc_id", "")
    logger.info(f"[Worker:ingest] start doc_id={doc_id} tenant_id={tenant_id}")

    pipeline = get_ingest_pipeline()
    req = AsyncIngestRequest(**req_data)
    result = await pipeline.run(req)

    logger.info(
        f"[Worker:ingest] done doc_id={doc_id} tenant_id={tenant_id} "
        f"success={result.success}"
    )
    return {
        "doc_id": result.doc_id,
        "success": result.success,
        # SECURITY: result.error is the sanitized IngestionResponse field —
        # never propagate raw exception repr (could leak paths/secrets).
        # See threat T-05-09.
        "error": result.error,
        # tenant_id is needed by GET /ingest/status for cross-tenant 404 check
        # (see threat T-05-08 IDOR mitigation).
        "tenant_id": tenant_id,
    }


class WorkerSettings:
    """ARQ WorkerSettings — entry point for `arq services.ingest_worker.WorkerSettings`."""

    functions = [ingest_task]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    keep_result = settings.arq_keep_result_sec   # 86400 — ASYNC-02 24h TTL
    keep_result_forever = False
    job_timeout = settings.arq_job_timeout       # 300s
    max_jobs = 10
