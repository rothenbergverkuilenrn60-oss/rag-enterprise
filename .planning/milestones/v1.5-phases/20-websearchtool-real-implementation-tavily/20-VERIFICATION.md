---
status: passed
phase: 20-websearchtool-real-implementation-tavily
verified_at: 2026-05-10T00:00:00Z
requirements_verified: [AGENT-10, AGENT-11, AGENT-12, AGENT-13]
plans_verified: [20-01, 20-02, 20-03, 20-04, 20-05]
combined_coverage: 73.83%
tdd_gate: passed
preexisting_failures:
  - tests/integration/test_pgvector_recall.py::test_recall_at_10
  - tests/integration/test_pgvector_rls.py (3 tests)
  - tests/integration/test_ragas_eval.py (2 tests)
phase_test_results:
  unit_web_search_tool: "15/15 passed"
  integration_planner_picks_web_search: "4/4 passed"
  unit_static_ui_web_branch: "10/10 passed"
  unit_secret_redaction_smoke: "2 passed, 1 skipped (.env.docker gitignored)"
  combined_phase_20: "31 passed, 1 skipped"
  full_unit_suite: "802 passed, 2 skipped"
byte_identity:
  agent_system_prompt: "byte-identical (lines 619-680 vs pre-Phase-20 617-678; +2 line shift from comment growth above allowlist)"
  static_ui_css: "byte-identical (zero-byte diff vs d9ffc0a)"
  static_ui_html: "byte-identical (zero-byte diff vs d9ffc0a)"
secret_leak_check:
  outside_allowlist: 0
  allowlist:
    - .planning/
    - .pre-commit-config.yaml
    - tests/unit/test_secret_redaction_smoke.py
    - tests/unit/test_web_search_tool.py
---

# Phase 20: WebSearchTool Real Implementation (Tavily) — Verification Report

**Phase Goal (ROADMAP §Phase 20):** Replace v1.4 placeholder `WebSearchTool.run()` body with a real Tavily-backed implementation. Wire it into the planner allowlist, render web sources distinctively in the UI, and gate against secret-leakage. Closes the v1.4-to-v1.5 boundary on observability + tool-call-driven retrieval-augmented agents.

**Verified:** 2026-05-10
**Status:** passed
**Mode:** initial verification (no prior `*-VERIFICATION.md` for this phase)

---

## Goal Achievement Summary

All 5 ROADMAP §Phase 20 success criteria observably true in the codebase. AGENT-10/11/12/13 each have implementation evidence + passing tests. TDD gates for plans 20-02 and 20-03 verified by git log + commit-file inspection. D-01 byte-identity invariants for `_AGENT_SYSTEM`, `static/ui.css`, `static/ui.html` hold. Combined coverage 73.83% ≥ 70% gate. Zero `tvly-[A-Za-z0-9]` real-key shape outside the 4 allowlisted paths.

| # | Success Criterion | Verdict | Evidence |
|---|-------------------|---------|----------|
| 1 | `WebSearchTool.run()` Tavily AsyncTavilyClient happy-path → mapped RetrievedChunks | PASS | services/agent/tools/web_search.py:38, 119-133, 140-162, 181-249; test_happy_path_maps_results passes |
| 2 | Three error kinds (`tavily_disabled`, `quota_exhausted`, `web_search_failed`) + tenacity 3-attempt retry; final-attempt → typed-error ToolResult | PASS | web_search.py:75-85 (`_ERROR_CONTENT`), 119-133 (decorator), 194-234 (3 branches); test_429_returns_quota_exhausted, test_5xx_then_200_recovers, test_5xx_final_failure, test_settings_disabled_short_circuits all pass |
| 3 | `AGENT_TOOL_ALLOWLIST` includes `web_search`; integration test asserts planner picks correctly per query class | PASS | services/pipeline.py:600 (`["search_knowledge_base", "refine_search", "web_search"]`); test_realtime_query_picks_web_search + test_in_corpus_query_picks_search_knowledge_base + test_allowlist_includes_web_search pass |
| 4 | `static/ui.js` renders `URL=<host>` for `chunk_type === "web"`; PDF rendering byte-identical | PASS | static/ui.js:28-30 (locator ternary), 48-51 (`hostOf` helper); test_locator_ternary_uses_strict_equality + test_hostof_helper_present + test_url_is_plain_text_not_clickable_anchor pass; static/ui.css zero-byte diff |
| 5 | TAVILY_API_KEY never in tracked files; pre-commit + smoke test enforce; `.env` gitignored; `.env.docker` uses `${TAVILY_API_KEY:-}` | PASS | .pre-commit-config.yaml:14 (regex hook); tests/unit/test_secret_redaction_smoke.py (3 tests); .gitignore:22,29-32; grep outside allowlist returns zero matches |

