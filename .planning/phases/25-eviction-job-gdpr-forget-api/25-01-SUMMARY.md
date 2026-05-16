---
phase: 25-eviction-job-gdpr-forget-api
plan: 01
subsystem: foundations
tags: [settings, memory-cap, audit-enum, MEMORY_FORGET, MEMORY_EVICT, wave1-prep, T6]
requirements: [EVICT-01, EVICT-02, GDPR-03]
dependency_graph:
  requires: []
  provides:
    - "config.settings.settings.memory_facts_cap_per_user: int = 500 (ge=1)"
    - "services.audit.audit_service.AuditAction.MEMORY_FORGET = 'MEMORY_FORGET'"
    - "services.audit.audit_service.AuditAction.MEMORY_EVICT = 'MEMORY_EVICT'"
  affects:
    - "Plan 25-04 (forget controller) — reads AuditAction.MEMORY_FORGET"
    - "Plan 25-05 (eviction CLI) — reads AuditAction.MEMORY_EVICT + settings.memory_facts_cap_per_user"
tech_stack:
  added: []
  patterns:
    - "Pydantic V2 Field(default=500, ge=1) — settings-load validator (T6 / outside-voice F4 mitigates T-25-01-D1)"
    - "str Enum append-only extension after TOKEN_VERIFIED (Pitfall 5: preserves existing 12 DB string values)"
key_files:
  created:
    - "tests/unit/test_phase25_foundations.py"
  modified:
    - "config/settings.py"
    - "services/audit/audit_service.py"
decisions:
  - "T6 amendment: memory_facts_cap_per_user uses Field(default=500, ge=1) instead of plain int = 500 — Pydantic V2 ValidationError at settings-load closes silent total-wipe failure mode if MEMORY_FACTS_CAP_PER_USER=0 is set via ConfigMap typo. T-25-01-D1 STRIDE disposition flipped from accept to mitigate."
  - "AuditAction enum extended in append-only mode (Pitfall 5): MEMORY_FORGET + MEMORY_EVICT appended after TOKEN_VERIFIED; existing 12 values byte-identical."
metrics:
  duration_minutes: ~12
  tasks_completed: 2
  tests_added: 5
  files_modified: 2
  files_created: 1
  completed_date: "2026-05-16T14:14:27Z"
  commits:
    - hash: "4998dc2"
      message: "test(25-01): RED gates for settings cap field + AuditAction enum + ge=1 rejection (EVICT-01, GDPR-03 D-2.1, T6)"
    - hash: "cdfb049"
      message: "feat(25-01): add memory_facts_cap_per_user setting (ge=1) + MEMORY_FORGET/MEMORY_EVICT enum values (D-2.1, EVICT-01, T6)"
---

# Phase 25 Plan 01: Wave-1 Foundations Summary

Two Wave-1 foundation additions for Phase 25: a `memory_facts_cap_per_user: int = Field(default=500, ge=1)` setting (with T6 outside-voice F4 ge=1 validator closing the cap=0 silent-wipe failure mode) plus two append-only `AuditAction` enum values (`MEMORY_FORGET`, `MEMORY_EVICT`) that unblock the forget controller (25-04) and eviction CLI (25-05).

## Outcome

- 5 RED tests in `tests/unit/test_phase25_foundations.py` → 5 GREEN after production edits in Task 2.
- `Settings(memory_facts_cap_per_user=0)` raises `pydantic.ValidationError` (T6 acceptance gate green — closes T-25-01-D1).
- `AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"` and `AuditAction.MEMORY_EVICT.value == "MEMORY_EVICT"` — total enum count = 14 (12 existing verbatim + 2 new).
- All 12 pre-existing enum values byte-identical (append-only invariant per Pitfall 5).
- `ruff` clean on touched files; `mypy --strict` shows zero NEW violations (3 pre-existing line-number-shifted warnings unchanged).

## Tasks Executed

### Task 1 — RED (commit `4998dc2`)
Created `tests/unit/test_phase25_foundations.py` with 5 tests:
1. `test_memory_facts_cap_per_user_default` — `settings.memory_facts_cap_per_user == 500`.
2. `test_memory_facts_cap_per_user_is_int` — `Settings.model_fields["memory_facts_cap_per_user"].annotation is int` and `.default == 500`.
3. `test_memory_facts_cap_zero_rejected` (T6) — `Settings(memory_facts_cap_per_user=0)` and `=-1` both raise `pydantic.ValidationError`.
4. `test_audit_action_memory_forget_exists` — `AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"`.
5. `test_audit_action_memory_evict_exists` — `AuditAction.MEMORY_EVICT.value == "MEMORY_EVICT"`.

Imports of `config.settings` and `services.audit.audit_service` placed inside test bodies so collection succeeds in RED state. Env-var setdefault block (`APP_MODEL_DIR`, `SECRET_KEY`) at module top mirrors `tests/unit/test_memory_save_fact.py`.

Collection gate: 5 items. RED gate: 5 failures (each test gets the expected `AttributeError` or wrong-default mismatch — Task 2 production changes pending).

