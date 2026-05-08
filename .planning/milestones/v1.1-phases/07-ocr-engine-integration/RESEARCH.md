# Phase 7 — OCR Engine Integration: RESEARCH

**Source:** Phase-scoped extract from `.planning/research/v1.1-track-a-research.md` (Topic 1: PaddleOCR integration). Topic 2 of that document covers Phase 8 metadata work.

This file points at the canonical research doc. The planner should read both this summary and the source for full code snippets and citations.

---

## Recommendation

Use **PP-StructureV3** (not raw PP-OCRv5) as the OCR engine. It accepts a PDF path directly and returns per-page text, table HTML, and reading-order blocks in a single call.

```python
from paddleocr import PPStructureV3

pipeline = PPStructureV3()  # singleton
result = pipeline.predict(input=pdf_path)  # list[PageResult]
```

## Why

1. **Layout-aware** — multi-column reading order, tables, formulas all surface in one call. Raw PP-OCRv5 returns flat boxes that you'd need to re-layout yourself.
2. **CMYK is solved internally** — PP-StructureV3 rasterizes each PDF page to RGB before recognition. The v1.0 PyMuPDF "cannot write mode CMYK as PNG" failures only affected per-image extraction; OCR via PP-StructureV3 sidesteps that path.
3. **Single dependency tree** — `paddleocr[doc-parser]==3.1.*` brings in everything (PP-OCRv5 + layout + table + formula models).
4. **Compatible with Python 3.11 + Linux CPU** — research-verified version pin: `paddlepaddle==3.0.0` + `paddleocr[doc-parser]==3.1.*`.

## Implementation Sketch

### Singleton + Async Wrapping

```python
# services/extractor/ocr_engine.py
import asyncio
from functools import lru_cache
from paddleocr import PPStructureV3
from config.settings import settings

@lru_cache(maxsize=1)
def _engine() -> PPStructureV3:
    return PPStructureV3()  # loads ~600MB-1.2GB of models

_sem = asyncio.Semaphore(settings.ocr_concurrency)

async def ocr_pdf(pdf_path: str) -> list:
    async with _sem:
        return await asyncio.to_thread(_engine().predict, input=pdf_path)
```

### Pre-warm in ARQ Worker

```python
# services/ingest_worker.py (or wherever WorkerSettings lives)
async def startup(ctx):
    from services.extractor.ocr_engine import _engine
    _engine()  # materialize the model on worker boot
```

### Docker Bake

```dockerfile
# Dockerfile (between dependency install and code copy)
RUN python -c "from paddleocr import PPStructureV3; PPStructureV3()" \
    && du -sh /root/.paddlex
```

(Path may be `~/.paddleocr/` — verify during planning. Either way, copy that directory into the runtime stage.)

### Failure Mode Handling

| Failure | Detection | Action |
|---------|-----------|--------|
| Timeout | `asyncio.wait_for(..., settings.ocr_timeout_sec)` | tenacity retry once; on second failure → mark in `extraction_errors`, continue |
| OOM | OS kills the worker | bubble up; ARQ retry policy handles |
| Garbled CJK | Heuristic: `cjk_ratio < 0.30 and ascii_ratio < 0.05` | `logger.warning`, return as-is (do not raise) |

## Pitfalls

1. **PP-StructureV3 has no documented thread safety** — never share an instance across threads without the singleton+semaphore wrapper.
2. **First call is slow** — model load is 5–15s on CPU. Pre-warm or every first ingest pays this cost.
3. **GB national-standard PDFs** can have:
   - Mixed CMYK + RGB pages (handled internally by PP-StructureV3)
   - Vertical / multi-column layout (PP-StructureV3 reading-order helps but verify on `data/raw/GB4785-2019.pdf`)
   - Equations and tables with complex structure (PP-StructureV3 returns structured table HTML — keep it intact when mapping to `ExtractedContent`)
4. **Image size delta in container** is significant (~600MB–1.2GB). Document this in PLAN.md and call out CI image build time impact.
5. **Don't fallback silently** — if PP-StructureV3 import fails at runtime, log a clear error and route to Tesseract; don't pretend OCR succeeded with empty output.

## Open Questions for Planner

- Whether `paddleocr download-model` is a documented CLI, or download is implicit in instantiation (research recommends verifying during planning)
- How to keep the existing Tesseract fallback wired without duplicating the engine selection logic
- Default value for `settings.ocr_concurrency` — research uses 2 as a placeholder; planner should justify against expected ARQ worker concurrency
- Whether to add a `settings.ocr_engine` enum ("auto" / "paddle" / "tesseract") for explicit operator control vs auto-detection
