# Phase 32: mypy `--strict` Cleanup - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Drain v1.8-deferred mypy `--strict` debt to zero entries in `./deferred-items.md` (7 → 0). Replace bare `# type: ignore` sites with the `[code]  # why:` form (silence convention locked in v1.8 Phase 30-03). Resolve `import-untyped` silences for `asyncpg`, `pgvector.asyncpg`, and other deferred-listed third-party libs via upstream stubs where available, silence-with-why otherwise.

**In scope:** the bounded scope `services/ + config/ + utils/ + controllers/ + scripts/` (production + ops paths), plus `tests/` for the specific bare-ignore and untyped-import sites surfaced by audit. mypy config evolution (`explicit_package_bases`) is in scope.

**Out of scope:** annotating all `tests/` fixtures (`no-untyped-def`, `no-untyped-call`) to drive full-repo error count toward zero — `tests/` retain a separate uncapped budget for fixture/test-helper signatures (D-CAP). Stub-rolling for `pgvector.asyncpg`, `rank_bm25`, `datasets` (no upstream stubs exist — silence-with-why is the accepted path).

</domain>

<decisions>
## Implementation Decisions

### Cap policy (must_have #4 reconciliation)
- **D-CAP-01:** "Cap = 25" applies to the **bounded scope** `services/ + config/ + utils/ + controllers/ + scripts/` (production + ops paths). This matches Phase 30-03's actual sweep window; the ROADMAP literal "full-repo ≤25" was a planning-doc artifact that did not match Phase 30 reality.
- **D-CAP-02:** `tests/` carry a **separate, uncapped silence budget**. Test fixtures legitimately need more `no-untyped-def` / `no-untyped-call` ignores; capping them would push the phase into 200+ LOC of fixture annotation work that is out of v1.9 reliability-burn-down scope. Tests/ silence count is **tracked + reported** in the SUMMARY (audit-mode-before-enforce discipline) but not gated.
- **D-CAP-03:** Phase 32 success-criterion #4 is re-stated for the verifier: "Bounded-scope silence count ≤ 25 post-Phase-32 AND deferred-items.md drained to 0 AND no bare `# type: ignore` remains repo-wide AND tests/ silence count documented in 32-00-SUMMARY.md."

### Audit scope (MYPY-03 + MYPY-04 expansion)
- **D-AUDIT-01:** Audit-mode-before-enforce discipline (carry-forward from v1.6 EVICT-02; v1.8 30-03) applies. Plan ROADMAP names a subset; audit found a broader set. **All surfaced sites are in scope** (audit treated as enforcement, not exception).
- **D-AUDIT-02 (MYPY-03 bare ignores):** Plan scope expands from 1 named site to **4 sites**:
  - `services/nlu/nlu_service.py:538` (named in ROADMAP)
  - `tests/integration/test_ragas_eval.py:442` (surfaced by audit)
  - `tests/unit/test_extractor_coverage.py:152` (surfaced by audit)
  - `tests/unit/test_extractor_coverage.py:300` (surfaced by audit)
- **D-AUDIT-03 (MYPY-04 untyped imports):** Plan scope expands from 2 named lines in `test_save_facts_toctou.py` to **all 4 asyncpg-shaped sites** in tests/, plus the deferred-items.md asyncpg sites (which fold into MYPY-02):
  - `tests/integration/memory/test_save_facts_toctou.py:32` — asyncpg (named)
  - `tests/integration/memory/test_save_facts_toctou.py:57` — pgvector.asyncpg (named)
  - `tests/integration/test_memory_forget_e2e.py:37` — asyncpg (surfaced)
  - `tests/integration/test_evict_long_term_facts_e2e.py:36` — asyncpg (surfaced)
- **D-AUDIT-04:** Planner MUST run a fresh `mypy --strict <bounded-scope>` audit at plan time and grep `# type: ignore[^[]` repo-wide to confirm the audit set has not drifted since 2026-05-18. If new sites surface between discuss and plan, fold them in without re-checkpointing.

