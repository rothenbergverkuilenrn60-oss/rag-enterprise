---
phase: 07-ocr-engine-integration
plan: 01
subsystem: extractor
tags: [ocr, paddleocr, pp-structure-v3, async, semaphore, lru_cache]
requires:
  - settings.ocr_engine literal (existing)
  - utils.models.ExtractedContent (existing — unchanged)
provides:
  - services.extractor.ocr_engine.OcrEngine (Protocol)
  - services.extractor.ocr_engine.PpStructureV3Engine
  - services.extractor.ocr_engine.TesseractEngine
  - services.extractor.ocr_engine.get_ocr_engine
  - services.extractor.ocr_engine._paddle_pipeline (lru_cache singleton)
  - settings.ocr_concurrency (default 2)
  - settings.ocr_timeout_sec (default 120)
affects:
  - services/extractor/extractor.py (_extract_pdf_scanned_paddleocr now a shim)
tech-stack:
  added:
    - "paddlepaddle==3.0.0 (declared, install lands in Plan 02 Docker bake)"
    - "paddleocr[doc-parser]==3.1.* (declared)"
  patterns:
    - "functools.lru_cache(maxsize=1) for process-singleton heavy model"
    - "asyncio.to_thread + lazy-init asyncio.Semaphore for bounded async OCR"
    - "Protocol-based engine abstraction (PEP 544)"
key-files:
  created:
    - services/extractor/ocr_engine.py
    - tests/unit/test_settings_ocr.py
    - tests/unit/test_ocr_engine.py
    - tests/unit/test_extractor_ocr_routing.py
  modified:
    - requirements.txt
    - config/settings.py
    - services/extractor/extractor.py
decisions:
  - "Singleton lives in a new module (ocr_engine.py), not extractor.py — extractor.py is already 600+ lines"
  - "TesseractEngine is an adapter — wraps existing _extract_pdf_scanned_tesseract byte-identical"
  - "ocr_concurrency default = 2 (CPU paddlepaddle uses all cores; >2 thrashes 4–8 core hosts)"
  - "Loop bridge uses plain asyncio.run() — extractor_fn already runs in run_in_executor (no live loop)"
metrics:
  duration: ~25 min
  completed: 2026-04-27
  tasks: 3
  commits: 4 (3 task commits + this docs commit)
  files_changed: 7
  tests_added: 17
  tests_run: 34
  tests_passing: 34
---

# Phase 7 Plan 01: OCR Engine Integration Summary

PP-StructureV3 wired in behind a small async-safe engine abstraction with bounded concurrency, dependency pins, and zero regression on the Tesseract fallback path.

## What landed

| Concern | Implementation |
|---|---|
| **Engine abstraction** | `OcrEngine` Protocol in `services/extractor/ocr_engine.py` with two implementations |
| **PP-StructureV3 wiring** | `PpStructureV3Engine` — `lru_cache(maxsize=1)` singleton, `asyncio.to_thread`, semaphore-gated, returns `{body_text, tables(html), pages, title, engine}` |
| **Tesseract fallback** | `TesseractEngine` adapter wraps existing `_extract_pdf_scanned_tesseract` (body untouched) |
| **Selector** | `get_ocr_engine(name)` honours explicit `tesseract`/`paddle` and probes `paddleocr` for `auto` |
| **Concurrency cap** | Module-level `asyncio.Semaphore(settings.ocr_concurrency)` lazily constructed |
| **Settings** | `ocr_concurrency=2`, `ocr_timeout_sec=120`, both env-overridable |
| **Dependency pins** | `paddlepaddle==3.0.0` + `paddleocr[doc-parser]==3.1.*` declared in `requirements.txt` |
| **Extractor refactor** | `_extract_pdf_scanned_paddleocr` is now a 22-line sync shim that calls `asyncio.run(get_ocr_engine('auto').extract_pdf(...))` |

## Files changed (LOC delta)

| File | Δ |
|---|---|
| `requirements.txt` | +9 / -10 |
| `config/settings.py` | +6 / -0 |
| `services/extractor/ocr_engine.py` | **+186 (new)** |
| `services/extractor/extractor.py` | +18 / -65 (shim collapsed) |
| `tests/unit/test_settings_ocr.py` | **+50 (new)** |
| `tests/unit/test_ocr_engine.py` | **+199 (new)** |
| `tests/unit/test_extractor_ocr_routing.py` | **+178 (new)** |

