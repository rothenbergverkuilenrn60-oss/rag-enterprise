# Phase 1: pgvector Foundation — Pattern Map

**Mapped:** 2026-04-21
**Files analyzed:** 5 files to modify + 2 test files to create
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/vectorizer/vector_store.py` | service | CRUD + request-response | Self (existing `PgVectorStore` + `QdrantVectorStore`) | exact |
| `config/settings.py` | config | — | Self (existing `Settings` class) | exact |
| `services/tenant/tenant_service.py` | service | request-response | `services/audit/audit_service.py` (async service pattern) | role-match |
| `services/pipeline.py` | service | request-response | Self (2 call-site renames) | exact |
| `requirements.txt` | config | — | Self | exact |
| `tests/unit/test_pgvector_store.py` | test | — | None (Wave 0 creation) | none |
| `tests/integration/test_pgvector_rls.py` | test | — | None (Wave 0 creation) | none |

---

## Pattern Assignments

### `services/vectorizer/vector_store.py` — Primary change target

**Analog:** Self — `QdrantVectorStore` (lines 54–233) and existing `PgVectorStore` (lines 239–372)

#### Imports pattern (lines 1–15)
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from config.settings import settings
from utils.models import DocumentChunk
from utils.logger import log_latency
```

#### ABC extension pattern — add abstract methods to `BaseVectorStore` (lines 29–49)

Copy the existing `@abstractmethod` style. New methods to add:
```python
@abstractmethod
async def upsert_parent_chunks(
    self,
    chunks: list[DocumentChunk],
    collection_name: str,
) -> None: ...

@abstractmethod
async def fetch_parent_chunks(
    self,
    parent_ids: list[str],
    collection_name: str,
) -> dict[str, str]: ...
```

#### Pool init pattern — `PgVectorStore._get_pool()` (lines 248–255)

Current (broken — missing codec registration):
```python
async def _get_pool(self):
    if self._pool is None:
        import asyncpg
        self._pool = await asyncpg.create_pool(
            self._dsn.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=2, max_size=10,
        )
    return self._pool
```

Replace with (add `init=` callback for pgvector codec):
```python
async def _get_pool(self) -> asyncpg.Pool:
    if self._pool is None:
        from pgvector.asyncpg import register_vector

        async def _init_conn(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        self._pool = await asyncpg.create_pool(
            self._dsn.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=2,
            max_size=10,
            init=_init_conn,
        )
    return self._pool
```

#### Tenacity retry pattern — copy from `QdrantVectorStore` (lines 87–88, 109–110)
```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def upsert(self, chunks: list[DocumentChunk]) -> None:
    ...

@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def search(self, ...) -> list[VectorSearchResult]:
    ...
```
Apply the same decorator to `upsert_parent_chunks` and `fetch_parent_chunks` on `PgVectorStore`.

#### Structured logging pattern — copy from `QdrantVectorStore` (lines 65, 83, 107, 154)
```python
logger.info(f"PgVectorStore: table={self._table} dim={self._dim}")   # __init__
logger.info(f"pgvector table ready: {self._table}")                   # create_collection
logger.debug(f"pgvector upserted {len(records)} rows")               # upsert
logger.debug(f"Parent upserted {len(points)} to {collection_name}")  # upsert_parent_chunks
logger.warning(f"fetch_parent_chunks failed: {exc}")                  # error path
```

#### `create_collection` DDL replacement pattern

Current (defective — IVFFlat, no RLS, no parent table):
```python
await conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {self._table} (...)
    CREATE INDEX IF NOT EXISTS {self._table}_vec_idx
        ON {self._table} USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
""")
```

Replace with (HNSW + RLS + parent table, inside explicit transaction for `work_mem`):
```python
async with pool.acquire() as conn:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {self._table} (
            chunk_id  TEXT PRIMARY KEY,
            doc_id    TEXT NOT NULL,
            content   TEXT NOT NULL,
            metadata  JSONB,
            embedding vector({self._dim}),
            tenant_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS {self._table}_doc_idx
            ON {self._table}(doc_id);
    """)
    async with conn.transaction():
        await conn.execute("SET LOCAL work_mem = '256MB'")
        await conn.execute(f"""
            DROP INDEX IF EXISTS {self._table}_vec_idx;
            CREATE INDEX IF NOT EXISTS {self._table}_vec_idx
                ON {self._table} USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
        """)
    # RLS setup
    await conn.execute(f"""
        ALTER TABLE {self._table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {self._table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {self._table};
        CREATE POLICY tenant_isolation ON {self._table}
            USING (metadata->>'tenant_id' = current_setting('app.current_tenant', true));
    """)
    # Parent table
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {self._table}_parent (
            chunk_id  TEXT PRIMARY KEY,
            doc_id    TEXT NOT NULL,
            content   TEXT NOT NULL,
            metadata  JSONB,
            tenant_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS {self._table}_parent_doc_idx
            ON {self._table}_parent(doc_id);
    """)
logger.info(f"pgvector table ready: {self._table}")
```

#### Per-query tenant context pattern (RLS)

