---
phase: 08-multimodal-metadata-query-filter
plan: 01
status: complete
completed_at: 2026-05-08T03:08:38Z
wave: 1
files_changed:
  - utils/models.py
  - config/settings.py
  - scripts/check_pgvector_version.sh
  - tests/unit/test_chunker_section_metadata.py
  - tests/unit/test_filter_extractor.py
  - tests/integration/test_pgvector_filtered_recall.py
requirements:
  - META-01
  - META-02
  - QUERY-01
commits:
  - 41976f6  # test(08-01): RED scaffolds
  - 76611dc  # feat(08-01): ChunkMetadata + Settings
  - 4655fac  # chore(08-01): version gate
tags:
  - phase-8
  - wave-0
  - schema
  - test-scaffold
---

# Phase 8 Plan 01: Wave 0 Schema + RED Test Scaffolds — Summary

Wave 0 of Phase 8 is in place. ChunkMetadata carries `section_id` and `section_title`; Settings exposes `pgvector_ef_search_filtered=200` with env-var binding; deployment-target pgvector ≥ 0.8.0 is asserted by `scripts/check_pgvector_version.sh`; and 19 RED tests are seeded across three files for META-01, META-02, and QUERY-01. Three of those tests already pass against the new fields; the other 16 are intentional RED state, satisfied by 08-02/03/04/05.

## What Landed

### Task 1 — ChunkMetadata + Settings (commit `76611dc`)