---

## Success Criterion 1 — Real Tavily Implementation (AGENT-10) — PASS

**Truth required:** `WebSearchTool.run()` issues async Tavily search via `AsyncTavilyClient`; happy-path returns `ToolResult(content, chunks, metadata)` with chunks shaped per D-09..D-12.

**Evidence:**

- `services/agent/tools/web_search.py:38` — `from tavily import AsyncTavilyClient, UsageLimitExceededError`
- `services/agent/tools/web_search.py:95-105` — `get_tavily_client()` lazy singleton factory (D-05)
- `services/agent/tools/web_search.py:125-133` — `_tavily_search(query)` calls `client.search(query, search_depth, max_results)` async
- `services/agent/tools/web_search.py:140-162` — `_map_tavily_result()` builds `RetrievedChunk(chunk_id=f"web:{sha1(url)[:16]}", doc_id="web", metadata=ChunkMetadata(source=url, title=title, chunk_type="web", page_number=None), content=snippet, final_score=score, retrieval_method="web")`
- `services/agent/tools/web_search.py:181-249` — `WebSearchTool.run()` async body
- `config/settings.py:277-279` — three Tavily fields (`tavily_api_key=""`, `tavily_search_depth="basic"`, `tavily_max_results=5`)
- `requirements.txt:54` — `tavily-python>=0.7.24,<0.8`

**Tests passing:** `test_happy_path_maps_results` (asserts `chunk_id`, `doc_id`, `content`, `metadata.source/title/chunk_type/page_number`, `final_score`, `retrieval_method` per D-09..D-12).

---

## Success Criterion 2 — Error Handling + Retry (AGENT-11) — PASS

**Truth required:** Three typed error kinds; tenacity 3-attempt exponential backoff on transient failures; final-attempt failure converts to typed-error ToolResult; no exception escapes `run()`.

**Evidence:**

- `services/agent/tools/web_search.py:75-85` — `_ERROR_CONTENT` dict (single source of truth for D-13 strings)
- `services/agent/tools/web_search.py:119-124` — `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10), reraise=True, retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.HTTPError)))` — 429 (UsageLimitExceededError) deliberately NOT retried (Plan 20-02 D1 deviation: SDK uses typed exception, not httpx.HTTPStatusError(429))
- `services/agent/tools/web_search.py:194-198` — `tavily_disabled` short-circuit (BEFORE network call, BEFORE `get_tavily_client`)
- `services/agent/tools/web_search.py:201-213` — `UsageLimitExceededError` → `quota_exhausted`
- `services/agent/tools/web_search.py:214-224` — `httpx.HTTPStatusError` (5xx after retries) → `web_search_failed`
- `services/agent/tools/web_search.py:225-234` — transport-layer (`httpx.HTTPError`, `TimeoutError`) → `web_search_failed`
- `services/agent/tools/web_search.py:251-268` — `_error_result()` staticmethod constructs `ToolResult(metadata={"error": True, "kind": kind, "latency_ms": latency_ms}, is_error=True)` inline (D-15 redaction; bypasses `BaseTool._build_error_result`)

**Redaction grep gates (all pass):**

