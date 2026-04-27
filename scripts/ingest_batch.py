#!/usr/bin/env python
# =============================================================================
# scripts/ingest_batch.py
# 批量摄取脚本 — 扫描目录，将所有支持格式文件入库
# 用法：
#   conda run -n torch_env python scripts/ingest_batch.py \
#       --dir /mnt/f/rag_enterprise/data/raw \
#       --recursive
# =============================================================================
from __future__ import annotations
import argparse
import asyncio
import sys
import time
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from config.settings import settings
from utils.logger import setup_logger
from utils.models import IngestionRequest
from services.pipeline import get_ingest_pipeline

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls",
    ".csv", ".html", ".htm", ".json", ".txt", ".md",
}


async def ingest_file(pipeline, file_path: Path, dry_run: bool = False) -> dict:
    if dry_run:
        logger.info(f"[DryRun] Would ingest: {file_path}")
        return {"file": str(file_path), "status": "dry_run"}

    req = IngestionRequest(
        file_path=str(file_path),
        metadata={"title": file_path.stem},
    )
    try:
        result = await pipeline.run(req)
        status = "ok" if result.success else f"failed:{result.error}"
        logger.info(
            f"[Ingest] {file_path.name} → {status} "
            f"chunks={result.total_chunks} ms={result.elapsed_ms:.0f}"
        )
        return {
            "file": str(file_path),
            "status": status,
            "doc_id": result.doc_id,
            "chunks": result.total_chunks,
            "elapsed_ms": result.elapsed_ms,
        }
    except Exception as exc:
        logger.error(f"[Ingest] FAILED {file_path.name}: {exc}")
        return {"file": str(file_path), "status": f"exception:{exc}"}


async def main() -> None:
    setup_logger()
    parser = argparse.ArgumentParser(description="Enterprise RAG Batch Ingestion")
    parser.add_argument("--dir", required=True, help="目标目录路径（必须在 /mnt/f/）")
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不实际执行")
    parser.add_argument("--concurrency", type=int, default=3, help="并发摄取数量")
    args = parser.parse_args()

    scan_dir = Path(args.dir)
    if not scan_dir.exists():
        logger.error(f"目录不存在: {scan_dir}")
        sys.exit(1)

    # 扫描文件
    pattern = "**/*" if args.recursive else "*"
    files = [
        f for f in scan_dir.glob(pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    logger.info(f"发现 {len(files)} 个可摄取文件")

    if not files:
        logger.warning("未找到可摄取文件，退出。")
        return

    pipeline = get_ingest_pipeline()

    # 使用信号量控制并发
    semaphore = asyncio.Semaphore(args.concurrency)
    start_total = time.perf_counter()
    results = []

    async def _bounded_ingest(f: Path) -> dict:
        async with semaphore:
            return await ingest_file(pipeline, f, dry_run=args.dry_run)

    tasks = [_bounded_ingest(f) for f in files]
    results = await asyncio.gather(*tasks)

    # 统计报告
    elapsed = time.perf_counter() - start_total
    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = len(results) - ok_count
    total_chunks = sum(r.get("chunks", 0) for r in results)

    logger.info("=" * 50)
    logger.info(f"批量摄取完成 | 总耗时: {elapsed:.1f}s")
    logger.info(f"  成功: {ok_count} | 失败: {fail_count}")
    logger.info(f"  总 chunks: {total_chunks}")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
