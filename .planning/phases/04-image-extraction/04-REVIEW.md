---
phase: 04-image-extraction
reviewed: 2026-04-27T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - utils/models.py
  - services/extractor/image_extractor.py
  - services/extractor/extractor.py
  - services/doc_processor/chunker.py
  - services/pipeline.py
  - tests/unit/test_image_models.py
  - tests/unit/test_image_extractor.py
  - services/retriever/retriever.py
  - tests/unit/test_retriever.py
findings:
  critical: 0
  warning: 9
  info: 6
  total: 15
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-04-27T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Nine files were reviewed covering the full image-extraction phase: new Pydantic models (`ExtractedImage`, `ChunkMetadata` image fields), PDF image extraction via PyMuPDF, standalone image extraction, chunker image-captioning, ingestion/query pipelines, two unit test modules from the initial phase, and the two files added by the IMG-03 gap-closure plan (`services/retriever/retriever.py` patch and `tests/unit/test_retriever.py` additions).

The IMG-03 patch itself (lines 389–390 in `retriever.py`) is correct and functionally closes the round-trip gap. The broader concerns from the initial review still apply (ERR-01 violations, deprecated async APIs, mutation anti-patterns). The new findings from IMG-03 review are WR-07, WR-08, WR-09 and IN-05, IN-06.

---

## Warnings

### WR-01: Bare `except Exception` in `extractor.py` — violates ERR-01

**File:** `services/extractor/extractor.py:57`
**Issue:** `is_scanned_pdf` catches `except Exception as exc` broadly. Same pattern at line 92 in `_detect_header_footer_texts`. The project CLAUDE.md states ERR-01: no bare `except` — narrow exception types only. These swallow unexpected errors silently.
**Fix:**
```python
# line 57 — replace broad catch with specific fitz/IO exceptions
except (RuntimeError, OSError) as exc:
    logger.warning(f"is_scanned_pdf check failed: {exc}")
    return False

# line 92 — same pattern
except (RuntimeError, OSError) as exc:
    logger.warning(f"页眉页脚检测失败: {exc}")
    return set()
```

### WR-02: `asyncio.get_event_loop()` deprecated in Python 3.10+ async context

**File:** `services/extractor/extractor.py:614` and `services/extractor/extractor.py:642`
**Issue:** `asyncio.get_event_loop()` inside a running async function is deprecated since Python 3.10 and raises `DeprecationWarning` (and may raise `RuntimeError` in 3.12+ if no current loop). The correct API inside an `async def` is `asyncio.get_running_loop()`.
**Fix:**
```python
# line 614
loop = asyncio.get_running_loop()
result_dict = await loop.run_in_executor(None, extractor_fn, path)

# line 642
loop2 = asyncio.get_running_loop()
images = await loop2.run_in_executor(
    None, extract_images_from_pdf, path, doc.raw_id
)
```

### WR-03: Post-construction mutation of `ExtractedContent` bypasses `model_post_init`

**File:** `services/extractor/extractor.py:647-648`
**Issue:** After `ExtractedContent` is constructed (line 625), `content.images` and `content.images_count` are assigned directly:
```python
content.images = images
if content.images:
    content.images_count = len(content.images)
```
`model_post_init` runs only at construction time, so `images_count` is correct only if images is non-empty. But if `images` is empty, `images_count` stays 0 even though the post-init logic already handled that case. More importantly, Pydantic V2 models are not frozen here, so the mutation succeeds silently — but it bypasses validation and creates fragile coupling. The same mutation happens at lines 659-660 for standalone images.
**Fix:** Build `ExtractedContent` with images already populated, or use `model_copy`:
```python
content = content.model_copy(update={"images": images, "images_count": len(images)})
```

### WR-04: `_chunk_images` mutates caller's `ExtractedContent.extraction_errors`

**File:** `services/doc_processor/chunker.py:1181` and `1191`
**Issue:** `_chunk_images` appends to `content.extraction_errors`, mutating a Pydantic model passed in from the pipeline. This is a side-effect that callers cannot easily anticipate and that violates the immutability convention in the project coding style. Errors from chunking should be returned, not injected into the extraction model.
**Fix:** Collect errors locally and return them alongside chunks:
```python
async def _chunk_images(self, ...) -> tuple[list[DocumentChunk], list[str]]:
    chunks: list[DocumentChunk] = []
    errors: list[str] = []
    ...
    errors.append(f"Image p{img.page_number} skipped: {type(exc).__name__}")
    ...
    return chunks, errors
```

