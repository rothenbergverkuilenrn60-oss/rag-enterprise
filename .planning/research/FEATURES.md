# Features Research

## Summary

JWT hardening requires startup-time entropy validation (reject weak secrets before the server accepts traffic, not just in production mode). Per-route rate limiting with `slowapi` requires a decorator on each route — global middleware alone is insufficient. PII detection must run before chunking/embedding to be effective. RAGAS metrics with a minimum 50-pair eval dataset are the current standard for RAG quality CI gates.

## JWT Hardening Patterns

**Best practice:** Validate the secret at startup, before accepting any traffic.

```python
import os, secrets

def validate_jwt_secret():
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET env var is required")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    # Denylist of known weak defaults
    WEAK_SECRETS = {"CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY", "secret", "changeme", "password"}
    if secret in WEAK_SECRETS:
        raise RuntimeError(f"JWT_SECRET is a known weak default — set a strong random value")
```

- No default fallback in `os.environ.get()` — missing secret = crash at startup, not runtime
- Denylist approach catches exact known-weak values regardless of `ENVIRONMENT`
- FastAPI: call `validate_jwt_secret()` in the app lifespan startup handler

## Per-Route Rate Limiting in FastAPI

**`slowapi` requires a decorator per route** — `app.state.limiter` middleware alone does not enforce per-route limits.

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/ingest")
@limiter.limit("10/minute")
async def ingest(request: Request, ...):
    ...
```

- `request: Request` must be the first parameter on every rate-limited route
- Global middleware only handles the `RateLimitExceeded` exception — it does not apply limits
- Test isolation: use `limiter.reset()` or patch `get_remote_address` in test fixtures

## PII Detection in Ingestion Pipelines

**Microsoft Presidio** is the standard library. Must run **before chunking** (so PII isn't split across chunk boundaries).

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def detect_pii(text: str, block_entities: list[str]) -> PIIResult:
    results = analyzer.analyze(text=text, language="en")
    if any(r.entity_type in block_entities for r in results):
        raise PIIBlockedError(f"Blocked entity detected: {results}")
    return anonymizer.anonymize(text=text, analyzer_results=results)
```

- `BLOCK_ENTITIES` (e.g., SSN, CREDIT_CARD) — raise and reject ingest
- `ANONYMIZE_ENTITIES` (e.g., PERSON, EMAIL) — redact before storing
- Non-blocking = silent data leakage risk; blocking should be the default

## Testing FastAPI Service Singletons

**Canonical pattern:** `app.dependency_overrides` + `lru_cache.cache_clear()` in teardown.

```python
from functools import lru_cache
import pytest
from httpx import AsyncClient

@lru_cache()
def get_vector_store() -> VectorStore:
    return QdrantVectorStore(...)

@pytest.fixture
async def client(mock_vector_store):
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    get_vector_store.cache_clear()  # critical — prevents singleton leakage between tests
```

- Always call `cache_clear()` in teardown — otherwise singletons bleed across tests
- For `get_*()` factory pattern (not FastAPI Depends), monkeypatch the module attribute directly

## RAG Evaluation Standards

**Minimum dataset sizes:**
- 10 pairs: statistically meaningless (current state) — one bad answer = 10% drop
- 50 pairs: minimum for CI smoke test
- 200+ pairs: meaningful regression detection

**RAGAS metrics (2024 standard):**
```
faithfulness > 0.85        — answer grounded in retrieved context
answer_relevancy > 0.80    — answer addresses the question
context_precision > 0.75   — retrieved chunks are relevant
context_recall > 0.70      — relevant chunks were retrieved
```

**Tooling:** `ragas` library + `deepeval` for automated CI integration. Generate synthetic QA pairs from existing documents using LLM-based dataset generation to bootstrap from 10 → 200.

## Sources

- Presidio docs: https://microsoft.github.io/presidio/
- slowapi docs: https://slowapi.readthedocs.io/
- RAGAS: https://docs.ragas.io/
- FastAPI testing patterns: https://fastapi.tiangolo.com/tutorial/testing/
