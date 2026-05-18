# =============================================================================
# services/vectorizer/vector_store.py
# STAGE 4b — Vector storage
# Backends: pgvector (production) / Chroma (dev/PoC)
# QdrantVectorStore removed per D-05.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential

from config.settings import settings
from utils.models import DocumentChunk


@dataclass
class VectorSearchResult:
    chunk_id: str
    doc_id: str
    content: str
    metadata: dict
    score: float


# ══════════════════════════════════════════════════════════════════════════════
# Abstract Base
# ══════════════════════════════════════════════════════════════════════════════
class BaseVectorStore(ABC):
    @abstractmethod
    async def create_collection(self) -> None: ...

    @abstractmethod
    async def upsert(self, chunks: list[DocumentChunk], tenant_id: str = "") -> None: ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        tenant_id: str = "",
        filters: dict | None = None,
    ) -> list[VectorSearchResult]: ...

    @abstractmethod
    async def delete_by_doc(self, doc_id: str) -> int: ...

    @abstractmethod
    async def count(self) -> int: ...

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


# ══════════════════════════════════════════════════════════════════════════════
# pgvector Backend (production)
# ══════════════════════════════════════════════════════════════════════════════
def _build_filter_where(
    filters: dict[str, int | str],
    start_param: int = 3,
) -> tuple[str, list[int | str]]:
    """Build a parameterized WHERE clause for JSONB metadata filters (META-02).

    Caller is responsible for $1=query_vector and $2=top_k. Filter values
    occupy $start_param onwards. Filter VALUES are asyncpg ``$N`` parameters —
    NEVER f-string-interpolated (T-08-01 mitigation). Filter KEYS are
    hard-coded via ``repr`` of the str literal — keys must come from a trusted
    extractor (services.nlu.filter_extractor), never from raw user input.

    Args:
        filters: dict whose keys are JSONB extraction targets (e.g. ``page_number``,
            ``section_id``) and values are ``int`` or ``str``. Unknown value types
            are silently dropped (defense-in-depth).
        start_param: ``$N`` index for the first filter value.

    Returns:
        ``(where_sql, param_list)``. Empty filters or all-skipped filters
        return ``("", [])``.

    Examples:
        >>> _build_filter_where({"page_number": 63})
        ("WHERE (metadata->>'page_number')::int = $3", [63])
        >>> _build_filter_where({"section_id": "3.10"})
        ("WHERE metadata->>'section_id' = $3", ["3.10"])
        >>> _build_filter_where({})
        ("", [])
    """
    if not filters:
        return "", []
    clauses: list[str] = []
    params: list[int | str] = []
    n = start_param
    for key, value in filters.items():
        # bool is a subclass of int in Python; the explicit ``not isinstance(value, bool)``
        # guard prevents ``filters={"x": True}`` from being routed to the integer branch.
        if isinstance(value, int) and not isinstance(value, bool):
            # Cast JSONB extraction to int — backed by B-tree expression index.
            clauses.append(f"(metadata->>{key!r})::int = ${n}")
        elif isinstance(value, str):
            clauses.append(f"metadata->>{key!r} = ${n}")
        else:
            # Unknown type — skip silently (defense-in-depth: never inject untyped value).
            continue
        params.append(value)
        n += 1
    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