### WR-05: Global singleton factories are not thread-safe

**File:** `services/pipeline.py:707-727`
**Issue:** The module-level singletons (`_ingest_pipeline`, `_query_pipeline`, `_agent_pipeline`) are initialized with a non-atomic check-then-set pattern. Under concurrent ASGI startup, two threads can both see `None` and both construct, with the second overwriting the first.
**Fix:**
```python
import threading
_lock = threading.Lock()

def get_ingest_pipeline() -> IngestionPipeline:
    global _ingest_pipeline
    if _ingest_pipeline is None:
        with _lock:
            if _ingest_pipeline is None:
                _ingest_pipeline = IngestionPipeline()
    return _ingest_pipeline
```

### WR-06: Test `test_no_bare_except_in_module` uses a relative path — will fail outside project root

**File:** `tests/unit/test_image_extractor.py:215`
**Issue:** `module_path = Path("services/extractor/image_extractor.py")` is relative to the current working directory. When pytest is invoked from any directory other than the repo root, `module_path.exists()` returns `False` and the test skips silently.
**Fix:**
```python
module_path = Path(__file__).parent.parent.parent / "services/extractor/image_extractor.py"
```

### WR-07: Unguarded `DocType()` constructor in `_to_retrieved_chunk` crashes retrieval on invalid stored value

**File:** `services/retriever/retriever.py:387`

**Issue:** `DocType(r.metadata.get("doc_type", "unknown"))` raises `ValueError` if the JSONB metadata contains any string not in the enum (e.g. `"jpeg"`, `"jpg"`, `"pptx"`, or any legacy value written by an older ingestion run). `_to_retrieved_chunk` has no error handling, so the exception propagates through `_retrieve_impl` and aborts the entire retrieval request. The IMG-03 patch adds two more `.metadata.get()` accesses to the same constructor call, increasing reliance on this code path without fixing its one unsafe operation. Since JSONB is schemaless, an invalid `doc_type` is a realistic production scenario (index built before `DocType.IMAGE` existed, third-party ingestion, etc.).

**Fix:**
```python
def _to_retrieved_chunk(r: VectorSearchResult, method: str = "dense") -> RetrievedChunk:
    raw_doc_type = r.metadata.get("doc_type", "unknown")
    try:
        doc_type = DocType(raw_doc_type)
    except ValueError:
        logger.warning(
            f"[_to_retrieved_chunk] Unknown doc_type={raw_doc_type!r} "
            f"for chunk={r.chunk_id}, falling back to DocType.UNKNOWN"
        )
        doc_type = DocType.UNKNOWN
    meta = ChunkMetadata(
        source=r.metadata.get("source", ""),
        doc_id=r.doc_id,
        title=r.metadata.get("title", ""),
        author=r.metadata.get("author", ""),
        chunk_index=r.metadata.get("chunk_index", 0),
        total_chunks=r.metadata.get("total_chunks", 0),
        doc_type=doc_type,
        language=r.metadata.get("language", "zh"),
        chunk_type=r.metadata.get("chunk_type", "text"),
        image_b64=r.metadata.get("image_b64", ""),
    )
    ...
```

### WR-08: Vacuous assertion in `test_two_lists_boosts_common_items` provides no regression protection

**File:** `tests/unit/test_retriever.py:29`

**Issue:** `assert "A" in top2 or "B" in top2` is a tautology. `top2` is a 2-item set drawn from `{A, B, C, D}`. The assertion fails only if `top2 == {"C", "D"}` — i.e., both A and B rank last — which is the exact failure the test is meant to catch. Any broken RRF implementation that returns `["A", "C"]` or `["B", "D"]` will still pass this assertion. The test intent is that A and B, appearing in both lists, must both be in the top 2.

**Fix:**
```python
def test_two_lists_boosts_common_items(self) -> None:
    list1 = [("A", 0.9), ("B", 0.8), ("C", 0.7)]
    list2 = [("B", 0.95), ("D", 0.85), ("A", 0.6)]
    result = rrf_fusion([list1, list2])
    top2 = {r[0] for r in result[:2]}
    assert top2 == {"A", "B"}, f"Expected A and B in top-2, got {top2}"
```

