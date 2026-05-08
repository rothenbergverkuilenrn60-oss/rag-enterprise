---
phase: 07-ocr-engine-integration
verified: 2026-04-27T00:00:00Z
status: human_needed
score: 15/15 codebase truths verified; 1 truth requires container-side human verification
overrides_applied: 0
human_verification:
  - test: "Build production Docker image and verify ≤5s first OCR after worker startup with no runtime model download"
    expected: "docker build succeeds; scripts/verify_ocr_bake.sh exits 0; ARQ worker `[Worker:startup] PP-StructureV3 singleton ready` log appears within 5s of startup; e2e test passes inside the container"
    why_human: "Heavy step (10–20 min build, ~600MB–1.2GB image delta) explicitly deferred to user per 07-02 plan scope rule. Cannot be exercised from CI / dev VM. The integration test is correctly skip-gated via importlib.util.find_spec('paddleocr') so unit suite stays green; the test itself is real and contains real assertions (chars > 0, CJK present, wall-clock ceiling)."
---

# Phase 7: OCR Engine Integration — Verification Report

**Phase Goal:** Pure-image PDFs ingest with real per-page text and tables extracted by PP-StructureV3, running async-safe under bounded concurrency with models baked into the Docker image. Tesseract retained as fallback.

**Verified:** 2026-04-27
**Status:** HUMAN_NEEDED (codebase complete; one success criterion requires container build the user must run)
**Re-verification:** No — initial verification

## Goal Achievement

### ROADMAP Success Criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | GB4785 ingest → `chars > 0` + ≥1 chunk per page span end-to-end | ⚠ HUMAN | Test exists and is real: `tests/integration/test_ocr_e2e.py:55-73` (`assert len(extracted.body_text) > 0`, `assert _CJK_RE.search(extracted.body_text)`). Skip-gated correctly via `pytest.mark.skipif(not _PADDLEOCR_AVAILABLE)` (line 42-46) — confirmed runs as SKIPPED in dev env, COLLECTED for `-m integration`. Will pass when paddleocr present (i.e. inside Docker). |
| 2 | PP-StructureV3 invoked exactly once / process; concurrency ≤ `settings.ocr_concurrency` | ✓ VERIFIED | `services/extractor/ocr_engine.py:99` `@lru_cache(maxsize=1) def _paddle_pipeline()`; `:66-73` lazy `asyncio.Semaphore(settings.ocr_concurrency)`; `:142` `async with _semaphore()` wraps every call. Test: `tests/unit/test_ocr_engine.py` singleton + semaphore tests passed (8/8). |
| 3 | Built image performs first OCR ≤5s after worker startup; no runtime download | ⚠ HUMAN | Code: `Dockerfile:43-48` builder bake `RUN pip install … && python -c "from paddleocr import PPStructureV3; PPStructureV3(…)"`; `Dockerfile:98-99` `COPY --from=builder --chown=raguser:raguser /root/.paddlex /home/raguser/.paddlex` + `ENV PADDLE_PDX_CACHE_HOME=…`; `services/ingest_worker.py:64-104` `on_startup` pre-warms; `:116` wires to `WorkerSettings.on_startup`. The 5-second wall-clock can only be measured against the actual built image (build deferred to user — see 07-02-SUMMARY §"Image-size delta"). |
| 4 | OCR > `ocr_timeout_sec` retries once, then surfaces in `IngestionResponse.extraction_errors` | ✓ VERIFIED | `services/extractor/ocr_engine.py:139-171`: `asyncio.wait_for(timeout=settings.ocr_timeout_sec)` inside `AsyncRetrying(retry=retry_if_exception_type(asyncio.TimeoutError), stop=stop_after_attempt(2), wait=wait_fixed(1), reraise=True)`. On second timeout returns dict with `extraction_errors=["OCR timeout after Xs, retried 1x"]` and `body_text=""`. The errors propagate via `services/extractor/extractor.py:575-576` (`if "extraction_errors" in result_dict: errors.extend(...)`) → `:594` `extraction_errors=errors` on `ExtractedContent` → `services/pipeline.py:241` `IngestionResponse(... extraction_errors=extracted.extraction_errors)`. Test: `tests/unit/test_ocr_failure_modes.py` 10/10 passed (timeout+retry+success-on-retry+oom-passthrough+garbled covered). |
| 5 | Environments without PaddleOCR continue using Tesseract fallback with no behavioural regression | ✓ VERIFIED | `services/extractor/ocr_engine.py:269-279` `get_ocr_engine("auto")` `try: import paddleocr` else `TesseractEngine()` with explicit warning (no silent regression). `services/extractor/extractor.py:199-224` `_extract_pdf_scanned_paddleocr` shim wraps engine call and falls back to `_extract_pdf_scanned_tesseract` on any failure. The legacy Tesseract function (`extractor.py:240-275`) is byte-identical (uses `pytesseract`, `tesseract-ocr-chi-sim` system pkg installed at `Dockerfile:67`). Test: `tests/unit/test_extractor_ocr_routing.py::test_tesseract_route_uses_legacy_function` passed; phase-4 image-extractor 17/17 regression tests passed. |