### Task 2 — GREEN (commit `cdfb049`)
1. `config/settings.py`: added `memory_facts_cap_per_user: int = Field(default=500, ge=1)` immediately after `recall_tool_enabled` (Phase 24 field) with comment block citing Phase 25 / EVICT-01 and T6. `Field` was already imported (used elsewhere in the file), so no new import line.
2. `services/audit/audit_service.py::AuditAction`: appended `MEMORY_FORGET = "MEMORY_FORGET"` and `MEMORY_EVICT = "MEMORY_EVICT"` after `TOKEN_VERIFIED` with comment header `# Phase 25 — D-2.1 — GDPR forget API + eviction job`. Existing 12 values verbatim.

All 5 tests went GREEN. T6 acceptance gate: `Settings(memory_facts_cap_per_user=0)` raises `ValidationError` (verified out-of-test via `uv run python -c`).

## Verification Run

| Gate | Command | Result |
|------|---------|--------|
| Collection | `uv run pytest tests/unit/test_phase25_foundations.py --collect-only -q` | 5 tests collected |
| RED (pre-Task-2) | `uv run pytest tests/unit/test_phase25_foundations.py -q` | 5 failed |
| GREEN (post-Task-2) | `uv run pytest tests/unit/test_phase25_foundations.py -x -q` | 5 passed in 0.06s |
| T6 acceptance | `uv run python -c "from config.settings import Settings; from pydantic import ValidationError; r=False; \ntry: Settings(memory_facts_cap_per_user=0)\nexcept ValidationError: r=True\nassert r"` | exit 0 |
| Enum count | `uv run python -c "from services.audit.audit_service import AuditAction; assert len([a for a in AuditAction]) == 14"` | exit 0 (14 values) |
| Literal grep | `grep 'memory_facts_cap_per_user: int = Field(default=500, ge=1)' config/settings.py` | 1 match |
| TOKEN_VERIFIED < MEMORY_FORGET line | line 37 < line 39 | append-after invariant OK |
| ruff | `uv run ruff check config/settings.py services/audit/audit_service.py tests/unit/test_phase25_foundations.py` | All checks passed |
| mypy --strict NEW violations | compared HEAD vs HEAD~2 | 0 new (3 pre-existing) |

## Success Criteria

- EVICT-01 structural prerequisite — `settings.memory_facts_cap_per_user = 500` available for eviction CLI (Plan 25-05). MET.
- EVICT-02 structural prerequisite — `AuditAction.MEMORY_EVICT` available for eviction CLI audit rows. MET.
- GDPR-03 structural prerequisite — `AuditAction.MEMORY_FORGET` available for forget controller audit rows. MET.
- D-2.1 honored — TWO new enum values added, 12 existing values unchanged. MET (verified line 37 TOKEN_VERIFIED still present; line numbers of new values 39, 40).
- Pitfall 5 mitigated — values appended after TOKEN_VERIFIED, string values match enum names exactly. MET.
- T6 (eng-review outside-voice F4) — T-25-01-D1 cap=0 silent-wipe failure mode closed via Pydantic `Field(ge=1)` validator + RED→GREEN test. MET.

## Deviations from Plan

None — plan executed exactly as written. The T6 amendment was already incorporated into the plan (`memory_facts_cap_per_user: int = Field(default=500, ge=1)`) and was applied verbatim.

The only minor observation: mypy `--strict` on the two touched production files reports 3 pre-existing warnings (line 105 `dict` type-arg in settings.py; line 61 `dict` type-arg in audit_service.py; line 260 `asyncpg` missing stubs). All 3 reproduce on HEAD~2 (pre-edit) with identical content — they pre-date Plan 25-01. Out of scope per Rule "SCOPE BOUNDARY: only auto-fix issues DIRECTLY caused by the current task's changes." Logged here for traceability.

## Known Stubs

None. The two new enum values are not stubs — they are the contract surface that Plans 25-04 and 25-05 will consume; both plans land in Wave 2.

## Threat Flags

No new threat surface introduced. T6 closes T-25-01-D1 (cap=0 silent-wipe DoS via env override); STRIDE register in 25-01-PLAN frontmatter reflects the disposition flip from `accept` to `mitigate`. All other STRIDE entries unchanged.

## Self-Check: PASSED

- `tests/unit/test_phase25_foundations.py` — FOUND (71 lines, 5 tests).
- `config/settings.py` line 435 — FOUND (`memory_facts_cap_per_user: int = Field(default=500, ge=1)`).
- `services/audit/audit_service.py` lines 39-40 — FOUND (`MEMORY_FORGET = "MEMORY_FORGET"` and `MEMORY_EVICT = "MEMORY_EVICT"`).
- Commit `4998dc2` — FOUND in `git log`.
- Commit `cdfb049` — FOUND in `git log`.

## TDD Gate Compliance

- RED gate: commit `4998dc2` (type `test`) — present.
- GREEN gate: commit `cdfb049` (type `feat`) — present and follows the RED commit.
- REFACTOR gate: not needed (both production edits are minimal additions; no cleanup necessary).
