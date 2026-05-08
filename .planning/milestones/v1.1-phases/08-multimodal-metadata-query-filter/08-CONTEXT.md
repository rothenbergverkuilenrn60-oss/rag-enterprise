# Phase 8: Multimodal Metadata + Query Filter - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver section-aware retrieval for the existing pgvector store:

1. **META-01** — Chunker enriches `content_with_header` with the **leaf section heading text** (e.g., `"3.10 定义的透光面\n\n<body>"`) and adds two structured metadata fields `section_id` (`"3.10"`) and `section_title` (`"定义的透光面"`). Page numbers and bare section IDs never enter the embedded text.
2. **META-02** — `PgVectorStore.search(filters: dict | None)` runs a JSONB-filtered HNSW search with `iterative_scan='relaxed_order'` + `ef_search=200` (configurable) over a B-tree expression index on `(metadata->>'page_number')` and `(metadata->>'section_id')`. Unfiltered queries unchanged in behavior and recall.
3. **QUERY-01** — Regex-first query-side extractor turns `"第63页灯具的发光面"` into `filters={"page_number": 63}` + stripped semantic query `"灯具的发光面"`, propagating end-to-end (NLU → pipeline → retriever → vector_store).
4. Image-caption chunks (Phase 4 image flow) carry `page_number` + `section_id` and the vision LLM call receives the surrounding section heading as prompt context.
5. Legacy chunks (ingested before v1.1, no section context) load and search with empty-string section fields and do not error.

**Out of scope (defer):** LLM-based query extractor (regex-only in v1.1), English query patterns (`"page 63"`, `"Section 3.10"`), proactive backfill of legacy chunks, multi-key filter intersection semantics beyond what acceptance tests require.

</domain>

<decisions>
## Implementation Decisions

### OCR-document section heading source
- **D-01:** Reuse `chunker._classify_line` regex over `OcrEngine.body_text` to detect headings. **No Phase 7 contract change.** PP-StructureV3 wrapper continues to return `body_text` only (block-level types stay un-surfaced).
  - **Why:** `_classify_line` already recognizes `\d+(\.\d+)*` numbered headings (the dominant pattern in Chinese GB-style standards). Extending `OcrEngine` to emit blocks would re-open Phase 7's verified contract and require an OCR e2e re-run for marginal precision gain on the current corpus.
  - **Edge case the planner must handle:** `_run_sync` prefixes each page with `"[第N页·OCR]\n"` before concatenating. The chunker's section walker MUST treat that prefix as a page-boundary marker, not as a heading line.

### content_with_header shape
- **D-02:** Leaf-only heading: `f"{section_id} {section_title}\n\n{body}"` → e.g., `"3.10 定义的透光面\n\n{body}"`. Parent chain (`"3 总则 > 3.10 定义的透光面"`) is **not** prepended even though `structure_aware_split` produces `parent_heading`.
  - **Why:** Matches REQ A-3 acceptance #1 sample byte-for-byte; minimizes embedding noise; keeps recall scoped to the exact section a chunk lives in.

### Query-side extractor language scope
- **D-03:** v1.1 strictly Chinese-only — patterns frozen to those in REQ A-5:
  - `第\s*(\d+)\s*页` → `{page_number: N}`
  - `(\d+(?:\.\d+)+)\s*节?` → `{section_id: "<value>"}`
  - `(\d+(?:\.\d+)+)条款` → `{section_id: "<value>"}`
  - **Why:** Current corpus is exclusively Chinese GB national standards. English patterns are deferred to v1.2 — see Deferred Ideas.

