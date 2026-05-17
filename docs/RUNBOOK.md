# EnterpriseRAG Runbook

**Audience:** Developers onboarding to a local dev environment + operators performing
day-2 operations.
**Scope:** v1.7+ ops deltas (TD-01 audit_log auto-create, TD-03 asyncpg URL handling,
TD-07 bge-m3 HF cache layout, TD-06 redis-mock test pattern) plus baseline local-dev
setup. On-call playbook deferred to v1.8.

See [README.md](../README.md) for project overview, architecture, and quick demos.
See [docs/DOCKER_DEPLOY.md](DOCKER_DEPLOY.md) for Docker-stack production deployment.

---

## Local dev setup

Step-by-step from a clean clone to a passing test suite. Does not duplicate the
README Quick start — read that first for Docker-stack mode. This section covers
the "I want unit + integration tests locally" path.

### 1. Python environment

```bash
# Requires Python ≥ 3.11 and uv (https://github.com/astral-sh/uv)
uv venv
source .venv/bin/activate   # or .venv/Scripts/activate on Windows
uv sync                     # installs all project + dev deps from uv.lock
```

All subsequent commands use `uv run <cmd>` to stay inside the managed environment.

### 2. PostgreSQL + pgvector

Unit tests run against a live PG instance.

```bash
# Quickest path — run in Docker:
docker run -d \
  --name pg-local \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Verify:
psql postgresql://postgres:postgres@localhost:5432/postgres \
  -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

For the full Docker-compose stack (includes Nginx, ARQ worker, Ollama) see
[docs/DOCKER_DEPLOY.md](DOCKER_DEPLOY.md).

### 3. Redis

```bash
docker run -d --name redis-local -p 6379:6379 redis:7-alpine
```

Unit tests that exercise Redis are isolated via the `@pytest.mark.uses_redis`
marker (TD-06); most unit tests do not require a live Redis instance.

### 4. Environment variables

```bash
cp .env.docker .env           # .env.docker is the canonical template
# Edit .env — minimum required for local dev:
#
#   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
#   REDIS_URL=redis://localhost:6379/0
#   SECRET_KEY=<any 32-char string for local dev>
#   MODEL_DIR=/path/to/your/local/model-cache   # OPS-01: must be env-driven
```

`MODEL_DIR` **must** be set via environment variable — it is never hardcoded
(OPS-01 requirement; see `config/settings.py`).

### 5. Model files (bge-m3)

Integration tests that call the embedder require the bge-m3 model. See
[Ops §4 — bge-m3 model dir layout](#4-bge-m3-model-dir-layout-td-07--phase-26)
for the expected directory structure. Unit tests that use `AgentQueryPipeline`
mock at the consumer path and do not need model files on disk.

### 6. First test run

```bash
uv run pytest -m 'not benchmark'
```

This is the CI gate used in Phase 27 (excludes `@pytest.mark.benchmark` tests
that require calibrated hardware). A green result here matches what CI will see.

---

## Ops procedures

### 1. Verify audit_log auto-create on fresh PG (TD-01 / Phase 26)

Since Phase 26, `services/audit/audit_service.py` auto-creates the `audit_log`
table on its first call — no manual DDL step is required.

**Behaviour:** First call into `audit_service` triggers `_get_pool` →
`_create_tables` → DDL that creates `audit_log` and immediately applies:

```sql
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
```

The INSERT-ONLY invariant is established by the same DDL call that creates the
table. No `UPDATE` or `DELETE` on `audit_log` is ever granted.

**Verification (run once after cold-start):**

```sql
SELECT to_regclass('public.audit_log');
-- Expected: non-null (e.g. "audit_log")
-- If null: the first audit-write call has not yet occurred;
--          trigger one by exercising any API endpoint that logs.
```

Source: `.planning/phases/26-memory-infra-hygiene/26-04-SUMMARY.md`.

### 2. Run the eviction job (v1.6 Phase 25 carry-over)

The memory eviction job runs as a Kubernetes CronJob and prunes
`long_term_facts` rows by recency + importance score. Full operational guide —
CronJob YAML, dry-run mode, audit-then-enforce workflow:

[docs/memory-eviction.md](memory-eviction.md)

### 3. GDPR forget API (v1.6 Phase 25 carry-over)

Purge all stored facts for a user:

```bash
curl -X DELETE \
  "https://<host>/api/v1/memory/forget?user_id=<id>" \
  -H "Authorization: Bearer <admin-claim-JWT>"
```

Full operational usage (audit trail, error codes, partial-purge handling):
[docs/memory-eviction.md](memory-eviction.md).

### 4. bge-m3 model dir layout (TD-07 / Phase 26)

**Primary path (vanilla HF cache):** `{MODEL_DIR}/BAAI/bge-m3/`

Pre-download before first use:

```bash
huggingface-cli download BAAI/bge-m3 --local-dir "$MODEL_DIR/BAAI/bge-m3"
```

If `MODEL_DIR` is writable and `HF_HUB_OFFLINE` is unset, the loader will
auto-download on first invocation.

**Backwards-compat path:** `{MODEL_DIR}/embedding_models/bge-m3/` is still
resolved by the loader for operators on the old layout. No migration required;
both paths work. The vanilla HF cache layout is now the documented primary.

Source: `.planning/phases/26-memory-infra-hygiene/26-05-SUMMARY.md`.

### 5. asyncpg URL `?ssl=disable` handling (TD-03 / Phase 26)

asyncpg's URL parser misreads the literal `ssl=disable` query parameter and
raises a cryptic SSL error. Since Phase 26 this is handled centrally:

```python
# Both services already do this — you do NOT need to handle it per-module:
from utils.asyncpg_helper import prepare_dsn

