---
phase: 07-ocr-engine-integration
plan: 02
subsystem: extractor + worker + container
tags: [ocr, docker, arq, integration-test, failure-modes, tenacity]
requires:
  - 07-01 (OcrEngine Protocol, PpStructureV3Engine, _paddle_pipeline singleton)
  - settings.ocr_timeout_sec, settings.ocr_concurrency (declared in 07-01)
  - WorkerSettings (existing, ASYNC-02)
provides:
  - PpStructureV3Engine.extract_pdf with timeout + tenacity-once + garbled heuristic
  - services.extractor.ocr_engine._looks_garbled (pure helper)
  - services.ingest_worker.on_startup (pre-warm hook)
  - WorkerSettings.on_startup wired to the pre-warm
  - Dockerfile builder-stage paddleocr install + PPStructureV3 model bake
  - Dockerfile runtime-stage COPY of /home/raguser/.paddlex + PADDLE_PDX_CACHE_HOME
  - scripts/verify_ocr_bake.sh (offline + ownership + size checks)
  - tests/integration/test_ocr_e2e.py (skip-gated GB4785-2019 e2e)
  - pytest.ini integration marker + default-exclude addopts
affects:
  - services/extractor/ocr_engine.py (PpStructureV3Engine.extract_pdf wrapped)
  - services/ingest_worker.py (on_startup added; WorkerSettings extended)
  - Dockerfile (builder + runtime stages)
  - pytest.ini (markers + addopts)
tech-stack:
  added: []
  patterns:
    - "tenacity.AsyncRetrying with retry_if_exception_type(asyncio.TimeoutError) + stop_after_attempt(2)"
    - "asyncio.wait_for(timeout=settings.ocr_timeout_sec) gate per attempt"
    - "Builder→runtime model COPY (no runtime network) + PADDLE_PDX_CACHE_HOME override"
    - "ARQ WorkerSettings.on_startup async hook for cold-start warm-up"
    - "Skip-gated integration test (importlib.util.find_spec) + addopts -m 'not integration'"
key-files:
  created:
    - tests/unit/test_ocr_failure_modes.py
    - tests/unit/test_worker_startup.py
    - tests/integration/test_ocr_e2e.py
    - scripts/verify_ocr_bake.sh
  modified:
    - services/extractor/ocr_engine.py
    - services/ingest_worker.py
    - Dockerfile
    - pytest.ini
decisions:
  - "ASCII regex was already broad (\\x20-\\x7e) — pure '#@!' garbage scores HIGH ASCII, not low; the heuristic correctly fires only on non-CJK non-printable noise (e.g. PaddleOCR's box-drawing/symbol glyphs when recognition collapses). Test 4 uses ■●█¤• to exercise the realistic garbled signature."
  - "Wave 1's _looks_garbled lived in the plan as a stub; this plan promotes it to a tested pure helper at module level so callers (and unit tests) can probe the heuristic without going through extract_pdf."
  - "ERR-01 exemption documented in services/ingest_worker.py:on_startup — broad except logs and continues so a transient pre-warm failure cannot keep the worker permanently down. The first real OCR call will surface a clean error via the normal path."
  - "pytest.ini gets addopts = -m 'not integration' so default `pytest` runs exclude the heavy test cleanly. CI/Docker runs opt in with `-m integration`."
  - "Dockerfile bake uses pip install --find-links=/wheels (paddlepaddle is in the wheels we already built); avoids re-downloading from PyPI mid-build."
  - "PADDLE_PDX_CACHE_HOME env var set explicitly so PaddleX finds the cache regardless of \\$HOME resolution under USER raguser."
metrics:
  duration: ~30 min
  completed: 2026-04-27
  tasks: 5
  commits: 4 (3 task-feat + 1 docs commit forthcoming)
  files_changed: 8
  tests_added: 17
  tests_run: 33
  tests_passing: 33
---

# Phase 7 Plan 02: OCR Failure Modes + Docker Bake + E2E Integration Summary

The OCR engine is now production-deployable: timeouts retry once, OOM
bubbles up cleanly, garbled CJK is flagged not crashed on, model weights
ride along inside the runtime image, the ARQ worker pays the cold-start
once at boot, and a skip-gated end-to-end test exercises the real
GB4785-2019.pdf path inside the built container.

## What landed

