# Phase 3: Error Handling Sweep - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-22
**Phase:** 03-error-handling-sweep
**Areas discussed:** Exception specificity, Swallowed error policy, create_task callback pattern, Audit log vs structured logger

---

## Exception Specificity

| Option | Description | Selected |
|--------|-------------|----------|
| asyncpg.PostgresError | Catches all Postgres-level errors (connection, query, constraint). Specific enough to not swallow non-DB exceptions. | ✓ |
| asyncpg.exceptions.* | Fine-grained types like UniqueViolationError, ConnectionDoesNotExistError per site. Maximum precision but requires per-call judgment. | |
| Exception + comment | Keep broad catch but add a comment explaining why. Minimal change, lowest risk. | |

**User's choice (DB):** `asyncpg.PostgresError`

| Option | Description | Selected |
|--------|-------------|----------|
| Exception group per library | redis.RedisError, openai.APIError, httpx.HTTPError etc. — library's base exception class. | ✓ |
| OSError + ValueError | Python stdlib IO base types. Works but misses library-specific error info. | |
| Exception (unchanged) | Leave external call sites as-is — only fix DB and internal logic sites. | |

**User's choice (External IO):** Library-specific base exception class per service

---

## Swallowed Error Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Keep log+continue | Genuinely non-fatal — app can run without Redis warmup or Langfuse. Warning logged, service degrades gracefully. | ✓ |
| Re-raise as startup failure | Any warmup failure crashes the app. Forces infrastructure to be ready before app starts. | |

**User's choice (startup errors):** Keep log+continue

| Option | Description | Selected |
|--------|-------------|----------|
| Return structured error | Catch specific exception, log it, return Response(success=False, error=...). Caller gets actionable info. | ✓ |
| Re-raise and let global handler catch | Let FastAPI global_exception_handler convert to 500. Simpler but less specific error messages. | |
| Keep log+continue | Swallow and proceed. Least disruptive. | |

**User's choice (pipeline in-request errors):** Return structured error

---

## create_task Callback Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Shared _log_task_error helper | One module-level helper. All create_task() calls attach it with add_done_callback. DRY, consistent, easy to grep. | ✓ |
| Inline lambda per call site | task.add_done_callback(lambda t: logger.error(...) if t.exception() else None). No helper needed, self-contained. | |
| Global asyncio exception handler | loop.set_exception_handler() globally. Less explicit per-task. | |

**User's choice:** Shared helper

| Option | Description | Selected |
|--------|-------------|----------|
| utils/tasks.py | New utility module. Clean import path, easy to find and test. | ✓ |
| Each file that uses it | Define locally in main.py and event_bus.py. Duplicates the function. | |
| utils/logger.py | Collocate with logger setup. Slightly odd separation of concerns. | |

**User's choice (location):** `utils/tasks.py`

---

## Audit Log vs Structured Logger

| Option | Description | Selected |
|--------|-------------|----------|
| Business events only in audit | Audit = PII blocks, auth failures, tenant violations, explicit rejects. Infrastructure errors go to logger.error only. | ✓ |
| All errors in both | Every exception logged to both audit and structured log. Complete coverage but noisy. | |
| Only where audit already exists | Don't add any new audit.log calls — leave current audit boundaries unchanged. | |

**User's choice:** Business events only in audit

---

## Claude's Discretion

- Exact exception type mappings for less common libraries (langdetect, sentence-transformers, pymupdf)
- Whether to introduce a `_handle_pipeline_error` DRY helper or inline the pattern per site

## Deferred Ideas

None.
