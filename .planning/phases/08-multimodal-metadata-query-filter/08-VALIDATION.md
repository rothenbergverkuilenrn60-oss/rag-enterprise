---
phase: 8
slug: multimodal-metadata-query-filter
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-08
updated_by: gsd-planner
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Wave 0 RED tests are seeded by 08-01-PLAN.md task 3 — every later plan is
> proven GREEN by flipping a specific test that already exists.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio (asyncio_mode=auto) |
| **Config file** | `pytest.ini` (project root) + `tests/conftest.py` |
| **Quick run command** | `pytest tests/unit -x -q --ignore=tests/integration` |
| **Full suite command** | `pytest tests/ -m "not slow" --cov=services --cov=utils` |
| **Integration command** | `pytest tests/integration/test_pgvector_filtered_recall.py -m integration -x -q` |
| **Estimated runtime** | quick ≈ 30s · full ≈ 90s · integration (with PG) ≈ 30s · integration (no PG) ≈ 1s (skip-gated) |
| **Pgvector gate** | `bash scripts/check_pgvector_version.sh` — exit 0 only if ≥ 0.8.0 |

---

## Sampling Rate

- **After every task commit:** quick command (`pytest tests/unit -x -q --ignore=tests/integration`)
- **After every plan wave:** full suite (`pytest tests/ -m "not slow"`)
- **Before `/gsd-verify-work`:** full suite GREEN + integration suite GREEN (or correctly SKIPPED if PG not local)
- **Pre-08-04 deployment gate:** `bash scripts/check_pgvector_version.sh` exits 0
- **Max feedback latency:** 30s (quick) / 90s (full) / 60s (single integration test)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01 T1 | 01 | 1 | META-01, META-02 | T-08-03, T-08-04 | section_id/title default ""; settings int-typed | unit | `pytest tests/unit/test_chunker_section_metadata.py::TestSectionMetadataFields -x` | tests/unit/test_chunker_section_metadata.py (RED) | ⬜ pending |
| 08-01 T2 | 01 | 1 | META-02 | T-08-10 | pgvector ≥ 0.8.0 deployment gate | shell | `bash -n scripts/check_pgvector_version.sh && test -x scripts/check_pgvector_version.sh` | scripts/check_pgvector_version.sh (NEW) | ⬜ pending |
| 08-01 T3 | 01 | 1 | META-01, META-02, QUERY-01 | — | RED test scaffolds for every SC | unit/integration | `pytest tests/unit/test_chunker_section_metadata.py tests/unit/test_filter_extractor.py --collect-only` | three new test files (RED) | ⬜ pending |
| 08-02 T1 | 02 | 1 | QUERY-01 | T-08-01, T-08-06 | typed filters; linear regex; no SQL surface | unit | `pytest tests/unit/test_filter_extractor.py -x -q` | tests/unit/test_filter_extractor.py | ⬜ pending |
| 08-03 T1 | 03 | 2 | META-01 | T-08-01 | _GB_HEADING_RE captures dotted-numeric only; `[一-鿿]` Chinese-leading title | unit | `pytest tests/unit/test_chunker_section_metadata.py::TestSectionWalker -x -q` | tests/unit/test_chunker_section_metadata.py | ⬜ pending |
| 08-03 T2 | 03 | 2 | META-01 | T-08-01, T-08-08, T-08-03 | D-02 leaf form; D-04 image prefix; legacy fallback | unit | `pytest tests/unit/test_chunker_section_metadata.py -x -q` | tests/unit/test_chunker_section_metadata.py | ⬜ pending |
| 08-04 T1 | 04 | 2 | META-02 | T-08-01, T-08-09 | _build_filter_where parameterised; bool-vs-int guard; B-tree partial indexes | unit | `pytest tests/unit/test_pgvector_store.py -x -q` (regression) + inline asserts in T1 verify block | services/vectorizer/vector_store.py | ⬜ pending |
| 08-04 T2 | 04 | 2 | META-02 | T-08-01, T-08-02, T-08-05, T-08-09, T-08-10 | SET LOCAL hnsw GUCs; RLS preserved; page_number=0 strip | integration | `pytest tests/integration/test_pgvector_filtered_recall.py -m integration -x -q` | tests/integration/test_pgvector_filtered_recall.py | ⬜ pending |
| 08-05 T1 | 05 | 3 | QUERY-01 | T-08-01, T-08-11 | extract → effective_query → tf merge precedence; cache_key uses stripped | unit | `pytest tests/unit/test_pipeline.py -x -q` (regression — no new pipeline unit test added; static greps cover the wiring) | services/pipeline.py | ⬜ pending |
| 08-05 T2 | 05 | 3 | QUERY-01, META-02 | T-08-01, T-08-02, T-08-09 | end-to-end extract → search → top-3 page-scoped | integration | `pytest tests/integration/test_pgvector_filtered_recall.py::test_pipeline_e2e_filter_propagation -m integration -x -q` | tests/integration/test_pgvector_filtered_recall.py | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `utils/models.py` extended with `ChunkMetadata.section_id` and `section_title` (default `""`) — 08-01 T1
- [ ] `config/settings.py` extended with `pgvector_ef_search_filtered: int = 200` — 08-01 T1
- [ ] `scripts/check_pgvector_version.sh` exists, executable, asserts pgvector ≥ 0.8.0 — 08-01 T2
- [ ] `tests/unit/test_chunker_section_metadata.py` exists with ≥ 9 RED test functions covering SC#1, SC#4, SC#5 — 08-01 T3
- [ ] `tests/unit/test_filter_extractor.py` exists with ≥ 7 RED test functions covering SC#3 — 08-01 T3
- [ ] `tests/integration/test_pgvector_filtered_recall.py` exists with ≥ 3 RED test functions covering SC#2, SC#5; pytestmark gates on `PG_AVAILABLE` — 08-01 T3
- [ ] All RED tests fail today (ImportError / AttributeError as designed) — verifiable via `pytest --collect-only`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| pgvector server version on production target | META-02 (deployment gate) | Requires access to the deployed PostgreSQL instance, not the dev machine | Run `bash scripts/check_pgvector_version.sh` against the production DSN; remediate via `apt-get install postgresql-16-pgvector` if exit code 2. Documented in 08-01 T2 acceptance criteria. |
| GB4785-2019.pdf full-document recall (REQ A-4 acceptance #4 against real OCR'd content) | META-02 | Requires live OCR pipeline + Phase 7 docker bake to be in place; the integration tests use synthetic embeddings to avoid coupling to the embedder | After `docker compose build rag-api` completes (Phase 7 outstanding work), run a full ingest of `data/raw/GB4785-2019.pdf` then issue query `第63页灯具的发光面` against `/api/v1/query` and verify the response cites a page-63 §3.10 chunk. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — VERIFIED in per-task map
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — VERIFIED (every task has a pytest or grep command)
- [x] Wave 0 covers all MISSING references — VERIFIED (08-01 T3 seeds three RED files; 08-02/03/04/05 each turn at least one of those tests GREEN)
- [x] No watch-mode flags — VERIFIED
- [x] Feedback latency < 60s (quick) / 300s (full) — VERIFIED (≈ 30s / ≈ 90s)
- [x] `nyquist_compliant: true` set in frontmatter — VERIFIED above

**Approval:** planner-self-approved (gsd-planner, 2026-05-08)
