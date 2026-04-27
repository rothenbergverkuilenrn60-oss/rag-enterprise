---
phase: 03-error-handling-sweep
plan: 02
subsystem: services/pipeline, services/retriever, services/auth, services/vectorizer
tags:
  - error-handling
  - exception-narrowing
  - asyncpg
  - jose-jwt
  - httpx
  - anthropic
key-files:
  modified:
    - services/pipeline.py
    - services/retriever/retriever.py
    - services/auth/oidc_auth.py
    - services/vectorizer/indexer.py
decisions:
  - "D-04: warmup sites (summary-index, version-record, summary-search) narrowed to (RuntimeError, ValueError) with logger.warning; semantics preserved"
  - "D-02: AgentQueryPipeline Anthropic SDK call narrowed to anthropic.APIError (not openai.APIError — different library); import anthropic already present inline"
  - "D-04: CrossEncoderReranker init narrowed to RuntimeError (sentence-transformers raises RuntimeError for CUDA OOM, model load failures)"
  - "D-03: SLA metrics recording bare except narrowed to (ImportError, AttributeError) — dynamic import of retrieval_latency_seconds can only fail with these"
  - "D-04: HyDE and multi_query_expand LLM calls narrowed to (RuntimeError, ValueError) — abstract llm_client.chat() can raise either; non-fatal fallback preserved"
  - "D-02: oidc_auth._verify_oidc split into two try/except blocks — JWKS fetch (httpx.HTTPError) separated from JWT decode (JWTError) per D-05 boundary"
metrics:
  completed_date: "2026-04-24"
  tasks_completed: 2
  files_modified: 4
---

# Phase 03 Plan 02: Exception Narrowing — pipeline.py, retriever.py, oidc_auth.py, indexer.py — Summary

**One-liner:** Narrowed all `except Exception` sites in four external-dependency-heavy files to library-specific types (asyncpg.PostgresError, JWTError, httpx.HTTPError, anthropic.APIError, RuntimeError) with structured logging via exc_info; zero broad catches remain.

## Commits

| Task | Commit  | Description |
|------|---------|-------------|
| 1    | 299e250 | fix(03-02): narrow exception catches in pipeline.py |
| 2    | 7135d66 | fix(03-02): narrow exception catches in retriever.py, oidc_auth.py, indexer.py |

## Per-File Change Table

### services/pipeline.py

| Line (before) | Old catch | New catch | Library | Decision |
|---------------|-----------|-----------|---------|----------|
| 195 | `except Exception as exc` | `except (RuntimeError, ValueError) as exc` | Internal/summary_indexer | D-04 warmup |
| 227 | `except Exception as exc` | `except (RuntimeError, ValueError) as exc` | Internal/version_service | D-04 warmup |
| 316 (query warmup) | `except Exception as exc` | `except (RuntimeError, ValueError) as exc` | Internal/summary_indexer | D-04 warmup |
| 601 | `except Exception as exc` | `except anthropic.APIError as exc` | anthropic SDK | D-02 |

**Before → After:** 4 → 0 `except Exception` sites

### services/retriever/retriever.py

| Line (before) | Old catch | New catch | Library | Decision |
|---------------|-----------|-----------|---------|----------|
| 183 | `except Exception as exc` | `except httpx.HTTPError as exc` | httpx | D-02 |
| 203 | `except Exception as exc` | `except RuntimeError as exc` | sentence-transformers | D-04 warmup |
| 265–269 | `except Exception: pass` | `except (ImportError, AttributeError): pass` | utils.metrics | D-03 |
| 319 | `except Exception as exc` | `except (ValueError, KeyError, ZeroDivisionError) as exc` | pure Python | D-04 |
| 347 | `except Exception as exc` | `except (RuntimeError, ValueError) as exc` | LLM client (HyDE) | D-04 |
| 370 | `except Exception as exc` | `except (RuntimeError, ValueError) as exc` | LLM client (multi-query) | D-04 |
| 654 | `except Exception as exc` | `except asyncpg.PostgresError as exc` | asyncpg | D-01 |

**Before → After:** 7 → 0 `except Exception` sites
**Imports added:** `import asyncpg`, `import httpx`

### services/auth/oidc_auth.py

