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
