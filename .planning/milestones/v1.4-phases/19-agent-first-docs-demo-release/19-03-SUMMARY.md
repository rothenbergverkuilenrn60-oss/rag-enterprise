---
phase: 19-agent-first-docs-demo-release
plan: 03
subsystem: build
tags: [agent-08, makefile, demo, phase-19, wave-3, sc3]
requires:
  - services.agent._demo_runner.main  # Phase 19 plan 19-02
  - services.agent._demo_stubs.{DEMO_QUERY, DemoStubPlanner, build_demo_registry, make_fake_retrieve_tool}  # Phase 19 plan 19-01
provides:
  - Makefile::demo-agent          # canonical SC3 deliverable
  - Makefile::demo-agent-record   # one-shot maintenance target (plan 19-05 consumer)
affects:
  - docs/demo.cast (consumer — `make demo-agent-record` writes this; plan 19-05 commits it)
  - README.md (consumer — Phase 19 README rewrite references `make demo-agent` in Quick start, D-02)
tech-stack:
  added: []
  patterns:
    - bilingual-makefile-help-strings (Phase 19 honors existing v1.3 convention)
    - command-v-binary-guard (POSIX-portable availability check; actionable error message)
key-files:
  created: []
  modified:
    - Makefile (+10 / -1; ≤ 12 add / 1 rem budget)
decisions:
  - venv-python-not-conda-run: "The plan body specifies `conda run -n torch_env python -m services.agent._demo_runner` to match the existing Makefile style (lines 69, 80, 83, 86, 92, 100, 116-128 all use `conda run`). This WSL2 host has NO conda binary (`which conda` empty); the project's actual Python environment is `.venv/` (uv-managed, Python 3.12.13). Plans 19-01 and 19-02 hit the same constraint and adopted `.venv/bin/python` (Rule 3 - Blocking deviations). For consistency with the upstream stub modules AND to satisfy the hard SC3 acceptance criterion (`make demo-agent` exits 0), this Makefile target uses `.venv/bin/python`. Trade-off: stylistic divergence from existing Makefile targets in exchange for an actually-runnable SC3 deliverable. Future v1.5+ may unify the project on a single Python invocation pattern (uv vs conda) — out of scope for plan 19-03."
  - app-model-dir-default-tmp: "`config/settings.py:22` raises `RuntimeError` at import time if `APP_MODEL_DIR` is unset (CLAUDE.md OPS-01 — `MODEL_DIR` must be set via env var, not hardcoded). The demo runner (plan 19-02) imports `services.pipeline` which imports `config`, so the env var is required for `python -m services.agent._demo_runner` to even start. Recipe uses `APP_MODEL_DIR=${APP_MODEL_DIR:-/tmp}` shell parameter expansion (`$$` escapes for Make) — defaults to `/tmp` when unset, allows user override when set. `/tmp` is fine because the demo's stub LLM + stub tool registry never load any model files."
  - asciinema-guard-uses-command-v: "POSIX-portable `command -v` (vs the bash-specific `which` or `type`) for the asciinema availability guard. Same pattern as standard CI scripts. Error message points users to `pipx install asciinema` (the recommended modern install path)."
  - asciinema-rec-overwrite-flag: "`--overwrite` on `asciinema rec` allows re-recording without an interactive prompt — required because plan 19-05's re-recording workflow runs unattended (T-19-03-03 mitigation: prevents prompt-related stalls)."
metrics:
  duration_minutes: 2
  duration_seconds: 143
  tasks_completed: 1
  commits: 1
  files_created: 0
  files_modified: 1
  lines_added: 10
  lines_removed: 1
  acceptance_grep_checks_passed: 11
  sse_event_types_observed: 5
  events_emitted: 11
  exit_code_observed: 0
  completed_date: 2026-05-09
---

# Phase 19 Plan 03: `make demo-agent` + `make demo-agent-record` — Summary

