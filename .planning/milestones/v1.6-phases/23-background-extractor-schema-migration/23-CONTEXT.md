# Phase 23 — Background Extractor + schema migration

**Created:** 2026-05-15
**Phase goal (from ROADMAP.md):** Make `long_term_facts` agent-writable. Schema gains `embedding VECTOR(1024)` + HNSW cosine index via inline-DDL convention in `LongTermMemory._create_tables()` (no Alembic). New `services/agent/extractor.py` sub-agent reuses v1.5 verifier provider-singleton + `call_agentic_turn` + Pydantic-V2-frozen schema pattern, but dispatches background via `asyncio.create_task` + `utils/tasks.log_task_error`. Importance pinned to `{0.2, 0.5, 0.8}` buckets; per-turn cap N=3 facts; explicit refusal clause for policy-shaped / self-referential / role-redefinition inputs.
**Requirements:** MEM-01, MEM-02, MEM-03, MEM-04, MEM-05

<domain>
Background extraction of agent-authored long-term facts. Post-turn (NOT in critical path), the extractor sub-agent reads the just-finished (user_turn, ai_turn) exchange — **per eng-review A2 (2026-05-16), the original "ai_turn only" design was reversed because user-preference facts ("I prefer React", "I work in healthcare") live in `user_turn.content`, not the assistant's reply. Extractor now receives BOTH turns: `Extractor.run(user_turn, ai_turn)` and `dispatch_extraction(user_turn, ai_turn, user_id, tenant_id)`. Prompt format: `USER: {content[:2000]}\nASSISTANT: {content[:2000]}`. The "sub-agents do NOT inherit chat history" rule (v1.3 D-06) still holds — only this single exchange is visible, no scrollback.** Picks at most 3 memorable facts that match a whitelist of safe categories, scores each with a fixed importance bucket, and persists them with their embedding into `long_term_facts`. Phase 24 will rewrite the recall path; this phase only writes.
</domain>

<decisions>

### A — Embedding model for `long_term_facts.embedding`

**Locked:** Same as KB chunks. Use `settings.embedding_model` (default `text-embedding-3-large`, 1024-dim) via `services/vectorizer/embedder.py::Embedder.embed_one()`. Schema column `embedding VECTOR(1024)` matches `settings.embedding_dim`.

**Why:** Query embedding at recall time (Phase 24 RecallTool) is shared between `search_knowledge_base` and `recall_memory` — same model means same query vector, computed once, reused twice. Cross-store similarity stays comparable for future dedup work. Zero new infra; `save_fact` extension just calls existing `embed_one()` inside the function. Per-write cost is bounded by the N=3 per-turn cap × ~30-token average fact length — trivial fraction of total embedding spend vs full-document KB ingest.

**Rejected:**
- Smaller dedicated model (text-embedding-3-small, truncate to 1024): would force second adapter inside `services/vectorizer/embedder.py` AND either double-embed query at recall time or break cross-store comparison. Cheap-model experiment is a v1.7+ optimization once we have real usage data.
- Local Sentence-BERT (all-MiniLM-L6-v2, 384-dim): different dim breaks cross-store comparison; adds self-hosted inference container; quality drop on short facts.

### B1 — Refusal-clause shape

**Locked:** Whitelist (fail-closed). Extractor extracts ONLY facts that match a listed category; anything else is silently ignored. No blacklist; if a fact doesn't fit the listed shape, it does not get stored.

**Why:** Matches v1.0 Phase 2 security-hardening philosophy (explicit allowlist > deny-by-exception). Memory writes are a security-sensitive path — fail-closed is the correct default. Jailbreaks targeting a category not on the whitelist are silently rejected by the prompt without needing maintenance updates. The user can always restate the fact next turn; storing wrong facts is harder to fix than missing some.

**Rejected:**
- Blacklist (extract anything except forbidden): fail-OPEN; every new jailbreak category is a security hole until the blacklist is updated.
- Both layered (whitelist + per-category blacklist): longer prompt; two rules to maintain. Add in v1.7+ only if a sub-category gotcha emerges within the whitelist.

### B2 — Whitelisted categories + importance bucket mapping

