# Phase 8: Multimodal Metadata + Query Filter — Pattern Map

**Mapped:** 2026-05-08
**Files analyzed:** 6 (2 new, 4 modified)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/nlu/filter_extractor.py` | utility / regex extractor | request-response (stateless transform) | `services/nlu/nlu_service.py` (dataclass + module-level re.compile + function) | role-match |
| `tests/unit/test_filter_extractor.py` | unit test | — | `tests/unit/test_nlu_service.py` (class-based, import-inside-test, env guard) | exact |
| `services/doc_processor/chunker.py` | chunker pipeline stage | transform (text → structured chunks) | self (extend existing) | exact — read-only reference |
| `utils/models.py` | Pydantic V2 data model | — | self (extend `ChunkMetadata`) | exact — read-only reference |
| `services/vectorizer/vector_store.py` | async vector store (asyncpg) | CRUD + HNSW filtered search | self (extend `PgVectorStore.search` + `create_collection`) | exact — read-only reference |
| `services/pipeline.py` | pipeline orchestrator | request-response | self (extend `_run_query` filter merge block) | exact — read-only reference |

---

## Pattern Assignments

---

### `services/nlu/filter_extractor.py` (utility, request-response)

**Analog:** `services/nlu/nlu_service.py` — same NLU layer, same pattern of module-level `re.compile` patterns + `@dataclass` result type + pure-function entry point. No class needed (stateless).

**Imports pattern** — copy from `nlu_service.py` lines 12–23, strip LLM deps:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
```

**Dataclass result pattern** — mirrors `NLUResult` / `SubQuery` style in `nlu_service.py` lines 47–80:

```python
@dataclass
class FilterExtractionResult:
    filters:        dict[str, int | str] = field(default_factory=dict)
    semantic_query: str = ""
```

**Core regex pattern** — module-level compiled patterns (same idiom as `_CHAPTER_PATTERNS` / `_ARTICLE_PATTERNS` in `chunker.py` lines 157–170):

```python
_PAGE_RE    = re.compile(r'第\s*(\d+)\s*页')
_SECTION_RE = re.compile(r'(\d+(?:\.\d+)+)\s*节?')
_CLAUSE_RE  = re.compile(r'(\d+(?:\.\d+)+)条款')
```

**Entry-point function signature** — plain `def`, no async (pure regex, no I/O):

```python
def extract_filters(query: str) -> FilterExtractionResult:
    """Regex-first filter extraction (Chinese-only, v1.1).

    Priority: page > clause-section > generic-section.
    Extracted tokens stripped from semantic_query before embedding.
    Guard: if stripping empties the query, keep original as semantic_query.
    """
```

**Error handling:** No try/except needed — regex never raises. Guard against empty-after-strip:

```python
if not stripped.strip():
    stripped = query   # safe fallback: embed original, still apply filter
```

**Type hints:** All signatures `str -> FilterExtractionResult`. No `Any`. `dict[str, int | str]` for filters (mypy --strict compliant).

---

### `tests/unit/test_filter_extractor.py` (unit test)

**Analog:** `tests/unit/test_nlu_service.py` — env-guard at top, class-per-feature, import-inside-test, `monkeypatch` for singleton resets. For `filter_extractor` (no singleton), import directly.

**File header pattern** — copy from `test_nlu_service.py` lines 1–10:

```python
"""
tests/unit/test_filter_extractor.py
Unit tests for regex-first query filter extraction (QUERY-01 / REQ A-5).
"""
from __future__ import annotations

import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
```

**Test class structure** — one class per feature group (same as `TestNLURuleBased`):

```python
class TestExtractFilters:
    def test_page_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("第63页灯具的发光面")
        assert result.filters == {"page_number": 63}
        assert result.semantic_query == "灯具的发光面"

    def test_section_clause_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10条款中规定的内容")
        assert result.filters == {"section_id": "3.10"}
        assert "3.10" not in result.semantic_query

    def test_section_generic_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10节中的内容")
        assert result.filters == {"section_id": "3.10"}

    def test_no_filter_passthrough(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("灯具的发光面")
        assert result.filters == {}
        assert result.semantic_query == "灯具的发光面"

    def test_empty_after_strip_keeps_original(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10节")
        assert result.filters == {"section_id": "3.10"}
        assert result.semantic_query == "3.10节"   # guard: not ""
```

**Async tests:** None needed — `extract_filters` is sync. No `pytest.mark.asyncio`.

**No fixture needed** — input is plain strings.

---

### `services/doc_processor/chunker.py` (chunker, extend existing)

**Analog:** Self. All changes are additive to existing patterns.

#### New module-level constants — follow lines 157–170 pattern

