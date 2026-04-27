---
phase: 1
slug: pgvector-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-21
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pytest.ini` (exists) |
| **Quick run command** | `conda run -n torch_env pytest tests/ -x -q --tb=short -k pgvector` |
| **Full suite command** | `conda run -n torch_env pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~30 seconds (unit + integration with test DB) |

---

## Sampling Rate

- **After every task commit:** Run `conda run -n torch_env pytest tests/ -x -q --tb=short -k pgvector`
- **After every plan wave:** Run `conda run -n torch_env pytest tests/ -v --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | PG-05 | — | Protocol enforces parent chunk interface at class-definition time | unit | `conda run -n torch_env pytest tests/test_pgvector_store.py::test_base_protocol -xq` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | PG-01 | — | PgVectorStore.create_collection() creates table + HNSW index, no Qdrant import | unit | `conda run -n torch_env pytest tests/test_pgvector_store.py::test_create_collection -xq` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | PG-02 | — | HNSW index present; work_mem=256MB set on connection before index ops | integration | `conda run -n torch_env pytest tests/test_pgvector_store.py::test_hnsw_index -xq` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 1 | PG-03 | T-1-01 | Tenant B query with Tenant A token returns 0 results (RLS enforced) | integration | `conda run -n torch_env pytest tests/test_rls_isolation.py::test_cross_tenant_blocked -xq` | ❌ W0 | ⬜ pending |
| 1-04-01 | 04 | 1 | PG-04 | — | upsert_parent_chunks / fetch_parent_chunks round-trip: stored content matches retrieved | integration | `conda run -n torch_env pytest tests/test_pgvector_store.py::test_parent_chunk_roundtrip -xq` | ❌ W0 | ⬜ pending |
| 1-05-01 | 05 | 2 | PG-01 | — | Pipeline ingest stores in PostgreSQL; no qdrant_client import triggered at runtime | integration | `conda run -n torch_env pytest tests/test_pipeline_pgvector.py::test_ingest_uses_pgvector -xq` | ❌ W0 | ⬜ pending |
| 1-05-02 | 05 | 2 | PG-01 | — | pgvector vector codec registered on pool init (no asyncpg type codec errors) | unit | `conda run -n torch_env pytest tests/test_pgvector_store.py::test_codec_registration -xq` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pgvector_store.py` — stubs for PG-01, PG-02, PG-04, PG-05 (unit + integration)
- [ ] `tests/test_rls_isolation.py` — stubs for PG-03 (cross-tenant isolation)
- [ ] `tests/test_pipeline_pgvector.py` — stubs for PG-01 pipeline integration
- [ ] `tests/conftest.py` — shared fixtures: asyncpg test pool, test tenant setup, pgvector test DB
- [ ] `pgvector` Python package added to `requirements.txt` (currently missing — blocking)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| recall@10 within 5% of Qdrant baseline | PG-02 (HNSW quality) | Requires Qdrant baseline data; no automated benchmark in repo | Ingest 1000 docs into both backends; run 50 representative queries; compare top-10 overlap |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
