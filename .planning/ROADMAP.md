# Roadmap — EnterpriseRAG

## Milestones

- ✅ **v1.0 Hardening** — Phases 1–6 (shipped 2026-04-27) — [archive](milestones/v1.0-ROADMAP.md)
- 🚧 **v1.1 Retrieval Depth & Frontend** — Phases 7–10 (in progress)

## Phases

<details>
<summary>✅ v1.0 Hardening (Phases 1–6) — SHIPPED 2026-04-27</summary>

- [x] Phase 1: pgvector Foundation (4/4 plans) — completed 2026-04-22
- [x] Phase 2: Security Hardening + Operational Fixes (3/3 plans) — completed 2026-04-23
- [x] Phase 3: Error Handling Sweep (3/3 plans) — completed 2026-04-24
- [x] Phase 4: Image Extraction (4/4 plans) — completed 2026-04-25
- [x] Phase 5: Async Ingest Tracking (3/3 plans) — completed 2026-04-26
- [x] Phase 6: Test Coverage and Eval (3/3 plans) — completed 2026-04-27

See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) for full phase details.

</details>

### v1.1 Retrieval Depth & Frontend (Phases 7–10)

- [ ] **Phase 7: OCR Engine Integration** — PP-StructureV3 layout-aware OCR with async/concurrency/baked models
- [ ] **Phase 8: Multimodal Metadata + Query Filter** — section enrichment, JSONB filter retrieval, regex query extractor
- [ ] **Phase 9: Frontend Extraction** — static HTML asset served via FastAPI StaticFiles
- [ ] **Phase 10: Coverage Gate on New Code** — diff-cover CI step + Makefile target

**Phase grouping rationale:** Track A is split into Phase 7 (engine plumbing) and Phase 8 (metadata + filter retrieval) because OCR text must flow through the chunker before section-aware metadata can be produced; QUERY-01 must land in the same phase as META-02 since the regex extractor and the filtered-search code path are tested together end-to-end. Phases 9 and 10 are kept separate despite both being small: Phase 9 is asset/code work in `main.py` + `static/`, Phase 10 is CI/Makefile/tooling — zero shared files, different verification surfaces, cleaner ship boundaries.

## Phase Details

### Phase 7: OCR Engine Integration

**Goal:** Pure-image PDFs ingest with real per-page text and tables extracted by PP-StructureV3, running async-safe under bounded concurrency with models baked into the Docker image.
**Depends on:** v1.0 Phase 4 (image extraction pipeline must exist; OCR text path runs alongside it)
**Requirements:** OCR-01, OCR-02
**Success Criteria** (what must be TRUE):
  1. Ingesting `data/raw/GB4785-2019.pdf` (an image-only PDF) produces non-empty `chars > 0` and at least one chunk per page span — verified end-to-end through the existing `/ingest` endpoint.
  2. PP-StructureV3 is invoked exactly once per process (singleton); concurrent ingest requests do not exceed `settings.ocr_concurrency` parallel OCR calls.
  3. Building the production Docker image produces a self-contained container that performs its first OCR request within 5 seconds of worker startup (no runtime model download).
  4. An OCR call exceeding `settings.ocr_timeout_sec` retries once and, on second failure, surfaces in `IngestionResponse.extraction_errors` rather than crashing the worker.
  5. Environments without PaddleOCR installed continue to use the documented Tesseract fallback with no behavioural regression.
**Plans:** 2 plans

Plans:
- [ ] 07-01-PLAN.md — OcrEngine module + PP-StructureV3 singleton + Tesseract fallback adapter + settings/deps (OCR-01/02 partial)
- [ ] 07-02-PLAN.md — Docker model bake + ARQ worker pre-warm + tenacity timeout retry + garbled-CJK heuristic + GB4785 e2e integration test (OCR-01/02 complete)

### Phase 8: Multimodal Metadata + Query Filter

**Goal:** A user typing "第63页…" or "3.10节中的…" gets the page/section lifted into a metadata filter and returns the matching chunk in the top-3, with section-heading context aiding semantic recall but page numbers never polluting the embedding space.
**Depends on:** Phase 7 (chunker needs OCR text + reading-order blocks before it can attach `section_id` / `section_title`)
**Requirements:** META-01, META-02, QUERY-01
**Success Criteria** (what must be TRUE):
  1. A chunk from a known section reads `"3.10 定义的透光面\n\n<body>"` in `content_with_header`, while `metadata.section_id` is `"3.10"` and `metadata.section_title` is `"定义的透光面"` — page numbers and section numeric IDs do not appear in the embedded text.
  2. A filtered query for a known `(page_number=63, query)` pair returns the matching chunk in the top-3 against `PgVectorStore`; the same query without filter still works at unchanged recall.
  3. A user query "第63页灯具的发光面" reaches `vector_store.search()` with `filters={"page_number": 63}` and the literal "第63页" stripped from the embedded query text.
  4. Image-caption chunks produced by Phase 4's pipeline carry the host page's `page_number` and `section_id` and are retrievable by page-scoped queries.
  5. Existing legacy chunks ingested before v1.1 (without section context) load and search without errors.
