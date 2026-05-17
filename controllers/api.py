# =============================================================================
# controllers/api.py
# FastAPI Controller — 全局中间件 + 异常拦截 + 路由
# =============================================================================
import re
import uuid

import asyncpg
import httpx
import openai
import redis
import tenacity
from arq.jobs import Job, JobStatus
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from config.settings import settings
from services.auth.oidc_auth import AuthenticatedUser, get_current_user
from services.pipeline import (
    get_agent_pipeline,
    get_ingest_pipeline,
    get_query_pipeline,
    get_swarm_pipeline,  # AGENT-03
)
from utils.cache import cache_invalidate
from utils.models import (
    APIResponse,
    AsyncIngestRequest,
    FeedbackRequest,
    GenerationRequest,
    GenerationResponse,
    IngestionRequest,
    IngestionResponse,
)

# Per-route rate limiter (per D-07: decorators enforce tiered policy independently of global middleware)
_limiter = Limiter(key_func=get_remote_address, default_limits=[])
limiter = _limiter  # exported for main.py: app.state.limiter = limiter

#创建路由组，prefix='/api/v1'。这个路由下所有接口都自动加上这个前缀
router = APIRouter(prefix=settings.api_prefix)


# ══════════════════════════════════════════════════════════════════════════════
# Health & Info
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/health", tags=["system"])     # tags 用于 Swagger 文档分组显示
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.environment,
        "llm_provider": settings.llm_provider,
        "vector_store": settings.vector_store,
        "embedding_provider": settings.embedding_provider,
    }


@router.get("/readiness", tags=["system"])     # K8s 就绪探针接口，检查依赖服务是否可用
async def readiness() -> dict:
    """K8s readiness probe — 检查依赖连通性。"""
    checks: dict[str, str] = {}
    # Redis
    try:
        from utils.cache import get_redis
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except redis.RedisError as e:
        checks["redis"] = f"error: {e}"
    # VectorStore
    try:
        from services.vectorizer.vector_store import get_vector_store
        count = await get_vector_store().count()
        checks["vector_store"] = f"ok ({count} vectors)"
    except asyncpg.PostgresError as e:
        checks["vector_store"] = f"error: {e}"

    all_ok = all("ok" in v for v in checks.values())    # 生成器表达式：检查所有依赖的状态值都包含 'ok' 字符串
    return {"ready": all_ok, "checks": checks}


# ══════════════════════════════════════════════════════════════════════════════
# Ingestion（摄取：STAGE 1-4）
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/ingest", response_model=APIResponse, tags=["ingestion"])      # response_model:校验返回值是否符合 APIResponse 模型，FastAPI 自动转换为 JSON 格式
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest(request: Request, req: IngestionRequest) -> APIResponse:
    """
    摄取文档（同步）。
    大文件建议调用 /ingest/async，走后台任务队列。
    """
    trace_id = str(uuid.uuid4())[:8]
    try:
        pipeline = get_ingest_pipeline()
        result: IngestionResponse = await pipeline.run(req)
        if not result.success and result.error not in ("Duplicate document skipped",):
            raise HTTPException(status_code=422, detail=result.error)
        return APIResponse(
            success=result.success,
            data=result.model_dump(),
            trace_id=trace_id,
        )
    except HTTPException:
        raise
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error(f"[API:ingest] trace={trace_id} error={exc}")
        raise HTTPException(status_code=500, detail="文档摄取失败，请稍后重试")


