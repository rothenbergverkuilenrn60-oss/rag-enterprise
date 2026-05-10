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

## Milestone: v1.1 — Retrieval Depth & Frontend

**Shipped:** 2026-05-08
**Phases:** 4 | **Plans:** 9 | **Commits:** (stacked PR #1)

### What Was Built

1. **OCR Engine Integration** — PP-StructureV3 layout-aware OCR for scanned PDFs; async-safe with bounded concurrency; Docker-baked model weights for cold-start reliability
2. **Multimodal Metadata + Query Filter** — Section heading text embedded in chunk content; `section_id`/`section_title` in JSONB metadata; `hnsw.iterative_scan = strict_order` + B-tree expression indexes for filtered recall; regex-first Chinese query filter extractor
3. **Frontend Extraction** — `_UI_HTML` constant extracted to `static/ui.html`; served via FastAPI `StaticFiles`; `index.html → ui.html` symlink to satisfy `html=True` behavior
4. **Coverage Gate on New Code** — `diff-cover ≥ 80%` gate on v1.1-touched files; legacy 46% floor preserved as informational; CI baseline split: `v1.0` tag for CI, `origin/master` for local dev-loop

### What Worked

- **Wave parallelism** — Plans 07-01/07-02, 08-01/08-02/08-03, 08-04/08-05 ran in parallel worktrees; merged cleanly with no content conflicts
- **Deviation checkpoint** — The `index.html → ui.html` symlink deviation (Phase 9) was caught at executor checkpoint; the right call for `StaticFiles(html=True)` behavior
- **diff-cover approach** — Gating only new code avoids the legacy coverage wall entirely; clean separation of "regression guard" vs "new code quality"
- **Regex-first filter extractor** — 100% deterministic, zero per-query cost; correctly deferred LLM fallback to v1.3

### What Was Inefficient

- **PP-StructureV3 Docker model baking** — Required non-trivial Dockerfile surgery; should have been scoped earlier in planning to avoid executor surprise
- **JSONB filter GUC complexity** — `iterative_scan` + `ef_search` tuning for selective filters was research-heavy; the pattern is now documented but wasn't in the plan upfront
- **Phase 8 scope** — 5 plans across metadata + filter + retrieval is the heaviest single phase; could have split META vs QUERY into separate phases for cleaner verification

### Patterns Established

- `hnsw.iterative_scan = strict_order` + raised `ef_search` as the standard pattern for JSONB-filtered pgvector queries
- `diff-cover --compare-branch=origin/master` locally; `diff-cover --compare-branch=v1.0` in CI — two refs, two use cases, one command
- Section heading text in embedded content, numeric IDs only in metadata — keeps embedding space free of high-cardinality numerics

### Key Lessons

1. **Scope OCR model dependencies in planning** — Docker-baked weights vs cold-download is a binary choice with big Dockerfile implications; decide before execution starts
2. **JSONB filter retrieval is non-trivial in pgvector** — The `iterative_scan` + `ef_search` pattern requires understanding of HNSW internals; should be in the plan, not discovered during execution
3. **Parallel wave plans must not share write targets** — STATE.md and phase plan files are safe as long as each worktree writes to its own phase-local files first

### Cost Observations

- Model mix: sonnet-4-6 throughout
- Sessions: ~1 session (all 4 phases on same day)
- Notable: All 4 phases shipped in a single day via wave parallelism

---

## Milestone: v1.2 — Agentic Layer + Swarm

**Shipped:** 2026-05-08
**Phases:** 1 | **Plans:** 4 | **Commits:** (stacked PR #2)

### What Was Built

1. **Provider-Neutral Foundation** — `ToolCall` + `AgenticTurn` Pydantic V2 frozen models in `utils/models.py`; `BaseLLMClient.call_agentic_turn` default-raise method; provider-neutral return shape for all agentic turn data
2. **Wire Fixtures** — 7 hand-curated JSON fixtures (4 Anthropic + 3 OpenAI) in `tests/unit/fixtures/agentic_turn/` against real SDK response shapes; enables realistic adapter testing without live API calls
3. **Adapter Implementations** — `AnthropicLLMClient.call_agentic_turn` + `OpenAILLMClient.call_agentic_turn`; wire differences absorbed inside each adapter; 13-test parametrized suite covering text-only, single tool call, parallel tool calls, max-iterations termination
4. **Pipeline Refactor + Parallel Burst** — `AgentQueryPipeline.run` refactored onto `call_agentic_turn`; Anthropic-only gate at `pipeline.py:599-604` removed; `asyncio.gather` parallel burst; `tool_call.id` correlation via `zip`; audit log per turn; live OpenAI integration test; README differentiator section

### What Worked

- **Hand-curated wire fixtures** — Realistic SDK response shapes caught format nuances that generated fixtures would miss; the fixture investment paid off immediately in Plan 11-03
- **Staged wave design** — Splitting into 3 waves (models → fixtures → adapters → pipeline) gave clean dependency ordering; each wave had a verifiable artifact before the next started
- **`_RAW_DICT_FIELDS = {"input"}` pattern** — Locking opaque fields in Pydantic models avoids coercion surprises with arbitrary tool schemas; generalizable to any model with opaque dict fields
- **`asyncio.gather` + `zip` for tool correlation** — Simple, correct, and order-stable; no additional bookkeeping needed

### What Was Inefficient

- **Stop_reason mapping discovery** — The Anthropic (`"tool_use"`) vs OpenAI (`"tool_calls"`) divergence wasn't documented in the plan; had to be discovered at implementation time (gotcha #6)
- **Anthropic live integration gated on key** — Mock-tested side works; live Anthropic path deferred to CI, which creates a latent verification gap until key is available

### Patterns Established

- Non-abstract default-raise pattern on `BaseLLMClient` — future adapters opt into agentic mode without breaking the base class
- `_RAW_DICT_FIELDS` class var in Pydantic models — marks opaque dict fields that must survive round-trip without coercion
- Wave-based adapter delivery: models → fixtures → implementations → integration — clear dependency ordering for any future provider

### Key Lessons

1. **Document provider wire-format divergences in the plan** — `stop_reason` mapping, system message placement, tool call ID formats — collect these before implementation; they're not discoverable from the interface contract alone
2. **Wire fixtures are worth the investment** — Hand-curated fixtures against real SDK responses are more valuable than generated mocks; they catch format bugs before CI runs
3. **Single-phase milestones are fast** — 4 plans, 1 phase, shipped in one day; small milestone scope enables rapid closure

### Cost Observations

- Model mix: sonnet-4-6 throughout
- Sessions: ~1 session (all 4 plans on same day)
- Notable: Audit was pre-run (`/gsd-audit-milestone`) before close, which made the close workflow trivial

---

## Cross-Milestone Trends

| Metric | v1.0 | v1.1 | v1.2 |
|--------|------|------|------|
| Phases | 6 | 4 | 1 |
| Plans | 20 | 9 | 4 |
| Commits | 100 | (stacked) | (stacked) |
| Duration | 7 days | 1 day | 1 day |
| Deferred items at close | 1 (TEST-02) | 0 | 0 |
| Verification score | 3/3 (1 accepted deviation) | 4/4 | 4/4 |
| Security threats closed | 14/14 | n/a | n/a |
