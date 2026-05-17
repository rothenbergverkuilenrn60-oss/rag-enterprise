# Phase 27 Deferred Items

## tests/integration/test_extractor_e2e.py — pre-existing env-coupling

**Plan:** 27-04 (discovered during regression check)

**Symptom:**
```
FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found
   tests/integration/test_extractor_e2e.py::test_user_turn_writes_user_side_fact_within_2s
```

**Root cause (not caused by 27-04):**
The pipeline constructor (`AgentQueryPipeline.__init__`) calls `get_embedder()` before
the `embedder_or_mock` fixture monkeypatch reaches the consumer path. When
`APP_MODEL_DIR=/tmp` and the bge-m3 model is NOT downloaded locally,
`HuggingFaceEmbedder.__init__` raises FileNotFoundError before the test body runs.

**Verification this is pre-existing:**
- Failure trace contains zero references to `memory_service`, `save_fact`, or
  `save_facts` — purely the embedder init path.
- The fixture pattern (lazy patch after pipeline construction) is the bug.
- Same test would fail on master tip in the same environment.

**Scope ruling:**
Out of scope for 27-04 per executor Rule "Only auto-fix issues DIRECTLY caused by
the current task's changes". Logged here for future fix.

**Suggested fix (deferred):**
- Move `embedder_or_mock` patch earlier in pipeline construction, OR
- Pre-download bge-m3 model in CI fixtures, OR
- Mock `services.vectorizer.embedder.HuggingFaceEmbedder.__init__` directly.