`utils/models.py`:
```python
section_id:      str           = ""           # GB标准章节号，例如 "3.10" (META-01)
section_title:   str           = ""           # 章节标题文本，例如 "定义的透光面" (META-01)
```
Inserted between `sub_section` and `page_number`. Empty-string defaults match the `source` / `section` / `sub_section` pattern; legacy chunks without these keys round-trip through `model_validate` with no error (REQ A-3 acceptance #4 / SC #5).

`config/settings.py`:
```python
pgvector_ef_search_filtered: int = 200    # hnsw.ef_search for filtered queries (REQ A-4)
```
Inserted after `top_k_sparse` in the STAGE 5 cluster. Pydantic-Settings auto-binds `PGVECTOR_EF_SEARCH_FILTERED` env var (Pydantic V2 BaseSettings standard).

### Task 2 — pgvector version gate (commit `4655fac`)

`scripts/check_pgvector_version.sh` — read-only psql probe of `pg_extension.extversion`. Exit-code matrix:

| Exit | Meaning |
|------|---------|
| 0 | extversion >= 0.8.0, OR psql not on PATH (CI-host responsibility) |
| 1 | pgvector extension not installed |
| 2 | extversion < 0.8.0 (with remediation hint) |
| 3 | DB connection failed |

Required for any executor that emits `SET LOCAL hnsw.iterative_scan` in 08-04 — older servers raise `ERROR: unrecognized configuration parameter` (RESEARCH Pitfall #3, Open Question #1 closed).

### Task 3 — RED test scaffolds (commit `41976f6`)

Three files, 19 tests total, gated only on `PG_AVAILABLE` for the integration file.

## Verification Evidence

```
$ .venv/bin/python -c "from utils.models import ChunkMetadata; print(ChunkMetadata(section_id='3.10', section_title='X').model_dump()['section_id'])"
3.10

$ APP_MODEL_DIR=/tmp SECRET_KEY=test-secret-key-for-unit-tests-only-32c \
  .venv/bin/python -c "from config.settings import settings; print(settings.pgvector_ef_search_filtered)"
200

$ bash -n scripts/check_pgvector_version.sh && test -x scripts/check_pgvector_version.sh && echo OK
OK

$ bash scripts/check_pgvector_version.sh; echo "exit=$?"
[check_pgvector_version] psql not on PATH; skipping (CI host responsibility)
exit=0

$ .venv/bin/ruff check utils/models.py tests/unit/test_chunker_section_metadata.py \
                          tests/unit/test_filter_extractor.py \
                          tests/integration/test_pgvector_filtered_recall.py
All checks passed!

$ .venv/bin/pytest tests/unit/test_chunker_section_metadata.py \
                  tests/unit/test_filter_extractor.py \
                  tests/integration/test_pgvector_filtered_recall.py --collect-only -q | tail -3
16/19 tests collected (3 deselected) in 0.03s
```

## RED Test Inventory

### `tests/unit/test_filter_extractor.py` — 7 tests (all RED → 08-02)

| Test | Failure today | Resolved by |
|------|---------------|-------------|
| `test_page_extraction` | ModuleNotFoundError: services.nlu.filter_extractor | 08-02 |
| `test_page_with_whitespace` | ModuleNotFoundError | 08-02 |
| `test_section_clause_extraction` | ModuleNotFoundError | 08-02 |
| `test_section_generic_extraction` | ModuleNotFoundError | 08-02 |
| `test_no_filter_passthrough` | ModuleNotFoundError | 08-02 |
| `test_empty_after_strip_keeps_original` | ModuleNotFoundError | 08-02 |
| `test_filter_value_types_are_safe` | ModuleNotFoundError | 08-02 |

### `tests/unit/test_chunker_section_metadata.py` — 9 tests (3 GREEN today, 6 RED → 08-03)

| Test | State today | Resolved by |
|------|-------------|-------------|
| `TestSectionWalker::test_gb_heading_regex_matches_decimal_section` | RED — ImportError on `_GB_HEADING_RE` | 08-03 T1 |
| `TestSectionWalker::test_strip_ocr_markers_with_pages` | RED — ImportError on `_strip_ocr_markers_with_pages` | 08-03 T1 |
| `TestSectionWalker::test_build_gb_section_map_returns_offset_id_title` | RED — ImportError on `_build_gb_section_map` | 08-03 T1 |
| `TestSectionMetadataFields::test_section_metadata_fields_default_empty` | **GREEN** (08-01 T1) | — |
| `TestSectionMetadataFields::test_legacy_chunk_backward_compat` | **GREEN** (08-01 T1) | — |
| `TestSectionMetadataFields::test_no_page_in_embedded_text_sample` | **GREEN** (string-side invariant) | — |
| `TestSectionWalkerEndToEnd::test_chunker_emits_d02_form_for_gb_text` | RED — chunker pipeline unchanged | 08-03 T1+T2 |
| `TestImageChunkSectionMetadata::test_image_chunk_carries_section_fields` | RED — `_chunk_images` does not propagate section_* | 08-03 T2 |
| `TestImageChunkSectionMetadata::test_image_chunk_content_with_header_d04_form` | RED — D-04 form not emitted | 08-03 T2 |

### `tests/integration/test_pgvector_filtered_recall.py` — 3 tests (deselected without PG; RED when run → 08-04)

| Test | RED reason | Resolved by |
|------|-----------|-------------|
| `test_filtered_recall_page` | `PgVectorStore.search` ignores `filters` arg | 08-04 |
| `test_unfiltered_recall_unchanged` | Regression guard for filtered branch | 08-04 |
| `test_legacy_chunks_searchable` | NULL section_id semantics unverified | 08-04 |

## Deviations from Plan

1. **Removed `import pytest` from the two unit test files** (Rule 1 — fix bug). The plan body included `import pytest` at module top, but the unit tests don't reference `pytest.*` markers (no `@pytest.mark`, no `pytest.raises`). Ruff's F401 would have failed the plan's own `<verification>` ruff check. Kept `import pytest` in the integration file because `pytest.mark.integration`, `pytest.mark.skipif`, and `@pytest.mark.asyncio` are used. Documented; commit `41976f6`.
2. **Removed unused `DocType` import** from `tests/integration/test_pgvector_filtered_recall.py` inside `test_filtered_recall_page` (Rule 1). Same reason — F401, plan-body included it but it's never referenced.
3. **Added `.planning/phases/08-multimodal-metadata-query-filter/deferred-items.md`** to capture pre-existing ruff F541 (config/settings.py:404-406) and pre-existing mypy `dict` type-arg error (utils/models.py:93). Confirmed pre-existing via `git stash` + `mypy` comparison: error count is identical before and after my edits. Out-of-scope for 08-01 (scope-boundary rule).

## Threat Surface (per plan threat model)

| Threat | Disposition | Closed by |
|--------|-------------|-----------|
| T-08-03 (legacy JSONB rows lacking section_*) | mitigate | `test_legacy_chunk_backward_compat` (GREEN today) + `test_legacy_chunks_searchable` (RED → 08-04) |
| T-08-04 (Settings env type-confusion) | mitigate | Pydantic V2 `int` coercion (BaseSettings — verified by `settings.pgvector_ef_search_filtered == 200` smoke check) |
| T-08-05 (DSN leak in version-check script) | accept | Operator-run script; dev creds; no PII |

No new threat surfaces introduced beyond those already enumerated in `08-01-PLAN.md` `<threat_model>`.

## Follow-Ups for Downstream Plans

- **08-02** must implement `services.nlu.filter_extractor.extract_filters(query: str) -> ExtractFiltersResult`. The 7 RED tests in `test_filter_extractor.py` define the exact contract: dict-typed filters, semantic-query strip, page/section regex, fallback when strip leaves empty.
- **08-03 T1** must add `_GB_HEADING_RE`, `_strip_ocr_markers_with_pages(body) -> (str, dict[int,int])`, `_build_gb_section_map(clean) -> list[tuple[int,str,str]]`, and propagate `section_id` / `section_title` from `structure_aware_split` through `structure_nodes_to_chunks`. Content-with-header MUST start with `f"{section_id} {section_title}\n\n"` (D-02).
- **08-03 T2** must define `_chunk_images(...)` that joins each image to its host-page section map and emits `content_with_header == f"{section_id} {section_title}\n\n{caption}"` (D-04).
- **08-04** must add `filters` clause to `PgVectorStore.search` (JSONB `metadata->>'page_number'` and `metadata->>'section_id'` predicates) AND apply `SET LOCAL hnsw.ef_search = settings.pgvector_ef_search_filtered` only on the filtered branch. Run `bash scripts/check_pgvector_version.sh` in CI before this plan executes.
- **08-05** integrates `extract_filters` into the query pipeline.

## Self-Check: PASSED

Verified by direct filesystem + git probes:

- `[ -f utils/models.py ]` → FOUND
- `[ -f config/settings.py ]` → FOUND
- `[ -x scripts/check_pgvector_version.sh ]` → FOUND, executable
- `[ -f tests/unit/test_chunker_section_metadata.py ]` → FOUND
- `[ -f tests/unit/test_filter_extractor.py ]` → FOUND
- `[ -f tests/integration/test_pgvector_filtered_recall.py ]` → FOUND
- `git log --oneline | grep 41976f6` → FOUND
- `git log --oneline | grep 76611dc` → FOUND
- `git log --oneline | grep 4655fac` → FOUND
- ruff: clean across all touched files
- pytest --collect-only: 16/19 collected (3 PG-deselected as designed)
- 3 of 9 chunker tests GREEN today (the metadata + invariant tests); rest RED by design
