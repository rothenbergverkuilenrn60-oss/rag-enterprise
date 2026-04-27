# Phase 4: Image Extraction — Pattern Map

**Mapped:** 2026-04-24
**Files analyzed:** 6 (1 new, 5 modified)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/extractor/image_extractor.py` | service | file-I/O + request-response | `services/extractor/extractor.py` (`_extract_pdf_vision_async`) | exact |
| `utils/models.py` | model | transform | `utils/models.py` (existing Pydantic models) | exact (self-analog) |
| `services/extractor/extractor.py` | service | file-I/O | `services/extractor/extractor.py` (existing) | exact (self-analog) |
| `services/doc_processor/chunker.py` | service | transform | `services/doc_processor/chunker.py` (`parent_child_split`) | exact (self-analog) |
| `services/pipeline.py` | orchestrator | request-response | `services/pipeline.py` (`_run_ingest`) | exact (self-analog) |
| `services/vectorizer/vector_store.py` | service | CRUD | `services/vectorizer/vector_store.py` (`upsert`) | exact (self-analog) |

---

## Pattern Assignments

### `services/extractor/image_extractor.py` (new, service, file-I/O + request-response)

**Analog:** `services/extractor/extractor.py` — `_extract_pdf_vision_async` (lines 332–377)

**Imports pattern** (copy from extractor.py lines 10–26):
```python
from __future__ import annotations
import asyncio
import base64
from pathlib import Path
from typing import Any
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from utils.models import ExtractedContent, DocType
```

**New model needed — define in utils/models.py first:**
```python
class ExtractedImage(BaseModel):
    page_number: int
    image_index: int          # index within page
    width: int
    height: int
    media_type: str = "image/png"
    image_b64: str            # base64-encoded, already resized to <= 1024px
    caption: str = ""         # filled by LLM captioning
```

**Core image extraction pattern** (model after extractor.py lines 344–376):
```python
import fitz
import base64
from PIL import Image
import io

async def extract_images_from_pdf(
    file_path: Path,
    llm_client,
    doc_id: str,
) -> tuple[list[ExtractedImage], list[str]]:
    """
    Returns (images, errors).
    Skips images < 100x100 px (D-01).
    Caps at 50 images per document (D-02).
    Resizes to <= 1024px before base64 encoding (D-05).
    Caption failures append to errors, not raise (D-03/D-04).
    """
    loop = asyncio.get_event_loop()
    # fitz is blocking — run in executor (same pattern as ExtractorService.extract line 610)
    raw_images = await loop.run_in_executor(None, _extract_raw_images, file_path)

    images: list[ExtractedImage] = []
    errors: list[str] = []

    if len(raw_images) > 50:          # D-02
        logger.warning(
            f"[ImageExtractor] doc_id={doc_id} found {len(raw_images)} images, "
            f"capping at 50"
        )
        raw_images = raw_images[:50]

    for item in raw_images:
        w, h = item["width"], item["height"]
        if w < 100 or h < 100:        # D-01 — silent skip
            continue

        img_b64 = _resize_and_encode(item["image"], item["ext"])  # D-05

        try:
            caption = await llm_client.chat_with_vision(
                system=_IMAGE_CAPTION_SYSTEM,
                image_b64=img_b64,
                query="请简洁描述这张图片的内容。",
                media_type=f"image/{item['ext']}",
                task_type="generate",
            )
        except (openai.APIError, httpx.HTTPError, anthropic.APIError) as exc:  # D-03 ERR-01
            logger.warning(
                f"[ImageExtractor] caption failed doc_id={doc_id} "
                f"page={item['page_number']}: {exc}",
                exc_info=exc,
            )
            errors.append(f"Image p{item['page_number']} skipped: {exc}")      # D-04
            continue

        images.append(ExtractedImage(
            page_number=item["page_number"],
            image_index=item["image_index"],
            width=w,
            height=h,
            media_type=f"image/{item['ext']}",
            image_b64=img_b64,
            caption=caption.strip(),
        ))

    return images, errors
