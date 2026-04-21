# EnterpriseRAG — Project Guide

## Project State

This project uses GSD (Get Shit Done) workflow. Always read planning files before starting work.

**Planning files:**
- `.planning/STATE.md` — current phase and progress
- `.planning/ROADMAP.md` — all 6 phases and requirements
- `.planning/REQUIREMENTS.md` — 22 requirements with traceability
- `.planning/PROJECT.md` — project context and decisions

## GSD Workflow

```
/gsd-discuss-phase N   → clarify approach for phase N
/gsd-plan-phase N      → generate execution plan
/gsd-execute-phase N   → execute the plan
/gsd-verify-work N     → verify requirements met
/gsd-ship              → commit and advance
```

**Current phase:** Start with `/gsd-plan-phase 1` (pgvector Foundation)

## Project Standards

See `Claude.md` for full implementation standards. Key rules:

- **No prototype code** — production-grade only; Pydantic V2, mypy --strict, ruff
- **No bare `except`** — narrow exception types only (this is a v1 requirement: ERR-01)
- **No blocking I/O** in async contexts
- **Adapters** for all external dependencies (LLMs, DBs, vector stores)
- **Tenacity** retry logic for all external calls
- **Structured logging** for every operation

## Architecture

Three-layer: `utils/` → `services/` → `controllers/`

Vector store: PostgreSQL + pgvector (replacing Qdrant — Phase 1 goal)
Auth: OIDC/JWT via `services/auth/`
Pipelines: `services/pipeline.py` — `IngestionPipeline`, `QueryPipeline`, `AgentQueryPipeline`

## Phase 1 Priority

Phase 1 (pgvector Foundation) unblocks everything else. Complete PG-01–05 before touching security, image extraction, or tests.

Key files for Phase 1:
- `services/vectorizer/vector_store.py` — `BaseVectorStore` ABC + `PgVectorStore` (incomplete)
- `services/pipeline.py` — `IngestionPipeline`, `QueryPipeline`
- `services/retriever/` — calls `upsert_parent_chunks` / `fetch_parent_chunks`

## Environment

- WSL2 + Miniconda `torch_env`
- `MODEL_DIR` must be set via env var (not hardcoded — OPS-01 requirement)
- PostgreSQL + pgvector required for Phase 1+
