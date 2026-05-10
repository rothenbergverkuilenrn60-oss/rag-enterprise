---
phase: 20-websearchtool-real-implementation-tavily
plan: 03
subsystem: planner-allowlist-contract
status: complete
type: tdd
tasks_completed: 2  # RED + GREEN; REFACTOR documented as no-op (single-line edit)
tags: [allowlist, planner, integration-test, tdd, contract-test, sc3]
gates:
  red:
    commit: 3dddfb0
    message: "test(20-03): RED — failing planner-picks-web_search integration tests"
  green:
    commit: 23b360a
    message: "feat(20-03): GREEN — add web_search to AGENT_TOOL_ALLOWLIST"
  refactor:
    commit: null
    note: "No-op — single-line literal edit cannot meaningfully refactor (plan acknowledges)."
requires:
  - "Plan 20-02 — WebSearchTool real impl + D-02 description (planner reads it)"
  - "Plan 20-02 — registry @register on WebSearchTool (so schemas_for sees it)"
provides:
  - "AGENT_TOOL_ALLOWLIST = ['search_knowledge_base', 'refine_search', 'web_search']"
  - "Two-fixture SC3 contract test (real-time → web_search; in-corpus → search_knowledge_base)"
  - "D-01 byte-identity guardrail (test_agent_system_prompt_unchanged_d01)"
affects:
  - "Plan 20-04 — UI render branch reads chunk_type='web' on RetrievedChunks (no shared edits)"
  - "Phase 21 — verifier inherits enriched allowlist; no further allowlist work in v1.5"
tech-stack:
  added: []  # No new dependencies — wiring-only edit + new test file
  patterns:
    - "Consumer-path stub LLM (Planner.__init__(llm=stub) — CONTEXT D-04)"
    - "schemas_for(provider, names=AGENT_TOOL_ALLOWLIST) — picked up by reference at 3 call sites"
    - "Source-text guardrail asserting verbatim _AGENT_SYSTEM anchor (D-01)"
key-files:
  modified:
    - path: services/pipeline.py
      role: "AGENT_TOOL_ALLOWLIST literal extended; comment block updated to Phase 20 wording"
      lines_added: 4
      lines_removed: 2
  created:
    - path: tests/integration/test_planner_picks_web_search.py
      role: "SC3 two-fixture integration contract + allowlist precondition + D-01 source guardrail"
      lines_total: 156
decisions:
  - "REFACTOR is a documented no-op — the GREEN edit is one literal + one comment block. The plan explicitly accepts this."
  - "Three of four RED tests fail (allowlist + realtime + in-corpus precondition) when web_search is missing from schemas. The fourth (D-01 prompt guardrail) passes both before and after — it is a one-way ratchet that detects future drift."
  - "Test B (in_corpus) carries the same `web_search schema missing` precondition as Test A (realtime). This makes the SC3 contract symmetric: the SAME schemas list must satisfy BOTH branches, so the allowlist precondition is the joint enforcement point."
metrics:
  duration_minutes: ~3
  completed_date: "2026-05-10"
  files_touched: 2
  lines_added_pipeline_py: 4
  lines_removed_pipeline_py: 2
  test_count_added: 4
  full_unit_suite: "790 passed, 1 skipped"  # unchanged from 20-02 baseline
  integration_suite_new: "4 passed (test_planner_picks_web_search.py)"
---

# Phase 20 Plan 03: AGENT_TOOL_ALLOWLIST + SC3 Integration Test Summary

**One-liner:** Wire `web_search` into the planner-visible tool surface via a one-line `AGENT_TOOL_ALLOWLIST` extension, gated by a four-test integration contract (allowlist precondition, realtime → web_search, in-corpus → search_knowledge_base, D-01 prompt guardrail) that drove the edit RED→GREEN with full byte-identity of `_AGENT_SYSTEM`.

## TDD Gate Sequence

| Gate     | Commit    | Lines added | Tests state                                                   |
| -------- | --------- | ----------- | ------------------------------------------------------------- |
| RED      | `3dddfb0` | tests +156  | 3/4 fail (allowlist + realtime + in-corpus); D-01 anchor passes |
| GREEN    | `23b360a` | source +4 / -2 | 4/4 pass; full unit suite 790 passed, 1 skipped (no regressions) |
| REFACTOR | (none)    | n/a         | Documented no-op — plan accepts (single-line literal edit cannot meaningfully refactor) |

REFACTOR omission is by plan design (`<acceptance_criteria>`: "TDD discipline: 2 commits in RED → GREEN order; no REFACTOR commit"). Body of the GREEN commit is 1 literal + 3 comment lines; there is no structure to extract.

## Tasks Completed

### Task 1 — RED: failing integration test (commit `3dddfb0`)

Created `tests/integration/test_planner_picks_web_search.py` with four tests:

