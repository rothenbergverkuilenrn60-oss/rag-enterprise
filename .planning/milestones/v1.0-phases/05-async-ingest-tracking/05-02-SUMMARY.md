---
plan: 05-02
phase: 05-async-ingest-tracking
status: complete
completed: "2026-04-27"
requirements: [ASYNC-01, ASYNC-02]
---

# 05-02 Summary: Settings + FastAPI Auth Dependency

## What Was Built

Added the two foundation pieces Plan 03 consumes:

1. **`config/settings.py`** — two ARQ settings fields:
   - `arq_keep_result_sec: int = 86400` (ASYNC-02: 24h TTL)
   - `arq_job_timeout: int = 300` (ASYNC-01/02: max worker job seconds)

2. **`services/auth/oidc_auth.py`** — `get_current_user` FastAPI dependency:
   - `HTTPBearer(auto_error=False)` prevents FastAPI's default 403; raises 401 instead
   - Reuses `get_auth_service()` singleton (no per-request OIDCAuthService instantiation)
   - Static error messages only — no token contents echoed (T-05-04 mitigation)

3. **`tests/unit/test_oidc_auth_dependency.py`** — 4 tests, all GREEN:
   - valid token → AuthenticatedUser returned
   - credentials=None → 401 "Authorization required"
   - verify_token returns None → 401 "Invalid or expired token"
   - singleton call count verified (no re-instantiation)

## Self-Check: PASSED

- `grep -c 'arq_keep_result_sec' config/settings.py` → 1 ✓
- `grep -c 'arq_job_timeout' config/settings.py` → 1 ✓
- `grep -c 'async def get_current_user' services/auth/oidc_auth.py` → 1 ✓
- `grep -c 'HTTPBearer(auto_error=False)' services/auth/oidc_auth.py` → 1 ✓
- 4 tests committed in test_oidc_auth_dependency.py ✓
- No existing routes modified ✓

## Key Files

### Modified
- `config/settings.py` — +2 ARQ fields in Redis section
- `services/auth/oidc_auth.py` — +2 imports, +`_bearer`, +`get_current_user`

### Created
- `tests/unit/test_oidc_auth_dependency.py` — 4-test auth dependency suite

## Commits
- `9a4e94d feat(05-02): add ARQ settings fields to config/settings.py`
- `527dfbc feat(05-02): add get_current_user FastAPI dependency to oidc_auth.py`

## Deviations
None — implemented exactly per plan spec.