| Concern | Implementation |
|---|---|
| **Hard timeout + retry** | `asyncio.wait_for(timeout=ocr_timeout_sec)` inside an `AsyncRetrying` loop with `stop_after_attempt(2)` + `retry_if_exception_type(asyncio.TimeoutError)`; second timeout returns `extraction_errors=["OCR timeout after Xs, retried 1x"]` and `body_text=""` |
| **OOM passthrough** | No `except MemoryError` anywhere in the engine — propagates to ARQ |
| **Garbled-CJK heuristic** | `_looks_garbled(text)` pure helper: `len>=50 ∧ ascii_ratio<0.05 ∧ cjk_ratio<0.30`; logs a warning and returns the dict unchanged |
| **Worker pre-warm** | `services.ingest_worker.on_startup` wired to `WorkerSettings.on_startup`; routes `auto`/`paddle` → `_paddle_pipeline()`; skips on `tesseract`/`none`; tolerates `ImportError` so worker boots without paddleocr |
| **Docker bake (builder)** | `RUN pip install --find-links=/wheels paddlepaddle==3.0.0 'paddleocr[doc-parser]==3.1.*' && python -c "from paddleocr import PPStructureV3; PPStructureV3(...)"` materialises `/root/.paddlex/official_models` |
| **Docker bake (runtime)** | `COPY --from=builder --chown=raguser:raguser /root/.paddlex /home/raguser/.paddlex` + `ENV PADDLE_PDX_CACHE_HOME=/home/raguser/.paddlex` |
| **Verify script** | `scripts/verify_ocr_bake.sh` runs `--network=none` PPStructureV3 instantiation, asserts ≥3 model dirs, owner=`raguser:1001`, prints image size for the SUMMARY delta |
| **E2E test** | `tests/integration/test_ocr_e2e.py` drives `ExtractorService.extract()` against `data/raw/GB4785-2019.pdf`, asserts `chars > 0` and CJK character present, with a wall-clock ceiling preventing retry-loop regressions |
| **Marker hygiene** | `pytest.ini` registers `integration` and adds `addopts = -m 'not integration'` so default runs exclude the heavy test |

## Files changed

| File | Δ |
|---|---|
| `services/extractor/ocr_engine.py` | +66 / -2 (heuristic + AsyncRetrying wrapper) |
| `services/ingest_worker.py` | +43 / -0 (`on_startup` + WorkerSettings wire-up) |
| `Dockerfile` | +20 / -0 (builder bake + runtime COPY + PADDLE_PDX_CACHE_HOME) |
| `pytest.ini` | +3 / -0 (markers + addopts) |
| `tests/unit/test_ocr_failure_modes.py` | **+248 (new)** |
| `tests/unit/test_worker_startup.py` | **+135 (new)** |
| `tests/integration/test_ocr_e2e.py` | **+89 (new)** |
| `scripts/verify_ocr_bake.sh` | **+73 (new)** |

## Test counts

| File | Tests | Result (this env) |
|---|---:|---|
| `tests/unit/test_ocr_failure_modes.py` | 10 | passed |
| `tests/unit/test_worker_startup.py` | 6 | passed |
| `tests/unit/test_ocr_engine.py` (07-01 regression) | 8 | passed |
| `tests/unit/test_settings_ocr.py` (07-01 regression) | 4 | passed |
| `tests/unit/test_extractor_ocr_routing.py` (07-01 regression) | 5 | passed |
| `tests/integration/test_ocr_e2e.py` | 1 | **skipped** (paddleocr not installed locally — expected; runs in container) |
| **Phase 7 unit total** | **33** | **33 passed** |

The plan budgeted 7 + 5 + 1 = 13 new tests; we shipped 10 + 6 + 1 = 17 (split a few tests for tighter failure messages — heuristic pure-fn coverage, OOM/timeout-success branches, semaphore-release regression).

## Key contract checks (per PLAN done-criteria)

```
grep -c 'except MemoryError' services/extractor/ocr_engine.py        => 0  ✓
grep -c 'AsyncRetrying'      services/extractor/ocr_engine.py        => 2  ✓ (1 import + 1 use)
grep -c 'asyncio.wait_for'   services/extractor/ocr_engine.py        => 2  ✓ (1 doc + 1 use)
grep -v '^#' services/extractor/ocr_engine.py | grep -c 'except Exception'  => 0  ✓
grep -c 'except Exception'   services/ingest_worker.py               => 1  ✓ (documented exemption)
grep -c 'PPStructureV3('     Dockerfile                              => 1  ✓
grep -c 'COPY --from=builder.*paddlex' Dockerfile                    => 1  ✓
bash -n scripts/verify_ocr_bake.sh                                   => 0  ✓ (syntax clean)
test -x scripts/verify_ocr_bake.sh                                   => 0  ✓
```

## Image-size delta

**Not measured — Docker build deferred to user per plan scope rule.** The
container build is heavy (~10 minutes for first model download). The
research-projected delta is **+600MB to +1.2GB**; the user should record the
observed delta after running `docker compose build` and replace this estimate
in the next pass through STATE.md.

