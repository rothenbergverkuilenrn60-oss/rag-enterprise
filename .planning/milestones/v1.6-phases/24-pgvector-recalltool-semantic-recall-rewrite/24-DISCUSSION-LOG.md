# Phase 24: pgvector RecallTool + semantic recall rewrite — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 24-pgvector-recalltool-semantic-recall-rewrite
**Areas discussed:** A (HNSW iterative_scan tuning), B (load_context vs RecallTool overlap), C (Recall result formatting), D (Backfill job ops shape)

---

## A — HNSW iterative_scan mode

### A1: iterative_scan mode

| Option | Description | Selected |
|--------|-------------|----------|
| `strict_order` | Returns exact top-k under WHERE prefilter; slower (~10-30% latency hit); matches ROADMAP + v1.1 Phase 8 chosen pattern | ✓ |
| `relaxed_order` | Walks HNSW graph until top-k filter-matches found; faster; may return suboptimal ordering under high-cardinality prefilter; matches `vector_store.py:322` precedent | |
| Make it configurable via settings | `settings.recall_iterative_scan` field; default strict_order; operator override | |

**User's choice:** strict_order. Resolves STATE.md Open Question #4.

### A2: ef_search tuning

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing `settings.pgvector_ef_search_filtered = 200` | Single tuning knob across both stores; avoids config-surface fragmentation | ✓ |
| New dedicated `pgvector_ef_search_memory` | Separate ef_search for facts vs chunks; smaller per-tenant rowcount may warrant different value | |
| Hardcode 200 in `get_relevant_facts` | No settings field; simplest; no ops knob | |

**User's choice:** reuse existing setting.

### A3: Minimum similarity cutoff

| Option | Description | Selected |
|--------|-------------|----------|
| Top-K only, no similarity floor | Always returns up to K facts; cosine quality assessed offline (SC-1) not runtime; matches chunks pattern | ✓ |
| `WHERE embedding <=> $query < 0.5` SQL floor | Drops weak matches; cleaner empty-result signal; risk of guessed threshold pre-deploy | |
| Configurable threshold (default off) | `settings.recall_min_similarity: float \| None = None`; operator opts in once eval data justifies | |

**User's choice:** top-K only, no floor.

### A4: Top-K default

| Option | Description | Selected |
|--------|-------------|----------|
| Keep K=5 default | Preserves existing signature; ~150 token prompt impact; tunable per-caller via limit param | ✓ |
| Lower to K=3 (matches extractor cap) | Symmetric mental model; ~40% token reduction; risk of cutting too aggressively | |
| K=10 for RecallTool, K=3 for load_context | Asymmetric per-call-site defaults; cleaner if Area B picks "shrink load_context K" | |

**User's choice:** keep K=5 default.

---

## B — load_context() vs RecallTool overlap

### B1: Overlap resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Keep both, accept potential double-fetch | load_context always-on + RecallTool refinement; simplest migration; ~150 + ~250 token cost | ✓ |
| Shrink load_context K to 1-2 + RecallTool broader | Halves always-on cost; risk of recall regression on turns where planner doesn't pick RecallTool | |
| Remove load_context entirely; RecallTool only | Cleanest separation; biggest semantic shift; risk planner doesn't pick RecallTool reliably | |

**User's choice:** keep both, accept duplicates.

### B2: Duplicate-fact dedup

| Option | Description | Selected |
|--------|-------------|----------|
| Accept duplicates in v1.6 | LLM dedupes at synthesis; ~30 tokens per dup; revisit in v1.7 if eval regression | ✓ |
| Dedup at planner-tool-result-merge | Compare RecallTool result against load_context list; drop string-exact matches; adds executor plumbing | |
| Dedup at SQL with row-exclusion list | Pass already-injected fact IDs as `WHERE id NOT IN (...)`; widens ToolContext surface | |

**User's choice:** accept duplicates in v1.6.

### B3: MEM-10 audit shape

| Option | Description | Selected |
|--------|-------------|----------|
| Length-only regression + prompt-budget measurement | Assert `len(ctx.long_term_facts) <= N` preserved + measure mean/p95 token delta to phase artifact | ✓ |
| Snapshot test — record current facts, assert new returns same set | Presumes popularity == query-relevance which it is NOT for the new contract; wrong test shape | |
| Behavioral regression — end-to-end answer-quality | Expensive (real LLM); slow CI; better as offline eval | |

**User's choice:** length-only regression + token-delta measurement.

### B4: RecallTool gating

| Option | Description | Selected |
|--------|-------------|----------|
| Always-pickable + `recall_tool_enabled` kill-switch | Mirror `extractor_enabled` (Phase 23); default True; operator can disable in ops emergency without code change | ✓ |
| Always-pickable, no kill-switch | Matches ROADMAP literal; rollback requires emergency PR if needed | |
| Gated behind `agent_mode=True` only | Controller-scoped opt-in; conflicts with request-scoped AGENT_TOOL_ALLOWLIST pattern | |

**User's choice:** always-pickable + `recall_tool_enabled` kill-switch.

---

## C — Recall result formatting

### C1: Result format

