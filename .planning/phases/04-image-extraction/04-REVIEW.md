---
phase: 04-image-extraction
reviewed: 2026-04-27T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - utils/models.py
  - services/extractor/image_extractor.py
  - services/extractor/extractor.py
  - services/doc_processor/chunker.py
  - services/pipeline.py
  - tests/unit/test_image_models.py
  - tests/unit/test_image_extractor.py
findings:
  critical: 0
  warning: 6
  info: 4
  total: 10
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-04-27T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Seven files were reviewed covering the image-extraction phase additions: new Pydantic models (`ExtractedImage`, `ChunkMetadata` image fields), PDF image extraction via PyMuPDF, standalone image extraction, chunker image-captioning, the full ingestion/query pipelines, and two unit test modules.

The models and image extractor are well-structured and meet ERR-01 (no bare `except`). The main concerns are:

- Two bare `except Exception` blocks in `extractor.py` violate the project's ERR-01 rule.
- `asyncio.get_event_loop()` is deprecated / unsafe in Python 3.10+ async contexts — used twice in `extractor.py`.
- `ExtractedContent` is mutated after construction in `extractor.py`, bypassing Pydantic's immutability intent and breaking the `model_post_init` auto-count logic.
- The `_chunk_images` method in `chunker.py` mutates `content.extraction_errors` (a passed-in Pydantic model) from inside an async method, which is a side-effect anti-pattern.
- The test for `test_no_bare_except_in_module` uses a relative path that will fail when pytest is run from any directory other than the project root.
- Global singleton factories (`get_ingest_pipeline`, etc.) in `pipeline.py` are not thread-safe.

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
# Instead of mutating, pass images at construction (refactor Stage 2b to collect images first, then build content)
# Or at minimum use model_copy to keep validation in the picture:
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
Then in `process()`, caller merges errors: `content.extraction_errors.extend(img_errors)` (or propagates via return value).

### WR-05: Global singleton factories are not thread-safe

**File:** `services/pipeline.py:707-727`
**Issue:** The module-level singletons (`_ingest_pipeline`, `_query_pipeline`, `_agent_pipeline`) are initialized with a non-atomic check-then-set pattern. Under concurrent ASGI startup (e.g., multiple Uvicorn workers sharing an asyncio loop, or multi-threaded test runners), two threads can both see `None` and both construct, with the second overwriting the first. The service objects hold stateful clients.
**Fix:** Use a lock or the `functools.cache` / `lru_cache` pattern:
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
**Issue:** `module_path = Path("services/extractor/image_extractor.py")` is relative to the current working directory. When pytest is invoked from a directory other than the repo root (e.g., `python -m pytest tests/` from inside `tests/`), `module_path.exists()` returns `False` and the test skips silently instead of asserting. The ERR-01 structural test becomes unreliable.
**Fix:**
```python
module_path = Path(__file__).parent.parent.parent / "services/extractor/image_extractor.py"
```

---

## Info

### IN-01: Unused import `from torch import device` in `extractor.py`

**File:** `services/extractor/extractor.py:21`
**Issue:** `from torch import device` is imported at module level but never used anywhere in the file. Importing `torch` at module startup adds significant load time (~1–2 seconds) even when no GPU functionality is needed.
**Fix:** Remove the import entirely. If `device` is needed for future OCR GPU routing, import it lazily inside the relevant function.

### IN-02: Magic literal `"auto"` string repeated across `extractor.py` and `pipeline.py`

**File:** `services/extractor/extractor.py:405`, `services/extractor/extractor.py:606`, `services/doc_processor/chunker.py:649`
**Issue:** The string `"auto"` (and `"vision"`, `"paddle"`, `"tesseract"`, `"none"`) for `ocr_engine` values are scattered as string literals with no central definition. A typo would silently fall through to the default branch.
**Fix:** Define an `OcrEngine` `StrEnum` in `config/settings.py` or `utils/models.py` to make the values explicit and type-safe.

### IN-03: `_process_parent_child` method in `DocProcessorService` is never called

**File:** `services/doc_processor/chunker.py:934-954`
**Issue:** The method `_process_parent_child` is defined but the `process()` dispatcher never invokes it — parent-child logic is handled inline via `_make_parent_child`. The method is dead code and its presence creates confusion about the actual flow.
**Fix:** Either remove `_process_parent_child` or document clearly that it's a legacy path kept for direct testing only.

### IN-04: `total_chunks=-1` sentinel is never resolved for table chunks

**File:** `services/doc_processor/chunker.py:1125`
**Issue:** `_process_tables` sets `total_chunks=-1` as a sentinel, matching the parent-child pattern. However, unlike the parent-child flow (which back-fills at lines 461-463), table chunks produced by `_process_tables` within `_process_structure` are never back-filled with actual total counts. The `-1` sentinel persists into the vector store metadata.
**Fix:** After `_process_structure` assembles all chunks (text + table), back-fill `total_chunks`:
```python
for c in chunks:
    if c.metadata.total_chunks == -1:
        c.metadata.total_chunks = len(chunks)
```

---

_Reviewed: 2026-04-27T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