**One-liner:** Add two PHONY Makefile targets exposing the Phase 19 demo runner — `demo-agent` invokes `python -m services.agent._demo_runner` (plan 19-02), prints the 11-event SSE log to stdout, exits 0 (canonical SC3 deliverable); `demo-agent-record` guards on `asciinema` availability and wraps the demo under `asciinema rec docs/demo.cast --overwrite` for one-shot re-recording (plan 19-05 consumer, D-08 — contributors do NOT need asciinema to run the demo).

## Tasks Executed

| Task | Commit  | Files                                | Status |
| ---- | ------- | ------------------------------------ | ------ |
| T1   | `5793dbe` | `Makefile` (+10 / -1)               | All 11 acceptance grep checks PASS. Recipe simulation: 11 SSE events emitted (1 planner.plan + 4 tool.span.start + 4 tool.span.end + 1 executor.parallel + 1 synthesizer.final), exit 0. asciinema-missing guard: prints actionable error + exit 1. Bilingual `make help` lines render correctly. Diff exactly: 1 PHONY-line modification + 1 inserted ~10-line block. |

## Public Surface (Makefile additions)

| Target              | Help-string                                                       | Recipe |
| ------------------- | ----------------------------------------------------------------- | ------ |
| `demo-agent`        | `演示 Planner→Executor→Synthesizer 4 路并行 (Phase 19, AGENT-08)` | `APP_MODEL_DIR=$${APP_MODEL_DIR:-/tmp} .venv/bin/python -m services.agent._demo_runner` |
| `demo-agent-record` | `录制 docs/demo.cast (维护任务，需要 asciinema)`                   | (1) `command -v asciinema` guard with actionable error; (2) `asciinema rec docs/demo.cast --overwrite --command "..."` wrapping the same `demo-agent` invocation. |

`.PHONY` line modified (line 7) to append `demo-agent demo-agent-record` at the end — every existing PHONY entry preserved.

## Verification Results

`make` is NOT installed on this WSL2 host (`which make` → not found; `apt-get install` requires sudo password unavailable to the agent). All recipe-level verification was performed by **simulating the Make recipe directly via bash** — Make's recipe execution model is `bash -c "<recipe-line>"`, so running the recipe contents in bash is functionally equivalent. The Makefile syntax was independently validated via a Python parser (`/tmp/check_makefile.py` — TAB indentation, target uniqueness, PHONY membership, recipe line shape).

| Check | Command (or simulation) | Result |
| --- | --- | --- |
| AC1: `^demo-agent:` count | `grep -c "^demo-agent:" Makefile` | 1 |
| AC2: `^demo-agent-record:` count | `grep -c "^demo-agent-record:" Makefile` | 1 |
| AC3: PHONY contains both targets | `grep -c "demo-agent demo-agent-record" Makefile` | 1 |
| AC4: section banner | `grep -c "Agent 演示 (Phase 19)" Makefile` | 1 |
| AC5: bilingual help-string | `grep -c "演示 Planner→Executor→Synthesizer 4 路并行" Makefile` | 1 |
| AC6: asciinema invocation | `grep -c "asciinema rec docs/demo.cast" Makefile` | 1 |
| AC7: `python -m` invocations | `grep -c "python -m services.agent._demo_runner" Makefile` | 2 |
| AC8: recipe simulation exit code | `APP_MODEL_DIR=/tmp .venv/bin/python -m services.agent._demo_runner; echo $?` | **0** |
| AC9: 5 SSE event types on stdout | grep `event: planner.plan / tool.span.start / tool.span.end / executor.parallel / synthesizer.final` | 1 / 4 / 4 / 1 / 1 — all 5 types present |
| AC10: total event/data lines | `grep -c '^event: ' && grep -c '^data: '` | 11 / 11 |
| AC11: `make help` shows both targets (simulated) | `grep+awk` recipe ran inline against Makefile | renders both lines with cyan target name + Chinese help-string |
| AC12: asciinema-missing guard error path | `command -v asciinema >/dev/null 2>&1 \|\| echo "..." && exit 1` | exit 1 + `asciinema not installed; install via: pipx install asciinema` |
| AC13: diff stat ≤ 12 add / 1 rem | `git diff --stat HEAD~1 HEAD -- Makefile` | `Makefile \| 11 ++++++++++- (10 insertions, 1 deletion)` |
| AC14: Makefile syntax valid | `/tmp/check_makefile.py` — TAB indentation, target uniqueness, PHONY membership, recipe line shape | PASS |
| AC15: existing targets unchanged | `git diff HEAD~1 HEAD -- Makefile` shows ONLY the PHONY line + the new ~10-line block | confirmed — no incidental edits |

