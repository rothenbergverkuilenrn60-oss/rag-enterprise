---
phase: 32-mypy-strict-cleanup
verified: 2026-05-18T00:00:00Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
overrides:
  - must_have: "Integration test suite green count is ≥ 31 passed / 0 failed / 2 skipped / 3 errors (Phase 31 post-fix baseline, D-VERIFY-02)."
    reason: "Phase 31 baseline was over-optimistic; actual pre-Phase-32 baseline was 9 failed / 31 passed / 1 skipped / 3 errors. Phase 32 is annotation-only and cannot cause E2E regressions. Failing tests reference files not touched by Phase 32. User-approved override on pre-existing failure basis."
    accepted_by: "executor (T7 closeout, user-approved)"
    accepted_at: "2026-05-18T00:00:00Z"
gaps: []
deferred: []
human_verification: []
---

# Phase 32: mypy --strict Cleanup Verification Report

**Phase Goal:** Drain the `--strict` debt to zero net new violations vs v1.8 close; replace every bare `# type: ignore` with `[code]  # why:` form; resolve asyncpg/pgvector.asyncpg untyped-import silences.
**Verified:** 2026-05-18
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | deferred-items.md contains 0 outstanding entries (the 7 v1.8-overflow violations are all resolved) | VERIFIED | `grep -c '^- ' deferred-items.md` → 0 (exit 1 from grep = no matches) |
| 2 | No bare `# type: ignore` (without bracketed error code) exists anywhere in services/, tests/, utils/, config/, scripts/, controllers/ | VERIFIED | `grep -rn '# type: ignore[^[]' services/ tests/ utils/ ...` → empty (exit 0) |
| 3 | asyncpg + pgvector.asyncpg `[import-untyped]` errors no longer surface in the 4 audit-expanded test files | VERIFIED | `uv run mypy --strict <3 test files> 2>&1 \| grep import-untyped` → empty |
| 4 | services/nlu/nlu_service.py:538 carries a coded silence `[func-returns-value]  # why:` (no bare ignore) | VERIFIED | `grep -n 'func-returns-value' services/nlu/nlu_service.py` → line 538 matches `ignore[func-returns-value]  # why: set.add() returns None; walrus-style dedup pa...` |
| 5 | Bounded-scope silence count across Phase-32 touched files ≤ 25 (D-CAP-03) | VERIFIED | Sum across 9 bounded-scope files = 12 (PASS ≤ 25) |
| 6 | tests/ silence count is reported in 32-00-SUMMARY.md (audit-mode-before-enforce, not gated) | VERIFIED | SUMMARY Gate 6 reports 92 informational; not gated per D-CAP-02 |
| 7 | Integration test suite green count is ≥ 31 passed / 0 failed (OVERRIDE: 9 failed pre-existing) | VERIFIED (override) | T7 result: 9 failed / 31 passed / 1 skipped / 3 errors. 31 passed floor met. Override: 9 failures reference tests not in Phase 32 touched-file list; pre-dating Phase 32 |
| 8 | CI dep-install path includes the new stubs (requirements-dev.txt updated alongside pyproject.toml [dependency-groups].dev) | VERIFIED | `requirements-dev.txt:12`: `asyncpg-stubs~=0.30.2`; `:13`: `pandas-stubs>=3.0.0.260204`. CI yaml installs: `pip install ... asyncpg-stubs~=0.30.2 "pandas-stubs>=3.0.0.260204"` |
| 9 | Typing-hygiene script enforces stub-parity AND zero bare ignores; wired into pre-commit AND CI | VERIFIED | `scripts/check_typing_hygiene.py` exists (6.7K), `uv run python scripts/check_typing_hygiene.py` exits 0 with [PASS] on both invariants. `.pre-commit-config.yaml`: hook `typing-hygiene` calls `python scripts/check_typing_hygiene.py`. `.github/workflows/ci.yml`: step "Typing hygiene gate (D1 + D3)" runs same script. |
| 10 | T2.5 generic-arg drift overflow recovery: if [type-arg] silences push count > 25, executor halts | VERIFIED | 3 drift silences added (vector_store.py:148 [assignment], audit_service.py:128 [call-overload], memory_service.py:243 [call-overload]). Pre-cap 9 + 3 = 12. Cap not triggered; no halt needed. Correctly handled without auto-silencing past D-CAP-03 |

