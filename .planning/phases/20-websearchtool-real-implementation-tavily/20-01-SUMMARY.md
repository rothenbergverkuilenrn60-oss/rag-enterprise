---
phase: 20-websearchtool-real-implementation-tavily
plan: 01
subsystem: config-foundation
status: complete
tasks_completed: 3
tags: [config, tavily, settings, dependency-pin, env-placeholder]
requires: []
provides:
  - "Settings.tavily_api_key / tavily_search_depth / tavily_max_results"
  - "tavily-python>=0.7.24,<0.8 dependency pin"
  - "TAVILY_API_KEY=${TAVILY_API_KEY:-} env placeholder (disk-only; gitignored)"
affects: [Plan 20-02 — services/agent/tools/web_search.py rewrite]
tech-stack:
  added: ["tavily-python>=0.7.24,<0.8 (pin only — not yet imported)"]
  patterns: ["Pydantic V2 BaseSettings field, case-insensitive env binding"]
key-files:
  modified:
    - path: config/settings.py
      lines: "276-279"
      role: "3 new BaseSettings fields adjacent to anthropic_model"
    - path: requirements.txt
      lines: "53-54"
      role: "Tavily SDK pin + section header"
    - path: .env.docker
      lines: "37-40"
      role: "TAVILY_API_KEY substitution placeholder + 2 default-knob lines (gitignored — disk only)"
decisions:
  - "Single Settings entrypoint preserved — no TavilySettings sub-model (CONTEXT D-06)"
  - "No field_validator — empty tavily_api_key is observable behavior, not a startup error (CONTEXT D-03)"
  - "${TAVILY_API_KEY:-} substitution is the only form ever written — never a real tvly- prefix (P-16 prevention)"
  - ".env.docker is gitignored per PROJECT.md core-value contract; placeholder lives on disk only"
metrics:
  duration_minutes: ~3
  completed_date: "2026-05-10"
  files_touched: 3
  lines_added: 10
---

# Phase 20 Plan 01: WebSearch Config Foundation (Tavily) Summary

**One-liner:** Three Pydantic V2 settings fields, one `tavily-python` dependency pin, one `${TAVILY_API_KEY:-}` substitution placeholder — the configuration foundation Plan 20-02 imports.

## Tasks Completed

### Task 1 — `config/settings.py` (commit `efc4fa8`)

Added three `BaseSettings` fields directly after `anthropic_model:` (lines 276–279), matching the column-aligned `:` and `=` style of the surrounding LLM keys:

```python
# Tavily web search (Phase 20, AGENT-10) ───────────────────────────────────
tavily_api_key:        str = ""
tavily_search_depth:   str = "basic"   # SDK accepts: basic | fast | advanced | ultra-fast
tavily_max_results:    int = 5
```

- No `Field(alias=...)` — `case_sensitive=False` already binds `TAVILY_API_KEY` env var to the field.
- No `field_validator` — empty default is the documented `tavily_disabled` short-circuit trigger (D-03).
- No `TavilySettings` sub-model — single Settings entrypoint convention preserved.

**Verification evidence:**
- `grep -c "tavily_api_key:" config/settings.py` → 1
- `grep -c "tavily_search_depth:" config/settings.py` → 1
- `grep -c "tavily_max_results:" config/settings.py` → 1
- `APP_MODEL_DIR=/tmp/models uv run python -c "from config.settings import settings; ..."` → `OK` (defaults `''`, `'basic'`, `5`)
- `uv run ruff check config/settings.py` → `All checks passed!`

### Task 2 — `requirements.txt` (commit `7fff13a`)

Inserted a "Web search" section header + Tavily pin between the LLM SDK block (line 51) and the vector DB clients block (line 56), preserving the existing `# ── … ───` comment shape:

```
# ── Web search ────────────────────────────────────────────────────────────────
tavily-python>=0.7.24,<0.8   # Tavily AsyncTavilyClient (Phase 20, AGENT-10)
```

- Pin range `>=0.7.24,<0.8` from `.planning/research/STACK.md` — locks the documented `AsyncTavilyClient` surface, allows patch upgrades.
- Not installed in this commit; install runs as part of repo install workflow.

**Verification evidence:**
- `grep -c "^tavily-python>=0.7.24,<0.8" requirements.txt` → 1
- `grep -c "^tavily" requirements.txt` → 1 (no duplicates)
- `awk '/^anthropic==/{anth=NR} /^tavily-python/{tav=NR} END{...}'` → anthropic line 51, tavily line 54, ordered correctly
- File ends with single LF (`tail -c 1 | xxd` → `0a`)

### Task 3 — `.env.docker` (disk only, NOT committed — file is gitignored)

Inserted three lines + section header after `ANTHROPIC_MODEL=claude-sonnet-4-6`:

```
# ── Web search: Tavily ────────────────────────────────────────────────────────
TAVILY_API_KEY=${TAVILY_API_KEY:-}
TAVILY_SEARCH_DEPTH=basic
TAVILY_MAX_RESULTS=5
```

**Important:** `.env.docker` is in `.gitignore` (line 30) per PROJECT.md core-value contract: *"Tavily key handling: stored in `.env` only (gitignored); `.env.docker` references via `${TAVILY_API_KEY:-}`; never written into planning docs or commits."* — the file is operationally maintained on disk; this plan applied the change there.

**Verification evidence (file on disk):**
- `grep -c '^TAVILY_API_KEY=\${TAVILY_API_KEY:-}$' .env.docker` → 1 (literal substitution, exact match)
- `grep -c '^TAVILY_SEARCH_DEPTH=basic$' .env.docker` → 1
- `grep -c '^TAVILY_MAX_RESULTS=5$' .env.docker` → 1
- `grep -c "tvly-" .env.docker` → 0 (no real key prefix)
- `grep -nE 'TAVILY_API_KEY=.+[^}]$' .env.docker` → 0 matches (defends against future paste of a real key)

## Plan Verification Block — All Pass

```
APP_MODEL_DIR=/tmp/models uv run python -c "from config.settings import settings; print(repr(settings.tavily_api_key), settings.tavily_search_depth, settings.tavily_max_results)"
→ '' basic 5

grep -c "tavily-python>=0.7.24,<0.8" requirements.txt          → 1
grep -c "^TAVILY_API_KEY=" .env.docker                         → 1   (value: ${TAVILY_API_KEY:-})
grep -rn "tvly-" .env.docker requirements.txt config/settings.py → 0 results (exit 1)
ruff check config/settings.py                                  → All checks passed!
```

## Deviations from Plan

### `.env.docker` not committed

- **Reason:** `.env.docker` is gitignored per PROJECT.md core-value contract and `.gitignore:30` (re-ignored by commit `9c41e68 chore: sync .env.docker from local config, gitignore env files`). The file once was tracked and was intentionally moved to gitignore in v1.0; the placeholder lives on disk only.
- **Effect:** Tasks 1 & 2 produced commits (`efc4fa8`, `7fff13a`); Task 3 produced a verified disk change but no commit.
- **Plan must_haves still satisfied:** the artifacts contract reads "`.env.docker` carries a `TAVILY_API_KEY=${TAVILY_API_KEY:-}` placeholder line" — the file does carry it, verified by grep. The `key_links.from: .env.docker → Settings env-var binding` link is operational regardless of git tracking; Pydantic loads the file at container startup via Docker compose.
- **Rule classification:** This is a Rule 3 / scope-boundary observation, not a bug. Forcing a tracked commit would violate the project's secret-handling policy.

## Threat Flags

None — this plan adds no network endpoints, no auth paths, no schema changes. The threat register's T-20-01 (real-key paste) is mitigated by `${TAVILY_API_KEY:-}` substitution + the SC5 `tvly-` grep already passing.

## Hand-Off Note for Plan 20-02

Plan 20-02 imports settings at module top of `services/agent/tools/web_search.py`:

```python
from config.settings import settings
```

and reads three fields inside `_tavily_search` and the `tavily_disabled` short-circuit branch of `run()`:

- `settings.tavily_api_key` — empty string triggers the `tavily_disabled` ToolResult (D-03 / D-13).
- `settings.tavily_search_depth` — passed to `client.search(search_depth=...)`.
- `settings.tavily_max_results` — passed to `client.search(max_results=...)`.

The `tavily-python>=0.7.24,<0.8` pin is now in `requirements.txt`; Plan 20-02 may `uv add tavily-python` or rely on the repo install workflow to surface the SDK before importing `from tavily import AsyncTavilyClient`.

## Self-Check: PASSED

**Files claimed:**
- `config/settings.py` lines 276–279 — FOUND (3 new tavily fields, verified via `grep -n "tavily" config/settings.py`)
- `requirements.txt` lines 53–54 — FOUND (section header + pin, verified via `awk` ordering check)
- `.env.docker` lines 37–40 — FOUND on disk (gitignored — disk-only artifact)

**Commits claimed:**
- `efc4fa8` (Task 1) — FOUND in `git log`
- `7fff13a` (Task 2) — FOUND in `git log`

**Plan must_haves contract:**
- Truth 1 (3 fields with documented defaults) — ✓
- Truth 2 (`tavily-python>=0.7.24,<0.8` tracked dependency) — ✓
- Truth 3 (`.env.docker` carries `TAVILY_API_KEY=${TAVILY_API_KEY:-}` line, never a real key) — ✓
- Artifacts: all three `contains` strings present — ✓
- Key links: `from config.settings import settings` resolvable; `TAVILY_API_KEY` env binds via case-insensitive name match — ✓
