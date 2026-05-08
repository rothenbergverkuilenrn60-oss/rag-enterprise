# Phase 8: Multimodal Metadata + Query Filter - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 08-multimodal-metadata-query-filter
**Areas discussed:** OCR-document section heading source, content_with_header shape, English query patterns, Image-caption section context

---

## OCR-document section heading source

| Option | Description | Selected |
|--------|-------------|----------|
| (b) Reuse `_classify_line` regex over `body_text` | Zero Phase 7 contract change. Chunker calls `structure_aware_split` on OCR `body_text`. Existing regex covers `\d+(\.\d+)*` Chinese GB-style headings. Must preprocess `[第N页·OCR]` page markers to avoid false heading classification. Cost low; precision relies on regex coverage. | ✓ |
| (a) Extend `OcrEngine` output to emit blocks list (title/text/table) | PP-StructureV3 internally has layout classification; Phase 7 wrapper drops it. ~50 LOC + ocr_engine unit-test additions + Phase 7 e2e re-run. Highest precision (model layout). Touches verified Phase 7 module. | |
| (c) Hybrid — blocks-first, regex fallback | OCR engine emits blocks; chunker prefers blocks, falls back to regex when missing. Two code paths + two test paths. Phase 8 scope grows ~30%. Most robust but heaviest. | |

**User's choice:** (b)
**Notes:** Phase 7 contract stays frozen. Chunker must strip the `[第N页·OCR]` page-prefix line before feeding into `structure_aware_split` to prevent that marker from being misclassified as a heading.

---

## content_with_header shape

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Leaf only: `"3.10 定义的透光面\n\n{body}"` | Matches REQ A-3 acceptance #1 sample byte-for-byte. Minimal embedding noise. Reads only the leaf `heading` field from `StructureNode`, ignoring `parent_heading`. | ✓ |
| (b) Parent chain: `"3 总则 > 3.10 定义的透光面\n\n{body}"` | Reuses `structure_aware_split.parent_heading`. More embedded context, may improve recall on cross-section queries. Sample text in REQ would need re-statement as "contains heading text" rather than equality. | |

**User's choice:** (a)
**Notes:** Embedded text stays scoped to the leaf section. Parent context is recoverable from `section_id` numeric prefix (e.g., `"3.10"` → user can derive `"3"` is the parent if they need it) without polluting the embedding.

---

## English query patterns

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Chinese-only, v1.1 frozen | Patterns frozen to REQ A-5: `第N页` / `(\d+(?:\.\d+)+)\s*节?` / `(\d+(?:\.\d+)+)条款`. Zero extra surface. | ✓ |
| (b) Chinese + English in v1.1 | Add `page\s*(\d+)` (case-insensitive), `Section\s*(\d+(?:\.\d+)+)`, `Clause\s*(\d+(?:\.\d+)+)`. ~30 LOC + 5 unit tests. ~5 minute scope creep. | |
| (c) Defer English to v1.2 | Document in DEFERRED. Re-open when English documents enter the corpus. | |

**User's choice:** (a)
**Notes:** Logged in Deferred Ideas as "open in v1.2 once English-language docs enter the corpus" — equivalent outcome to (c).

---

## Image-caption section context

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Vision prompt injection + content_with_header wraps heading | `chat_with_vision` receives `section_title` + `page_number` so caption text reads `"Figure on page 63 in section 3.10 — …"`. Also `image_chunk.content_with_header = f"{section_id} {section_title}\n\n{caption}"`. Matches REQ A-3 acceptance #3. New behavior applies only to fresh ingests. | ✓ |
| (b) Append to caption only, no vision-prompt change | `content_with_header = f"章节：{heading}\n\n{caption}"`. Zero LLM-call change; works on legacy chunks via post-hoc concat. Caption text itself stays section-blind — diverges from REQ #3 literal text. | |
| (c) Both — prompt injection + content_with_header concat (superset of (a)) | Strict superset of (a). Effectively identical to (a) since content_with_header wrap is already part of (a). | |

**User's choice:** (a)
**Notes:** Treated as the baseline — (c) collapses to (a) in this codebase since (a) already wraps `content_with_header`. Legacy image chunks (pre-v1.1) keep `content_with_header=caption` and empty `section_*` fields per REQ A-3 acceptance #4.

---

## Claude's Discretion

- Section walker implementation strategy (pre-pass vs streaming walk during chunking) — planner decides
- Regex extractor lives in `services/nlu/nlu_service.py` extension vs new `services/nlu/filter_extractor.py` — REQ A-5 leaves both open
- B-tree expression index DDL exact form — pick what `EXPLAIN ANALYZE` shows index-using
- Filter zero-results UX — not in REQ acceptance, defer to plan-phase

## Deferred Ideas

- **English query patterns** — re-open in v1.2 once English documents enter the corpus
- **OCR engine block-level output** — extend `OcrEngine.extract_pdf` to emit blocks once a corpus example surfaces where regex misclassifies a heading
- **Proactive legacy backfill** — re-OCR / re-chunk all `data/raw` content; not required by REQ acceptance
- **LLM-based filter extractor** — explicitly deferred by REQ A-5 acceptance #5
- **Filter zero-results fallback UX** — revisit after v1.1 ships and we have user-facing telemetry
- **Multi-key filter intersection semantics** — beyond REQ acceptance; planner may add a smoke test only
