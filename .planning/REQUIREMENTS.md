# Requirements — v1.1 Retrieval Depth & Frontend

**Milestone:** v1.1
**Status:** Draft (pre-roadmap)
**Created:** 2026-04-27
**Predecessor:** [v1.0 Hardening](milestones/v1.0-REQUIREMENTS.md)

## Milestone Goal

Close the v1.0 image-only-PDF retrieval gap, expose the API as a usable simple frontend, and put a coverage gate on new code so v1.1 doesn't repeat v1.0's coverage drift.

Three independent tracks:

- **Track A — Image PDF Retrieval Depth:** OCR text-layer recovery + page/section metadata + query-time filter extraction. Closes the "第63页…" failure mode discovered post-v1.0.
- **Track B — Frontend Separation:** Extract the inline HTML in `main.py` into a static asset served by FastAPI. No build step, no new dependencies.
- **Track C — Coverage Gate on New Code:** Diff-coverage threshold ≥ 80% on v1.1-touched files only. Legacy modules keep current 46% baseline.

---

## Track A — Image PDF Retrieval Depth

### REQ A-1 (OCR-01): PP-StructureV3 layout-aware OCR for scanned PDFs

**As a** user querying a pure-image PDF (no text layer)
**I want** the document's text content extracted with layout structure preserved
**So that** semantic queries match real document text, not just LLM image captions

**Acceptance criteria:**
1. `services/extractor/extractor.py` calls PP-StructureV3 (not raw PP-OCRv5) for any PDF where `is_scanned_pdf()` is true.
2. PP-StructureV3 receives the PDF path directly and returns per-page text, table HTML, and reading-order blocks. CMYK images are handled internally by PP-StructureV3's page rasterization (no separate per-image CMYK conversion needed).
3. Output is mapped into existing `ExtractedContent` (text + per-page tables) so downstream chunker is unchanged.
4. Tesseract path remains as documented fallback for environments where PaddleOCR is not installed; no silent regression for non-PaddleOCR environments.
5. Integration test: ingesting `data/raw/GB4785-2019.pdf` produces non-empty `chars > 0` and at least one chunk per page span.

### REQ A-2 (OCR-02): Async-safe OCR invocation with bounded concurrency and baked models

**As an** operator running OCR under load
**I want** OCR calls to not block the event loop and to not exhaust CPU/RAM
**So that** ingest workers stay responsive and predictable

**Acceptance criteria:**
1. PP-StructureV3 client is a process-singleton (`functools.lru_cache(maxsize=1)`).
2. Invocation wraps the sync call via `asyncio.to_thread(...)` with a module-level `asyncio.Semaphore` (configurable via `settings.ocr_concurrency`, default 2).
3. Models are baked into the Docker image at build time (no runtime download). `Dockerfile` adds the model-prefetch step. Image size delta documented (~600MB–1.2GB acceptable).
4. ARQ ingest worker pre-warms the OCR singleton on startup so the first request does not pay cold-start latency.
5. Failure-mode handling per research:
   - Hard timeout (`settings.ocr_timeout_sec`, default 120) → retry once via tenacity, then mark `extraction_errors`
   - OOM / process death → bubble up; ARQ retry policy handles
   - Garbled CJK output (heuristic: < 5% ASCII + < 30% CJK character class) → log warning, do not raise

### REQ A-3 (META-01): Section-heading enrichment in chunk content; structured IDs in metadata

**As a** retrieval engineer
**I want** chunks to carry section context in embedded text, but page/section IDs only in metadata
**So that** semantic search benefits from heading semantics without numeric noise diluting the embedding space

**Acceptance criteria:**
1. `services/doc_processor/chunker.py` `content_with_header` field prepends nearest **section heading text** (e.g., `"3.10 定义的透光面\n\n"`) to chunks that fall under it. Page numbers and section numeric IDs are NOT injected into embedded text.
2. `ChunkMetadata.page_number` (already exists) is reliably populated for both text and image chunks. New fields added: `section_id` (e.g., `"3.10"`), `section_title` (e.g., `"定义的透光面"`).
3. For image-caption chunks, the LLM caption call receives the surrounding section heading as context so captions read as "Figure on page 63 in section 3.10 — …" rather than caption-only.
4. Existing chunks without section context (legacy `data/raw` re-ingests) populate empty strings for the new fields and do not error.

### REQ A-4 (META-02): pgvector metadata-filter retrieval with iterative scan

**As a** user issuing "page-N" or section-scoped queries
**I want** the vector store to combine semantic similarity with metadata filters without recall collapse
**So that** filtered queries return results, not empty lists

**Acceptance criteria:**
1. `PgVectorStore.search()` accepts a `filters: dict | None` parameter. `{"page_number": 63}` and `{"section_id": "3.10"}` both supported.
2. Filter is applied as `WHERE` clause on a B-tree **expression index** over `(metadata->>'page_number')` and `(metadata->>'section_id')` (created in `create_collection()` migration).
3. When a filter is present, the search session sets `hnsw.iterative_scan='relaxed_order'` and raises `hnsw.ef_search` to a configurable value (`settings.pgvector_ef_search_filtered`, default 200).
4. Recall test: filtered query for known-good `(page_number, query)` pair returns the matching chunk in the top-3 with same content as unfiltered baseline.
5. Existing unfiltered queries unchanged in behaviour and recall.