### Stub install policy (MYPY-02 + MYPY-04)
- **D-STUB-01:** Install upstream stubs where available; silence-with-why otherwise. Highest fix-vs-silence ratio; real downstream typing benefit for the most-touched dep (`asyncpg` appears 5+ times across plan + deferred + audit-expanded scope).
- **D-STUB-02:** `uv add --dev asyncpg-stubs` — resolves asyncpg `import-untyped` at every site (toctou.py, memory_forget_e2e.py, evict_long_term_facts_e2e.py, indexer.py:9, scripts/backfill_fact_embeddings.py:32, scripts/evict_long_term_facts.py:63). One dependency add eliminates 6 silences.
- **D-STUB-03:** `uv add --dev pandas-stubs` — includes `pandas.api.types` (deferred-items.md `eval/ragas_runner.py:333`).
- **D-STUB-04:** For deps without upstream stubs (`pgvector.asyncpg`, `rank_bm25`, `datasets`) — silence with `# type: ignore[import-untyped]  # why: no upstream stubs; tracking: <upstream-issue-url-or-NA>`. The `<url>` is best-effort: file or link to existing GH issue requesting py.typed; "NA" acceptable if no public tracking exists.
- **D-STUB-05:** No local hand-rolled `stubs/` package. Excessive for a hardening phase; community stubs cover the high-traffic deps; per-site silence is acceptable for the long tail.
- **D-STUB-06:** Planner MUST verify on PyPI that `asyncpg-stubs` and `pandas-stubs` are currently maintained (last release ≤ 12 months) before committing to D-STUB-02/03. If stale, fall back to per-site silence and note in PLAN.

### Structural duplicate-module fix
- **D-STRUCT-01:** Add `explicit_package_bases = true` to `[tool.mypy]` in `pyproject.toml`. Config-only; zero blast radius outside type checking. Resolves the `scripts/evict_long_term_facts.py` duplicate-module entry in deferred-items.md.
- **D-STRUCT-02:** Do NOT add `scripts/__init__.py` — would make `scripts/` a real Python package, which (a) may affect entry-point invocation patterns (`python scripts/X.py` relative imports) and (b) requires audit of existing test imports from `scripts.*`. Out of scope for a config-bounded hardening phase.

### Verification / acceptance contract
- **D-VERIFY-01:** Per-MYPY-requirement file-scoped mypy command for each site, recorded as a check in the plan's must_haves:
  - MYPY-02: `cat deferred-items.md` shows 0 outstanding entries.
  - MYPY-03: `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/` returns empty.
  - MYPY-04: `uv run mypy --strict tests/integration/memory/test_save_facts_toctou.py tests/integration/test_memory_forget_e2e.py tests/integration/test_evict_long_term_facts_e2e.py` exits 0 with no `[import-untyped]` errors.
  - Bounded scope cap: `uv run mypy --strict services/ config/ utils/ controllers/ scripts/` followed by `grep -c '# type: ignore\[' <touched-files>` totals ≤ 25.
  - Tests/ silence count: `grep -rc '# type: ignore\[' tests/` recorded in 32-00-SUMMARY.md (informational, not gated).
- **D-VERIFY-02:** Test suite green count must not regress vs Phase 31 post-fix baseline (31 passed / 0 failed / 2 skipped / 3 errors under standard integration filter `-m 'integration and not real_llm and not benchmark'`). Adding `asyncpg-stubs` / `pandas-stubs` as `--dev` deps means CI deps grow by 2 — verify CI config still installs `--dev`.

### Claude's Discretion
- Specific silence-comment wording — phrase the `why:` clause to be self-explanatory; not user-reviewed per site.
- Order of execution within the plan (fix deferred → fix bare ignores → fix untyped imports, OR interleave per file). Planner picks based on dependency analysis.
- Whether to bundle into one plan (single 32-00) or split into two (32-00 stub install + structural fix; 32-01 audit-expanded silence sweep + bare-ignore replacement). Planner picks based on Wave / parallelism analysis.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plan / requirements / state
- `.planning/REQUIREMENTS.md` — MYPY-02, MYPY-03, MYPY-04 acceptance criteria
- `.planning/ROADMAP.md` §Phase 32 — Goal, Success Criteria, Canonical refs
- `.planning/PROJECT.md` §Active — v1.9 in-flight requirement list

