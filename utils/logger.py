# =============================================================================
# utils/logger.py
# 结构化日志初始化 + log_latency 装饰器
# 使用 Loguru：比标准 logging 更易用，支持文件滚动、彩色输出、结构化字段
# =============================================================================
from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Callable

from loguru import logger


def setup_logger() -> None:
    """
    初始化 Loguru 日志系统。
    - 控制台：彩色输出，级别由 settings.log_level 控制
    - 文件：JSON 结构化日志，按天滚动，保留 30 天，压缩归档
    在 main.py 的 lifespan 启动时调用一次。
    """
    from config.settings import settings

    # 移除默认的 stderr handler，避免重复输出
    logger.remove()

    # 控制台 handler：彩色、人类可读
    logger.add(
        sink=lambda msg: print(msg, end=""),  # 用 print 兼容所有环境
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
        colorize=True,
        backtrace=True,               # 异常时显示完整调用链
        diagnose=settings.debug,      # 生产关闭：避免异常时把 API Key/Token 等局部变量打入日志
    )

    # 文件 handler：JSON 格式，按天滚动
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        sink=str(log_dir / "rag_{time:YYYY-MM-DD}.log"),
        level=settings.log_level,
        format="{time:YYYY-MM-DDTHH:mm:ss.SSS}Z | {level} | {name}:{function}:{line} | {message}",
        rotation="00:00",     # 每天零点滚动新文件
        retention="30 days",  # 保留 30 天日志
        compression="gz",     # 旧日志 gzip 压缩
        encoding="utf-8",
        enqueue=True,         # 异步写入，不阻塞业务线程
    )

    logger.info(f"Logger initialized: level={settings.log_level} log_dir={log_dir}")


def log_latency(func: Callable) -> Callable:
    """
    装饰器：自动记录被装饰的异步/同步函数的执行时间。

    用法：
        @log_latency
        async def my_service_method(self, ...):
            ...

    日志格式：
        [log_latency] my_service_method took 123.4ms
    """
    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.debug(f"[log_latency] {func.__qualname__} took {elapsed_ms}ms")
            return result
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(f"[log_latency] {func.__qualname__} FAILED after {elapsed_ms}ms: {exc}")
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.debug(f"[log_latency] {func.__qualname__} took {elapsed_ms}ms")
            return result
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(f"[log_latency] {func.__qualname__} FAILED after {elapsed_ms}ms: {exc}")
            raise

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