```

**Blocking helper — runs in executor:**
```python
def _extract_raw_images(file_path: Path) -> list[dict]:
    """fitz image extraction — blocking, call via run_in_executor."""
    import fitz
    doc = fitz.open(str(file_path))
    results = []
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        for img_idx, img_tuple in enumerate(page.get_images(full=True)):
            xref = img_tuple[0]
            img_data = doc.extract_image(xref)
            results.append({
                "page_number": page_idx + 1,
                "image_index": img_idx,
                "width": img_data["width"],
                "height": img_data["height"],
                "ext": img_data["ext"],          # "png", "jpeg", etc.
                "image": img_data["image"],      # raw bytes
            })
    doc.close()
    return results
```

**Resize pattern** (D-05 — Pillow, already available in Tesseract path):
```python
def _resize_and_encode(image_bytes: bytes, ext: str) -> str:
    """Resize to max 1024px on either dimension, return base64 string."""
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    fmt = "PNG" if ext.lower() in ("png", "unknown") else ext.upper()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()
```

**Caption system prompt** (mirror `_VISION_OCR_SYSTEM` pattern, extractor.py lines 323–330):
```python
_IMAGE_CAPTION_SYSTEM = """\
你是专业的图像内容描述助手。
请简洁准确地描述图片中的内容：
  - 图表：说明图表类型、坐标轴含义、关键数据点
  - 照片：描述主体对象和场景
  - 图示/流程图：说明流程步骤和关系
  - 只输出描述内容，不要添加说明或注释
"""
```

**Error handling pattern** (follow ERR-01, extractor.py line 614):
```python
# Narrow exception types per ERR-01 / D-03:
except (openai.APIError, httpx.HTTPError, anthropic.APIError) as exc:
    logger.warning(f"...", exc_info=exc)
    errors.append(f"Image p{N} skipped: {exc}")
    continue
# NOT: except Exception
```

---

### `utils/models.py` — add `ExtractedImage` model + modify `ExtractedContent` and `ChunkMetadata`

**Analog:** `utils/models.py` existing Pydantic V2 models (lines 73–127)

**New `ExtractedImage` model** — insert after line 87 (after `ExtractedContent`'s field block):
```python
class ExtractedImage(BaseModel):
    """Single image extracted from a document page."""
    page_number:  int
    image_index:  int
    width:        int
    height:       int
    media_type:   str  = "image/png"
    image_b64:    str              # base64 str — JSON-serialisable, no bytes
    caption:      str  = ""
```

**Modify `ExtractedContent`** — add `images` field (line 87, after `images_count`):
```python
images_count:      int               = 0
images:            list[ExtractedImage] = Field(default_factory=list)  # ADD
```

**Modify `ChunkMetadata`** — add `chunk_type` discriminator (after `node_type` line 126):
```python
node_type:       str           = "paragraph"
chunk_type:      str           = "text"    # "text" | "image" — ADD
```

**Modify `IngestionResponse`** — add `extraction_errors` field (per CONTEXT.md D-04):
```python
class IngestionResponse(BaseModel):
    doc_id:            str
    total_chunks:      int        = 0
    success:           bool       = True
    elapsed_ms:        float      = 0.0
    error:             str | None = None
    extraction_errors: list[str]  = Field(default_factory=list)  # ADD
```

**Also add `DocType.IMAGE`** — after `DocType.MD` (line 28):
```python
MD      = "md"
IMAGE   = "image"   # ADD — standalone image files (jpg/png/webp)
UNKNOWN = "unknown"
```

**Pydantic V2 pattern** (copy from existing models, lines 44–50):
```python
class MyModel(BaseModel):
    field: str = Field(default_factory=list)
    optional: str | None = None