### Deferred items (MYPY-02 source of truth)
- `./deferred-items.md` — 7 outstanding entries at repo root; format: H2 `## MYPY-01 overflow (deferred to v1.9)` with `### Files` bullet list

### Silence convention (locked from Phase 30-03)
- `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-03-SUMMARY.md` — Per-Silence Table, fix-vs-silence ratio (1/25), `# type: ignore[code]  # why:` convention
- `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-CONTEXT.md` — original cap=25 decision rationale (Phase 29 baseline = 40 mypy errors)

### Specific target sites
- `services/nlu/nlu_service.py:538` — bare `# type: ignore` (MYPY-03 named)
- `tests/integration/memory/test_save_facts_toctou.py:32,57` — asyncpg + pgvector.asyncpg import-untyped (MYPY-04 named)
- `tests/integration/test_ragas_eval.py:442` — bare ignore (audit-expanded MYPY-03)
- `tests/unit/test_extractor_coverage.py:152,300` — bare ignores (audit-expanded MYPY-03)
- `tests/integration/test_memory_forget_e2e.py:37` — asyncpg import-untyped (audit-expanded MYPY-04)
- `tests/integration/test_evict_long_term_facts_e2e.py:36` — asyncpg import-untyped (audit-expanded MYPY-04)

### Codebase intel
- `.planning/codebase/CONVENTIONS.md` §Code Style — type hint conventions (`from __future__ import annotations`, modern union syntax, Pydantic V2 inter-stage)
- `.planning/codebase/STACK.md` — runtime / dep landscape relevant to stub-install policy

### Related upstream (best-effort, planner verifies live)
- PyPI `asyncpg-stubs` — community stub for asyncpg (D-STUB-02 dependency)
- PyPI `pandas-stubs` — official-adjacent pandas type stubs (D-STUB-03 dependency)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `# type: ignore[<code>]  # why: <reason>` convention — already applied 25× across `config/settings.py`, `controllers/api.py`, `services/memory/memory_service.py`, `services/vectorizer/vector_store.py` and 12 other files (Phase 30-03). Phase 32 silences follow this verbatim.
- `[tool.mypy]` section in `pyproject.toml` — already configured for `--strict` runs; Phase 32 adds the `explicit_package_bases` key.

### Established Patterns
- Bounded-scope mypy sweep (Phase 30-03): the sweep ran over a defined module set; tests/ historically uncapped. Phase 32 codifies this rather than redefining it.
- Audit-mode-before-enforce (v1.6 EVICT-02; v1.8 30-03): metric-first; the audit-surfaced sites in MYPY-03/MYPY-04 are treated as enforcement-in-scope, not silently skipped.

### Integration Points
- `pyproject.toml` `[tool.mypy]` — config edit lands here (D-STRUCT-01) + optional `[tool.uv.dev-dependencies]` if uv requires explicit grouping for `asyncpg-stubs` / `pandas-stubs`.
- CI mypy step — must continue to run after Phase 32; verify dep-install command picks up `--dev` group so stubs are present in CI.

</code_context>

<specifics>
## Specific Ideas

- User explicitly chose recommended options across all 4 gray areas → strong signal to favor audit-mode discipline, upstream-stub-first, config-only structural fix, and bounded-scope cap with separate tests/ tracking.
- Verifier MUST report tests/ silence count even though it is not gated (audit-before-enforce mirror).

</specifics>

<deferred>
## Deferred Ideas

- **Drive tests/ silence count toward 0** — would require ~200 LOC of test-fixture / test-helper type annotation work. Belongs in a future test-infra polish phase, not v1.9 reliability burn-down.
- **Hand-roll local `stubs/` package** — considered for `pgvector.asyncpg` + `rank_bm25` + `datasets`; rejected as excessive for v1.9. Reconsider if any of these grows past 10 call-sites or surfaces real type-related production bugs.
- **Convert `scripts/` to a real package** (`scripts/__init__.py`) — rejected per D-STRUCT-02. Reconsider if entry-point invocation patterns change for other reasons.

</deferred>

---

*Phase: 32-mypy-strict-cleanup*
*Context gathered: 2026-05-18*
