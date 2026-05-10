---
phase: 21-agent-05-multi-agent-debate-sub-agent-verifier
plan: 06
subsystem: docs
tags:
  - docs
  - event-schema-reference
  - verifier-events
  - debate-mode
  - sse
  - backward-compat
  - doc-vs-code-parity
  - sc4
  - agent-15
requirements: [AGENT-15]
dependency_graph:
  requires:
    - "21-02: VerifierStartEvent / VerifierCompleteEvent / VerifierDisagreementEvent frozen Pydantic V2 schemas (utils/models.py — field tables in this doc mirror them verbatim)"
    - "21-05: SwarmQueryPipeline.run_streaming + controllers/api.py:280 route dispatch (the wire path the doc claims is wire-truthful, not forward-looking)"
  provides:
    - "docs/agent-architecture.md ### Debate Mode subsection — opt-in/latency/ordering/wire-route prose anchor for downstream consumers"
    - "docs/agent-architecture.md ### verifier.start / ### verifier.complete / ### verifier.disagreement — frozen wire schema reference"
    - "Doc-vs-code drift gate (DOC-CODE-PARITY) — Python check that every Pydantic field name appears in the doc; suitable for Phase 22 docs-drift CI lift"
    - "Backward-compat blockquote (LOCKED phrasing) — machine-greppable contract anchor for future doc-drift CI"
    - "Extended `### Consuming the Stream` JS example — 3 new addEventListener lines for frontend integrators"
  affects:
    - "Phase 22 (docs-drift CI lift): the in-place doc-vs-code parity check is suitable for promotion to a CI gate"
    - "v1.6+ (consumer integrations): downstream UI / ops dashboards code against this schema, not utils/models.py directly"
tech_stack:
  added: []
  patterns:
    - "Doc-vs-code parity gate (Python re.findall + json.loads on fenced ```json blocks) — runs in seconds; suitable for CI promotion"
    - "Closed-Literal contract anchoring in prose — `reason` field documented as closed Literal set with explicit 'fourth value requires Literal bump AND doc update' bilateral contract"
    - "Backward-compat blockquote with LOCKED phrasing — additivity contract made machine-greppable for future doc-drift CI"
    - "Mirror-the-existing-template insertion strategy — verifier.{start,complete,disagreement} subsections mirror the tool.span.{start,end,error} triple's heading + prose + field-table + JSON-example shape; consumers learn one pattern"
key_files:
  created: []
  modified:
    - "docs/agent-architecture.md (+148/-1; preamble line 251 update + ### Debate Mode subsection + 3 new event subsections + 3 new addEventListener lines)"
key_decisions:
  - "Inserted 3 new event subsections AFTER ### synthesizer.final and BEFORE ### Consuming the Stream so the JS example covers the new event types in the same code block (consumer-facing locality)."
  - "Backward-compat note rendered as Markdown blockquote (`> **Backward compatibility:**`) rather than bold-inline (the existing redaction-policy treatment) — intentional visual separation since this note is the AGENT-15 contract anchor; not a regression, deliberate emphasis."
  - "Preamble updated from '6 concrete subclasses' to '9 concrete subclasses; 3 verifier subclasses are debate-mode-only — see ### Debate Mode below' so readers learn the debate-mode condition in the same sentence that mentions the new subclasses."
  - "Doc text quotes the controllers/api.py:274 ternary verbatim (`pipeline = get_swarm_pipeline() if req.swarm_mode else get_agent_pipeline()`) — anchors the wire route to a specific source location consumers can cross-reference."
  - "Did NOT introduce a new common-fields table for the 3 new events — they inherit trace_id / seq / ts_ms from AgentEvent (covered at lines 254-258); per-event tables list event-specific fields ONLY (matches the existing 6-event convention)."
  - "Did NOT mention the Pitfall P-08 Chinese-banner-on-English-disagree concern — it's an answer-text concern (Plan 04 _DISAGREE_BANNER_TEMPLATE), not an event-schema concern; out of scope for this doc."
metrics:
  duration: "12 min"
  completed: "2026-05-10"
---

