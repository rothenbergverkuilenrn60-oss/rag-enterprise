---
phase: 03-error-handling-sweep
plan: "03"
subsystem: application-layer-error-handling
tags:
  - error-handling
  - exception-narrowing
  - ERR-01
dependency_graph:
  requires:
    - utils.tasks.log_task_error  # plan-01 — create_task wiring untouched
  provides:
    - narrowed exception handling in 9 application-layer files
  affects:
    - services/knowledge/knowledge_service.py
    - services/knowledge/summary_indexer.py
    - services/knowledge/version_service.py
    - services/nlu/nlu_service.py
    - services/memory/memory_service.py
    - services/annotation/annotation_service.py
    - services/mcp_server.py
    - controllers/api.py
    - main.py
tech_stack:
  added:
    - asyncpg (direct import for exception type)
    - httpx (direct import for exception type)
    - redis (direct import for exception type)
    - jose.JWTError (direct import for exception type)
  patterns:
    - library-specific exception narrowing per D-01/D-02/D-03
    - D-04 startup warmup semantics preserved (logger.warning + continue)
    - D-06 shutdown flush semantics preserved (except Exception: pass)
key_files:
  created: []
  modified:
    - services/knowledge/knowledge_service.py
    - services/knowledge/summary_indexer.py
    - services/knowledge/version_service.py
    - services/nlu/nlu_service.py
    - services/memory/memory_service.py
    - services/annotation/annotation_service.py
    - services/mcp_server.py
    - controllers/api.py
    - main.py
decisions:
  - "D-04 startup warmup sites in main.py keep logger.warning with narrowed types — OSError/RuntimeError/asyncpg.PostgresError per service"
  - "D-06 shutdown flush sites (lines 112/118/124 main.py) left unchanged — intentional silent pass"
  - "Redis rate-limit fail-open (main.py) narrowed to redis.RedisError — preserves fail-open semantics"
  - "Auth middleware narrowed to (JWTError, httpx.HTTPError, ValueError) — covers OIDC/local JWT failure modes"
  - "Route handlers in api.py use tuples: (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError)"
  - "Readiness probe catches narrowed to redis.RedisError and asyncpg.PostgresError respectively"
  - "Plan-01 create_task / add_done_callback lines in main.py untouched"
metrics:
  duration: "~20 minutes (split across 2 sessions due to rate limit)"
  completed: "2026-04-24"
  tasks_completed: 2
  files_changed: 9
  commits: 3
---

# Phase 03 Plan 03: Exception Narrowing — Application Layer Summary

## Commits

| Task | Commit  | Description |
|------|---------|-------------|
| 1    | de4d322 | fix(03-03): narrow except Exception in 6 internal service files |
| 2    | 60a675b | fix(03-03): narrow except Exception in controllers/api.py and main.py |
| 3    | 4febce6 | fix(03-03): narrow except Exception in mcp_server.py (gap closure) |

## Deviations

- **03-03 agent hit API rate limit mid-execution** — 6 of 9 files were completed in the first commit (de4d322). The remaining files were completed inline by the orchestrator: api.py + main.py in recovery, mcp_server.py after verifier caught the gap.
- **D-06 shutdown sites kept as `except Exception: pass`** — per plan exemption, these 3 sites in main.py lifespan shutdown are intentionally broad to ensure graceful shutdown regardless of flush failure.

## Self-Check

- [x] No `except Exception` or bare `except:` in any of the 9 files (excluding D-06 exemptions)
- [x] asyncpg.PostgresError used for DB sites (VectorStore warmup, route handlers, retriever)
- [x] redis.RedisError used for Redis sites (rate limiter fail-open, readiness probe)
- [x] openai.APIError + httpx.HTTPError used for LLM/HTTP sites (route handlers)
- [x] jose.JWTError + httpx.HTTPError used for auth middleware
- [x] D-04 startup warmup preserved with logger.warning semantics
- [x] D-06 shutdown flush unchanged
- [x] Plan-01 create_task wiring in main.py untouched
- [x] Every caught exception logged (no silent swallows except D-06)

**Self-Check: PASSED**
