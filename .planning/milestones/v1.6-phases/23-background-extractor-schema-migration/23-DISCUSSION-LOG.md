# Phase 23 — Discussion Log

**Date:** 2026-05-15
**Workflow:** /gsd-discuss-phase 23 (default mode)
**Output:** 23-CONTEXT.md (canonical decisions)
**Purpose:** Audit trail of options presented + user selections. Not consumed by downstream agents — use 23-CONTEXT.md for that.

---

## Area Selection — D-P23-1

**Question:** Which Phase 23 gray areas to discuss?

**Options presented:**
- A — Embedding model choice (same as KB vs cheaper) (recommended)
- B — Extractor prompt shape + importance categories (recommended)
- D — Wire-in auth edge cases (recommended)
- C — Cost guard / agent_mode gating

**User selection:** A + B + D (multi-select). C deferred to Phase 23 RESEARCH.

**Note:** C is OQ#2 from STATE.md; punted to researcher to gather per-turn cost numbers, then planner picks based on real data.

---

## Area A — Embedding model

### D-P23-A1: Embedding model for `long_term_facts.embedding`

**Options presented:**
1. Same as KB chunks — `settings.embedding_model`, 1024-dim (recommended)
2. Smaller dedicated model (text-embedding-3-small) — cheaper per-write
3. Local model (Sentence-BERT, 384-dim) — zero per-call cost, new infra

**User selection:** Option 1 — Same as KB.

**Rationale (Claude's recommendation, user-accepted):** Same model means same query vector at recall time — shared between `search_knowledge_base` and `recall_memory`, computed once, reused twice. Cross-store similarity stays comparable. Zero new infra; `save_fact` calls existing `embed_one()`. Per-write cost bounded by N=3 per-turn cap.

**Implications:**
- MEM-01 schema column: `embedding VECTOR(1024)` (matches `settings.embedding_dim`).
- MEM-02 `save_fact` rewrite: calls `services/vectorizer/embedder.py::Embedder.embed_one()` before INSERT.
- No new settings field; no new embedding adapter path.

---

## Area B — Extractor prompt + importance categories

### D-P23-B1: Refusal-clause shape

**Options presented:**
1. Whitelist — extract only listed categories (recommended)
2. Blacklist — extract anything except forbidden types
3. Both layered — whitelist + per-category blacklist

**User selection:** Option 1 — Whitelist (fail-closed).

**Rationale:** Matches v1.0 Phase 2 security philosophy (explicit allowlist > deny-by-exception). Fail-closed default; unknown categories silently ignored — no jailbreak surface. The user can restate next turn; storing wrong facts is harder to fix than missing some.

### D-P23-B2: Whitelisted categories + importance bucket mapping

**Options presented:**
1. 3 categories → 3 buckets (recommended)
2. 2 categories → 2 buckets — drop transient
3. 4 categories → 3 buckets — separate identity from preference

**User selection:** Option 1 — 3 categories, 1:1 bucket mapping.

**Locked rubric:**

| Category | Importance | Examples |
|---|---|---|
| `stable_preferences` | 0.8 | "user prefers React over Vue", "user works in healthcare" |
| `recurring_topics` | 0.5 | "user often asks about Postgres performance" |
| `transient_context` | 0.2 | "user is currently working on v1.6 milestone" |

**Implications:**
- MEM-03 `ExtractedFact` schema: `category: Literal["stable_preferences", "recurring_topics", "transient_context"]` + `importance: Literal[0.2, 0.5, 0.8]` with cross-field validator enforcing the mapping.
- Phase 25 eviction priority = importance bucket — lowest evicted first (transient_context first).

---

## Area D — Wire-in auth edge cases

### D-P23-D1: Behavior when request lacks user_id / tenant_id

**Options presented:**
A. Silent skip — no log, no error
B. Log-then-skip — structured log, no fact, no exception (recommended)
C. Fail — raise typed error caught by `log_task_error`
D. Empty-string fallback — write with `tenant_id=''`

**User selection:** Option B — Log-then-skip.

**Rationale:** Extraction is best-effort. Silent skip hides misconfigured prod auth as invisible regression. Structured-log entry (`operation="extractor_skipped"` + `reason ∈ {"missing_user_id", "missing_tenant_id"}`) gives ops visibility without breakage. Matches v1.0 Phase 3 narrow-exception + structured-log pattern. Empty-string fallback rejected as multi-tenant isolation regression.

**Implementation note (for planner):** Precondition check lives in dispatch wrapper, NOT inside `Extractor.run()`. Wrapper signature: `dispatch_extraction(turn, user_id, tenant_id) -> None`.

---

## Deferred Ideas (captured, not acted on)

### Within v1.6 — pushed to later phase / sub-step
- **Cost guard / `agent_mode` gating** (OQ#2) → Phase 23 RESEARCH (cost numbers) + PLAN (decision based on numbers).
- **HNSW `iterative_scan` mode** (OQ#4) → Phase 24 PLAN (recall-path concern, not Phase 23).
- **Recall result formatting** → Phase 24 PLAN.
- **Extractor LLM provider/model choice** (cheaper model vs user-facing turn model) → Phase 23 RESEARCH.

### Out of v1.6 — v1.7+ backlog
- Live planner-callable `save_memory` tool (rejected /office-hours D3).
- Manual "remember this" UI (rejected /office-hours D3).
- Cross-user-within-tenant recall (out per design doc Premise 3).
- SSE `memory.*` events (out per design doc Premise 5).
- Identity-vs-preference category split (rejected D-P23-B2 as nice-to-have).
- Both-layered whitelist+blacklist refusal (rejected D-P23-B1 as future-only).

---

## Claude's Discretion (no user decision needed)

Items downstream planner/researcher can resolve without user input:
- **Inline DDL syntax** — `ALTER TABLE long_term_facts ADD COLUMN IF NOT EXISTS embedding VECTOR(1024)` form (matches existing `_create_tables()` convention).
- **HNSW index name** — `ltf_emb_hnsw_idx` (matches the table's existing `ltf_user_idx` naming).
- **Test fixture file layout** — `tests/unit/test_extractor_adversarial.py`, `tests/unit/test_extractor_categories.py`, `tests/unit/fixtures/extractor/*.json` per existing test conventions.
- **`MemoryFactWriteError` location** — `services/memory/memory_service.py` next to existing imports; planner picks exact line.
- **Extractor singleton accessor** — `get_extractor()` (matches `get_planner()` / `get_executor()` / `get_verifier()` pattern).
