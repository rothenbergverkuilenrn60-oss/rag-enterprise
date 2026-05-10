---
phase: 21-agent-05-multi-agent-debate-sub-agent-verifier
plan: 01
subsystem: config-foundation
status: complete
tasks_completed: 2
tags: [config, settings, verifier, agent-05]
requires: []
provides:
  - "Settings.verifier_model: str | None (None default)"
  - "Settings.verifier_provider: Literal['openai','anthropic'] | None (None default)"
affects:
  - "Plan 21-03 — services/agent/verifier.py reads settings.verifier_provider in Verifier._resolve_llm()"
  - "Plan 21-05 — SwarmQueryPipeline.run() debate hop uses settings.verifier_model in audit metadata model_label"
tech-stack:
  added: []
  patterns: ["Pydantic V2 BaseSettings field (no validator); case-insensitive env binding"]
key-files:
  modified:
    - path: config/settings.py
      lines: "288-294"
      role: "2 new BaseSettings fields + 5-line section comment, between llm_stream and # Swarm divider"
  created:
    - path: tests/unit/test_settings.py
      lines: "1-20"
      role: "smoke test pinning both verifier defaults to None"
decisions:
  - "Both fields default to None; verifier reuses peer provider via existing get_llm_client() factory (D-05 default branch)"
  - "No field_validator — provider-key absence (ANTHROPIC_API_KEY='') already fails at AnthropicLLMClient.__init__ (P-09)"
  - "verifier_model is shipped but documented as not-yet-wired-to-per-call-model in v1.5 (Pitfall P-09 / Assumption A3)"
  - "Literal narrowed to ['openai','anthropic'] only — azure/ollama excluded from v1.5 verifier hop"
  - "Inserted adjacent to llm_max_tokens block (LLM-related grouping) per PATTERNS.md, mirroring the Tavily block precedent"
metrics:
  duration_minutes: ~5
  completed_date: "2026-05-10"
  files_touched: 2
  lines_added: 27
---

# Phase 21 Plan 01: Verifier Settings Foundation Summary

**One-liner:** Two Pydantic V2 BaseSettings fields (`verifier_model`, `verifier_provider`, both `None`-default) adjacent to `llm_max_tokens` — the configuration foundation Plans 21-03 (`Verifier._resolve_llm()`) and 21-05 (`SwarmQueryPipeline.run()` debate hop audit metadata) consume.

## Tasks Completed

### Task 1 — `config/settings.py` (commit `8dde058`)

Added two `BaseSettings` fields plus a 5-line section comment block directly after `llm_stream: bool = True` (line 287), before the `# ════ … Swarm` divider — keeping LLM-related fields grouped per the precedent set by the Tavily block (lines 276–279):

```python
# Verifier sub-agent (Phase 21, AGENT-05) ──────────────────────────────────
# verifier_provider="openai"|"anthropic" overrides peer provider; None = reuse.
# verifier_model is reserved (per-call model override not wired in v1.5; see
# 21-RESEARCH.md Pitfall P-09 / Assumption A3). Plan 21-05 logs it in audit
# metadata; Plan 21-03 does NOT consume verifier_model in v1.5.
verifier_model:    str | None = None
verifier_provider: Literal["openai", "anthropic"] | None = None
```

- No `Field(alias=...)` — `case_sensitive=False` (Settings model_config) already binds `VERIFIER_PROVIDER` env var.
- No `field_validator` / `@model_validator` — provider-key absence already fails at `AnthropicLLMClient.__init__` / `OpenAILLMClient.__init__` (P-09 default branch).
- `_validate_security` model_validator (line 410) NOT extended — verifier fields have no security cross-checks.
- `active_model` property (line 450-458) NOT modified — Plan 21-05 audit row uses `settings.verifier_model or settings.active_model`.

**Verification evidence:**
- `grep -cE '^\s*verifier_model:\s+str' config/settings.py` → `1` (single field declaration)
- `grep -cE '^\s*verifier_provider:\s+Literal' config/settings.py` → `1` (single field declaration)
- `APP_MODEL_DIR=/tmp SECRET_KEY=… uv run python -c "from config.settings import settings; …"` → `OK` (both defaults are `None`)
- `uv run ruff check config/settings.py` → `All checks passed!`
- `uv run mypy --strict config/settings.py` → 1 pre-existing baseline error at line 105 (`dict` missing type params); zero NEW errors from verifier fields.

### Task 2 — `tests/unit/test_settings.py` (commit `41f7b34`)

