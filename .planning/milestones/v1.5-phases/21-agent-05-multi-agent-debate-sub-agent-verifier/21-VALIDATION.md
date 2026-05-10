# Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier — Nyquist Validation

**Generated:** 2026-05-10
**Author:** gsd-researcher
**Policy:** `.planning/config.json` workflow.nyquist_validation == true
**Companion:** `21-RESEARCH.md` (TDD pre-classification + branch enumeration)

---

## Nyquist Principle (this phase)

Every requirement has at least ONE measurable test signal sampled at a rate strictly higher than the rate at which the requirement could regress. Phase 21 has 3 requirements (AGENT-05, AGENT-14, AGENT-15) and 5 ROADMAP success criteria (SC1..SC5); ALL of them get evidence-frequency mapping below.

**Sampling rate definitions** (calibrated to v1.5 dev cadence):
- **Per-task** = pytest run on touched module(s); triggered by every implementation commit (~minutes).
- **Per-wave** = pytest unit suite + diff-cover on the wave's diff; triggered before wave merge (~hours).
- **Per-phase** = full unit suite + integration tier + combined coverage gate; triggered before `/gsd-verify-work` (~daily).

A requirement that COULD regress at commit-time MUST be sampled per-task. A requirement that could regress at integration-time (provider behavior, latency on real LLM) is sampled per-phase.

---

## Requirement → Evidence map

### AGENT-05 — `Verifier` class with text-only call_agentic_turn, forbid invention, forced-disagree

| Sub-claim | Test signal | Test file:case | Sampling | Branch in 21-RESEARCH §"Coverage Branch Enumeration" |
|-----------|-------------|----------------|----------|------------------------------------------------------|
| Verifier class exists at `services/agent/verifier.py::Verifier` | import test asserts symbol available | `tests/unit/test_verifier.py::test_verifier_imports` | per-task | structural |
| `verify(peer_results, evidence, user_query) → VerifierVerdict` signature | mypy type check + signature inspection | `tests/unit/test_verifier.py::test_verify_signature` | per-task | structural |
| Uses `call_agentic_turn(..., tools=[])` text-only (CF-03) | mock asserts tools kwarg == [] | `tests/unit/test_verifier.py::test_verify_calls_text_only` | per-task | B-01..B-03 |
| System prompt forbids inventing facts | string-presence assertion in `_VERIFIER_SYSTEM` for "不得编造" / "no invention" semantics | `tests/unit/test_verifier.py::test_system_prompt_forbids_invention` | per-task | structural |
| `verdict=="agree"` AND empty `evidence_chunk_ids` → forced to "disagree" (CF-04) | mock LLM returns agree+empty; assert returned verdict.verdict == "disagree" | `tests/unit/test_verifier.py::test_forced_disagree_on_no_evidence` | per-task | B-02 |
| `proposed_answer` always populated (D-02) | parametrized test agree-path + disagree-path both have non-empty proposed_answer | `tests/unit/test_verifier.py::test_proposed_answer_always_populated` | per-task | B-01..B-03 |
| Defensive chunk-id filter | mock LLM cites "c99" not in evidence; assert returned evidence_chunk_ids excludes "c99" | `tests/unit/test_verifier.py::test_defensive_chunk_id_filter` | per-task | B-09 |

### AGENT-14 — `GenerationRequest.debate` field + verifier hop + latency contract + unchanged on debate=False

| Sub-claim | Test signal | Test file:case | Sampling | Branch |
|-----------|-------------|----------------|----------|--------|
| `GenerationRequest.debate: bool = False` field exists | construct test: GenerationRequest() → debate is False | `tests/unit/test_models.py::test_debate_field_default_false` | per-task | structural |
| D-10 cross-field validator: debate=True + swarm_mode=False → ValueError | parametrized: pytest.raises(ValueError) | `tests/unit/test_models.py::test_debate_requires_swarm_mode` | per-task | B-31 |
| Verifier hop appended after `asyncio.gather` (when req.debate=True) | mock SwarmQueryPipeline run → assert order: gather → dedup → verify → synth | `tests/unit/test_swarm_pipeline.py::test_verifier_hop_runs_after_gather` | per-task | B-17 |
| **Latency contract: total ≤ max(peer) + verifier + small_overhead (SC2/CF-06)** | synthetic asyncio.sleep on peers + verifier; assert elapsed_ms ∈ (max+overhead-floor, max+overhead-ceiling) | `tests/unit/test_swarm_pipeline.py::test_debate_latency_bounded_by_max_plus_verifier` | per-task (unit) + per-phase (integration smoke at `tests/integration/test_swarm_debate_e2e.py`) | B-21 |
| `debate=False` → byte-identical run (SC5/CF-08) | identical mock script run with debate=False vs debate=True; assert: zero new events, identical answer text on debate=False; verify swarm answer is unchanged | `tests/unit/test_swarm_pipeline.py::test_debate_false_byte_identical_to_v13_swarm` | per-task | B-16 |
| Single verifier call, NOT N (latency budget assumption) | mock asserts `verifier._llm.call_agentic_turn` awaited exactly once | `tests/unit/test_verifier.py::test_verify_single_llm_call` | per-task | structural |