**Score:** 4/5 verified in code, 1/5 (#1 e2e) ✓ verified static + skip-gated correctly + ⚠ requires container run for live confirmation.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `services/extractor/ocr_engine.py` | OcrEngine Protocol + PpStructureV3Engine + TesseractEngine + singleton + semaphore + retry + heuristic | ✓ VERIFIED | 279 lines; all components present at lines 77-95 (Protocol), 99-114 (singleton), 117-220 (Paddle engine + retry), 224-240 (Tesseract adapter), 244-279 (selector), 39-59 (garbled heuristic). |
| `services/ingest_worker.py` | `on_startup` hook + `WorkerSettings.on_startup` wired | ✓ VERIFIED | `:64-104` async `on_startup`, `:116` `on_startup = on_startup`. |
| `Dockerfile` | builder bake of PaddleOCR models + runtime COPY + `PADDLE_PDX_CACHE_HOME` | ✓ VERIFIED | `:43-48` builder bake; `:98-99` runtime COPY + ENV. |
| `requirements.txt` | `paddlepaddle==3.0.0`, `paddleocr[doc-parser]==3.1.*`, `tenacity==9.0.0` | ✓ VERIFIED | Lines 21, 96, 97. |
| `config/settings.py` | `ocr_concurrency` (default 2), `ocr_timeout_sec` (default 120), `ocr_engine` Literal | ✓ VERIFIED | Lines 139, 145, 146. |
| `tests/unit/test_ocr_engine.py` | Singleton, semaphore, selector, engine dispatch | ✓ VERIFIED | 237 lines, 16 asserts, 8 tests passing. |
| `tests/unit/test_ocr_failure_modes.py` | Timeout+retry, OOM passthrough, garbled heuristic | ✓ VERIFIED | 288 lines, 24 asserts, 10 tests passing. |
| `tests/unit/test_worker_startup.py` | Pre-warm dispatch / skip / ImportError tolerance | ✓ VERIFIED | 149 lines, 5 asserts, 6 tests passing. |
| `tests/unit/test_extractor_ocr_routing.py` | Routing: paddle/tesseract/none/digital | ✓ VERIFIED | 180 lines, 12 asserts, 5 tests passing. |
| `tests/integration/test_ocr_e2e.py` | GB4785 e2e with skip-gate | ✓ VERIFIED | 104 lines, real assertions (`chars > 0`, CJK present, wall-clock ceiling), skip-gate via `importlib.util.find_spec('paddleocr')` + `Path('data/raw/GB4785-2019.pdf').exists()` + `pytest.mark.integration`. Confirmed: collects 1 test, runs as SKIPPED in dev env (paddleocr absent). |
| `pytest.ini` | `integration` marker + `addopts = -m "not integration"` | ✓ VERIFIED | All 3 lines present, default unit run excludes integration cleanly. |
| `scripts/verify_ocr_bake.sh` | Offline + ownership + size assertions for image | ✓ EXISTS | Listed in 07-02-SUMMARY; not exercised here (Docker-only). |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `extractor.py::_extract_pdf_scanned_paddleocr` | `ocr_engine.get_ocr_engine` | `asyncio.run(engine.extract_pdf(...))` | ✓ WIRED | extractor.py:210, :219 |
| `ocr_engine.PpStructureV3Engine` | `_paddle_pipeline` singleton | direct call inside `_run_sync` | ✓ WIRED | ocr_engine.py:184 |
| OCR timeout result | `IngestionResponse.extraction_errors` | dict["extraction_errors"] → ExtractedContent → IngestionResponse | ✓ WIRED | ocr_engine.py:168 → extractor.py:575-576,594 → pipeline.py:241 |
| `WorkerSettings.on_startup` | `_paddle_pipeline()` | `services.extractor.ocr_engine` import | ✓ WIRED | ingest_worker.py:89-91, :116 |
| `Dockerfile` builder | runtime image (`/home/raguser/.paddlex`) | `COPY --from=builder` | ✓ WIRED | Dockerfile:98 |
| `is_scanned_pdf()` | `_extract_pdf_scanned_paddleocr` | `_EXTRACTOR_MAP[DocType.PDF]` → `_extract_pdf_enterprise` → routing on `ocr_engine` setting | ✓ WIRED | extractor.py:356-382 |

### REQ Acceptance Criteria

#### REQ A-1 / OCR-01 (5 criteria)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `extractor.py` calls PP-StructureV3 (not raw PP-OCRv5) when `is_scanned_pdf()` true | ✓ VERIFIED | extractor.py:377-378 routes to `_extract_pdf_scanned_paddleocr` → ocr_engine.py:108-114 imports `PPStructureV3` (not `PaddleOCR` raw). |
| 2 | PP-StructureV3 receives PDF path directly; returns per-page text + table HTML + reading-order | ✓ VERIFIED | ocr_engine.py:184 `_paddle_pipeline().predict(input=str(file_path))`; :188-209 iterates pages, extracts `markdown_texts` (reading-order text) + `pred_html` table HTML. |
| 3 | Output mapped into `ExtractedContent` (text + per-page tables); chunker unchanged | ✓ VERIFIED | ocr_engine.py:214-220 returns `{body_text, tables(html+page), pages, title, engine}`; extractor.py:583-595 maps into `ExtractedContent`. `services/doc_processor/chunker.py` not modified in Phase 7 (per SUMMARY's affects list — confirmed unchanged). |
| 4 | Tesseract fallback path retained, no silent regression | ✓ VERIFIED | ocr_engine.py:224-240 `TesseractEngine` adapter wraps `_extract_pdf_scanned_tesseract`; extractor.py:240-275 untouched (per 07-01-SUMMARY, byte-identical); auto-fallback at ocr_engine.py:269-279 emits explicit warning, never silent. |
| 5 | Integration test on `data/raw/GB4785-2019.pdf` produces `chars > 0` + ≥1 chunk per page | ⚠ HUMAN | Test exists with real assertions and is correctly skip-gated. Awaits Docker run. |

#### REQ A-2 / OCR-02 (5 criteria)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Process-singleton via `functools.lru_cache(maxsize=1)` | ✓ VERIFIED | ocr_engine.py:99-114. |
| 2 | `asyncio.to_thread` + module-level `asyncio.Semaphore(settings.ocr_concurrency)` (default 2) | ✓ VERIFIED | ocr_engine.py:142-146; settings.py:145 default 2. |
| 3 | Models baked into Docker image at build time; image delta documented | ✓ VERIFIED (CODE) ⚠ HUMAN (delta) | Dockerfile:43-48 + :98-99 present. Image-size delta is research-projected at +600MB–1.2GB (07-02-SUMMARY §"Image-size delta") — actual measurement requires user-run `docker compose build`. |
| 4 | ARQ ingest worker pre-warms OCR singleton on startup | ✓ VERIFIED | ingest_worker.py:64-104 `on_startup`; :116 `WorkerSettings.on_startup = on_startup`. Test: `tests/unit/test_worker_startup.py` 6/6 passed including dispatch on auto/paddle, skip on tesseract/none, ImportError tolerance, broad-except continuation. |
| 5 | Failure modes: hard timeout → retry once → `extraction_errors`; OOM bubbles up; garbled CJK warns only | ✓ VERIFIED | Timeout/retry: ocr_engine.py:139-171. OOM: no `except MemoryError` anywhere (verified `grep -c 'except MemoryError' ocr_engine.py == 0`). Garbled: ocr_engine.py:39-59 + :176-180 (warn only, no raise). Test: 10/10 in `test_ocr_failure_modes.py`. |

### Behavioural Spot-Checks

| Behaviour | Command | Result | Status |
|---|---|---|---|
| All Phase 7 unit tests pass | `pytest tests/unit/test_ocr_engine.py …` | 33 passed in 3.87s | ✓ PASS |
| E2E test collects + skips correctly without paddleocr | `pytest tests/integration/test_ocr_e2e.py -m integration` | 1 skipped (`reason=paddleocr not installed; run inside the built Docker image`) | ✓ PASS |
| Phase-4 image-extractor regression | `pytest tests/unit/test_image_extractor.py` | 17 passed | ✓ PASS |
| `extraction_errors` flows from OCR dict → IngestionResponse | grep trace | extractor.py:575-576 → :594 → pipeline.py:241 | ✓ PASS |
| `ocr_engine.py` has no broad `except Exception` | `grep -v '^#' ocr_engine.py | grep -c 'except Exception'` | 0 | ✓ PASS |

### v1.0 Contract Regression Check

| Contract | Status | Evidence |
|---|---|---|
| `IngestionResponse.extraction_errors` | ✓ INTACT | `utils/models.py:99` and `:272` Field unchanged; OCR timeout failures use it (ocr_engine.py:168). |
| Phase-4 image-caption pipeline (`image_b64`, `extract_images_from_pdf`) | ✓ INTACT | extractor.py:26 import unchanged; :320 `image_b64=…`; :602 `extract_images_from_pdf(...)`. 17/17 regression tests passing. |
| Tesseract fallback path | ✓ INTACT | `_extract_pdf_scanned_tesseract` byte-identical; system packages still installed at Dockerfile:66-68. |
| `services/vectorizer/vector_store.py` | ✓ INTACT | No commits in Phase 7 touching it (last touch: `8e3c5d3`/`3bb154a`/`bd4c5fb`/`e9601c9`, all v1.0). |
| `services/doc_processor/chunker.py` | ✓ INTACT | Not in Phase 7 SUMMARY's `affects` list; no Phase 7 commits modify it. |

### Anti-Pattern Scan

| File | Finding | Severity |
|---|---|---|
| `services/ingest_worker.py:98-104` | Documented `except Exception` (ERR-01 EXEMPTION) — explicitly justified, logs full repr, does not silently swallow | ℹ INFO — by design |
| `services/extractor/extractor.py:213-217, 220-224` | Two `except Exception` in shim, both log + fall back to Tesseract (no silent failure). | ℹ INFO — defensive fallback documented in shim docstring |
| `services/extractor/ocr_engine.py:210-212` | Catches `(KeyError, AttributeError, TypeError)` for malformed page result — narrow types only, ERR-01 compliant | ✓ OK |

No TODO/FIXME/PLACEHOLDER markers in Phase 7 code. No empty `return null/[]/{}` stubs in implementation paths.

## Gaps Summary

**No code-level gaps.** All 5 ROADMAP success criteria, all 10 REQ acceptance criteria, all 6 declared key links, all 12 declared artifacts are present and verified. 33/33 Phase 7 unit tests passing; 17/17 Phase-4 regression tests still passing; e2e test correctly skip-gated (`pytest.mark.skipif` on `importlib.util.find_spec('paddleocr')`) — collects 1 test, would run if paddleocr were importable.

The single remaining item is operational, not a code gap: the production Docker image must be built and the e2e test run inside it to physically confirm SC #1 (GB4785 OCR) and SC #3 (≤5s warm-start). Both SUMMARY documents flag this as user-deferred, and the verify script (`scripts/verify_ocr_bake.sh`) plus `pytest -m integration` give a clean gate for that step.

## Human Verification Required

### 1. Build production image and run e2e

**Test:** Run the three commands from `07-02-SUMMARY.md §Outstanding work`:
```bash
docker compose build rag-api          # or: docker build -t rag-enterprise:phase7-test .
bash scripts/verify_ocr_bake.sh rag-enterprise:phase7-test
docker run --rm -v $(pwd)/data:/app/data:ro \
  -e APP_MODEL_DIR=/app/cache \
  -e SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))') \
  rag-enterprise:phase7-test \
  python -m pytest tests/integration/test_ocr_e2e.py -m integration -x -s
```

**Expected:**
- `docker build` completes (10–20 min for first build, +600MB–1.2GB image growth)
- `verify_ocr_bake.sh` exits 0 and prints model-dir count ≥ 3, owner `raguser:1001`, image size
- `pytest -m integration` reports 1 passed, with `[OCR e2e]` line printing `chars`, `pages`, per-page latency
- Worker boot log line `[Worker:startup] PP-StructureV3 singleton ready` appears within 5s of `arq services.ingest_worker.WorkerSettings`

**Why human:** Docker build is heavy (10–20 min) and explicitly deferred to user per 07-02 plan scope rule. Cannot be exercised from this environment.

## User Next Step

The docker-rebuild instruction in `07-02-SUMMARY.md §"Outstanding work / next-step instructions for the user"` (lines 177-204) **is the correct gate** before declaring SC #1 (GB4785 e2e) and SC #3 (≤5s warm) live-verified. Code-side everything is in place; rebuild + run the three commands above. Once green, update STATE.md with the observed image-size delta and per-page OCR latency captured by the verify script and the `[OCR e2e]` test print.

## Verdict

**PASS (codebase) + HUMAN_NEEDED (container verification).**

Goal achieved at the code, test, and wiring level. v1.0 contracts intact. The final operational step (image build + e2e run inside container) is a one-shot user action; no rework needed.

---

_Verified: 2026-04-27_
_Verifier: Claude (gsd-verifier)_