`tests/unit/test_settings.py` did not pre-exist (the repo had `test_settings_ocr.py` and `test_settings_validators.py` only). Created a fresh file with one smoke test mirroring the singleton-import pattern of `test_settings_ocr.py`:

```python
def test_verifier_settings_default_none() -> None:
    """Phase 21 AGENT-05 — verifier_model and verifier_provider both default to None."""
    from config.settings import settings
    assert settings.verifier_model is None
    assert settings.verifier_provider is None
```

The test pins the documented `None` defaults; a future regression that flips either default to `""` or to a hard-coded provider string fails this assertion in CI before the swarm verifier silently reroutes.

**Verification evidence:**
- `uv run python -m pytest tests/unit/test_settings.py -k "verifier" -x -v` → `1 passed in 0.05s`
- `uv run python -m pytest tests/unit/test_settings.py -x` → `1 passed in 0.04s` (no regression — no pre-existing tests in this file)
- `grep -c "verifier_model" tests/unit/test_settings.py` → `1`
- `grep -c "verifier_provider" tests/unit/test_settings.py` → `1`
- `uv run ruff check tests/unit/test_settings.py` → `All checks passed!`

## Deviations from Plan

**1. [Spec clarification — not a code deviation] Test file did not pre-exist.**
- **Found during:** Task 2 (`<read_first>` step)
- **Issue:** Plan instructed "append at end of file" assuming `tests/unit/test_settings.py` existed; the file was absent (only `test_settings_ocr.py` + `test_settings_validators.py` were present).
- **Resolution:** Created the file fresh with one smoke test (the pattern the plan suggested); no append-vs-create matters semantically here since the test contents are identical to what the plan specified.
- **Files modified:** `tests/unit/test_settings.py` (created, not modified)
- **Commit:** `41f7b34`

**2. [Spec clarification] Acceptance criterion `grep -c "verifier_model" config/settings.py` → 1 expects 1.**
- The actual grep returns `3` because the inserted section comment legitimately mentions `verifier_model` twice in the explanatory comment block (the plan's own action block specifies that exact comment text).
- The intent of the criterion is "single field declaration; no duplicate field" — verified instead via `grep -cE '^\s*verifier_model:\s+str'` which correctly returns `1`. Same for `verifier_provider`.
- No code change needed; the planner's `<contains>` clause and `<truths>` already align with the field-only interpretation.

No other deviations. No auto-fixed bugs. No architectural changes. No authentication gates.

## Hand-off Notes

### To Plan 21-03 (`services/agent/verifier.py`)
- Module-level `from config.settings import settings` import is the access path.
- `Verifier._resolve_llm()` reads `settings.verifier_provider` and branches:
  - `"anthropic"` → instantiate `AnthropicLLMClient()` (key check happens in `__init__` per P-09)
  - `"openai"` → instantiate `OpenAILLMClient()` (key check happens in `__init__`)
  - `None` (default) → fall through to `get_llm_client()` factory — verifier reuses the peer provider/model.
- `settings.verifier_model` is **not** consumed in 21-03 (per Pitfall P-09 / Assumption A3 — LLM clients lack a per-call model override hook in v1.5).

### To Plan 21-05 (`SwarmQueryPipeline.run()` debate hop)
- Audit metadata `model_label = settings.verifier_model or settings.active_model` — `verifier_model` value is shipped-but-not-wired in v1.5 except for this audit-row label.
- `active_model` property at `config/settings.py:450-458` is unchanged and is the v1.5 default model label source.

## Threat Model Compliance

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-21-01 (provider override w/o key) | mitigate | Satisfied externally — `AnthropicLLMClient.__init__` / `OpenAILLMClient.__init__` already fail at startup when their key env var is empty (`services/generator/llm_client.py:597-598`); no new validator added per Claude's-discretion bullet. |
| T-21-02 (model name in audit row) | accept | No-op for this plan — Plan 21-05 owns the audit-row write. |
| T-21-03 (default flips from None to "") | mitigate | Task 2 `test_verifier_settings_default_none` pins `is None` for both fields; CI catches any future regression. |

## Self-Check: PASSED

- `config/settings.py` modified — `git log --oneline 8dde058 -1` → `feat(21-01): add verifier_model + verifier_provider settings (D-05/P-09)`
- `tests/unit/test_settings.py` created — `git log --oneline 41f7b34 -1` → `test(21-01): pin verifier_model + verifier_provider Settings defaults to None`
- Both commits present in `git log --oneline -5`.
- `pytest tests/unit/test_settings.py -k "verifier"` exits 0.
- Both new fields reachable via `from config.settings import settings`.