| Test                                              | What it asserts                                                                                                                          | RED state            |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| `test_allowlist_includes_web_search`              | `AGENT_TOOL_ALLOWLIST == ['search_knowledge_base', 'refine_search', 'web_search']`                                                       | FAIL (allowlist drift) |
| `test_realtime_query_picks_web_search`            | After `schemas_for(allowlist)`, `web_search` schema present; stubbed-LLM tool_use → `ToolPlan.steps[0].name == "web_search"`             | FAIL (schemas missing web_search) |
| `test_in_corpus_query_picks_search_knowledge_base` | Same `schemas_for(...)` exposes both `web_search` and `search_knowledge_base`; stubbed-LLM tool_use → `ToolPlan.steps[0].name == "search_knowledge_base"` | FAIL (schemas missing web_search precondition) |
| `test_agent_system_prompt_unchanged_d01`          | `services/pipeline.py` source contains BOTH the verbatim `_AGENT_SYSTEM = """\` declaration shape AND the verbatim opening phrase `你是企业知识库的智能问答助手` | PASS (unchanged at RED time) |

#### Stub LLM pattern (consumer-path mock per CONTEXT D-04)

```python
class _StubLLM:
    provider_name: str = "openai"
    def __init__(self, turn): self._turn = turn
    async def call_agentic_turn(self, *, messages, tools, system):
        return self._turn
