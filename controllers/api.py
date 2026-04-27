# =============================================================================
# controllers/api.py
# FastAPI Controller — 全局中间件 + 异常拦截 + 路由
# =============================================================================
from __future__ import annotations
import time
import uuid
import asyncpg
import httpx
import openai
import redis
import re
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from arq.jobs import Job, JobStatus
from services.auth.oidc_auth import get_current_user, AuthenticatedUser
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from config.settings import settings
from utils.models import (
    IngestionRequest, IngestionResponse, AsyncIngestRequest,
    GenerationRequest, GenerationResponse,
    APIResponse, FeedbackRequest,
)
from services.pipeline import get_ingest_pipeline, get_query_pipeline, get_agent_pipeline
from utils.cache import cache_invalidate

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


# ══════════════════════════════════════════════════════════════════════════════
# Query（检索 + 生成：STAGE 5-6）
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/query", response_model=APIResponse, tags=["query"])
@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")
async def query(request: Request, req: GenerationRequest) -> APIResponse:
    """非流式 RAG 查询。非流式用于后台任务、批处理、长文本生成"""
    trace_id = str(uuid.uuid4())[:8]
    try:
        # agent_mode=True → Agentic 工具循环；否则走标准 Pipeline
        pipeline = get_agent_pipeline() if req.agent_mode else get_query_pipeline()
        result: GenerationResponse = await pipeline.run(req)
        return APIResponse(
            success=True,
            data=result.model_dump(mode="json"),
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
        except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
            logger.error(f"[API:stream] error={exc}")
            # 生产环境不向客户端暴露内部异常详情（防止信息泄露）
            # 参考 claude-code errors.ts：只向客户端返回安全的通用错误消息
            yield "data: [ERROR] 服务暂时不可用，请稍后重试\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",      # SSE 协议：返回文本流，每个事件占一行，事件之间用空行隔开
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},      # 禁用缓存,x-accel-buffering 是告诉 Nginx 不要缓冲，直接透传
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
    """用户对回答提交正负反馈，触发闭环学习流程。"""
    try:
        from services.feedback.feedback_service import get_feedback_service, FeedbackRecord
        record = FeedbackRecord(
            session_id=req.session_id,
            query="", answer="",
            feedback=req.feedback,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            comment=req.comment,
        )
        await get_feedback_service().submit(record)
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
        from services.knowledge.knowledge_service import get_knowledge_service
        from services.pipeline import get_ingest_pipeline
        from pathlib import Path
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
    from services.ab_test.ab_test_service import get_ab_test_service, Experiment, Variant
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
    from services.ab_test.ab_test_service import get_ab_test_service
    from dataclasses import asdict
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
