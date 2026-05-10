---
phase: 12-fork-agent-swarm
plan: 01
subsystem: data-model
tags: [pydantic, basesettings, swarm, agent, fork-agent]

requires: []
provides:
  - "GenerationRequest.swarm_mode bool field (default False) — opt-in routing flag for SwarmQueryPipeline"
  - "Settings.max_swarm_agents int field (default 5, env MAX_SWARM_AGENTS) — coordinator fan-out cap"
  - "Settings.max_swarm_turns_per_agent int field (default 5, env MAX_SWARM_TURNS_PER_AGENT) — per-agent turn cap"
affects: [12-02, 12-03, swarm-pipeline, agent-routing]

tech-stack:
  added: []
  patterns:
    - "Pydantic V2 bool flag for execution-mode selection (mirrors existing agent_mode)"
    - "Pydantic BaseSettings env-var auto-binding via case_sensitive=False (no manual env= alias)"

key-files:
  created: []
  modified:
    - utils/models.py
    - config/settings.py

key-decisions:
  - "D-04: swarm_mode is a plain bool with no @field_validator — matches agent_mode shape; coercion semantics inherited from Pydantic V2 default"
  - "D-09: defaults 5 / 5 chosen as safe ceiling; operator may raise via env vars; no startup validator for negative/zero values (downstream handles in Plan 12-02 per threat T-12-01-04)"

patterns-established:
  - "Swarm settings live in dedicated 'Swarm（Fork-Agent — AGENT-03）' sub-section between LLM and Cache sections — future swarm-related ints go here"
  - "Mode flags on GenerationRequest follow alignment convention: name + space-padded type + ' = False   # 中文注释（REQ-ID）'"

requirements-completed: [AGENT-03]

duration: 4min
completed: 2026-05-09
---

# Phase 12 Plan 01: Fork-Agent Swarm Data Model Summary

**Two boolean/int field additions delivering the typed surface area Wave 2 SwarmQueryPipeline depends on: `GenerationRequest.swarm_mode` opt-in flag and `settings.max_swarm_{agents,turns_per_agent}` env-var-backed caps.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-09T09:50:00Z (approx)
- **Completed:** 2026-05-09T09:54:00Z (approx)
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- `GenerationRequest.swarm_mode: bool = False` declared on line 215 of `utils/models.py`, immediately after `agent_mode` (line 214), preserving column alignment of adjacent fields.
- `Settings.max_swarm_agents: int = 5` declared on line 288 of `config/settings.py`.
- `Settings.max_swarm_turns_per_agent: int = 5` declared on line 289 of `config/settings.py`.
- Both settings live in a dedicated, comment-banner-labelled "Swarm（Fork-Agent — AGENT-03）" sub-section (lines 285–289) between the existing LLM and Cache sections.
- Env-var override verified live: `MAX_SWARM_AGENTS=3 → settings.max_swarm_agents == 3` (Pydantic BaseSettings auto-binds via existing `case_sensitive=False` config; no manual `env=` annotation required).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add swarm_mode field to GenerationRequest** — `83396b1` (feat)
2. **Task 2: Add max_swarm_agents and max_swarm_turns_per_agent to Settings** — `c0db54e` (feat)

**Plan metadata commit:** to follow this SUMMARY.

## Files Created/Modified

- `utils/models.py` — added `swarm_mode: bool = False` to `GenerationRequest` (line 215, single-line additive change)
- `config/settings.py` — added two `int = 5` fields plus a 3-line section banner to `Settings` (lines 285–289, 6-line additive change including blank-line padding)

## Decisions Made

- **Followed plan as specified.** Both edits exactly match the concrete edit blocks in 12-01-PLAN.md, including indentation, column alignment, Chinese comment annotations, and section banner style.
- **Plain bool / plain int — no validators.** Per plan, `swarm_mode` mirrors `agent_mode` (no `@field_validator`); the two int settings rely on Pydantic's default int coercion; negative/zero edge case for `max_swarm_agents` is explicitly accepted in this plan's threat register (T-12-01-04) and deferred to Plan 12-02 synthesis fallback.

## Deviations from Plan

None — plan executed exactly as written. All concrete edit blocks applied verbatim; no fields touched outside the specified insertion points; no imports added; no ancillary refactors.