pool = await asyncpg.create_pool(prepare_dsn(dsn))
```

`utils/asyncpg_helper.prepare_dsn` strips the `ssl=disable` literal before
passing the DSN to asyncpg. `services/memory/memory_service.py` and
`services/audit/audit_service.py` both use this path; the inline copies have
been removed.

**Action required only if you write a NEW module that opens its own asyncpg
pool.** In that case: import `prepare_dsn` from `utils.asyncpg_helper` and
apply it to the DSN before `asyncpg.create_pool`.

Source: `.planning/phases/26-memory-infra-hygiene/26-01-SUMMARY.md`.

---

## Troubleshooting

### 1. Redis-ConnectionError on unit suite

**Symptom:**

```
redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379.
```

during `pytest tests/unit/...`.

**Diagnosis:** The test is hitting the production `get_redis()` codepath
instead of a mock.

**Fix:** Mark the test with `@pytest.mark.uses_redis`:

```python
import pytest

@pytest.mark.uses_redis
def test_something_that_needs_redis():
    ...
```

The `pytest_collection_modifyitems` hook in `tests/conftest.py` automatically
applies the `redis_mock` fixture to every test carrying this marker — no live
Redis required for the unit suite (TD-06 pattern, Phase 27).

Reference: `.planning/phases/27-test-isolation-memory-reliability/27-02-SUMMARY.md`
for the full marker rollout details.

### 2. openai SDK signature drift — 32 pre-existing unit failures

**Symptom:**

```
TypeError: APIError.__init__() missing 1 required positional argument: 'request'
```

from: `test_agent_pipeline_refactor.py`, `test_agent_sse.py`,
`test_pipeline_coverage.py`, `test_feedback_ab_forward.py`,
`test_memory_controller.py`, `test_recall_tool.py`.

**Diagnosis:** openai SDK ≥ v1.x changed the `APIError.__init__` signature;
these tests construct it with the old shape. This is a pre-existing failure
that has been latent on `master` since v1.5 (the lint gate previously masked
it).

**Workaround:** Skip-mark the failing tests locally or update the constructor
call to pass a `request` argument. A systematic fix is tracked as v1.8 backlog
**OAI-01** (see `.planning/REQUIREMENTS-v1.8.md`).

### 3. asyncpg DSN `ssl=disable` literal misread

**Symptom:** asyncpg connect failure with a cryptic SSL error when `PG_DSN`
(or `DATABASE_URL`) contains `?ssl=disable`.

**Fix:** Do NOT bypass `utils/asyncpg_helper.prepare_dsn`. If you wrote a new
module that opens its own asyncpg pool, add:

```python
from utils.asyncpg_helper import prepare_dsn

pool = await asyncpg.create_pool(prepare_dsn(os.environ["DATABASE_URL"]))
```

Existing call sites in `memory_service.py` and `audit_service.py` already
apply `prepare_dsn` (TD-03, Phase 26).

### 4. Event-loop singleton leaks after marker rollout (+14)

**Symptom:** An integration test fails with:

```
RuntimeError: There is no current event loop in thread 'MainThread'
```

after applying `@pytest.mark.uses_redis` (from troubleshooting item 1 above).

**Diagnosis:** A module-level singleton was constructed under a stale event
loop. The marker rollout (Phase 27) tightened test isolation, surfacing
pre-existing TD-02-style leaks.

**Workaround pattern:** Rebuild the singleton via the `create_app()` factory
from `tests/factories/app.py` (Phase 27 SC-1):

```python
from tests.factories.app import create_app

@pytest.fixture
def app():
    return create_app()
```

This ensures each test gets a fresh app instance with its own event loop
context.

Tracked as v1.8 backlog **EVT-01** (see `.planning/REQUIREMENTS-v1.8.md`).

### 5. `test_extractor_e2e.py` FileNotFoundError on bge-m3

**Symptom:**

```
FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found
```

when running `tests/integration/test_extractor_e2e.py`.

**Diagnosis:** The `embedder_or_mock` fixture monkeypatches the embedder AFTER
`AgentQueryPipeline.__init__` has already called `get_embedder()` →
`HuggingFaceEmbedder.__init__` raises. This is a pre-existing fixture-ordering
bug, not introduced by v1.7.

**Workarounds (pick one):**

1. Pre-download bge-m3 to `$MODEL_DIR/BAAI/bge-m3/` (see [Ops §4](#4-bge-m3-model-dir-layout-td-07--phase-26)).
2. Apply the mock-at-consumer-path pattern (CLAUDE.md §"Mock at consumer path")
   at the embedder **import site** rather than after `__init__`:
   ```python
   # Patch before the pipeline is constructed:
   monkeypatch.setattr("services.vectorizer.embedder.HuggingFaceEmbedder.__init__",
                       lambda self, *a, **kw: None)
   ```
3. Move the fixture patch earlier in the test lifecycle (fixture teardown
   ordering fix).

See `.planning/phases/27-test-isolation-memory-reliability/deferred-items.md`
for full analysis and the three suggested fix paths. Tracked as v1.8 backlog
**TEST-INFRA-01** (see `.planning/REQUIREMENTS-v1.8.md`).

---

*Near-duplicate guard note (TD-04 / v1.7):* `LongTermMemory.save_fact` emits a
`MEMORY_NEAR_DUPLICATE_SKIPPED` audit row when the embedding cosine distance
to an existing fact is < 0.05. In v1.7 this is **audit-mode only** — the
INSERT still runs. Silent-skip enforcement is v1.8 scope (SK-01).
