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
from utils.logger import log_latency


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
            from pgvector.asyncpg import register_vector

            async def _init_conn(conn: _asyncpg.Connection) -> None:
                await register_vector(conn)

            self._pool = await _asyncpg.create_pool(
                self._dsn.replace("postgresql+asyncpg://", "postgresql://"),
                min_size=2,
                max_size=10,
                init=_init_conn,
                server_settings={"work_mem": "256MB"},  # D-06: work_mem for all HNSW queries
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
        """Search for nearest neighbors.

        Opens an explicit transaction and sets app.current_tenant via set_config
        before the SELECT so RLS is enforced at the row level (D-02).
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # D-02: set RLS context transaction-locally before read
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
        return [
            VectorSearchResult(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                content=r["content"],
                metadata=r["metadata"] or {},
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
        import chromadb
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
