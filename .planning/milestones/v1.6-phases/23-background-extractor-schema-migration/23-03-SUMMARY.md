---
phase: 23
plan: 03
subsystem: agent
tags: [sub-agent, pydantic-v2, frozen-model, literal-types, model-validator, call_agentic_turn, provider-singleton, mem-03]
requires:
  - utils.models.AgenticTurn               # text-only call_agentic_turn helper shape
  - services.generator.llm_client.BaseLLMClient
  - services.generator.llm_client.AnthropicLLMClient
  - services.generator.llm_client.OpenAILLMClient
  - services.generator.llm_client.get_llm_client
  - services.memory.memory_service.ConversationTurn
  - config.settings.settings.llm_max_tokens
provides:
  - utils.models.ExtractedFact             # frozen Pydantic V2 model w/ cross-field validator
  - services.agent.extractor.Extractor     # async run(user_turn, ai_turn) → list[ExtractedFact]
  - services.agent.extractor.get_extractor # lazy module-level singleton accessor
  - services.agent.extractor.dispatch_extraction  # STUB — body filled in Plan 23-05
  - services.agent.extractor._EXTRACTOR_SYSTEM    # 1049-char Chinese system prompt
  - config.settings.Settings.extractor_enabled    # bool (default True)
  - config.settings.Settings.extractor_model      # str | None (reserved; not consumed v1.6)
  - config.settings.Settings.extractor_provider   # Literal["openai","anthropic"] | None
affects:
  - tests/unit/test_extractor_schema.py    # 10 schema gates GREEN
  - tests/unit/test_extractor.py           # 11 unit gates GREEN
tech-stack:
  added: []                                # zero new packages — verifier pattern reuse only
  patterns:
    - "verifier.py provider-singleton bypass clone (Pitfall P-09)"
    - "Pydantic V2 frozen + cross-field @model_validator(mode='after')"
    - "post-LLM bucket pinning (Literal[0.2, 0.5, 0.8] + category↔importance map)"
    - "BaseException swallow at sub-agent boundary (Phase 12 isolation contract / D-01)"
    - "fire-and-forget dispatch wrapper signature stability (stub now, body later)"
key-files:
  created:
    - services/agent/extractor.py          # 214 LOC (in [120,250] target band)
    - tests/unit/test_extractor_schema.py  # 136 LOC, 10 collected tests
    - tests/unit/test_extractor.py         # ~270 LOC, 11 collected tests
  modified:
    - utils/models.py                      # +51 lines (ExtractedFact class only; no edits to existing models)
    - config/settings.py                   # +9 lines (3 extractor_* fields + comment block)
decisions:
  - "eng-review A2 amendment honored end-to-end: Extractor.run takes BOTH user_turn and ai_turn (not singular ai_turn), prompt format `USER: {user[:2000]}\\nASSISTANT: {ai[:2000]}`, system prompt contains the A2 sentinel sentence."
  - "dispatch_extraction shipped as STUB in Plan 23-03 (signature only) so Plan 04 + downstream consumers can import the symbol without waiting on Plan 23-05's body fill-in."
  - "List-shape defensive guard on parsed['facts'] (not just .get with default): rejects {\"facts\": \"not a list\"} explicitly via isinstance check rather than relying on for-loop iterating string chars."
metrics:
  duration: "5m 46s"
  completed: "2026-05-16T07:41:31Z"
  tests_added: 21       # 10 schema + 11 unit (5 of 7 functions are parametrized)
  files_created: 3
  files_modified: 2
  lines_added: ~480
---

# Phase 23 Plan 03: ExtractedFact + Extractor Sub-Agent Summary

Built the MEM-03 Extractor sub-agent infrastructure — frozen `ExtractedFact` Pydantic V2 model with cross-field bucket-pinning validator, `services/agent/extractor.py` cloning the verifier provider-singleton + defensive-parse skeleton (with three deltas: BaseException swallow, post-LLM top-3 truncation by importance, dual-turn A2 signature), `get_extractor()` singleton accessor, `dispatch_extraction` stub (body fills in Plan 23-05), and three new `extractor_*` settings fields. Zero new packages; 21/21 tests GREEN; ruff + mypy --strict clean on touched files.

## What Landed

