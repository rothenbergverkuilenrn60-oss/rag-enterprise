# Roadmap — EnterpriseRAG

## Milestones

- ✅ **v1.0 Hardening** — Phases 1–6 (shipped 2026-04-27) — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** — Phases 7–10 (shipped 2026-05-08) — [archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Agentic Layer + Swarm** — Phase 11 (shipped 2026-05-08) — [archive](milestones/v1.2-ROADMAP.md)
- 🚧 **v1.3 Fork Swarm, NLU & Quality** — Phases 12–15 (in progress)

## Phases

<details>
<summary>✅ v1.0 Hardening (Phases 1–6) — SHIPPED 2026-04-27</summary>

- [x] Phase 1: pgvector Foundation (4/4 plans) — completed 2026-04-22
- [x] Phase 2: Security Hardening + Operational Fixes (3/3 plans) — completed 2026-04-23
- [x] Phase 3: Error Handling Sweep (3/3 plans) — completed 2026-04-24
- [x] Phase 4: Image Extraction (4/4 plans) — completed 2026-04-25
- [x] Phase 5: Async Ingest Tracking (3/3 plans) — completed 2026-04-26
- [x] Phase 6: Test Coverage and Eval (3/3 plans) — completed 2026-04-27

See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.1 Retrieval Depth & Frontend (Phases 7–10) — SHIPPED 2026-05-08</summary>

- [x] Phase 7: OCR Engine Integration (2/2 plans) — completed 2026-05-08
- [x] Phase 8: Multimodal Metadata + Query Filter (5/5 plans) — completed 2026-05-08
- [x] Phase 9: Frontend Extraction (1/1 plan) — completed 2026-05-08
- [x] Phase 10: Coverage Gate on New Code (1/1 plan) — completed 2026-05-08

See [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.2 Agentic Layer + Swarm (Phase 11) — SHIPPED 2026-05-08</summary>

- [x] Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst (4/4 plans) — completed 2026-05-08

See [milestones/v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md) for full phase details.

</details>

### v1.3 Fork Swarm, NLU & Quality

- [x] **Phase 12: Fork-Agent Swarm** — Coordinator decomposes multi-dimension queries; N sub-agents run isolated `call_agentic_turn` loops concurrently; synthesis LLM call produces final unified answer (completed 2026-05-09)
- [ ] **Phase 13: LLM Filter Fallback** — `FilterExtractor` gains a confidence-gated LLM fallback that activates only when regex returns empty; cached per query; fallback source traced in returned filter (Wave 1 complete; Wave 2 + 3 pending)
- [ ] **Phase 14: Frontend Split and DOM Modernization** — JS and CSS extracted from `static/ui.html` into `static/ui.js` / `static/ui.css`; inline event handlers replaced with `addEventListener`; StaticFiles config unchanged
- [ ] **Phase 15: Coverage Combine and 70% Floor** — CI wired to emit `.coverage.unit` + `.coverage.integration` and combine them; global floor raised from 46% to 70% backed by new unit tests on undercovered service modules

## Phase Details

### Phase 12: Fork-Agent Swarm
**Goal**: Users issuing multi-dimension queries with `agent_mode=True` receive answers that fully address every sub-question, produced by N independent sub-agents running concurrently with isolated context
**Depends on**: Phase 11 (v1.2 `call_agentic_turn` abstraction)
**Requirements**: AGENT-03
**Success Criteria** (what must be TRUE):
  1. A multi-dimension query (N ≥ 2 sub-questions) dispatches N sub-agents, each holding its own `messages` list and `max_iterations` budget; no sub-agent reads or writes another's message history
  2. All N sub-agents execute concurrently; total latency is bounded by the slowest sub-agent, not the sum
  3. The coordinator emits a final synthesized answer that explicitly references results from all N sub-agents
  4. A swarm invocation with more sub-questions than `MAX_SWARM_AGENTS` (default 5) is capped; sub-agents exceeding `MAX_SWARM_TURNS_PER_AGENT` (default 5) stop cleanly without error
  5. The audit log for every swarm invocation records N, per-agent turn count, per-agent tool calls, swarm latency, and synthesis latency
**Plans**: 12-01 (Wave 1 — data-model foundations) ✅ complete; 12-02 (Wave 2 — SwarmQueryPipeline core) ✅ complete; 12-03 (Wave 3 — routing + tests) pending
**UI hint**: no

### Phase 13: LLM Filter Fallback
**Goal**: Users whose queries use natural language section references (not covered by regex) get correctly filtered retrieval, with zero extra cost on queries the regex already handles
**Depends on**: Phase 8 (regex filter extractor baseline, QUERY-01)
**Requirements**: NLU-02
**Success Criteria** (what must be TRUE):
  1. A query matching the existing regex pattern returns a `QueryFilter` without ever calling the LLM
  2. A query using a natural language section reference (e.g., "关于第三章的内容") that the regex misses returns the correct `QueryFilter` via the LLM fallback path
  3. An LLM response that is invalid JSON or missing required fields is silently caught; the caller receives `None` (no filter), not an exception
  4. Submitting the same unmatched query N times results in exactly one LLM call; subsequent calls hit the cache
  5. Every returned `QueryFilter` carries a `fallback_source` field set to `"regex"`, `"llm"`, or `None`, visible in logs
**Plans**:
  - [x] 13-01-PLAN.md (Wave 1) — Add `FilterExtractor` class, `ExtractionResult` dataclass, `_FILTER_EXTRACT_SYSTEM` prompt, and `get_filter_extractor()` singleton to `services/nlu/filter_extractor.py`. Existing regex helper preserved (D-02). ✅ complete 2026-05-09 (commits 7ef9135, 660023b)
  - [ ] 13-02-PLAN.md (Wave 2) — Migrate 4 callsites in `services/pipeline.py` from sync `extract_filters(req.query)` to `await get_filter_extractor().extract(req.query)`.
  - [ ] 13-03-PLAN.md (Wave 2, parallel with 13-02) — Wrap existing 7 regex tests + add 6 new unit tests for FilterExtractor + create live-LLM integration test.
**UI hint**: no

### Phase 14: Frontend Split and DOM Modernization
**Goal**: Developers can edit JavaScript and CSS in separate files without opening a monolithic HTML file; the running UI is visually identical to the pre-split version
**Depends on**: Phase 9 (StaticFiles mount + ui.html baseline, UI-01)
**Requirements**: UI-02
**Success Criteria** (what must be TRUE):
  1. `static/ui.html` contains no `<script>` block with inline JavaScript and no `<style>` block with inline CSS; it references `ui.js` and `ui.css` only
  2. FastAPI serves `static/ui.js` and `static/ui.css` alongside `ui.html` with no configuration changes; the `index.html → ui.html` symlink and StaticFiles mount are unchanged
  3. No `onclick=`, `onsubmit=`, or other inline event handlers remain in `ui.html`; all event wiring lives in `ui.js` via `addEventListener`
  4. The UI renders identically to the pre-split version for the document upload, query submission, and result display flows
**Plans**: TBD
**UI hint**: yes

### Phase 15: Coverage Combine and 70% Floor
**Goal**: The CI coverage report accurately reflects all exercised paths (unit + integration combined), and the global floor blocks merges that drop below 70%
**Depends on**: Phase 10 (diff-cover gate, TEST-03); Phase 12 (new swarm code must be covered); Phase 13 (new fallback code must be covered); Phase 14 (any new backend code must be covered)
**Requirements**: TEST-04, TEST-06
**Success Criteria** (what must be TRUE):
  1. CI produces two separate `.coverage` files (unit and integration) and combines them before reporting; `coverage report` and `coverage xml` both run on the combined artifact
  2. `coverage report --fail-under=70` on the combined artifact passes in CI; a PR that drops coverage below 70% is blocked
  3. The per-file diff-cover gate (TEST-03, ≥ 80% on touched files) continues to run independently on the same combined `.coverage` without regression
  4. Service modules that were below 70% threshold at v1.2 close have new unit tests covering their primary execution paths
  5. CI artifacts include a per-module coverage breakdown making remaining gaps immediately visible
**Plans**: TBD
**UI hint**: no

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. pgvector Foundation | v1.0 | 4/4 | Complete ✓ | 2026-04-22 |
| 2. Security Hardening + Operational Fixes | v1.0 | 3/3 | Complete ✓ | 2026-04-23 |
| 3. Error Handling Sweep | v1.0 | 3/3 | Complete ✓ | 2026-04-24 |
| 4. Image Extraction | v1.0 | 4/4 | Complete ✓ | 2026-04-25 |
| 5. Async Ingest Tracking | v1.0 | 3/3 | Complete ✓ | 2026-04-26 |
| 6. Test Coverage and Eval | v1.0 | 3/3 | Complete ✓ | 2026-04-27 |
| 7. OCR Engine Integration | v1.1 | 2/2 | Complete ✓ | 2026-05-08 |
| 8. Multimodal Metadata + Query Filter | v1.1 | 5/5 | Complete ✓ | 2026-05-08 |
| 9. Frontend Extraction | v1.1 | 1/1 | Complete ✓ | 2026-05-08 |
| 10. Coverage Gate on New Code | v1.1 | 1/1 | Complete ✓ | 2026-05-08 |
| 11. Provider-Agnostic Agentic Layer + Parallel Burst | v1.2 | 4/4 | Complete ✓ | 2026-05-08 |
| 12. Fork-Agent Swarm | v1.3 | 3/3 | Complete    | 2026-05-09 |
| 13. LLM Filter Fallback | v1.3 | 0/3 | Planned | — |
| 14. Frontend Split and DOM Modernization | v1.3 | 0/TBD | Not started | — |
| 15. Coverage Combine and 70% Floor | v1.3 | 0/TBD | Not started | — |

## Coverage Validation

All 5 v1.3 REQ-IDs map to exactly one phase:

| REQ-ID | Track | Phase |
|--------|-------|-------|
| AGENT-01 (E-1) | E — Agentic Layer | Phase 11 |
| AGENT-02 (E-2) | E — Agentic Layer | Phase 11 |
| AGENT-03 (E-3) | E — Agentic Layer | Phase 12 |
| NLU-02 | NLU — Query Understanding | Phase 13 |
| UI-02 | UI — Frontend | Phase 14 |
| TEST-04 | TEST — Coverage | Phase 15 |
| TEST-06 | TEST — Coverage | Phase 15 |

**Coverage:** 5/5 v1.3 requirements mapped ✓
**Orphans:** none
**Duplicates:** none
