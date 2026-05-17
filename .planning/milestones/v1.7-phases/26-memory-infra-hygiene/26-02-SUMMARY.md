# Plan 26-02 Summary — bge-m3 path resolver

**Status:** ✅ Complete
**Executed:** 2026-05-17
**Wave:** 1 (no deps)
**Requirements closed:** TD-07 (embedding + reranker layouts unified)

## What shipped

- `config/settings.py` — module-level `resolve_embedding_model_path(name)` function + `embedding_model_path` + `reranker_model_path` converted to `@computed_field @property` delegates
- `tests/unit/test_resolve_embedding_model_path.py` — 7 unit tests covering all 4 search-order branches + reranker variant + env-override scoping
- `tests/conftest.py` — bge-m3 guard at line 149-156 delegates to resolver (no more hardcoded `embedding_models/bge-m3` literal)

## Verification

- `uv run pytest tests/unit/test_resolve_embedding_model_path.py -v` → **7/7 PASSED** in 0.16s
- `uv run pytest tests/unit/ -k 'settings or config' -v` → **37 passed, 0 failed** (existing settings tests unaffected by property-delegate refactor)
- `uv run ruff check config/settings.py tests/conftest.py` → all clean
- `APP_MODEL_DIR=/tmp uv run python -c "..."` → `settings.embedding_model_path` returns `PosixPath('/tmp/embedding_models/bge-m3')` (legacy fallback when no model present — preserves crash-at-load semantics)
- Existing callers verified: `services/retriever/retriever.py:88+92`, `services/vectorizer/embedder.py:110`, `services/doc_processor/chunker.py:119` all use `str(settings.embedding_model_path)` — works unchanged with property accessor

## Pre-existing mypy note

`config/settings.py:154` `embedding_ensemble: list[dict] = []` triggers `Missing type parameters for generic type "dict"` under `mypy --strict`. NOT introduced by this plan — pre-existing on master. Tracked as v1.8+ cleanup todo (not in TD-07 scope).

## Eng-review fixes embedded

None — Plan 26-02 had no eng-review findings.

## Commits

- `test(26-02): RED gates for resolve_embedding_model_path (TD-07)`
- `feat(26-02): bge-m3 path resolver — HF flat + legacy + hub cache layouts (TD-07)`
- `chore(26-02): conftest bge-m3 guard delegates to resolve_embedding_model_path (TD-07)`

## Implementation deviation

Resolver reads `APP_MODEL_DIR` from `os.environ` at call time (with `MODEL_DIR` as fallback) instead of using only the module-level `MODEL_DIR` constant. Rationale: makes the function testable via `monkeypatch.setenv` without requiring `importlib.reload(config.settings)` for every test. Production behavior is unchanged because `APP_MODEL_DIR` does not mutate after startup. The `MODEL_DIR` global is still set at module import for OPS-01 fail-fast.

## Unblocks

- (none — Plan 26-02 is leaf in its wave; only affects test fixture + property delegates)
