# Phase 8: Multimodal Metadata + Query Filter — Research

**Researched:** 2026-05-08
**Domain:** pgvector JSONB-filtered HNSW search · GB-standard section heading detection · Chinese query filter extraction · asyncpg session GUC patterns
**Confidence:** HIGH (code verified via tooling; pgvector docs via official GitHub raw)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Reuse `chunker._classify_line` regex over `OcrEngine.body_text` to detect headings. No Phase 7 contract change. PP-StructureV3 wrapper continues to return `body_text` only. The chunker's section walker MUST treat `[第N页·OCR]\n` prefix as a page-boundary marker, not as a heading line.
- **D-02:** Leaf-only heading shape: `f"{section_id} {section_title}\n\n{body}"` — e.g., `"3.10 定义的透光面\n\n{body}"`. Parent chain NOT prepended.
- **D-03:** Chinese-only regex patterns frozen to REQ A-5: `第\s*(\d+)\s*页` → `{page_number: N}`; `(\d+(?:\.\d+)+)\s*节?` → `{section_id: "value"}`; `(\d+(?:\.\d+)+)条款` → `{section_id: "value"}`. No EN expansion in v1.1.
- **D-04:** Vision prompt injection — `LLMClient.chat_with_vision(...)` call receives `section_title` + `page_number`. `content_with_header = f"{section_id} {section_title}\n\n{caption}"`.

### Claude's Discretion

