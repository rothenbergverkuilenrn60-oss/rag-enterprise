# Memory Eviction & Backfill (Phase 24)

This document covers operational concerns for the v1.6 `long_term_facts` pgvector store.
Phase 24 ships the backfill section; Phase 25 will extend with the eviction section.

## Cost Formula (per provider)

| Provider | Per 1M facts | Per fact (~40 tokens) |
|---|---|---|
| OpenAI `text-embedding-3-large` (1024-dim) | $0.13/1M tokens × 40M = ~$5.20 | ~$5.2 µ |
| OpenAI `text-embedding-3-small` (1024-dim) | $0.02/1M tokens × 40M = ~$0.80 | ~$0.8 µ |
| HuggingFace local (BGE-M3, CPU/GPU) | $0 marginal | $0 |
| Ollama local (any) | $0 marginal | $0 |

Estimate for your deployment: `uv run python scripts/backfill_fact_embeddings.py --dry-run`
prints `Would embed N facts (~M tokens, ~$X large / ~$Y small)` with zero API calls.

## Backfill — Run Once

Pre-Phase-23 rows have `embedding IS NULL` and will not surface in semantic recall.
Run this script once after Phase 24 deployment to backfill those legacy rows.

```bash
# 1. Dry-run cost estimate (no API calls, no DB writes)
uv run python scripts/backfill_fact_embeddings.py --dry-run

# 2. Real run (100 rows per txn; tenacity 3-retry on 5xx already in embedder)
uv run python scripts/backfill_fact_embeddings.py --batch-size 100

# 3. Resume after a partial failure (UUID from the last log line)
uv run python scripts/backfill_fact_embeddings.py --resume-from-id <uuid>
```

The cursor (`WHERE embedding IS NULL`) is idempotent: re-running after a successful
pass selects 0 rows and exits 0 with no API calls.

## Failure Modes

| Symptom | Cause | Recovery |
|---|---|---|
| Exit 1 with `embedder failed` | Provider transient (429 / 5xx after 3 retries) | Re-run; `WHERE embedding IS NULL` cursor skips already-embedded rows |
| Exit 1 with `txn UPDATE failed, rollback complete` | pgvector codec or dimension mismatch | Verify `settings.embedding_dim` matches column; re-run |
| Long runtime + no log progress | Rate limit not honored | Wait, or reduce batch size (`--batch-size 50`) |

## Recurring Backfill

Not needed in steady state. Phase 23 `save_fact` embeds-on-write — only pre-Phase-24
rows have `embedding IS NULL`. If a future schema migration adds new rows without
embeddings, re-run the same script with `--batch-size` as appropriate.

## Eviction — Schedule & Cap

v1.6 eviction bounds `long_term_facts` rows per `(user_id, tenant_id)` bucket.

- **Default cap:** 500 facts; env override `MEMORY_FACTS_CAP_PER_USER=<int>` via ConfigMap `rag-config` (edit rolls into next run, no image rebuild)
- **Schedule:** daily 03:00 UTC — see CronJob YAML below
- **Cap tuning:** run `--mode=audit`, observe `row_count` per bucket, set cap at ~95th-percentile + 20% headroom, update ConfigMap, re-run audit, then enforce
- **Warning:** `--mode=enforce` deletes immediately — no internal audit preflight. Audit-first is an operator discipline (D-3.2)

## Audit Mode Workflow

Audit mode performs zero deletes; emits one JSON-line per `(user_id, tenant_id)` bucket.

```bash
uv run python scripts/evict_long_term_facts.py --mode=audit
# JSON-line shape (D-3.1): {"bucket": {"user_id": "alice", "tenant_id": "acme"}, "row_count": 612, "over_cap_by": 112, "would_delete_count": 112, "sweep_run_id": "20260516-030000-abc123"}
# Surface heavy buckets:
uv run python scripts/evict_long_term_facts.py --mode=audit | jq '. | select(.over_cap_by > 100)'
```

Inspect distribution → choose cap → update `MEMORY_FACTS_CAP_PER_USER` → re-run audit to confirm → proceed to enforce (or wait for next CronJob tick).

## Enforce Mode

