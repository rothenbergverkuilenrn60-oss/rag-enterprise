# =============================================================================
# main.py
# 企业级 RAG 应用入口
# FastAPI + 全局中间件 + 异常处理 + 生命周期管理
# 启动命令：conda run -n torch_env uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# =============================================================================
from __future__ import annotations
import time
import uuid
from contextlib import asynccontextmanager      # 异步上下文管理器，用于生命周期管理
from typing import AsyncGenerator
import asyncpg
import httpx
import redis
from arq.connections import RedisSettings, create_pool
from jose import JWTError

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response as FastAPIResponse
from loguru import logger

from config.settings import settings
from utils.logger import setup_logger
from utils.tasks import log_task_error
from utils.metrics import (
    get_metrics_response,
    http_requests_total,
    active_requests_gauge,
    rate_limit_hits_total,
)
from controllers.api import router, limiter as _route_limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


# ══════════════════════════════════════════════════════════════════════════════
# 生命周期管理（startup / shutdown）
# ══════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:             # AsyncGenerator[None, None] 表示 yield 前是启动逻辑，yield 后是关闭逻辑
    # ── Startup ──────────────────────────────────────────────────────────────
    setup_logger()

    # 可观测性：Langfuse LLM 追踪 + OpenTelemetry 分布式 Span（按配置自动初始化）
    try:
        from utils.observability import setup_observability
        setup_observability()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.warning(f"Observability setup failed (non-fatal): {exc}")
    logger.info("=" * 60)
    logger.info(f"  {settings.app_name} v{settings.app_version} starting")  
    logger.info(f"  env={settings.environment}")                            # 环境变量
    logger.info(f"  llm={settings.llm_provider}/{settings.active_model}")      # 模型提供者和模型名称
    logger.info(f"  embed={settings.embedding_provider}/{settings.embedding_model}")      # 嵌入模型提供者和模型名称
    logger.info(f"  store={settings.vector_store}")
    logger.info("=" * 60)

    # 预热：确保向量集合已创建
    try:
        from services.vectorizer.indexer import get_vectorizer
        vectorizer = get_vectorizer()
        await vectorizer.ensure_collection()
        count = await vectorizer._store.count()
        logger.info(f"VectorStore ready: {count} vectors in collection")
    except asyncpg.PostgresError as exc:
        logger.warning(f"VectorStore warmup failed (non-fatal): {exc}")

    # ── 启动事件总线 ──────────────────────────────────────────────────────────
    try:
        from services.events.event_bus import get_event_bus
        bus = get_event_bus()
        await bus.start()
        logger.info("EventBus started")
    except (asyncpg.PostgresError, OSError) as exc:
        logger.warning(f"EventBus start failed (non-fatal): {exc}")

    # ── 注册事件 Handler（反馈驱动的重索引）────────────────────────────────
    try:
        from services.events.event_bus import EventType
        from services.feedback.feedback_service import get_feedback_service
        async def _on_reindex(event):
            logger.info(f"[Event] Reindex requested: {event.payload}")
        bus.subscribe(EventType.REINDEX_REQUESTED, _on_reindex)
    except (RuntimeError, ValueError) as exc:
        logger.warning(f"Event handler registration failed: {exc}")

    # ── 启动时自动扫描知识库（如配置开启）──────────────────────────────────
    if getattr(settings, "auto_update_on_startup", False):
        try:
            from services.knowledge.knowledge_service import get_knowledge_service
            from services.pipeline import get_ingest_pipeline
            from pathlib import Path
            import asyncio
            _auto_scan_task = asyncio.create_task(
                get_knowledge_service().scan_and_update(
                    Path(settings.data_dir), get_ingest_pipeline()
                ),
                name="auto-knowledge-scan",
            )
            _auto_scan_task.add_done_callback(log_task_error)
            logger.info("Auto knowledge scan scheduled on startup")
        except RuntimeError as exc:
            logger.warning(f"Auto update schedule failed: {exc}")

    # ARQ pool for async ingest task queue (Phase 5 — ASYNC-01, ASYNC-02).
    # Singleton pool stored on app.state, accessed by routes via request.app.state.arq_redis.
    # Per RESEARCH.md pitfall 2: never create per-request pool.
    app.state.arq_redis = await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    )
    logger.info("[startup] arq_redis pool created")

    yield  # ── 应用运行 ──────────────────────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────────
    try:
        from services.events.event_bus import get_event_bus as _get_bus
        await _get_bus().stop()
    except Exception:
        pass
    # 应用关闭时 flush 审计日志缓冲区，确保所有审计记录写入 DB
    try:
        from services.audit.audit_service import get_audit_service as _get_audit
        await _get_audit().flush()
    except Exception:
        pass
    # Flush observability buffers（确保 Langfuse 数据不丢失）
    try:
        from utils.observability import flush as obs_flush
        obs_flush()
    except Exception:
        pass
    try:
        await app.state.arq_redis.close()
        logger.info("[shutdown] arq_redis pool closed")
    except (ConnectionError, OSError) as exc:
        # Do not crash shutdown over a Redis close error
        logger.warning(f"[shutdown] arq_redis close error={exc}")
    logger.info(f"{settings.app_name} shutting down…")


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI 实例
# ══════════════════════════════════════════════════════════════════════════════
def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"success": False, "error": "Rate limit exceeded", "detail": str(exc.detail)},
        headers={"Retry-After": "60"},
    )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "RAG 系统 — 预处理 → 提取 → 文档处理 → 向量化存储 → 检索 → 生成"
    ),
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,                          # 生命周期管理器，用于启动和关闭应用
)

