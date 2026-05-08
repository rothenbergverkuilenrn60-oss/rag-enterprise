---
phase: 08-multimodal-metadata-query-filter
plan: 02
status: complete
completed_at: 2026-05-08T03:12:34Z
wave: 1
files_changed:
  - services/nlu/filter_extractor.py
requirements:
  - QUERY-01
commits:
  - b073cbc  # feat(08-02): implement Chinese query filter extractor (QUERY-01)
tags:
  - phase-8
  - wave-1
  - nlu
  - regex
  - query-filter
dependency_graph:
  requires:
    - tests/unit/test_filter_extractor.py  # Wave 0 RED scaffolds (08-01, commit 41976f6)
  provides:
    - services.nlu.filter_extractor.extract_filters
    - services.nlu.filter_extractor.FilterExtractionResult
  affects:
    - services/pipeline.py  # Will be wired in 08-05 (QueryPipeline integration)
tech_stack:
  added: []
  patterns:
    - "Module-level re.compile (frozen patterns)"
    - "@dataclass result with typed dict[str, int | str]"
    - "Stateless plain-def entry point (no class needed)"
key_files:
  created:
    - services/nlu/filter_extractor.py
  modified: []
decisions:
  - "Patterns frozen per D-03: _PAGE_RE / _CLAUSE_RE / _SECTION_RE; no English variants in v1.1"
  - "Clause variant matched before generic to avoid orphan '条款' suffix"
  - "Empty-after-strip falls back to original query (T-08-01 / Open Question #2)"
metrics:
  duration_seconds: 87
  tasks_completed: 1
  files_changed: 1
---

# Phase 8 Plan 02: Chinese Query Filter Extractor — Summary

**One-liner:** Regex-first Chinese page/section filter extractor (`extract_filters`) flips the 7 Wave 0 RED tests GREEN, lifting `第N页` / `N.M条款` / `N.M节` tokens out of the embedded query into a typed JSONB-ready filter dict.

## What Landed

### Task 1 — `services/nlu/filter_extractor.py` (commit `b073cbc`)

92-line, dependency-free module exporting:

```python
@dataclass
class FilterExtractionResult:
    filters:        dict[str, int | str] = field(default_factory=dict)
    semantic_query: str                  = ""

def extract_filters(query: str) -> FilterExtractionResult: ...

__all__ = ["FilterExtractionResult", "extract_filters"]
```

**Regex patterns (final form, LOCKED by CONTEXT.md D-03):**

| Name          | Pattern                       | Captures                       | Coercion          |
|---------------|-------------------------------|--------------------------------|-------------------|
| `_PAGE_RE`    | `第\s*(\d+)\s*页`             | `\d+` → page number            | `int(...)`        |
| `_CLAUSE_RE`  | `(\d+(?:\.\d+)+)条款`         | `\d+(?:\.\d+)+` → section id   | `str` (slice)     |
| `_SECTION_RE` | `(\d+(?:\.\d+)+)\s*节?`       | `\d+(?:\.\d+)+` → section id   | `str` (slice)     |

**Priority ordering rationale:** `_CLAUSE_RE` runs **before** `_SECTION_RE` because the generic section pattern uses `节?` (optional `节`), so without the clause guard it would also match the `3.10` inside `3.10条款`, leaving an orphan `条款` token in `semantic_query`. Page extraction runs first because it is the most specific surface form and never overlaps with section patterns. `count=1` on every `re.sub` so a query like `第63页 第64页…` extracts only the first page reference; later occurrences remain as semantic tokens.

**Empty-after-strip fallback:** `extract_filters("3.10节")` → `filters={"section_id": "3.10"}`, but stripping leaves `""`. The guard restores `semantic_query = query` so the embedder never sees an empty string (zero-vector / noise risk). The structured filter still applies downstream — recall is preserved while filter precision is improved.

**Type safety (T-08-01):** Captured groups are coerced before assignment — `int(m.group(1))` for page, raw string slice (already restricted to `\d+(?:\.\d+)+`) for section_id. SQL fragments in adversarial input (`第63页 SELECT * FROM x`) flow into `semantic_query` (will be embedded), never into `filters`. `test_filter_value_types_are_safe` enforces this invariant.

## Verification Evidence