Wrap every query method body:
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, true)", tenant_id
        )
        # ... run query inside same transaction
```

When no `tenant_id` is available (e.g., `count()`), omit `set_config` or pass `""`.

#### `upsert_parent_chunks` pattern — derive from `QdrantVectorStore.upsert_parent_chunks` (lines 161–207), adapted to SQL:
```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def upsert_parent_chunks(
    self,
    chunks: list[DocumentChunk],
    collection_name: str,
) -> None:
    import json as _json
    pool = await self._get_pool()
    records = [
        (c.chunk_id, c.doc_id, c.content,
         _json.dumps(c.metadata.model_dump(mode="json")))
        for c in chunks
    ]
    if not records:
        return
    async with pool.acquire() as conn:
        await conn.executemany(
            f"""
            INSERT INTO {self._table}_parent(chunk_id, doc_id, content, metadata)
            VALUES($1, $2, $3, $4::jsonb)
            ON CONFLICT(chunk_id) DO UPDATE
                SET content=EXCLUDED.content,
                    metadata=EXCLUDED.metadata
            """,
            records,
        )
    logger.debug(f"Parent upserted {len(records)} to {self._table}_parent")
```

#### `fetch_parent_chunks` pattern — derive from `QdrantVectorStore.fetch_parent_chunks` (lines 209–233), use narrow exception type (ERR-01):
```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def fetch_parent_chunks(
    self,
    parent_ids: list[str],
    collection_name: str,
) -> dict[str, str]:
    if not parent_ids:
        return {}
    pool = await self._get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT chunk_id, content FROM {self._table}_parent "
                f"WHERE chunk_id = ANY($1::text[])",
                parent_ids,
            )
        return {r["chunk_id"]: r["content"] for r in rows}
    except asyncpg.PostgresError as exc:
        logger.warning(f"fetch_parent_chunks failed: {exc}")
        return {}
```
Note: use `asyncpg.PostgresError` (not bare `except Exception`) — ERR-01 constraint.

#### `upsert` existing pattern — add `@retry` decorator (currently missing):
```python
# line 277 — add decorator above existing upsert
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def upsert(self, chunks: list[DocumentChunk]) -> None:
```

#### `search` existing pattern — add `@retry` decorator (currently missing):
```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def search(self, query_vector: list[float], top_k: int, filters: dict | None = None) -> list[VectorSearchResult]:
```

---

### `config/settings.py` — Single field default change

**Analog:** Self (line 191)

Change (line 191):
```python
# Before:
vector_store: Literal["qdrant", "milvus", "pgvector", "chroma"] = "qdrant"
# After:
vector_store: Literal["qdrant", "milvus", "pgvector", "chroma"] = "pgvector"
```

Pattern for Pydantic V2 settings field (copy from lines 76–79 for `Field` with description if needed):
```python
vector_store: Literal["qdrant", "milvus", "pgvector", "chroma"] = Field(
    default="pgvector",
    description="Vector backend. pgvector = Phase 1 default.",
)
```

---

### `services/tenant/tenant_service.py` — Rename + new async method

**Analog:** `services/audit/audit_service.py` (async service method with try/except + logger.warning)

#### Rename pattern (line 61):
```python
# Before:
def get_qdrant_filter(self, tenant_id: str) -> dict | None:
# After (keep old name as alias for 1-step migration if needed):
def get_tenant_filter(self, tenant_id: str) -> dict | None:
    """Return metadata filter dict for tenant isolation. Returns None for admin context."""
    if not tenant_id:
        return None
    return {"tenant_id": tenant_id}
```

#### New async method — copy try/except + logging pattern from `audit_service.py` lines 255–284:
```python
async def set_tenant_context(
    self,
    conn: asyncpg.Connection,
    tenant_id: str,
) -> None:
    """Set RLS session variable for the current connection/transaction.

    Call inside an active transaction so set_config is transaction-local.
    Pass empty string for admin/system operations (RLS will return 0 rows).
    """
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, true)", tenant_id
        )
    except asyncpg.PostgresError as exc:
        logger.warning(f"[Tenant] set_tenant_context failed: {exc}")
```

---

### `services/pipeline.py` — Two call-site renames

**Analog:** Self (lines 300, 419)

#### Call-site rename pattern (lines 300, 419):
```python
# Before (line 300):
tf = self._tenant_svc.get_qdrant_filter(tenant_id)
# After:
tf = self._tenant_svc.get_tenant_filter(tenant_id)
```
Apply identical change at line 419 (same pattern in `stream()` method).

---

### `requirements.txt` — Add pgvector Python package

**Analog:** Existing `requirements.txt` pinning style (`asyncpg==0.30.0`)

Add one line, following the same `package==version` format:
```
pgvector>=0.3.0
```
Place near `asyncpg` in the vector/DB section.

---

### `tests/unit/test_pgvector_store.py` — Wave 0 creation

**Analog:** None in codebase. Use pytest-asyncio pattern from `pytest.ini` (`asyncio_mode = auto`).

#### Test structure pattern from `pytest.ini` + project standard:
```python
import pytest
import asyncpg
from unittest.mock import AsyncMock, patch