| Line (before) | Old catch | New catch | Library | Decision |
|---------------|-----------|-----------|---------|----------|
| 118 | `except Exception as exc` | `except JWTError as exc` | python-jose | D-02 |
| 158 | `except Exception as exc` | split: `except httpx.HTTPError as exc` + `except JWTError as exc` | httpx + python-jose | D-02 |

**Before → After:** 2 → 0 `except Exception` sites
**Imports added:** `import httpx`, `from jose import JWTError` (top-level; previously inline in try block)
**Security note:** All JWT error details route to `logger.error(..., reason=type(exc).__name__, exc_info=exc)` only — no raw exception text in return values or HTTP responses (T-03-02-01 mitigation confirmed).

### services/vectorizer/indexer.py

| Line (before) | Old catch | New catch | Library | Decision |
|---------------|-----------|-----------|---------|----------|
| 142 | `except Exception as exc` | `except asyncpg.PostgresError as exc` | asyncpg | D-01 |

**Before → After:** 1 → 0 `except Exception` sites
**Imports added:** `import asyncpg`

## Acceptance Criteria Verification

```
grep -c 'except Exception' services/pipeline.py           → 0  PASS
grep -c 'except Exception' services/retriever/retriever.py → 0  PASS
grep -c 'except Exception' services/auth/oidc_auth.py      → 0  PASS
grep -c 'except Exception' services/vectorizer/indexer.py  → 0  PASS
grep -c 'except asyncpg.PostgresError' services/retriever/retriever.py → 1  PASS
grep -c 'except asyncpg.PostgresError' services/vectorizer/indexer.py  → 1  PASS
grep -c 'JWTError' services/auth/oidc_auth.py              → 3 (1 import + 2 catches)  PASS
grep -nE 'detail=.*str\(exc' services/auth/oidc_auth.py    → 0  PASS (no raw exc text)
grep -nE 'error=.*str\(exc' services/pipeline.py           → 0  PASS
all four files: python3 ast.parse() → OK  PASS
```

## Deviations from Plan

### Auto-applied decisions

**1. [Rule 1 - Claude's discretion] Anthropic SDK: anthropic.APIError (not openai.APIError)**
- **Found during:** Task 1, AgentQueryPipeline loop (line 601)
- **Issue:** Plan interfaces listed `openai.APIError` but the try block imports and uses `anthropic` SDK, not `openai`
- **Fix:** Used `anthropic.APIError` — the correct base exception for the anthropic package's `messages.create` call. The `import anthropic` was already present inline at line 569.
- **Files modified:** services/pipeline.py

**2. [Rule 2 - D-04] oidc_auth._verify_local_jwt changed from logger.debug to logger.error**
- **Found during:** Task 2
- **Issue:** Original site used `logger.debug` — the plan requires `logger.error` for JWT verification failures (every caught exception must log via logger.error)
- **Fix:** Changed to `logger.error("JWT verification failed", reason=type(exc).__name__, exc_info=exc)` — matches D-11 requirement (infrastructure failure, not silent swallow)
- **Files modified:** services/auth/oidc_auth.py

**3. [Rule 2 - D-02] oidc_auth._verify_oidc: split single try/except into two**
- **Found during:** Task 2
- **Issue:** Original `except Exception` covered both JWKS fetch (httpx) and JWT decode (jose) in a single block — splitting allows distinct error messages and proper attribution
- **Fix:** First try/except catches `httpx.HTTPError` from `_get_jwks()` and returns `None`; second try/except catches `JWTError` from `jose_jwt.decode()`
- **Files modified:** services/auth/oidc_auth.py

## Known Stubs

None — all changes are exception-narrowing refactors; no new data flow or rendering paths introduced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. Exception narrowing in oidc_auth.py improves T-03-02-01 mitigation by ensuring JWT error details never surface in return values.

## Self-Check: PASSED

- services/pipeline.py modified: FOUND
- services/retriever/retriever.py created in worktree: FOUND
- services/auth/oidc_auth.py created in worktree: FOUND
- services/vectorizer/indexer.py modified in worktree: FOUND
- Commit 299e250 exists: FOUND
- Commit 7135d66 exists: FOUND
- Zero `except Exception` in all 4 files: VERIFIED
- All 4 files parse cleanly (python3 ast.parse): VERIFIED
