---
plan: 02-03
phase: 02-security-hardening-operational-fixes
status: complete
completed: 2026-04-22
requirements: [SEC-02, OPS-02]
---

## Plan 02-03: Per-Route Rate Limiting + Rule ABC Enforcement

### What Was Built

Added slowapi per-route rate-limit decorators to ingest and query routes (SEC-02) and converted `Rule` from a plain dataclass to an ABC with `@abstractmethod check()` (OPS-02).

### Key Files

- **controllers/api.py** — `slowapi.Limiter` + `@_limiter.limit()` on 4 routes; `request: Request` added as first param
- **main.py** — `app.state.limiter`, `SlowAPIMiddleware`, `RateLimitExceeded` handler
- **services/rules/rules_engine.py** — `class Rule(ABC)` with explicit `__init__` and `@abstractmethod check()`
- **pyproject.toml** — added `slowapi>=0.1.9` dependency
- **tests/unit/test_rate_limiting.py** — 3 tests (ingest 429 on 11th, query 429 on 31st, single not blocked)
- **tests/unit/test_rules_engine_abc.py** — 4 tests (TypeError on bad subclass, PromptInjectionRule ok, engine init, engine run PASS)

### Tasks Completed

1. **Per-route slowapi decorators (SEC-02)** — `_limiter = Limiter(key_func=get_remote_address, default_limits=[])` exported as `limiter`. Decorators on `/ingest` and `/ingest/async` (10 RPM), `/query` and `/query/stream` (30 RPM). `request: Request` injected as first param on all 4 routes per slowapi requirement.

2. **SlowAPIMiddleware wired in main.py** — `app.state.limiter = _route_limiter`, `RateLimitExceeded` handler returns 429 with `Retry-After: 60`, `SlowAPIMiddleware` added.

3. **Rule ABC enforcement (OPS-02)** — `@dataclass` removed from `Rule`. `class Rule(ABC)` with explicit `__init__`. `@abstractmethod check()` ensures `TypeError` at instantiation time for any subclass that omits `check()`. All 7 builtin rules inherit the explicit `__init__` and continue to work.

### Test Results

```
27 passed in 2.63s  (full phase 2 suite)
```

### Deviations

- `slowapi>=0.1.9` added to `pyproject.toml` (not in original plan — required dependency).
- `controllers.api` imported at module level in test file to ensure module is in `sys.modules` before `patch()` resolves attributes.

### Self-Check: PASSED

- `grep "_limiter.limit" controllers/api.py` → 4 matches ✓
- `grep "app.state.limiter" main.py` → 1 match ✓
- `grep "SlowAPIMiddleware" main.py` → 1 match ✓
- `grep "class Rule(ABC)" services/rules/rules_engine.py` → 1 match ✓
- `grep "@abstractmethod" services/rules/rules_engine.py` → 1 match ✓
- All 27 phase 2 unit tests pass ✓