### Per-event detail (AC8/AC9 — recipe simulation stdout)

| seq | event_type             | content (abbreviated)                                                                                                |
| --- | ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 0   | `planner.plan`         | 4-tool ToolPlan: 4× `search_knowledge_base` calls fanned across kb_shards `compliance / finance / engineering / hr`. |
| 1-4 | `tool.span.start` × 4  | one per shard, with span_id + args including the shard kb_shard.                                                     |
| 5-8 | `tool.span.end` × 4    | each `latency_ms=500`, `chunk_count=3`, `is_error=false`, `content_preview="[fixture chunk]"`.                       |
| 9   | `executor.parallel`    | `fan_out=4`, `group_latency_ms=500` — D-05 max-not-sum bound holds (500 < 700).                                      |
| 10  | `synthesizer.final`    | `answer="Found references to 'data retention' across all 4 knowledge bases — see span results above."`.              |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Recipe uses `.venv/bin/python` instead of `conda run -n torch_env python`**
- **Found during:** Pre-flight verification (before Task 1 edit).
- **Issue:** Plan body §`<action>` Change 2 specifies `conda run -n torch_env python -m services.agent._demo_runner`. This WSL2 host has NO conda binary (`which conda` returns empty). Same blocking situation plans 19-01 and 19-02 hit (Deviation #1 in their SUMMARYs). The user's prompt explicitly anticipated this: "If existing Makefile uses `conda run`, document the env-mismatch in your SUMMARY as a Rule 3 deviation and fall back to `python -m`."
- **Fix:** Use `.venv/bin/python` (uv-managed venv, Python 3.12.13 — same interpreter version plans 19-01/19-02 wrote against). The recipe sets `APP_MODEL_DIR=$${APP_MODEL_DIR:-/tmp}` to satisfy `config/settings.py:22`'s import-time env check (CLAUDE.md OPS-01 — `MODEL_DIR` env-var requirement is intentional; `/tmp` works because the demo's stub LLM + stub tool registry never load any model file).
- **Files modified:** `Makefile` recipe lines for both targets.
- **Commit:** `5793dbe`.
- **Trade-off:** Recipe stylistically diverges from the 6+ existing `conda run -n torch_env`-based targets in the same Makefile. Trade-off accepted because: (a) hard acceptance criterion `make demo-agent` exits 0 cannot be satisfied with `conda run` on this host; (b) consistent with the upstream stub modules' choice; (c) future v1.5+ may unify the Makefile on a single Python invocation pattern.

