# Phase 7 — OCR Engine Integration: CONTEXT

**Milestone:** v1.1 Retrieval Depth & Frontend
**Requirements:** OCR-01, OCR-02
**Depends on:** v1.0 Phase 4 (image extraction pipeline)

## Phase Boundary

**In scope:**
- Wire PP-StructureV3 (paddleocr ≥3.1) into `services/extractor/extractor.py` as the OCR engine for `is_scanned_pdf()=true` PDFs
- Map PP-StructureV3 output (per-page text, table HTML, reading-order blocks) into existing `ExtractedContent` model so downstream chunker is unchanged
- Singleton + `asyncio.to_thread` + bounded `asyncio.Semaphore` for async safety
- Bake models into Docker image at build time
- Pre-warm OCR singleton in ARQ worker startup
- Tenacity retry on hard timeout; surface in `extraction_errors`; OOM bubbles up; garbled CJK detection logs warning only
- Settings additions: `ocr_concurrency` (default 2), `ocr_timeout_sec` (default 120)

**Out of scope (Phase 8 territory):**
- Section-heading extraction from PP-StructureV3 reading-order blocks (META-01)
- `ChunkMetadata.section_id` / `section_title` fields (META-01)
- pgvector filter retrieval (META-02)
- Query-side regex filter extractor (QUERY-01)

**Out of scope (deferred):**
- MinerU / raw PP-OCRv5 alternative engines
- OCR microservice container isolation
- LLM-based filter extraction
- Adaptive `ef_search` tuning

## Implementation Decisions (locked)

### Engine

- **PP-StructureV3 over raw PP-OCRv5** — gives layout + tables + reading-order in one call; avoids hand-rolling layout analysis on top of raw OCR.
- **`paddlepaddle==3.0.0` + `paddleocr[doc-parser]==3.1.*`** on Python 3.11 Linux CPU baseline.
- **Tesseract path stays as documented fallback** when PaddleOCR is not installed; no silent regression — existing `_extract_pdf_scanned_paddleocr` already falls back to Tesseract.

### Async Contract

- Singleton via `functools.lru_cache(maxsize=1)` so the model is loaded exactly once per process.
- Sync invocation wrapped via `asyncio.to_thread(...)`.
- Module-level `asyncio.Semaphore(settings.ocr_concurrency)` gates concurrency.

### Container

- Models prefetched at Docker build time so runtime cold-start does not download.
- ARQ worker startup hook calls the singleton once with a 1×1 placeholder image to materialize the model into memory.

### Failure Modes

| Failure | Action |
|---------|--------|
| Hard timeout > `ocr_timeout_sec` | tenacity retry once; on second failure → `extraction_errors`, continue ingest |
| OOM / process death | bubble up; ARQ retry policy handles |
| Garbled CJK output (heuristic: < 5% ASCII + < 30% CJK character class) | log warning, do not raise |

### Claude's Discretion

- Exact placement of the singleton (new `services/extractor/ocr_engine.py` file vs inside `extractor.py`)
- Whether to expose the engine via dependency injection or module-level function — pick whichever matches existing extractor patterns
- Test fixture choice for the integration test — recorded snapshot vs live PaddleOCR run (recorded preferred for CI determinism)

## Canonical References

### Research

- `.planning/research/v1.1-track-a-research.md` — Topic 1 (PaddleOCR integration patterns) is the authoritative source for this phase
- `.planning/phases/07-ocr-engine-integration/RESEARCH.md` — phase-scoped extract pointing at the above

### Codebase Anchors

- `services/extractor/extractor.py:54` — `is_scanned_pdf()` density check (already exists, reuse)
- `services/extractor/extractor.py:266` — `_extract_pdf_scanned_paddleocr()` warning "PaddleOCR未安装，回退Tesseract" — this is where the new engine lands
- `services/extractor/extractor.py:579-662` — `extract()` entrypoint and result mapping
- `services/extractor/image_extractor.py:95` — CMYK extract failures (Phase 4 path; orthogonal — PP-StructureV3 rasterizes pages internally so CMYK is not an issue for OCR)
- `Dockerfile` — OCR model prefetch step lands here
- `services/ingest_worker.py` (or equivalent ARQ worker module) — `WorkerSettings.on_startup` for singleton pre-warm
- `config/settings.py` — `ocr_concurrency` and `ocr_timeout_sec` settings

### v1.0 Outputs to Avoid Breaking

- `IngestionResponse.extraction_errors` — must continue to surface non-fatal OCR errors
- `ChunkMetadata.image_b64` and image-caption pipeline (Phase 4) — independent path, must keep working
- Tesseract fallback — must keep working when paddleocr is not importable

## Specific Ideas

- Make `OcrEngine` a small abstract base with `extract_pdf(path) -> ExtractedContent`-shaped output and concrete `PpStructureV3Engine` / `TesseractEngine` implementations selected via `settings.ocr_engine` ("auto" → paddle first, fallback tesseract).
- Add a `services/extractor/ocr_engine.py` module to host the singleton and the `asyncio.to_thread`/`Semaphore` plumbing — keeps `extractor.py` from growing further (it's already 600+ lines).
- Prefer letting PP-StructureV3 read the PDF directly (`pipeline.predict(input=pdf_path)`) rather than per-page rasterization — research notes this is the documented happy path.
- For the model bake step: in `Dockerfile`, add a build stage that runs a tiny Python snippet importing PP-StructureV3 and triggering model download into `~/.paddleocr/` (or whatever path PaddleOCR uses). Copy that path into the runtime image.

## Deferred Ideas

- Replacing Tesseract entirely (still keep as fallback)
- Streaming OCR results back through the pipeline (not needed — ingest is async via ARQ)
- GPU-accelerated PaddlePaddle build (CPU baseline ships first; GPU is a follow-up if latency demands it)
- Per-tenant OCR engine override

## Open Questions for Planner

1. **Model bake mechanics** — is there a documented `paddleocr download-model` CLI, or does the import-then-instantiate trigger it? The research doc lists this as an open question; the planner should resolve it during plan-writing or punt it to the executor with a concrete probe.
2. **Tesseract retention strategy** — keep the existing `_extract_pdf_scanned_paddleocr` (which already falls back to Tesseract) but route through the new engine abstraction, or carve Tesseract out into its own engine class? Planner picks based on minimum-diff principle.
3. **Concurrency default** — `ocr_concurrency=2` is a guess. The planner should verify against expected ARQ worker count and document the chosen default in PLAN.md.
