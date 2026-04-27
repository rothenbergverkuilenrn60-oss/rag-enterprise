# Phase 2: Security Hardening + Operational Fixes — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-22
**Phase:** 02-security-hardening-operational-fixes
**Areas discussed:** JWT denylist scope, PII block entities, CORS prod detection, Rate limits per route

---

## JWT Denylist Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Common weak patterns | Hardcode ~15 well-known weak strings; no env-var extension | ✓ |
| Minimal — just the default | Only denylist the existing default string | |
| Hardcoded + env-var extensible | Hardcode common patterns AND allow EXTRA_JWT_DENYLIST env var | |

**User's choice:** Common weak patterns (~15 strings)
**Notes:** Existing `CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY` is included; no env-var extension needed

---

## JWT Environment Scope

| Option | Description | Selected |
|--------|-------------|----------|
| ALL environments | Block in dev, staging, and production — SEC-01 explicit | ✓ |
| Non-development only | Allow weak secrets in development | |

**User's choice:** ALL environments
**Notes:** Directly per SEC-01 requirement wording ("in ALL environments")

---

## PII Block Entities

| Option | Description | Selected |
|--------|-------------|----------|
| Financial + gov ID only | US_SSN, CREDIT_CARD, US_BANK_NUMBER, US_DRIVER_LICENSE, US_PASSPORT | ✓ |
| Broad PII block | Above + EMAIL_ADDRESS, PHONE_NUMBER, IP_ADDRESS | |
| Minimal — just SSN + credit card | Only US_SSN and CREDIT_CARD | |

**User's choice:** Financial + gov ID only
**Notes:** Contact info (email, phone) not blocked — common in legitimate enterprise documents

---

## PII Entity Configuration Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Global settings only | BLOCK_ENTITIES in settings.py/env var; tenants opt out of blocking, not customize entities | ✓ |
| Per-tenant entity list | TenantConfig can override BLOCK_ENTITIES per tenant | |

**User's choice:** Global settings only

---

## CORS Production Detection

| Option | Description | Selected |
|--------|-------------|----------|
| ENVIRONMENT=production env var | Reject localhost when settings.environment == 'production' | ✓ |
| Always reject localhost when CORS_ORIGINS set | Strip localhost if CORS_ORIGINS env var explicitly provided | |
| Startup validator blocks mixed config | Raise at startup if localhost + production, warn in staging | |

**User's choice:** ENVIRONMENT=production env var
**Notes:** `environment` field already exists as Literal in settings.py — clean integration

---

## CORS Default Value

| Option | Description | Selected |
|--------|-------------|----------|
| Empty list — fail at startup | No default; CORS_ORIGINS env var required; same pattern as MODEL_DIR | ✓ |
| Keep localhost defaults for dev | Keep current ['http://localhost:3000', 'http://localhost:8080'] default | |

**User's choice:** Empty list — fail at startup

---

## Rate Limit Tiers

| Option | Description | Selected |
|--------|-------------|----------|
| Tiered: strict ingest, loose query | Auth 5/min, ingest 10/min, query 30/min, health unlimited | ✓ |
| Uniform: all routes same as global | All routes 60 RPM (global setting) | |
| Custom tiers | User specifies numbers | |

**User's choice:** Tiered
**Notes:** Ingest is slow and resource-heavy → 10/min; auth → 5/min brute-force protection; query → 30/min

---

## Rate Limit Configurability

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable via settings | Add rate_limit_ingest_rpm, rate_limit_query_rpm, rate_limit_auth_rpm to settings.py | ✓ |
| Hardcoded in decorators | Bake strings directly into @limiter.limit() | |

**User's choice:** Configurable via settings

---

## Claude's Discretion

- Specific denylist strings (beyond obvious ones) — Claude selects from OWASP lists
- Presidio confidence thresholds — standard defaults
- `@limiter.limit()` string format for referencing settings values — Claude decides implementation

## Deferred Ideas

None.