### `utils/models.py` (+51 LOC, append-only)
- `ExtractedFact(BaseModel)` immediately after `VerifierVerdict` (line 679).
- `model_config = ConfigDict(frozen=True)` — immutability mandatory.
- `fact: str` with `@field_validator("fact")` enforcing non-empty-after-strip + ≤200 chars + strips leading/trailing whitespace.
- `category: Literal["stable_preferences", "recurring_topics", "transient_context"]`.
- `importance: Literal[0.2, 0.5, 0.8]`.
- `@model_validator(mode="after")` cross-field check: `{stable_preferences:0.8, recurring_topics:0.5, transient_context:0.2}[category] != importance` → `ValueError`.

### `config/settings.py` (+9 LOC, append-only)
Inserted immediately after `verifier_provider` block (line 295):
- `extractor_enabled: bool = True`
- `extractor_model: str | None = None`
- `extractor_provider: Literal["openai", "anthropic"] | None = None`
With grouping comment block referencing Plan 23-05 dispatch gate + verifier_model precedent.

### `services/agent/extractor.py` (NEW, 214 LOC)
- Module docstring documents A2 dual-turn rationale + D-06 history-isolation + D-01 best-effort contract.
- `_EXTRACTOR_SYSTEM` (1049 chars) — verbatim Chinese prompt from RESEARCH §Pattern 3 + the A2 amendment sentence ("Extract facts about the USER. The USER message carries direct preference signals; the ASSISTANT message provides context but is NOT a fact source itself.") placed near the top per plan acceptance criteria.
- `class Extractor` (~110 LOC):
  - `__init__` → `self._llm: BaseLLMClient = self._resolve_llm()`
  - `_resolve_llm()` — line-for-line verifier mirror; settings field swap.
  - `async run(self, user_turn: ConversationTurn, ai_turn: ConversationTurn) -> list[ExtractedFact]` — A2 signature. Prompt formatted as `f"USER: {user_turn.content[:2000]}\nASSISTANT: {ai_turn.content[:2000]}"`. `except BaseException as exc:  # noqa: BLE001` swallow per Phase 12 isolation contract.
  - `_parse_and_truncate(raw)` — `re.search(r"\{.*\}", raw, re.DOTALL)` first-JSON extraction; `JSONDecodeError` → `[]`; `isinstance(raw_facts, list)` guard; accept up to 5 LLM rows; per-row `ExtractedFact.model_validate` with silent `ValidationError` drop; stable sort by `-importance`; slice `[:3]`.
- `_extractor: Extractor | None = None` + `def get_extractor() -> Extractor` lazy singleton.
- `def dispatch_extraction(user_turn, ai_turn, user_id, tenant_id) -> None` — STUB body returns `None` with docstring pointing at Plan 23-05.

### `tests/unit/test_extractor_schema.py` (NEW, 10 collected tests)
- `test_extracted_fact_frozen` — model_config['frozen'] is True; mutation raises.
- `test_category_importance_bucket_pairing` — 7 parametrized rows covering all 1:1 valid + 4 mismatch failures.
- `test_fact_length_validator` — empty / whitespace-only / 201-char rejected; 200-char accepted; whitespace stripped.
- `test_literal_rejection` — out-of-whitelist category + out-of-bucket importance both raise.

### `tests/unit/test_extractor.py` (NEW, 11 collected tests)
- `test_settings_extractor_fields_present` — defaults verified.
- `test_resolve_llm_provider_bypass` — 3 branches: `"anthropic"` → `AnthropicLLMClient`; `"openai"` → `OpenAILLMClient`; `None` → `get_llm_client()` sentinel.
- `test_run_truncates_top3_by_importance` — 5-fact payload → 3 returned with `[0.8, 0.8, 0.5]` ordering and `"user prefers React"` preserved in slot 0 (stable-sort tie-break).
- `test_run_returns_empty_on_llm_exception` — sub-case A `Exception("provider down")` + sub-case B custom `BaseException` subclass (avoids `CancelledError` semantics conflation).
- `test_run_returns_empty_on_malformed_json` — 5 parametrized sub-cases (empty, plain text, markdown-wrapped malformed, wrong-shape facts-as-string, category/importance mismatch).
- `test_get_extractor_singleton` — `a is b`; after reset `c is not a`.
- `test_run_passes_user_and_ai_turn_truncated_to_2000_each` — A2 amendment gate; asserts `kwargs["messages"]` exactly matches the 2000-char-per-side `"USER: ...\nASSISTANT: ..."` body.

## Verification Status

