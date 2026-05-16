# Phase 25 Discussion Log

**Skill:** /gsd-discuss-phase 25
**Mode:** discuss (default)
**Date:** 2026-05-16
**Themes selected (multi-select):** all 4 — Forget API surface, Audit-log shape, Eviction UX, Docs reconciliation

## Theme 1 — Forget API surface

**Q1: Forget API auth gate**
- A) admin OR self-delete (matches ROADMAP) ← **SELECTED**
- B) admin only
- C) config-toggled `settings.memory_self_delete_enabled`

**Q2: Forget scope**
- A) long_term_facts only (matches design doc Premise 7) ← **SELECTED**
- B) + short-term Redis history
- C) + short-term + user_profile (all three stores)

**Q3: Status codes for empty-bucket forget**
- A) 200 with deleted_row_count=0 (idempotent) ← **SELECTED**
- B) 404 when no rows match
- C) 200 always + body `had_facts: bool`

**Q4: Confirmation header**
- A) Require `X-Confirm-Delete: yes` header ← **SELECTED**
- B) No confirmation header
- C) Confirmation only for admin-delete-others path

**Theme 1 continuation check:** "Move to Theme 2 (Recommended)" ← **SELECTED**. Error handling defaults to Phase 23 `save_fact` precedent (raise typed `MemoryForgetError` on `asyncpg.PostgresError`).

## Theme 2 — Audit-log shape

**Q1: AuditAction enum extension**
- A) Add MEMORY_FORGET + MEMORY_EVICT (two new values) ← **SELECTED**
- B) Single MEMORY_DELETE with subtype
- C) Reuse DELETE_DOC + detail.target

**Q2: Eviction audit granularity**
- A) One row per bucket touched ← **SELECTED**
- B) One row per sweep run (summary only)
- C) Both (sweep summary + per-bucket)

**Q3: Audit-log write timing**
- A) AFTER the DELETE with actual deleted_row_count ← **SELECTED**
- B) BEFORE the DELETE (intent-log)
- C) Both (intent + result)

**Theme 2 continuation check:** "Move to Theme 3 (Recommended)" ← **SELECTED**. Detail dict shape defaults to `{target_user_id, target_tenant_id, deleted_row_count, actor_user_id, actor_is_admin, requesting_ip}` for forget; `{... cap_value, remaining_count, mode}` for evict.

## Theme 3 — Eviction operator UX

**Q1: Audit-mode (`--mode=audit`) output**
- A) stdout JSON-lines + audit_log table (both sinks) ← **SELECTED**
- B) stdout only (human-readable table)
- C) stdout JSON-lines + audit_log + JSON summary file

**Q2: First-run safety**
- A) Runbook-only — docs document audit→enforce workflow ← **SELECTED**
- B) Enforce-mode refuses unless prior audit-mode audit-row exists
- C) Refuse unless `--confirm-cap=N` flag matches settings

**Q3: CronJob YAML scope in docs**
- A) k8s CronJob YAML only ← **SELECTED**
- B) k8s + docker-compose + systemd-timer (three runtimes)
- C) k8s + generic cron(8) line

**Q4: Recommended cron frequency**
- A) Daily @ 3am UTC (`0 3 * * *`) ← **SELECTED**
- B) Weekly @ Sunday 3am
- C) Defer — doc describes tradeoff, operator picks

## Theme 4 — Docs reconciliation

**Q1: EVICT-03 mark reconciliation**
- A) Un-mark to `[ ]` now; re-mark `[x]` after Phase 25 verifier ← **SELECTED**
- B) Keep `[x]`; Phase 25 "extends" the doc
- C) Split EVICT-03 into 03a (done) + 03b (Phase 25)

**Q2: Doc extension shape**
- A) Single file `docs/memory-eviction.md`, sectioned ← **SELECTED**
- B) Split into `memory-eviction.md` + `memory-forget.md`
- C) Rename to `docs/memory-ops.md` + restructure

## Closeout

**Final check:** "Ready for CONTEXT.md (Recommended)" ← **SELECTED**.

13 decisions captured across 4 themes. Sub-areas deferred to Claude defaults:
- Forget error class shape (D-1.5): mirror Phase 23 `MemoryFactWriteError`
- Audit detail dict fields (D-2.4): standard fields per pattern
- CronJob YAML field values (D-3.3): generic Pod spec from existing v1.4 manifests if present
- Eviction CLI flag naming (D-3.2): ROADMAP-spec'd `--mode={audit,enforce}` + `--batch-size`

## Deferred Ideas Surfaced

See `25-CONTEXT.md` §Deferred Ideas. v1.7+ candidates:
- `save_fact` pre-INSERT cap check
- Full GDPR forget (short-term + user_profile)
- Per-tenant cap overrides + importance decay
- Cap auto-tuning from observed percentiles
- Code-enforced first-run audit preflight
- `docs/memory-ops.md` consolidation rename
- Bulk-forget endpoint (per tenant)