| Option | Description | Selected |
|--------|-------------|----------|
| Bulleted plain text, no metadata | `- fact1\n- fact2\n- fact3`; smallest token footprint; preserves `list[str]` shape | ✓ |
| JSON with importance + age | LLM can reason about freshness + confidence; ~3x tokens; no evidence planner uses metadata yet | |
| Bullets with importance suffix | `- fact (importance=0.8)`; ~1.3x tokens; marginal | |

**User's choice:** bulleted plain text.

### C2: Empty-result handling

| Option | Description | Selected |
|--------|-------------|----------|
| Empty string + explicit `No matching facts found.` marker | Prevents LLM from interpreting empty as 'tool failed'; 5 tokens; MCP best-practice convention | ✓ |
| Empty string only | Cheapest tokens but ambiguous signal; risk of planner retry loops | |
| Structured `{"facts": [], "reason": "no_match"}` | Overkill for v1.6; planner doesn't inspect tool-result JSON | |

**User's choice:** explicit "No matching facts found." marker.

### C3: Error handling

| Option | Description | Selected |
|--------|-------------|----------|
| Catch + return `ToolResult(content="Memory unavailable; proceed without recall.", error=True)` | Best-effort isolation (matches MEM-04); clear LLM signal; flagged for trace logs | ✓ |
| Let exception propagate to executor | Tool-failure path may halt or retry planner; inconsistent with Phase 23 pattern | |
| Return empty result (silent skip) | Indistinguishable from 'no facts found'; worst observability | |

**User's choice:** best-effort with `error=True` flag.

### C4: Tool description

| Option | Description | Selected |
|--------|-------------|----------|
| Use ROADMAP draft verbatim | Already includes positive + negative signal; matches web_search.py / retrieve.py prose style | ✓ |
| Refine with examples | Adds 1-2 concrete examples; ~20 extra tokens in EVERY planner prompt; marginal | |
| Refine with negative examples | Reduces over-firing; same token cost; same marginal-gain bet | |

**User's choice:** ROADMAP verbatim.

---

## D — Backfill job ops shape

### D1: Job shape

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone async CLI — run once + archive | `uv run python scripts/backfill_fact_embeddings.py [--dry-run] [--batch-size 100] [--resume-from-id N]`; idempotent via WHERE embedding IS NULL | ✓ |
| Standalone CLI + Kubernetes CronJob template | CLI plus CronJob YAML in docs; recurring ops; marginal value since save_fact covers steady state | |
| Async batch worker with progress + checkpoint file | Daemon-style with `--checkpoint`; overkill for small expected rowcount | |

**User's choice:** standalone CLI, run once + archive.

### D2: Rate limiting

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse `Embedder.embed_batch` + chunked-commit 100 rows/txn | OpenAI 2048/batch; tenacity handles 429; no explicit sleep | ✓ |
| Explicit `--qps N` flag + asyncio.sleep | Operator-tunable QPS bound; defensive for shared-quota tenants | |
| Per-batch token-budget tracker | Most defensive; most complex; overkill v1.6 | |

**User's choice:** reuse embed_batch + chunked-commit; no explicit QPS flag.

### D3: Mid-batch failure

| Option | Description | Selected |
|--------|-------------|----------|
| Roll back whole 100-row txn, log + exit non-zero | Simplest semantics; idempotent re-run skips 0 covered rows; matches Phase 23 zero-partial-write pattern | ✓ |
| Skip failed row, commit the rest | Best-effort; failed rows stay NULL for next-run retry; more complex bookkeeping | |
| Per-row commits (no batching) | Defeats chunked-commit MEM-07 spec; 100x commit overhead | |

**User's choice:** whole-batch txn rollback + non-zero exit.

### D4: Cost docs scope

| Option | Description | Selected |
|--------|-------------|----------|
| Companion section in `docs/memory-eviction.md` | ROADMAP-spec'd location; 30-50 lines covering cost formula + dry-run + rate-limit fallback | ✓ |
| Dedicated `docs/backfill-fact-embeddings.md` | Separate page; cleaner per-script ownership; deviates from ROADMAP literal | |
| Inline `--help` text only | Always visible from CLI; loses depth; combine with companion section | |

**User's choice:** companion section in `docs/memory-eviction.md`.

---

## Claude's Discretion

Items left to planner judgment (per CONTEXT.md `<decisions>` §Claude's Discretion):

- Tie-break ordering after cosine sort — ROADMAP literal `importance DESC, created_at DESC`.
- Tool `parameters_schema` JSON shape — verbatim from REQUIREMENTS MEM-08.
- `ToolContext` field access for RecallTool — mirror RetrieveTool/WebSearchTool patterns.
- Backfill `--dry-run` output format — standard CLI convention.
- RecallTool registration in `services/agent/tools/__init__.py` top-level — expected: yes.

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section. Summary:

- v1.7+ follow-ups: result metadata (C1.2), planner-tool-result-merge dedup (B2.2), load_context K shrink (B1.2), `--qps N` rate flag (D2.2), `recall_min_similarity` threshold (A3.3), CronJob backfill template (D1.2), SSE `memory.recalled` event.
- Re-confirmed v1.6 out-of-scope: cross-user-within-tenant recall, RLS enforcement on `long_term_facts`, per-tenant capacity overrides, importance decay, live planner `save_memory` tool, manual "remember this" UI.