### AGENT-15 — 3 SSE event types as frozen Pydantic V2 subclasses + emit through existing route + synthesizer.final terminal + doc extension

| Sub-claim | Test signal | Test file:case | Sampling | Branch |
|-----------|-------------|----------------|----------|--------|
| `VerifierStartEvent` is frozen Pydantic V2 subclass of AgentEvent | construct + frozen-mutation rejection + isinstance(AgentEvent) | `tests/unit/test_models.py::test_verifier_start_event_shape` | per-task | B-30 |
| `VerifierCompleteEvent` is frozen Pydantic V2 subclass | same | `tests/unit/test_models.py::test_verifier_complete_event_shape` | per-task | B-30 |
| `VerifierDisagreementEvent` is frozen Pydantic V2 subclass + 3 reason values | construct + Literal validation on reason | `tests/unit/test_models.py::test_verifier_disagreement_event_shape` | per-task | B-30 |
| Wire format unchanged (event: <type>\ndata: <json>\n\n) | call `emit_sse_frame` on each new event class; assert format | `tests/unit/test_models.py::test_verifier_events_emit_sse_format` | per-task | B-30 |
| Events emit through `/api/v1/agent/v1/run/stream` (option B from RESEARCH P-05) | route-test: req.swarm_mode=True + req.debate=True → SSE stream contains all 3 event types | `tests/unit/test_agent_stream_route.py::test_swarm_debate_events_reach_route` | per-task | structural integration |
| `synthesizer.final` remains terminal in all paths (CF-07) | event-stream test: last event in (debate=False, debate=True+agree, debate=True+disagree, debate=True+failed) is always SynthesizerFinalEvent | `tests/unit/test_swarm_pipeline.py::test_synthesizer_final_terminal_in_all_paths` | per-task | B-17..B-20 |
| `docs/agent-architecture.md` extended with 3 new subsections | grep test asserts presence of "### verifier.start", "### verifier.complete", "### verifier.disagreement" | `tests/unit/test_docs.py::test_event_schema_reference_includes_verifier_events` (or simple grep in CI) | per-wave | structural |

---

## Success Criterion → Evidence map (ROADMAP §Phase 21)

| SC# | ROADMAP claim | Primary test | Sampling | Notes |
|-----|---------------|--------------|----------|-------|
| **SC1** | Verifier class implemented; verify() signature; text-only call_agentic_turn; system prompt forbids invention; forced-disagree on agree+empty | tdd-2 cases 1, 2, 3, 9; B-01, B-02, B-09 | per-task | All sub-claims have a unit case in `tests/unit/test_verifier.py` |
| **SC2** | `total ≤ max(peer_latency) + verifier_latency + small_overhead`; not sum, not N×verifier | unit: synthetic delay test (B-21); integration: live LLM e2e with synthetic peer slowness | per-task + per-phase | Unit asserts the structural contract; integration verifies it doesn't degrade on real provider latency variance |
| **SC3** | 3 new SSE event types as frozen Pydantic V2 subclasses; emit through existing route; wire format unchanged; `synthesizer.final` terminal | tdd-1 cases 5–9; B-30; route test in `test_agent_stream_route.py` | per-task | Wire format is preserved by the existing `emit_sse_frame` (no serializer change) |
| **SC4** | `docs/agent-architecture.md` Event Schema Reference extended with 3 new subsections + payloads + backward-compat note | doc grep test + manual review | per-wave | Backward-compat note structurally verified by string-presence test |
| **SC5** | RLS isolates tenants (inherited); audit log records verifier subagent calls; combined coverage ≥ 70%; no production code change when debate=False | RLS: existing pgvector RLS test (`tests/integration/test_pgvector_rls.py`); audit: tdd-4 case 7 (B-22); coverage: pytest --cov reports diff-cover ≥ 70%; SC5 byte-identity: tdd-4 case 1 (B-16) | per-phase | Coverage gate is the project-wide combine job (Phase 15 D-08 `parallel = false` topology) |

---

## Test Suite Topology (Wave 0 prerequisite)

| File | Status | Action in Wave 0 |
|------|--------|------------------|
| `tests/unit/test_verifier.py` | NEW | Create empty file with shared fixtures (mock_llm_client, sample evidence list, sample _SubAgentResult list). Skeleton ~30 LOC. |
| `tests/unit/test_models.py` | EXTEND | Add a section header `# Phase 21: VerifierVerdict + 3 events + GenerationRequest.debate` near the existing AgentEvent test block. No file creation needed. |
| `tests/unit/test_swarm_pipeline.py` | EXTEND | Add a section header `# Phase 21: debate hop` after Test 8 (line 362). Reuse existing `mock_pipeline` fixture (`tests/unit/test_swarm_pipeline.py:73-111`); add `verifier_mock` to the fixture. |
| `tests/integration/test_swarm_debate_e2e.py` | NEW | Create with `pytestmark = [pytest.mark.integration]`. One test for SC2 latency contract on live LLM. ~50 LOC; mirrors `tests/integration/test_swarm_pipeline_e2e.py` shape. |
| `tests/unit/test_settings.py` | EXTEND | Append two assertions: `assert settings.verifier_model is None`; `assert settings.verifier_provider is None`. |
| `tests/unit/test_agent_stream_route.py` | EXTEND (if Option B from P-05 chosen) | Add one route test asserting that req.swarm_mode + req.debate dispatches through SwarmQueryPipeline.run_streaming and yields the 3 verifier events. |