**Plans:** 5 plans

Plans:
**Wave 1**
- [ ] 08-01-PLAN.md — Wave 0 schema + settings + pgvector ≥ 0.8.0 gate + RED test scaffolds (META-01, META-02, QUERY-01)
- [ ] 08-02-PLAN.md — services/nlu/filter_extractor.py + unit tests (QUERY-01)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 08-03-PLAN.md — Chunker GB section walker + D-02 content_with_header + D-04 image-caption injection (META-01)
- [ ] 08-04-PLAN.md — PgVectorStore B-tree expression indexes + filtered HNSW search + SET LOCAL hnsw GUCs (META-02)

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 08-05-PLAN.md — Pipeline wiring (extract_filters → tf merge → effective_query) + e2e propagation integration test (QUERY-01, META-02)

### Phase 9: Frontend Extraction

**Goal:** The inline UI is a real `static/ui.html` file editable with normal frontend tooling, served by FastAPI StaticFiles at `/ui/`, with no behavioural change versus the v1.0 inline page.
**Depends on:** Nothing (parallel with Phase 7/8 — independent track)
**Requirements:** UI-01
**Success Criteria** (what must be TRUE):
  1. `static/ui.html` exists as a standalone file; `main.py` no longer contains a `_UI_HTML` triple-quoted string and the `/ui` route is replaced by `app.mount("/ui", StaticFiles(directory="static", html=True))`.
  2. Visiting `http://localhost:8000/ui/` renders the UI, calls `/api/v1/query` with `include_images: true`, and renders answer + sources + images identically to the v1.0 inline version.
  3. The production Docker image includes `static/` via `COPY` and serves the page without any bind-mount or extra volume.
  4. The page renders without horizontal scroll on a 1280×800 viewport; source images cap at the container width.
**Plans:** 1 plan
**UI hint**: yes

Plans:
**Wave 1**
- [x] 09-01-PLAN.md — Extract `_UI_HTML` to `static/ui.html`, mount StaticFiles in main.py, verify Dockerfile COPY, integration test + human visual verify (UI-01)

### Phase 10: Coverage Gate on New Code

**Goal:** Any v1.1 PR touching a file leaves that file at ≥ 80% line coverage on the changed lines; legacy modules continue to track the v1.0 46% baseline as a separate metric.
**Depends on:** Nothing (tooling layer — runs against whatever code has shipped). Lands last so it gates Phase 7–9 deliverables on the way through CI.
**Requirements:** TEST-03
**Success Criteria** (what must be TRUE):
  1. A PR that modifies a v1.1 file with < 80% diff coverage fails the CI `coverage-diff` step; a PR meeting the threshold passes.
  2. `make coverage-diff` run locally against `git diff origin/master...HEAD` produces the same pass/fail verdict as CI.
  3. The CI run attaches an HTML diff-coverage report as a downloadable GitHub Actions artifact.
  4. The legacy 46% global floor remains a separate informational CI step and continues to pass for unchanged files.
**Plans:** 1 plan

Plans:
- [x] 10-01-PLAN.md — diff-cover dependency pin + CI step against v1.0 + Makefile coverage-diff target + README docs (TEST-03 complete in single wave)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. pgvector Foundation | v1.0 | 4/4 | Complete ✓ | 2026-04-22 |
| 2. Security Hardening + Operational Fixes | v1.0 | 3/3 | Complete ✓ | 2026-04-23 |
| 3. Error Handling Sweep | v1.0 | 3/3 | Complete ✓ | 2026-04-24 |
| 4. Image Extraction | v1.0 | 4/4 | Complete ✓ | 2026-04-25 |
| 5. Async Ingest Tracking | v1.0 | 3/3 | Complete ✓ | 2026-04-26 |
| 6. Test Coverage and Eval | v1.0 | 3/3 | Complete ✓ | 2026-04-27 |
| 7. OCR Engine Integration | v1.1 | 0/2 | Not started | - |
| 8. Multimodal Metadata + Query Filter | v1.1 | 0/0 | Not started | - |
| 9. Frontend Extraction | v1.1 | 0/1 | Not started | - |
| 10. Coverage Gate on New Code | v1.1 | 0/0 | Not started | - |

## Coverage Validation

All 7 v1.1 REQ-IDs map to exactly one phase:

| REQ-ID | Track | Phase |
|--------|-------|-------|
| OCR-01 (A-1) | A | Phase 7 |
| OCR-02 (A-2) | A | Phase 7 |
| META-01 (A-3) | A | Phase 8 |
| META-02 (A-4) | A | Phase 8 |
| QUERY-01 (A-5) | A | Phase 8 |
| UI-01 (B-1) | B | Phase 9 |
| TEST-03 (C-1) | C | Phase 10 |

**Coverage:** 7/7 requirements mapped ✓
**Orphans:** none
**Duplicates:** none
