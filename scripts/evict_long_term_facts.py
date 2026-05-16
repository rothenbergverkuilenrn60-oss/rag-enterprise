#!/usr/bin/env python
"""scripts/evict_long_term_facts.py — Phase 25 / EVICT-01 + EVICT-02.

Caps ``long_term_facts`` growth per ``(user_id, tenant_id)`` bucket. Deletes
lowest-importance rows (tie-break: oldest ``created_at`` first), chunked at
``batch_size`` rows/txn, idempotent. Supports ``--mode=audit|enforce``.

Design decisions honored:
  D-1.2  Scope: ``long_term_facts`` ONLY (no Redis, no user_profile).
  D-2.2  Per-bucket audit row written AFTER each bucket's DELETE completes.
  D-2.3  Audit AFTER DELETE — never before.
  D-2.4  ``sweep_run_id = uuid.uuid4().hex`` generated once per sweep and
         propagated to every per-bucket audit row.
  D-3.1  Audit mode writes BOTH stdout JSON-lines (for operator review) AND
         a SKIPPED audit_log row.
  D-3.2  No code-enforced ``--mode=audit`` precondition; runbook-only.
  EVICT-01  Chunked DELETE (default 1000 rows/txn); tie-break ORDER BY
            ``importance ASC, created_at ASC``.
  EVICT-02  ``--mode={audit,enforce}`` CLI surface.

Pitfall mitigations (25-RESEARCH.md):
  Pitfall 1  Pool obtained via ``LongTermMemory()._get_pool()`` — never the
             raw asyncpg pool factory directly. This inherits the
             ``register_vector`` codec.
  Pitfall 2  Row count parsed via ``int(status.split()[1])`` from
             ``conn.execute()`` return string ("DELETE N" → N).
  Pitfall 4  Batch loop catches ``(asyncpg.PostgresError, asyncpg.InterfaceError)``
             — CLI runs many txns, network blips re-raise InterfaceError.
  Pitfall 8  Re-run on already-at-cap bucket returns 0 deletes; idempotent.

Eng-review amendments:
  T1 (Architecture A1) — ``audit_svc.log()`` is wrapped in try/except inside
     both audit-mode and enforce-mode branches of ``evict_bucket``. On audit
     failure: structured ERROR log emitted (operation="evict_audit_log") with
     the would-be detail payload + sweep_run_id + mode + deleted_count.
     The sweep CONTINUES to the next bucket. Audit failure must NEVER abort
     the sweep — that would silently destroy correctness data (we know the
     DELETE happened, we just couldn't record it; the log is the secondary
     record so the operator can backfill the audit row by hand).
  T8 (outside voice F2) — ``remaining_count`` in the audit detail dict comes
     from a SECOND ``pool.fetchrow("SELECT COUNT(*) ...")`` AFTER the chunked
     DELETE loop completes. Replaces stale ``row_count - total_deleted``
     arithmetic which lies when ``save_fact``/``forget_user`` runs
     concurrently in another transaction. Sub-ms COUNT cost per bucket.

Usage:
  uv run python scripts/evict_long_term_facts.py --mode=audit
  uv run python scripts/evict_long_term_facts.py --mode=enforce --batch-size 1000
  uv run python scripts/evict_long_term_facts.py --mode=enforce --user-id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

# Project-root injection — mirrors scripts/backfill_fact_embeddings.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from loguru import logger

from config.settings import settings
from services.audit.audit_service import (
    AuditAction,
    AuditEvent,
    AuditResult,
    get_audit_service,
)
from services.memory.memory_service import LongTermMemory
from utils.logger import setup_logger


async def evict_bucket(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    cap: int,
    batch_size: int,
    mode: str,
    sweep_run_id: str,
    audit_svc,
) -> int:
    """Evict one (user_id, tenant_id) bucket down to ``cap``. Returns rows deleted.

    Flow (T1 + T8 contracts):

      1. Pre-DELETE COUNT (cheap; reused for over_cap_by + stdout JSON).
      2. If over_cap_by == 0 → idempotent no-op, return 0.
      3. audit mode → emit stdout JSON-line + wrap audit_svc.log() in T1 try/except;
         return 0 (no DELETE).
      4. enforce mode → chunked DELETE with ORDER BY importance ASC, created_at ASC.
         Catch (asyncpg.PostgresError, asyncpg.InterfaceError) and re-raise so the
         outer main_async sweep loop logs+continues to the next bucket.
      5. POST-DELETE: second SELECT COUNT(*) (T8) — reflects actual remaining
         rows even if save_fact wrote between the pre-COUNT and the DELETE.
      6. audit_svc.log(SUCCESS) wrapped in T1 try/except — audit failure
         emits ERROR log with operation="evict_audit_log" and the would-be
         payload, then returns total_deleted (does NOT propagate).
    """
    pre_row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        user_id, tenant_id,
    )
    row_count = int(pre_row["n"]) if pre_row else 0
    over_cap_by = max(0, row_count - cap)

    if over_cap_by == 0:
        return 0  # Pitfall 8: idempotent

    # ------------------------------------------------------------------ audit
    if mode == "audit":
        # D-3.1: stdout JSON-line so the operator can pipe to jq / file.
        print(
            json.dumps({
                "bucket":             {"user_id": user_id, "tenant_id": tenant_id},
                "row_count":          row_count,
                "cap":                cap,
                "over_cap_by":        over_cap_by,
                "would_delete_count": over_cap_by,
                "sweep_run_id":       sweep_run_id,
            }),
            file=sys.stdout,
            flush=True,
        )

        audit_event = AuditEvent(
            action=AuditAction.MEMORY_EVICT,
            user_id=user_id,
            tenant_id=tenant_id,
            result=AuditResult.SKIPPED,
            detail={
                "target_user_id":   user_id,
                "target_tenant_id": tenant_id,
                "deleted_count":    0,
                "cap_value":        cap,
                "remaining_count":  row_count,  # audit mode: nothing deleted
                "mode":             "audit",
                "sweep_run_id":     sweep_run_id,
            },
        )
        # T1: audit failure must NOT abort sweep — loud-log and continue.
        try:
            await audit_svc.log(audit_event)
        except Exception as audit_exc:  # noqa: BLE001 — T1: audit failure must not abort sweep
            logger.error(
                "audit log write failed during eviction sweep (audit mode, no DELETE)",
                operation="evict_audit_log",
                audit_payload=audit_event.detail,
                user_id=user_id,
                tenant_id=tenant_id,
                sweep_run_id=sweep_run_id,
                mode=mode,
                deleted_count=0,
                exc_info=audit_exc,
            )
        return 0

    # ---------------------------------------------------------------- enforce
    total_deleted = 0
    remaining_to_delete = over_cap_by

    while remaining_to_delete > 0:
        chunk = min(batch_size, remaining_to_delete)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    status = await conn.execute(
                        """
                        DELETE FROM long_term_facts
                        WHERE id IN (
                            SELECT id FROM long_term_facts
                            WHERE user_id=$1 AND tenant_id=$2
                            ORDER BY importance ASC, created_at ASC
                            LIMIT $3
                        )
                        """,
                        user_id, tenant_id, chunk,
                    )
            # Pitfall 2 / SP-5: parse "DELETE N" → N
            deleted_in_chunk = int(status.split()[1])
            total_deleted += deleted_in_chunk
            remaining_to_delete -= deleted_in_chunk
            if deleted_in_chunk == 0:
                # No rows matched (concurrent forget?); exit cleanly.
                break
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            # Pitfall 4: CLI batch loop catches BOTH (network blip + PG error).
            logger.error(
                "eviction chunk DELETE failed",
                user_id=user_id,
                tenant_id=tenant_id,
                exc_info=exc,
                operation="evict_bucket_chunk",
            )
            raise

    # T8: re-fetch COUNT(*) for accurate remaining_count even under concurrent writes.
    post_row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        user_id, tenant_id,
    )
    remaining_count = int(post_row["n"]) if post_row else 0

    # SP-6 / D-2.3: audit row written AFTER the DELETE completes.
    audit_event = AuditEvent(
        action=AuditAction.MEMORY_EVICT,
        user_id=user_id,
        tenant_id=tenant_id,
        result=AuditResult.SUCCESS,
        detail={
            "target_user_id":   user_id,
            "target_tenant_id": tenant_id,
            "deleted_count":    total_deleted,
            "cap_value":        cap,
            "remaining_count":  remaining_count,  # T8: re-COUNT, not arithmetic
            "mode":             "enforce",
            "sweep_run_id":     sweep_run_id,
        },
    )
    # T1: audit failure must NOT abort sweep — loud-log and continue.
    try:
        await audit_svc.log(audit_event)
    except Exception as audit_exc:  # noqa: BLE001 — T1: audit failure must not abort sweep
        logger.error(
            "audit log write failed during eviction sweep (DELETE already committed)",
            operation="evict_audit_log",
            audit_payload=audit_event.detail,
            user_id=user_id,
            tenant_id=tenant_id,
            sweep_run_id=sweep_run_id,
            mode=mode,
            deleted_count=total_deleted,
            exc_info=audit_exc,
        )

    return total_deleted


async def main_async(mode: str, batch_size: int, user_id: str | None) -> int:
    """Sweep all over-cap buckets (or a single bucket if --user-id given).

    Returns 0 on completion — per-bucket failures are logged and skipped, the
    CronJob restartPolicy: OnFailure handles retry at the sweep level. T1
    audit failures DO NOT cause non-zero exit (the DELETE already happened;
    the structured ERROR log is the recovery record).
    """
    setup_logger()

    # Pitfall 1: reuse LongTermMemory pool so register_vector codec is inherited.
    mem = LongTermMemory()
    pool = await mem._get_pool()

    audit_svc = get_audit_service()
    sweep_run_id = uuid.uuid4().hex  # D-2.4: per-sweep correlation ID
    cap = settings.memory_facts_cap_per_user  # 25-01 added this field

    if user_id:
        buckets = await pool.fetch(
            """SELECT user_id, tenant_id, COUNT(*) AS n
               FROM long_term_facts WHERE user_id=$1
               GROUP BY user_id, tenant_id HAVING COUNT(*) > $2""",
            user_id, cap,
        )
    else:
        buckets = await pool.fetch(
            """SELECT user_id, tenant_id, COUNT(*) AS n
               FROM long_term_facts
               GROUP BY user_id, tenant_id HAVING COUNT(*) > $1""",
            cap,
        )

    if not buckets:
        logger.info(
            "eviction: no buckets over cap",
            cap=cap,
            mode=mode,
            sweep_run_id=sweep_run_id,
        )
        await audit_svc.flush()
        return 0

    total_deleted = 0
    for b in buckets:
        try:
            deleted = await evict_bucket(
                pool=pool,
                user_id=b["user_id"],
                tenant_id=b["tenant_id"],
                cap=cap,
                batch_size=batch_size,
                mode=mode,
                sweep_run_id=sweep_run_id,
                audit_svc=audit_svc,
            )
            total_deleted += deleted
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error(
                "eviction bucket failed — continuing to next bucket",
                user_id=b["user_id"],
                tenant_id=b["tenant_id"],
                sweep_run_id=sweep_run_id,
                exc_info=exc,
                operation="evict_bucket_failed",
            )
            # CronJob restartPolicy: OnFailure handles sweep-level retry.
            continue

    await audit_svc.flush()
    logger.info(
        "eviction sweep complete",
        mode=mode,
        total_deleted=total_deleted,
        bucket_count=len(buckets),
        sweep_run_id=sweep_run_id,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evict long_term_facts rows over per-user cap (EVICT-01 + EVICT-02).",
    )
    parser.add_argument(
        "--mode",
        choices=["audit", "enforce"],
        default="audit",
        help="audit: stdout JSON + SKIPPED audit row, zero DELETEs. "
             "enforce: chunked DELETE + SUCCESS audit row (default: audit).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        metavar="N",
        help="Rows per DELETE chunk / txn (default: 1000, EVICT-01 spec).",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        metavar="UUID",
        help="Restrict sweep to this single user_id (default: all over-cap buckets).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.mode, args.batch_size, args.user_id)))


if __name__ == "__main__":
    main()