class PgVectorStore(BaseVectorStore):

    def __init__(self) -> None:
        self._dsn = settings.pg_dsn
        self._table = settings.qdrant_collection.replace("-", "_")
        self._dim = settings.embedding_dim
        self._pool = None
        logger.info(f"PgVectorStore: table={self._table} dim={self._dim}")

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg as _asyncpg
            from pgvector.asyncpg import register_vector  # type: ignore[import-untyped]  # why: pgvector.asyncpg lacks stubs as of 2026-05

            async def _init_conn(conn: _asyncpg.Connection) -> None:
                await register_vector(conn)

            dsn = self._dsn.replace("postgresql+asyncpg://", "postgresql://")
            # strip ?ssl=... — asyncpg treats URL ssl param as a runtime GUC
            # which raises CantChangeRuntimeParamError; pass ssl= kwarg instead
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
            parsed = urlparse(dsn)
            qs = {k: v for k, v in parse_qs(parsed.query).items() if k.lower() != "ssl"}
            dsn = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
            self._pool = await _asyncpg.create_pool(  # type: ignore[assignment]  # why: asyncpg-stubs Pool[Record] generic conflicts with None-initialized field; full Pool annotation deferred (T2.5 drift)
                dsn,
                min_size=2,
                max_size=10,
                init=_init_conn,
                ssl=False,
                server_settings={"work_mem": "256MB"},
            )
        return self._pool

    async def create_collection(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            # Main chunk table (tenant_id column for RLS)
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
            # HNSW index — SET LOCAL work_mem inside transaction as defense-in-depth for index build
            async with conn.transaction():
                await conn.execute("SET LOCAL work_mem = '256MB'")
                await conn.execute(f"DROP INDEX IF EXISTS {self._table}_vec_idx;")
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self._table}_vec_idx
                        ON {self._table} USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16, ef_construction = 64);
                """)
            # RLS setup — T-1-01: prevent cross-tenant data leaks
            await conn.execute(f"""
                ALTER TABLE {self._table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {self._table} FORCE ROW LEVEL SECURITY;
                DROP POLICY IF EXISTS tenant_isolation ON {self._table};
                CREATE POLICY tenant_isolation ON {self._table}
                    USING (
                        tenant_id = current_setting('app.current_tenant', true)
                        OR current_setting('app.current_tenant', true) IS NULL
                        OR current_setting('app.current_tenant', true) = ''
                    );
            """)
            # Phase 8 (META-02): B-tree expression indexes for JSONB-filtered HNSW.
            # Partial indexes WHERE … IS NOT NULL skip legacy chunks (no section_id);
            # text-shape index supports IS NOT NULL predicate evaluation, int-cast
            # index backs the (metadata->>'page_number')::int = $N filter clause.
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {self._table}_page_idx
                    ON {self._table} USING btree ((metadata->>'page_number'))
                    WHERE metadata->>'page_number' IS NOT NULL;
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {self._table}_page_int_idx
                    ON {self._table} USING btree (((metadata->>'page_number')::int))
                    WHERE metadata->>'page_number' IS NOT NULL;
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {self._table}_section_idx
                    ON {self._table} USING btree ((metadata->>'section_id'))
                    WHERE metadata->>'section_id' IS NOT NULL;
            """)
            # Parent chunk table (no vector column — pure content storage)
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

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
    async def upsert(
        self,
        chunks: list[DocumentChunk],
        tenant_id: str = "",
    ) -> None:
        """Upsert chunks into the vector table.

        Opens an explicit transaction and sets app.current_tenant via set_config
        before each INSERT so RLS is enforced at the row level (D-02).
        """
        import json as _json
        pool = await self._get_pool()
        records = [
            (
                c.chunk_id,
                c.doc_id,
                c.content,
                _json.dumps(c.metadata.model_dump(mode="json")),
                c.embedding,
                getattr(c.metadata, "tenant_id", tenant_id) or tenant_id,
            )
            for c in chunks
            if c.embedding is not None
        ]
        if not records:
            logger.warning("upsert called with no chunks that have embeddings")
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                # D-02: set RLS context transaction-locally before write
                await conn.execute(
                    "SELECT set_config('app.current_tenant', $1, true)", tenant_id
                )
                await conn.executemany(
                    f"""
                    INSERT INTO {self._table}
                        (chunk_id, doc_id, content, metadata, embedding, tenant_id)
                    VALUES ($1, $2, $3, $4::jsonb, $5::vector, $6)
                    ON CONFLICT(chunk_id) DO UPDATE
                        SET content=EXCLUDED.content,
                            metadata=EXCLUDED.metadata,
                            embedding=EXCLUDED.embedding,
                            tenant_id=EXCLUDED.tenant_id
                    """,
                    records,
                )
        logger.debug(f"Upserted {len(records)} chunks into {self._table}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        tenant_id: str = "",
        filters: dict | None = None,
    ) -> list[VectorSearchResult]:
        """Search for nearest neighbors with optional JSONB metadata filtering.

        D-02 (Phase 1): set_config('app.current_tenant', …, true) opens RLS scope.
        META-02 (Phase 8): when filters are non-empty (after page_number=0 strip),
        also set hnsw.iterative_scan='relaxed_order' + hnsw.ef_search transaction-
        locally so HNSW expansion finds k matches against sparse JSONB filters
        (REQ A-4 #3). SET LOCAL keeps the override scoped to this transaction —
        does not leak to subsequent pooled-connection requests (Pitfall #5).
        """
        # T-08-09: page_number=0 is the "unknown" sentinel set by the image
        # extractor for standalone images. Stripping it before WHERE-build
        # prevents queries with filters={page_number: 0} from broadcast-matching
        # every legacy image chunk and polluting recall.
        effective_filters: dict[str, int | str] = {}
        for k, v in (filters or {}).items():
            if k == "page_number" and v == 0:
                continue
            effective_filters[k] = v

        where_clause, filter_params = _build_filter_where(effective_filters, start_param=3)
        # _build_filter_where may also produce ("", []) if all values had unknown types.
        has_filter = bool(where_clause)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # D-02: tenant scope FIRST — must precede the GUC + SELECT.
                await conn.execute(
                    "SELECT set_config('app.current_tenant', $1, true)", tenant_id
                )
                if has_filter:
                    # META-02 / Pitfall #3 + #5: SET LOCAL scopes to this transaction only.
                    # iterative_scan walks the HNSW graph until top-k filter-matches found.
                    ef_search = int(getattr(settings, "pgvector_ef_search_filtered", 200))
                    await conn.execute(
                        "SET LOCAL hnsw.iterative_scan = 'relaxed_order'"
                    )
                    # ef_search is a trusted int from settings — int() cast is the only
                    # safe f-string surface here (T-08-01: no user value reaches SQL text).
                    await conn.execute(f"SET LOCAL hnsw.ef_search = {ef_search}")

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
        import json as _json
        return [
            VectorSearchResult(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                content=r["content"],
                metadata=(_json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]) or {},
                score=float(r["score"]),
            )
            for r in rows
        ]

    async def delete_by_doc(self, doc_id: str) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self._table} WHERE doc_id=$1", doc_id
            )
        return int(result.split()[-1])

    async def count(self) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT COUNT(*) AS c FROM {self._table}")
            return row["c"]

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
    async def upsert_parent_chunks(
        self,
        chunks: list[DocumentChunk],
        collection_name: str,
    ) -> None:
        """Upsert parent chunks to {table}_parent (no embedding — pure content storage).

        collection_name parameter kept for API parity; pgvector backend uses
        self._table + '_parent' regardless of collection_name value.
        """
        import json as _json
        pool = await self._get_pool()
        records = [
            (
                c.chunk_id,
                c.doc_id,
                c.content,
                _json.dumps(c.metadata.model_dump(mode="json")),
            )
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

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
    async def fetch_parent_chunks(
        self,
        parent_ids: list[str],
        collection_name: str,
    ) -> dict[str, str]:
        """Fetch parent chunk content by IDs. Returns {chunk_id: content} dict.

        collection_name parameter kept for API parity; pgvector backend ignores it.
        """
        if not parent_ids:
            return {}
        import asyncpg as _asyncpg
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT chunk_id, content FROM {self._table}_parent "
                    f"WHERE chunk_id = ANY($1::text[])",
                    parent_ids,
                )
            return {r["chunk_id"]: r["content"] for r in rows}
        except _asyncpg.PostgresError as exc:
            logger.warning(f"fetch_parent_chunks failed: {exc}")
            return {}