```

---

### `services/extractor/extractor.py` — integrate image extraction into `ExtractorService.extract()`

**Analog:** `services/extractor/extractor.py` — `ExtractorService.extract()` lines 569–638

**Integration point — after `result_dict` is assembled (line 619), before `ExtractedContent` construction:**
```python
# ── Image extraction (PDF only) ───────────────────────────────────────────
extracted_images: list[ExtractedImage] = []
if doc_type == DocType.PDF and llm_client is not None:
    from services.extractor.image_extractor import extract_images_from_pdf
    img_list, img_errors = await extract_images_from_pdf(
        file_path=path,
        llm_client=llm_client,
        doc_id=doc.raw_id,
    )
    extracted_images = img_list
    errors.extend(img_errors)          # D-04: partial success
```

**Modify `ExtractedContent` construction** (lines 620–633) — add `images` field:
```python
content = ExtractedContent(
    ...
    images_count=len(extracted_images),   # was: result_dict.get("images_count", 0)
    images=extracted_images,              # ADD
    ...
)
```

**`_EXTRACTOR_MAP` — add `DocType.IMAGE`** (after line 553):
```python
DocType.IMAGE: _extract_standalone_image,   # ADD
```

**New `_extract_standalone_image` function** — standalone image path (IMG-04):
```python
def _extract_standalone_image(file_path: Path) -> dict:
    """Standalone image files: return minimal dict; captioning done in ExtractorService."""
    return {
        "body_text": "",
        "tables": [],
        "pages": 1,
        "title": file_path.stem,
        "engine": "standalone-image",
    }
```

**`_detect_doc_type`** — add image extensions (after line 560):
```python
".jpg": DocType.IMAGE, ".jpeg": DocType.IMAGE,
".png": DocType.IMAGE, ".webp": DocType.IMAGE,
```

**`run_in_executor` pattern** (lines 609–610 — use for all blocking fitz calls):
```python
loop = asyncio.get_event_loop()
result_dict = await loop.run_in_executor(None, extractor_fn, path)
```

---

### `services/doc_processor/chunker.py` — generate image chunks

**Analog:** `services/doc_processor/chunker.py` — `parent_child_split` DocumentChunk construction (lines 395–457)

**New function to add — `image_chunks_from_extracted`:**
```python
def image_chunks_from_extracted(
    content: ExtractedContent,
    doc_id: str,
    start_index: int = 0,
) -> list[DocumentChunk]:
    """Build one DocumentChunk per ExtractedImage.
    Caption is the embedding input (content_with_header).
    base64 bytes travel in metadata (JSON-serialisable str).
    """
    chunks: list[DocumentChunk] = []
    for idx, img in enumerate(content.images):
        chunk_idx = start_index + idx
        chunk_id = _make_chunk_id(doc_id, chunk_idx, img.caption or f"image_{idx}")
        meta = ChunkMetadata(
            source=content.metadata.get("source", ""),
            doc_id=doc_id,
            title=content.title,
            author=content.author,
            page_number=img.page_number,
            chunk_index=chunk_idx,
            total_chunks=-1,           # back-filled by caller
            doc_type=content.doc_type,
            chunk_level="child",
            node_type="image",
            chunk_type="image",        # discriminator field
        )
        caption_text = img.caption or f"[图片 第{img.page_number}页]"
        chunks.append(DocumentChunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            content=caption_text,
            content_with_header=f"来源：{content.title}\n\n{caption_text}",
            metadata=meta,
            token_count=count_tokens(caption_text),
        ))
    return chunks