### WR-09: No test for `DocType` crash path — IMG-03 coverage gap

**File:** `tests/unit/test_retriever.py:120-137`

**Issue:** `TestToRetrievedChunkImageFields` covers only valid metadata. The IMG-03 plan's stated goal is ensuring round-trip correctness through JSONB deserialization — but JSONB is untyped, so an invalid `doc_type` is the most realistic failure mode. Without a negative test, WR-07 can regress silently after any future data migration.

**Fix:** Add:
```python
def test_invalid_doc_type_falls_back_gracefully(self) -> None:
    r = _make_vector_search_result({
        "doc_type": "jpeg",   # not a valid DocType member
        "chunk_type": "image",
        "image_b64": "abc==",
    })
    # Must not raise ValueError; must fall back to DocType.UNKNOWN
    chunk = _to_retrieved_chunk(r)
    assert chunk.metadata.doc_type == DocType.UNKNOWN
    assert chunk.metadata.chunk_type == "image"
    assert chunk.metadata.image_b64 == "abc=="
```

---

## Info

### IN-01: Unused import `from torch import device` in `extractor.py`

**File:** `services/extractor/extractor.py:21`
**Issue:** `from torch import device` is imported at module level but never used anywhere in the file. Importing `torch` at module startup adds significant load time even when no GPU functionality is needed.
**Fix:** Remove the import. If `device` is needed for future GPU routing, import it lazily inside the relevant function.

### IN-02: Magic literal `"auto"` string repeated without central definition

**File:** `services/extractor/extractor.py:405`, `services/extractor/extractor.py:606`, `services/doc_processor/chunker.py:649`
**Issue:** The strings `"auto"`, `"vision"`, `"paddle"`, `"tesseract"`, `"none"` for `ocr_engine` are scattered as literals with no central definition. A typo silently falls through to the default branch.
**Fix:** Define an `OcrEngine` `StrEnum` in `config/settings.py` or `utils/models.py`.

### IN-03: `_process_parent_child` method in `DocProcessorService` is never called (dead code)

**File:** `services/doc_processor/chunker.py:934-954`
**Issue:** The method is defined but the `process()` dispatcher never invokes it. Dead code creates confusion about actual flow.
**Fix:** Remove `_process_parent_child` or add a docstring marking it as a legacy/test-only path.

### IN-04: `total_chunks=-1` sentinel is never resolved for table chunks

**File:** `services/doc_processor/chunker.py:1125`
**Issue:** `_process_tables` sets `total_chunks=-1` as a sentinel but the back-fill logic that resolves it for parent-child chunks is never applied to table chunks. The `-1` persists into the vector store metadata.
**Fix:** After `_process_structure` assembles all chunks, back-fill:
```python
for c in chunks:
    if c.metadata.total_chunks == -1:
        c.metadata.total_chunks = len(chunks)
```

### IN-05: `chunk_type` accepts any string — no enum validation enforced

**File:** `utils/models.py:144`

**Issue:** `ChunkMetadata.chunk_type` is typed `str` with a comment `"text" | "image"`, but Pydantic V2 does not enforce this constraint at runtime. Any string from JSONB (e.g. `"table"`, `"diagram"`, `""`) is silently accepted. Downstream consumers branching on `chunk_type == "image"` will silently mishandle stray values.

**Fix:** Define a `ChunkType` `str`-enum and use it as the field type:
```python
class ChunkType(str, Enum):
    TEXT  = "text"
    IMAGE = "image"

class ChunkMetadata(BaseModel):
    chunk_type: ChunkType = ChunkType.TEXT
```

### IN-06: `image_b64` loaded unconditionally for all chunks regardless of caller needs

**File:** `services/retriever/retriever.py:390`

**Issue:** `image_b64=r.metadata.get("image_b64", "")` materialises the full base64 payload for every chunk on every retrieval call, even for text-only queries. For image chunks this can be hundreds of KB to several MB per chunk. A `top_k=10` result set of image chunks could materialise tens of MB into Python objects that the caller never uses.

**Fix:** Consider a lazy-load approach or an opt-in flag on the retrieval call. At minimum, callers that do not need image payloads should filter on `chunk_type` before building prompts to avoid passing large base64 strings to the LLM context.

---

_Reviewed: 2026-04-27T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