# Phase 21 Plan 06: docs/agent-architecture.md Event Schema Reference extension Summary

**Event Schema Reference extended with `### Debate Mode` opt-in/latency/ordering/wire-route prose + 3 new verifier event subsections (`verifier.start`, `verifier.complete`, `verifier.disagreement`) + LOCKED-phrasing backward-compat blockquote + 3 new JS addEventListener lines — doc-vs-code parity gate (`DOC-CODE-PARITY: OK`) validates every Pydantic field name appears verbatim.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-10
- **Completed:** 2026-05-10
- **Tasks:** 1 (Task 1 — single structural edit per plan)
- **Files modified:** 1 (docs/agent-architecture.md)

## Accomplishments

- AGENT-15 (Phase 21 SC4) acceptance text satisfied — "docs/agent-architecture.md Event Schema Reference extended with three new subsections + example payloads" and "backward-compat note documents that debate-mode events are additive and non-debate flows unchanged" both land verbatim.
- Doc-vs-code drift gate (DOC-CODE-PARITY) passes — every Pydantic field on the 3 verifier events appears in the doc; closed Literal sets (`reason` 3-value, `verdict` 2-value) listed in full.
- All 9 fenced ```json blocks in `docs/agent-architecture.md` parse via `json.loads` (regression check that the insertions did not corrupt prior blocks).
- JS consumer example extended consistently with the existing 6-event pattern — 3 new addEventListener lines slot between `executor.parallel` and `synthesizer.final`, preserving the terminal-event ordering invariant.

## Task Commits

1. **Task 1: Insert Debate Mode subsection + 3 new event subsections + extend JS consumer example** — `bea77b5` (docs)

**Plan metadata:** `<this commit>` (docs: SUMMARY + STATE/ROADMAP advance)

## 5 Distinct Insertions to docs/agent-architecture.md

| # | What | Location (post-edit line range) |
|---|------|----------------------------------|
| 1 | Preamble update — "6 concrete subclasses" → "9 concrete subclasses; 3 verifier subclasses are debate-mode-only" | line 251-252 |
| 2 | `### Debate Mode` subsection — opt-in (D-10) / latency (CF-06) / 5-path ordering / terminal-event invariant (CF-07) / wire route + backward-compat blockquote | lines 376-431 |
| 3 | `### verifier.start` subsection — peer_count + model field table + JSON example | lines 433-450 |
| 4 | `### verifier.complete` subsection — verdict + evidence_chunk_count + latency_ms field table + JSON example | lines 452-471 |
| 5 | `### verifier.disagreement` subsection — 3-reason discriminator prose + 5-field table + 3 JSON examples (one per reason) | lines 473-516 |
| 6 | 3 new `addEventListener` lines in JS example — verifier.start / verifier.complete / verifier.disagreement, inserted before terminal `synthesizer.final` | lines 530-532 |

## Files Created/Modified

- `docs/agent-architecture.md` — +148 / -1; the only file touched. Doc grows from 390 → 537 lines (+147 net).

## Verify Gate Output

```
DOC-CODE-PARITY: OK
JSON-PARSE: parsed 9 JSON blocks OK
```

Heading order verified (synthesizer.final → Debate Mode → verifier.start → verifier.complete → verifier.disagreement → Consuming the Stream); JS listener order verified (executor.parallel → verifier.* → synthesizer.final); `git status --short` confirms only `docs/agent-architecture.md` modified; no code changes (no pytest required).

## Decisions Made

See `key_decisions:` in frontmatter — 6 decisions recorded inline. Most-load-bearing:

1. Mirror-the-existing-template insertion strategy — the 3 new event subsections clone the heading + prose + field-table + JSON-example shape of the existing `tool.span.{start,end,error}` triple. Consumers who already read the doc once learn one pattern, not two.
2. Doc-vs-code parity gate is in-place (Python re.findall over the new field names) and runs in seconds — suitable for promotion to a CI gate in Phase 22 (docs-drift lift).

## Deviations from Plan

None — plan executed exactly as written. The action block contained verbatim Markdown to insert; insertion was structural (between two known anchors). All grep + Python verification gates pass.