```

**`metadata` carries base64** — store on `ChunkMetadata` via a custom field OR embed in the `metadata` dict that flows through JSONB. Since `ChunkMetadata.model_dump(mode="json")` is called before JSONB insertion (vector_store.py line 167), add `image_b64: str = ""` directly to `ChunkMetadata`:
```python
# In ChunkMetadata (utils/models.py):
image_b64:       str           = ""    # non-empty for chunk_type="image"
```

**Existing `_make_chunk_id` pattern** (chunker.py lines 42–44):
```python
def _make_chunk_id(doc_id: str, idx: int, text: str) -> str:
    suffix = hashlib.md5(text[:64].encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{doc_id}_{idx:04d}_{suffix}"
```

---

### `services/pipeline.py` — wire image chunks into `_run_ingest`

**Analog:** `services/pipeline.py` — `_run_ingest` lines 98–232

**No pipeline structural changes** — image chunks come out of `self._doc_processor.process(extracted, ...)` because `chunker.py` handles them. The pipeline calls are unchanged. The only addition is surfacing `extraction_errors` in the response:

```python
# Replace final return (line 231–232):
return IngestionResponse(
    doc_id=doc_id,
    total_chunks=vr.total_chunks,
    success=True,
    elapsed_ms=elapsed_ms,
    extraction_errors=extracted.extraction_errors,   # ADD — D-04 partial success
)
```

**Standalone image ingest** — `_infer_doc_type` needs image extensions:
```python
".jpg": DocType.IMAGE, ".jpeg": DocType.IMAGE,
".png": DocType.IMAGE, ".webp": DocType.IMAGE,
```

---

### `services/vectorizer/vector_store.py` — no changes needed

**Analog:** `vector_store.py` `upsert()` lines 150–194

The existing `upsert` already stores `metadata JSONB` via `c.metadata.model_dump(mode="json")`. Adding `image_b64` and `chunk_type` fields to `ChunkMetadata` automatically flows through without any vector_store changes. `image_b64` is a `str` field so it is JSON-serialisable.

Pattern to confirm compatibility (line 167):
```python
_json.dumps(c.metadata.model_dump(mode="json"))
# model_dump(mode="json") serialises all fields including image_b64: str — no bytes issues
```

---

## Shared Patterns

### run_in_executor for blocking fitz/Pillow work
**Source:** `services/extractor/extractor.py` lines 609–610
**Apply to:** `image_extractor.py` `_extract_raw_images` call
```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, blocking_fn, arg)
```

### Exception narrowing (ERR-01)
**Source:** `services/pipeline.py` lines 195–196, 227–228 (non-fatal warning pattern)
**Apply to:** `image_extractor.py` caption call site (D-03)
```python
except (openai.APIError, httpx.HTTPError, anthropic.APIError) as exc:
    logger.warning(f"[...] failed: {exc}", exc_info=exc)
    errors.append(f"Image p{N} skipped: {exc}")
    continue
# NOT bare except Exception
```

### logger.warning + continue for per-item recoverable failures
**Source:** `services/extractor/extractor.py` line 368, `services/pipeline.py` lines 195–196
**Apply to:** image caption loop in `image_extractor.py`
```python
try:
    caption = await llm_client.chat_with_vision(...)
except (openai.APIError, httpx.HTTPError, anthropic.APIError) as exc:
    logger.warning(f"...", exc_info=exc)
    errors.append(...)
    continue    # no chunk created — D-03
```

### Pydantic V2 model_dump for JSONB
**Source:** `services/vectorizer/vector_store.py` line 167
**Apply to:** all new fields on `ChunkMetadata` — must be JSON-serialisable types (str, int, float, list, dict — NOT bytes)
```python
_json.dumps(c.metadata.model_dump(mode="json"))
```

### chat_with_vision signature
**Source:** `services/generator/llm_client.py` lines 492–525
```python
await llm_client.chat_with_vision(
    system=_IMAGE_CAPTION_SYSTEM,   # str
    image_b64=img_b64,              # str (base64)
    query="请简洁描述这张图片的内容。",
    media_type="image/png",         # or "image/jpeg" etc.
    task_type="generate",
)  # returns str
```

---

## No Analog Found

None — all files have direct analogs in the existing codebase.

---

## Metadata

**Analog search scope:** `services/extractor/`, `services/doc_processor/`, `services/vectorizer/`, `services/generator/`, `services/pipeline.py`, `utils/models.py`
**Files scanned:** 6
**Pattern extraction date:** 2026-04-24
