---
phase: 22-per-module-70-coverage-lift
plan: "05"
subsystem: services/extractor
tags: [coverage, extractor, ocr, pymupdf, tesseract, sc5, test-12]
dependency_graph:
  requires: [22-00]
  provides: [TEST-12, SC5-extractor-coverage]
  affects: [services/extractor/extractor.py]
tech_stack:
  added: []
  patterns: [sys.modules-injection, monkeypatch-consumer-path, parametrize-table]
key_files:
  created:
    - tests/unit/test_extractor_coverage.py
  modified: []
decisions:
  - "Mocked fitz via sys.modules injection (not module-level setattr) because extractor.py imports fitz inside function bodies, not at module top-level"
  - "Used TrackedDocument subclass with __getitem__ override to count page accesses for cap-branch verification"
  - "Added _extract_pdf_digital multi-column + pdfplumber table branches to close 69.9% → 73.5% gap"
metrics:
  duration_minutes: 5
  completed_date: "2026-05-10"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  tests_added: 30
---

# Phase 22 Plan 05: Per-Module Coverage Lift — services/extractor/extractor.py Summary

One-liner: SC5 coverage via sys.modules-injected fitz/pytesseract fakes; 30 tests lift extractor.py from 37.3% to 73.5%.

## Coverage Result

| Module | Before | After | Gap Closed |
|--------|--------|-------|-----------|
| `services/extractor/extractor.py` | 37.3% (baseline) | **73.5%** | 36.2pp |

Gate `--fail-under=70` exits 0.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SC5 coverage tests (all 4 branch families) | 7329121 | tests/unit/test_extractor_coverage.py |
| 2 | Per-module gate verification (73.5% ≥ 70%) | — (no code change) | — |

## SC5 Branch Families Covered

All 4 ROADMAP SC5 branch families are covered:

1. **is_scanned_pdf 3-page heuristic** — text-rich (density > 0.01), empty pages, below-threshold, zero-area (L50), open failure (except branch), sample_pages boundary, parametrize table
2. **_detect_header_footer_texts 10-page-cap** — 50-page doc capped at 10 reads, 5-page doc reads all 5, repeated lines noise detection, fitz.open failure returns empty set
3. **OCR-vs-native-extract router (_extract_pdf_enterprise)** — digital path, tesseract explicit, paddleocr/auto, none (skipped), unknown engine degradation
4. **Tesseract OCR engine selection (v1.4.2 fix, _extract_pdf_scanned_tesseract)** — image_to_string called + result in body_text, ImportError fallback dict, result structure, whitespace-only page exclusion parametrize

## Deviations from Plan

### Auto-adjusted Implementation

**1. [Rule 1 - Implementation] fitz mocked via sys.modules, not monkeypatch.setattr on module attribute**

- **Found during:** Task 1 analysis
- **Issue:** `services/extractor/extractor.py` imports `fitz` inside function bodies (`import fitz` at L38, L71, L121, L233, L307). There is no module-level `fitz` binding, so `monkeypatch.setattr("services.extractor.extractor.fitz", ...)` would fail with AttributeError.
- **Fix:** Used `monkeypatch.setitem(sys.modules, "fitz", fake_fitz_module)` — the canonical Python mechanism to replace a module before a local `import` resolves. This is still CF-02 compliant: we are replacing the module as seen by the extractor consumer, not touching pytesseract or fitz source.
- **Files modified:** tests/unit/test_extractor_coverage.py only
- **Commit:** 7329121

**2. [Rule 2 - Coverage gap] Added _extract_pdf_digital branches to close 69.9% → 73.5% gap**

- **Found during:** Task 2 verification
- **Issue:** After Task 1, coverage was 69.9% — just 0.1% below the 70% gate.
- **Fix:** Added 3 more tests for `_extract_pdf_digital`: happy-path, multi-column branch (L149-150), pdfplumber table extraction (L165-176). Also added `test_zero_area_returns_true` for L50 (total_area==0).
- **Files modified:** tests/unit/test_extractor_coverage.py only
- **Commit:** 7329121 (same commit)

## Constraint Compliance

| Constraint | Status | Evidence |
|-----------|--------|---------|
| CF-01: No production-code changes | PASS | `git diff --name-only services/` returns nothing |
| CF-02: Mock at consumer path only | PASS | `grep -cE 'monkeypatch\.setattr\("(pytesseract|fitz|pymupdf)\.'` returns 0 |
| D-09: test_extractor_ocr_routing.py unchanged | PASS | `git diff tests/unit/test_extractor_ocr_routing.py` returns empty |
| D-12: Module docstring at top | PASS | File begins with `"""Coverage tests for services/extractor/extractor.py per TEST-12` |
| D-16: No new binary PDF fixtures | PASS | `git status tests/unit/fixtures/` shows no .pdf/.png/.jpg files |
| CF-06: diff-cover ≥80% | PASS | New file is 100% new code; diff-cover trivially passes |

## Test Statistics

- **File:** `tests/unit/test_extractor_coverage.py`
- **Tests:** 30 (including 5 parametrized variants)
- **Runtime:** 0.13s
- **Test classes:** TestIsScannedPdf (9), TestDetectHeaderFooterTexts (4), TestExtractPdfEnterpriseRouter (5), TestExtractPdfScannedTesseract (5), TestExtractPdfDigital (3), TestExtractorServiceEdgePaths (4)

## Known Stubs

None — all tests exercise real code paths via mocked I/O.

## Threat Flags

None — test-only change; no new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- `tests/unit/test_extractor_coverage.py` exists: FOUND
- `coverage report --include=services/extractor/extractor.py --fail-under=70` exits 0: PASSED (73.5%)
- Task 1 commit 7329121 exists: FOUND
- `git diff --name-only services/` returns no .py files: PASSED
- `git diff tests/unit/test_extractor_ocr_routing.py` is empty: PASSED