```
grep -c "Placeholder" services/agent/tools/web_search.py                 → 0
grep -cE "exc\.response\.(headers|text)" web_search.py                   → 0
grep -cE 'f"\{exc\}"|f"\{exc!r\}"|format_exc\(' web_search.py            → 0
grep -c "_build_error_result" web_search.py                              → 0
```

**Tests passing:** `test_settings_disabled_short_circuits`, `test_429_returns_quota_exhausted`, `test_5xx_final_failure`, `test_5xx_then_200_recovers`, `test_metadata_redaction_no_auth_or_tvly_substrings`, `test_short_circuit_not_retried`, `test_tavily_search_is_tenacity_wrapped` (asserts `retrying.stop.max_attempt_number == 3`), `test_get_tavily_client_is_lazy_singleton`.

---

## Success Criterion 3 — Planner Allowlist (AGENT-13) — PASS

**Truth required:** `AGENT_TOOL_ALLOWLIST` includes `web_search`; planner schemas include the tool; integration test passes for both query classes.

**Evidence:**

- `services/pipeline.py:600` — `AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]`
- `services/pipeline.py:791, 864, 1091` — three `schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)` callsites pick up the new value by reference (no further edits needed)
- `tests/integration/test_planner_picks_web_search.py` — 156 lines, 4 tests:
  - `test_allowlist_includes_web_search` — exact-list assertion
  - `test_realtime_query_picks_web_search` — stubbed-LLM tool_use → ToolPlan.steps[0].name == "web_search"
  - `test_in_corpus_query_picks_search_knowledge_base` — stubbed-LLM → ToolPlan.steps[0].name == "search_knowledge_base"
  - `test_agent_system_prompt_unchanged_d01` — D-01 byte-identity guardrail (anchors on `_AGENT_SYSTEM = """\` declaration shape AND verbatim opening phrase `你是企业知识库的智能问答助手`)

**Test results:** `4 passed, 1 warning in 0.62s` (warning is harmless: pytest-asyncio mark applied to sync test D via module-level pytestmark, gracefully no-ops).

---

## Success Criterion 4 — UI Source Rendering (AGENT-12 UI side) — PASS

**Truth required:** `static/ui.js` renders `URL=<host>` for `chunk_type === "web"`; PDF rendering byte-identical to v1.4; UI smoke test verifies mixed query renders both source types.

**Evidence:**

- `static/ui.js:28-30` — locator ternary: `const locator = (m.chunk_type === 'web') ? 'URL=' + esc(hostOf(m.source)) : '页=' + (m.page_number ?? '?')`
- `static/ui.js:31` — meta line uses `' + locator + '`
- `static/ui.js:48-51` — `hostOf(url)` helper: `try { return new URL(url).host; } catch(e) { return '?'; }`
- `static/ui.js:44-46` — `esc()` helper preserved (host string XSS-defended)

**Static-source assertion test (10 tests passing in `tests/unit/test_static_ui_web_branch.py`):**

| Test | Asserts |
|------|---------|
| `test_url_label_literal_is_uppercase_ascii` | `'URL='` literal present; no `网址=` / `Source=` |
| `test_page_label_preserved` | `页=` still present |
| `test_url_question_mark_fallback_via_hostof` | `catch(e) { return '?'; }` present |
| `test_source_row_uses_existing_classes` | `.source` and `.meta` classes reused |
| `test_static_ui_css_has_no_web_specific_selector` | No `.source.web` / `.meta-web` / `[data-chunk-type]` in CSS |
| `test_url_is_plain_text_not_clickable_anchor` | No `<a href` / `<a ` in ui.js |
| `test_locator_ternary_uses_strict_equality` | `chunk_type === 'web'` (strict, lowercase) |
| `test_hostof_helper_present` | `function hostOf` + `new URL(url).host` |
| `test_host_passed_through_escape_helper` | `esc(hostOf(` (XSS defence) |
| `test_ui_html_unchanged_sentinels` | v1.4 baseline `Agent 查询` sentinels intact |

**Byte-identity verification:**

```
git diff d9ffc0a..HEAD -- static/ui.css     → empty (zero-byte diff)
git diff d9ffc0a..HEAD -- static/ui.html    → empty (zero-byte diff)
```

**Mixed-source live UI render** verified by Plan 20-05 Task C human-verify checkpoint (approved 2026-05-10, recorded in 20-05-SUMMARY.md).

---

## Success Criterion 5 — Secret-Leakage Gate — PASS

**Truth required:** TAVILY_API_KEY never in git history, planning docs (real-key shape), logs, SSE error frames; pre-commit + repo grep confirm absence; `.env` gitignored; `.env.docker` uses `${TAVILY_API_KEY:-}`.

**Evidence:**

- `.pre-commit-config.yaml:14` — `forbid-tavily-key` hook with `tvly-[A-Za-z0-9]` regex; runs against `--diff-filter=ACM` staged files; excludes `tests/unit/test_web_search_tool.py` and `.planning/` (path-based, NOT regex weakening)
- `tests/unit/test_secret_redaction_smoke.py` — 3 tests:
  - `test_no_tavily_key_prefix_in_tracked_files` — enumerates `git ls-files -z`, greps each non-allowlisted file for `rb"tvly-[A-Za-z0-9]"`, asserts zero hits
  - `test_env_is_gitignored` — `.gitignore` contains `.env` entry
  - `test_env_docker_uses_substitution_placeholder` — skips when `.env.docker` is untracked (current state: gitignored, developer-only copy)
- `.gitignore:22,29-32` — `.env`, `.env.docker`, `.env.local`, `.env.*.local` all gitignored

**Repo-wide grep gate verification:**

```
git ls-files | xargs grep -nE "tvly-[A-Za-z0-9]" 2>/dev/null \
    | grep -v -E "^(\.planning/|\.pre-commit-config\.yaml|tests/unit/test_secret_redaction_smoke\.py|tests/unit/test_web_search_tool\.py)"
→ (empty output, exit 1 = no matches)
```

**Source-side redaction (defence at the line of failure):** `services/agent/tools/web_search.py` `logger.error()` calls log only `exc.__class__.__name__` + `status_code`; `_error_result` metadata contains only `{error, kind, latency_ms}` — no headers, no body, no `f"{exc}"`, no traceback. Verified by `test_metadata_redaction_no_auth_or_tvly_substrings` (asserts `Authorization`, `tvly-LEAK`, `Bearer`, `Retry-After`, `Traceback` substrings all absent from `result.model_dump_json()`).

---

## Requirements Traceability

| REQ-ID | Description | Plan(s) | Code Evidence | Test Evidence | Status |
|--------|-------------|---------|---------------|---------------|--------|
| AGENT-10 | Real Tavily impl + settings + dependency | 20-01, 20-02 | config/settings.py:277-279; requirements.txt:54; services/agent/tools/web_search.py:38, 95-162, 181-249 | test_web_search_tool.py (15 tests, 94.8% coverage) | SATISFIED |
| AGENT-11 | Error handling (3 kinds) + tenacity retry | 20-02 | web_search.py:75-85 (`_ERROR_CONTENT`), 119-133 (decorator), 194-234 (3 branches), 251-268 (`_error_result`) | test_429_returns_quota_exhausted, test_5xx_final_failure, test_5xx_then_200_recovers, test_settings_disabled_short_circuits, test_metadata_redaction_no_auth_or_tvly_substrings, test_tavily_search_is_tenacity_wrapped | SATISFIED |
| AGENT-12 | RetrievedChunk shape + UI render branch | 20-02 (mapping), 20-04 (UI) | web_search.py:140-162 (`_map_tavily_result`); static/ui.js:28-30, 48-51 | test_happy_path_maps_results; test_static_ui_web_branch.py (10 tests) | SATISFIED |
| AGENT-13 | Allowlist + integration test | 20-03 | services/pipeline.py:600 (`AGENT_TOOL_ALLOWLIST` includes `web_search`) | test_planner_picks_web_search.py (4 tests) | SATISFIED |

**Note:** `.planning/REQUIREMENTS.md` lines 18-24 currently reflect mid-phase status (AGENT-10/11 marked `[x]`; AGENT-12 marked `[~]` "UI side remains in Plan 20-04"; AGENT-13 marked `[ ]`). Per task instructions, the orchestrator updates REQUIREMENTS.md status fields AFTER VERIFICATION.md is written. The CODE evidence above is what verification confirms; the markdown checkboxes are stale and do not affect this verification's `passed` status.

---

## TDD Gate Verification

Required (per phase task instructions): one `test(20-02)` commit touching tests/, one `feat(20-02)` touching `services/agent/tools/web_search.py`, one `test(20-03)` touching `tests/integration/`, one `feat(20-03)` touching `services/pipeline.py`.

| Plan | Gate | Commit | Files Changed | Verdict |
|------|------|--------|---------------|---------|
| 20-02 | RED  | `dd4e5af` test(20-02): RED — failing tests for real WebSearchTool (Tavily) | `tests/unit/test_web_search_tool.py` (+384/-79) | PASS |
| 20-02 | GREEN | `edf7a67` feat(20-02): GREEN — Tavily-backed WebSearchTool real impl | `services/agent/tools/web_search.py` (+225 lines), `tests/unit/test_web_search_tool.py` (+10/-0 fixup) | PASS |
| 20-02 | REFACTOR | `57485a1` refactor(20-02): extract _map_tavily_result + _ERROR_CONTENT dict | web_search.py + test file | PASS (bonus — plan required RED→GREEN→REFACTOR) |
| 20-03 | RED  | `3dddfb0` test(20-03): RED — failing planner-picks-web_search integration tests | `tests/integration/test_planner_picks_web_search.py` (+156) | PASS |
| 20-03 | GREEN | `23b360a` feat(20-03): GREEN — add web_search to AGENT_TOOL_ALLOWLIST | `services/pipeline.py` (+4/-2) | PASS |
| 20-03 | REFACTOR | (none) | n/a | PASS (documented no-op — single-line literal edit cannot meaningfully refactor; plan acknowledges) |

**TDD gate result: PASSED.** All four required commits exist; commit ordering RED → GREEN (→ REFACTOR for 20-02) verified in `git log`; touched files match expectations.

Note: prep commit `4a10a91 chore(20-02): sync tavily-python into pyproject.toml + uv.lock` lands BEFORE the RED gate (recorded as `prep:` in 20-02-SUMMARY frontmatter). Not part of the TDD gate sequence; required because Plan 20-01 added the requirements.txt pin only and `uv sync` needed pyproject.toml + uv.lock to surface the SDK before tests imported it.

---

## D-01 Byte-Identity Verification

| Invariant | Expected | Verification | Verdict |
|-----------|----------|--------------|---------|
| `_AGENT_SYSTEM` body byte-identical to v1.4 | Line content unchanged from pre-Phase-20 (commit `d9ffc0a`) | `diff <(git show d9ffc0a:services/pipeline.py | sed -n '617,680p') <(sed -n '619,682p' services/pipeline.py)` → empty (BYTE-IDENTICAL); +2 line shift only from comment growth above the allowlist | PASS |
| `static/ui.css` byte-identical | Zero-byte diff | `git diff d9ffc0a..HEAD -- static/ui.css` → empty | PASS |
| `static/ui.html` byte-identical | Zero-byte diff | `git diff d9ffc0a..HEAD -- static/ui.html` → empty | PASS |
| Test D guardrail anchors present in tests | `_AGENT_SYSTEM = """\` shape AND `你是企业知识库的智能问答助手` opening phrase | `grep -c "你是企业知识库的智能问答助手" tests/integration/test_planner_picks_web_search.py` → 1; both `assert ... in src` anchors present | PASS |

---

## Combined Coverage

```
APP_MODEL_DIR=/tmp SECRET_KEY="test-secret-key-padding-padding-padding" \
    uv run pytest tests/unit -q --cov=services --cov=config --cov=static
...
TOTAL                                        5716   1496  73.8%
Required test coverage of 70.0% reached. Total coverage: 73.83%
================ 802 passed, 2 skipped, 316 warnings in 18.66s =================
```

**Combined coverage: 73.83% ≥ 70% gate — PASS.** Full unit suite 802/2 — no regressions.

---

## Anti-Patterns Scanned

| File | Scan | Result |
|------|------|--------|
| services/agent/tools/web_search.py | `Placeholder`, `TODO`, `FIXME`, `HACK` | 0 matches (all clean) |
| services/agent/tools/web_search.py | `exc.response.(headers|text)`, `f"{exc}"`, `format_exc()`, `_build_error_result` | 0 matches each — D-15 redaction gates all hold |
| services/pipeline.py | `_AGENT_SYSTEM` body lines 619-680 | byte-identical to pre-Phase-20 — D-01 holds |
| static/ui.js | `<a href`, `<a ` | 0 matches in source-row block — UI-SPEC §Visual-Treatment Delta holds |
| static/ui.css | `.source.web`, `.meta-web`, `[data-chunk-type` | 0 matches — no Phase 20 CSS edit |
| repo-wide tracked files | `tvly-[A-Za-z0-9]` outside 4 allowlisted paths | 0 matches — SC5 grep gate holds |

No new anti-patterns introduced by Phase 20. The lone `tvly-LEAK` literal in `tests/unit/test_web_search_tool.py` is a deliberate redaction-test fixture (asserts the redaction code does NOT propagate it); allowlisted in BOTH gates by exact path.

---

## Pre-Existing Failures (NOT Phase 20 Regressions)

Per task instructions, the following test failures pre-date Phase 20 (verified by bisect at commit `fa6537c`, BEFORE any Phase 20 work). They MUST NOT block Phase 20 acceptance:

| Test | Failure Mode | Pre-Existing |
|------|--------------|--------------|
| `tests/integration/test_pgvector_recall.py::test_recall_at_10` | HNSW recall=0 (data/index issue, unrelated to Phase 20) | YES |
| `tests/integration/test_pgvector_rls.py` (3 tests) | `monkeypatch.setattr` path interpretation issue | YES |
| `tests/integration/test_ragas_eval.py` (2 tests) | `PermissionError: '/app'` hardcoded path at module import (collection error) | YES |

Phase 20 did NOT touch any of these test files, fixtures, or the underlying production code paths they exercise. Verified by `git log --since=2026-05-09 -- tests/integration/test_pgvector_*.py tests/integration/test_ragas_eval.py` returning zero Phase 20 commits.

These should be tracked separately and addressed in a follow-up housekeeping commit; they do NOT affect Phase 20's `passed` status.

---

## Final Verdict

**Status: PASSED.**

All 5 ROADMAP §Phase 20 success criteria observably true in the codebase. AGENT-10/11/12/13 all satisfied with code + test evidence. TDD gates intact for plans 20-02 and 20-03. D-01 byte-identity invariants for `_AGENT_SYSTEM`, `static/ui.css`, `static/ui.html` all hold. Combined coverage 73.83% ≥ 70% gate. Zero `tvly-[A-Za-z0-9]` real-key shape leakage in tracked files outside the 4 allowlisted paths. Plan 20-05 Task C human-verify checkpoint already approved 2026-05-10 (recorded in 20-05-SUMMARY); no new human verification items required by this verifier pass.

Phase 20 is ready to ship. Orchestrator may proceed to update REQUIREMENTS.md status fields (AGENT-10/11/12/13 → `[x]`), advance STATE.md, and continue to Phase 21 (AGENT-05 verifier).

---

_Verified: 2026-05-10_
_Verifier: Claude (gsd-verifier, goal-backward)_