**2. [Rule 3 - Blocking] Recipe-level verification simulated via bash (no `make` binary on host)**
- **Found during:** First attempt to run `make demo-agent` for AC8 verification.
- **Issue:** `which make` returns empty; `make` is not installed on this WSL2 host. `apt-get install make` requires sudo password unavailable to the agent. The plan's hard acceptance criterion is "`make demo-agent` exits 0" — which I cannot literally invoke.
- **Fix:** Three-pronged equivalent verification:
  - **Recipe simulation:** Run the recipe contents directly in bash. Since Make invokes recipe lines via `$(SHELL) -c "<line>"` (default `/bin/sh`, `bash` on this system), running `APP_MODEL_DIR=/tmp .venv/bin/python -m services.agent._demo_runner` in bash is functionally equivalent to what `make demo-agent` would do. Result: exit 0 + 11 SSE events.
  - **Makefile syntax validation:** Wrote `/tmp/check_makefile.py` to parse the Makefile and validate (a) TAB indentation on recipe lines (`cat -A` confirmed `^I` markers), (b) target uniqueness, (c) PHONY membership, (d) recipe-line shape (≥ 1 line for `demo-agent`, ≥ 2 lines for `demo-agent-record`), (e) `## help-string` presence on target lines. Result: PASS.
  - **`make help` simulation:** Ran the help recipe's `grep+awk` pipeline directly. Result: both new targets render correctly with Chinese help-strings.
- **Files modified:** None (verification-time only).
- **Commit:** N/A.
- **Trade-off:** Cannot literally execute `make demo-agent` on this host — but the recipe IS syntactically correct (validated) and IS functionally correct (recipe contents exit 0). Anyone with `make` installed will see `make demo-agent` exit 0 immediately. Future hosts where `make` is installed (CI runners, contributor laptops with build-essential) will see the canonical SC3 deliverable run as designed.

### Auth gates / Architectural questions (Rule 4)

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. The threat register from the plan was satisfied:

| Threat ID | Disposition | Verification |
| --- | --- | --- |
| T-19-03-01 (EoP — `make demo-agent` running with elevated permissions) | accept | Recipe invokes `python -m`, not `sudo`. The runner (plan 19-02) is the same Python entrypoint exercised in `tests/integration/test_demo_agent.py` with no privilege escalation. |
| T-19-03-02 (Info disclosure — `docs/demo.cast` capturing terminal env vars) | mitigate | `demo-agent-record` only records the demo subprocess output (via `--command "..."`). The runner uses placeholder tenant IDs only (verified in plan 19-02 `_demo_runner.py`: 3 occurrences of `demo-tenant`/`demo-user`/`demo-session`, 0 occurrences of `acme`/`production`). Plan 19-05 will gate the cast file with explicit review before commit. |
| T-19-03-03 (Tampering — asciinema rec failing silently producing corrupt cast) | mitigate | `command -v asciinema` guard (verified — exit 1 + actionable message when binary missing). `--overwrite` flag prevents prompt-related stalls. Plan 19-05 will add explicit cast-file integrity check. |

## Known Stubs

The Makefile target invokes `services.agent._demo_runner` which IS the demo's stub-runtime entrypoint (CONTEXT.md D-05 / D-06). No new stubs introduced by this plan — the Makefile is a thin invocation wrapper. The stub-runtime contract is fully owned by plans 19-01 (`_demo_stubs.py`) and 19-02 (`_demo_runner.py`). `make demo-agent` simply makes that runtime accessible from a clean checkout.

## Self-Check: PASSED

- File `Makefile` modified (commit `5793dbe`) ✓
- File `.planning/phases/19-agent-first-docs-demo-release/19-03-SUMMARY.md` exists ✓
- Commit `5793dbe` exists in `git log` (`git log --oneline | head -1` shows `5793dbe feat(19-03-T1): make demo-agent + make demo-agent-record`) ✓
- All 15 acceptance checks PASS ✓
- Recipe simulation: `APP_MODEL_DIR=/tmp .venv/bin/python -m services.agent._demo_runner` exits 0 with 11 SSE events ✓
- Makefile syntax validated: TAB indentation on recipes, both targets defined exactly once, PHONY membership correct, help-strings present ✓
- Diff stat: 10 insertions / 1 deletion — within plan budget (≤ 12 add / 1 rem) ✓
- Existing Makefile targets unchanged: `git diff HEAD~1 HEAD -- Makefile` shows ONLY the PHONY line modification + the new ~10-line block; every existing target/recipe byte-identical ✓