app.state.limiter = _route_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# ══════════════════════════════════════════════════════════════════════════════
# 中间件栈（顺序：外 → 内）
# ══════════════════════════════════════════════════════════════════════════════

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. GZip 压缩（响应 > 1KB 自动压缩）
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 3. 请求追踪中间件（注入 Trace-ID + 记录访问日志）
@app.middleware("http")
async def trace_middleware(request: Request, call_next) -> Response:
    trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:8]
    request.state.trace_id = trace_id
    start = time.perf_counter()

    active_requests_gauge.inc()
    try:
        response = await call_next(request)     # call_next调用下一层处理（路由函数）
    finally:
        active_requests_gauge.dec()

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Trace-ID"] = trace_id
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"

    # 记录 HTTP 请求计数（按方法/路径/状态码）
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=str(response.status_code),
    ).inc()

    logger.info(
        f"{request.method} {request.url.path} "
        f"→ {response.status_code} "
        f"[{elapsed_ms}ms] trace={trace_id}"
    )
    return response


# 4. IP 限流：Redis 分布式滑动窗口（多 worker / 多节点共享状态）
#    降级：Redis 不可用时自动切换为进程内字典（单节点兼容）
_RATE_WINDOW = 60.0    # 1 分钟滑动窗口（秒）

# 进程内备用计数器（Redis 不可用时启用）
_fallback_counts: dict[str, list[float]] = {}
_fallback_cleanup: float = 0.0


async def _redis_rate_check(client_ip: str, now: float) -> bool:
    """
    Redis 滑动窗口限流（Sorted Set 实现）。
    返回 True 表示超限，False 表示放行。

    原理：
      1. ZREMRANGEBYSCORE 删除窗口外的旧请求时间戳
      2. ZADD 记录本次请求时间戳（score=now, member=now:random）
      3. ZCOUNT 统计当前窗口内的请求数
      4. EXPIRE 设置键 TTL 自动清理
    """
    try:
        from utils.cache import get_redis
        import random
        r = await get_redis()
        key = f"rl:{client_ip}"
        window_start = now - _RATE_WINDOW

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)                      # 删除窗口外
        pipe.zadd(key, {f"{now}:{random.random()}": now})                # 记录本次
        pipe.zcount(key, window_start, now)                              # 统计窗口内
        pipe.expire(key, int(_RATE_WINDOW) + 5)                         # 自动 TTL
        results = await pipe.execute()
        count = results[2]
        return count > settings.rate_limit_rpm
    except redis.RedisError:
        return False   # Redis 异常时放行（fail-open），不影响业务


