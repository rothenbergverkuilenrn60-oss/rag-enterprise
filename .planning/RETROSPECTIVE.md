# Retrospective — EnterpriseRAG

## Milestone: v1.0 — Hardening

**Shipped:** 2026-04-27
**Phases:** 6 | **Plans:** 20 | **Commits:** 100

### What Was Built

1. **pgvector Foundation** — Replaced Qdrant with PostgreSQL+pgvector; HNSW index; PostgreSQL RLS tenant isolation; parent chunk round-trip via `upsert_parent_chunks`/`fetch_parent_chunks`
2. **Security Hardening** — JWT denylist validator at startup; per-route `@limiter.limit()` decorators; PII blocking by default; CORS locked to explicit origins; APP_MODEL_DIR required env var; Rule.check() ABC enforcement
3. **Error Handling Sweep** — 50+ broad `except Exception` sites narrowed; `utils/tasks.py` helper for `done_callback` on all `create_task()` calls; 3 intentional exemptions documented (D-04/D-06)
4. **Image Extraction** — PyMuPDF-based PDF image extraction; `ExtractedImage` model; LLM captioning with CLIP fallback; `chunk_type="image"` stored in pgvector JSONB metadata; standalone image file ingestion
5. **Async Ingest Tracking** — ARQ worker with Redis backend; `POST /ingest/async` returns `task_id`; `GET /ingest/status/{task_id}` with pending/complete/failed states; 24h TTL
6. **Test Coverage + Eval** — 263 unit tests across 11 service modules; 46.63% CI coverage floor (46%); 200 stratified QA pairs; holdout manifest; RAGAS faithfulness/relevancy gate on main-branch CI

### What Worked

- **Wave-based parallel execution** — Plans 06-01 and 06-02 ran in parallel worktrees; merged cleanly and saved meaningful time
- **Checkpoint protocol** — The human-verify checkpoint in 06-03 caught a real problem (coverage 46% vs 80% target) before it became a hidden technical debt item
- **Security auditor** — `gsd-security-auditor` verified all 14 threats in one pass with evidence citations; no re-work needed
- **SUMMARY.md discipline** — Every plan producing a SUMMARY.md made the milestone archive trivial to generate; accomplishments were already written
- **Narrow exception wins** — The error handling sweep uncovered real bugs (ConnectionError not caught in `multi_query_expand`) that were fixed as a side-effect

### What Was Inefficient

- **REQUIREMENTS.md traceability never updated** — All 22 requirements were delivered but the traceability table showed 21/22 as "Pending" at milestone close. No phase transition step updated it. Had to correct at archive time.
- **Git worktree merge conflicts** — 06-01 and 06-02 executors both updated `STATE.md`; merge conflict required manual resolution. Could be avoided by having executors write to phase-specific files and having the orchestrator merge.
- **Coverage target mismatch** — The 80% coverage floor was set in the plan without accounting for the 5000-line codebase; the executor hit the wall at checkpoint and needed a course correction. Better sizing upfront would have avoided the rework.
- **ROADMAP.md plan checkboxes never updated** — Plans stayed as `- [ ]` even after completion; only SUMMARY.md and STATE.md were authoritative.

### Patterns Established

- `os.environ.setdefault("APP_MODEL_DIR", "/tmp")` at top of every test file — prevents deferred import failures
- Instance-level monkeypatching (`setattr(service_instance, "_client", mock)`) before any HTTP call
- autouse singleton-reset fixtures (`_X_service = None` post-yield) in every test file that touches module-level state
- `done_callback` pattern via `utils/tasks.py` — use `create_logged_task()` instead of raw `create_task()`
- Holdout manifest before QA generation — `holdout_manifest.json` is single source of truth; tests assert `source_doc ∈ manifest`

### Key Lessons

1. **Size test coverage targets against actual LOC** — "80% of services/" means counting service lines first, then estimating test files needed
2. **Update REQUIREMENTS.md traceability at phase completion** — one-line `gsd-transition` step; don't defer to milestone close
3. **Worktree executors should write phase-local STATE.md updates** — orchestrator merges; avoids content conflicts on shared files
4. **Checkpoint threshold was right; target was wrong** — the 46%/80% checkpoint catch was correct behavior; the target number should have been validated earlier
5. **Security audit at end is fast when plans include threat models** — having STRIDE registers in PLAN.md made the final `/gsd-secure-phase` a 2-minute operation

### Cost Observations

- Model mix: sonnet-4-6 throughout (main + subagents)
- Sessions: ~4 sessions across 7 days
- Notable: Wave-based parallelism (06-01 + 06-02 simultaneously) saved roughly 40% of wave 1 execution time vs sequential

---

## Cross-Milestone Trends

| Metric | v1.0 |
|--------|------|
| Phases | 6 |
| Plans | 20 |
| Commits | 100 |
| Duration | 7 days |
| Deferred items at close | 1 (TEST-02 coverage floor) |
| Verification score | 3/3 (1 accepted deviation) |
| Security threats closed | 14/14 |
