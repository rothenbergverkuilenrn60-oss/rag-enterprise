# Deferred Items

v1.8+ deferred items captured during phase execution; format: H2 per item, bullet per concrete site.

## MYPY-01 overflow (deferred to v1.9)

_All 7 entries resolved in Phase 32 — see `.planning/phases/32-mypy-strict-cleanup/32-00-SUMMARY.md`._

| Entry | Resolution | Task |
|-------|-----------|------|
| `eval/ragas_runner.py:19` datasets | Silenced with `# type: ignore[import-untyped]  # why: huggingface datasets has no py.typed or stubs` | T3 |
| `eval/ragas_runner.py:333` pandas.api.types | pandas-stubs installed; silence not needed (line was already clean) | T1+T3 |
| `scripts/backfill_fact_embeddings.py:32` asyncpg | asyncpg-stubs installed; import now typed | T1+T2 |
| `scripts/evict_long_term_facts.py:63` asyncpg | asyncpg-stubs installed; import now typed | T1+T2 |
| `services/vectorizer/indexer.py:9` asyncpg | asyncpg-stubs installed; import now typed | T1+T2 |
| `services/vectorizer/indexer.py:30` rank_bm25 | Silenced with `# type: ignore[import-untyped]  # why: rank_bm25 no stubs; tracking: NA` | T3 |
| `scripts/evict_long_term_facts.py` structural | `explicit_package_bases = true` added to `[tool.mypy]` | T0 |