### REQ A-5 (QUERY-01): Query-side filter extraction for "第N页" / "第N.M节" patterns

**As a** user typing "第63页…" or "3.10节中的…"
**I want** the page/section number lifted into a metadata filter and the rest used as the semantic query
**So that** the retriever runs a tight filtered search instead of relying on rank-only matching

**Acceptance criteria:**
1. `services/nlu/nlu_service.py` (or new `services/nlu/filter_extractor.py`) runs a **regex-first** extractor against the user query.
2. Patterns supported (priority order):
   - `第\s*(\d+)\s*页` → `{page_number: N}`
   - `(\d+(?:\.\d+)+)\s*节?` → `{section_id: "3.10"}`
   - `(\d+(?:\.\d+)+)条款` → `{section_id: "3.10"}`
3. Extracted filters are **stripped from the semantic query** before embedding so the embedded text doesn't carry the literal numbers.
4. Filters propagate end-to-end: NLU → `pipeline._run_query` → `retriever.retrieve_multi_query` → `vector_store.search(filters=...)`.
5. No LLM-based extractor in v1.1 (regex-only). LLM fallback is an open question for v1.2.

---

## Track B — Frontend Separation

### REQ B-1 (UI-01): Extract inline HTML to a single static asset; serve via FastAPI StaticFiles

**As a** developer touching the UI
**I want** the HTML/JS in its own file with syntax highlighting, not a Python triple-quoted string
**So that** I can edit it like a normal frontend file (linter, formatter, browser dev-tools source maps)

**Acceptance criteria:**
1. `static/ui.html` exists with the full UI markup. Inline JS may stay in the same file (no bundler step in v1.1).
2. `main.py` removes the `_UI_HTML` triple-quoted string and the `/ui` route handler is replaced by `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")`.
3. Visiting `http://localhost:8000/ui/` (or `/ui`) returns the HTML, the page calls `/api/v1/query` with `include_images: true`, and renders answer + sources + images exactly as the inline version did.
4. Docker image includes `static/` (Dockerfile `COPY` covers it; no extra bind-mount needed).
5. Page is responsive on a 1280×800 viewport (no horizontal scroll, source images cap at container width).

---

## Track C — Coverage Gate on New Code

### REQ C-1 (TEST-03): Diff-coverage gate ≥ 80% on v1.1-touched files

**As a** maintainer merging v1.1 PRs
**I want** new and modified files to ship with ≥ 80% line coverage measured against the v1.0 baseline
**So that** v1.1 does not repeat v1.0's coverage drift while not blocking on legacy code

**Acceptance criteria:**
1. CI step runs `pytest --cov` then `diff-cover` against the v1.0 tag (`v1.0`).
2. Threshold: any file with v1.1 changes must have **≥ 80% coverage on the changed lines**. Files untouched in v1.1 are not measured.
3. Threshold-fail blocks merge; legacy 46% global floor remains as separate informational metric.
4. `Makefile` target `make coverage-diff` runs the same check locally against `git diff origin/master...HEAD`.
5. CI artifact: HTML diff-coverage report attached to the GitHub Actions run.

---

## Out of Scope (v1.1)

- LLM-based filter extractor (regex-only in v1.1; LLM fallback deferred to v1.2)
- React / Vue / Streamlit frontend (single static HTML is the v1.1 ceiling)
- Reaching 80% coverage on legacy modules (deferred indefinitely; v1.1 only gates new code)
- MinerU / PP-OCRv5 raw replacement of PP-StructureV3 (research recommends PP-StructureV3 — alternatives deferred)
- OCR container isolation as a separate microservice (single-container deployment in v1.1; isolation deferred)
- Query-time pgvector `ef_search` auto-tuning (fixed value via settings in v1.1; adaptive deferred)

---

## Traceability

| REQ-ID | Track | Phase | Status |
|--------|-------|-------|--------|
| OCR-01 (A-1) | A — Image PDF Retrieval Depth | Phase 7 — OCR Engine Integration | Pending |
| OCR-02 (A-2) | A — Image PDF Retrieval Depth | Phase 7 — OCR Engine Integration | Pending |
| META-01 (A-3) | A — Image PDF Retrieval Depth | Phase 8 — Multimodal Metadata + Query Filter | Pending |
| META-02 (A-4) | A — Image PDF Retrieval Depth | Phase 8 — Multimodal Metadata + Query Filter | Pending |
| QUERY-01 (A-5) | A — Image PDF Retrieval Depth | Phase 8 — Multimodal Metadata + Query Filter | Pending |
| UI-01 (B-1) | B — Frontend Separation | Phase 9 — Frontend Extraction | Pending |
| TEST-03 (C-1) | C — Coverage Gate on New Code | Phase 10 — Coverage Gate on New Code | Pending |

**Coverage:** 7/7 requirements mapped ✓ — no orphans, no duplicates.

**Sequencing notes:**
- Phase 7 → Phase 8: OCR text feeds the chunker which produces section-aware metadata; META-01 cannot be verified without OCR-01 output.
- META-02 → QUERY-01 (intra-Phase 8): the server-side filter pipeline must exist before the query-side regex extractor is wired to it.
- Phase 9 (UI-01) and Phase 10 (TEST-03) are independent of Tracks A and can run parallel/late.