def _fallback_rate_check(client_ip: str, now: float) -> bool:
    """进程内滑动窗口（Redis 不可用时的降级实现）。"""
    global _fallback_cleanup
    if now - _fallback_cleanup > 300.0:   # 每 5 分钟清理一次
        stale = [ip for ip, ts in _fallback_counts.items()
                 if not any(now - t < _RATE_WINDOW for t in ts)]
        for ip in stale:
            del _fallback_counts[ip]
        _fallback_cleanup = now

    timestamps = [t for t in _fallback_counts.get(client_ip, []) if now - t < _RATE_WINDOW]
    if len(timestamps) >= settings.rate_limit_rpm:
        return True
    timestamps.append(now)
    _fallback_counts[client_ip] = timestamps
    return False


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next) -> Response:
    """
    分布式 IP 限流中间件。
    - 生产环境：Redis 滑动窗口，多 worker / 多节点共享计数
    - Redis 不可用：自动降级为进程内字典（单节点保底）
    - 跳过：非生产环境 / /metrics / /health 等内部路径
    """
    # 跳过内部探针路径（不限流）
    path = request.url.path
    if path in ("/metrics", "/health", "/readiness", "/api/v1/health", "/api/v1/readiness"):
        return await call_next(request)

    if settings.environment == "production":
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for \
            else (request.client.host if request.client else "unknown")
        now = time.time()

        if settings.rate_limit_redis:
            exceeded = await _redis_rate_check(client_ip, now)
        else:
            exceeded = _fallback_rate_check(client_ip, now)

        if exceeded:
            rate_limit_hits_total.inc()
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error":   "Rate limit exceeded",
                    "limit":   settings.rate_limit_rpm,
                    "window":  "60s",
                },
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


# ══════════════════════════════════════════════════════════════════════════════
# 全局异常处理器
# ══════════════════════════════════════════════════════════════════════════════
@app.exception_handler(Exception)       # 捕获所有未被处理的异常（兜底处理），防止服务崩溃或暴露内部堆栈信息给用户
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.exception(f"Unhandled exception trace={trace_id}: {exc}")    # exception() 方法会自动打印完整的 Python 错误堆栈，比 error() 多堆栈信息
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "trace_id": trace_id,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Prometheus 指标端点
# ══════════════════════════════════════════════════════════════════════════════
if getattr(settings, "metrics_enabled", True):
    @app.get(
        getattr(settings, "metrics_path", "/metrics"),
        include_in_schema=False,
        summary="Prometheus metrics",
    )
    async def metrics_endpoint() -> FastAPIResponse:
        data, content_type = get_metrics_response()
        return FastAPIResponse(content=data, media_type=content_type)


# ══════════════════════════════════════════════════════════════════════════════
# 认证中间件（Bearer Token → OIDC / 本地 JWT）
# 注入 request.state.user 供路由函数使用（可选，不强制）
# ══════════════════════════════════════════════════════════════════════════════
@app.middleware("http")
async def auth_middleware(request: Request, call_next) -> Response:
    """
    可选认证中间件：解析 Authorization: Bearer <token>，
    将认证结果写入 request.state.user。
    - 未提供 Token 时不拦截（允许匿名访问）
    - 路由函数可通过 request.state.user 获取已认证用户
    - 强制认证的端点可在路由函数中检查 request.state.user is None
    """
    request.state.user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from services.auth.oidc_auth import get_auth_service
            auth_svc = get_auth_service()
            token = auth_header[len("Bearer "):]
            user = await auth_svc.verify_token(token)
            request.state.user = user
            if user:
                from utils.metrics import auth_attempts_total
                auth_attempts_total.labels(result="success").inc()
        except (JWTError, httpx.HTTPError, ValueError) as exc:
            logger.debug(f"[Auth] middleware error (non-fatal): {exc}")
            from utils.metrics import auth_attempts_total
            auth_attempts_total.labels(result="failure").inc()
    return await call_next(request)


# ══════════════════════════════════════════════════════════════════════════════
# 路由注册
# ══════════════════════════════════════════════════════════════════════════════
app.include_router(router)


# ══════════════════════════════════════════════════════════════════════════════
# 直接运行入口
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    # 多 worker 模式：生产环境设置 UVICORN_WORKERS=4（建议 CPU 核心数 * 2 + 1）
    # 注意：多 worker 时各进程独立初始化，单例 Service 在每个进程内独立存在；
    #       跨进程共享状态（限流计数、缓存）必须走 Redis，不能用进程内变量。
    workers = settings.uvicorn_workers if not settings.debug else 1
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        workers=workers,
        loop="uvloop",          # 比默认 asyncio 快 2-4 倍（需 pip install uvloop）
        http="httptools",       # 更快的 HTTP 解析器（需 pip install httptools）
    )
