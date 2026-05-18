---
phase: 30
slug: test-infra-mypy-hardening
status: backfilled
nyquist_compliant: true
backfilled: 2026-05-18
original_phase_shipped: 2026-05-17
backfilled_by: phase-35-doc-02
---

# Phase 30 — Validation Strategy (Backfilled)

> Retroactive Nyquist validation. Phase 30 shipped 2026-05-17 (3 of 4 plans
> + 1 superseded via orchestrator override; documented in 30-VERIFICATION.md).
> This file backfills the missing artifact per Phase 35 DOC-02.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + mypy --strict + asyncpg integration |
| **Config file** | `pyproject.toml` `[tool.mypy]` (strict mode) + `pytest.ini` (markers) |
| **Quick run command** | `uv run mypy --strict <file>` + `uv run pytest tests/unit/<file> -q` |
| **Full suite command** | `uv run mypy --strict .` (silence count) + `uv run pytest -m 'integration and not real_llm and not benchmark' -q` |
| **Live PG host** | `docker rag-postgres / pgvector/pgvector:pg16 / PG 16.13 / vector 0.8.2` |

---

## Sampling Rate

- **Per task commit:** mypy --strict on touched file + unit run on impacted tests
- **Per plan wave:** full mypy --strict silence-count tally + diff vs prior
- **Pre-ship:** integration suite baseline + extractor_e2e on live PG (to validate Plan 30-02 autouse mock didn't break real-model paths)

---

## Per-Requirement Verification Map

| Gate ID | Requirement | Test Type | Authoritative Command | Source Plan | Verified |
|---------|-------------|-----------|------------------------|-------------|----------|
| OAI-01 | APIError SDK-drift cleanup | unit | `uv run pytest tests/unit/ -q` → 1200 passed (vacuously: 0 stale callsites; `make_api_error()` helper landed for future drift) | 30-00 | ✅ (override-accepted, scope pivot documented in 30-VERIFICATION) |
| EVT-01 | +14 event-loop leak sites migrated to create_app() | integration / live PG | enumeration deferred — 4 of ~14 sites fixed via 30-00 pivot; remaining ~10 deferred to v1.9 Phase 31 | 30-01 (skipped) | ⏭ DEFERRED to Phase 31 (v1.9 EVT-02 — closed 2026-05-18) |
| TEST-INFRA-01a | Autouse mock for HuggingFaceEmbedder.__init__ | integration / live PG | `uv run pytest tests/integration/test_extractor_e2e.py -v -m integration` → 2 passed (no bge-m3 FileNotFoundError) | 30-02 | ✅ |
| TEST-INFRA-01b | CrossEncoderReranker mock (Rule-2 deviation absorbed) | integration / live PG | same as TEST-INFRA-01a — both classes mocked in `tests/integration/conftest.py::_mock_local_model_inits` | 30-02 | ✅ |
| MYPY-01a | Strict-mode error count drained 32→7 | static | `uv run mypy --strict .` → ≤ 25 silences remain (cap honored); 7 deferred to v1.9 Phase 32 | 30-03 | ✅ |
| MYPY-01b | Named site clean | static | `uv run mypy --strict services/<named-modules>` → 0 errors at named callsites | 30-03 | ✅ |

---

## Override / Deferral Sign-Off

- **EVT-01 deferred to v1.9 Phase 31 (EVT-02)**: orchestrator-accepted post-30-00 deviation. Plan 30-01 skipped. Remaining ~10 leak sites required PG-host enumeration; deferred to Phase 31 which subsequently grew `_SINGLETON_INVENTORY` 34→48 and closed the gap.
- **OAI-01 vacuous pass**: 0 stale APIError callsites on master at verify time. `make_api_error()` helper landed for forward-drift protection.

---

## Validation Sign-Off

- [x] All 4 v1.8 Phase 30 must-haves have automated verify (2 live + 2 override-accepted)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0: no new infrastructure needed
- [x] No watch-mode flags
- [x] Feedback latency < 60s for mypy gate; <120s for integration baseline
- [x] `nyquist_compliant: true` set — verified retroactively against 30-VERIFICATION evidence

**Approval:** retroactive — phase shipped 2026-05-17 with VERIFICATION passed; this file backfills the missing artifact 2026-05-18 (Phase 35 DOC-02). EVT-01 deferral subsequently closed in v1.9 Phase 31 (EVT-02 must-haves verified 2026-05-17).