- **Deletion order:** lowest `importance` first; ties broken by oldest `created_at` (importance ASC, created_at ASC). Example: bucket `importance=(0.2, 0.2, 0.8)`, `cap=2` → the older `0.2` is deleted; the `0.8` + newer `0.2` are kept
- **Chunking:** 1000 rows / txn (`--batch-size=1000`) — bounded lock duration
- **Idempotent:** at-or-under-cap buckets produce zero deletes; safe to re-run
- **Partial-sweep recovery:** per-bucket failure is logged + skipped; next bucket continues; `restartPolicy: OnFailure` retries the sweep on the next tick
- **Audit DB:** `AUDIT_DB_ENABLED=true` (CronJob env) writes one `audit_log` row per touched bucket alongside stdout + file log

## CronJob YAML

Verbatim Phase 25 manifest (from `25-RESEARCH.md §E6`); apply with `kubectl apply -f`. Other runtimes (docker-compose, systemd) are operator-owned.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ltf-eviction
  namespace: rag-enterprise
spec:
  schedule: "0 3 * * *"         # daily @ 03:00 UTC (D-3.4)
  successfulJobsHistoryLimit: 3  # bound history accumulation
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: eviction
              image: rag-enterprise:latest
              command:
                - uv
                - run
                - python
                - scripts/evict_long_term_facts.py
                - --mode=enforce
                - --batch-size=1000
              env:
                - name: PG_DSN
                  valueFrom:
                    secretKeyRef:
                      name: rag-secrets
                      key: PG_DSN
                - name: MEMORY_FACTS_CAP_PER_USER
                  valueFrom:
                    configMapKeyRef:
                      name: rag-config
                      key: MEMORY_FACTS_CAP_PER_USER
                - name: AUDIT_DB_ENABLED
                  value: "true"
              resources:
                requests:
                  cpu: "200m"
                  memory: "256Mi"
                limits:
                  cpu: "500m"
                  memory: "512Mi"
```

**Field notes:**

- `AUDIT_DB_ENABLED: "true"` — REQUIRED in production. Without it, evictions log to stdout + file only and the PG `audit_log` table gets no rows (Pitfall 3 in `25-RESEARCH.md`); compliance auditors must verify presence
- `MEMORY_FACTS_CAP_PER_USER` — sourced from `rag-config` ConfigMap; cap tuning = ConfigMap edit, no image rebuild
- `successfulJobsHistoryLimit: 3` / `failedJobsHistoryLimit: 1` — bound history; last 3 successes + last failure retained for `kubectl logs` triage
- `restartPolicy: OnFailure` — pairs with the script's idempotent re-run semantic

## Forget API

GDPR right-to-be-forgotten: `DELETE /api/v1/memory/forget?user_id=<id>`.

**Scope:** `long_term_facts` ONLY. Short-term Redis history, `user_profile`, and other
per-user state are NOT cleared in v1.6 (D-1.2); erase those out-of-band.

**Authorization:**

- Admin JWT (`role == "admin"`) — forget any `user_id` within the admin's tenant
- Non-admin — forget only own data (`jwt.sub == user_id`); cross-user → 403

**Admin tenant scope (T3 — cross-tenant idempotent no-op):** `target_tenant_id` is
resolved from the **caller's JWT**, never from a query param. An admin in tenant A
cannot reach users in tenant B; `DELETE /memory/forget?user_id=bob` where `bob` lives
in tenant B but the admin JWT is for tenant A returns `200 + {"deleted_row_count": 0}`.

> **Note for operators:** `200 + deleted_row_count=0` means *"the user has no facts in
> YOUR tenant."* It does **NOT** prove the user has no facts anywhere; cross-tenant
> existence is not surfaced. To confirm forget across all tenants, call once per
> admin-JWT-tenant.

```bash
# Admin:
curl -X DELETE "https://api.example.com/api/v1/memory/forget?user_id=alice" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "X-Confirm-Delete: yes"
# → {"deleted_row_count": N}  (200 even when N=0 — idempotent or T3 no-op)
# Self-delete (non-admin): same URL + headers; bearer is user's own JWT (sub == alice)
```

**Order of failures (T9):** role check wins over header check — a non-admin who omits
`X-Confirm-Delete` while targeting another user gets **403, not 400** (identity fail-closed-first).

| Code | Cause |
|---|---|
| 400 | Missing/wrong `X-Confirm-Delete` (only after role check passes) |
| 403 | Non-admin deleting another user — checked first (T9) |
| 404 | Empty `user_id` query param |
| 500 | DB failure (`asyncpg.PostgresError`) |
