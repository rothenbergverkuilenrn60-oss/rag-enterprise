# Phase 2: Security Hardening + Operational Fixes — Context

**Gathered:** 2026-04-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the running system against misconfiguration and abuse: weak JWT secrets crash startup, PII-containing documents are rejected at ingest, rate limits are enforced per-route, CORS origins are explicitly configured, and missing required env vars (MODEL_DIR, CORS_ORIGINS) fail startup with clear errors.

No new user-facing features. No changes to the retrieval or generation pipelines.

</domain>

<decisions>
## Implementation Decisions

### SEC-01: JWT Secret Denylist

- **D-01:** The startup validator blocks weak secrets in **ALL environments** (dev, staging, production). SEC-01 is explicit — no environment exemptions.
- **D-02:** Denylist scope: **common weak patterns** (~15 strings). Include at minimum: `CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY` (current default), `secret`, `password`, `changeme`, `dev`, `test`, `insecure`, `12345678901234567890123456789012`, `aaaa...` (32+ repeated chars), and similar well-known weak strings. No env-var extension needed.
- **D-03:** Minimum length: 32 characters (as specified in SEC-01). Check applies in addition to denylist.
- **D-04:** Validator replaces the existing `warn_default_secret_key` field_validator in `settings.py` — upgrade from warn-in-prod to fail-everywhere.

### SEC-02: Per-Route Rate Limiting

- **D-05:** Rate limits are **tiered by route type**, configurable via settings (not hardcoded in decorators):
  - Auth routes (`/auth/*`, login, token): **5 RPM** — brute-force protection
  - Ingest routes (`/documents/ingest`, etc.): **10 RPM** — resource-heavy
  - Query routes (`/query`, `/search`, etc.): **30 RPM** — primary use case
  - Health / metrics endpoints: **unlimited** (no decorator)
- **D-06:** Add `rate_limit_ingest_rpm`, `rate_limit_query_rpm`, `rate_limit_auth_rpm` to `settings.py`.
- **D-07:** `@limiter.limit()` decorators on individual routes enforce per-route limits. Global middleware remains as defense-in-depth (fail-safe, not primary enforcement).

### SEC-03: PII Blocking

- **D-08:** `pii_block_on_detect` default flipped from `False` → `True`. Blocking is opt-out, not opt-in.
- **D-09:** Default `BLOCK_ENTITIES` list (financial + gov ID): `US_SSN`, `CREDIT_CARD`, `US_BANK_NUMBER`, `US_DRIVER_LICENSE`, `US_PASSPORT`. Contact info (EMAIL_ADDRESS, PHONE_NUMBER) is **not** blocked by default — common in enterprise documents.
- **D-10:** BLOCK_ENTITIES is a **global settings field** (env var configurable). Tenants can opt out of blocking entirely (non-blocking mode per SEC-03), but cannot customize which entity types are blocked per-tenant.

### SEC-04: CORS Configuration

- **D-11:** Production detection via `settings.environment == "production"`. The `environment` field already exists as a `Literal["development", "staging", "production"]` in settings.
- **D-12:** `cors_origins` default changed from `["http://localhost:3000", "http://localhost:8080"]` → **empty list `[]`**. Startup validation requires `CORS_ORIGINS` env var to be explicitly set. Server refuses to start if unset (same pattern as OPS-01 for MODEL_DIR).
- **D-13:** Startup validator additionally rejects any localhost/127.0.0.1 entry in `cors_origins` when `environment == "production"`.

### OPS-01: MODEL_DIR Startup Validation

- **D-14:** Remove the hardcoded fallback `"/mnt/f/my_models"` from `MODEL_DIR` module-level assignment. Startup must fail with a descriptive error if `APP_MODEL_DIR` env var is not set.
- **D-15:** Error message format: `"APP_MODEL_DIR environment variable is required. Set it to the directory containing model files (e.g., /models). Server will not start."`.

### OPS-02: Rule.check() ABC Enforcement

- **D-16:** `Rule` becomes an `ABC` subclass. `check()` decorated with `@abstractmethod`. Concrete rule subclasses that don't implement `check()` raise `TypeError` at class definition time (Python ABC behavior), not at runtime call site.
- **D-17:** The existing `@dataclass` decorator is retained where compatible; if ABC + dataclass inheritance causes issues, restructure to plain class with `__init__`.

### Claude's Discretion

- Specific denylist strings beyond the required ones: Claude selects well-known common weak secrets from OWASP / common credential lists
- Presidio analyzer configuration (confidence thresholds, language settings): standard defaults
- How `@limiter.limit()` string format references settings values (lambda vs. string format): Claude decides

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — SEC-01, SEC-02, SEC-03, SEC-04, OPS-01, OPS-02 full acceptance criteria
- `.planning/ROADMAP.md` — Phase 2 success criteria (4 numbered items)

### Key Source Files
- `config/settings.py` — `Settings` class, existing `warn_default_secret_key` validator, `cors_origins`, `pii_block_on_detect`, `MODEL_DIR`, `rate_limit_rpm`
- `main.py` — existing `rate_limit_middleware`, `CORSMiddleware` registration, lifespan handler
- `services/auth/oidc_auth.py` — `_verify_local_jwt()`, `issue_token()` using `settings.secret_key`
- `services/rules/rules_engine.py` — `Rule` dataclass, `check()` method (OPS-02 target)
- `controllers/api.py` — route definitions where `@limiter.limit()` decorators will be added

### Project Context
- `.planning/PROJECT.md` — production-grade only; Pydantic V2, no bare except, no blocking I/O in async

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `settings.py` `@field_validator("secret_key")`: upgrade from warn-in-prod → fail-everywhere denylist check
- `settings.py` `environment: Literal[...]`: already exists, use for CORS production detection
- `settings.py` `pii_block_on_detect: bool = False`: flip default, add `BLOCK_ENTITIES` list field
- `main.py` `rate_limit_middleware`: keep as global fallback, add per-route decorators on top

### Established Patterns
- Pydantic V2 `@field_validator` and `@model_validator` used for startup validation (see `settings.py`)
- Module-level `MODEL_DIR = Path(os.getenv(...))` pattern — needs startup guard added
- `AuditAction.PII_DETECTED` already exists in `audit_service.py` — rejection path should log via this

### Integration Points
- Startup validation: Pydantic `@model_validator(mode="after")` in `Settings` class for CORS + MODEL_DIR checks
- Rate limiting: `controllers/api.py` routes need `@limiter.limit(...)` added; `slowapi` or equivalent library needed
- PII: `services/preprocessor/` or ingest pipeline Stage 3 — `pii_block_on_detect` flag check point

</code_context>

<specifics>
## Specific Requirements

- JWT check must run before any traffic is accepted — in `Settings.__init__` or `@model_validator`, not in request handlers
- `cors_origins` empty list at startup = fail immediately (not a runtime 403) — same pattern as OPS-01
- Tiered rate limits: auth 5, ingest 10, query 30 (all per minute, per IP)
- PII block entities: exactly `["US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT"]` as default
- All startup failures must produce human-readable error messages (not stack traces) — per PROJECT.md production-grade standard

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-security-hardening-operational-fixes*
*Context gathered: 2026-04-22*
