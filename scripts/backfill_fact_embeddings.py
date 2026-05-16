#!/usr/bin/env python
"""scripts/backfill_fact_embeddings.py — Phase 24 / MEM-07 backfill CLI.

Embeds ``long_term_facts`` rows whose ``embedding IS NULL`` (pre-Phase-23
legacy rows) using the configured embedder, idempotently and resumably.

Design decisions honored:
  D-D1: standalone one-shot CLI; no recurring CronJob / systemd integration.
  D-D3: whole-batch txn rollback on failure; idempotent re-run via IS NULL cursor.
  D-D4: dry-run cost estimate printed; zero API calls in dry-run mode.
  T4:   single batch UPDATE via unnest($1::uuid[], $2::vector[]) — 10-50× faster
        than row-by-row.
  T5:   narrow ``except asyncpg.Error`` — covers PostgresError + InterfaceError;
        no bare Exception, no # noqa directive.
  T10:  ASCII diagram in backfill() docstring.

Usage:
  uv run python scripts/backfill_fact_embeddings.py --dry-run
  uv run python scripts/backfill_fact_embeddings.py --batch-size 100
  uv run python scripts/backfill_fact_embeddings.py --resume-from-id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Project-root injection — mirrors scripts/ingest_batch.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from loguru import logger

from services.memory.memory_service import LongTermMemory
from services.vectorizer.embedder import get_embedder
from utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Cost estimate constants (D-D4 dry-run formula)
# ---------------------------------------------------------------------------
_AVG_TOKENS_PER_FACT = 40  # heuristic: short declarative fact sentences
_OPENAI_LARGE_COST_PER_M_TOKENS = 0.13  # text-embedding-3-large, $/1M tokens
_OPENAI_SMALL_COST_PER_M_TOKENS = 0.02  # text-embedding-3-small, $/1M tokens


async def _count_remaining(pool: asyncpg.Pool) -> int:
    """Cheap pre-flight COUNT of unembedded facts (used for dry-run estimate)."""
    row = await pool.fetchrow("SELECT COUNT(*) AS n FROM long_term_facts WHERE embedding IS NULL")
    return int(row["n"]) if row else 0


async def backfill(
    batch_size: int,
    dry_run: bool,
    resume_from_id: str | None,
) -> int:
    """Embed pre-Phase-23 long_term_facts rows with embedding IS NULL.

    Returns 0 on success (or idempotent no-op), 1 on first error encountered.

    Flow diagram (T10 / Decision-4):

    backfill(batch_size, dry_run, resume_from_id):
    ┌─────────────────────────────────────────────────────────────┐
    │  pool = await LongTermMemory._get_pool()    # Pitfall 1     │
    │  if dry_run: print cost-estimate; return 0                  │
    │                                                             │
    │  while True:                                                │
    │    rows = SELECT id, fact FROM long_term_facts              │
    │             WHERE embedding IS NULL                         │
    │             [AND id > $resume_from_id]                      │
    │             LIMIT $batch_size                               │
    │    if not rows: break                    # cursor exhausted │
    │                                                             │
    │    try:                                                     │
    │      vectors = await embedder.embed_batch(texts)            │
    │    except (RuntimeError, OSError): return 1                 │
    │                                                             │
    │    try:                                                     │
    │      async with conn.transaction():                         │
    │        UPDATE ... FROM unnest($1::uuid[], $2::vector[])     │  <- T4
    │    except (asyncpg.PostgresError, asyncpg.InterfaceError):  │  <- T5
    │      rollback; return 1                                     │
    │                                                             │
    │    total_done += len(rows)                                  │
    │                                                             │
    │  return 0                               # idempotent re-run │
    └─────────────────────────────────────────────────────────────┘
    """
    # Pitfall 1: reuse LongTermMemory pool so register_vector codec is inherited.
    mem = LongTermMemory()
    pool = await mem._get_pool()

    embedder = get_embedder()

    remaining = await _count_remaining(pool)

    if dry_run:
        total_tokens = remaining * _AVG_TOKENS_PER_FACT
        cost_large = total_tokens / 1_000_000 * _OPENAI_LARGE_COST_PER_M_TOKENS
        cost_small = total_tokens / 1_000_000 * _OPENAI_SMALL_COST_PER_M_TOKENS
        logger.info(
            f"Would embed {remaining} facts "
            f"(~{total_tokens} tokens, "
            f"~${cost_large:.4f} large / ~${cost_small:.4f} small)"
        )
        return 0

    total_done = 0

    while True:
        # Cursor SELECT — WHERE embedding IS NULL; resumable via AND id >
        if resume_from_id is not None:
            rows = await pool.fetch(
                """
                SELECT id, fact
                FROM long_term_facts
                WHERE embedding IS NULL
                  AND id > $1
                ORDER BY id
                LIMIT $2
                """,
                resume_from_id,
                batch_size,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, fact
                FROM long_term_facts
                WHERE embedding IS NULL
                ORDER BY id
                LIMIT $1
                """,
                batch_size,
            )

        if not rows:
            break  # cursor exhausted — idempotent re-run exits here

        texts = [r["fact"] for r in rows]
        ids = [r["id"] for r in rows]

        # Embed batch — narrow exception: RuntimeError (Ollama re-raise), OSError (HF torch)
        try:
            vectors = await embedder.embed_batch(texts)
        except (RuntimeError, OSError) as exc:
            logger.error(f"embedder failed: {exc!r} — aborting backfill")
            return 1

        # T4: single batch UPDATE via unnest — one round-trip per batch
        # T5: narrow except asyncpg.Error (covers PostgresError + InterfaceError)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE long_term_facts
                           SET embedding = u.emb
                          FROM unnest($1::uuid[], $2::vector[]) AS u(id, emb)
                         WHERE long_term_facts.id = u.id
                        """,
                        ids,
                        vectors,
                    )
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error(f"txn UPDATE failed, rollback complete: {exc!r}")
            return 1

        total_done += len(rows)
        logger.info(
            f"backfilled batch: count={len(rows)} "
            f"total={total_done} "
            f"remaining≈{remaining - total_done}"
        )

    logger.info(f"backfill complete: total_done={total_done}")
    return 0


def main() -> None:
    setup_logger()
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for pre-Phase-23 long_term_facts rows (MEM-07)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cost estimate only; make zero API calls and zero DB writes.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        metavar="N",
        help="Rows per txn commit batch (default: 100).",
    )
    parser.add_argument(
        "--resume-from-id",
        type=str,
        default=None,
        metavar="UUID",
        help="Resume cursor from this fact UUID (exclusive); skips already-embedded rows.",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(
        backfill(
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            resume_from_id=args.resume_from_id,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
