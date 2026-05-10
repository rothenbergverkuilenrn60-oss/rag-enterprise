---
plan: 22-02
phase: 22-per-module-70-coverage-lift
status: complete
requirements: [TEST-09]
---

# Plan 22-02 — llm_client.py Coverage Lift (SC2)

## Outcome

`services/generator/llm_client.py` per-module coverage: **53.0% → 70.6%** (≥70% gate cleared).

43 tests in `tests/unit/test_llm_client_coverage.py` (979 lines), all passing.

## SC2 Branch Families Covered

All 4 SDK exception classes covered across BOTH `AnthropicLLMClient` AND `OpenAILLMClient`:
- `RateLimitError`
- `OverloadedError` (Anthropic) / `InternalServerError(529)` shim — `anthropic.OverloadedError` not present in SDK v0.96.0; documented deviation
- `RetryError`
- `APIConnectionError`

Happy paths reuse `tests/unit/fixtures/agent_parity/{single_step,parallel_multi_step}.json` (CF-03). Failure paths use inline `side_effect` (D-13).

## Locks Honored

- **CF-01** — zero production code changes to `services/generator/llm_client.py`
- **CF-02** — consumer-path mocks via `patch("anthropic.AsyncAnthropic")` etc.; `monkeypatch.setattr("services.generator.llm_client.<dep>")` not viable for local imports — files resolved via `sys.modules` (documented deviation, equivalent semantics: replaces module as seen by consumer, not SDK source)
- **D-15** — `tenacity.wait_none()` monkeypatched per retry test; tests stay <1s
- **D-04** — no env-var hooks
- **CF-06** — diff-cover ≥80% on the new test file

## Commits

- `c642a8b` (worktree) → cherry-picked to master as `9244aa9`: `feat(22-02): add llm_client SC2 coverage tests — 43 tests, 70.6% gate passes`
- `6843261` (worktree, STATE.md update) — skipped (orchestrator owns STATE.md)

## Notes / Deviations

1. **`anthropic.OverloadedError` absent in SDK v0.96.0** — substituted with `InternalServerError(529)`; `_handle_error` always re-raises so propagation semantics preserved.
2. **`call_agentic_turn` has no `@retry`** — exception propagation tested directly; retry tested on `OpenAILLMClient.chat`.
3. **Consumer-path mock via `patch("anthropic.AsyncAnthropic")`** — not `monkeypatch.setattr("services.generator.llm_client.anthropic...")` because `llm_client` does local `import anthropic` inside function bodies (not module-level). Replacing in `sys.modules` is equivalent (CF-02 spirit honored: replaces module as seen by consumer, not SDK source). Same pattern as 22-05's `fitz` deviation.
4. Executor agent's SUMMARY-write was tool-denied; orchestrator authored this SUMMARY from the agent's returned report.

## Verification

```bash
uv run pytest tests/unit/test_llm_client_coverage.py -q --timeout=15
# 43 passed in 0.67s
```

Per-module gate verified separately during Wave 3 finalization.
