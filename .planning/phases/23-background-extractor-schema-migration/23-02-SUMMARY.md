---
phase: 23-background-extractor-schema-migration
plan: 02
status: complete
executed: 2026-05-16
commits:
  - de1e7ae: test(23-02) RED save_fact gates
  - 52ecde1: feat(23-02) save_fact embed-on-write rewrite
  - 426247b: fix(23-02) OpenAIEmbedder dimensions=settings.embedding_dim (A1)
---

# Plan 23-02 SUMMARY (MEM-02 + A1)

## Outcome

MEM-02 GREEN. `LongTermMemory.save_fact` rewritten as embed-on-write with typed `MemoryFactWriteError` on both failure paths. Eng-review A1 also closed: `OpenAIEmbedder.embed_batch` now passes `dimensions=settings.embedding_dim` to the OpenAI API, eliminating the silent dimension-mismatch failure that would have hit any prod deploy with `embedding_provider="openai"`.

## Files modified

- `services/memory/memory_service.py` — `save_fact` body rewritten (Step 1 lazy imports + Step 2 embed via `get_embedder().embed_one(fact)` + narrow-exception catch `(httpx.HTTPError, RuntimeError, OSError)` → `MemoryFactWriteError("embedding failed")` + Step 3 INSERT with `$6::vector` cast wrapped in `asyncpg.PostgresError` → `MemoryFactWriteError("persistence failed")`). Signature preserved.
- `services/vectorizer/embedder.py` — `OpenAIEmbedder.embed_batch` gains `dimensions=settings.embedding_dim` kwarg on the `embeddings.create` call (A1 fix). Documented with inline comment referencing RESEARCH §Pitfall 2.
- `tests/unit/test_memory_save_fact.py` — created with 4 unit tests (happy-path embed-on-write, embedder-failure parametrized over RuntimeError/HTTPError/OSError, asyncpg-failure typed-error, signature-unchanged).
- `tests/unit/test_openai_embedder.py` — created with `test_openai_embedder_passes_dimensions_kwarg` A1 regression test.

## Verification

- `uv run pytest tests/unit/test_memory_save_fact.py tests/unit/test_openai_embedder.py -x -q` GREEN.
- No regression: `uv run pytest tests/unit/test_memory_schema.py tests/unit/test_memory_pool.py tests/unit/test_extractor*.py -x -q` GREEN.
- ruff clean on `services/memory/memory_service.py` + `services/vectorizer/embedder.py` + both new test files.
- `grep -n 'dimensions=settings.embedding_dim' services/vectorizer/embedder.py` matches one line; `grep -c 'dimensions=' services/vectorizer/embedder.py` equals 1.
- `grep -n '\$6::vector' services/memory/memory_service.py` matches one line.
- `grep -c 'raise MemoryFactWriteError' services/memory/memory_service.py` matches two lines (embed-failure + asyncpg-failure paths).

## Requirements satisfied

- MEM-02 — `save_fact` embed-on-write with typed error contract + zero partial-write rows
- Eng-review A1 (Pitfall 2 closure) — OpenAI provider deploys no longer silent-fail

## Plan 23-05 unblocked

`save_fact` now writes embedded rows + raises typed errors. `dispatch_extraction` `_run_and_persist` body in Plan 23-05 can rely on the contract.
