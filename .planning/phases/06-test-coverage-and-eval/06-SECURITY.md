---
phase: 06
slug: test-coverage-and-eval
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-27
---

# Phase 06 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| CI runner → GitHub Secrets | OPENAI_API_KEY and RAG_API_BASE_URL passed only via `${{ secrets.* }}` | External API key (confidential) |
| Generator → holdout docs | generator reads holdout_manifest.json paths only; never reads non-listed corpus | Document metadata (internal) |
| eval_ci_gate.py → RagasEvaluator → judge LLM | Outbound call to OpenAI on main-branch CI pushes | QA pair questions + RAG responses (may contain PII if corpus has PII) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-06-01 | Information Disclosure | Test files leaking real SECRET_KEY | mitigate | `os.environ.setdefault("SECRET_KEY", literal-test-value)` in all 11 test files before service import | closed |
| T-06-02 | Tampering | Singleton mutation across tests | mitigate | autouse fixtures reset `_X_service = None` post-yield in test_nlu_service.py:16, test_memory_service.py:26, test_ab_test_service.py:26 | closed |
| T-06-03 | Denial of Service | Test suite hanging on async tasks | mitigate | `timeout = 60` in pytest.ini; fakeredis `aclose()` in teardown (test_memory_service.py:23, test_ab_test_service.py:23) | closed |
| T-06-04 | Spoofing | Tests hitting real Ollama/Redis | mitigate | Instance-level monkeypatching before any HTTP call; CI runs without network access | closed |
| T-06-05 | Information Disclosure | Audit tests writing to real file paths | mitigate | `AuditService.__new__` bypasses init; `settings.audit_db_enabled` patched to False; `_setup_audit_logger` patched via `patch.object` | closed |
| T-06-06 | Tampering | Singletons leaking across tests | mitigate | autouse resets: `_audit_service` (test_audit_service.py:14), `_event_bus` (:13), `_feedback_service` (:13), `_knowledge_service` (:13) | closed |
| T-06-07 | Denial of Service | Event bus dispatch loop hanging | mitigate | All 4 event bus tests wrap `bus.start()` in try/finally with `bus.stop()` (test_event_bus.py:36,55,89,111) | closed |
| T-06-08 | Elevation of Privilege | Tests running with real DB credentials | mitigate | Zero `asyncpg.connect`/`create_pool` calls in unit tests; pool always mocked | closed |
| T-06-09 | Information Disclosure | OPENAI_API_KEY logged to CI output | mitigate | ci.yml:253–254 passes key only via `${{ secrets.* }}`; eval_ci_gate.py never echoes key material | closed |
| T-06-10 | Tampering | Eval contamination from indexed docs | mitigate | holdout_manifest.json (12 entries) is single source of truth; test_qa_dataset.py:45–55 asserts every `source_doc` ∈ manifest on every PR | closed |
| T-06-11 | Denial of Service | Eval gate burning API budget on every PR | mitigate | ci.yml:237 `if: github.ref == 'refs/heads/main' && github.event_name == 'push'` — gate absent from PR runs | closed |
| T-06-12 | Repudiation | CI passes silently on None RAGAS metrics | mitigate | eval_ci_gate.py:26 explicit None-first guard; test_eval_ci_gate.py:72–86 proves None → SystemExit(1) | closed |
| T-06-13 | Elevation of Privilege | PR adds docs without holdout discipline | mitigate | test_qa_dataset.py:45–55 asserts all `source_doc` ∈ holdout_manifest.json; runs in unit-tests job on every PR | closed |
| T-06-14 | Spoofing | RagasEvaluator field name drift | mitigate | All 4 gate behaviors tested in test_eval_ci_gate.py (pass:23, low-faithfulness:39, low-relevancy:55, None:72) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-27 | 14 | 14 | 0 | gsd-security-auditor (Claude) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-27