```python
# Place after _LIST_PATTERNS block (line ~170)
# GB national-standard numbered-section heading
_GB_HEADING_RE = re.compile(
    r'^(\d+(?:\.\d+)*)\s+([一-鿿]\S.*?)\s*$',
    re.MULTILINE,
)
# OCR page-marker splitter (strips [第N页·OCR]\n)
_OCR_PAGE_MARKER_RE = re.compile(r'\[第(\d+)页·OCR\]\n?')
```

#### `_strip_ocr_markers_with_pages` — new module-level function

Pattern: same style as `_make_chunk_id` (line 47) — short, pure, typed, no class:

```python
def _strip_ocr_markers_with_pages(body_text: str) -> tuple[str, dict[int, int]]:
    """Strip [第N页·OCR] markers; return (clean_text, {clean_offset: page_number}).

    MUST be called BEFORE _build_gb_section_map so offsets are consistent.
    """
```

#### `_build_gb_section_map` — new module-level function

```python
def _build_gb_section_map(
    clean_text: str,
) -> list[tuple[int, str, str]]:
    """Return [(text_offset, section_id, section_title)] for GB-standard numbered headings."""
```

#### `_resolve_primary_strategy` extension — lines 762–776

Extend the `has_structure` heuristic to also detect OCR markers:

```python
# Existing (line 771-773):
has_structure = bool(
    re.search(r"第[一二三四五六七八九十百零\d]+[章条]", sample)
)
# Extend to:
has_structure = bool(
    re.search(r"第[一二三四五六七八九十百零\d]+[章条]", sample)
    or re.search(r'\[第\d+页·OCR\]', sample)          # GB OCR docs → force structure
    or _GB_HEADING_RE.search(sample)                   # numbered GB sections
)
```

#### `structure_nodes_to_chunks` extension — lines 342–367

`content_with_header` mutation (D-02) and `section_id`/`section_title` assignment.

Current pattern (line 342):
```python
enriched = f"[{node.node_type}] {context_header}\n\n{sub_text}"
```

New pattern (D-02):
```python
# section_id/section_title come from caller passing section_map to this function
# OR from a pre-pass assigning per-node before calling this function
if section_id and section_title:
    enriched = f"{section_id} {section_title}\n\n{sub_text}"
else:
    enriched = f"{context_header}\n\n{sub_text}" if context_header else sub_text
```

`ChunkMetadata` construction (lines 347–359): add two new fields after existing `sub_section`:
```python
meta = ChunkMetadata(
    ...                    # existing fields unchanged
    sub_section=node.heading,
    section_id=section_id,      # NEW: e.g. "3.10"
    section_title=section_title, # NEW: e.g. "定义的透光面"
    ...
)
```

#### Image-caption loop extension — lines 1168–1214 (D-04)

**Pattern:** Extend the existing `try/except` block around `chat_with_vision`. Add context-hint string before the `query=` kwarg. Add `content_with_header` mutation after caption is produced.

Follow existing error handling pattern exactly (`except (openai.APIError, httpx.HTTPError, anthropic.APIError)` — lines 1175–1184). No new exception types.

```python
# Before chat_with_vision call — resolve section context for this image
# (section_id/section_title assigned by pre-pass walker to img or via lookup)
_section_id    = getattr(img, 'section_id', '') or ''
_section_title = getattr(img, 'section_title', '') or ''
context_hint = ''
if _section_title and img.page_number:
    context_hint = f"图片位于第{img.page_number}页，所属章节：{_section_id} {_section_title}。"

caption: str = await llm_client.chat_with_vision(
    image_b64=image_b64,
    query=f"{context_hint}请描述这张图片的内容。",   # extended query, same kwarg
    media_type=media_type,
    system=_IMAGE_CAPTION_SYSTEM,
)

# ... existing empty-caption guard (lines 1186-1194) unchanged ...

# content_with_header — D-04 shape (D-02 consistent)
if _section_id and _section_title:
    cwh = f"{_section_id} {_section_title}\n\n{caption}"
else:
    cwh = caption

# ChunkMetadata construction (lines 1197-1208): add section_id/section_title
meta = ChunkMetadata(
    ...                   # existing fields
    page_number=img.page_number,
    section_id=_section_id,        # NEW
    section_title=_section_title,  # NEW
    ...
)
chunks.append(DocumentChunk(
    ...
    content_with_header=cwh,       # was: caption
    ...
))
```

---

### `utils/models.py` (Pydantic V2 model, extend `ChunkMetadata`)

**Analog:** Self — lines 125–146. Pydantic V2 `BaseModel` with typed defaults. All fields have default values (no required fields added — backwards-compatible).

**Add after `sub_section` field (line 132):**