# asyncio_mode = auto means no @pytest.mark.asyncio needed

async def test_factory_returns_pgvector(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "pgvector")
    from services.vectorizer.vector_store import get_vector_store, PgVectorStore
    # reset singleton
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    store = get_vector_store()
    assert isinstance(store, PgVectorStore)
```

#### ABC interface test pattern:
```python
import inspect
from services.vectorizer.vector_store import BaseVectorStore

def test_abc_interface():
    abstract_methods = {
        name for name, val in inspect.getmembers(BaseVectorStore)
        if getattr(val, "__isabstractmethod__", False)
    }
    assert "upsert_parent_chunks" in abstract_methods
    assert "fetch_parent_chunks" in abstract_methods
```

---

### `tests/integration/test_pgvector_rls.py` — Wave 0 creation

**Analog:** None. Use `pytest.mark.skipif` for CI without PostgreSQL.

#### Integration test pattern (from RESEARCH.md + project pytest.ini):
```python
import pytest
import asyncpg

pytestmark = pytest.mark.skipif(
    not _pg_available(),  # helper that calls asyncpg.connect
    reason="PostgreSQL + pgvector not available"
)

async def test_cross_tenant_isolation(pg_pool):
    store = PgVectorStore()
    # ingest with tenant_id=A, query with tenant_id=B → assert 0 results
    ...
```

---

## Shared Patterns

### Async pool acquisition
**Source:** `services/vectorizer/vector_store.py` — `PgVectorStore` (lines 248–255), `services/audit/audit_service.py` (lines 256–278)
**Apply to:** All `PgVectorStore` query methods

```python
pool = await self._get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        # set RLS context, then run query
```

### Tenacity retry
**Source:** `services/vectorizer/vector_store.py` — `QdrantVectorStore` (lines 87–88)
**Apply to:** `PgVectorStore.upsert`, `search`, `upsert_parent_chunks`, `fetch_parent_chunks`

```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def method_name(self, ...) -> ...:
```

### Structured logging (loguru)
**Source:** `services/vectorizer/vector_store.py` — `QdrantVectorStore` (lines 65, 83, 107, 154, 187, 207)
**Apply to:** All `PgVectorStore` methods

```python
logger.info(f"...")   # init and create_collection
logger.debug(f"...")  # successful upsert/fetch (counts, IDs)
logger.warning(f"...") # non-fatal errors (fetch_parent_chunks failure)
```

### Narrow exception handling (ERR-01)
**Source:** Project CLAUDE.md + `services/audit/audit_service.py` (lines 124–126, 281–283)
**Apply to:** All `try/except` blocks in `PgVectorStore`

```python
# WRONG (bare):
except Exception as exc:
# CORRECT (narrow):
except asyncpg.PostgresError as exc:
```

### DSN sanitization
**Source:** `services/vectorizer/vector_store.py` — `PgVectorStore._get_pool()` (line 253) and `audit_service.py` (line 257)
**Apply to:** Any new asyncpg connection creation

```python
# Both files use the same pattern:
dsn = settings.pg_dsn.replace("postgresql+asyncpg://", "postgresql://")
# audit_service uses:
dsn = settings.pg_dsn.replace("+asyncpg", "")
# Standardize to the vector_store.py version (more explicit)
```

### Factory singleton pattern
**Source:** `services/vectorizer/vector_store.py` lines 439–455; `services/audit/audit_service.py` lines 293–300
**Apply to:** Any new service modules

```python
_instance: ServiceClass | None = None

def get_service() -> ServiceClass:
    global _instance
    if _instance is None:
        _instance = ServiceClass()
    return _instance
```

### Pydantic V2 settings field
**Source:** `config/settings.py` (lines 19–25, 76–79)
**Apply to:** Any new settings fields

```python
field_name: type = Field(default=..., description="...")
# or simple:
field_name: type = default_value
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/unit/test_pgvector_store.py` | test | — | No existing unit tests for vector store; Wave 0 creation |
| `tests/integration/test_pgvector_rls.py` | test | — | No RLS integration tests exist; Wave 0 creation |
| `tests/integration/test_pgvector_recall.py` | test | — | No recall benchmarking tests exist; Wave 0 creation |
| `tests/conftest.py` (pg_pool fixture) | test fixture | — | No shared PostgreSQL fixture exists |

---

## Metadata

**Analog search scope:** `services/`, `config/`, `utils/`, `tests/`
**Files scanned:** 6 source files read directly
**Key pitfall reminders for planner:**
1. `init=` callback is mandatory for pgvector codec — pool without it silently breaks vector queries
2. `DROP INDEX IF EXISTS` before `CREATE INDEX` — `IF NOT EXISTS` does NOT replace IVFFlat with HNSW
3. `except asyncpg.PostgresError` not bare `except Exception` — ERR-01
4. `set_config(..., true)` (transaction-local) inside `async with conn.transaction()` — not session-scoped
5. `pgvector>=0.3.0` must be added to `requirements.txt` before any import of `pgvector.asyncpg`
**Pattern extraction date:** 2026-04-21
