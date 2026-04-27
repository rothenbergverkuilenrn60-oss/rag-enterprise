---
phase: 04-image-extraction
verified: 2026-04-27T00:00:00Z
status: gaps_found
score: 6/7 must-haves verified
re_verification: false
gaps:
  - truth: "Hybrid query response includes chunk_type='image' chunks with caption text and base64 bytes in metadata"
    status: failed
    reason: "_to_retrieved_chunk() in services/retriever/retriever.py reconstructs ChunkMetadata with only 8 named fields — chunk_type and image_b64 are NOT mapped from r.metadata. Both default to 'text' and '' respectively, so every retrieved image chunk loses its chunk_type discriminator and base64 bytes."
    artifacts:
      - path: "services/retriever/retriever.py"
        issue: "_to_retrieved_chunk() (line 379-397) builds ChunkMetadata without chunk_type=r.metadata.get('chunk_type','text') and image_b64=r.metadata.get('image_b64','') — two fields that ARE stored in the JSONB metadata column but are never read back on retrieval"
    missing:
      - "Add chunk_type=r.metadata.get('chunk_type', 'text') to ChunkMetadata construction in _to_retrieved_chunk()"
      - "Add image_b64=r.metadata.get('image_b64', '') to ChunkMetadata construction in _to_retrieved_chunk()"
---

# Phase 4: Image Extraction Verification Report

**Phase Goal:** PDF-embedded images and standalone image files are ingested as captioned, embedded chunks that are retrievable alongside text chunks with no changes to the query API.
**Verified:** 2026-04-27T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ExtractedContent carries a typed list of ExtractedImage objects out of Stage 2 | VERIFIED | `utils/models.py` line 95: `images: list[ExtractedImage] = Field(default_factory=list)`; `model_post_init` sets `images_count` at line 101-103 |
| 2 | ChunkMetadata has a chunk_type discriminator field distinguishing text from image chunks | VERIFIED | `utils/models.py` line 144: `chunk_type: str = "text"` |
| 3 | DocType.IMAGE exists for standalone image file ingestion | VERIFIED | `utils/models.py` line 29: `IMAGE = "image"` |
| 4 | IngestionResponse carries extraction_errors so callers see skipped images | VERIFIED | `utils/models.py` line 256: `extraction_errors: list[str] = Field(default_factory=list)`; pipeline.py line 236: `extraction_errors=extracted.extraction_errors` |
| 5 | Extracting a PDF with embedded images populates ExtractedContent.images; image_extractor.py enforces size/count constraints | VERIFIED | `services/extractor/image_extractor.py` exists; `_MAX_IMAGES_PER_DOC=50`, `_MIN_DIMENSION_PX=100`, `_MAX_DIMENSION_PX=1024`; `extract_images_from_pdf` wired into `extractor.py` via `run_in_executor` (line 644) |
| 6 | Chunker produces DocumentChunk objects with chunk_type='image', caption in content, and base64 bytes in metadata.image_b64; caption failures append to extraction_errors | VERIFIED | `services/doc_processor/chunker.py` line 1142: `_chunk_images()` async method; line 1175: catches `(openai.APIError, httpx.HTTPError, anthropic.APIError)`; line 1181: appends to `content.extraction_errors`; line 1200: `chunk_type="image"`, line 1201: `image_b64=image_b64` |
| 7 | Hybrid query response includes chunk_type='image' chunks with caption text and base64 bytes in metadata | FAILED | `_to_retrieved_chunk()` in `services/retriever/retriever.py` (line 379-390) builds `ChunkMetadata` with only 8 fields — `chunk_type` and `image_b64` are absent; both revert to defaults `"text"` and `""` on every retrieved chunk |