**Combined coverage threshold:** 70% (project-wide; Phase 15 D-08). Phase 21's diff-cover target: ≥ 70% on the new lines (Phase 10 TEST-03 carry-forward).

---

## Sampling Cadence

| Cadence | Trigger | Tests run | Pass criterion |
|---------|---------|-----------|----------------|
| Per-task | Every implementation commit (TDD plans) | `pytest tests/unit/test_verifier.py tests/unit/test_models.py tests/unit/test_swarm_pipeline.py -x` | All green; sub-30s typical |
| Per-wave | Wave merge into next wave's branch | `pytest -m "not integration" --cov=services/agent/verifier.py --cov=services/pipeline.py --cov=utils/models.py --cov-report=term-missing` | Diff-cover ≥ 70% on touched files; combined coverage stays ≥ 70% |
| Per-phase | Pre-`/gsd-verify-work` | (a) full unit suite; (b) `pytest tests/integration/test_swarm_debate_e2e.py -m integration`; (c) verify SSE wire on `/api/v1/agent/v1/run/stream` with curl + `req.debate=True` | All green; integration latency assertion holds; SSE frames include 3 verifier events when `req.debate=True` |

---

## Calibration Check (does the rate exceed regression rate?)

| Concern | Could regress at | Sampled at | Margin |
|---------|------------------|------------|--------|
| Verifier text-only contract (CF-03) | Each commit to `verifier.py` | Per-task | Margin = commit-rate vs commit-rate (matches; OK because tests run synchronously with the commit) |
| Latency contract (SC2/CF-06) | Each commit to `pipeline.py` debate hop OR each provider-side latency change | Per-task (unit synthetic) + per-phase (integration live) | Unit catches structural regressions; integration catches provider drift |
| Forced-disagree (CF-04) | Each commit to `verifier.py::verify` | Per-task | Matches |
| `debate=False` byte-identity (SC5) | Each commit to `pipeline.py::SwarmQueryPipeline` | Per-task | Matches |
| SSE wire format (CF-05/SC3) | Each commit to `utils/models.py` event subclasses OR `controllers/api.py` route | Per-task | Matches; route test in `test_agent_stream_route.py` runs in the unit tier |
| Audit metadata schema (CF-10/SC5) | Each commit to `pipeline.py::SwarmQueryPipeline.run` audit block | Per-task | Matches via tdd-4 case 7 (B-22) |
| Doc extension (SC4) | Each commit to `docs/agent-architecture.md` | Per-wave | Documentation drift; per-wave is acceptable because the file is rarely touched outside this phase |
| Coverage threshold (Phase 15 D-08) | Each commit | Per-wave | OK; the global threshold is the combined-coverage gate at PR-time |
| RLS tenant isolation (CF-10/SC5) | Migration to pgvector schema (rare); changes to retriever (occasional) | Per-phase (existing `test_pgvector_rls.py` integration test) | Matches; this phase doesn't touch RLS-relevant code |

**Conclusion:** Sampling rate exceeds regression rate for all 8 concerns. Nyquist condition satisfied.

---

## Wave 0 Test-Infrastructure Gaps

These must land in Wave 0 BEFORE TDD plans execute:

- [ ] Create `tests/unit/test_verifier.py` with empty `# Phase 21 Verifier unit tests` header + `pytest.mark.unit` module marker
- [ ] Create `tests/integration/test_swarm_debate_e2e.py` with `pytestmark = [pytest.mark.integration]` + module docstring noting it requires `OPENAI_API_KEY` (CONFIGURATION error if missing per existing precedent)
- [ ] Confirm `pytest-asyncio` is in `pyproject.toml` dev dependencies (verified — no install needed)

**No framework install needed.** Tests use existing `pytest 8.x + pytest-asyncio` stack already in use (verified by 802 passing unit tests at end of Phase 20 per `20-VERIFICATION.md`).

---

## Out-of-Scope (deferred sampling targets)

These are not Phase 21 evidence requirements but documented for traceability:

- **`SwarmQueryPipeline` whole-file coverage ≥ 70%** — deferred to Phase 22 TEST-08
- **`Verifier` whole-file coverage ≥ 70%** — Phase 21 ships ≥ 70% diff-cover; Phase 22 hardens branch coverage if needed
- **End-to-end SSE consumer test** — currently only unit-level smoke; full browser-side EventSource test deferred to v1.6+ UI work
- **Per-call model selection (Settings.verifier_model)** — shipped as field; not wired in v1.5 per RESEARCH §A3 assumption

---

*Phase: 21-AGENT-05 Multi-Agent Debate / Sub-Agent Verifier*
*Validation generated: 2026-05-10*
*Audit Dimension 8 expects this artifact at this path.*
