# Deferred Items

v1.8+ deferred items captured during phase execution; format: H2 per item, bullet per concrete site.

## MYPY-01 overflow (deferred to v1.9)

Phase 30 cap = 25 violations fixed/silenced. Residual count: 7. Captured 2026-05-17.

### Files

- `eval/ragas_runner.py:19` — `import-untyped` — Skipping analyzing "datasets": module is installed, but missing library stubs or py.typed marker
- `eval/ragas_runner.py:333` — `import-untyped` — Library stubs not installed for "pandas.api.types"
- `scripts/backfill_fact_embeddings.py:32` — `import-untyped` — Skipping analyzing "asyncpg": module is installed, but missing library stubs or py.typed marker
- `scripts/evict_long_term_facts.py:63` — `import-untyped` — Skipping analyzing "asyncpg": module is installed, but missing library stubs or py.typed marker
- `services/vectorizer/indexer.py:9` — `import-untyped` — Skipping analyzing "asyncpg": module is installed, but missing library stubs or py.typed marker
- `services/vectorizer/indexer.py:30` — `import-untyped` — Skipping analyzing "rank_bm25": module is installed, but missing library stubs or py.typed marker
- `scripts/evict_long_term_facts.py` — `structural` — Source file found twice under different module names ("evict_long_term_facts" and "scripts.evict_long_term_facts"); fix via adding `__init__.py` to `scripts/` or using `--explicit-package-bases`
