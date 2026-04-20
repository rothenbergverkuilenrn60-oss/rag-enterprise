# TESTING

## Summary
The project uses pytest with asyncio support and a two-tier test structure (unit + integration). Coverage floor is 60% for unit tests, but 11 of ~18 service modules have no unit tests at all, leaving significant gaps in critical subsystems.

## Test Configuration

**pytest.ini:**
- `asyncio_mode = auto` — all async tests run automatically
- Timeout: 60s per test
- Unit test coverage floor: 60% (enforced)
- Integration tests: non-blocking in CI (allowed to fail)

## Test Structure

```
tests/
├── unit/           # 4 files — fully mocked, no live services required
└── integration/    # 2 files — require live Redis, vector DB, and LLM services
```

### Unit Tests (4 files)
| File | Coverage |
|------|----------|
| test_pipeline.py | Ingestion + Query pipeline stages |
| test_chunking.py | Chunking strategies |
| test_cache.py | Redis cache layer |
| test_retrieval.py | Vector retrieval logic |

### Integration Tests (2 files)
| File | Notes |
|------|-------|
| test_api_integration.py | Full API round-trips (requires running stack) |
| test_rag_pipeline.py | End-to-end RAG flow |

## Patterns

**Fixture patterns:** Module-scoped fixtures for expensive setup (DB connections, model loading).

**Mock patterns:** `MagicMock` / `AsyncMock` throughout; `__new__` bypass used to construct service singletons under test without triggering real initialization.

**CI pipeline order:** lint → unit tests → integration tests (integration non-blocking).

## Coverage Gaps

11 service modules have **zero unit tests**:
- `services/auth.py`
- `services/memory.py`
- `services/feedback.py`
- `services/audit.py`
- `services/tenant.py`
- `services/events.py`
- `services/nlu.py`
- `services/knowledge.py`
- `services/ab_test.py`
- `services/rules.py`
- `services/vectorizer.py`

## Eval Coverage

`eval/` directory contains a 10-QA-pair evaluation dataset — insufficient for meaningful RAG quality assessment. No automated eval runs wired into CI.

## Sources
- pytest.ini
- tests/unit/ (4 files)
- tests/integration/ (2 files)
- .github/ workflows
- eval/ directory