**Score:** 6/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `utils/models.py` | ExtractedImage, images on ExtractedContent, chunk_type + image_b64 on ChunkMetadata, DocType.IMAGE | VERIFIED | All fields confirmed at correct lines |
| `services/extractor/image_extractor.py` | extract_images_from_pdf(), ImageExtractorService.extract_standalone() | VERIFIED | File exists; both functions present; constants correct; ExtractedImage imported from utils.models |
| `services/extractor/extractor.py` | Calls extract_images_from_pdf, DocType.IMAGE routing in _detect_doc_type | VERIFIED | Import at line 26; _detect_doc_type handles .jpg/.jpeg/.png/.webp at line 563; PDF path calls extractor at line 644; IMAGE path calls extract_standalone at line 651 |
| `services/doc_processor/chunker.py` | _chunk_images() method, _IMAGE_CAPTION_SYSTEM, base64 import, narrow exception catches | VERIFIED | All additions confirmed at lines 16, 588, 1142, 1175 |
| `services/pipeline.py` | _infer_doc_type handles image extensions; early-return guard includes `not extracted.images`; quality gate wrapped in `if extracted.body_text`; IngestionResponse carries extraction_errors | VERIFIED | Lines 69-70, 116, 163, 236 all confirmed |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| utils/models.py ExtractedImage | services/extractor/image_extractor.py | import | WIRED | Line 16: `from utils.models import ExtractedImage` |
| services/extractor/extractor.py | services/extractor/image_extractor.py extract_images_from_pdf() | run_in_executor call | WIRED | Line 26 import; line 644 call |
| services/doc_processor/chunker.py _chunk_images() | services/generator/llm_client.py chat_with_vision() | await call | WIRED | Line 1169: `await llm_client.chat_with_vision(...)` |
| services/doc_processor/chunker.py DocumentChunk | services/vectorizer/vector_store.py upsert() | metadata.model_dump(mode='json') | WIRED | vector_store.py line 167 serializes full metadata including chunk_type and image_b64 |
| services/pipeline.py _run_ingest() | utils/models.py IngestionResponse.extraction_errors | IngestionResponse(extraction_errors=...) | WIRED | pipeline.py line 236 confirmed |
| services/retriever/retriever.py _to_retrieved_chunk() | utils/models.py ChunkMetadata.chunk_type + image_b64 | r.metadata.get() | NOT WIRED | chunk_type and image_b64 are stored in JSONB but NOT read back in _to_retrieved_chunk — critical gap for IMG-03 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `_chunk_images()` in chunker.py | `caption` | `llm_client.chat_with_vision()` | Yes — live LLM call | FLOWING |
| `_to_retrieved_chunk()` in retriever.py | `chunk_type`, `image_b64` | `r.metadata` JSONB | No — fields stored but not read back | DISCONNECTED |

### Behavioral Spot-Checks

Step 7b: SKIPPED — no runnable Python environment available in this context (pydantic not installed in system Python; torch_env conda env not accessible). Static code analysis used throughout.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| IMG-01 | 04-01, 04-02 | Ingestion pipeline extracts images from PDFs; ExtractedContent includes images list | SATISFIED | ExtractedImage model, images field, extractor wiring all verified |
| IMG-02 | 04-01, 04-03 | Image chunks with chunk_type="image"; LLM caption via BGE-M3 embedding path | SATISFIED | _chunk_images() produces chunks with chunk_type="image"; caption is embedding input |
| IMG-03 | 04-03 | Image chunks retrievable alongside text; response includes caption and base64 bytes | BLOCKED | _to_retrieved_chunk() does not map chunk_type or image_b64 from stored metadata — image chunks retrieved as chunk_type="text" with empty image_b64 |
| IMG-04 | 04-01, 04-02, 04-03 | Standalone jpg/png/webp ingested as single image chunk with caption | SATISFIED | DocType.IMAGE routing in _detect_doc_type and _infer_doc_type; extract_standalone(); _chunk_images() path confirmed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| services/doc_processor/chunker.py | 41 | `except Exception:` | Info | Pre-existing — tiktoken fallback to heuristic token count; acceptable pattern |
| services/doc_processor/chunker.py | 132 | `except Exception as exc:` | Info | Pre-existing — semantic split fallback; acceptable |
| services/doc_processor/chunker.py | 538 | `except Exception as exc:` | Info | Pre-existing — proposition retry; acceptable |
| services/doc_processor/chunker.py | 624 | `except Exception as exc:` | Info | Pre-existing — contextual header fallback; acceptable |

No new bare excepts introduced by phase 4 changes.

### Human Verification Required

#### 1. End-to-End Image Ingestion and Retrieval

**Test:** Upload a PDF with embedded images (minimum 100x100px) to the ingest endpoint. Then query with a term that matches expected image content.
**Expected:** Query response contains chunks with `chunk_type="image"`, non-empty `metadata.image_b64`, and LLM-generated caption text. After the gap fix in retriever.py is applied, this should work.
**Why human:** Cannot run the full stack (requires PostgreSQL + pgvector + LLM API keys) in static verification.

#### 2. Caption failure graceful degradation (D-04)

**Test:** Ingest a PDF with images while the LLM API is unreachable (block or use invalid key).
**Expected:** `IngestionResponse.success=True`, `extraction_errors` contains `"Image p{N} skipped: APIError"` entries, text chunks still stored.
**Why human:** Requires controlled network/API failure injection.

### Gaps Summary

One gap blocks the phase goal. The entire retrieval half of IMG-03 (roadmap success criterion #2) is broken because `_to_retrieved_chunk()` in `services/retriever/retriever.py` explicitly names only 8 fields when reconstructing `ChunkMetadata` from JSONB. The two new fields — `chunk_type` and `image_b64` — are serialized correctly into the database by the vector store, but are never read back. Every retrieved image chunk will appear to callers as `chunk_type="text"` with `image_b64=""`.

The fix is a two-line addition to `_to_retrieved_chunk()`:

```python
chunk_type=r.metadata.get("chunk_type", "text"),
image_b64=r.metadata.get("image_b64", ""),
```

All other phase 4 deliverables — data models, PDF image extraction, standalone image extraction, LLM captioning, failure handling, and pipeline wiring — are fully implemented and wired correctly.

---

_Verified: 2026-04-27T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