The verify script's check #4 prints `docker images $IMAGE --format
'{{.Repository}}:{{.Tag}} {{.Size}}'` so the measurement is captured at
verification time without extra steps.

## Worker pre-warm wall-clock

**Not measured** — needs the built image. Research projects 5–15s on CPU.

## Integration test wall-clock

**Not measured** — paddleocr intentionally not installed in this dev env per
plan scope (Tasks 3+5 user-runs only). The test prints elapsed and per-page
when it runs; the user captures this from `pytest -s` output inside the
container.

## Deviations from plan

| Item | Deviation | Rationale |
|---|---|---|
| Test 4 garbled fixture | Plan suggested `"###@@@!!!"`; we use `"■●█¤•"` | The `[\x20-\x7e]` ASCII regex matches `#@!` — pure ASCII garbage scores HIGH ASCII, so it correctly does NOT trigger `<5% ASCII + <30% CJK`. The heuristic targets *non-printable / non-CJK noise* (PaddleOCR's failure mode is box-drawing / symbol glyphs, not letter punctuation). The test was wrong; the heuristic is right. |
| Test count: 10 instead of 7 | Added 3 pure-function heuristic tests + 1 OOM + 1 retry-success branch | Tighter failure messages; no scope creep — all branches the heuristic + retry expose are now pinned. |
| Plan grep `'PPStructureV3()'` (no args) | Code has `PPStructureV3(use_doc_orientation_classify=False, …)` | Constructor needs args matching the singleton's signature for cache parity; semantic intent (instantiate once at build time) preserved. Reported as `grep -c 'PPStructureV3('` which still returns 1. |
| `pytest.ini` `addopts` added | Plan said "confirm marker registered" only | Adding `-m 'not integration'` to default opts is cleaner than relying on `find_spec` skip alone — the heavy test is now opt-in everywhere, not just hosts without paddleocr. |
| Task 4 (verify script) folded into Task 3 commit | Plan numbered them separately | The script is meaningless without the Dockerfile changes; coupling them in one commit keeps the build+verify story atomic. |
| Docker build NOT executed | Plan task 3 verify clause runs `docker compose build` | Per user prompt scope rule: "Do NOT actually rebuild the Docker image during execution." User runs the build separately. |

No deviations triggered Rule 4 (architectural). All decisions preserve the documented contracts.

## Threat model verification

All `mitigate` dispositions in the plan's threat register are present:

* **T-07-07 (DoS, hanging PDF)** — `asyncio.wait_for(timeout=ocr_timeout_sec)` + tenacity retry-once → `extraction_errors`. Total budget = 2 × `ocr_timeout_sec` ≈ 240s default.
* **T-07-08 (DoS, OOM)** — no `except MemoryError`; propagates to ARQ where `arq_job_timeout=300s` + retry policy bound the blast radius.
* **T-07-10 (Repudiation, untracked failures)** — `extraction_errors` field carries timeout failures into `IngestionResponse`; ARQ `keep_result=86400s` (Phase 5 ASYNC-02) preserves the record.

Threats T-07-06, T-07-09, T-07-11 are `accept`; no implementation needed.

## Threat surface scan

| Flag | File | Description |
|------|------|-------------|
| _none_ | — | No new network endpoints, auth paths, or trust-boundary surface introduced. The Dockerfile bake step is build-time-only and runs against PyPI + paddleocr's CDN, both already in the v1.0 trust boundary. The worker `on_startup` runs locally with no IO. |

## Outstanding work / next-step instructions for the user

The dev-env tasks are complete; production verification needs the container:

1. **Build the image** — heavy step deferred to user:
   ```bash
   docker compose build rag-api
   # or:
   docker build -t rag-enterprise:phase7-test .
   ```
   Expected wall-clock: 10–20 minutes for the first build (PaddleOCR model
   download dominates). Image size growth: research-projected +600MB–1.2GB.
2. **Verify the bake**:
   ```bash
   bash scripts/verify_ocr_bake.sh rag-enterprise:phase7-test
   ```
   Expect exit 0; the final line prints the image size — record it for the
   STATE.md image-delta entry.
3. **Run the e2e integration test** inside the container:
   ```bash
   docker run --rm -v $(pwd)/data:/app/data:ro \
     -e APP_MODEL_DIR=/app/cache \
     -e SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))') \
     rag-enterprise:phase7-test \
     python -m pytest tests/integration/test_ocr_e2e.py -m integration -x -s
   ```
   Expect 1 passed, with the printed `[OCR e2e]` line giving pages, chars,
   and per-page latency for the SUMMARY follow-up.

## Self-Check: PASSED

Files exist:
* `tests/unit/test_ocr_failure_modes.py` — FOUND
* `tests/unit/test_worker_startup.py` — FOUND
* `tests/integration/test_ocr_e2e.py` — FOUND
* `scripts/verify_ocr_bake.sh` — FOUND (executable)

Commits exist (verified via `git log --oneline -5`):
* `9e8246d` (Task 1 — failure modes) — FOUND
* `fff296b` (Task 2 — worker on_startup) — FOUND
* `5db4175` (Task 3+4 — Dockerfile + verify script) — FOUND
* `2878952` (Task 5 — e2e integration test) — FOUND