```
$ APP_MODEL_DIR=/tmp SECRET_KEY=test-secret-key-for-unit-tests-only-32c \
  .venv/bin/pytest tests/unit/test_filter_extractor.py -v
============================= test session starts ==============================
collected 7 items

tests/unit/test_filter_extractor.py::TestExtractFilters::test_page_extraction PASSED                       [ 14%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_page_with_whitespace PASSED                  [ 28%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_section_clause_extraction PASSED             [ 42%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_section_generic_extraction PASSED            [ 57%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_no_filter_passthrough PASSED                 [ 71%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_empty_after_strip_keeps_original PASSED      [ 85%]
tests/unit/test_filter_extractor.py::TestExtractFilters::test_filter_value_types_are_safe PASSED           [100%]

============================== 7 passed in 0.02s ===============================

$ .venv/bin/ruff check services/nlu/filter_extractor.py
All checks passed!

$ .venv/bin/mypy --strict services/nlu/filter_extractor.py
Success: no issues found in 1 source file

$ APP_MODEL_DIR=/tmp SECRET_KEY=... .venv/bin/python -c "from services.nlu import filter_extractor; print(filter_extractor.__all__)"
['FilterExtractionResult', 'extract_filters']

$ APP_MODEL_DIR=/tmp SECRET_KEY=... .venv/bin/pytest tests/unit -q | tail -3
7 failed, 305 passed, 9 warnings in 14.94s
# 7 failures are pre-existing & out-of-scope:
#  - 6 in test_chunker_section_metadata.py: Wave 0 RED scaffolds for 08-03 (per 08-01 SUMMARY)
#  - 1 in test_worker_startup.py: pre-existing, unrelated to this plan
```

**Acceptance-criteria grep matrix (all PASS):**

| Check                                              | Expected | Actual |
|----------------------------------------------------|----------|--------|
| `grep -c 'def extract_filters'`                    | 1        | 1      |
| `grep -c '@dataclass'`                             | 1        | 1      |
| `grep -cE '_PAGE_RE\s*=\s*re\.compile'`            | 1        | 1      |
| `grep -cE '_CLAUSE_RE\s*=\s*re\.compile'`          | 1        | 1      |
| `grep -cE '_SECTION_RE\s*=\s*re\.compile'`         | 1        | 1      |
| `grep -v '^#' ... \| grep -c 'except'` (ERR-01)    | 0        | 0      |

## Deviations from Plan

**None.** Module body, regex patterns, dataclass field order, and entry-point signature were implemented exactly as specified in `08-02-PLAN.md` `<action>`. No bugs encountered, no missing critical functionality detected, no architectural pivots. The plan was complete and executable verbatim.

## Threat Surface (per plan threat model)

| Threat  | Disposition | Closed by |
|---------|-------------|-----------|
| T-08-01 (Filter-value injection) | mitigate | Restricted character classes (`\d+`, `\d+(?:\.\d+)+`) + `int()` coercion / `str` slice — verified by `test_filter_value_types_are_safe`. asyncpg `$N` parameterisation in 08-04 provides defense-in-depth. |
| T-08-06 (ReDoS)                  | mitigate | All three patterns are linear-time: bounded `\s*`, no nested quantifiers, no `(.+)+` shapes. Verified by inspection. |
| T-08-07 (Query log disclosure)   | accept   | Module performs no logging; no `loguru` import. |

No new threat surfaces introduced beyond those enumerated in `08-02-PLAN.md` `<threat_model>`.

## Follow-Ups for Downstream Plans

- **08-04** consumes `filters` dict directly via `vector_store.search(filters=…)` — `_build_filter_where` must use asyncpg `$N` parameterisation when interpolating `metadata->>'page_number'` and `metadata->>'section_id'` predicates.
- **08-05** integrates `extract_filters` into `QueryPipeline.execute(...)` upstream of `vector_store.search(...)`. Suggested call site: immediately after the pipeline receives the user query, before NLU sub-query decomposition (so each sub-query inherits the parent filter context).
- No future v1.1 plan should extend `_PAGE_RE` / `_CLAUSE_RE` / `_SECTION_RE`. English / mixed-language patterns are explicitly deferred to v1.2 per CONTEXT.md D-03.

## Self-Check: PASSED

Verified by direct filesystem + git probes:

- `[ -f services/nlu/filter_extractor.py ]` → FOUND
- `git log --oneline | grep b073cbc` → FOUND (`feat(08-02): implement Chinese query filter extractor (QUERY-01)`)
- pytest: 7/7 GREEN
- ruff: clean
- mypy --strict: clean
- Module imports: `__all__ == ['FilterExtractionResult', 'extract_filters']` confirmed
