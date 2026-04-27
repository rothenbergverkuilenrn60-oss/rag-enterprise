---
phase: 04-image-extraction
plan: "02"
subsystem: services/extractor
tags: [image-extraction, pymupdf, pillow, tdd, pdf, standalone-image]
dependency_graph:
  requires: [04-01-PLAN.md (ExtractedImage, ExtractedContent.images, DocType.IMAGE)]
  provides: [extract_images_from_pdf, ImageExtractorService.extract_standalone, ExtractorService image pipeline wiring]
  affects: [services/extractor/image_extractor.py, services/extractor/extractor.py]
tech_stack:
  added: [PyMuPDF (fitz) image extraction, Pillow thumbnail resize]
  patterns: [run_in_executor for sync image extraction, TDD red-green]
key_files:
  created: [services/extractor/image_extractor.py, tests/unit/test_image_extractor.py]
  modified: [services/extractor/extractor.py]
decisions:
  - extract_images_from_pdf placed in separate module (image_extractor.py) to keep extractor.py focused on text extraction orchestration
  - PIL.Image.MAX_IMAGE_PIXELS = 50_000_000 set at module level per T-04-02-02 (decompression bomb guard)
  - extractor_fn guard updated to allow DocType.IMAGE to pass through (extractor_fn=None is valid for image-only docs)
  - Copied previously untracked utils/logger, utils/cache, services/preprocessor into worktree for import resolution
metrics:
  duration: "~25 min"
  completed: "2026-04-27"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 10
---

# Phase 04 Plan 02: Image Extraction Service Summary

Stage 2 image extraction: sync `extract_images_from_pdf()` via PyMuPDF with D-01/D-02/D-05 filters, `ImageExtractorService.extract_standalone()` for jpg/png/webp, and full wiring into `ExtractorService.extract()` for both PDF and standalone image paths.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for image_extractor | b8f5de3 | tests/unit/test_image_extractor.py |
| 1 (GREEN) | Create services/extractor/image_extractor.py | b4e4331 | services/extractor/image_extractor.py, services/extractor/__init__.py, services/extractor/extractor.py |
| 2 | Wire image extraction into extractor.py | 65c5540 | services/extractor/extractor.py + utils/logger, utils/cache, services/preprocessor |

## What Was Built

### services/extractor/image_extractor.py (new)

- `extract_images_from_pdf(file_path, doc_id) -> list[ExtractedImage]`: sync, fitz-based, safe for `run_in_executor`
  - D-01: skip images where width < 100 px or height < 100 px (logged at DEBUG)
  - D-02: cap at 50 images per document; warns and breaks outer page loop at cap
  - D-05: thumbnail resize to 1024×1024 (LANCZOS) for images exceeding either dimension
  - T-04-02-02: `PIL.Image.MAX_IMAGE_PIXELS = 50_000_000` decompression bomb guard at module level
  - Narrow exception handling: `RuntimeError`, `fitz.FileDataError`, `KeyError`, `OSError` — no bare except (ERR-01)
- `_resize_image(raw_bytes) -> tuple[bytes, int, int]`: in-memory PNG resize helper
- `ImageExtractorService.extract_standalone(file_path) -> ExtractedImage`: jpg/jpeg/png/webp; auto-resize if > 1024px; raises `ValueError` for unsupported formats
- `get_image_extractor() -> ImageExtractorService`: factory function

### services/extractor/extractor.py (modified)

- Import: `from services.extractor.image_extractor import extract_images_from_pdf, get_image_extractor`
- `_EXTRACTOR_MAP`: added `DocType.IMAGE: None` entry
- `_detect_doc_type()`: added `.jpg`, `.jpeg`, `.png`, `.webp` → `DocType.IMAGE`
- `ExtractorService.extract()`:
  - Stage 2a: text extraction now guarded with `if doc_type != DocType.IMAGE and extractor_fn is not None`
  - Stage 2b: after content built, PDF path calls `extract_images_from_pdf` via `run_in_executor`, merges into `content.images`
  - Stage 2c: IMAGE path calls `get_image_extractor().extract_standalone()`, merges single image; `ValueError` appended to `extraction_errors`
  - Guard: `extractor_fn is None and doc_type != DocType.IMAGE` prevents false "unsupported format" return for image files

## Verification

- 17/17 new tests pass (test_image_extractor.py)
- 37/37 combined tests pass (test_image_extractor.py + test_image_models.py)
- `_detect_doc_type` inline assertion: jpg/png/webp/jpeg → DocType.IMAGE, pdf → DocType.PDF ✓
- No bare `except` in image_extractor.py (ERR-01 compliant) ✓
- All three decision constants present: `_MAX_IMAGES_PER_DOC=50`, `_MIN_DIMENSION_PX=100`, `_MAX_DIMENSION_PX=1024` ✓

## Deviations from Plan

### Auto-added (Rule 2 — missing critical functionality)

**1. [Rule 2 - Security] PIL decompression bomb guard**
- **Found during:** Task 1 implementation, threat model T-04-02-02
- **Issue:** Pillow will process arbitrarily large images without a pixel limit, enabling DoS via crafted image files
- **Fix:** `Image.MAX_IMAGE_PIXELS = 50_000_000` set at module level in image_extractor.py
- **Files modified:** services/extractor/image_extractor.py

### Infrastructure (Rule 3 — blocking issues)

**2. [Rule 3 - Blocking] Missing untracked files in worktree**
- **Found during:** Task 2 verification
- **Issue:** `utils/logger.py`, `utils/cache.py`, `utils/metrics.py`, `utils/observability.py`, `services/preprocessor/cleaner.py` existed only as untracked files in the main repo, not in git — unavailable in the worktree
- **Fix:** Copied files from main repo into worktree; added to Task 2 commit
- **Files added:** utils/__init__.py, utils/logger.py, utils/cache.py, utils/metrics.py, utils/observability.py, services/preprocessor/__init__.py, services/preprocessor/cleaner.py

## Known Stubs

None — all extraction paths are fully implemented. `content.images` is populated from real fitz/Pillow operations, not placeholders.

## Threat Flags

None beyond the plan's registered threats. T-04-02-02 mitigation applied (PIL.MAX_IMAGE_PIXELS). No new network endpoints, auth paths, or schema changes introduced.

## TDD Gate Compliance

- RED gate: commit `b8f5de3` — `test(04-02): add failing tests for image_extractor (RED phase)` ✓
- GREEN gate: commit `b4e4331` — `feat(04-02): create ImageExtractorService and extract_images_from_pdf` ✓

## Self-Check: PASSED

- `services/extractor/image_extractor.py` exists with all required symbols ✓
- `tests/unit/test_image_extractor.py` exists with 17 passing tests ✓
- Commit `b8f5de3` (RED) confirmed in git log ✓
- Commit `b4e4331` (GREEN) confirmed in git log ✓
- Commit `65c5540` (Task 2 wiring) confirmed in git log ✓
