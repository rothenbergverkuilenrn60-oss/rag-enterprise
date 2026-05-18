# EnterpriseRAG — v1.9 Hardening Round 3 Requirements

**Milestone:** v1.9 Hardening Round 3
**Status:** 📝 Planning (REQUIREMENTS scoped; ROADMAP written 2026-05-18)
**Opened:** 2026-05-18
**Phase numbering:** Continues from v1.8 (last phase = 30); v1.9 starts at **Phase 31**.

**Goal:** Close v1.8-deferred debt — eliminate residual event-loop singleton leaks (EVT-01 carry-over), finish mypy `--strict` cleanup (MYPY-01 overflow + bare ignores + asyncpg untyped imports), stabilize test infra (autouse-mock opt-out marker, order-dependent flaky failures, sentinel drift), and backfill missing planning artifacts (Nyquist VALIDATION.md, MILESTONES.md v1.7 entry). Zero new user-facing capabilities — pure reliability + test infra polish + process polish.

**Carry-forward gates** (inherited from v1.8): `diff-cover ≥ 80%` on touched files; combined coverage `--fail-under=70`; INSERT-ONLY `audit_log` invariant; audit-mode-before-enforce; audit-write failure must NOT block destructive action; `# type: ignore[code]  # why:` silence convention (mypy violations cap = 25; deferred-items cap = 7); `BaseTool` ABC + `AGENT_TOOL_ALLOWLIST` constant preserved.

## Categorized ID Schema

| Prefix | Category | Description |
|--------|----------|-------------|
| `EVT-` | Event-loop singleton leaks | Residual fixture sites left over from v1.8 Phase 30-01 supersession |
| `MYPY-` | mypy --strict cleanup | Deferred violations, bare ignores, untyped-import silences |
| `TEST-` | Test infra hygiene | Autouse-mock opt-out marker, order-dependent failures, sentinel drift |
| `DOC-` | Planning artifact backfill | Nyquist VALIDATION.md, missing MILESTONES.md entry |

## Active Requirements (v1.9)

### Event-loop Singleton Leaks

- [x] **EVT-02**: Enumerate + fix all remaining event-loop singleton leak sites surfaced during v1.8 Phase 30 (Plan 30-01 superseded — ~10 sites deferred). Grow `_SINGLETON_INVENTORY` from 34 toward 48 on a PG-enabled host. Each leak site is a module-level instance whose constructor binds to whatever event loop existed at import time, causing `RuntimeError: ... attached to a different loop` when fixtures recreate the loop.
  - **Acceptance:** PG-host run of full suite (`pytest -m integration --uses-redis`) reports zero "different loop" failures; `_SINGLETON_INVENTORY` lint passes with the new count.
  - **Reference:** `.planning/milestones/v1.8-MILESTONE-AUDIT.md` tech-debt block; `tests/factories/app.py::_SINGLETON_INVENTORY`.

### mypy `--strict` Cleanup

- [x] **MYPY-02**: Resolve all 7 deferred violations recorded in `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/deferred-items.md` (overflow beyond the 25-silence cap). Cap drains to ≤ 0 entries.
  - **Acceptance:** `deferred-items.md` listed entries reach zero; full repo `mypy --strict` reports ≤ 0 net new violations vs v1.8 close baseline (target ≤ 25 silences total).

- [x] **MYPY-03**: Replace bare `# type: ignore` at `services/nlu/nlu_service.py:538` with the v1.8 `# type: ignore[code]  # why:` convention. Pre-existing since v1.3/v1.6 — left untouched at v1.8 close because it was outside the Plan 30-03 scope window.
  - **Acceptance:** Targeted error code present; explanatory `# why:` comment present; `mypy --strict services/nlu/nlu_service.py` exits 0 with no new findings.

- [x] **MYPY-04**: Resolve asyncpg + pgvector.asyncpg `import-untyped` silences in `tests/integration/memory/test_save_facts_toctou.py:32, 57`. Either upstream stubs landed (verify), or local stubs added to `stubs/` dir, or `[code]  # why:` form applied with concrete upstream-tracking link.
  - **Acceptance:** Both lines pass `mypy --strict tests/integration/memory/test_save_facts_toctou.py` without `[import-untyped]` errors.

### Test Infra Hygiene

- [ ] **TEST-08**: Add `@pytest.mark.real_embedder` opt-out marker so the `tests/integration/conftest.py` autouse fixture (which mocks `HuggingFaceEmbedder.__init__` + `CrossEncoderReranker.__init__`) honors a per-test opt-out. Tests marked `@pytest.mark.real_embedder` must observe the real implementation classes — autouse mock skips itself when marker is present.
  - **Acceptance:** Marker registered in `pyproject.toml` / `pytest.ini`; autouse fixture conditionally early-returns when `request.node.get_closest_marker("real_embedder")` is non-None; at least one canary test exists exercising the real-embedder path on PG host; documented in `docs/RUNBOOK.md` test-infra section.

