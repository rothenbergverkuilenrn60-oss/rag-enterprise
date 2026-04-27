# SECURITY.md — Phase 6 Security Audit

**Phase:** 06 — Test Coverage and Eval  
**Plans audited:** 06-01, 06-02, 06-03  
**ASVS Level:** 1  
**Audit date:** 2026-04-27  
**Auditor:** claude-sonnet-4-6  

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-06-01 | Information Disclosure | mitigate | CLOSED | All 9 wave-1 test files contain `os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")` before any service import. Verified in: test_tenant_service.py:10, test_nlu_service.py:10, test_memory_service.py:10, test_ab_test_service.py:10, test_embedder.py:15, test_audit_service.py:4, test_event_bus.py:4, test_feedback_service.py:4, test_knowledge_service.py:4. test_eval_ci_gate.py:9 and test_qa_dataset.py:8 also carry the header. |
| T-06-02 | Tampering | mitigate | CLOSED | autouse fixtures reset singletons post-yield in: test_nlu_service.py:16-22 (`_nlu_service`, `_service`); test_memory_service.py:26-30 (`_memory_service`); test_ab_test_service.py:26-31 (`_ab_service`). |
| T-06-03 | Denial of Service | mitigate | CLOSED | pytest.ini:7 sets `timeout = 60`. fakeredis `aclose()` called in teardown at test_memory_service.py:23 and test_ab_test_service.py:23. Note: pytest.ini uses `timeout=60`, not `timeout=30` as declared in plan — the plan's 30-second CLI flags override this during local runs; the global config is conservatively larger, not smaller, so no hang risk is introduced. |
| T-06-04 | Spoofing | mitigate | CLOSED | OllamaEmbedder: `monkeypatch.setattr(embedder, "_client", mock_client)` applied after construction (test_embedder.py:40,52,76,94). Memory/ABTest: `monkeypatch.setattr(svc, "_client"/"_redis", fake_redis)` applied before any async call (test_memory_service.py:38, test_ab_test_service.py:56). No real httpx or Redis calls can reach network — client is patched at instance level. |
| T-06-05 | Information Disclosure | mitigate | CLOSED | `AuditService.__new__(audit_mod.AuditService)` used at test_audit_service.py:26. `settings.audit_db_enabled` monkeypatched to False in relevant tests (test_audit_service.py:40,60). `_setup_audit_logger` patched via `patch.object` in singleton test (test_audit_service.py:143). No real file handles opened. |
| T-06-06 | Tampering | mitigate | CLOSED | autouse singleton resets confirmed in: test_audit_service.py:14-18 (`_audit_service`); test_event_bus.py:13-17 (`_event_bus`); test_feedback_service.py:13-17 (`_feedback_service`); test_knowledge_service.py:13-17 (`_knowledge_service`). All four singletons covered. |
| T-06-07 | Denial of Service | mitigate | CLOSED | All four event bus tests wrap `bus.publish()`/asserts in `try/finally: bus.stop()` (test_event_bus.py:36-45, 55-75, 89-99, 111-125). pytest.ini timeout=60 enforced globally. |
| T-06-08 | Elevation of Privilege | mitigate | CLOSED | Grep of all unit test files for `asyncpg.connect` or `create_pool` outside mock/patch context returns zero results. test_knowledge_service.py substitutes `TransactionalIndexer` with fully mocked embedder/vector_store. No DATABASE_URL consumed in any unit test. |
| T-06-09 | Information Disclosure | mitigate | CLOSED | ci.yml:253-254 passes `OPENAI_API_KEY` and `RAGAS_JUDGE_API_KEY` exclusively via `${{ secrets.OPENAI_API_KEY }}`. eval_ci_gate.py contains no `os.environ` print/log calls — only `sys.stderr` output of threshold values, never key material. GitHub Actions auto-redacts secret values. |
| T-06-10 | Tampering | mitigate | CLOSED | `holdout_manifest.json` exists at eval/datasets/holdout_manifest.json with 12 holdout doc entries. All entries in the tail of qa_pairs.json reference only paths present in the manifest. `test_qa_dataset.py:45-55` (`test_qa_dataset_holdout_only`) asserts every `source_doc` ∈ manifest paths at test time on every PR. |
| T-06-11 | Denial of Service | mitigate | CLOSED | ci.yml:237: `if: github.ref == 'refs/heads/main' && github.event_name == 'push'` on the `eval-gate` job. Gate does not run on PRs. |
| T-06-12 | Repudiation | mitigate | CLOSED | eval_ci_gate.py:26: `if report.avg_faithfulness is None or report.avg_faithfulness < FAITHFULNESS_THRESHOLD` — None is checked first, before comparison. Same pattern at line 30-33 for `avg_answer_relevancy`. test_eval_ci_gate.py:73-86 (`test_gate_fails_on_none_metric`) proves None triggers SystemExit(1). |
| T-06-13 | Elevation of Privilege | mitigate | CLOSED | `test_qa_dataset.py:45-55` runs as part of the unit-tests job on every PR. It reads qa_pairs.json at `data["pairs"]` (matching actual JSON key) and asserts every `source_doc` appears in holdout_manifest.json. |
| T-06-14 | Spoofing | mitigate | CLOSED | test_eval_ci_gate.py covers all 4 gate behaviors: pass (line 23), low faithfulness (line 39), low answer_relevancy (line 55), None metric (line 72). Field names `avg_faithfulness` and `avg_answer_relevancy` are used consistently in eval_ci_gate.py:26,31 and test mocks. |

---

## Unregistered Flags

**06-01-SUMMARY.md Threat Flags:** None declared.  
**06-02-SUMMARY.md Threat Flags:** None declared.  
**06-03-SUMMARY.md Threat Flags:** None declared.

No unregistered flags to log.

---

## Accepted Risks Log

None. All threats carry `mitigate` disposition and are verified closed.

---

## Notable Observations (non-blocking)

1. **T-06-03 — timeout value mismatch:** Plan declares `--timeout=30`; pytest.ini global is `timeout=60`. The plans pass `--timeout=30` explicitly on the CLI for verification commands, which overrides pytest.ini. The global config is more permissive but not dangerously so. No hang risk introduced.

2. **T-06-11 — coverage floor deviation:** 06-03-SUMMARY.md documents that `--cov-fail-under` was lowered from 80% to 46% during execution due to realistic coverage baseline. ci.yml:60 now reads `--cov-fail-under=46`. This is a plan deviation documented in the SUMMARY and is not a threat — the floor still guards against regressions from the actual baseline.

3. **T-06-04 — instance-level vs class-level monkeypatching:** The executor noted (06-01-SUMMARY.md decision 1) that `OllamaEmbedder` stores its client at `__init__` time, requiring instance-level patching. This is correctly implemented and prevents the gap where class-level patching would miss already-constructed instances.

---

## Threats Closed: 14/14
