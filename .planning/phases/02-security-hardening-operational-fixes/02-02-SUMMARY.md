---
plan: 02-02
phase: 02-security-hardening-operational-fixes
status: complete
completed: 2026-04-22
requirements: [SEC-03]
---

## Plan 02-02: PII Blocking (Entity-Type Granularity)

### What Was Built

Extended PII detection to support Presidio-compatible US entity type names and added
per-entity-type blocking in the ingestion pipeline. Documents are only blocked when a
detected PII type appears in the `pii_block_entities` allowlist, not on all PII.

### Key Files

- **services/preprocessor/pii_detector.py** — `_US_SSN` regex + `_PII_TYPE_ALIASES` dict + alias expansion in `PIIDetectionResult.__post_init__`
- **services/pipeline.py** — Stage 3 block check now gates on `pii_block_entities` set
- **config/settings.py** — `pii_block_on_detect` default → `True`; added `pii_block_entities` field
- **tests/unit/test_pii_detector.py** — 9 tests covering US entity names and settings defaults
- **tests/unit/test_pipeline_pii_block.py** — 3 tests covering block/pass/audit logic

### Tasks Completed

1. **US SSN detection (SEC-03)** — `_US_SSN` regex (`NNN-NN-NNNN`), masked to `***-**-NNNN`, pii_type `"US_SSN"`.

2. **Presidio-compatible aliases** — `_PII_TYPE_ALIASES` maps internal `"bank_card"` → `["CREDIT_CARD", "US_BANK_NUMBER"]`. `PIIDetectionResult.pii_types` expands aliases so callers see Presidio names.

3. **Entity-type block list** — `settings.pii_block_entities` (default: `["US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT"]`). Pipeline blocks only when detected type intersects this set.

4. **Audit always fires** — `audit.log_pii_detected` called on any PII detection regardless of block decision.

### Test Results

```
12 passed in 4.08s
```

### Deviations

None.

### Self-Check: PASSED

- `grep "_US_SSN" services/preprocessor/pii_detector.py` ✓
- `grep "_PII_TYPE_ALIASES" services/preprocessor/pii_detector.py` ✓
- `grep "pii_block_entities" config/settings.py` ✓
- `grep "pii_block_entities" services/pipeline.py` ✓
- All 12 unit tests pass
