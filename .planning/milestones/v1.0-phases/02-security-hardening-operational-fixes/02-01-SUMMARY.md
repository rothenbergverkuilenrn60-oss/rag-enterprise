---
plan: 02-01
phase: 02-security-hardening-operational-fixes
status: complete
completed: 2026-04-22
requirements: [SEC-01, SEC-04, OPS-01]
---

## Plan 02-01: Settings Hardening

### What Was Built

Hardened `config/settings.py` so the server refuses to start with insecure configuration. All checks fire at module-import time (not request time), eliminating silent runtime failures.

### Key Files

- **config/settings.py** — Four new validators + three rate-limit fields
- **tests/unit/test_settings_validators.py** — 8 tests (committed pre-execution as failing stubs; all pass post-implementation)

### Tasks Completed

1. **JWT denylist validator (SEC-01)** — `_validate_security` model_validator raises `ValueError` when `secret_key` is < 32 chars, all-same-character, or in `_JWT_DENYLIST` (14 known-weak values). Replaces old `warn_default_secret_key` field_validator that only warned in production.

2. **CORS production guard (SEC-04)** — Same model_validator raises `ValueError` in production when `cors_origins` is empty or contains any `localhost`/`127.0.0.1`/`0.0.0.0`/`::1` entry. Default changed from `["http://localhost:3000", "http://localhost:8080"]` to `[]`.

3. **MODEL_DIR guard (OPS-01)** — Module-level `RuntimeError` raised at import time if `APP_MODEL_DIR` env var is not set. Hardcoded fallback `/mnt/f/my_models` removed.

4. **Rate-limit settings fields (for Plan 03)** — Added `rate_limit_auth_rpm=5`, `rate_limit_ingest_rpm=10`, `rate_limit_query_rpm=30`.

### Test Results

```
8 passed in 0.17s
```

### Deviations

None. Implementation matched plan spec exactly.

### Self-Check: PASSED

- `grep "_JWT_DENYLIST" config/settings.py` ✓
- `grep "rate_limit_ingest_rpm" config/settings.py` ✓
- `grep "RuntimeError" config/settings.py` ✓
- All 8 unit tests pass