```python
section_id:    str = ""   # GB standard section number, e.g. "3.10" (META-01)
section_title: str = ""   # Section heading text, e.g. "定义的透光面" (META-01)
```

**Pattern rules from existing model:**
- `str` fields use `= ""` default (not `Optional[str]`), per existing `source`, `section`, `sub_section` pattern
- Field ordering: `sub_section` → `section_id` → `section_title` → `page_number` (insert before `page_number`)
- No `Field(...)` needed — simple `= ""` default
- `int | None = None` for numeric nullable fields (matches `page_number` on line 133)

---

### `services/vectorizer/vector_store.py` (async vector store, extend `PgVectorStore`)

**Analog:** Self. All changes extend existing asyncpg + transaction + `SET LOCAL` patterns already established in `upsert` (lines 185–203) and `create_collection` (lines 104–155).

#### `create_collection` extension — append after existing DDL (lines 119–154)

Pattern: follow `CREATE INDEX IF NOT EXISTS` idiom (lines 119–130). Add inside the outer `async with pool.acquire() as conn:` block, after the HNSW index transaction:

```python
# B-tree expression indexes for filtered HNSW search (META-02)
# Partial index WHERE ... IS NOT NULL avoids entries for legacy chunks
await conn.execute(f"""
    CREATE INDEX IF NOT EXISTS {self._table}_page_idx
        ON {self._table} USING btree ((metadata->>'page_number')::int)
        WHERE metadata->>'page_number' IS NOT NULL;
    CREATE INDEX IF NOT EXISTS {self._table}_section_idx
        ON {self._table} USING btree ((metadata->>'section_id'))
        WHERE metadata->>'section_id' IS NOT NULL;
""")
```

#### `search` extension — lines 206–247

Pattern: mirror `upsert`'s `async with conn.transaction()` + `set_config` call (lines 186–203).
Add `SET LOCAL` GUCs inside the existing transaction block, before `conn.fetch`.
Add `_build_filter_where` helper as a module-level function (not a method).