**Locked:** Exactly three categories, 1:1 mapped to importance buckets:

| Category | Importance | Examples |
|---|---|---|
| `stable_preferences` | **0.8** | "user prefers React over Vue", "user works in healthcare", "user is an experienced backend engineer" |
| `recurring_topics` | **0.5** | "user often asks about Postgres performance", "user is exploring agentic patterns", "user's domain is enterprise RAG" |
| `transient_context` | **0.2** | "user is currently working on v1.6 Memory tool milestone", "user is debugging an HNSW index issue today" |

**Why:** Each importance bucket has exactly one category triggering it — zero LLM disambiguation ambiguity. Maps cleanly to lifecycle: stable lives ~forever, recurring decays via use, transient gets evicted first. Importance rubric is also the Phase 25 eviction priority — lowest evicted first.

**Rejected:**
- 2-bucket (drop transient, 0.2 unused): loses the transient-vs-recurring distinction; project context same weight as long-running topic interest.
- 4-category mapped to 3 buckets (identity=0.8, preference=0.8 split): identity-vs-preference distinction is a v1.7+ nice-to-have; adds prompt complexity for marginal downstream value.

**Extractor output schema (locked):** Pydantic V2 frozen model `ExtractedFact` with fields:
- `fact: str` (the fact text, ≤200 chars enforced by validator)
- `category: Literal["stable_preferences", "recurring_topics", "transient_context"]`
- `importance: Literal[0.2, 0.5, 0.8]` (must match the bucket for `category`; cross-field validator enforces)

`Extractor.run(turn) -> list[ExtractedFact]` with `len <= 3` (per-turn cap enforced post-LLM, truncating to top-3 by importance if LLM returns more).

### D — Wire-in behavior on auth edge cases

**Locked:** Log-then-skip. When the request context lacks `user_id` or `tenant_id` (anonymous mode, broken JWT, service-account without user claim), the extractor dispatch wrapper writes a structured-log entry with `operation="extractor_skipped"` + `reason ∈ {"missing_user_id", "missing_tenant_id"}` and returns without firing `asyncio.create_task`. No fact written. No exception raised. User-facing turn unaffected.

**Why:** Extraction is best-effort — must never fail the user turn. Silent skip would hide misconfigured prod auth as an invisible regression. Structured-log entry gives ops visibility (grep `extractor_skipped` finds auth misconfig) without breakage. Matches v1.0 Phase 3 narrow-exception + structured-log pattern.

**Rejected:**
- Silent skip: invisible regression risk.
- Raise typed error caught by `log_task_error`: functionally equivalent to log-then-skip but noisier (error-level vs info-level).
- Empty-string fallback (`tenant_id=''`): multi-tenant isolation regression — anonymous turns from tenant A would pollute the empty-tenant bucket and be recallable by tenant B's anonymous turns. Security regression masquerading as a feature.

**Implementation note (for planner):** Dispatch wrapper is the place to check, NOT inside `Extractor.run()`. Wrapper signature (**A2-amended 2026-05-16**): `dispatch_extraction(user_turn: ConversationTurn, ai_turn: ConversationTurn, user_id: str | None, tenant_id: str | None) -> None`. Wrapper does the precondition check (kill-switch FIRST, then `user_id`, then `tenant_id`), then `task = asyncio.create_task(_run_and_persist(...), name="extractor"); task.add_done_callback(log_task_error)`.

</decisions>

<deferred>

### Deferred to Phase 23 RESEARCH (will be answered before PLAN)