- **Test count: 21/21 GREEN** (10 schema + 11 extractor; 5 of 7 extractor test functions are parametrized → 11 collected).
- **Ruff: clean** on all 5 touched files (`utils/models.py`, `config/settings.py`, `services/agent/extractor.py`, both new test files).
- **Mypy `--strict`: zero errors specific to `services/agent/extractor.py`.** Baseline mypy errors exist in unrelated pre-existing files (`services/retriever/retriever.py` and 11 others — 163 total) — out of scope per executor scope-boundary rule.
- **No regressions:** verifier (17) + memory_schema + memory_pool all still GREEN.
- **All acceptance-criteria grep gates pass** (every gate in Plan 23-03 §acceptance_criteria for Tasks 1, 2, 3 — including the A2-amended ones: `grep 'user_turn.content[:2000]'` = 1 match, `grep 'def run(self, user_turn: ConversationTurn, ai_turn: ConversationTurn)'` = 1 match, `grep 'def dispatch_extraction(user_turn: ConversationTurn, ai_turn: ConversationTurn,'` = 1 match).
- **Line count: 214** (within plan target [120, 250]).
- **`_EXTRACTOR_SYSTEM` size: 1049 chars** (well above >500 acceptance gate); contains all three whitelist categories, all three refusal rules (A/B/C), the strict JSON output shape, and the A2 sentinel sentence.

## Deviations from Plan

None — plan executed exactly as written (with A2 amendments respected throughout per the task prompt's explicit instructions; A2 was already in PLAN.md via commit ce37aca, not a runtime deviation).

One micro-decision applied (Claude's discretion bullet inside `_parse_and_truncate`): used `isinstance(raw_facts, list)` guard instead of try/except TypeError on the for-loop init. The plan acceptance-criteria fixture `'{"facts": "not a list"}'` would otherwise iterate the string character-by-character — the `isinstance` check fails fast at the right boundary and is what the plan's narrative description ("if `parsed.get("facts", [])` is not iterable (e.g. a string)") actually requires.

## Authentication Gates

None encountered. The extractor sub-agent does not perform any auth-bearing operations; all mocks at the consumer path.

## Commits

| Hash      | Type     | Description                                                                   |
| --------- | -------- | ----------------------------------------------------------------------------- |
| d9ec223   | test     | RED — failing ExtractedFact schema gates (4 tests + 7 parametrized rows)      |
| 63c025d   | feat     | GREEN — ExtractedFact Pydantic V2 frozen model + cross-field validator         |
| a3ca425   | test     | RED — extractor unit tests (6 RED) + settings.extractor_* fields (1 immediate GREEN) |
| 33b5fdd   | feat     | GREEN — `services/agent/extractor.py` (Extractor + get_extractor + dispatch stub) |

## Known Stubs

| Symbol                  | File                          | Reason                                                                                                                              |
| ----------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `dispatch_extraction`   | services/agent/extractor.py   | Body deliberately empty in Plan 23-03; Plan 23-05 wire-in fills body (`asyncio.create_task(...)` + `task.add_done_callback(log_task_error)`). Signature is final per A2 — Plan 05 will NOT change it. |

`extractor_model` field in settings is reserved (not consumed in v1.6 — mirrors `verifier_model` precedent). Intentional, documented in the comment block.

## TDD Gate Compliance

Per-task RED→GREEN sequence enforced:
1. `test(23-03): RED schema gates` (d9ec223) → `feat(23-03): ExtractedFact GREEN` (63c025d) — Task 1 cycle complete.
2. `test(23-03): extractor RED + settings` (a3ca425) → `feat(23-03): Extractor module GREEN` (33b5fdd) — Tasks 2 + 3 cycle complete.

Each `feat(...)` commit is preceded by a corresponding `test(...)` commit in git log. No fast-pathing.

## Self-Check: PASSED

- ✓ `services/agent/extractor.py` exists (214 LOC)
- ✓ `tests/unit/test_extractor_schema.py` exists
- ✓ `tests/unit/test_extractor.py` exists
- ✓ `utils/models.py` contains `class ExtractedFact` at line 679
- ✓ `config/settings.py` contains all 3 `extractor_*` fields
- ✓ All 4 commits present in git log (d9ec223, 63c025d, a3ca425, 33b5fdd)
- ✓ 21/21 plan-scoped tests GREEN; ruff clean on every touched file