- [ ] **TEST-09**: Fix 7 pre-existing order-dependent unit-test failures (registry-singleton pollution between tests + `embed_one`/`embed_batch` mock-shape mismatch from v1.7 batch API migration). Failures only manifest in certain `-p random_order` permutations, masking the underlying state leak.
  - **Acceptance:** Full unit suite passes under `pytest --random-order --random-order-seed=<fixed>` for at least 3 distinct seeds; registry singletons reset via fixture in `tests/conftest.py`; mock-shape parity restored (consumers patch the same callable signature regardless of single-vs-batch path).

- [ ] **TEST-10**: Refresh `tests/test_pipeline_load_context_audit::test_no_v1_5_regression` for the GenerationRequest schema drift (v1.5 introduced `query=`; test still uses pre-v1.5 `q=` kwarg, triggering ValidationError).
  - **Acceptance:** Test instantiates GenerationRequest with `query=` (matching current Pydantic V2 model); test passes against current `services/pipeline.py`; original v1.5-regression intent preserved (no scope creep — the test still verifies what it was written to verify).

- [ ] **TEST-11**: Refresh `tests/test_ui_static::test_ui_static_serves_html` `<title>` sentinel — current sentinel was minted against v1.0 UI; v1.4 frontend rewrite (`static/ui.html` split into ui.css + ui.js) drifted the `<title>` value. Test now fails because sentinel no longer matches served HTML.
  - **Acceptance:** Sentinel updated to match current `static/ui.html` `<title>` text; test passes; brief commit-message note records the v1.4-drift root cause so future drifts have a tracking precedent.

### Planning Artifact Backfill

- [ ] **DOC-02**: Backfill Nyquist `VALIDATION.md` for Phase 29 + 30 via `/gsd:validate-phase 29` + `/gsd:validate-phase 30` on the live `.planning/milestones/v1.8-phases/29-toctou-silent-skip-enforcement/` and `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/` directories. Both phases shipped without Nyquist coverage — milestone audit flagged this as process gap.
  - **Acceptance:** `29-VALIDATION.md` + `30-VALIDATION.md` files exist; each documents Nyquist gates considered, evidence assembled, validation verdict; gsd-nyquist-auditor returns `passed` for both phases.

- [ ] **DOC-03**: Backfill missing MILESTONES.md v1.7 entry — v1.7-close oversight (v1.7 shipped without appending its summary to the repo-root MILESTONES.md ledger). Mirror v1.6 + v1.8 entries: 6-deliverable bullet list, accomplishments, deferred items, audit reference.
  - **Acceptance:** MILESTONES.md ledger contains v1.7 entry in chronological order between v1.6 and v1.8; format matches surrounding entries (same headers, same fields); `.planning/milestones/v1.7-ROADMAP.md` cross-referenced.

## Out of Scope

The following items remain on the carry-forward list (NOT v1.9-scoped) — explicit deferral with reasoning:

- **Code-acting / SQLTool (10x roadmap #4)** — sandbox selection unresolved; needs design phase first; v1.9 is debt-paydown not feature
- **RLS `app.current_tenant` per-connection production verification** — needs production-pool access we don't have in sandbox; defer to first production deploy
- **SSE memory events (memory.extracted, memory.recalled)** — new user-facing feature; v1.9 charter excludes new capabilities
- **Per-tenant capacity overrides / importance decay** — new memory-system feature; out of v1.9 charter
- **UI-03 React/Vue full migration** — large new-feature scope; carry-forward
- **TEST-07 mutation testing** — separate test-quality initiative; not part of v1.8 deferred items
- **UI-02 first-deploy browser smoke** — needs deploy infrastructure; defer to first deploy
- **Per-module coverage floor raise (>70%) or branch-coverage activation** — Phase 22 D-08 follow-up; separate initiative
- **PyMuPDF AGPL commercial licensing** — legal/business decision, not engineering
- **Docker Build CI fix (paddleocr ABI churn)** — infra-team scope; currently masked by `continue-on-error: true`
- **Phase 26-04 P1 backport to `LongTermMemory._get_pool`** — pre-v1.8 patch backport; consider v1.10 hygiene round
- **Close-then-reuse `_closed: bool` guard** — project-wide pattern adoption; consider v1.10
- **AuditService `application_name=audit_service`** — observability polish; consider v1.10

## Traceability

Each REQ-ID maps to exactly one phase. Coverage: 10/10. No orphans. No duplicates.

| REQ-ID | Phase | Plan(s) |
|--------|-------|---------|
| EVT-02 | 31 | TBD |
| MYPY-02 | 32 | TBD |
| MYPY-03 | 32 | TBD |
| MYPY-04 | 32 | TBD |
| TEST-08 | 33 | TBD |
| TEST-09 | 33 | TBD |
| TEST-10 | 34 | TBD |
| TEST-11 | 34 | TBD |
| DOC-02 | 35 | TBD |
| DOC-03 | 35 | TBD |

## Future Requirements (v1.10+ carry-forward)

See "Out of Scope" above for the full carry-forward list. Items there are deferred (not invalidated) and will be re-evaluated at v1.10 planning.