### Image-caption section context
- **D-04:** Two-pronged enrichment:
  1. **Vision prompt injection** — `LLMClient.chat_with_vision(...)` call must be extended (or wrapped) to receive `section_title` + `page_number`. Caption text reads `"Figure on page 63 in section 3.10 — …"` rather than caption-only.
  2. **content_with_header wrap** — `image_chunk.content_with_header = f"{section_id} {section_title}\n\n{caption}"` (matches D-02 shape so text and image chunks embed identically).
  - **Why:** REQ A-3 acceptance #3 requires caption text itself to carry section context (cannot be done by post-hoc string concat alone). Wrapping `content_with_header` keeps the embedded text format consistent with text chunks for downstream re-ranking.
  - **Effect on legacy images:** New behavior only applies to fresh ingests. Pre-v1.1 image chunks keep `content_with_header=caption` and empty `section_*` fields (covered by REQ A-3 acceptance #4 + Phase 8 SC #5).

### Claude's Discretion (planner / executor decide HOW)
- Whether the section walker is a pre-pass building `(start_offset, section_id, section_title)` ranges then assigning by overlap, or a per-block streaming walk during chunking.
- B-tree expression index DDL exact form (`CREATE INDEX … ((metadata->>'page_number')::int)` vs text comparison) — choose what `EXPLAIN ANALYZE` shows index-using under the existing query patterns.
- `ChunkMetadata` field ordering / docstring text.
- Where the regex extractor lives (`services/nlu/nlu_service.py` extension vs new `services/nlu/filter_extractor.py`) — REQ A-5 leaves both open.
- Test fixture choice for the recall-baseline test (REQ A-4 acceptance #4) — pick a stable `(page_number, query)` pair from `data/raw/GB4785-2019.pdf` already validated in Phase 7 e2e.
- Filter zero-results UX (fall-back to unfiltered vs return empty + UI hint) — not in REQ acceptance criteria; defer to plan-phase.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 8 spec (LOCKED)
- `.planning/REQUIREMENTS.md` §"REQ A-3 (META-01)" — content_with_header format, ChunkMetadata new fields, image-caption acceptance criteria
- `.planning/REQUIREMENTS.md` §"REQ A-4 (META-02)" — filters dict signature, B-tree expression index, hnsw.iterative_scan='relaxed_order', ef_search=200, recall test
- `.planning/REQUIREMENTS.md` §"REQ A-5 (QUERY-01)" — regex priority list, strip-from-query rule, end-to-end propagation chain
- `.planning/ROADMAP.md` §"Phase 8" — 5 success criteria

### Phase 7 (upstream contract — DO NOT BREAK)
- `services/extractor/ocr_engine.py` — `OcrEngine.extract_pdf` returns `{body_text, tables, pages, title, engine, [extraction_errors]}`. `body_text` has `[第N页·OCR]\n…` page prefixes.
- `.planning/phases/07-ocr-engine-integration/07-02-SUMMARY.md` — OCR engine post-conditions, `_looks_garbled` heuristic, semaphore + tenacity wrapping (informs how the chunker should treat empty/garbled OCR output).

### Existing chunker code (REUSE, don't reinvent)
- `services/doc_processor/chunker.py:173` — `_classify_line` heuristic heading detector
- `services/doc_processor/chunker.py:190` — `structure_aware_split` already produces `StructureNode` with `heading` + `parent_heading`
- `services/doc_processor/chunker.py:301` — `structure_nodes_to_chunks` builds `Chunk` with `section`/`sub_section`/`content_with_header`
- `services/doc_processor/chunker.py:552` — `inject_metadata_header` (current header style, will be superseded by D-02 form for embedded text but kept for log/UI metadata header)
- `services/doc_processor/chunker.py:1157-1215` — image-caption flow (Phase 4); `chat_with_vision` call site for D-04 prompt injection

### Vector store + filter wiring
- `services/vectorizer/vector_store.py:38-43` — `BaseVectorStore.search(filters: dict | None)` ABC signature (already exists)
- `services/vectorizer/vector_store.py:104` — `PgVectorStore.create_collection` (extend with B-tree expression indexes here)
- `services/vectorizer/vector_store.py:207-212` — `PgVectorStore.search` (extend WHERE-clause + per-session GUCs here)

### Chunk + metadata model
- `utils/models.py:121-133` — current `ChunkMetadata` (add `section_id`, `section_title` here)

### NLU + pipeline
- `services/nlu/nlu_service.py` — host for the regex filter extractor (or new sibling `services/nlu/filter_extractor.py`)
- `services/pipeline.py` `_run_query` / `run_query` — propagation point: extracted filters must reach `retriever.retrieve_multi_query` then `vector_store.search(filters=…)`

### Project standards
- `CLAUDE.md` — Pydantic V2, mypy --strict, ruff, no bare `except`, no blocking I/O in async, adapters for external deps, tenacity retries, structured logging
- `.planning/PROJECT.md` §"Key Decisions" — 三层架构 utils/services/controllers, MODEL_DIR via env, asyncpg JSONB returns string (must `json.loads()`)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `chunker._classify_line` + `structure_aware_split` — already classify lines and build heading-aware structure nodes from raw text. The Phase 8 section walker is essentially a wrapper around these for OCR'd `body_text`, plus a new step that emits `section_id` (numeric prefix split off the heading) and `section_title` (heading text minus the numeric prefix).
- `BaseVectorStore.search(filters: dict | None)` already accepts the `filters` arg (Phase 1) — Phase 8 fills in the WHERE-clause body for `PgVectorStore`, adds the GUC session settings, and adds the expression indexes in `create_collection`.
- `LLMClient.chat_with_vision` — existing image-caption call site; D-04 extends it (added kwargs or context-prefix inside the prompt) without restructuring the chunker's image loop.

### Established Patterns
- `asyncpg` returns JSONB columns as `str` — must `json.loads()` (already proven in `vector_store.search` parsing fix from session prior). Filter WHERE-clauses must compare JSONB key extractions (`metadata->>'page_number'`), not parse-then-compare.
- `lru_cache(maxsize=1)` singleton + `asyncio.Semaphore` + `to_thread` (Phase 7 OCR pattern) — re-applies if the regex extractor ever needs heavy state, but for v1.1 a stateless `re.compile` module-level pattern suffices.
- Tenacity retry + `asyncio.wait_for` — Phase 8 work is pure CPU (regex, SQL); no new retry surface.

### Integration Points
- `services/doc_processor/chunker.py` `process()` (line 655) — main entry that produces chunks from `ExtractedContent`. Section walker hooks before chunking; new metadata fields fill at line 352–353 (text) and line 1196–1215 (image).
- `services/pipeline.py` query path — extracted filters must thread from NLU → retriever → vector_store. Existing `filters: dict | None` in `vector_store.search` is the merge point.
- `services/vectorizer/vector_store.py` `create_collection` — DDL append point for the two new B-tree expression indexes; idempotent `IF NOT EXISTS` pattern is already used.

</code_context>

<specifics>
## Specific Ideas

- Recall-baseline test fixture: REQ A-4 acceptance #4 wants a known `(page_number=63, query)` pair against `PgVectorStore`. `data/raw/GB4785-2019.pdf` page 63 §3.10 was already exercised in the Phase 7 end-to-end run; reuse that page+query as the regression anchor instead of inventing a new fixture.
- D-02's leaf-heading shape (`"3.10 定义的透光面\n\n<body>"`) is canonical for both text chunks and image-caption chunks (D-04). `services/extractor` page-prefix `"[第N页·OCR]"` is OCR-internal scaffolding and MUST be stripped before becoming part of `content_with_header`.
- Logical split inside Phase 8 (informs plan task graph): META-01 (chunker + image-caption) → META-02 (vector store filter + index) → QUERY-01 (regex extractor + propagation). META-02 must land before QUERY-01 wires to it (per REQUIREMENTS sequencing note).

</specifics>

<deferred>
## Deferred Ideas

- **English query patterns (`"page 63"`, `"Section 3.10"`, `"Clause 3.10"`)** — out of scope for v1.1 (corpus is Chinese-only). Re-open in v1.2 once any English language documents enter the corpus.
- **OCR engine block-level output** — extending `OcrEngine.extract_pdf` to emit a `blocks: list[{type, text, page}]` structure would let the chunker rely on PP-StructureV3's layout classifier directly instead of regex over `body_text`. Defer to v1.2 once a corpus example surfaces where the regex misclassifies (e.g., heading lines without numeric prefix).
- **Proactive legacy backfill** — REQ A-3 acceptance #4 explicitly requires "load and search without errors" with empty `section_*` fields, not re-OCR. A re-ingest job is straightforward but unnecessary in v1.1.
- **LLM-based filter extractor** — REQ A-5 acceptance #5 explicitly defers to v1.2.
- **Filter zero-results fallback UX** — if `filters={"page_number": 999}` returns 0, do we (a) return empty + UI hint, or (b) silently drop the filter? Out of REQ acceptance; revisit after v1.1 ships and we have user-facing telemetry.
- **Multi-key filter intersection semantics** — REQ acceptance covers single-key filters. Combined `{page_number: N, section_id: "X"}` is implicitly AND but not exercised by acceptance tests; planner may add a smoke test only.

</deferred>

---

*Phase: 08-multimodal-metadata-query-filter*
*Context gathered: 2026-05-08*