**Current search body (lines 219–247):**
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, true)", tenant_id
        )
        rows = await conn.fetch(
            f"""
            SELECT chunk_id, doc_id, content, metadata,
                   1 - (embedding <=> $1::vector) AS score
            FROM {self._table}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            query_vector,
            top_k,
        )
```

**Extended pattern (add GUC block + WHERE clause):**
```python
# Build WHERE clause — strip page_number=0 sentinel
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
            ef_search = getattr(settings, 'pgvector_ef_search_filtered', 200)
            await conn.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
            await conn.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
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
# JSONB → dict parsing unchanged (line 243 pattern)
```

**`_build_filter_where` helper — module-level function, placed before `PgVectorStore` class:**

```python
def _build_filter_where(
    filters: dict[str, int | str],
    start_param: int = 3,
) -> tuple[str, list]:
    """Build parameterized WHERE clause for JSONB metadata filters.

    ($1=query_vector, $2=top_k are caller's params; filter params start at start_param.)
    Filter values MUST be asyncpg $N params — never f-string interpolated (SQL injection guard).
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
            continue  # skip unknown types silently (safe)
        params.append(value)
        n += 1
    if not clauses:
        return '', []
    return 'WHERE ' + ' AND '.join(clauses), params
```

**Error handling pattern:** `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(...))` already on `search` (line 206) — keep unchanged. No new exceptions to catch for GUC/WHERE clause (asyncpg will propagate `asyncpg.PostgresError` which bubbles to the retry wrapper).

---

### `services/pipeline.py` (pipeline orchestrator, extend `_run_query`)

**Analog:** Self — lines 262–344. Extend the existing filter-merge block at lines 315–317.

**Import to add** (after existing NLU import at line 42):
```python
from services.nlu.filter_extractor import extract_filters
```

**Injection point in `_run_query`** — insert AFTER `nlu = await self._nlu.analyze(...)` (line 291) and BEFORE the cache-key computation (line 307). This ensures `effective_query` is available for both caching and NLU rewrite propagation:

```python
# QUERY-01: extract regex filters and strip filter tokens from embed text
_extraction = extract_filters(req.query)
effective_query = _extraction.semantic_query   # stripped of "第N页" / "N.M节" tokens

# Existing tf-merge block (lines 315-317) — extend to also merge extracted filters:
tf = self._tenant_svc.get_tenant_filter(tenant_id)
if req.filters:
    tf = {**(tf or {}), **req.filters}
if _extraction.filters:
    tf = {**(tf or {}), **_extraction.filters}
```

**NLU call:** Pass `effective_query` (not `req.query`) to NLU so rewritten_queries embed the stripped text. This requires changing the `analyze(req.query, ...)` call to `analyze(effective_query, ...)`. The NLU service signature is unchanged — only the argument changes.

**Same pattern** applies to `AgentQueryPipeline._run_query` (lines 420–448) and `StreamQueryPipeline._run_query` (lines 560–650) — both have identical tf-merge blocks.

---

## Shared Patterns

### asyncpg transaction + `SET LOCAL` GUC
**Source:** `services/vectorizer/vector_store.py` lines 185–203 (upsert) and lines 219–236 (search)
**Apply to:** `PgVectorStore.search` GUC extension
```python
async with conn.transaction():
    await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
    # SET LOCAL scopes change to this transaction only
    await conn.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
```

### JSONB string → dict guard
**Source:** `services/vectorizer/vector_store.py` line 243
**Apply to:** All `conn.fetch` result processing in `vector_store.py`
```python
metadata=(_json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]) or {}
```

### Module-level `re.compile` constants
**Source:** `services/doc_processor/chunker.py` lines 157–170
**Apply to:** `filter_extractor.py` (all three pattern constants), `chunker.py` new GB/OCR patterns

### Pydantic V2 `BaseModel` optional fields with `= ""` default
**Source:** `utils/models.py` lines 125–146 (`ChunkMetadata`)
**Apply to:** New `section_id` / `section_title` fields in `ChunkMetadata`

### Narrow exception handling
**Source:** `services/doc_processor/chunker.py` lines 1175–1184
**Apply to:** Image-caption loop — keep `except (openai.APIError, httpx.HTTPError, anthropic.APIError)`, do not add bare `except` (ERR-01 hard requirement)

### `@retry` on async db methods
**Source:** `services/vectorizer/vector_store.py` lines 157, 206, 263
**Apply to:** `PgVectorStore.search` — existing decorator is kept; `_build_filter_where` is pure function, no retry needed

### `@dataclass` + `field(default_factory=...)` for result DTOs
**Source:** `services/nlu/nlu_service.py` lines 47–80
**Apply to:** `FilterExtractionResult` in `filter_extractor.py`

### Integration test: `pytestmark` + `skipif(not PG_AVAILABLE)`
**Source:** `tests/integration/test_pgvector_recall.py` lines 24–27
**Apply to:** `tests/integration/test_pgvector_filtered_recall.py`
```python
from tests.conftest import PG_AVAILABLE
pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="PostgreSQL + pgvector not available — skipping filtered recall test"
)
```

### Integration test: isolated table + teardown
**Source:** `tests/integration/test_pgvector_recall.py` lines 63–97
**Apply to:** `test_pgvector_filtered_recall.py` — override `store._table` to isolated name, `await store.create_collection()` in test body.

---

## No Analog Found

All files have analogs. No gaps.

---

## Critical Implementation Notes for Planner

1. **Offset consistency (Pitfall 6):** `_strip_ocr_markers_with_pages` MUST run before `_build_gb_section_map`. Both must operate on the same `clean_text` string so offsets align.

2. **`_GB_HEADING_RE` is required (Pitfall 1):** The existing `_classify_line` does NOT match `3.10 定义的透光面`. The `_GB_HEADING_RE` pre-pass is the only source of `section_id`/`section_title` for GB standard documents. Without it, all `section_id` fields will be `""`.

3. **`SET LOCAL` mandatory (Pitfall 5):** GUCs for `hnsw.iterative_scan` must use `SET LOCAL` inside `async with conn.transaction()`. The existing `set_config(..., true)` call already uses the same transaction-local pattern — follow it exactly.

4. **pgvector server ≥ 0.8.0 required (Pitfall 3):** Plan must include Wave 0 check `SELECT extversion FROM pg_extension WHERE extname='vector'`. The `iterative_scan` GUC raises `PostgresError` on older servers.

5. **Filter WHERE clause parameterized only (Security):** `key` in `_build_filter_where` is always a trusted constant from extractor output (never user-supplied text). Values are `$N` params — never f-string interpolated.

6. **`effective_query` threading:** After `extract_filters`, `effective_query` must be passed to `nlu.analyze()` and used in the retrieval embed call. `req.query` (original) is preserved for audit/logging only.

---

## Metadata

**Analog search scope:** `services/`, `utils/`, `tests/unit/`, `tests/integration/`, `tests/conftest.py`
**Files read:** `chunker.py`, `vector_store.py`, `nlu_service.py`, `pipeline.py`, `models.py`, `tests/unit/test_chunker.py`, `tests/unit/test_nlu_service.py`, `tests/unit/test_pgvector_store.py`, `tests/integration/test_pgvector_recall.py`, `tests/conftest.py`
**Pattern extraction date:** 2026-05-08