## Issues Encountered

- **mypy --strict on `utils/models.py` and `config/settings.py` reports one pre-existing error each** (`tables: list[dict]` line 92 in models.py; `embedding_ensemble: list[dict]` line 105 in settings.py — both `[type-arg]` "Missing type parameters for generic type 'dict'"). These errors exist on `master` before this plan and are unrelated to my changes; the plan acceptance criterion is "no new errors introduced" and is satisfied. Logged for future cleanup but **out of scope** per execute-plan SCOPE BOUNDARY (do not fix unrelated pre-existing diagnostics).
- **`tests/unit/test_models.py` does not exist.** The plan verification step references it ("`pytest tests/unit/test_models.py -x` (existing tests still pass — no regression)"); since the file is absent, there is no regression surface to check. Recorded for transparency.
- **Settings instantiation requires `APP_MODEL_DIR` env var (OPS-01) and a strong `SECRET_KEY` (SEC-01).** Verification commands had to be run with both env vars set:
  ```
  APP_MODEL_DIR=/tmp/models SECRET_KEY=$(openssl rand -hex 32) .venv/bin/python -c "..."
  ```
  This is project-wide pre-existing behavior, not specific to Plan 12-01.

## Verification Evidence

All acceptance criteria from 12-01-PLAN.md exit 0:

| Check | Result |
|-------|--------|
| `grep -c '^[[:space:]]*swarm_mode:[[:space:]]*bool[[:space:]]*=[[:space:]]*False' utils/models.py` | `1` (≥1 required) |
| `grep -n 'agent_mode\|swarm_mode' utils/models.py` shows consecutive lines | `214` (agent_mode), `215` (swarm_mode) |
| `'swarm_mode' in GenerationRequest.model_fields` | `True` |
| `GenerationRequest.model_fields['swarm_mode'].default is False` | `True` |
| `GenerationRequest(query='x', swarm_mode=True).swarm_mode is True` | `True` |
| `grep -c '^[[:space:]]*max_swarm_agents:[[:space:]]*int[[:space:]]*=[[:space:]]*5' config/settings.py` | `1` |
| `grep -c '^[[:space:]]*max_swarm_turns_per_agent:[[:space:]]*int[[:space:]]*=[[:space:]]*5' config/settings.py` | `1` |
| `settings.max_swarm_agents == 5 and settings.max_swarm_turns_per_agent == 5` | `True` |
| `'max_swarm_agents' in Settings.model_fields and 'max_swarm_turns_per_agent' in Settings.model_fields` | `True` |
| `MAX_SWARM_AGENTS=3 → Settings().max_swarm_agents == 3` | `True` (env override works) |
| `ruff check utils/models.py config/settings.py` | All checks passed |

## User Setup Required

None — no external service configuration introduced by this plan. The two new env vars (`MAX_SWARM_AGENTS`, `MAX_SWARM_TURNS_PER_AGENT`) are optional and have safe defaults (5 / 5).

## Next Phase Readiness

- **Plan 12-02 (SwarmQueryPipeline core, Wave 2)** is now unblocked: `req.swarm_mode` and `settings.max_swarm_agents` / `settings.max_swarm_turns_per_agent` are referenceable.
- **Plan 12-03 (routing + tests, Wave 3)** depends on 12-02 and inherits the same surface.
- No blockers. Phase 12 can proceed to Wave 2.

---

## Self-Check: PASSED

- `utils/models.py` — swarm_mode line FOUND at line 215
- `config/settings.py` — max_swarm_agents FOUND at line 288, max_swarm_turns_per_agent FOUND at line 289
- Commit `83396b1` (Task 1) FOUND in `git log --oneline`
- Commit `c0db54e` (Task 2) FOUND in `git log --oneline`

## Threat Flags

None — this plan's threat surface (`<threat_model>`) was scoped at planning time. No new endpoints, auth paths, file access patterns, or schema surfaces beyond the two declared fields. T-12-01-01 mitigation (Pydantic typed bool + downstream rate limit + Plan 02 cap) is realized in part here (typed bool); the cap enforcement lives in Plan 12-02 as planned.

---
*Phase: 12-fork-agent-swarm*
*Plan: 01*
*Completed: 2026-05-09*
