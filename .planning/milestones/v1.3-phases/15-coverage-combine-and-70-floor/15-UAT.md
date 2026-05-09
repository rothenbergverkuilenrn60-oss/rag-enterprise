---
status: complete
phase: 15-coverage-combine-and-70-floor
source:
  - .planning/phases/15-coverage-combine-and-70-floor/15-01-SUMMARY.md
  - .planning/phases/15-coverage-combine-and-70-floor/15-02-SUMMARY.md
started: 2026-05-09T17:45:00.000Z
updated: 2026-05-09T18:00:00.000Z
---

## Current Test

[testing complete]

## Tests

### 1. Combined Coverage Floor Gate (Local)
expected: Running combined `coverage report --fail-under=70` locally against the post-Wave-2 unit suite produces a TOTAL row >= 70% and exits 0. Per-module breakdown is visible in the table.
result: pass

### 2. pyproject.toml Coverage Config Blocks Present
expected: `pyproject.toml` contains a `[tool.coverage.run]` block with `source = ["services", "utils"]` and `parallel = false`, plus a `[tool.coverage.report]` block with `fail_under = 70`, `show_missing = true`, and `precision = 1`. The blocks were added by Wave 1 (commit 8fb1722) and remain unchanged after Wave 2.
result: pass

### 3. CI 3-Job Coverage Topology
expected: `.github/workflows/ci.yml` defines three coverage-relevant jobs: `unit-tests` (writes `.coverage.unit`), `integration-tests` (writes `.coverage.integration` with `--cov-append`, `continue-on-error: true`), and `coverage-combine` (with `needs: [unit-tests, integration-tests]` and `if: always()`). The `unit-tests` job no longer passes `--cov-fail-under=46` to pytest.
result: pass

### 4. coverage-combine Job Enforces Floor + diff-cover
expected: The `coverage-combine` job in `.github/workflows/ci.yml` checks out with `fetch-depth: 0`, downloads both `coverage-unit` and `coverage-integration` artifacts, runs `coverage combine --keep`, then runs `coverage report --fail-under=70` (TEST-06 hard gate) and `diff-cover coverage.xml --compare-branch=v1.0 --fail-under=80 --format html:diff-cover.html` (TEST-04 AC#3 migrated from unit-tests). It uploads a `coverage-report` artifact containing `.coverage`, `.coverage.unit`, `.coverage.integration`, `coverage.xml`, and `diff-cover.html`.
result: pass

### 5. README Coverage Section Documents New Flow
expected: `README.md` has a §Coverage section explaining the combined unit + integration flow with the 70% floor, and explicitly cites that Phase 15 D-05 supersedes Phase 10 D-03 (diff-cover migrated from `unit-tests` to `coverage-combine`). The section was rewritten in Wave 1 commit 5cd93d2.
result: pass

### 6. Makefile coverage-combined Target Mirrors CI
expected: `Makefile` has a `coverage-combined` target (added by Wave 1 commit 5cd93d2) that runs unit + integration + combine + `coverage report --fail-under=70` locally for developer DX. The pre-existing `coverage-diff` target is preserved unchanged. `.PHONY` is updated to include the new target.
result: pass

### 7. 20 New Wave-2 Test Files Exist and Pass
expected: 20 new `test_*.py` files exist under `tests/unit/` covering the 20 services/ modules below 70% at v1.2 close (audit_service helpers, indexer, ab_test extra, annotation, mcp_server, reranker, version_service, embedder extra, event_bus extra, memory_service extra, oidc_auth, knowledge_service extra, summary_indexer, entity_disambiguator, nlu_service extra, vector_store filter_where, llm_client helpers, pipeline helpers, retriever helpers, extractor helpers). Running `uv run --no-sync pytest tests/unit/ -x -q --ignore=tests/unit/test_pgvector_store.py` exits 0 with all new tests green.
result: pass

### 8. Each Wave-2 File Has Happy + Error Path
expected: Every new Wave-2 test file contains at least one happy-path test and at least one error-path test (the latter typically asserts a swallowed exception, fallback return, or pytest.raises). This satisfies TEST-06 AC#4 "covering its primary execution path" for every services/ module previously below 70%.
result: pass

### 9. ruff Clean on All New Test Files
expected: `uv run --no-sync ruff check tests/unit/test_audit_service_helpers.py tests/unit/test_indexer_service.py tests/unit/test_ab_test_service_extra.py tests/unit/test_annotation_service.py tests/unit/test_mcp_server.py tests/unit/test_reranker_service_app.py tests/unit/test_version_service.py tests/unit/test_embedder_extra.py tests/unit/test_event_bus_extra.py tests/unit/test_memory_service_extra.py tests/unit/test_oidc_auth.py tests/unit/test_knowledge_service_extra.py tests/unit/test_summary_indexer.py tests/unit/test_entity_disambiguator.py tests/unit/test_nlu_service_extra.py tests/unit/test_vector_store_filter_where.py tests/unit/test_llm_client_helpers.py tests/unit/test_pipeline_helpers.py tests/unit/test_retriever_helpers.py tests/unit/test_extractor_helpers.py` reports "All checks passed!".
result: pass

### 10. No Production Code Modified, No New Deps
expected: `git diff 2b9933c~25..HEAD -- services/ utils/` is empty (no production code touched in either wave); pyproject.toml `[project]` and `[dependency-groups] dev` sections add no new packages versus the pre-Phase-15 baseline; no test files were added under `tests/integration/`.
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