```

The real `Planner` runs end-to-end; only the LLM client (`call_agentic_turn`) is replaced with a canned `AgenticTurn` containing one `tool_use` block.

#### `_StubLLM` injection idiom

```python
plan = await Planner(llm=_StubLLM(canned)).plan_from_messages(
    messages=[{"role": "user", "content": query_text}],
    tools=tools,
    system=None,
)
```

Direct constructor injection — no `monkeypatch.setattr` needed since `Planner.__init__` accepts `llm: Any | None`.

#### RED evidence

```
$ uv run pytest tests/integration/test_planner_picks_web_search.py -v -m integration
tests/integration/test_planner_picks_web_search.py::test_allowlist_includes_web_search FAILED
tests/integration/test_planner_picks_web_search.py::test_realtime_query_picks_web_search FAILED
tests/integration/test_planner_picks_web_search.py::test_in_corpus_query_picks_search_knowledge_base FAILED
tests/integration/test_planner_picks_web_search.py::test_agent_system_prompt_unchanged_d01 PASSED
==================== 3 failed, 1 passed, 1 warning in 0.67s ====================
```

Failure messages name the precondition concretely:
- `AssertionError: assert 'web_search' in ['search_knowledge_base', 'refine_search']`
- `AssertionError: web_search schema missing from planner tool list`

#### Acceptance grep gates (RED)

```
grep -c "_StubLLM" tests/integration/test_planner_picks_web_search.py            → 3   (≥3 ✓)
grep -c "pytestmark"                                                              → 1   (=1 ✓)
grep -c "pytest.mark.integration"                                                 → 1   (=1 ✓)
grep -c "import services.agent.tools.web_search"                                  → 2   (≥1 ✓)
grep -c "你是企业知识库的智能问答助手"                                              → 1   (=1 ✓)
grep -cE "assert .* in src"                                                       → 2   (≥2 ✓)
grep -c "Replace with the verbatim assertion before commit"                       → 0   (=0 ✓)
```

### Task 2 — GREEN: append `"web_search"` to AGENT_TOOL_ALLOWLIST (commit `23b360a`)

The single-line literal edit at `services/pipeline.py:598` (post-edit: line 600 — comment block grew by 2 lines).

#### Exact diff

```diff
@@ -594,8 +594,10 @@ _SYNTHESIS_SYSTEM: str = """\
 # Module-level constant (AGENT-06 / CONTEXT.md D-12).
 # The cap is enforced by the orchestrator outer loop; Executor runs exactly
 # one ToolPlan per call and does NOT enforce this limit internally.
 MAX_ITERATIONS: int = 5

 # Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
-# WebSearchTool is registered but excluded here (placeholder — v1.5+).
-AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]
+# Phase 20: web_search joins the allowlist with the real Tavily impl
+# (services/agent/tools/web_search.py). Empty TAVILY_API_KEY is a runtime
+# short-circuit per CONTEXT D-03 — no startup-time filtering here.
+AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]


 class AgentQueryPipeline:
```

`git diff --numstat` reports `4 insertions, 2 deletions = 6 changed lines` (≤ 12 acceptance ceiling).

#### Acceptance grep + runtime gates (GREEN)

```
$ APP_MODEL_DIR=/tmp SECRET_KEY=test-secret-key-... uv run python -c \
    "from services.pipeline import AGENT_TOOL_ALLOWLIST; print(AGENT_TOOL_ALLOWLIST)"
['search_knowledge_base', 'refine_search', 'web_search']

$ grep -c '"web_search"' services/pipeline.py
1

$ grep -nE 'AGENT_TOOL_ALLOWLIST: list\[str\] = \["search_knowledge_base", "refine_search", "web_search"\]' services/pipeline.py
600:AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]

$ git diff --numstat services/pipeline.py | awk '{print $1+$2}'
6   (≤12 ✓)
```

#### Test results post-GREEN

```
$ uv run pytest tests/integration/test_planner_picks_web_search.py -v -m integration
tests/integration/test_planner_picks_web_search.py::test_allowlist_includes_web_search PASSED
tests/integration/test_planner_picks_web_search.py::test_realtime_query_picks_web_search PASSED
tests/integration/test_planner_picks_web_search.py::test_in_corpus_query_picks_search_knowledge_base PASSED
tests/integration/test_planner_picks_web_search.py::test_agent_system_prompt_unchanged_d01 PASSED
========================= 4 passed, 1 warning in 0.60s =========================

$ uv run pytest tests/unit -q | tail -1
================ 790 passed, 1 skipped, 316 warnings in 14.60s =================
```

Unit suite still at the 20-02 baseline (790/1) — no regressions from the allowlist extension. The 3 `schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)` call sites at `pipeline.py:789/:862/:1089` pick up the new value by reference; no other edits in `pipeline.py`.

#### mypy / ruff gates (GREEN)

```
$ uv run ruff check services/pipeline.py
All checks passed!

$ uv run mypy --strict services/pipeline.py | tail -1
Found 296 errors in 28 files (checked 1 source file)
```

`296` is the exact v1.4 baseline (recorded in 20-02 SUMMARY: "v1.4 close baseline (296 errors = baseline; 0 new)"). The allowlist-literal edit added 0 new mypy errors — the literal type is unchanged at `list[str]`.

### Task 3 — REFACTOR: documented no-op

The GREEN edit is one literal `["search_knowledge_base", "refine_search", "web_search"]` plus three lines of explanatory comment. There is nothing to extract, no duplication to dedupe, no naming to clarify, and no structure to reshape. The plan's `<task type="auto">` block for Task 2 is the terminal task; the `<acceptance_criteria>` explicitly states "TDD discipline: 2 commits in RED → GREEN order; no REFACTOR commit". This SUMMARY documents the no-op explicitly so the absence of a `refactor(20-03):` commit in `git log` is unambiguous, not a missed gate.

## D-01 Byte-Identity Verification

The `_AGENT_SYSTEM` literal block (now lines 619–635 in services/pipeline.py — shifted +2 from 617–633 by the comment growth above it) is byte-identical to its v1.4 form. Verified by:

1. **Line-level diff scope** — `git diff 9cbc0ab..23b360a -- services/pipeline.py` shows exclusively the allowlist literal (line 598 → 600) and three comment lines above it. No lines anywhere in the 619–635 range are touched.
2. **Source-text grep** — `grep -nE "^(    _AGENT_SYSTEM = |你是企业知识库|<strategy>|</strategy>|<rules>|</rules>)" services/pipeline.py` produces the identical anchor sequence at the new offsets.
3. **Test D guardrail** — `test_agent_system_prompt_unchanged_d01` asserts both anchors are present in the source. The test passes both at RED-time (allowlist not yet edited) and at GREEN-time (allowlist edited, prompt untouched). Future drift on either anchor will fail Test D.

D-01 contract from CONTEXT (`"`_AGENT_SYSTEM` prompt at `services/pipeline.py:617-665` is BYTE-IDENTICAL to v1.4"`) is satisfied — the byte content is unchanged; only the line numbers shifted by the +2-line comment growth above the block.

## Plan Verification Block — All Pass

```
pytest tests/integration/test_planner_picks_web_search.py -v -m integration  → 4 passed
pytest tests/unit -q                                                          → 790 passed, 1 skipped
python -c "from services.pipeline import AGENT_TOOL_ALLOWLIST; ..."           → ['search_knowledge_base', 'refine_search', 'web_search']
ruff check services/pipeline.py                                               → All checks passed!
mypy --strict services/pipeline.py | tail -1                                  → Found 296 errors (= baseline)
git log --oneline | grep -E "^[0-9a-f]+ (test|feat)\(20-03\)"                 → 2 commits (test → feat order)
git diff 9cbc0ab..23b360a -- services/pipeline.py | range 619..635           → empty (D-01 verified)
```

## Deviations from Plan

### D1. Pytest config requires `-m integration` opt-in (no auto-fix; expected env behavior)

**Found during:** First RED test invocation.

`pytest.ini` `addopts = -m "not integration"` deselects integration tests by default. The plan's `<verify><automated>` block uses `pytest tests/integration/...` without `-m integration`, which deselects all 4 tests. Resolution: ran with `-m integration` to opt in for the RED/GREEN evidence. Not a code change; documented here so any future re-run of the verification block needs the explicit marker. No deviation in the test file or source — the marker on `pytestmark` is correctly placed; the gate is at the `addopts` level.

### D2. RED count is 3/4 (matches plan body), not 4/4 (Test D passes both at RED and GREEN)

**Found during:** RED gate execution.

The plan body for Task 1 explicitly anticipates this: "*Tests A and B fail … Test C fails on the same assertion; Test D passes (since allowlist is unchanged at this point — the prompt is also unchanged). At least 3 of 4 tests RED — that's the gate.*" Test D is a one-way ratchet against future D-01 drift; it is intentionally always-green at this plan's RED-and-GREEN times. Not a deviation, but called out so the 1 PASS in the RED log is not misread as a faulty test.

### D3. `pytest.mark.asyncio` warning on Test D (synchronous test under module-level pytestmark)

**Found during:** Both RED and GREEN runs.

```
PytestWarning: The test <Function test_agent_system_prompt_unchanged_d01> is marked with
'@pytest.mark.asyncio' but it is not an async function.
```

`pytestmark = [pytest.mark.asyncio, pytest.mark.integration]` applies the asyncio mark to all four tests in the module, including Test D which is synchronous (it reads source text from disk; no async I/O). The warning is harmless — pytest-asyncio gracefully no-ops on sync functions. Not addressed in this plan (the plan specifies the module-level pytestmark verbatim; splitting the marker would deviate from the `grep -c "pytestmark"` returns 1 acceptance criterion). Acceptable noise; future cleanup would use a per-test `@pytest.mark.asyncio` decorator on the three async tests instead of the module marker.

## Threat Flags

None — the plan's threat register is satisfied:
- **T-20-12** (allowlist tampering): the literal is a build-time tracked-source constant; no runtime mutation surface added.
- **T-20-13** (LLM names a non-allowlisted tool): the only registered+allowlisted tools after Plan 20-03 are `search_knowledge_base`, `refine_search`, `web_search` — exactly the intended planner-visible surface.
- **T-20-14** (D-01 silent drift): Test D embeds both anchors verbatim; CI fails on any future edit dropping or altering either.
- **T-20-15** (`_StubLLM` exfiltration): the class is defined inside `tests/integration/`; pytest never imports test modules from production code paths.

## Hand-Off Note for Plan 20-04

Plan 20-04 (UI render branch) reads only:
```javascript
const m = s.metadata || {};
m.chunk_type      // === "web" → render URL=<host> branch
m.source          // the Tavily URL → input to hostOf()
```
No further `services/pipeline.py` edits scheduled in Phase 20. The `AGENT_TOOL_ALLOWLIST` constant is now stable for v1.5 — Phase 21 verifier inherits it as-is; Phase 22 coverage tests will assert `"web_search" in AGENT_TOOL_ALLOWLIST` per the deferred-items note in the plan.

The integration test in this plan is the SC3 acceptance evidence — Plan 20-04 does not need to re-test the planner contract; it only needs the `chunk_type === "web"` ternary branch and a UI-side smoke fixture.

## Self-Check: PASSED

**Files claimed:**
- `services/pipeline.py` (modified, +4 / -2 lines around line 598→600) — FOUND
- `tests/integration/test_planner_picks_web_search.py` (created, 156 lines) — FOUND

**Commits claimed:**
- `3dddfb0` (RED, test) — FOUND in `git log`
- `23b360a` (GREEN, feat) — FOUND in `git log`

**TDD gate compliance:**
- `git log --grep="^test(20-03):"` → 1 commit (RED `3dddfb0`)
- `git log --grep="^feat(20-03):"` → 1 commit (GREEN `23b360a`)
- `git log --grep="^refactor(20-03):"` → 0 commits (intentional no-op per plan)
- Order in git log: RED → GREEN (verified `git log --oneline | grep "(20-03)"`)

**Plan must_haves contract:**
- Truth 1 (`AGENT_TOOL_ALLOWLIST == ["search_knowledge_base", "refine_search", "web_search"]`) — ✓
- Truth 2 (planner schema list includes `web_search`; verified by Test A precondition + Test B precondition) — ✓
- Truth 3 (real-time query → `ToolPlan.steps[0].name == "web_search"`) — ✓ Test A
- Truth 4 (in-corpus query → `ToolPlan.steps[0].name == "search_knowledge_base"`) — ✓ Test B
- Truth 5 (`_AGENT_SYSTEM` byte-identical to v1.4) — ✓ Test D + diff scope check

All 2 artifacts (`services/pipeline.py` and `tests/integration/test_planner_picks_web_search.py`) declared in the plan's `must_haves.artifacts` are present and contain the required substrings (`"web_search"` literal in pipeline.py; `test_realtime_query_picks_web_search` symbol in the test file).