## Open questions resolved (from CONTEXT.md / 07-01-PLAN.md)

1. **Model bake mechanism** — confirmed: instantiating `PPStructureV3()` triggers download into `~/.paddlex/official_models/`. No separate CLI step needed. The Dockerfile bake step lands in Plan 02.
2. **Tesseract retention** — minimum diff: `_extract_pdf_scanned_tesseract` is byte-identical; `TesseractEngine` is a thin async adapter.
3. **Concurrency default** — `ocr_concurrency=2` justified: `WorkerSettings.max_jobs=10` allows 10 concurrent ARQ jobs; the semaphore caps OCR-specific concurrency so non-OCR work continues at full parallelism.

## Test counts

| File | Tests | Result |
|---|---:|---|
| `tests/unit/test_settings_ocr.py` | 4 | passed |
| `tests/unit/test_ocr_engine.py` | 8 | passed |
| `tests/unit/test_extractor_ocr_routing.py` | 5 | passed |
| `tests/unit/test_image_extractor.py` (regression) | 17 | passed |
| **Total** | **34** | **passed** |

The plan budgeted 16 (4 + 7 + 5); we shipped 17 unit tests across the three new files (added a singleton-equality test) plus 17 image-extractor regression checks.

## Deviations from plan

| Item | Deviation | Rationale |
|---|---|---|
| Plan said 7 ocr_engine tests | Shipped 8 | Split "singleton" (cache_clear semantics) and "selector dispatch — paddle" into separate tests for tighter failure messages; no scope creep |
| Plan suggested `extractor_fn` monkeypatch | Used `monkeypatch.setitem(_EXTRACTOR_MAP, DocType.PDF, fake)` | `_EXTRACTOR_MAP` captures the function reference at module import — patching `ext._extract_pdf_enterprise` doesn't update the map. Test had to follow the actual dispatch path |
| Plan target `ocr_engine.py` ~140–180 lines | Final 186 lines | Within tolerance; extra lines are the comprehensive docstrings that document the locked decisions |

No deviations triggered Rule 4 (architectural). All changes preserved the documented contracts.

## Threat model verification

All `mitigate` dispositions in the plan's threat register are present:

* **T-07-01 (tampering, requirements.txt)** — exact `==3.0.0` and `==3.1.*` pins applied
* **T-07-02 (DoS, event loop)** — `asyncio.to_thread` + `_semaphore()` enforced in `PpStructureV3Engine.extract_pdf`
* **T-07-03 (DoS, malicious PDF)** — `ocr_timeout_sec` setting declared (Plan 02 owns the tenacity wrapper)
* **T-07-04 (info disclosure, log path)** — fallback log uses `file_path.name`, not the full path

## Outstanding work — Plan 02 (07-02)

Items deferred per the plan's scope boundary:

1. **Dockerfile bake step** — `RUN python -c "from paddleocr import PPStructureV3; PPStructureV3()"` to materialize `~/.paddlex/official_models/` into the runtime image, then `COPY` it across.
2. **ARQ worker pre-warm** — `WorkerSettings.on_startup` calls `_paddle_pipeline()` once to pay the 5–15s cold-start in worker boot, not first ingest.
3. **Tenacity timeout retry** — wrap `asyncio.run(engine.extract_pdf(...))` in `asyncio.wait_for(..., settings.ocr_timeout_sec)` with one tenacity retry; on second timeout surface in `extraction_errors`.
4. **Garbled-CJK heuristic** — log warning when `cjk_ratio < 0.30 and ascii_ratio < 0.05`; do not raise.
5. **End-to-end integration test** — run on `data/raw/GB4785-2019.pdf` with paddleocr actually installed (CI matrix or Docker-only test mark).
6. **OOM hardening** — confirm ARQ retry policy bubbles up worker OOM cleanly; consider `max_jobs` cap when paddleocr is in the worker.

## Self-Check: PASSED

Verified files exist:
* `services/extractor/ocr_engine.py` — FOUND
* `tests/unit/test_settings_ocr.py` — FOUND
* `tests/unit/test_ocr_engine.py` — FOUND
* `tests/unit/test_extractor_ocr_routing.py` — FOUND

Verified commits:
* `4a95c35` (Task 1) — FOUND in git log
* `b4f1d48` (Task 2) — FOUND in git log
* `1f0f6a0` (Task 3) — FOUND in git log