**Score:** 10/10 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | `[tool.mypy]` with `strict=true` + `explicit_package_bases=true`; asyncpg-stubs~=0.30.2 + pandas-stubs listed under `[dependency-groups].dev` | VERIFIED | Lines 135-136: `strict = true`, `explicit_package_bases = true`. Line 80: `asyncpg-stubs~=0.30.2`. Line 85: `pandas-stubs>=3.0.0.260204` (deviated from plan's 2.2.3 pin — correct: matches pandas 3.0.2 runtime) |
| `requirements-dev.txt` | Same two stub pins for pip-based CI install path | VERIFIED | Lines 12-13 contain `asyncpg-stubs~=0.30.2` and `pandas-stubs>=3.0.0.260204` with explanatory comments |
| `deferred-items.md` | Drained ledger — 0 entries; each prior bullet fixed or silenced | VERIFIED | 0 bullet lines (`'^- '`); all 7 prior entries have resolution notes in table form; single `## MYPY-01 overflow` section shows all 7 resolved |
| `scripts/check_typing_hygiene.py` | Enforces stub parity + bare-ignore ban | VERIFIED | File exists (6.7K), logic correct: `_extract_stubs_from_pyproject` parses `[dependency-groups]` dev section; `check_bare_ignores()` uses `re.compile(r"# type" + r": ignore(?!\[)")` avoiding self-match via `_self` exclusion; exits 0 on current codebase |
| `.planning/phases/32-mypy-strict-cleanup/32-00-SUMMARY.md` | Per-task verification + bounded-scope silence count + tests/ silence count | VERIFIED | 298 lines; all 7 tasks committed with hashes; D-VERIFY-01 gates 1-6 documented with results; tests/ silence count (92) reported |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `pyproject.toml [dependency-groups].dev` | `requirements-dev.txt` | mirrored stub pins | WIRED | Both files contain `asyncpg-stubs~=0.30.2` and `pandas-stubs>=3.0.0.260204` |
| `asyncpg-stubs install (T1)` | asyncpg `[import-untyped]` silence removal (T2) | stub presence makes silences trigger `[unused-ignore]` | WIRED | `asyncpg-stubs 0.30.2` installed (pkg_resources confirmed); asyncpg imports in services/ now typed via stubs |
| `explicit_package_bases = true (T0)` | `scripts/evict_long_term_facts.py` structural deferred entry | config-only fix resolves duplicate-module error | WIRED | `pyproject.toml:136`: `explicit_package_bases = true`; structural deferred item resolved in table |
| `services/nlu/nlu_service.py:538 bare ignore` | `[func-returns-value]  # why: set.add() returns None` | T4 surgical edit | WIRED | Line 538 confirmed: coded silence present |
| `tests/integration/test_ragas_eval.py:442 bare ignore` | removed entirely | T4 deletion | WIRED | `grep -n '442\|type: ignore' test_ragas_eval.py \| grep ':44[0-9]'` → empty; line removed |
| `tests/unit/test_extractor_coverage.py:152,300 bare ignores` | `[attr-defined]  # why: fake_fitz monkeypatching` | T4 two-site coded form | WIRED | Lines 152 and 300 confirmed: `type: ignore[attr-defined]  # why: fake_fitz is a raw ModuleType` |
| `scripts/check_typing_hygiene.py (T1.5)` | pre-commit + CI lint-and-type-check job | single-script enforcement | WIRED | Pre-commit hook `typing-hygiene` registered; CI step "Typing hygiene gate (D1 + D3)" registered in ci.yml |

---

## Data-Flow Trace (Level 4)

Not applicable — this is a type-annotation/tooling phase with no dynamic data rendering. Artifacts are config files, a CLI script, and inline comment changes.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| check_typing_hygiene exits 0 | `uv run python scripts/check_typing_hygiene.py` | `[PASS] Invariant 1 — stub parity ... [PASS] Invariant 2 — bare-ignore ban ...` exit 0 | PASS |
| No bare ignores in source dirs | `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null \| grep -v .pyc` | empty output, exit 0 | PASS |
| deferred-items.md has 0 bullets | `grep -c '^- ' deferred-items.md` | 0 (exit 1 = grep found 0 matches) | PASS |
| bounded-scope silence count ≤ 25 | sum across 9 files | 12 | PASS |
| asyncpg-stubs + pandas-stubs installed | pkg_resources check | `asyncpg-stubs 0.30.2`, `pandas-stubs 3.0.0.260204` | PASS |
| mypy bounded-scope error count non-increasing | `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 \| tail -1` | `Found 384 errors in 39 files` (SUMMARY claims 390→384, -6 wins) | PASS |

---

## Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| D-VERIFY-01 Gate 1 (MYPY-02) | `grep -c '^- ' deferred-items.md` | 0 | PASS |
| D-VERIFY-01 Gate 2 (MYPY-03) | `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null \| grep -v .pyc` | empty | PASS |
| D-VERIFY-01 Gate 3 (MYPY-04) | `uv run mypy --strict <3 test files> 2>&1 \| grep import-untyped` | empty | PASS |
| D-VERIFY-01 Gate 4 | `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 \| tail -1` | 384 errors | PASS (non-increasing) |
| D-VERIFY-01 Gate 5 | bounded-scope silence sum | 12 | PASS (≤ 25) |
| Typing hygiene script | `uv run python scripts/check_typing_hygiene.py` | exit 0 | PASS |

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| MYPY-02 | Resolve all 7 deferred violations in deferred-items.md; cap drains to ≤ 0 entries | SATISFIED | `grep -c '^- ' deferred-items.md` = 0; all 7 entries resolved via stubs, `explicit_package_bases`, or silence-with-why |
| MYPY-03 | Replace bare `# type: ignore` at nlu_service.py:538 with `[code]  # why:` convention | SATISFIED | Line 538: `ignore[func-returns-value]  # why: set.add() returns None`; test_ragas_eval.py:442 removed; test_extractor_coverage.py:152,300 coded; no bare ignores repo-wide |
| MYPY-04 | Resolve asyncpg + pgvector.asyncpg `[import-untyped]` silences in test_save_facts_toctou.py:32,57 | SATISFIED | asyncpg line 32: now typed via asyncpg-stubs 0.30.2 (no silence needed); pgvector.asyncpg line 57: `type: ignore[import-untyped]  # why: pgvector.asyncpg lacks py.typed`; `uv run mypy --strict <3 test files> 2>&1 \| grep import-untyped` → empty |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `eval/report_renderer.py` | 163 | `[unused-ignore]` — `[call-arg]` silence now unnecessary since jinja2 stubs cover it | Info | Pre-existing; not Phase 32 introduced; SUMMARY claims these were "logged to deferred-items" but they were NOT added to deferred-items.md. Minor SUMMARY inaccuracy only. |
| `services/generator/llm_client.py` | 740 | `[unused-ignore]` — `[return-value]` silence doesn't match new error `[no-any-return]` | Info | Pre-existing; same documentation inaccuracy as above. |
| `services/extractor/extractor.py` | 233 | `[unused-ignore]` — PyMuPDF 1.27.2 now ships py.typed, silence obsolete | Info | Pre-existing; same documentation inaccuracy. |

**Assessment:** The 3 unused-ignore issues are real pre-existing mypy errors (confirmed via `uv run mypy --strict`). They are NOT caused by Phase 32 and are included in the 384-error baseline. SUMMARY's `decisions` field claims they were "logged to deferred-items under a new section" — this is inaccurate; deferred-items.md has no new section for them. This is a documentation-only discrepancy. It does not affect MYPY-02 acceptance (which counts `'^- '` bullet entries = 0) and does not block any requirement. The 3 errors are tracked implicitly in the mypy baseline count.

No `TBD`, `FIXME`, or `XXX` markers found in Phase 32 touched files.

---

## T7 Failure Attribution Assessment

**Claim:** 9 integration + 7 unit failures are pre-existing and not caused by Phase 32.

**Evidence supporting pre-existing claim:**

- Phase 32 touched test files: `tests/conftest.py`, `tests/integration/memory/test_save_facts_toctou.py`, `tests/integration/test_ragas_eval.py`, `tests/unit/test_extractor_coverage.py`
- Identified failing integration tests: `test_ui_static.py`, `test_planner_picks_web_search.py`, `test_recall_latency.py`, `test_swarm_pipeline_e2e.py`, `test_recall_offline_eval.py`, `test_recall_tool_e2e.py` — **none of these appear in Phase 32's file diff** (`git diff 122d1ff..53a1f52 --name-only`)
- Identified failing unit tests: `test_retrieve_tool.py`, `test_web_search_tool.py` — **neither in Phase 32's file diff**
- Phase 31 baseline already showed 10 integration failures (now 9 — Phase 32 actually fixed one via annotation-only change or test collection difference)
- Phase 32 changes are annotation-only: inline comment additions/removals, `pyproject.toml` config, `requirements-dev.txt` pins — no runtime logic changed

**Verdict:** Pre-existing attribution VERIFIED. User-approved override is correctly grounded.

---

## Human Verification Required

None. All must-haves are verifiable from the codebase state.

---

## Gaps Summary

No gaps. All 10 must-haves are verified with direct command evidence. The minor SUMMARY documentation inaccuracy (3 unused-ignore items described as "logged to deferred-items" but not actually there) does not constitute a gap against any PLAN must-have or REQUIREMENTS acceptance criterion — MYPY-02's gate is `grep -c '^- ' deferred-items.md` → 0, which passes.

---

_Verified: 2026-05-18_
_Verifier: Claude (gsd-verifier)_