- Whether section walker is a pre-pass (offset-range → assign-by-overlap) or per-block streaming walk.
- B-tree expression index DDL exact form (`::int` vs text comparison).
- `ChunkMetadata` field ordering/docstring text.
- Where regex extractor lives (`nlu_service.py` extension vs new `filter_extractor.py`).
- Test fixture choice for recall-baseline test (REQ A-4 acceptance #4).
- Filter zero-results UX (fall-back vs return empty).

### Deferred Ideas (OUT OF SCOPE)

- English query patterns (`"page 63"`, `"Section 3.10"`, `"Clause 3.10"`) — v1.2
- OCR engine block-level output — v1.2
- Proactive legacy backfill — explicit non-goal in v1.1
- LLM-based filter extractor — v1.2
- Filter zero-results fallback UX — post-v1.1 telemetry
- Multi-key filter intersection semantics beyond acceptance tests
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| META-01 | Chunker enriches `content_with_header` with leaf section heading; adds `section_id` + `section_title` to `ChunkMetadata`. Page/section IDs NOT in embedded text. | Section walker design (§Architecture Patterns #1), `ChunkMetadata` extension (§Code Anchors), `content_with_header` mutation (§Architecture Patterns #2) |
| META-02 | `PgVectorStore.search(filters)` runs JSONB-filtered HNSW with `iterative_scan='relaxed_order'` + `ef_search=200` + B-tree expression index | pgvector 0.8.0 iterative_scan verified (§Standard Stack), WHERE clause recipe (§Architecture Patterns #3), index DDL (§Don't Hand-Roll) |
| QUERY-01 | Regex-first extractor turns `"第63页灯具的发光面"` → `filters={"page_number": 63}` + stripped semantic query. Propagates NLU → pipeline → retriever → vector_store. | Filter extractor design (§Architecture Patterns #4), propagation path (§Code Anchors), pipeline wiring already supports `req.filters` (§Code Anchors #pipeline) |
</phase_requirements>

---

## Summary

Phase 8 adds section-aware metadata to chunks at ingest time (META-01) and filtered HNSW search at query time (META-02 + QUERY-01). The three concerns touch three well-separated layers: the chunker, the vector store, and the NLU/pipeline. All three integration points already exist in the codebase — this phase fills in the missing implementations.

The most critical gap discovered in research is that `_classify_line` does NOT recognize GB national-standard numbered headings (`3.10 定义的透光面`). The existing patterns target Chinese HR-document structure (`第X章`, `第X条`). Phase 8 requires a new GB-heading regex (`^\d+(?:\.\d+)*\s+[Chinese text]`) to be added — either as an extension to `_CHAPTER_PATTERNS`/`_ARTICLE_PATTERNS` or as a separate pre-pass walker. The pre-pass approach (D-01 discretion) is recommended because it naturally produces `(offset, section_id, section_title)` ranges suitable for both text chunks and image chunks that reference `img.page_number`.

pgvector `iterative_scan` + `relaxed_order` was added in pgvector 0.8.0 (2024-10-30). Requirements pin `pgvector>=0.3.0` — the deployed version must be ≥ 0.8.0. The GUC is set transaction-locally with `SET LOCAL` before the SELECT inside the existing `conn.transaction()` block, matching the pattern already used for RLS (`set_config`).

**Primary recommendation:** Pre-pass GB section walker → assign to chunks by offset overlap; B-tree expression index on `(metadata->>'page_number')::int` + `(metadata->>'section_id')`; filter extractor as new `services/nlu/filter_extractor.py`; pipeline propagation via existing `req.filters` + `tf` merge path.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GB section heading detection | Chunker (doc_processor) | — | Text structure is a document-processing concern, not retrieval |
| `section_id`/`section_title` metadata population | Chunker (doc_processor) | utils/models | Chunker builds ChunkMetadata; models holds the schema |
| `content_with_header` mutation (D-02) | Chunker (doc_processor) | — | Embedded text is the chunker's output responsibility |
| Image-caption section context injection (D-04) | Chunker image loop | LLMClient.chat_with_vision | Chunker orchestrates; LLMClient is the transport |
| JSONB WHERE clause + session GUC | Vector store (services/vectorizer) | — | Backend implementation detail; caller passes only `filters: dict` |
| B-tree expression index DDL | Vector store `create_collection` | — | Schema is owned by the vector store |
| Query filter regex extraction | NLU service / filter_extractor | — | Pre-retrieval query understanding step |
| Filter propagation | Pipeline (`_run_query`) | Retriever | Pipeline already has `tf` merge; retriever passes through |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pgvector (PostgreSQL extension) | ≥ 0.8.0 | HNSW iterative_scan, filtered ANN | `iterative_scan` added 0.8.0 (2024-10-30) [VERIFIED: github.com/pgvector/pgvector CHANGELOG] |
| asyncpg | 0.30.0 (pinned in requirements.txt) | Async PostgreSQL driver | Already in use; `SET LOCAL` works within transaction |
| pgvector Python package | ≥ 0.3.0 (requirements.txt) | `register_vector()` codec for asyncpg pool | Already in use |
| Pydantic V2 | per project | `ChunkMetadata` model extension | Project standard |
| re (stdlib) | — | GB heading detection + query filter patterns | No external dep needed for regex-only extractor |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-asyncio | per project | Unit + integration tests | All new tests |
| pytest-cov | per project | Diff-coverage gate (REQ C-1) | Phase 10 gate, but new test files must comply |

### Version verification

`requirements.txt` pins: `asyncpg==0.30.0`, `pgvector>=0.3.0`. [VERIFIED: requirements.txt grep]

The PostgreSQL server extension version must be ≥ 0.8.0 for `SET hnsw.iterative_scan`. This is a **server-side** version, not the Python package version. The planner must include a Wave 0 check: `SELECT extversion FROM pg_extension WHERE extname='vector'`. If < 0.8.0, the `SET LOCAL hnsw.iterative_scan` will raise `ERROR: unrecognized configuration parameter`. [CITED: pgvector README — iterative_scan section]

---

## Architecture Patterns

### System Architecture Diagram

```
User query "第63页灯具的发光面"
         │
         ▼
┌─────────────────────────┐
│  filter_extractor.py    │  regex: 第\s*(\d+)\s*页
│  (NLU layer)            │  → filters={"page_number": 63}
│                         │  → semantic_query="灯具的发光面"
└────────┬────────────────┘
         │  filters dict + stripped query
         ▼
┌─────────────────────────┐
│  pipeline._run_query    │  merges req.filters into tf
│  (services/pipeline.py) │  passes tf → retriever
└────────┬────────────────┘
         │  filters={"page_number": 63}
         ▼
┌─────────────────────────┐
│  retriever.retrieve     │  embeds semantic_query
│  (services/retriever)   │  passes filters → vector_store.search
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  PgVectorStore.search   │  SET LOCAL hnsw.iterative_scan='relaxed_order'
│  (services/vectorizer)  │  SET LOCAL hnsw.ef_search=200
│                         │  WHERE (metadata->>'page_number')::int = $3
│                         │  ORDER BY embedding <=> $1
│                         │  LIMIT $2
└────────┬────────────────┘
         │  VectorSearchResult (top-3)
         ▼
     Ranked chunks (page 63, section 3.10 context)
```

**Ingest path (META-01):**

```
ExtractorService (OCR) → body_text with [第N页·OCR] markers
         │
         ▼
┌─────────────────────────┐
│  _build_gb_section_map  │  strips [第N页·OCR]\n, builds
│  (new pre-pass in       │  [(offset, page_num, section_id,
│   chunker.py)           │   section_title)] ranges
└────────┬────────────────┘
         │  section_ranges + page_ranges
         ▼
┌─────────────────────────┐
│  structure_aware_split  │  runs on CLEANED body_text
│  (existing)             │  produces StructureNode list
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  structure_nodes_to_    │  assigns section_id, section_title
│  chunks (modified)      │  per chunk offset (nearest-preceding
│                         │  heading anchor)
│                         │  content_with_header = D-02 form
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  image chunk loop       │  chat_with_vision with section context
│  (chunker.py:1157-1215) │  content_with_header = D-04 form
└─────────────────────────┘
```

### Recommended Project Structure

No new top-level directories needed. Files modified/added:

```
services/
├── doc_processor/
│   └── chunker.py              # extend: _GB_HEADING_RE, _build_gb_section_map(),
│                               #   _resolve_primary_strategy (detect GB structure),
│                               #   structure_nodes_to_chunks (section fields + D-02),
│                               #   image loop (D-04)
├── nlu/
│   ├── nlu_service.py          # (unchanged — filter extractor is separate)
│   └── filter_extractor.py     # NEW: extract_filters(query) -> (filters, stripped_query)
├── vectorizer/
│   └── vector_store.py         # extend: create_collection (B-tree indexes),
│                               #         search (GUC SET + WHERE clause)
utils/
└── models.py                   # extend: ChunkMetadata (section_id, section_title)
services/pipeline.py            # extend: pass extracted filters into tf merge
tests/
├── unit/
│   ├── test_chunker.py         # extend: section walker tests
│   └── test_filter_extractor.py  # NEW
└── integration/
    └── test_pgvector_filtered_recall.py  # NEW
```

### Pattern 1: GB Standard Section Pre-Pass Walker

**What:** Before calling `structure_aware_split`, run a single pass over the cleaned body_text to build a list of `(text_offset, section_id, section_title, page_number)` anchors. Then when assigning metadata to each `DocumentChunk`, find the nearest-preceding anchor for the chunk's content.

**When to use:** When `body_text` comes from OCR of GB/ISO-style numbered-section documents.

**GB heading regex (verified via Python testing in this session):**

```python
# Source: verified via python3 test in research session
import re

_OCR_PAGE_MARKER = re.compile(r'^\[第(\d+)页·OCR\]\n?', re.MULTILINE)
_GB_HEADING_RE = re.compile(
    r'^(\d+(?:\.\d+)*)\s+([一-鿿]\S.*?)\s*$',
    re.MULTILINE,
)

def _strip_ocr_markers_with_pages(body_text: str) -> tuple[str, dict[int, int]]:
    """Strip [第N页·OCR] markers; return (clean_text, {text_offset: page_number}).
    
    page_offset_map: maps text position (in cleaned text) to page number.
    Used to assign page_number to chunks by their content offset.
    """
    page_offset_map: dict[int, int] = {}
    clean_parts: list[str] = []
    clean_offset = 0

    for i, segment in enumerate(re.split(r'\[第(\d+)页·OCR\]\n?', body_text)):
        if i % 2 == 0:
            # Text segment
            clean_parts.append(segment)
            clean_offset += len(segment)
        else:
            # Page number
            page_offset_map[clean_offset] = int(segment)

    return ''.join(clean_parts), page_offset_map


def _build_gb_section_map(
    clean_text: str,
) -> list[tuple[int, str, str]]:
    """Build [(text_offset, section_id, section_title)] from GB-standard text."""
    result: list[tuple[int, str, str]] = []
    for m in _GB_HEADING_RE.finditer(clean_text):
        result.append((m.start(), m.group(1), m.group(2)))
    return result
```

**Assigning section_id to a chunk by its content offset:**

```python
def _nearest_section(
    content: str,
    full_clean_text: str,
    section_map: list[tuple[int, str, str]],
) -> tuple[str, str]:
    """Find (section_id, section_title) for a chunk by locating its content in clean_text."""
    offset = full_clean_text.find(content[:50])  # first 50 chars as anchor
    if offset < 0 or not section_map:
        return '', ''
    # Nearest-preceding heading
    best_section_id, best_title = '', ''
    for (heading_offset, sid, title) in section_map:
        if heading_offset <= offset:
            best_section_id, best_title = sid, title
        else:
            break
    return best_section_id, best_title
```

### Pattern 2: content_with_header Mutation (D-02)

**What:** Replace the existing `enriched = f"[{node.node_type}] {context_header}\n\n{sub_text}"` in `structure_nodes_to_chunks` with the D-02 form. Do NOT remove `inject_metadata_header` — it is used for log/UI purposes, not for embedding.

**Where:** `chunker.py:342` (inside `structure_nodes_to_chunks`)

```python
# Source: D-02 locked decision (CONTEXT.md), verified against REQ A-3 acceptance #1
# Before (current):
enriched = f"[{node.node_type}] {context_header}\n\n{sub_text}"

# After (Phase 8):
if section_id and section_title:
    enriched = f"{section_id} {section_title}\n\n{sub_text}"
else:
    enriched = f"{context_header}\n\n{sub_text}" if context_header else sub_text
```

`page_number` and `section_id` (numeric) are stored ONLY in `ChunkMetadata`, never in `enriched`.

### Pattern 3: PgVectorStore Filtered Search + Session GUC

**What:** Before the vector search SELECT, set `hnsw.iterative_scan` and `hnsw.ef_search` as session-local GUCs inside the existing transaction. Add parameterized WHERE clause for filters.

**When to use:** When `filters` is non-None and non-empty (after stripping `page_number=0`).

```python
# Source: pgvector README (raw.githubusercontent.com/pgvector/pgvector/master/README.md)
# asyncpg SET LOCAL pattern matches existing set_config pattern in vector_store.py

async def search(self, query_vector, top_k, tenant_id='', filters=None):
    pool = await self._get_pool()
    
    # Build WHERE clause — exclude page_number=0 (unknown)
    effective_filters = {
        k: v for k, v in (filters or {}).items()
        if not (k == 'page_number' and v == 0)
    }
    
    where_clause, filter_params = _build_filter_where(effective_filters, start_param=3)
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, true)", tenant_id
            )
            if effective_filters:
                # SET LOCAL: scoped to this transaction
                ef_search = getattr(settings, 'pgvector_ef_search_filtered', 200)
                await conn.execute(
                    f"SET LOCAL hnsw.iterative_scan = 'relaxed_order'"
                )
                await conn.execute(
                    f"SET LOCAL hnsw.ef_search = {int(ef_search)}"
                )
            rows = await conn.fetch(
                f"""
                SELECT chunk_id, doc_id, content, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM {self._table}
                {where_clause}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                query_vector,
                top_k,
                *filter_params,
            )
    ...
```

**`_build_filter_where` helper:**

```python
def _build_filter_where(filters: dict, start_param: int = 3) -> tuple[str, list]:
    """Build parameterized WHERE clause for JSONB metadata filters.
    
    Returns (where_sql, param_list). start_param is the $N index for first filter param.
    ($1=query_vector, $2=top_k are callers' responsibility.)
    """
    if not filters:
        return '', []
    clauses: list[str] = []
    params: list = []
    n = start_param
    for key, value in filters.items():
        if isinstance(value, int):
            clauses.append(f"(metadata->>{key!r})::int = ${n}")
        elif isinstance(value, str):
            clauses.append(f"metadata->>{key!r} = ${n}")
        else:
            continue  # unknown type — skip safely
        params.append(value)
        n += 1
    if not clauses:
        return '', []
    return 'WHERE ' + ' AND '.join(clauses), params
```

### Pattern 4: Query Filter Regex Extractor (QUERY-01)

**What:** A module-level function that extracts filters from a Chinese query and returns stripped semantic query.

**Where:** New file `services/nlu/filter_extractor.py`

**Design (verified regex behavior via Python testing in this session):**

```python
# Source: REQ A-5 (REQUIREMENTS.md) + verified via python3 test
import re
from dataclasses import dataclass, field

_PAGE_RE    = re.compile(r'第\s*(\d+)\s*页')
_SECTION_RE = re.compile(r'(\d+(?:\.\d+)+)\s*节?')
_CLAUSE_RE  = re.compile(r'(\d+(?:\.\d+)+)条款')


@dataclass
class FilterExtractionResult:
    filters:       dict[str, int | str] = field(default_factory=dict)
    semantic_query: str = ''


def extract_filters(query: str) -> FilterExtractionResult:
    """Regex-first filter extraction (Chinese-only, v1.1).
    
    Priority order: page > section (clause variant) > section (generic).
    Extracted tokens are stripped from semantic_query before embedding.
    """
    filters: dict[str, int | str] = {}
    stripped = query

    # 1. Page number: 第N页 (highest priority)
    m = _PAGE_RE.search(stripped)
    if m:
        filters['page_number'] = int(m.group(1))
        stripped = _PAGE_RE.sub('', stripped, count=1).strip()

    # 2. Section (clause form): N.M条款
    m = _CLAUSE_RE.search(stripped)
    if m:
        filters['section_id'] = m.group(1)
        # Strip "N.M条款" — sub the matched text, not just the section_id
        stripped = stripped[:m.start()] + stripped[m.end():].strip()
        stripped = stripped.strip()
    else:
        # 3. Section (generic form): N.M节 or N.M (bare)
        m = _SECTION_RE.search(stripped)
        if m:
            filters['section_id'] = m.group(1)
            stripped = _SECTION_RE.sub('', stripped, count=1).strip()

    # Guard: if stripping left an empty semantic query, keep original
    if not stripped:
        stripped = query

    return FilterExtractionResult(filters=filters, semantic_query=stripped)
```

**Integration point in pipeline:** Before the existing NLU analysis in `_run_query`, call `extract_filters(req.query)` and merge extracted filters into `tf`:

```python
# services/pipeline.py _run_query — after NLU analysis, before retrieval
from services.nlu.filter_extractor import extract_filters

extraction = extract_filters(req.query)
effective_query = extraction.semantic_query  # stripped of filter tokens

# Merge into tenant filter
tf = self._tenant_svc.get_tenant_filter(tenant_id)
if req.filters:
    tf = {**(tf or {}), **req.filters}
if extraction.filters:
    tf = {**(tf or {}), **extraction.filters}
```

The `nlu.rewritten_queries` should embed `effective_query`, not `req.query`. This requires threading `effective_query` into the NLU quad-query builder or calling NLU with `effective_query` instead of `req.query`.

### Anti-Patterns to Avoid

- **Putting page number or section_id in embedded text:** Numeric identifiers pollute the embedding space. They belong ONLY in `ChunkMetadata` and the JSONB `metadata` column. REQ A-3 acceptance #1 is byte-specific.
- **SET (non-LOCAL) for GUCs:** `SET hnsw.iterative_scan` without `LOCAL` persists for the connection lifetime and will affect subsequent queries on pooled connections. Must use `SET LOCAL` inside transaction.
- **Calling `_classify_line` for GB section detection without adding the `_GB_HEADING_RE` pattern:** Existing `_classify_line` does NOT match `3.10 定义的透光面` (verified by Python testing). Calling it unmodified will miss all GB-standard headings.
- **Using `@>` JSONB containment for numeric filter:** `metadata @> '{"page_number": 63}'::jsonb` works but is slower than `(metadata->>'page_number')::int = 63` with a B-tree expression index. Use the expression form.
- **asyncpg `SET` outside transaction:** asyncpg connections are not transaction-isolated by default for GUCs. Must be inside `async with conn.transaction()`.
- **`_resolve_primary_strategy` returning "recursive" for OCR GB docs:** The auto-resolver checks `第X章|第X条` which never appear in GB numbered-section standards. The planner must address this: either extend the heuristic or always use "structure" strategy when `[第N页·OCR]` markers are present.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HNSW filtered recall without empty results | Custom pre-filter / post-filter logic | pgvector 0.8.0 `hnsw.iterative_scan='relaxed_order'` | pgvector handles expansion loop; hand-rolled post-filter re-runs the query at high ef_search which is slower |
| JSONB index for numeric metadata | Full JSONB GIN index | B-tree expression index on `(metadata->>'page_number')::int` | GIN is for containment queries; B-tree expression index is used by `ORDER BY embedding <=> $1 WHERE expr` planner |
| Page number tracking across OCR pages | Re-running OCR per-page with custom parser | `[第N页·OCR]` prefix already injected by `_run_sync` at `ocr_engine.py:197` | The page numbering is already done; just split on the marker |

**Key insight:** pgvector's iterative scan is the correct solution for filtered ANN. Without it, any filtered query on a sparse key (e.g., page_number=63 matching only ~5% of chunks) will return empty results at default `ef_search=40`.

---

## Runtime State Inventory

> This is NOT a rename/refactor/migration phase. Chunks already ingested do NOT need backfill (REQ A-3 acceptance #4: legacy chunks load/search with empty section fields). No runtime state migration required.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Existing pgvector chunks have no `section_id`/`section_title` in JSONB metadata | None — empty-string default handles legacy gracefully |
| Live service config | No config-side strings renamed | None |
| OS-registered state | None | None |
| Secrets/env vars | `pgvector_ef_search_filtered` is a new settings key | Add to `config/settings.py` with default 200 |
| Build artifacts | None | None |

**JSONB missing key behavior:** `metadata->>'section_id'` returns `NULL` (not error) when the key is absent from the JSONB object. A WHERE clause `metadata->>'section_id' = 'X'` will NOT match NULL rows, which is the correct behavior — legacy chunks without section_id simply won't appear in section-filtered results. [ASSUMED — standard PostgreSQL NULL semantics, not specifically tested]

---

## Common Pitfalls

### Pitfall 1: `_classify_line` Does Not Detect GB-Standard Numbered Sections

**What goes wrong:** Running `structure_aware_split(body_text)` on OCR'd GB standard text returns all content as `paragraph` nodes with no heading structure. `section_id`/`section_title` will all be empty string.

**Why it happens:** `_CHAPTER_PATTERNS` matches `第X章` (Chinese ordinal chapters); `_ARTICLE_PATTERNS[1]` matches `^\d+[\.、]\s*[一-鿿]` (digit + dot + immediate Chinese char). GB section `3.10 定义的透光面` fails the article pattern because `3.10` has a digit after the dot, not a Chinese character. [VERIFIED: python3 test in research session]

**How to avoid:** Add `_GB_HEADING_RE = re.compile(r'^(\d+(?:\.\d+)*)\s+([一-鿿]\S.*?)\s*$', re.MULTILINE)` as a pre-pass before structure splitting. The pre-pass builds the section map; `structure_aware_split` handles body splitting.

**Warning signs:** All chunks have empty `section_id` + `section_title` after ingest of GB PDF.

### Pitfall 2: `_resolve_primary_strategy` Selects "recursive" for GB Docs

**What goes wrong:** In `auto` mode, the strategy resolver checks `re.search(r"第[一二三四五六七八九十百零\d]+[章条]", sample)`. GB standard docs never contain `第X章`. The resolver returns `"recursive"`, and recursive splitting ignores all heading structure. [VERIFIED: `_resolve_primary_strategy` code at chunker.py:762]

**How to avoid:** Extend the heuristic to also detect `[第N页·OCR]` markers OR numbered GB sections as evidence of structure. Alternative: when `[第N页·OCR]` is detected in `body_text`, force strategy to `"structure"`.

**Warning signs:** Phase 8 unit test for GB section detection passes, but integration test shows all chunks have `section_id=""`.

### Pitfall 3: pgvector Server Extension Version < 0.8.0

**What goes wrong:** `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` raises `ERROR: unrecognized configuration parameter "hnsw.iterative_scan"`. The `PgVectorStore.search` call will fail entirely when filters are present.

**Why it happens:** `iterative_scan` was added in pgvector 0.8.0 (2024-10-30). Older server deployments (e.g., Docker base image with pgvector 0.7.x) do not support it. [VERIFIED: pgvector CHANGELOG raw.githubusercontent.com/pgvector/pgvector/master/CHANGELOG.md]

**How to avoid:** Wave 0 database check: `SELECT extversion FROM pg_extension WHERE extname='vector';` — assert result ≥ 0.8.0. Document required server version in deployment notes.

**Warning signs:** `PgVectorStore.search` raises asyncpg `InvalidParameterValueError` when `filters` is non-None.

### Pitfall 4: asyncpg JSONB Returned as String

**What goes wrong:** `r["metadata"]` from `conn.fetch()` is a `str` (JSON-encoded), not a Python `dict`. Direct attribute access like `r["metadata"]["page_number"]` raises `TypeError`.

**Why it happens:** asyncpg returns JSONB columns as strings unless a custom codec is registered. The vector store does NOT register a JSONB codec (only registers the vector codec).

**How to avoid:** The existing `vector_store.search` already handles this with `_json.loads(r["metadata"]) if isinstance(r["metadata"], str)`. The filter WHERE clause is SQL-side (`metadata->>'page_number'`) and does not involve Python dict access. [VERIFIED: vector_store.py:243 — pattern already in use]

**Warning signs:** `TypeError: string indices must be integers` in post-processing of search results.

### Pitfall 5: `SET LOCAL` vs `SET` for GUCs in Connection Pool

**What goes wrong:** Using `SET hnsw.iterative_scan = 'relaxed_order'` (no LOCAL) in a pooled connection persists the setting for the connection's lifetime. Subsequent unfiltered queries from other requests will unexpectedly use iterative scan, causing performance regression.

**How to avoid:** Always `SET LOCAL` inside `async with conn.transaction()`. The existing `set_config(..., true)` call already uses the transaction-local form. [CITED: pgvector README — session GUC docs + PostgreSQL SET LOCAL docs]

**Warning signs:** Unfiltered queries show unexpectedly high `ef_search` in `EXPLAIN ANALYZE`.

### Pitfall 6: Page Number Offset After OCR Marker Stripping

**What goes wrong:** After stripping `[第N页·OCR]\n` from body_text, the text offsets shift. If the section map is built from RAW body_text (with markers), the offsets will be wrong when searching the cleaned text for chunk positions.

**How to avoid:** Build the section map from CLEANED text only. Strip markers FIRST, build section map SECOND, split THIRD. The `_strip_ocr_markers_with_pages` helper in Pattern 1 returns a page_offset_map keyed by position in the cleaned text.

### Pitfall 7: `_SECTION_RE` Pattern Colliding with IP Addresses and Version Strings

**What goes wrong:** The pattern `(\d+(?:\.\d+)+)` matches `192.168.1.1`, `v3.10.1`, etc. In Chinese GB standards text this is unlikely but possible in cross-references.

**How to avoid:** Apply the section extractor regex only to user queries (not document text). In query context, version-string false positives are negligible for the current Chinese GB standard corpus. For safety, require the section id to be followed by `节` or preceded by section-indicator context. In v1.1 the frozen patterns are sufficient for the documented corpus. [ASSUMED — no corpus analysis tool available]

---

## Code Examples

### B-tree Expression Index DDL

```sql
-- Source: pgvector README (filtering section) + PostgreSQL B-tree expression index docs
-- Add to PgVectorStore.create_collection() inside the idempotent IF NOT EXISTS block

CREATE INDEX IF NOT EXISTS {table}_page_idx
    ON {table} USING btree ((metadata->>'page_number')::int)
    WHERE metadata->>'page_number' IS NOT NULL;

CREATE INDEX IF NOT EXISTS {table}_section_idx
    ON {table} USING btree ((metadata->>'section_id'))
    WHERE metadata->>'section_id' IS NOT NULL;
```

Note: The `::int` cast on `page_number` enables integer comparison (e.g., `= 63`) and range queries (`> 60`). The `section_id` remains as text for exact-match equality. Partial index `WHERE ... IS NOT NULL` avoids index entries for legacy chunks that lack these fields.

### New settings.py field

```python
# config/settings.py — add alongside top_k_dense/top_k_sparse
pgvector_ef_search_filtered: int = 200  # hnsw.ef_search for filtered queries (REQ A-4)
```

### ChunkMetadata extension (utils/models.py)

```python
# Add to ChunkMetadata after sub_section field
section_id:    str = ""   # GB standard section number, e.g. "3.10"
section_title: str = ""   # Section heading text, e.g. "定义的透光面"
```

### Image chunk D-04 content_with_header

```python
# chunker.py image loop (around line 1196-1215) — after caption is generated
section_id    = getattr(img, 'section_id', '')    # set by pre-pass walker
section_title = getattr(img, 'section_title', '')

# Vision prompt injection (D-04 part 1)
context_hint = ''
if section_title and img.page_number:
    context_hint = f"图片位于第{img.page_number}页，所属章节：{section_id} {section_title}。"

caption = await llm_client.chat_with_vision(
    image_b64=image_b64,
    query=f"{context_hint}请描述这张图片的内容。",
    media_type=media_type,
    system=_IMAGE_CAPTION_SYSTEM,
)

# content_with_header (D-04 part 2 = D-02 shape)
if section_id and section_title:
    cwh = f"{section_id} {section_title}\n\n{caption}"
else:
    cwh = caption
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Post-filter: scan all HNSW candidates, apply WHERE | Iterative scan: expand candidate set until WHERE satisfied | pgvector 0.8.0 (2024-10-30) | Filtered queries no longer return empty results for sparse filters |
| Manual ef_search tuning for filters | `hnsw.iterative_scan='relaxed_order'` + `hnsw.max_scan_tuples` | pgvector 0.8.0 | Automatic expansion; ef_search still speeds convergence |
| GIN JSONB index for metadata filtering | B-tree expression index on extracted key | Standard PostgreSQL | B-tree supports equality + range; GIN supports containment — wrong tool |

**Deprecated/outdated:**
- `metadata @> '{"page_number": 63}'::jsonb` with GIN: works but slower than expression B-tree for equality queries
- `hnsw.ef_search = 400` workaround: was the pre-0.8.0 band-aid for sparse filter recall. Now superseded by iterative_scan.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | JSONB `metadata->>'section_id'` returns NULL (not error) for rows that lack the key, causing section-filtered queries to simply exclude legacy chunks | Runtime State Inventory | If NULL causes errors in WHERE, legacy search breaks — verify with `SELECT metadata->>'section_id' FROM table WHERE section_id IS NOT NULL LIMIT 1` |
| A2 | `SET LOCAL` inside asyncpg `conn.transaction()` correctly scopes GUC changes to the transaction | Architecture Patterns #3 | If SET LOCAL persists beyond transaction, pooled connections will have incorrect ef_search — test explicitly |
| A3 | GB standard documents do NOT contain `第X章` or `第X条` style headings (only `N.M heading` numbered sections) | Common Pitfalls #2 | If some GB docs mix styles, the `_resolve_primary_strategy` fix may be over-broad |
| A4 | `_SECTION_RE` false-positive rate on Chinese GB standard user queries is negligible (version strings, IP addresses not common in queries) | Architecture Patterns #4 | If false positives occur, they cause wrong section filters — monitor via query logs post-v1.1 |
| A5 | `chat_with_vision` accepts an extended `query` string that includes the section context prefix without requiring a new API parameter | Code Examples (image chunk) | If the method signature rejects longer queries, D-04 implementation requires a different injection point |

---

## Open Questions

1. **pgvector server version on deployment target**
   - What we know: `requirements.txt` pins `pgvector>=0.3.0` (Python package, not server extension). `iterative_scan` needs server ≥ 0.8.0.
   - What's unclear: The actual PostgreSQL + pgvector server version in the Docker container.
   - Recommendation: Add Wave 0 task: `SELECT extversion FROM pg_extension WHERE extname='vector'` — assert ≥ 0.8.0. If < 0.8.0, add `apt-get install postgresql-16-pgvector` to Dockerfile.

2. **Empty semantic query after full filter strip**
   - What we know: `"3.10节"` with `_SECTION_RE.sub('', ...)` leaves empty string.
   - What's unclear: Should a filter-only query (no semantic content) fallback to unfiltered or use `*` (return all page 3.10 chunks ranked by embedding against zero-vector)?
   - Recommendation: Guard in `extract_filters`: if `stripped.strip() == ''`, set `semantic_query = query` (use original for embedding but still apply filter). This is a safe default.

3. **`_resolve_primary_strategy` and GB-standard auto-detect**
   - What we know: The auto-resolver misclassifies GB docs as "recursive". The section walker pre-pass is external to `structure_aware_split`, so the strategy can be "recursive" for body splitting but still apply section metadata via the pre-pass.
   - What's unclear: Whether the chunker's primary strategy affects the `content` text quality enough to matter, or whether the pre-pass section assignment is sufficient regardless of split strategy.
   - Recommendation: Force strategy to `"structure"` when OCR markers are detected in `body_text` (inside `_resolve_primary_strategy`). This also ensures consistent chunk boundaries near heading lines.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL + pgvector ≥ 0.8.0 (server) | META-02 (iterative_scan) | Unknown — psql not reachable in research | Must verify in Wave 0 | Upgrade pgvector server to 0.8.0 |
| asyncpg 0.30.0 | vector_store.py | Pinned in requirements.txt | 0.30.0 | — |
| pgvector Python ≥ 0.3.0 | register_vector() | Pinned in requirements.txt | ≥ 0.3.0 | — |
| data/raw/GB4785-2019.pdf | Integration recall test | Exists (used by Phase 7 e2e test) | — | — |

**Missing dependencies with no fallback:**
- pgvector server ≥ 0.8.0: if server is older, `hnsw.iterative_scan` will error. Must be resolved in Wave 0.

**Missing dependencies with fallback:**
- None identified.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode=auto) |
| Config file | `pytest.ini` (project root) |
| Quick run command | `pytest tests/unit/test_chunker.py tests/unit/test_filter_extractor.py -x` |
| Full suite command | `pytest tests/ -m "not integration" -x` |
| Integration command | `pytest tests/integration/test_pgvector_filtered_recall.py -m integration` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| META-01 SC#1 | `content_with_header = "3.10 定义的透光面\n\n{body}"` | unit | `pytest tests/unit/test_chunker.py::test_section_walker_gb_heading -x` | ❌ Wave 0 |
| META-01 SC#1 | `metadata.section_id = "3.10"`, `metadata.section_title = "定义的透光面"` | unit | `pytest tests/unit/test_chunker.py::test_section_metadata_fields -x` | ❌ Wave 0 |
| META-01 SC#1 | page_number NOT in `content_with_header` | unit | `pytest tests/unit/test_chunker.py::test_no_page_in_embedded_text -x` | ❌ Wave 0 |
| META-01 SC#4 | Legacy chunks (no section fields) load and search without error | unit | `pytest tests/unit/test_chunker.py::test_legacy_chunk_backward_compat -x` | ❌ Wave 0 |
| META-01 SC#4 | Image chunks carry page_number + section_id | unit | `pytest tests/unit/test_chunker.py::test_image_chunk_section_context -x` | ❌ Wave 0 |
| META-02 SC#2 | `search(filters={"page_number": 63})` returns matching chunk in top-3 | integration | `pytest tests/integration/test_pgvector_filtered_recall.py::test_filtered_recall_page -m integration` | ❌ Wave 0 |
| META-02 SC#2 | Unfiltered query unchanged in recall | integration | `pytest tests/integration/test_pgvector_filtered_recall.py::test_unfiltered_recall_unchanged -m integration` | ❌ Wave 0 |
| META-02 SC#5 | Legacy chunks (empty section fields) search without error | integration | `pytest tests/integration/test_pgvector_filtered_recall.py::test_legacy_chunks_searchable -m integration` | ❌ Wave 0 |
| QUERY-01 SC#3 | `"第63页灯具的发光面"` → `filters={"page_number": 63}` + `semantic_query="灯具的发光面"` | unit | `pytest tests/unit/test_filter_extractor.py::test_page_extraction -x` | ❌ Wave 0 |
| QUERY-01 SC#3 | `"3.10节中的…"` → `filters={"section_id": "3.10"}` | unit | `pytest tests/unit/test_filter_extractor.py::test_section_extraction -x` | ❌ Wave 0 |
| QUERY-01 SC#3 | No filter: `"灯具的发光面"` → `filters={}` | unit | `pytest tests/unit/test_filter_extractor.py::test_no_filter_passthrough -x` | ❌ Wave 0 |
| QUERY-01 SC#3 | Filters propagate end-to-end to `vector_store.search(filters=...)` | integration | part of `test_pgvector_filtered_recall.py` e2e path | ❌ Wave 0 |

### Recall Test Design (REQ A-4 acceptance #4)

The recall baseline test follows the existing pattern in `test_pgvector_recall.py`:

1. Insert ≥ 1 chunk with `metadata.page_number=63` and known content (`"3.10 定义的透光面 …"` from GB4785-2019).
2. Embed `"灯具的发光面"` (stripped query) via the embedder.
3. Call `store.search(query_vector, top_k=3, filters={"page_number": 63})`.
4. Assert: target chunk appears in top-3 results.
5. Call `store.search(query_vector, top_k=3, filters=None)` — assert recall is not lower.

**Tolerance for "unchanged recall":** The unfiltered baseline should return the same or more relevant chunks. A simple assertion: the target chunk_id must appear in BOTH filtered AND unfiltered top-3 results (or filtered recall ≥ unfiltered recall for this specific query).

**Fixture:** Reuse `data/raw/GB4785-2019.pdf` page 63 §3.10 content (already validated in Phase 7 e2e). The integration test inserts real content from that page rather than synthetic random vectors.

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_chunker.py tests/unit/test_filter_extractor.py -x`
- **Per wave merge:** `pytest tests/ -m "not integration" -x`
- **Phase gate:** Full suite (including `-m integration` if PG available) green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_filter_extractor.py` — covers QUERY-01 (filter extraction + stripping)
- [ ] `tests/unit/test_chunker.py` — extend with GB section walker tests (META-01)
- [ ] `tests/integration/test_pgvector_filtered_recall.py` — covers META-02 + QUERY-01 end-to-end
- [ ] pgvector server version check — SQL: `SELECT extversion FROM pg_extension WHERE extname='vector'`
- [ ] `config/settings.py` — add `pgvector_ef_search_filtered: int = 200`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | yes (existing RLS) | `set_config('app.current_tenant', ...)` unchanged; new filter WHERE clauses must not bypass RLS |
| V5 Input Validation | yes | Filter values from regex extractor are typed (int or str); WHERE clause uses parameterized queries — no SQL injection surface |
| V6 Cryptography | no | — |

### Known Threat Patterns for Phase 8 Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Filter injection via crafted query: `"第63页; DROP TABLE"` | Tampering | asyncpg parameterized queries (`$N`) — never string-interpolate filter values into SQL |
| Cross-tenant data leak via section_id filter | Information Disclosure | RLS policy (`tenant_isolation`) enforced before WHERE clause; `set_config` is called BEFORE the filter SELECT within the same transaction |
| page_number=0 as bypass (always excluded from filter) | Elevation of Privilege | `page_number=0` is the "unknown" sentinel — strip it before building WHERE clause |

**Critical:** Filter values passed to `conn.fetch(..., *filter_params)` MUST be asyncpg parameters (`$N`), never f-string interpolated. The `_build_filter_where` helper above uses parameterized form for all values. The `key` (column name) is always a trusted constant from the extractor's output, not user-supplied text.

---

## Sources

### Primary (HIGH confidence)

- `pgvector/pgvector CHANGELOG.md` (raw.githubusercontent.com) — iterative_scan version, GUC syntax
- `pgvector/pgvector README.md` (raw.githubusercontent.com) — filtering, B-tree index, SET GUC, iterative scan modes
- `services/doc_processor/chunker.py` (local codebase) — `_classify_line`, `_CHAPTER_PATTERNS`, `_ARTICLE_PATTERNS`, `structure_aware_split`, `structure_nodes_to_chunks`, image loop
- `services/vectorizer/vector_store.py` (local codebase) — `PgVectorStore.search`, `create_collection`, asyncpg JSONB str pattern
- `services/nlu/nlu_service.py` (local codebase) — NLUService architecture, no existing filter extractor
- `services/pipeline.py` (local codebase) — `_run_query` filter merge via `tf`, verified `req.filters` exists
- `utils/models.py` (local codebase) — `ChunkMetadata` current fields, `GenerationRequest.filters`
- `tests/conftest.py`, `tests/integration/test_pgvector_recall.py` (local) — test patterns, pg_pool fixture
- `pytest.ini` (local) — asyncio_mode=auto, integration marker pattern
- Python `re` module — verified regex behavior for `_GB_HEADING_RE`, D-03 patterns, `[第N页·OCR]` splitting

### Secondary (MEDIUM confidence)

- PostgreSQL documentation (standard knowledge) — `SET LOCAL`, B-tree expression index, JSONB `->>'key'` extraction, NULL semantics for missing JSONB keys

### Tertiary (LOW confidence)

- None — all critical claims are verified against local codebase or official upstream sources.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — asyncpg/pgvector versions verified from requirements.txt; iterative_scan version from official CHANGELOG
- Architecture: HIGH — all code anchors verified by reading actual source; patterns tested via Python interpreter
- Pitfalls: HIGH — critical regex gap verified by running `_classify_line` against GB section heading samples; asyncpg JSONB handling verified from existing code
- Security: HIGH — parameterized query pattern already in use; RLS pattern unchanged

**Research date:** 2026-05-08
**Valid until:** 2026-08-08 (pgvector stable; no fast-moving changes expected)

---

## RESEARCH COMPLETE

**Phase:** 08 — Multimodal Metadata + Query Filter
**Confidence:** HIGH

### Key Findings

1. **Critical gap: `_classify_line` does not recognize GB numbered sections.** `_ARTICLE_PATTERNS[1]` matches `^\d+[\.、]\s*[Chinese char]` but GB headings like `3.10 定义的透光面` have a digit after the dot, not a Chinese char. A new `_GB_HEADING_RE = re.compile(r'^(\d+(?:\.\d+)*)\s+([一-鿿]\S.*?)\s*$', re.MULTILINE)` is required. [VERIFIED by Python testing]

2. **pgvector 0.8.0 `iterative_scan` is the correct solution** — added 2024-10-30. GUC: `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` inside a transaction. Requires server extension ≥ 0.8.0 (Python package version irrelevant). [VERIFIED via GitHub CHANGELOG]

3. **Full filter propagation path already exists:** `GenerationRequest.filters` → `pipeline._run_query` tf-merge → `retriever.retrieve` → `vector_store.search(filters=...)`. Phase 8 only needs to populate `req.filters` via the new `filter_extractor.py` and fill in the WHERE clause in `PgVectorStore.search`. [VERIFIED by reading pipeline.py and retriever.py]

4. **`_resolve_primary_strategy` selects "recursive" for GB docs** — auto-detect checks `第X章|第X条` only. Must be extended to detect `[第N页·OCR]` markers. [VERIFIED by reading resolver code]

5. **asyncpg JSONB string handling already in codebase** — `vector_store.py:243` uses `json.loads()` guard. Filter WHERE clauses operate SQL-side (`metadata->>'key'`), not Python-side. [VERIFIED by code reading]

### File Created

`.planning/phases/08-multimodal-metadata-query-filter/08-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Standard stack (pgvector 0.8.0, asyncpg 0.30.0) | HIGH | Official CHANGELOG + requirements.txt verified |
| Architecture (section walker, filter WHERE, query extractor) | HIGH | All code anchors read; regex patterns tested via Python |
| Pitfalls (classify_line gap, GUC scope, type coercion) | HIGH | Verified by running actual patterns against test input |
| Test design | HIGH | Existing test infrastructure (conftest, pg_pool, recall pattern) fully understood |

### Open Questions

- pgvector server extension version on deployment target (must be ≥ 0.8.0 for iterative_scan)
- Whether empty semantic query after full filter strip should use original query or a zero-vector placeholder

### Ready for Planning

Research complete. Planner can now create PLAN.md files.
