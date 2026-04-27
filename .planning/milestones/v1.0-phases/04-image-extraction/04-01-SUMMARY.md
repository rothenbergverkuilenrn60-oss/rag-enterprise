---
phase: 04-image-extraction
plan: "01"
subsystem: utils/models
tags: [pydantic, models, image-extraction, data-contracts]
dependency_graph:
  requires: []
  provides: [ExtractedImage, ExtractedContent.images, ChunkMetadata.chunk_type, ChunkMetadata.image_b64, IngestionResponse.extraction_errors, DocType.IMAGE]
  affects: [services/extractor/image_extractor.py, services/doc_processor/chunker.py, services/pipeline.py]
tech_stack:
  added: []
  patterns: [pydantic-v2-model-post-init, tdd-red-green]
key_files:
  created: [tests/unit/test_image_models.py]
  modified: [utils/models.py]
decisions:
  - ExtractedImage placed immediately before ExtractedContent to eliminate forward references
  - model_post_init only sets images_count when images list is non-empty AND images_count is still 0 (preserves explicit overrides)
  - list[dict] on ExtractedContent.tables pre-existing mypy error; not introduced by this plan
metrics:
  duration: "~10 min"
  completed: "2026-04-27"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 2
---

# Phase 04 Plan 01: Image Extraction Model Contracts Summary

Pydantic V2 data model extensions establishing typed handoff contracts for image extraction across all pipeline stages: ExtractedImage, images field on ExtractedContent, chunk_type/image_b64 on ChunkMetadata, extraction_errors on IngestionResponse, and DocType.IMAGE.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for image models | b2da44c | tests/unit/test_image_models.py |
| 1 (GREEN) | Implement image model additions | 15612c6 | utils/models.py |

## What Was Built

- `DocType.IMAGE = "image"` — new enum member for standalone image file ingestion
- `ExtractedImage` — Pydantic V2 BaseModel with `raw_bytes: bytes`, `width`, `height`, `page_number`, `image_index`, `ext` (default `"png"`)
- `ExtractedContent.images: list[ExtractedImage]` — carries typed image list out of Stage 2; `model_post_init` auto-sets `images_count = len(self.images)` when `images_count == 0`
- `ChunkMetadata.chunk_type: str = "text"` — discriminator distinguishing text from image chunks
- `ChunkMetadata.image_b64: str = ""` — base64-encoded image bytes (non-empty only for image chunks)
- `IngestionResponse.extraction_errors: list[str]` — surfaces skipped image errors to callers

## Verification

- 20/20 pytest tests pass (all GREEN)
- Plan inline assertion test prints `ALL CHECKS PASSED`
- mypy --strict emits only 1 pre-existing error (`list[dict]` on `tables` field, line 93 — not introduced by this plan)

## Deviations from Plan

None — plan executed exactly as written. The single mypy error is pre-existing on the `tables: list[dict]` field (original file), not introduced by any new field in this plan.

## Known Stubs

None — all new fields are fully wired with correct types and defaults.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond what the plan's threat model already registers (T-04-01-01 through T-04-01-03).

## Self-Check: PASSED

- `utils/models.py` exists and contains all required classes
- `tests/unit/test_image_models.py` exists with 20 passing tests
- Commit `b2da44c` (RED test) confirmed in git log
- Commit `15612c6` (GREEN implementation) confirmed in git log