`wc -l` grew by 147 lines (vs. plan's stated soft target of "80-100 LOC"); the additional ~47 lines come from the 5-path ordering bullet list + 3 separate JSON example payloads in the disagreement subsection (one per `reason` Literal value), both of which are explicitly required by the action block. Soft guardrail, not a deviation — the action's verbatim insertion content sets the size, not the LOC range.

## Issues Encountered

None.

## Phase 21 Closing Notes

All 5 Phase 21 success criteria addressed across 6 plans:

- **SC1** (Verifier class with text-only call_agentic_turn + force-disagree on empty evidence) → Plan 03 (services/agent/verifier.py)
- **SC2** (Latency contract `max(peer) + verifier`) → Plan 05 integration test (tests/integration/test_swarm_debate_e2e.py)
- **SC3** (3 new SSE event types as Pydantic V2 frozen subclasses; events emit through existing route; synthesizer.final terminal in all paths) → Plan 02 (utils/models.py schemas) + Plan 05 (run_streaming wire emission + controllers/api.py:280 route dispatch)
- **SC4** (docs/agent-architecture.md extension + backward-compat note) → Plan 06 (this plan)
- **SC5** (v1.3 invariants intact under debate=False; combined coverage ≥ 70%; no production-code changes when debate=False) → Plan 05 byte-identity test + the conditional `**({"agent_05": ...} if req.debate else {})` audit-detail spread (preserves CF-08 byte-identity for non-debate path)

Phase 21 ready for `/gsd-verify-work 21`.

## Hand-Off Notes

**Phase 22 (TEST-08 coverage lift):** the new lines in `services/pipeline.py` from Plan 05 are diff-covered ≥ 70% by Plan 05's tests; whole-file `pipeline.py` coverage lift is Phase 22's job per CONTEXT deferred section. Phase 22 may also promote this plan's `DOC-CODE-PARITY` check to a CI doc-drift gate.

**v1.6+ (deferred per CONTEXT):**
- `proposed_answer_preview` on `verifier.complete` (kept off the wire in v1.5 to avoid PII echo / frame bloat).
- UI banner for divergence (text-only banner is the v1.5 surface per D-03; full UI work deferred).
- `Synthesizer` class extraction (D-04 keeps composition inline).
- Per-call model selection — `Settings.verifier_model` activation; only `verifier_provider` is wired in v1.5 per Pitfall P-09 / Assumption A3.
- True streaming inside `SwarmQueryPipeline.run_streaming` — Plan 05 batch-emits events at end-of-run via `_run_with_state`; v1.6+ can refactor to interleaved emission if ops dashboards demand mid-run progress.

**Promoted from "deferred" to "shipped in Plan 05" via the BLOCKER-2 plan-checker iteration-1 fix:** swarm-route dispatch now lives in the route at `controllers/api.py:280` (`pipeline = get_swarm_pipeline() if req.swarm_mode else get_agent_pipeline()`) — this plan's doc anchors that line verbatim.

## Next Phase Readiness

Phase 21 is feature-complete (all 5 SCs addressed across 6 plans); ready for `/gsd-verify-work 21`. Next milestone work is Phase 22 (Per-Module 70% Coverage Lift).

## Self-Check: PASSED

Verified before recording:

- `docs/agent-architecture.md` modified (1 file, 148 insertions, 1 deletion) — `git status --short` confirms.
- Commit `bea77b5` exists in `git log`.
- All 4 new H3 headings (`### Debate Mode`, `### verifier.start`, `### verifier.complete`, `### verifier.disagreement`) appear exactly once in the post-edit doc.
- 3 new `es.addEventListener('verifier.*')` lines appear in the JS example, inserted before the terminal `synthesizer.final` line.
- Doc-vs-code parity gate `DOC-CODE-PARITY: OK` and 9-JSON-block parse `JSON-PARSE: parsed 9 JSON blocks OK` both pass.

---
*Phase: 21-agent-05-multi-agent-debate-sub-agent-verifier*
*Completed: 2026-05-10*