@router.post("/ingest/async", response_model=APIResponse, status_code=202, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_async(
    request: Request,
    req: AsyncIngestRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    """Async ingest: return 202 + task_id immediately, ARQ processes in background.

    ASYNC-01: response in <200ms regardless of doc size.
    """
    try:
        arq_redis = request.app.state.arq_redis
        job = await arq_redis.enqueue_job(
            "ingest_task",
            req.model_dump(mode="json"),
        )
        if job is None:
            raise HTTPException(status_code=503, detail="Task queue dedup conflict; retry")
        task_id = job.job_id
        logger.info(f"[API:ingest_async] task_id={task_id} doc_id={req.doc_id} tenant={current_user.tenant_id}")
        return APIResponse(
            success=True,
            data={"task_id": task_id, "status": "queued"},
            trace_id=task_id,
        )
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.error(f"[API:ingest_async] redis error={exc}")
        raise HTTPException(status_code=503, detail="Task queue temporarily unavailable")


# Alphanumeric task_id + dashes (ARQ UUIDs, test IDs, human-readable IDs all accepted)
# Rejects injection chars: quotes, spaces, semicolons, slashes (T-05-10)
_TASK_ID_RE = re.compile(r"[a-zA-Z0-9\-]{4,}")


@router.get("/ingest/status/{task_id}", response_model=APIResponse, tags=["ingestion"])
async def ingest_status(
    task_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    """Poll async ingest task status.

    ASYNC-02: returns {status, error} or 404 after 24h TTL.
    Cross-tenant access returns 404 (not 403) to prevent enumeration.
    """
    if not _TASK_ID_RE.fullmatch(task_id):
        raise HTTPException(status_code=400, detail="Invalid task_id format")
    try:
        arq_redis = request.app.state.arq_redis
        job = Job(task_id, arq_redis)
        info = await job.info()
        if info is None:
            raise HTTPException(status_code=404, detail="Task not found or expired")
        result_dict = info.result if isinstance(info.result, dict) else {}
        result_tenant = result_dict.get("tenant_id")
        if result_tenant and result_tenant != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Task not found or expired")
        status_map = {
            JobStatus.queued:      "pending",
            JobStatus.deferred:    "pending",
            JobStatus.in_progress: "pending",
            JobStatus.complete:    "complete",
            JobStatus.not_found:   "not_found",
        }
        job_status = await job.status()
        status_str = status_map.get(job_status, "pending")
        error_detail: str | None = None
        if not info.success:
            error_detail = result_dict.get("error")
            status_str = "failed"
        return APIResponse(
            success=True,
            data={"task_id": task_id, "status": status_str, "error": error_detail},
        )
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.error(f"[API:ingest_status] task_id={task_id} redis error={exc}")
        raise HTTPException(status_code=503, detail="Status query temporarily unavailable")


_ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv",
                        ".txt", ".md", ".html", ".htm", ".json"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB hard cap


@router.post("/ingest/upload", response_model=APIResponse, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_upload(
    request: Request,
    file: UploadFile = File(...),
    doc_id: str | None = None,
    tenant_id: str = "",
    force: bool = False,
) -> APIResponse:
    """Browser file upload → save to data_dir → run synchronous IngestionPipeline.

    Returns the same shape as POST /ingest. For large files prefer
    POST /ingest/async (text-only, but no synchronous wait).
    """
    import pathlib
    from uuid import uuid4

    trace_id = str(uuid.uuid4())[:8]
    fname = file.filename or "upload"
    suffix = pathlib.Path(fname).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(_ALLOWED_UPLOAD_EXTS)}",
        )

    data_dir = pathlib.Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / f"upload_{uuid4().hex}{suffix}"

    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1 << 20):  # 1 MB chunks
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (>{_MAX_UPLOAD_BYTES // (1024*1024)} MB)",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        logger.error(f"[API:ingest_upload] trace={trace_id} write error={exc}")
        raise HTTPException(status_code=500, detail="File save failed")

    logger.info(f"[API:ingest_upload] trace={trace_id} saved {fname} ({size}B) → {target}")

    from utils.models import IngestionRequest
    req = IngestionRequest(
        file_path=str(target),
        doc_id=doc_id or pathlib.Path(fname).stem,
        metadata={"tenant_id": tenant_id, "original_filename": fname},
        force=force,
    )
    try:
        pipeline = get_ingest_pipeline()
        result = await pipeline.run(req)
        return APIResponse(
            success=result.success,
            data={
                **result.model_dump(),
                "stored_at": str(target),
                "original_filename": fname,
                "size_bytes": size,
            },
            error=result.error,
            trace_id=trace_id,
        )
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error(f"[API:ingest_upload] trace={trace_id} pipeline error={exc}")
        raise HTTPException(status_code=500, detail="文档摄取失败，请稍后重试")


# ══════════════════════════════════════════════════════════════════════════════
# Query（检索 + 生成：STAGE 5-6）
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/query", response_model=APIResponse, tags=["query"])
@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")
async def query(request: Request, req: GenerationRequest) -> APIResponse:
    """非流式 RAG 查询。非流式用于后台任务、批处理、长文本生成"""
    trace_id = str(uuid.uuid4())[:8]
    try:
        # AGENT-03 三向路由：swarm_mode > agent_mode > 默认 QueryPipeline
        if req.swarm_mode:
            pipeline = get_swarm_pipeline()
        elif req.agent_mode:
            pipeline = get_agent_pipeline()
        else:
            pipeline = get_query_pipeline()
        result: GenerationResponse = await pipeline.run(req)
        data = result.model_dump(mode="json")
        if not req.include_images:
            for src in data.get("sources", []):
                meta = src.get("metadata")
                if isinstance(meta, dict) and meta.get("image_b64"):
                    meta["image_b64"] = ""
        return APIResponse(
            success=True,
            data=data,
            trace_id=result.trace_id or trace_id,
        )
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error(f"[API:query] trace={trace_id} error={exc}")
        raise HTTPException(status_code=500, detail="查询处理失败，请稍后重试")


@router.post("/query/stream", tags=["query"])
@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")
async def query_stream(request: Request, req: GenerationRequest) -> StreamingResponse:
    """流式 SSE 查询。"""
    pipeline = get_query_pipeline()

    async def _sse():
        try:
            async for token in pipeline.stream(req):
                yield f"data: {token}\n\n"  # SSE 协议格式：每条数据以 'data: ' 开头，两个换行结束。浏览器 EventSource 自动解析
            yield "data: [DONE]\n\n"        # 发送结束信号，前端收到 [DONE] 知道流式传输结束
        except (
            asyncpg.PostgresError,
            httpx.HTTPError,
            openai.APIError,
            tenacity.RetryError,
            ValueError,
        ) as exc:
            cause = exc.last_attempt.exception() if isinstance(exc, tenacity.RetryError) else None
            logger.error(f"[API:stream] error={exc!r} cause={cause!r}")
            # 生产环境不向客户端暴露内部异常详情（防止信息泄露）
            # 参考 claude-code errors.ts：只向客户端返回安全的通用错误消息
            yield "data: [ERROR] 服务暂时不可用，请稍后重试\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",      # SSE 协议：返回文本流，每个事件占一行，事件之间用空行隔开
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},      # 禁用缓存,x-accel-buffering 是告诉 Nginx 不要缓冲，直接透传
    )


# ══════════════════════════════════════════════════════════════════════════════
# Agent SSE (Phase 18, AGENT-04) — named-event stream over the agentic loop
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/agent/v1/run/stream", tags=["agent"])
@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")
async def agent_run_stream(request: Request, req: GenerationRequest) -> StreamingResponse:
    """SSE event stream for agentic queries (AGENT-04, Phase 18; AGENT-15 swarm dispatch added Phase 21).

    Emits typed AgentEvent payloads as named SSE frames:

        event: <event_type>\\ndata: <model_dump_json>\\n\\n

    Terminal event is ``synthesizer.final`` — no ``[DONE]`` sentinel (D-01).
    Auth + rate limit + multi-tenant RLS inherit from the existing ``/query``
    stack (D-01, D-03). Body shape is ``GenerationRequest`` unchanged.

    Phase 21 / Plan 21-05 / BLOCKER 2: dispatch to ``SwarmQueryPipeline`` when
    ``req.swarm_mode=True`` so the 3 verifier events (verifier.start /
    verifier.disagreement / verifier.complete) reach the wire when
    ``req.debate=True``. Backward-compat (CF-08): non-swarm requests still
    route to the agent pipeline.
    """
    # noqa-typing: factories are untyped at the import site (mirrors the pre-Phase-21
    # pattern at controllers/api.py:209-214 in /query); same baseline tolerance applies.
    pipeline = (
        get_swarm_pipeline()  # type: ignore[no-untyped-call]
        if req.swarm_mode
        else get_agent_pipeline()
    )

    async def _sse():
        try:
            async for evt in pipeline.run_streaming(req):
                # D-10 named-event format: event: + data: + blank line.
                # model_dump_json() is one-way Pydantic V2 serialization —
                # no client-controlled deserialization (T-18-17).
                yield f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"
        except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
            logger.error(f"[API:agent_stream] error={exc}")
            # Named-event error frame — keep wire shape consistent with the
            # rest of the stream so frontend EventSource handlers stay simple.
            # Generic message only; full traceback at logger.error (T-18-15).
            yield 'event: error\ndata: {"message": "服务暂时不可用，请稍后重试"}\n\n'

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Admin
# ══════════════════════════════════════════════════════════════════════════════
@router.delete("/cache", tags=["admin"])    # 清除所有缓存。用 DELETE 方法语义上表示「删除资源」
async def clear_cache() -> APIResponse:
    deleted = await cache_invalidate("rag:*")    # 删除 Redis 中所有以 'rag:' 开头的键，星号是通配符
    return APIResponse(success=True, data={"deleted_keys": deleted})


@router.get("/stats", tags=["admin"])    # 返回向量数据库中存储的向量总数，用于监控
async def stats() -> APIResponse:
    try:
        from services.vectorizer.vector_store import get_vector_store
        count = await get_vector_store().count()
        return APIResponse(success=True, data={"total_vectors": count})
    except asyncpg.PostgresError as exc:
        logger.error(f"[API:stats] error={exc}")
        raise HTTPException(status_code=500, detail="获取统计数据失败")


# ══════════════════════════════════════════════════════════════════════════════
# 反馈接口
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/feedback", tags=["feedback"])
async def submit_feedback(req: FeedbackRequest) -> APIResponse:
    """用户对回答提交正负反馈，触发闭环学习流程。

    若该 session 当前被路由到 A/B 实验变体（pipeline 在 `ab:session:{id}` 写过映射），
    本反馈同时转发到 ABTestService，使 admin UI 的 Stats 实时反映用户真实点踩。
    """
    try:
        from services.feedback.feedback_service import (
            FeedbackRecord,
            get_feedback_service,
        )
        record = FeedbackRecord(
            session_id=req.session_id,
            query="", answer="",
            feedback=req.feedback,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            comment=req.comment,
        )
        await get_feedback_service().submit(record)

        # 自动转发到 A/B 实验：失败不阻塞主反馈流程。
        try:
            import json as _json

            from services.ab_test.ab_test_service import get_ab_test_service
            from utils.cache import get_redis
            _r = await get_redis()
            mapping = await _r.get(f"ab:session:{req.session_id}")
            if mapping:
                m = _json.loads(mapping)
                await get_ab_test_service().record_feedback(
                    experiment_id=m["experiment_id"],
                    variant_id=m["variant_id"],
                    session_id=req.session_id,
                    feedback=int(req.feedback),
                )
        except (ConnectionError, TimeoutError, ValueError, KeyError) as exc:
            logger.warning(f"[API:feedback] A/B forward failed (non-fatal): {exc}")

        # 👎 自动推标注任务：低评价 → 人工标注队列（最高优先级）。
        if int(req.feedback) < 0:
            try:
                import json as _json

                from services.annotation.annotation_service import (
                    get_annotation_service,
                )
                from utils.cache import get_redis
                _r = await get_redis()
                qa_raw = await _r.get(f"last_qa:{req.session_id}")
                if qa_raw:
                    qa = _json.loads(qa_raw)
                    await get_annotation_service().push_task_from_feedback(
                        question=qa.get("question", ""),
                        answer=qa.get("answer", ""),
                        contexts=qa.get("contexts", []),
                        tenant_id=req.tenant_id or qa.get("tenant_id", ""),
                        user_comment=req.comment,
                    )
                    logger.info(f"[API:feedback] 👎 session={req.session_id} → annotation queue")
            except (ConnectionError, TimeoutError, ValueError, KeyError) as exc:
                logger.warning(f"[API:feedback] annotation forward failed (non-fatal): {exc}")

        return APIResponse(success=True, data={"message": "反馈已记录"})
    except (asyncpg.PostgresError, ValueError) as exc:
        logger.error(f"[API:feedback] error={exc}")
        raise HTTPException(status_code=500, detail="反馈提交失败，请稍后重试")


@router.get("/feedback/stats", tags=["feedback"])
async def feedback_stats() -> APIResponse:
    from services.feedback.feedback_service import get_feedback_service
    return APIResponse(success=True, data=get_feedback_service().get_stats())


# ══════════════════════════════════════════════════════════════════════════════
# 知识库管理接口
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/knowledge/scan", tags=["knowledge"])
async def knowledge_scan(bg: BackgroundTasks) -> APIResponse:
    """触发知识库增量扫描更新（后台异步执行）。"""
    trace_id = str(uuid.uuid4())[:8]
    async def _bg_scan():
        from pathlib import Path

        from services.knowledge.knowledge_service import get_knowledge_service
        from services.pipeline import get_ingest_pipeline
        svc = get_knowledge_service()
        pipeline = get_ingest_pipeline()
        await svc.scan_and_update(Path(settings.data_dir), pipeline)
        logger.info(f"[API:scan] trace={trace_id} completed")
    bg.add_task(_bg_scan)
    return APIResponse(success=True, data={"trace_id": trace_id, "status": "scan_queued"})


# ══════════════════════════════════════════════════════════════════════════════
# 文档版本控制接口
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/docs/{doc_id}/versions", tags=["versioning"])
async def list_versions(doc_id: str) -> APIResponse:
    """获取文档所有历史版本（从新到旧）。"""
    from services.knowledge.version_service import get_version_service
    result = await get_version_service().get_versions(doc_id)
    return APIResponse(success=True, data=result.model_dump())


@router.get("/docs/{doc_id}/versions/{version}", tags=["versioning"])
async def get_version(doc_id: str, version: int) -> APIResponse:
    """获取文档指定版本的详细信息。"""
    from services.knowledge.version_service import get_version_service
    v = await get_version_service().get_version(doc_id, version)
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return APIResponse(success=True, data=v.model_dump())


@router.post("/docs/{doc_id}/rollback", tags=["versioning"])
async def rollback_version(doc_id: str, request: Request) -> APIResponse:
    """
    将文档回滚到指定历史版本（重新入库）。
    请求体：{"target_version": 2}
    """
    from services.knowledge.version_service import get_version_service
    body = await request.json()
    target_version = body.get("target_version")
    if not target_version:
        raise HTTPException(status_code=400, detail="target_version is required")
    user = getattr(request.state, "user", None)
    user_id = user.user_id if user else ""
    success, message = await get_version_service().rollback(doc_id, target_version, user_id)
    if not success:
        raise HTTPException(status_code=422, detail=message)
    return APIResponse(success=True, data={"message": message, "doc_id": doc_id,
                                           "rolled_back_to": target_version})


# ══════════════════════════════════════════════════════════════════════════════
# 人工标注接口
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/annotation/tasks", tags=["annotation"])
async def create_annotation_task(request: Request) -> APIResponse:
    """
    创建人工标注任务（通常由 RAGAS 评估低分时自动触发，也支持手动创建）。
    请求体：AnnotationTask 字段（question/answer/contexts 必填）
    """
    from services.annotation.annotation_service import get_annotation_service
    from utils.models import AnnotationTask
    body = await request.json()
    task = AnnotationTask(**body)
    await get_annotation_service().push_task(task)
    return APIResponse(success=True, data={"task_id": task.task_id, "status": "queued"})


@router.get("/annotation/tasks/next", tags=["annotation"])
async def get_next_annotation_task(request: Request) -> APIResponse:
    """获取优先级最高的待标注任务（标注员逐条领取）。"""
    from services.annotation.annotation_service import get_annotation_service
    tenant_id = request.query_params.get("tenant_id", "")
    task = await get_annotation_service().pop_task(tenant_id)
    if not task:
        return APIResponse(success=True, data=None)
    return APIResponse(success=True, data=task.model_dump())


@router.post("/annotation/tasks/{task_id}/result", tags=["annotation"])
async def submit_annotation_result(task_id: str, request: Request) -> APIResponse:
    """
    标注员提交标注结果。
    请求体：AnnotationResult 字段（faithfulness/answer_quality 必填）
    """
    from services.annotation.annotation_service import get_annotation_service
    from utils.models import AnnotationResult
    body = await request.json()
    body["task_id"] = task_id
    result = AnnotationResult(**body)
    await get_annotation_service().submit_result(result)
    return APIResponse(success=True, data={"task_id": task_id, "status": "annotated"})


@router.post("/annotation/tasks/{task_id}/skip", tags=["annotation"])
async def skip_annotation_task(task_id: str) -> APIResponse:
    """跳过当前标注任务（放回队列末尾或标记为 skip）。"""
    from services.annotation.annotation_service import get_annotation_service
    await get_annotation_service().skip_task(task_id)
    return APIResponse(success=True, data={"task_id": task_id, "status": "skipped"})


@router.get("/annotation/stats", tags=["annotation"])
async def annotation_stats() -> APIResponse:
    """获取标注进度和质量统计。"""
    from services.annotation.annotation_service import get_annotation_service
    stats = await get_annotation_service().get_stats()
    return APIResponse(success=True, data=stats.model_dump())


# ══════════════════════════════════════════════════════════════════════════════
# A/B 测试 API
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/ab/experiments", tags=["ab_test"])
async def create_ab_experiment(request: Request) -> APIResponse:
    """
    创建 A/B 实验。
    请求体示例：
    {
        "name": "reranker_ab_test",
        "description": "对比 cross_encoder vs passthrough reranker",
        "tenant_id": "",
        "variants": [
            {"variant_id": "A", "name": "control", "traffic_pct": 0.5,
             "config": {"reranker_type": "cross_encoder", "top_k_rerank": 6}},
            {"variant_id": "B", "name": "treatment", "traffic_pct": 0.5,
             "config": {"reranker_type": "passthrough", "top_k_rerank": 10}}
        ]
    }
    """
    from services.ab_test.ab_test_service import (
        Experiment,
        Variant,
        get_ab_test_service,
    )
    body = await request.json()
    variants = [Variant(**v) for v in body.pop("variants", [])]
    exp = Experiment(variants=variants, **body)
    exp_id = await get_ab_test_service().create_experiment(exp)
    return APIResponse(success=True, data={"experiment_id": exp_id})


@router.post("/ab/experiments/{experiment_id}/start", tags=["ab_test"])
async def start_ab_experiment(experiment_id: str) -> APIResponse:
    """启动实验（开始流量路由）。"""
    from services.ab_test.ab_test_service import get_ab_test_service
    await get_ab_test_service().start_experiment(experiment_id)
    return APIResponse(success=True, data={"experiment_id": experiment_id, "status": "running"})


@router.post("/ab/experiments/{experiment_id}/stop", tags=["ab_test"])
async def stop_ab_experiment(experiment_id: str) -> APIResponse:
    """停止实验。"""
    from services.ab_test.ab_test_service import get_ab_test_service
    await get_ab_test_service().stop_experiment(experiment_id)
    return APIResponse(success=True, data={"experiment_id": experiment_id, "status": "stopped"})


@router.get("/ab/experiments", tags=["ab_test"])
async def list_ab_experiments() -> APIResponse:
    """列出所有实验。"""
    from services.ab_test.ab_test_service import get_ab_test_service
    experiments = await get_ab_test_service().list_experiments()
    return APIResponse(success=True, data={"experiments": experiments})


@router.get("/ab/experiments/{experiment_id}/stats", tags=["ab_test"])
async def get_ab_experiment_stats(experiment_id: str) -> APIResponse:
    """获取实验各变体统计（均值、P95延迟、faithfulness、反馈率）。"""
    from dataclasses import asdict

    from services.ab_test.ab_test_service import get_ab_test_service
    stats = await get_ab_test_service().get_stats(experiment_id)
    return APIResponse(success=True, data={"stats": [asdict(s) for s in stats]})


@router.get("/ab/experiments/{experiment_id}/winner", tags=["ab_test"])
async def get_ab_experiment_winner(experiment_id: str) -> APIResponse:
    """基于综合评分（faithfulness+反馈率-延迟）选出最优变体。"""
    from services.ab_test.ab_test_service import get_ab_test_service
    winner_id = await get_ab_test_service().get_winner(experiment_id)
    return APIResponse(success=True, data={"winner_variant_id": winner_id})


@router.post("/ab/experiments/{experiment_id}/feedback", tags=["ab_test"])
async def record_ab_feedback(experiment_id: str, request: Request) -> APIResponse:
    """
    记录用户反馈到 A/B 实验。
    请求体：{"variant_id": "A", "session_id": "xxx", "feedback": 1}
    feedback: +1=好评 / 0=中性 / -1=差评
    """
    from services.ab_test.ab_test_service import get_ab_test_service
    body = await request.json()
    await get_ab_test_service().record_feedback(
        experiment_id=experiment_id,
        variant_id=body["variant_id"],
        session_id=body.get("session_id", ""),
        feedback=int(body.get("feedback", 0)),
    )
    return APIResponse(success=True, data={"recorded": True})
