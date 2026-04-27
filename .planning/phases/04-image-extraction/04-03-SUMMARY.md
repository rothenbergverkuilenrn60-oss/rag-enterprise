---
phase: 04-image-extraction
plan: "03"
subsystem: services/doc_processor, services/pipeline
tags: [image-chunking, llm-captioning, pipeline-wiring, doctype-routing, extraction-errors]
dependency_graph:
  requires:
    - 04-01-PLAN.md (ExtractedImage, ChunkMetadata.chunk_type/image_b64, IngestionResponse.extraction_errors, DocType.IMAGE)
    - 04-02-PLAN.md (ImageExtractorService, extract_images_from_pdf, ExtractorService wiring)
  provides:
    - DocProcessorService._chunk_images() — LLM captioning loop producing DocumentChunk(chunk_type="image")
    - pipeline._infer_doc_type image extension routing (.jpg/.jpeg/.png/.webp -> DocType.IMAGE)
    - IngestionResponse.extraction_errors forwarded from extracted.extraction_errors
    - Image-only doc support: bypass text chunking, quality gate skipped
  affects:
    - services/vectorizer/indexer.py (receives image chunks via existing vectorize_and_store path)
    - controllers/ (IngestionResponse now carries extraction_errors)
tech_stack:
  added: []
  patterns:
    - base64-encode-then-llm-vision-caption
    - narrow-exception-catch (openai.APIError, httpx.HTTPError, anthropic.APIError)
    - image-only-doc-bypass (body_text empty + images present)
    - quality-gate-guard (wrapped in if extracted.body_text)
key_files:
  created: []
  modified:
    - services/doc_processor/chunker.py
    - services/pipeline.py
decisions:
  - "_chunk_images() placed as async method on DocProcessorService; called at end of process() after all text chunks are produced"
  - "Image-only documents bypass text chunking entirely via early path in process()"
  - "Quality gate wrapped in 'if extracted.body_text:' — image-only docs have no text to validate (T-04-03-04)"
  - "Error strings use type(exc).__name__ — no stack traces or paths exposed (T-04-03-03)"
  - "Empty caption treated as failure: appended to extraction_errors, chunk skipped (correctness requirement)"
metrics:
  duration: "~20 min"
  completed: "2026-04-27"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 2
---

# Phase 04 Plan 03: Image Chunking and Pipeline Wiring Summary

LLM-based image captioning loop in DocProcessorService and full pipeline wiring: `_chunk_images()` produces `DocumentChunk(chunk_type="image")` from `ExtractedImage` objects via `chat_with_vision`; `pipeline.py` routes `.jpg/.jpeg/.png/.webp` to `DocType.IMAGE`, allows image-only docs to bypass the quality gate, and forwards `extraction_errors` to `IngestionResponse`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add _chunk_images() to DocProcessorService | 8d93ba4 | services/doc_processor/chunker.py |
| 2 | Wire IngestionResponse.extraction_errors and DocType.IMAGE routing | 076805b | services/pipeline.py |

## What Was Built

### services/doc_processor/chunker.py (modified)

- Added imports: `base64`, `openai`, `httpx`, `anthropic`
- Added `_IMAGE_CAPTION_SYSTEM` module-level constant (Chinese vision caption prompt)
- Added `DocProcessorService._chunk_images(images, content, doc_id, llm_client, start_index)` async method:
  - base64-encodes each `ExtractedImage.raw_bytes`
  - Calls `llm_client.chat_with_vision(image_b64, query, media_type, system)` for each image
  - D-03: catches exactly `(openai.APIError, httpx.HTTPError, anthropic.APIError)` — no bare except
  - D-04: on failure OR empty caption, appends `f"Image p{N} skipped: {ExcTypeName}"` to `content.extraction_errors`; continues without chunk
  - On success: builds `DocumentChunk` with `chunk_type="image"`, `image_b64=image_b64`, `content=caption`
  - Logs summary: total produced, total skipped
- Modified `process()`:
  - Early-return guard changed: `not content.body_text.strip() and not content.images` (was `not body_text`)
  - Image-only path: if no `body_text` but `images` present, calls `_chunk_images()` directly and returns
  - End of mixed-content path: calls `_chunk_images()` with `start_index=len(all_chunks)` and extends result

### services/pipeline.py (modified)

- `_infer_doc_type()`: added `.jpg`, `.jpeg`, `.png`, `.webp` → `DocType.IMAGE`
- `_run_ingest()` early-return guard: `not extracted.images` condition added (image-only docs proceed)
- `_run_ingest()` quality gate: wrapped in `if extracted.body_text:` block (image-only docs skip validation)
- `_run_ingest()` success `IngestionResponse`: added `extraction_errors=extracted.extraction_errors`

## Verification

- `grep -c "_chunk_images" chunker.py` → 3 (definition + image-only call + mixed-content call)
- `grep -c "_IMAGE_CAPTION_SYSTEM" chunker.py` → 2
- All three exception types present: `openai.APIError`, `httpx.HTTPError`, `anthropic.APIError`
- `grep -n "DocType.IMAGE" pipeline.py` → 2 lines (_infer_doc_type + early-return guard)
- `grep -n "extracted.images" pipeline.py` → line 116 (early-return guard update)
- `grep -n "if extracted.body_text" pipeline.py` → line 163 (quality gate guard)
- `grep -n "extraction_errors=extracted.extraction_errors" pipeline.py` → line 236
- Background uv run verification: `chunker OK` (exit code 0)

## Deviations from Plan

### Auto-added (Rule 3 — blocking issue)

**1. [Rule 3 - Blocking] services/doc_processor/ directory missing from worktree**
- **Found during:** Task 1 start
- **Issue:** `services/doc_processor/` existed only as an untracked directory in the main repo, not tracked in git — unavailable in the worktree
- **Fix:** Copied `services/doc_processor/__init__.py` and `chunker.py` from main repo into worktree
- **Files added:** services/doc_processor/__init__.py, services/doc_processor/chunker.py (committed in Task 1 commit)

### Auto-added (Rule 2 — missing critical functionality)

**2. [Rule 2 - Correctness] Empty caption treated as failure**
- **Found during:** Task 1 implementation
- **Issue:** Plan specified catching LLM API errors, but an empty string response (LLM returned nothing) would produce a chunk with no content — silent data corruption
- **Fix:** Added explicit `if not caption.strip():` guard — appends to `extraction_errors`, skips chunk; same user-visible behavior as an API error

## Known Stubs

None — all image chunking paths are fully wired. `_chunk_images()` calls the real `chat_with_vision()` method; `DocumentChunk.image_b64` carries the actual base64 bytes; `IngestionResponse.extraction_errors` is populated from real runtime data.

## Threat Flags

None beyond the plan's registered threats. T-04-03-03 (error string exposure) and T-04-03-04 (quality gate bypass) mitigations both applied as implemented.

## Self-Check: PASSED

- `services/doc_processor/chunker.py` exists with all required symbols: _chunk_images, _IMAGE_CAPTION_SYSTEM, base64 import, openai/httpx/anthropic imports
- `services/pipeline.py` modified: DocType.IMAGE in _infer_doc_type, extracted.images guard, if extracted.body_text quality gate, extraction_errors in IngestionResponse
- Commit `8d93ba4` (Task 1) confirmed in git log
- Commit `076805b` (Task 2) confirmed in git log