- **Cost guard / `agent_mode` gating** (STATE.md OQ#2). Extractor adds one background LLM call per turn. Always-on vs gated behind `agent_mode=True` opt-in (matches v1.2 D1 pattern). DEFER: researcher costs out per-turn token spend × expected QPS; planner picks based on real numbers. First-line cost bound (N=3 per-turn cap) is already locked.
- **Extractor LLM provider + model selection.** Reuse the existing `BaseLLMClient` provider singleton (matches verifier pattern). But should extractor use a cheaper / faster model (e.g. `gpt-4o-mini` / `claude-haiku-4-5`) than the user-facing turn? Researcher to gather model-choice evidence; planner decides.

### Deferred to Phase 24 PLAN

- **HNSW `iterative_scan` mode for memory recall** (STATE.md OQ#4). Design doc said `strict_order`; code precedent at `services/vectorizer/vector_store.py:322` uses `'relaxed_order'`. Decision lives in Phase 24 PLAN — Phase 23 only ships the HNSW DDL (no scan-mode tuning in CREATE INDEX statement). Note for Phase 24: precedent leans `relaxed_order`; design doc claim was a doc-not-code observation.
- **Recall result formatting.** Plain text vs JSON with importance + age metadata. Phase 24-only concern.

### Out of v1.6 scope (do not raise again until v1.7+)

- Live planner-callable `save_memory` tool (mid-conversation writes) — rejected in /office-hours D3.
- User-facing "remember this" manual UI — rejected in /office-hours D3.
- Cross-user-within-tenant recall — out per design doc Premise 3.
- SSE `memory.extracted` event — out per design doc Premise 5; deferred to v1.7.

</deferred>

<canonical_refs>

**MANDATORY: every relative path verified against the working tree on 2026-05-15.**

### Locked-requirement source
- `.planning/REQUIREMENTS.md` — REQ-IDs MEM-01 through MEM-05 mapped to this phase
- `.planning/ROADMAP.md` — Phase 23 section: goal, depends-on, canonical refs, 5 success criteria
- `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-master-design-20260515-211345.md` — APPROVED design doc; Premise 4 (verifier reuse map) + Premise 8 (adversarial-extraction risk)

### Pattern sources (extractor reuse)
- `services/agent/verifier.py` — provider-singleton (line 99), `_resolve_llm()` (line 103), `verify()` (line 114), `call_agentic_turn` invocation (line 134), `_build_prompt` (line 154), `_parse` (line 172). Extractor copies this skeleton.
- `services/agent/executor.py:187` — `asyncio.create_task` parallel-burst pattern (reference for background dispatch shape)
- `services/events/event_bus.py:18,132-133,171-172` — `from utils.tasks import log_task_error` + `task.add_done_callback(log_task_error)` exact wiring
- `utils/tasks.py:14` — `log_task_error(task: asyncio.Task) -> None` done-callback signature
- `services/generator/llm_client.py::BaseLLMClient.call_agentic_turn` — text-only provider-neutral invocation

### Write path (extend, not replace)
- `services/memory/memory_service.py:143-182` — `LongTermMemory._create_tables()` DDL site; ALTER TABLE goes inline here
- `services/memory/memory_service.py:255-269` — `save_fact()` current signature (user_id, tenant_id, fact, source_doc="", importance=0.5); rewrite computes embedding internally before INSERT
- `services/memory/memory_service.py:236-254` — `get_relevant_facts()` is NOT modified in Phase 23 (Phase 24 rewrites)

### Embedding adapter (reuse)
- `services/vectorizer/embedder.py:29` — `embed_batch(texts) -> list[list[float]]` ABC
- `services/vectorizer/embedder.py:32` — `embed_one(text) -> list[float]` ABC
- `services/vectorizer/embedder.py:44,80-81` — `settings.embedding_model` resolution (default `text-embedding-3-large`)
- `services/vectorizer/vector_store.py:129` — `settings.embedding_dim` (default 1024) — schema dim source
- `services/vectorizer/vector_store.py:173-225` — HNSW DDL precedent: `CREATE INDEX IF NOT EXISTS {table}_vec_idx ON {table} USING hnsw (embedding vector_cosine_ops)` (line 181-182)

### Wire-in sites (post-turn dispatch)
- `services/pipeline.py:383, 793, 1227` — `get_memory_service()` instantiations in QueryPipeline / AgentQueryPipeline / SwarmQueryPipeline `__init__`
- `services/pipeline.py:427, 606, 960, 1051` — `load_context(...)` call sites (audited in Phase 24 for semantic shift; Phase 23 does NOT modify these)
- `services/pipeline.py::AgentQueryPipeline.run` + `SwarmQueryPipeline.run` — `save_turn` happens already inside; extractor dispatch attaches AFTER `save_turn` (planner: pick the exact attach point)

### Invariants (read once before planning)
- `CLAUDE.md` — narrow exception types, Tenacity for external calls, structured logging
- v1.3 D-06 — sub-agents do NOT inherit chat history
- v1.3 Phase 12 — `BaseException` (not `Exception`) for asyncio.gather isolation
- v1.4 Phase 16 — Planner/Executor/Synthesizer triad contracts frozen; this phase does NOT touch them

</canonical_refs>

<code_context>

### Reusable assets (no need to invent)
- **Verifier skeleton** — `services/agent/verifier.py` is 176 lines; extractor will be similar shape (provider-singleton, `_resolve_llm`, `run` async method, `_build_prompt`, `_parse`). Estimated extractor.py size: ~150-200 LOC.
- **`log_task_error`** — `utils/tasks.py:14`. Use AS-IS via `task.add_done_callback(log_task_error)`. NO new background-isolation infra needed.
- **`Embedder.embed_one`** — `services/vectorizer/embedder.py:32`. Existing API; `save_fact` rewrite calls it before INSERT.
- **Inline DDL pattern** — `LongTermMemory._create_tables()` already runs `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` on every pool init. Adding `ALTER TABLE long_term_facts ADD COLUMN IF NOT EXISTS embedding VECTOR(1024)` + a second `CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx ...` fits the existing pattern. No new Alembic dependency.

### Integration points
- **Pipeline wire-in:** `AgentQueryPipeline.run` and `SwarmQueryPipeline.run` are the two pipelines that should fire extraction. `QueryPipeline.run` (non-agentic legacy path) — defer to planner whether to wire (no agent reasoning happens there; arguably less valuable). Planner decides.
- **ConversationTurn type:** existing dataclass in `services/memory/memory_service.py:21`. Extractor accepts `ConversationTurn` plus `user_id` + `tenant_id` (passed separately, not inferred from turn).
- **MemoryFactWriteError:** new typed exception (per MEM-02). Define in `services/memory/memory_service.py` next to existing imports. Wraps either asyncpg.PostgresError OR embedding-adapter failure.

### Things to watch for (pitfalls)
- **`HNSW index build cost on populated table:** `long_term_facts` is currently empty in dev/test environments, but if any prod tenant has rows already, HNSW build is bounded by row count. Inline DDL pattern uses `CREATE INDEX IF NOT EXISTS` — idempotent, safe.
- **Embedding API failure inside `save_fact`:** must NOT silently swallow. New `MemoryFactWriteError` carries the underlying cause. The dispatch wrapper's `log_task_error` callback will surface it via the task done-handler.
- **Extractor latency for the per-turn cap:** N=3 cap is enforced AFTER the LLM returns. If the LLM returns 5 facts, post-process keeps top-3 by importance (tie-break: declaration order). Don't pass cap to the prompt as a hard limit — prompts that say "max 3" sometimes return exactly 0; let the LLM be expressive then truncate.
- **`text-embedding-3-large` returns 3072-dim by default** — the existing `services/vectorizer/embedder.py:80-81` resolution uses `settings.embedding_model` which is configured to truncate or use 1024-dim output. Planner: verify the existing embedder honors `settings.embedding_dim=1024`. If it doesn't, this is a `save_fact`-internal truncation step.

</code_context>

<next_steps>

1. `/clear` then `/gsd-plan-phase 23` — researcher will investigate OQ#2 cost data + OQ extractor model selection; planner will produce 23-XX-PLAN.md files for the 5 REQs.
2. After PLAN.md exists: `/plan-eng-review` (highest-leverage check spot for v1.6 per /office-hours D handoff).
3. Then `/gsd-execute-phase 23`.

</next_steps>

---

*Discussion via /gsd-discuss-phase. 3 areas (A: embedding model, B: extractor prompt + categories, D: wire-in auth edge cases) deep-dived; 4 AskUserQuestion turns + 1 area-selection turn. Cost-guard area C deferred to Phase 23 RESEARCH per workflow philosophy "research investigates, planner decides on numbers."*