# ══════════════════════════════════════════════════════════════════════════════
# Chroma Backend (local dev / PoC)
# ══════════════════════════════════════════════════════════════════════════════
class ChromaVectorStore(BaseVectorStore):

    def __init__(self) -> None:
        import chromadb  # type: ignore[import-not-found]  # why: chromadb has no stubs as of 2026-05
        self._client = chromadb.PersistentClient(
            path=str(settings.index_dir / "chroma")
        )
        self._col_obj = self._client.get_or_create_collection(
            settings.qdrant_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaVectorStore: collection={settings.qdrant_collection}")

    async def create_collection(self) -> None:
        pass  # auto-created above

    async def upsert(self, chunks: list[DocumentChunk], tenant_id: str = "") -> None:
        valid = [c for c in chunks if c.embedding]
        if not valid:
            return
        self._col_obj.upsert(
            ids=[c.chunk_id for c in valid],
            embeddings=[c.embedding for c in valid],
            documents=[c.content for c in valid],
            metadatas=[c.metadata.model_dump(mode="json") for c in valid],
        )

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        tenant_id: str = "",
        filters: dict | None = None,
    ) -> list[VectorSearchResult]:
        kwargs: dict = {"query_embeddings": [query_vector], "n_results": top_k}
        if filters:
            kwargs["where"] = filters
        r = self._col_obj.query(**kwargs)
        results = []
        for i, cid in enumerate(r["ids"][0]):
            results.append(VectorSearchResult(
                chunk_id=cid,
                doc_id=r["metadatas"][0][i].get("doc_id", ""),
                content=r["documents"][0][i],
                metadata=r["metadatas"][0][i],
                score=max(0.0, 1.0 - r["distances"][0][i]),
            ))
        return results

    async def delete_by_doc(self, doc_id: str) -> int:
        existing = self._col_obj.get(where={"doc_id": doc_id})
        ids = existing.get("ids", [])
        if ids:
            self._col_obj.delete(ids=ids)
        return len(ids)

    async def count(self) -> int:
        return self._col_obj.count()

    async def upsert_parent_chunks(
        self,
        chunks: list[DocumentChunk],
        collection_name: str,
    ) -> None:
        raise NotImplementedError(
            "ChromaVectorStore does not support parent chunks (dev/PoC only)"
        )

    async def fetch_parent_chunks(
        self,
        parent_ids: list[str],
        collection_name: str,
    ) -> dict[str, str]:
        raise NotImplementedError(
            "ChromaVectorStore does not support parent chunks (dev/PoC only)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════
_store_instance: BaseVectorStore | None = None


def get_vector_store() -> BaseVectorStore:
    global _store_instance
    if _store_instance is None:
        vs = settings.vector_store
        if vs == "pgvector":
            _store_instance = PgVectorStore()
        elif vs == "chroma":
            _store_instance = ChromaVectorStore()
        else:
            raise ValueError(f"Unsupported vector store: {vs}")
        logger.info(f"VectorStore factory: backend={vs}")
    return _store_instance
