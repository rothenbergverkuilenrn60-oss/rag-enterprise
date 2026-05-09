# Phase 13: LLM Filter Fallback - Discussion Log

**Date:** 2026-05-09
**Phase:** 13 (NLU-02)

## Gray Areas Selected

User selected ALL 4 gray areas:
- Module structure
- Cache layer
- Async interface
- Prompt + JSON enforcement

## Q&A Trail

### Round 1: Primary architecture

**Q1: Module structure — function extension vs class refactor?**
- A: Extend existing function (smaller diff)
- B: FilterExtractor class refactor (matches AC#1 literal) ← **Selected**
- C: Composite (function + wrapper class)

**Decision (D-01):** FilterExtractor class with `async def extract()` + `get_filter_extractor()` singleton.
**Reason:** Matches AC#1 wording verbatim. Aligns with project's class-with-singleton pattern (`get_query_pipeline`, `get_agent_pipeline`, `get_swarm_pipeline`).

---

**Q2: Cache layer — Redis vs lru_cache vs async-lru?**
- A: Redis with cache_ttl_sec ← **Selected**
- B: functools.lru_cache (in-process)
- C: async-lru package

**Decision (D-05):** Redis via `utils/cache.py`.
**Reason:** AC#2 says "TTL matching the existing cache layer" — Redis matches verbatim. Multi-worker safe (gunicorn). lru_cache lacks TTL. async-lru is unnecessary new dep.

---

**Q3: Async interface?**
- A: Make extract async ← **Selected**
- B: Sync regex + async LLM split
- C: asyncio.run inside sync (REJECT — anti-pattern)

**Decision (D-07):** `async def extract()`. 4 callsites in `services/pipeline.py` migrate to `await`.
**Reason:** Pipeline contexts already async. 4-line callsite change is contained. Avoids split API.

---

**Q4: Prompt + JSON enforcement?**
- A: chat() + try/except json.loads ← **Selected**
- B: chat_with_tools forced schema
- C: Hybrid (tools-first with chat fallback)

**Decision (D-10):** chat() + try/except. Matches Phase 12 coordinator pattern. ERR-01 narrow exception tuple for parse failures.
**Reason:** Single-shot structured extraction doesn't need tool-schema overhead. JSON-only prompt + json.loads in try/except is simpler and consistent with Phase 12.

---

### Round 2: Follow-ups uncovered during architecture

**Q5: AC#1 says `-> QueryFilter | None` but 2/4 callsites use `extraction.semantic_query` — how to preserve it?**
- A: Wrap: `ExtractionResult{filter, semantic_query, fallback_source}` ← **Selected**
- B: Strict AC#1 (drop semantic_query, callers rebuild)
- C: QueryFilter has semantic_query field

**Decision (D-03):** `ExtractionResult` dataclass with `filters`, `semantic_query`, `fallback_source` fields.
**Reason:** Pragmatic interpretation of AC#1. 2/4 callsites consume semantic_query (`pipeline.py:318, :479`) — breaking that API is unjustified churn. Wrapper preserves all data; truthiness on `.filters` works at all callsites.

---

**Q6: LLM model — Haiku via task_type='nlu'?**
- A: task_type='nlu' (Haiku) ← **Selected**
- B: task_type='generate' (main model)
- C: task_type='classify' (also Haiku)

**Decision (D-09):** `task_type="nlu"` → Haiku per Phase 11 routing.
**Reason:** Verified at `services/generator/llm_client.py:133, 317, 593`. NLU is exactly this use case. ~3x cheaper than Sonnet, sufficient accuracy for structured extraction.

---

**Q7: fallback_source semantics on regex partial hit?**
- A: regex empty → LLM; regex non-empty → stop (no merge) ← **Selected**
- B: Always try LLM, merge if regex partial
- C: force_llm parameter for caller

**Decision (D-11):** LLM ONLY when regex returns empty filters. No merge. fallback_source single-valued: `"regex"` | `"llm"` | `None`.
**Reason:** Matches AC#1 literal "LLM only when regex returns None". Simpler semantics. Avoids cost of always-LLM.

---

## All 9 Decisions Locked (D-01 through D-15)

See `13-CONTEXT.md` `<decisions>` block. Categories:
- Architecture (D-01, D-02)
- Return Type (D-03, D-04)
- Cache Layer (D-05, D-06)
- Async Interface (D-07, D-08)
- LLM Model + Prompt (D-09, D-10)
- Fallback Source Semantics (D-11, D-12)
- Failure Handling (D-13, D-14)
- Testing (D-15)

## Out of Scope (Deferred)

- English-language patterns (frozen v1.1 D-03)
- Multi-filter merge across sub-questions
- Streaming LLM responses
- LLM-based semantic_query rewriting

## Next Action

Run `/gsd-plan-phase 13` to research + plan Phase 13.
