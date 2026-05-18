---
phase: 29
slug: toctou-silent-skip-enforcement
status: backfilled
nyquist_compliant: true
backfilled: 2026-05-18
original_phase_shipped: 2026-05-17
backfilled_by: phase-35-doc-02
---

# Phase 29 — Validation Strategy (Backfilled)

> Retroactive Nyquist validation. Phase 29 shipped 2026-05-17 without a
> VALIDATION.md (process gap identified in v1.8 milestone audit). This file
> documents the gates that WERE used during execution, mapped to the evidence
> captured in 29-VERIFICATION.md. Per Phase 35 DOC-02.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio + asyncpg integration |
| **Config file** | `pytest.ini` (markers: integration, real_llm, uses_postgres) |
| **Quick run command** | `uv run pytest tests/unit/memory/<touched_file>.py -q` |
| **Full suite command** | `uv run pytest -m 'integration and not real_llm and not benchmark' -q` |
| **Live PG host** | `docker rag-postgres / pgvector/pgvector:pg16 / PG 16.13 / vector 0.8.2` |

---

## Sampling Rate

- **Per task commit:** unit-test file touched (~1-3 sec)
- **Per plan wave:** full unit + impacted integration tests
- **Pre-ship:** TOC-01 concurrent-writer integration test on live PG; SK-01 silent-skip integration test on live PG

---

## Per-Requirement Verification Map

| Gate ID | Requirement | Test Type | Authoritative Command | Source Task | Verified |
|---------|-------------|-----------|------------------------|-------------|----------|
| TOC-01a | TOCTOU concurrent-writer dedupe | integration / live PG | `uv run pytest tests/integration/memory/test_save_facts_toctou.py::test_save_facts_toctou_concurrent_writers_produce_one_row -v` → 1 passed (COUNT==1) | 29-00 | ✅ |
| TOC-01b | GUC preserved inside outer txn | integration / live PG | `tests/integration/memory/test_save_facts_toctou.py::test_save_facts_guc_preserved_inside_outer_txn` → 1 passed | 29-00 | ✅ |
| SK-01a | Near-duplicate silent-skip + audit emit | integration / live PG | `tests/integration/memory/test_memory_suite_factory_migrated.py::test_save_facts_with_near_duplicate_emits_audit_and_skips_silently_real_pg` → 1 passed | 29-01 | ✅ |
| SK-01b | Audit row written with MEMORY_NEAR_DUPLICATE_SKIPPED | integration | same as SK-01a (sub-assertion) | 29-01 | ✅ |
| TEST-INFRA-02a | Precheck rewritten against bulk-SELECT shape | unit | `uv run pytest tests/unit/memory/test_save_fact_precheck.py -q` → all green | 29-02 | ✅ |

---

## Validation Sign-Off

- [x] All v1.8 Phase 29 must-haves have automated verify (3/3 from 29-VERIFICATION.md)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0: no new infrastructure needed (live PG already in CI)
- [x] No watch-mode flags
- [x] Feedback latency < 30s for all gates
- [x] `nyquist_compliant: true` set — verified retroactively against 29-VERIFICATION evidence

**Approval:** retroactive — phase shipped 2026-05-17 with VERIFICATION passed; this file backfills the missing artifact 2026-05-18 (Phase 35 DOC-02). No re-execution required since shipped code matches verified evidence.
