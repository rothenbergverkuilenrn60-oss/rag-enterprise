---
phase: 32
slug: mypy-strict-cleanup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-18
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from `32-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | mypy 1.14.0 + pytest 9.0.3 |
| **Config file** | `pyproject.toml` `[tool.mypy]` (extended in Wave 0 T0); `pytest.ini` (existing) |
| **Quick run command** | `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 \| tail -5` |
| **Full suite command** | `uv run pytest tests/unit/ -m 'not integration' --asyncio-mode=auto --timeout=30 -q` |
| **Estimated runtime** | ~25s mypy; ~60-90s unit suite |

---

## Sampling Rate

- **After every task commit:** `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null | grep -v ".pyc" | wc -l` → 0 (audit-mode-before-enforce: report metric per commit; final commit gates on 0)
- **After every plan wave:** `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 | grep "Found\|Success"` → error count non-increasing vs prior wave
- **Before `/gsd:verify-work`:** All D-VERIFY-01 commands pass (deferred-items drained; mypy clean on touched files; bounded-scope cap honored)
- **Max feedback latency:** ~25s (single mypy run on bounded scope)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 32-00-T0 | 00 | 0 | MYPY-02/04 (struct) | — | N/A (config) | smoke | `grep -q '^explicit_package_bases = true' pyproject.toml` | ✅ pyproject.toml | ⬜ pending |
| 32-00-T1 | 00 | 0 | MYPY-02/04 (deps) | — | N/A | smoke | `uv pip list \| grep -E 'asyncpg-stubs\|pandas-stubs'` and `grep -E 'asyncpg-stubs\|pandas-stubs' requirements-dev.txt` | ✅ requirements-dev.txt | ⬜ pending |
| 32-00-T2 | 00 | 1 | MYPY-02/04 (asyncpg silence removal) | — | N/A | type-check | `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 \| grep -cE 'asyncpg.*import-untyped'` → 0 | ✅ | ⬜ pending |
| 32-00-T3 | 00 | 1 | MYPY-02 (deferred drain) | — | N/A | grep-gate | `wc -l < deferred-items.md` shows only header + `0 outstanding entries` line; bullet count under `### Files` is 0 | ✅ ./deferred-items.md | ⬜ pending |
| 32-00-T4 | 00 | 2 | MYPY-03 (bare→coded) | — | N/A | grep-gate | `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null \| grep -v '.pyc'` → empty | ✅ | ⬜ pending |
| 32-00-T5 | 00 | 2 | MYPY-04 (test-file untyped imports) | — | N/A | type-check | `uv run mypy --strict tests/integration/memory/test_save_facts_toctou.py tests/integration/test_memory_forget_e2e.py tests/integration/test_evict_long_term_facts_e2e.py 2>&1 \| grep import-untyped` → empty | ✅ | ⬜ pending |
| 32-00-T6 | 00 | 3 | D-VERIFY-01 sweep | — | N/A | composite | All of: deferred-items drained; bare-ignore grep empty; touched-file silence count ≤25; tests/ silence count recorded in SUMMARY | ✅ | ⬜ pending |
| 32-00-T7 | 00 | 3 | D-VERIFY-02 (no test regression) | — | N/A | functional | `uv run pytest tests/integration/ -m 'integration and not real_llm and not benchmark' --asyncio-mode=auto -q` → ≥31 passed | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` `[tool.mypy]` extended with `explicit_package_bases = true` — Wave 0 T0
- [ ] `pyproject.toml` `[dependency-groups.dev]` (or equivalent uv dev-deps block) adds `asyncpg-stubs~=0.30.2` + `pandas-stubs~=2.2.3` — Wave 0 T1
- [ ] `requirements-dev.txt` adds `asyncpg-stubs~=0.30.2` + `pandas-stubs~=2.2.3` (CI install path — research finding) — Wave 0 T1
- [ ] No new test files required — phase is annotation/config-only

*No test scaffolding gap — validation is grep-based and mypy-based against existing files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| asyncpg-stubs Pool generic-arg surface | MYPY-02 (Open Q #1) | New `[type-arg]` errors may surface after T2 across `services/memory/long_term_memory.py`, `services/audit/audit_service.py`, `services/vectorizer/indexer.py`. Planner adds targeted silences only if they appear. | After Wave 1 T2 commit: `uv run mypy --strict services/ 2>&1 \| grep -E 'type-arg.*asyncpg\|Pool\['` — if non-empty, add silences per site with `# type: ignore[type-arg]  # why: asyncpg-stubs Pool generics drift` |
| CI parity (lint-and-type-check) | Out of scope (Open Q #3) | Phase 32 does not change CI strict-mode. Optional follow-up: add bare-ignore grep gate to CI workflow. | Decided by planner; if added, document in 32-00-SUMMARY.md |

*Test-suite green count is automated (T7); only the post-stub generic-arg drift requires human judgment per site (D-STUB heuristic).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (8 tasks, all automated — pass)
- [ ] Wave 0 covers all MISSING references (pyproject.toml mypy section, dev stub deps)
- [ ] No watch-mode flags (mypy runs are one-shot, pytest --timeout=30 bounded)
- [ ] Feedback latency < 30s (mypy quick run on bounded scope ≈25s)
- [ ] `nyquist_compliant: true` set in frontmatter (after planner verifies the task map matches PLAN.md task IDs)

**Approval:** pending
