# Phase 4: Image Extraction — Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

PDF-embedded images and standalone image files (jpg/png/webp) ingested as captioned, embedded chunks retrievable alongside text chunks — no changes to the query API contract.

</domain>

<decisions>
## Implementation Decisions

### Image filter threshold (IMG-01 / IMG-04)
- **D-01:** Minimum extraction threshold: **100 × 100 px**. Images with width < 100 OR height < 100 are skipped silently. Filters icons, bullet graphics, HR lines, and other decorative elements.
- **D-02:** Maximum images per document: **50**. Images beyond the first 50 (by page order) are skipped with a `logger.warning` that includes `doc_id` and total image count found. Prevents runaway LLM calls on image-heavy PDFs.

### Caption failure behavior (IMG-02 / IMG-04)
- **D-03:** When `chat_with_vision()` raises an exception — no chunk is created for that image. Log a `logger.warning` with `doc_id`, `page_number`, and `exc_info=exc`. Follow ERR-01 narrowing: catch `(openai.APIError, httpx.HTTPError, anthropic.APIError)` specifically, not bare `except Exception`.
- **D-04:** Caption failures surface as **partial success**: `IngestionResponse.success = True` but the skipped image is appended to `extraction_errors` as `"Image p{N} skipped: {reason}"`. Caller has a signal without the whole ingest failing.

### Base64 storage cap (IMG-02 / IMG-03 / IMG-04)
- **D-05:** Before base64 encoding, resize any image exceeding **1024 px on either dimension** using Pillow (`Image.thumbnail((1024, 1024), Image.LANCZOS)`). Keeps storage bounded at ~300KB/image in JSONB while preserving enough resolution for LLM captioning. Done in-memory; no temp files.

### Claude's Discretion
- Where `chunk_type="image"` lives in the model (top-level field on `Chunk` or inside `ChunkMetadata`) — Claude can decide.
- `DocType` extension for standalone images — single `DocType.IMAGE` catch-all or per-extension entries.
- Whether caption prompt is in English or Chinese (consistent with the existing `_VISION_OCR_SYSTEM` pattern in extractor.py is fine).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Roadmap
- `.planning/REQUIREMENTS.md` — IMG-01 through IMG-04 acceptance criteria (exact wording)
- `.planning/ROADMAP.md` — Phase 4 success criteria (4 items including empty-PDF guard in IMG-01)
- `.planning/PROJECT.md` — Production-grade constraints: Pydantic V2, no bare `except`, no blocking I/O in async

### Key Source Files
- `services/extractor/extractor.py` — Stage 2 extractor; `_extract_pdf_digital` filters `b[6] == 0` text blocks only; `_extract_pdf_vision_async` shows fitz + base64 + chat_with_vision pattern to follow
- `utils/models.py` — `ExtractedContent` (line 73) needs `images: list[ExtractedImage]` field; `ChunkMetadata` (line 109) needs `chunk_type` discriminator
- `services/pipeline.py` — `IngestionPipeline._run_ingest()` (line 98); Stage 2 → Stage 3/4 flow; `IngestionResponse` fields including `extraction_errors`
- `services/generator/llm_client.py` — `AnthropicLLMClient.chat_with_vision()` (line 492); signature: `image_b64: str, query: str, media_type: str = "image/png"`, returns `str`
- `services/vectorizer/vector_store.py` — `upsert()` stores `metadata JSONB`; base64 bytes go in the metadata dict

### Prior Phase Patterns
- `.planning/phases/03-error-handling-sweep/03-CONTEXT.md` — ERR-01 exception narrowing pattern; D-03 above requires following this for caption call sites

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AnthropicLLMClient.chat_with_vision(image_b64, query, media_type)` (llm_client.py:492) — call this for caption generation; already handles base64 PNG input
- `fitz` (PyMuPDF) — already imported in extractor.py; `page.get_images(full=True)` gives `(xref, smask, w, h, bpc, cs, alt_cs, name, filter, referencer)` tuples for image blocks; `doc.extract_image(xref)` returns `{"ext": "png", "image": bytes, "width": int, "height": int}`
- `run_in_executor` pattern — already used in `ExtractorService.extract()` for blocking fitz work; image extraction from PDF should follow the same pattern
- `Pillow` (PIL) — already available (used in tesseract path); `Image.thumbnail()` for resize

### Established Patterns
- `extraction_errors: list[str]` on `ExtractedContent` — already exists; append skip-messages there
- `images_count: int = 0` on `ExtractedContent` — update to reflect actual extracted count (not just counted)
- `logger.warning` + continue for recoverable per-item failures (D-04 startup warmup pattern from Phase 3 context)

### Integration Points
- `ExtractedContent` flows from Stage 2 → `doc_processor/chunker` (Stage 3/4) — adding `images: list[ExtractedImage]` is the handoff contract
- `ChunkMetadata.model_dump(mode="json")` is called before JSONB insertion (vector_store.py:167) — base64 field must be JSON-serialisable (str, not bytes)
- `IngestionResponse` is returned to API caller — `extraction_errors` already in the response schema

</code_context>

<specifics>
## Specific Requirements

- Empty-PDF guard (per IMG-01 success criteria 4): when a PDF has no embedded images, `ExtractedContent.images` must be `[]` and the pipeline must not error.
- Standalone image files (IMG-04) are a single-chunk ingest: one image → one `chat_with_vision` call → one chunk with `chunk_type="image"`. No Stage 2 text extraction needed.
- Caption must be embedded via the **existing BGE-M3 embedder** — no separate embedding model for images. The caption string is the embedding input.
- Base64 bytes in metadata must travel through the query response to the caller — `retrieved image chunks include caption text and base64 raw bytes` (IMG-03).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-image-extraction*
*Context gathered: 2026-04-24*
