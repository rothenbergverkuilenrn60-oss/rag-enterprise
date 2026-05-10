---
measured_at: "2026-05-10T14:00:00Z"
coverage_version: "Coverage.py 7.13.5"
python_version: "3.12.13"
measurement_source: "unit tests only (integration tests failed to collect due to env permissions)"
---

# Phase 22 — Per-Module Coverage Baseline

Snapshot taken before any Phase-22 test work begins. Plans 22-01..22-05 reference the
Missing line ranges below as their Wave-2 backfill budget (D-06 measure-then-add strategy).

## Per-Module Baseline

| Module | Stmts | Miss | Cover% | Gap to 70% (stmts) |
|--------|-------|------|--------|---------------------|
| `services/pipeline.py` | 606 | 205 | 66.2% | ~23 stmts (close) |
| `services/generator/llm_client.py` | 364 | 171 | 53.0% | ~62 stmts |
| `services/vectorizer/vector_store.py` | 190 | 106 | 44.2% | ~49 stmts |
| `services/retriever/retriever.py` | 307 | 201 | 34.5% | ~109 stmts |
| `services/extractor/extractor.py` | 306 | 192 | 37.3% | ~94 stmts |

**Note:** `services/pipeline.py` improved from the Phase-22 CONTEXT.md baseline (42.7% →
66.2%) due to tests added in Phases 19–21. Gap to 70% is now only ~23 stmts. Plans 22-01..22-05
still ship their SC-prescribed branches regardless of starting coverage (D-06 + ROADMAP SC wording).

## Missing Line Ranges

### services/pipeline.py

```
Name                   Stmts   Miss  Cover   Missing
----------------------------------------------------
services/pipeline.py     606    205  66.2%   139-140, 154, 159-164, 167, 209-214, 220-224,
                                             231-241, 263, 265, 277-278, 288-297, 301-302,
                                             305-474, 477-541, 546, 750, 752, 887-897, 902,
                                             996-998, 1002-1004, 1008-1010, 1030-1040,
                                             1060-1061, 1065-1067, 1070-1071, 1078, 1081,
                                             1086-1087, 1136-1172, 1224-1225, 1325-1329,
                                             1497, 1499, 1551-1560, 1576-1578
```

### services/generator/llm_client.py

```
Name                               Stmts   Miss  Cover   Missing
----------------------------------------------------------------
services/generator/llm_client.py     364    171  53.0%   58-62, 77-78, 159, 162, 286-302,
                                                         307-331, 355-364, 369-381, 391-412,
                                                         422-439, 519-524, 548-551, 576, 603,
                                                         618-637, 645-670, 686-704, 776,
                                                         823-859, 873-894, 914-938, 945-1008,
                                                         1012, 1016, 1027-1049
```

### services/vectorizer/vector_store.py

```
Name                                  Stmts   Miss  Cover   Missing
-------------------------------------------------------------------
services/vectorizer/vector_store.py     190    106  44.2%   134-156, 159-228, 241-277, 300-342,
                                                            354-359, 362-365, 378-402, 416-428,
                                                            437-445, 448, 451-454, 468-481,
                                                            484-488, 491, 524-527
```

### services/retriever/retriever.py

```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
services/retriever/retriever.py     307    201  34.5%   84-92, 100-119, 142-146, 154-189,
                                                        197-212, 256-273, 303-325, 414-417,
                                                        432-433, 446-538, 555-623, 635-662,
                                                        668, 673, 681-683
```

### services/extractor/extractor.py

```
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
services/extractor/extractor.py     306    192  37.3%   37-59, 70-93, 121-182, 213-217,
                                                        220-225, 230-270, 305-332, 383-384,
                                                        391-421, 432-446, 458-459, 462, 542,
                                                        551, 571-572, 578-581, 608, 612-620,
                                                        630
```

## Source-of-Truth Note

Combined `.coverage` file (unit + integration); CF-08 single source of truth. Plans 22-01..22-05
use these line ranges as the Wave-2 backfill budget per D-06 measure-then-add. At this baseline
measurement, integration tests failed to collect (PermissionError on `tests/integration/`) so
combined data equals unit-only data. This matches the Phase 22 CONTEXT.md baseline table values
for `services/generator/llm_client.py`, `services/vectorizer/vector_store.py`,
`services/retriever/retriever.py`, and `services/extractor/extractor.py`. Pipeline improved
from prior phases.

Measurement command sequence:
```bash
uv run coverage erase
COVERAGE_FILE=.coverage.unit uv run pytest tests/unit/ --asyncio-mode=auto --timeout=30 \
  --cov=services --cov=utils --cov-report= -q \
  --ignore=tests/unit/test_ab_test_service.py \
  --ignore=tests/unit/test_ingest_status.py \
  --ignore=tests/unit/test_memory_service.py
COVERAGE_FILE=.coverage.integration uv run pytest tests/integration/ \
  --asyncio-mode=auto --timeout=60 --cov=services --cov=utils --cov-append --cov-report= -q || true
uv run coverage combine --keep .coverage.unit .coverage.integration
uv run coverage report --include="services/<mod>.py" --show-missing
```
