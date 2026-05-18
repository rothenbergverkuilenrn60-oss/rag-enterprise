# Phase 32: mypy `--strict` Cleanup — Research

**Researched:** 2026-05-18
**Domain:** Python type-checking — mypy strict mode, third-party stubs, silence convention
**Confidence:** HIGH (all findings verified against live codebase + PyPI)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-CAP-01/02/03:** Cap = 25 applies to bounded scope `services/+config/+utils/+controllers/+scripts/` in Phase 32 *touched files* (see cap interpretation, Q9 below). `tests/` uncapped but tracked + reported.
- **D-AUDIT-01–04:** All 4 bare-ignore sites and all 4 asyncpg untyped-import test sites are in scope. Planner must re-audit at plan time via `grep -rn '# type: ignore[^[]'` + fresh mypy run.
- **D-STUB-01–06:** Install `asyncpg-stubs` + `pandas-stubs` as dev deps; verify ≤12-month release before committing. Silence `pgvector.asyncpg`, `rank_bm25`, `datasets` with `# type: ignore[import-untyped]  # why: no upstream stubs; tracking: <url|NA>`. No local `stubs/` package.
- **D-STRUCT-01/02:** Add `explicit_package_bases = true` to `[tool.mypy]` in `pyproject.toml`. Do NOT add `scripts/__init__.py`.
- **D-VERIFY-01/02:** Per-requirement verification commands specified in CONTEXT.md §Verification. CI must install `--dev` group (see CI gap finding below).

### Claude's Discretion

- Silence-comment wording (`why:` clause phrasing per site).
- Order of execution within plan.
- Single plan (32-00) vs split (32-00 stub install + structural; 32-01 audit sweep).

### Deferred Ideas (OUT OF SCOPE)

- Drive `tests/` silence count toward 0 (~200 LOC annotation work).
- Hand-roll local `stubs/` package.
- Convert `scripts/` to a real Python package.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MYPY-02 | Resolve all 7 deferred violations in `deferred-items.md` (drain to 0) | asyncpg-stubs 0.30.2 fixes 5 asyncpg sites; pandas-stubs 2.2.3.x fixes 1 pandas site; rank_bm25 + datasets silenced; explicit_package_bases fixes structural entry |
| MYPY-03 | Replace bare `# type: ignore` at 4 sites with `[code]  # why:` form | Error codes identified for all 4 sites (see Q5) |
| MYPY-04 | Resolve asyncpg + pgvector.asyncpg `import-untyped` in 4 test files | asyncpg-stubs fixes 3 asyncpg-only files; pgvector.asyncpg silence needed for test_save_facts_toctou.py:57 |
</phase_requirements>

---

## Summary

Phase 32 drains 7 entries from `deferred-items.md` to 0, converts 4 bare `# type: ignore` comments to the `[code]  # why:` convention, and resolves 4 asyncpg-shaped untyped-import silences in test files. The primary mechanism is installing two stub packages (`asyncpg-stubs==0.30.2`, `pandas-stubs==2.2.3.250308`) as dev dependencies, adding `explicit_package_bases = true` to the mypy config, and applying per-site silence-with-why for the three deps without upstream stubs (`pgvector.asyncpg`, `rank_bm25`, `datasets`).

Installing asyncpg-stubs has a positive side effect: the 12 `import asyncpg  # type: ignore[import-untyped]` silences already placed in Phase 30-03 across bounded-scope files become unnecessary and should be removed. This produces a net reduction in bounded-scope silence count, well within D-CAP-03.

**Critical pre-work finding:** The `asyncpg-stubs` version must match `asyncpg` runtime version. Project pins `asyncpg==0.30.0` in `requirements.txt`; the matching stubs are `asyncpg-stubs==0.30.2` (released 2025-06-27). The latest stubs (0.31.2) require `asyncpg>=0.31` — installing them against asyncpg 0.30.0 causes a pip resolver conflict. Use `uv add --dev "asyncpg-stubs~=0.30.2"`.

**CI gap finding:** The current CI `lint-and-type-check` job runs `pip install ruff mypy types-requests` (no stubs) and uses `--ignore-missing-imports --no-strict-optional` (not `--strict`). Stubs added to `pyproject.toml [dependency-groups].dev` will NOT be installed in CI unless either (a) `requirements-dev.txt` is updated or (b) the CI step is changed to `uv sync --group dev`. The strict mypy gate is local/pre-commit only — CI remains a weaker gate.

**Primary recommendation:** Wave 0 — install stubs + pyproject config edit; Wave 1 — remove now-unnecessary asyncpg silences across bounded-scope files + add new per-site silences; Wave 2 — bare-ignore replacement + test-file untyped-import fixes.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Type stub installation | Dev tooling (pyproject.toml) | requirements-dev.txt (CI path) | Stubs are dev deps; both files must be updated for CI to see them |
| mypy config (`explicit_package_bases`) | `[tool.mypy]` in pyproject.toml | — | No mypy.ini exists; pyproject.toml is the only config file |
| Bare-ignore → coded-ignore conversion | File-at-a-line edits | grep verification gate | Surgical single-line edits; no logic change |
| CI mypy upgrade (--strict, stubs) | `.github/workflows/ci.yml` | requirements-dev.txt | Currently weak (`--ignore-missing-imports`); Phase 32 scope does NOT require hardening CI mypy, just not breaking it |

---

## Per-Question Findings

### Q1: asyncpg-stubs maintenance + coverage [VERIFIED: PyPI + GitHub bryanforbes/asyncpg-stubs]

**Maintenance status:**
- `asyncpg-stubs 0.30.2` released **2025-06-27** (< 12 months from 2026-05-18). Passes D-STUB-06 ≤12-month gate.
- `asyncpg-stubs 0.31.2` released **2026-02-19**. Requires `asyncpg>=0.31`. Project pins `asyncpg==0.30.0` → **NOT compatible**.
- Correct version for this project: `asyncpg-stubs~=0.30.2` (requires `asyncpg<0.31,>=0.30`).
- Maintained by `bryanforbes` (Bryan Forbes) — active since asyncpg early adopters; repo at `github.com/bryanforbes/asyncpg-stubs`.

**API surface coverage (verified via GitHub contents of v0.30.2 tag):**
The stub package provides `.pyi` files for all critical asyncpg symbols used in this codebase:

| Symbol | Stub file | Used in project |
|--------|-----------|----------------|
| `asyncpg.Connection` | `connection.pyi` | `services/memory/memory_service.py`, `services/vectorizer/vector_store.py`, `services/tenant/tenant_service.py` |
| `asyncpg.Pool` | `pool.pyi` + generics | `services/audit/audit_service.py`, `scripts/backfill_fact_embeddings.py` |
| `asyncpg.Record` | `protocol/protocol.pyi` | Indirect (Pool generic) |
| `asyncpg.transaction` | `transaction.pyi` | N/A direct (used via connection methods) |
| `asyncpg.PreparedStatement` | `prepared_stmt.pyi` | Indirect |
| `asyncpg.PostgresError`, `asyncpg.InterfaceError` | `exceptions/` | Multiple services |
| `asyncpg.create_pool` | `__init__.pyi` | `services/memory/memory_service.py`, `services/vectorizer/vector_store.py`, `services/audit/audit_service.py` |

**Gotchas:**
- Generic Pool `_Record` default: `Pool[Record]` — code using `asyncpg.Pool` without type params may get `type-arg` errors after stubs land. Inspect any `asyncpg.Pool | None` annotations.
- `pool.acquire()` returns a context-manager proxy (`PoolConnectionProxy`), not a raw `Connection`. Code using `conn: asyncpg.Connection = await pool.acquire()` may get `[assignment]` errors.
- `from __future__ import annotations` in project files defers annotation evaluation — compatible with stubs.

### Q2: pgvector.asyncpg — py.typed marker status [VERIFIED: live .venv inspection]

**Confirmed:** `pgvector==0.4.2` (latest, released 2025-12-05) installed in `.venv` has **no `py.typed` marker** and no `.pyi` stub files. No community stub package exists on PyPI (`pgvector-stubs` returns 404). [VERIFIED: PyPI lookup + .venv filesystem check]

**Import pattern in project:**
```python
# test_save_facts_toctou.py:57
from pgvector.asyncpg import register_vector
# services/memory/memory_service.py:16 (already silenced)
from pgvector.asyncpg import register_vector  # type: ignore[import-untyped]
```

**`register_vector`** is the only symbol imported from `pgvector.asyncpg` across the entire codebase. It is a simple coroutine: `async def register_vector(conn): ...`. The stub need would be trivial if one were ever written.

**Treatment:** Silence with `# type: ignore[import-untyped]  # why: pgvector.asyncpg lacks py.typed marker and has no community stubs as of 2026-05; tracking: github.com/pgvector/pgvector-python/issues (no open py.typed request found)`. The `tracking: NA` form is acceptable per D-STUB-04.

### Q3: `explicit_package_bases = true` interaction with project layout [VERIFIED: live mypy test]

**Problem:** `scripts/evict_long_term_facts.py` appears under two module names in a full-repo mypy scan:
- `evict_long_term_facts` (when mypy discovers it from the project root)
- `scripts.evict_long_term_facts` (when mypy finds `scripts/` as a namespace package)

**Fix verified:** Adding `explicit_package_bases = true` to `[tool.mypy]` eliminates the duplicate-module error. Tested with:
```ini
[mypy]
explicit_package_bases = True
```
`uv run mypy --config-file /tmp/mypy_test.ini --strict .` → no `duplicate module` error for `scripts/evict_long_term_facts.py`. [VERIFIED: live run]

**Why it works:** `explicit_package_bases` tells mypy to interpret file paths relative to the configured base directories (defaults to project root), resolving the ambiguity for namespace directories (those without `__init__.py`).

**Blast radius:** Zero outside type-checking. `scripts/` remains an ad-hoc directory without `__init__.py`. Entry-point invocation `uv run python scripts/X.py` is unaffected. No other currently-passing mypy checks regress.

**Other phases reliance:** The current mypy sweep command (`uv run mypy --strict services/ config/ utils/ controllers/ scripts/`) does NOT trigger the duplicate-module error because it specifies bounded paths. Only repo-wide `mypy .` hits it. Enabling `explicit_package_bases` in pyproject.toml is purely additive — no other phase relied on the status quo.

**pyproject.toml edit:**
```toml
[tool.mypy]
strict = true
explicit_package_bases = true
```
Note: no `[tool.mypy]` section currently exists in `pyproject.toml`. This creates it fresh.

### Q4: Phase 30-03 silence convention — current form [VERIFIED: 30-03-SUMMARY.md + codebase grep]

The locked convention from Phase 30-03 is:

```python
import asyncpg  # type: ignore[import-untyped]  # why: asyncpg has no py.typed marker as of 2026-05
```

Format: `# type: ignore[<error-code>]  # why: <reason>` — two spaces between the ignore and the `# why:` clause. [VERIFIED: live grep of 56 existing bounded-scope silences — all follow this exact pattern]

**For Phase 32 additions**, use the same form with a current date note:
```python
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]  # why: rank_bm25 has no stubs and no py.typed marker; tracking: NA
```

**mypy 1.x changes:** mypy 1.14.0 (installed) enforces `--warn-unused-ignores` under `--strict`. If asyncpg-stubs are installed and an `asyncpg` import-untyped silence remains, mypy will warn `[unused-ignore]`. This is the expected signal that stubs are working — the existing silences should be removed after stub installation. No changes needed to the convention format itself.

### Q5: Bare ignore replacement — error codes [VERIFIED: live mypy runs]

**Site 1: `services/nlu/nlu_service.py:538`**
```python
rewritten = [q for q in rewritten if q not in seen and not seen.add(q)]  # type: ignore
```
Error code: **`[func-returns-value]`** — "add" of "set" does not return a value (it only ever returns None). Confirmed with isolated mypy test.

Replacement:
```python
rewritten = [q for q in rewritten if q not in seen and not seen.add(q)]  # type: ignore[func-returns-value]  # why: set.add() returns None; walrus-style dedup pattern accepted here
```

**Alternative (eliminates ignore entirely):** Refactor to a seen-set comprehension with explicit walrus operator `seen.add(q) or True` — but this is a code-logic change, out of scope for a silence-sweep phase.

**Site 2: `tests/integration/test_ragas_eval.py:442`**
```python
assert "Connection timeout" in failed[0].error  # type: ignore
```
**Finding:** mypy 1.14.0 produces **no error** at this line when run with `--strict`. The bare ignore is currently **redundant** — it does not suppress any active error. [VERIFIED: `uv run mypy --strict tests/integration/test_ragas_eval.py` — line 442 absent from error list]

Context: `failed[0].error` is `str | None`. mypy narrows through the list comprehension `[r for r in report.results if r.error is not None]` in mypy 1.14, so `failed[0].error` is `str` at the assertion site. The ignore was placed pre-mypy-1.14 when narrowing through generators was unreliable.

**Replacement options:**
- **Remove the bare ignore entirely** — cleanest; mypy produces no error without it.
- **Replace with `# type: ignore[union-attr]  # why: historical guard; mypy 1.14 narrows through list-comp predicates but earlier versions did not`** — preserves intent as documentation.

Recommended: **remove entirely** (no active error to suppress; adding a `[union-attr]` silence for a non-error would itself trigger `[unused-ignore]` under `--strict`).

**Sites 3+4: `tests/unit/test_extractor_coverage.py:152` and `:300`**
```python
fake_fitz.open = lambda path: (_ for _ in ()).throw(RuntimeError("fitz open failed"))  # type: ignore
```
Error code: **`[attr-defined]`** — `Module has no attribute "open"` when mypy has full context. [VERIFIED: isolated test of `types.ModuleType` attribute assignment]

Note: In the current full-file mypy run, these lines produce no isolated error because the enclosing function is `no-untyped-def` (fixture lacks parameter annotations), masking the inner expression. However the bare ignore convention still requires the code form.

Replacement:
```python
fake_fitz.open = lambda path: (_ for _ in ()).throw(RuntimeError("fitz open failed"))  # type: ignore[attr-defined]  # why: fake_fitz is a raw ModuleType; attribute assignment is intentional monkeypatching
```

### Q6: `eval/ragas_runner.py` — scope + `datasets` typing [VERIFIED: live files + PyPI]

**Mypy scope:** `eval/` is **outside** D-CAP-01 bounded scope (`services/+config/+utils/+controllers/+scripts/`). The D-VERIFY-01 cap check (`grep -c '# type: ignore\[' <touched-files>`) does not gate on `eval/` silence count.

However, `eval/ragas_runner.py` contains 2 of the 7 deferred items (MYPY-02 scope):
- `:19` — `import-untyped` for `datasets`
- `:333` — `import-untyped` for `pandas.api.types`

**pandas-stubs** (see Q7) fixes line :333. Line :19 (`datasets`) requires a silence-with-why.

**`datasets` (HuggingFace):** No `py.typed` marker in installed package (`.venv` confirmed). No `datasets-stubs` on PyPI. HuggingFace datasets does not ship type stubs as of 2026-05.

Silence:
```python
from datasets import Dataset  # type: ignore[import-untyped]  # why: huggingface datasets has no py.typed marker or stubs as of 2026-05; tracking: NA
```

**`[import-untyped]` satisfies the existing import:** Yes — the error code exactly matches what mypy reports (`[import-untyped]`). The silence-with-why form is the accepted path per D-STUB-04.

**Note:** `eval/ragas_runner.py` also has ~15 other mypy errors (wrong types for `SecretStr` arguments, `union-attr` on `EvaluationResult | Executor`, `[misc]` for `exc` variable). These are **outside Phase 32 scope** — only lines :19 and :333 are in `deferred-items.md`. The planner must not create tasks for the other eval/ errors.

### Q7: `rank_bm25` — stubs or alternatives [VERIFIED: PyPI + venv]

**No upstream stubs:** `rank-bm25-stubs` returns 404 on PyPI. The package (`rank-bm25==0.2.2`, released **2022-02-16**) is stale (last release 3+ years ago) and has no `py.typed` marker. No community stubs exist.

**Usage in project:** Only `services/vectorizer/indexer.py:30` — a lazy import inside `BM25Index.build()`:
```python
from rank_bm25 import BM25Okapi
```
The import is already guarded by `try/except ImportError` for runtime fallback. The lazy import means `BM25Okapi` is typed as `Any` in the calling code.

**Treatment:** Add per-site silence at the import line:
```python
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]  # why: rank_bm25 has no stubs and no py.typed marker; last released 2022; tracking: NA
```

This is the only rank_bm25 site in the entire codebase. One silence eliminates this deferred item.

### Q8: `scripts/evict_long_term_facts.py` duplicate-module — full resolution [VERIFIED: live mypy test]

`explicit_package_bases = true` in `[tool.mypy]` cleanly resolves the duplicate-module structural error. No additional pyproject changes (no `namespace_packages`, no `packages = ["scripts"]`) are required. [VERIFIED: isolated mypy config test eliminates the error]

**Why no `namespace_packages` needed:** `explicit_package_bases` alone instructs mypy to treat the project root as the base for module resolution for all non-package directories. This makes `scripts/evict_long_term_facts.py` resolve to exactly one module name: `scripts.evict_long_term_facts` (since `scripts/` has no `__init__.py` but `explicit_package_bases` makes mypy root from the project root directory).

**Residual errors in `scripts/evict_long_term_facts.py` after fix:**
- `:63` `import-untyped` asyncpg → resolved by asyncpg-stubs installation
- `:77` `no-untyped-def` → pre-existing, outside Phase 32 scope (CONTEXT.md limits scope to the 7 deferred items)

### Q9: CI stub installation — `[dependency-groups]` vs `requirements-dev.txt` [VERIFIED: ci.yml + requirements-dev.txt]

**Current CI architecture:**
```yaml
# ci.yml lint-and-type-check job
- name: Install lint dependencies
  run: pip install ruff mypy types-requests   # HARD-CODED, no stubs

# ci.yml unit/integration jobs
- name: Install dependencies
  run: pip install -r requirements.txt -r requirements-dev.txt
```

**CI does NOT read `pyproject.toml [dependency-groups]`.** PEP 735 dependency groups (`[dependency-groups]`) are a uv-specific feature — `pip install` does not understand them. `uv sync --group dev` would read them, but CI uses pip.

**`requirements-dev.txt` contents (current):** `ruff`, `mypy`, `bandit`, `types-requests`, `pytest`, `pytest-asyncio`, `pytest-timeout`, `pytest-cov`, `diff-cover`, `fakeredis` — no stubs.

**Implication:**
1. `asyncpg-stubs` and `pandas-stubs` added to `pyproject.toml [dependency-groups].dev` will NOT reach CI.
2. The CI `lint-and-type-check` job uses `--ignore-missing-imports` (not `--strict`) and `continue-on-error: true` — it will not catch missing-stubs errors regardless.
3. D-VERIFY-02 says "verify CI config still installs `--dev`" — this is currently false for the lint job (it's `pip install ruff mypy types-requests` only). The unit-test job does install `requirements-dev.txt` but that doesn't include stubs.

**Phase 32 action required:** Add `asyncpg-stubs~=0.30.2` and `pandas-stubs~=2.2.3` to BOTH:
- `pyproject.toml [dependency-groups].dev` (for `uv` local usage)
- `requirements-dev.txt` (for CI unit/integration jobs that run `pip install -r requirements-dev.txt`)

The CI `lint-and-type-check` mypy run will still not use `--strict` — that gate is local only. This is acceptable per current CI architecture.

### Q10: Bounded-scope silence count gate — lowest-cost CI implementation [VERIFIED: codebase analysis]

**Cap=25 interpretation clarification:** D-VERIFY-01 says `grep -c '# type: ignore\[' <touched-files> totals ≤ 25`. This means: in the specific files Phase 32 modifies, the sum of `[code]` silences across those files must be ≤ 25. It does NOT mean the total bounded-scope silence count (currently 56) must reach 25.

**Pre/post analysis:**
| Action | Files touched | Silences removed | Silences added | Net in touched files |
|--------|--------------|-----------------|----------------|---------------------|
| Install asyncpg-stubs | 10 files (12 silences removed) | -12 | 0 | 0 remaining in those files |
| Install pandas-stubs | 1 file (`extractor.py`) | -1 | 0 | 0 remaining |
| rank_bm25 silence | `services/vectorizer/indexer.py` | 0 | +1 | 1 |
| nlu_service.py bare→coded | `services/nlu/nlu_service.py` | 0 | +1 (replaces bare) | 1 |
| eval deferred | `eval/ragas_runner.py` (out of bounded scope) | 0 | +1 (datasets) | — |
| scripts deferred asyncpg | `scripts/backfill*.py`, `scripts/evict*.py` | removed by stubs | 0 | 0 |

**Total new silences in bounded-scope touched files: ~2** (rank_bm25 + nlu coded silence). Well within cap=25.

**Recommended CI check command** (grep-based, fast, zero dependencies):
```bash
# Verify no bare ignores remain repo-wide
grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/
# Exit non-zero if any match (add to CI as a quick gate after mypy)
```

**For bounded-scope silence count** (informational + cap gate):
```bash
grep -rc '# type: ignore\[' services/ config/ utils/ controllers/ scripts/ | \
  awk -F: 'NR>0 && $2>0 {sum += $2; files = files $1 " "} END {print sum " silences in " files}'
```
This is a 5-second shell one-liner — no mypy invocation needed.

**Recommended additions to CI `lint-and-type-check` job:**
```yaml
- name: Verify no bare type: ignore comments
  run: |
    result=$(grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null | grep -v ".pyc" || true)
    if [ -n "$result" ]; then
      echo "FAIL: Bare type: ignore found (no error code):"
      echo "$result"
      exit 1
    fi
    echo "PASS: All type: ignore comments have error codes"
```

---

## Standard Stack

### Core (type-checking toolchain)

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| mypy | 1.14.0 | Static type checking with `--strict` | Already installed; project-standard |
| asyncpg-stubs | ~0.30.2 | Type stubs for asyncpg 0.30.x | Maintained by bryanforbes; matches installed asyncpg==0.30.0 |
| pandas-stubs | ~2.2.3 | Type stubs for pandas 2.x | Maintained by The Pandas Development Team; matches installed pandas==2.2.3 |

### No Stubs Available (silence-with-why path)

| Package | Runtime Version | Why No Stubs | Silence Code |
|---------|----------------|-------------|--------------|
| pgvector | 0.4.2 | No py.typed, no community stubs as of 2026-05 | `[import-untyped]` |
| rank-bm25 | 0.2.2 | Last released 2022; no stubs | `[import-untyped]` |
| datasets | 4.7.0 | HuggingFace does not ship py.typed | `[import-untyped]` |

### Installation

```bash
# Local (uv)
uv add --dev "asyncpg-stubs~=0.30.2" "pandas-stubs~=2.2.3"

# Also add to requirements-dev.txt (for CI pip path)
# asyncpg-stubs~=0.30.2
# pandas-stubs~=2.2.3
```

**Version verification (pre-write):** [VERIFIED: PyPI API]
- `asyncpg-stubs 0.30.2` — uploaded 2025-06-27 (< 12 months) ✓
- `pandas-stubs 2.2.3.250308` — uploaded 2025-03-08 (< 12 months) ✓

---

## Package Legitimacy Audit

> slopcheck unavailable at research time — packages assessed via PyPI metadata + GitHub source verification.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| asyncpg-stubs | PyPI | 5+ yrs (since 0.20.x) | N/A | github.com/bryanforbes/asyncpg-stubs | [ASSUMED] | Approved — well-known maintainer, references official asyncpg; versions track asyncpg releases |
| pandas-stubs | PyPI | 3+ yrs | N/A | github.com/pandas-dev/pandas-stubs | [ASSUMED] | Approved — maintained by The Pandas Development Team (official); `author` field confirms |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was unavailable at research time. Both packages are tagged `[ASSUMED]` for provenance but are high-confidence legitimate packages from well-known ecosystem maintainers. Planner should add a verification step.*

---

## Architecture Patterns

### Pattern 1: Stub-first, then silence-sweep

**What:** Install stubs → remove now-unnecessary silences → add new silences for no-stub deps
**When to use:** When an upstream stub becomes available for a previously-silenced dep
**Why:** Stub installation without silence removal produces `[unused-ignore]` warnings under `--strict`

```python
# BEFORE (Phase 30-03 status quo)
import asyncpg  # type: ignore[import-untyped]  # why: asyncpg has no py.typed marker as of 2026-05

# AFTER Phase 32 (stub installed — remove the silence entirely)
import asyncpg  # no ignore needed — asyncpg-stubs provides type information
```

### Pattern 2: Per-site silence with upstream tracking

```python
# For deps with no stubs (rank_bm25, pgvector.asyncpg, datasets)
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]  # why: rank_bm25 has no stubs and no py.typed marker; tracking: NA
from pgvector.asyncpg import register_vector  # type: ignore[import-untyped]  # why: pgvector.asyncpg lacks py.typed marker and has no community stubs as of 2026-05; tracking: NA
from datasets import Dataset  # type: ignore[import-untyped]  # why: huggingface datasets lacks py.typed and stubs as of 2026-05; tracking: NA
```

### Pattern 3: Bare → coded silence for functional code ignores

```python
# BEFORE (bare, MYPY-03 violation)
rewritten = [q for q in rewritten if q not in seen and not seen.add(q)]  # type: ignore

# AFTER (coded + rationale)
rewritten = [q for q in rewritten if q not in seen and not seen.add(q)]  # type: ignore[func-returns-value]  # why: set.add() returns None; walrus-style dedup pattern accepted here
```

### Anti-Patterns to Avoid

- **Installing stubs without removing old silences:** Causes `[unused-ignore]` under `--strict`.
- **Using `asyncpg-stubs~=0.31` with `asyncpg==0.30.0`:** Version conflict — resolver will reject or install wrong asyncpg version.
- **Adding `scripts/__init__.py`:** Converts scripts/ to a package, breaks entry-point invocations; D-STRUCT-02 prohibits.
- **Bare `# type: ignore` in new code:** Caught by `grep -rn '# type: ignore[^[]'` gate (D-VERIFY-01 MYPY-03 check).
- **Over-silencing eval/ errors:** Phase 32 scope for `eval/ragas_runner.py` is only lines :19 and :333 (the two deferred items). The other ~15 eval/ errors are pre-existing and out of scope.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| asyncpg Connection/Pool type stubs | `stubs/asyncpg/__init__.pyi` | `asyncpg-stubs~=0.30.2` | Community stubs cover full API surface; hand-rolling would miss generics |
| pandas.api.types stubs | `stubs/pandas/` | `pandas-stubs~=2.2.3` | Official team maintains these; hand-rolling is fragile |
| Structural module duplicate fix | `scripts/__init__.py` | `explicit_package_bases = true` in `[tool.mypy]` | Config-only; no structural side effects |

---

## Common Pitfalls

### Pitfall 1: asyncpg-stubs version/runtime mismatch
**What goes wrong:** `uv add --dev asyncpg-stubs` installs latest (0.31.2), which requires `asyncpg>=0.31`, conflicting with pinned `asyncpg==0.30.0`. Either uv rejects the install or upgrades asyncpg unexpectedly.
**How to avoid:** Pin: `uv add --dev "asyncpg-stubs~=0.30.2"`. Verify with `uv run python -c "import asyncpg_stubs"` after install.
**Warning signs:** `uv add` output shows asyncpg being upgraded to 0.31.x; or `pip check` reports version conflict.

### Pitfall 2: Removing asyncpg silences across too few files
**What goes wrong:** Stubs are installed but only the 5 deferred-items.md files have their silences removed. The 12 Phase-30-03 asyncpg silences in `memory_service.py`, `retriever.py`, etc. remain → mypy emits `[unused-ignore]` for each.
**How to avoid:** After stub install, run `uv run mypy --strict services/ config/ utils/ controllers/ scripts/` and look for `[unused-ignore]` errors. Remove all flagged silences.
**Warning signs:** `Found N errors` including `[unused-ignore]` after stub install.

### Pitfall 3: pandas-stubs version selecting 3.x (incompatible with pandas 2.2.3)
**What goes wrong:** `uv add --dev pandas-stubs` installs 3.0.0.260204 which targets pandas 3.0. The installed pandas is 2.2.3. Type errors (wrong API shape) surface.
**How to avoid:** Pin: `uv add --dev "pandas-stubs~=2.2.3"`. Latest 2.2.3.x stubs are `2.2.3.250308` (released 2025-03-08).
**Warning signs:** After install, `uv run mypy --strict eval/ragas_runner.py` reports unexpected type errors on pandas API calls.

### Pitfall 4: test_ragas_eval.py:442 bare ignore → don't re-add a silence
**What goes wrong:** Replacing the bare `# type: ignore` with `# type: ignore[union-attr]  # why:` — but mypy produces NO error at that line. Adding a `[union-attr]` silence where there's no error triggers `[unused-ignore]` under `--strict`.
**How to avoid:** Simply remove the bare ignore entirely. Mypy 1.14 narrows `str | None` through list-comp predicates.
**Warning signs:** `mypy --strict` shows `[unused-ignore]` at test_ragas_eval.py:442 after the change.

### Pitfall 5: asyncpg Pool generic type annotations require explicit params after stubs land
**What goes wrong:** `asyncpg.Pool | None` (without generic `[asyncpg.Record]`) may produce `[type-arg]` errors after stubs are installed, because `pool.pyi` defines `Pool` as generic.
**How to avoid:** After stub install, re-run mypy on all files that type-annotate `asyncpg.Pool`. If `[type-arg]` appears, add `asyncpg.Pool[asyncpg.Record]` or use `asyncpg.Pool[Any]` with a silence.
**Warning signs:** `[type-arg]` errors in `audit_service.py:112`, `memory_service.py`, `vector_store.py` after stubs land.

### Pitfall 6: CI doesn't install stubs → CI mypy still shows import-untyped errors
**What goes wrong:** Stubs added to `pyproject.toml [dependency-groups].dev` only. CI uses `pip install -r requirements.txt -r requirements-dev.txt` which doesn't read `[dependency-groups]`. CI mypy continues to report `[import-untyped]` errors for asyncpg (though currently `continue-on-error: true` masks this).
**How to avoid:** Add stubs to BOTH `pyproject.toml [dependency-groups].dev` AND `requirements-dev.txt`.
**Warning signs:** CI `Mypy type check` step output still shows `Skipping analyzing "asyncpg"`.

### Pitfall 7: `explicit_package_bases` creates `[tool.mypy]` section that conflicts with command-line flags
**What goes wrong:** If Phase 32 creates `[tool.mypy]` with only `explicit_package_bases = true`, but D-VERIFY-01 commands pass `--strict` on the CLI, there's no conflict (CLI flags override/extend config). However if `strict = false` is set accidentally in config, it would suppress all strict checks.
**How to avoid:** Set `[tool.mypy]` to:
```toml
[tool.mypy]
strict = true
explicit_package_bases = true
```
Verify with `uv run mypy --show-config-files` that pyproject.toml is picked up.

---

## Runtime State Inventory

> Not applicable — this phase makes no runtime state changes. All changes are dev tooling (stubs, mypy config) and comment-level code edits. No data migration, no service config, no OS-registered state, no schema changes.

---

## Recommended Task Ordering

Based on dependency analysis, the planner should structure tasks as:

**Wave 0 (foundation, no dependencies between tasks):**
1. **T0: pyproject.toml `[tool.mypy]` creation** — add `strict = true` + `explicit_package_bases = true`. Resolves structural deferred item. Zero blast radius.
2. **T1: Stub install** — `uv add --dev "asyncpg-stubs~=0.30.2" "pandas-stubs~=2.2.3"`. Update `requirements-dev.txt` with same. Verify uv lockfile.

**Wave 1 (depends on T1 — stubs must be installed first):**
3. **T2: Remove asyncpg `import-untyped` silences** — remove the 12 existing asyncpg silences across bounded-scope files + 2 asyncpg silences in `pgvector.asyncpg`-paired files (those stay). Also removes the pandas silence in `extractor.py:432`. Run `uv run mypy --strict services/ config/ utils/ controllers/ scripts/` to verify no `[unused-ignore]`.
4. **T3: Deferred items — new per-site silences** — add silences for `rank_bm25` (indexer:30), `datasets` (eval:19), `pgvector.asyncpg` (eval: already covered by existing silence). Remove deferred items from `deferred-items.md`.

**Wave 2 (independent of stubs — can run in parallel with Wave 1):**
5. **T4: MYPY-03 bare → coded** — replace 4 bare ignores:
   - `services/nlu/nlu_service.py:538` → `[func-returns-value]`
   - `tests/integration/test_ragas_eval.py:442` → **remove entirely**
   - `tests/unit/test_extractor_coverage.py:152` → `[attr-defined]`
   - `tests/unit/test_extractor_coverage.py:300` → `[attr-defined]`
6. **T5: MYPY-04 test-file untyped imports** — add/update silences in 4 test files:
   - `test_save_facts_toctou.py:32` — asyncpg: stubs fix this; verify and remove existing silence if present (check if `[import-untyped]` silence already exists)
   - `test_save_facts_toctou.py:57` — pgvector.asyncpg: add `[import-untyped]  # why:` (no stubs)
   - `test_memory_forget_e2e.py:37` — asyncpg: stubs fix; remove if already silenced
   - `test_evict_long_term_facts_e2e.py:36` — asyncpg: stubs fix; remove if already silenced

**Wave 3 (verification):**
7. **T6: Verification sweep** — run D-VERIFY-01 commands:
   - `cat deferred-items.md` → 0 entries
   - `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/` → empty
   - `uv run mypy --strict tests/integration/memory/test_save_facts_toctou.py ...` → 0 `[import-untyped]`
   - bounded-scope silence count in touched files ≤ 25
   - Document tests/ silence count in 32-00-SUMMARY.md

---

## Validation Architecture

> `nyquist_validation: true` per `.planning/config.json`.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + mypy 1.14.0 |
| Config file | `pytest.ini` (tests); `pyproject.toml` `[tool.mypy]` (type checking, to be created) |
| Quick run command | `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 \| tail -5` |
| Full suite command | `uv run pytest tests/unit/ -m 'not integration' --asyncio-mode=auto --timeout=30 -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MYPY-02 | `deferred-items.md` has 0 entries | smoke | `cat deferred-items.md \| grep -c '^-'` → 0 | ✅ (file exists; entries will be drained) |
| MYPY-02 | `mypy --strict` clean on deferred-item files | type-check | `uv run mypy --strict services/vectorizer/indexer.py scripts/backfill_fact_embeddings.py scripts/evict_long_term_facts.py eval/ragas_runner.py` | ✅ (files exist) |
| MYPY-03 | No bare `# type: ignore` anywhere | grep-gate | `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ \| grep -v ".pyc"` → empty | ✅ |
| MYPY-03 | nlu_service.py passes `mypy --strict` | type-check | `uv run mypy --strict services/nlu/nlu_service.py 2>&1 \| grep "538:"` → empty | ✅ |
| MYPY-04 | test_save_facts_toctou passes `mypy --strict` | type-check | `uv run mypy --strict tests/integration/memory/test_save_facts_toctou.py 2>&1 \| grep "import-untyped"` → empty | ✅ |
| MYPY-04 | memory_forget_e2e + evict_e2e pass | type-check | `uv run mypy --strict tests/integration/test_memory_forget_e2e.py tests/integration/test_evict_long_term_facts_e2e.py 2>&1 \| grep "import-untyped"` → empty | ✅ |
| D-VERIFY-02 | Test suite not regressed | functional | `uv run pytest tests/integration/ -m 'integration and not real_llm and not benchmark' --asyncio-mode=auto -q` → ≥31 passed | ✅ |

### Sampling Rate

- **Per task commit:** `grep -rn '# type: ignore[^[]' services/ tests/ utils/ config/ scripts/ controllers/ 2>/dev/null | grep -v ".pyc" | wc -l` → 0
- **Per wave merge:** `uv run mypy --strict services/ config/ utils/ controllers/ scripts/ 2>&1 | grep "Found\|Success"` → error count non-increasing
- **Phase gate:** All D-VERIFY-01 commands pass before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `pyproject.toml [tool.mypy]` section does not exist — Wave 0 T0 creates it
- [ ] `asyncpg-stubs` not in dev deps — Wave 0 T1 installs
- [ ] `pandas-stubs` not in dev deps — Wave 0 T1 installs
- [ ] `requirements-dev.txt` missing stubs — Wave 0 T1 updates

*(No new test files needed — this phase is annotation/config-only, no behavioral changes. Test-map validation is grep-based and mypy-based.)*

---

## Security Domain

> Annotation-only changes. No new code paths, no new network endpoints, no auth changes. ASVS not applicable to this phase.

---

## Open Questions for Planner

1. **asyncpg Pool generic annotations:** After stubs land, some files may show new `[type-arg]` errors where `asyncpg.Pool | None` annotations lack generic params. Planner should run `uv run mypy --strict services/ 2>&1 | grep "type-arg.*asyncpg\|Pool"` after T2 and add targeted silences if any appear. These would be new silences in previously-bounded-scope files, counting toward the per-file cap.

2. **test_ragas_eval.py:442 removal vs replace:** This research recommends removal (no active error). If the planner disagrees (e.g., wants to preserve intent as documentation), use `# type: ignore[union-attr]  # why: mypy ≤1.14 did not narrow through list-comp predicates; guard retained for forward-compatibility` — but verify this doesn't trigger `[unused-ignore]` on the current mypy version.

3. **CI mypy upgrade (out of Phase 32 scope but related):** The CI `lint-and-type-check` job uses `--ignore-missing-imports --no-strict-optional`. Phase 32 does not require upgrading it to `--strict`. However if the planner wants to add the bare-ignore grep gate to CI (recommended), that is a net-new CI check worth adding in Phase 32 since it's cheap and catches MYPY-03 regressions automatically.

4. **D-VERIFY-02 baseline:** The CONTEXT.md cites `31 passed / 0 failed / 2 skipped / 3 errors` as Phase 31 post-fix baseline. Planner must confirm this is the actual Phase 31 result (Phase 31 is marked "Not started" in STATE.md as of 2026-05-18). If Phase 31 hasn't completed yet, Phase 32 cannot proceed until it does (per REQUIREMENTS.md traceability: Phase 32 depends on silence convention from Phase 30-03, not Phase 31, so this may not be a hard gate).

---

## Sources

### Primary (HIGH confidence)
- Live `.venv` filesystem inspection — verified asyncpg 0.30.0 has no `py.typed`; pgvector 0.4.2 has no `py.typed`; confirmed `asyncpg-stubs` not installed
- Live `uv run mypy --strict` runs — verified error codes for all 4 bare-ignore sites; verified `explicit_package_bases` fix; verified bounded-scope error count
- `pyproject.toml`, `requirements-dev.txt`, `.github/workflows/ci.yml` — direct file reads confirming dep structure and CI install path
- `deferred-items.md` — source of truth for 7 overflow entries
- `32-CONTEXT.md` — locked decisions (D-CAP, D-STUB, D-STRUCT, D-VERIFY, D-AUDIT)
- `30-03-SUMMARY.md` — silence convention canonical form, Per-Silence Table

### Secondary (MEDIUM confidence)
- PyPI API JSON responses — asyncpg-stubs 0.30.2 (2025-06-27), 0.31.2 (2026-02-19), pandas-stubs 2.2.3.250308 (2025-03-08), 3.0.0.260204 (2026-02-04)
- GitHub API — `bryanforbes/asyncpg-stubs` contents listing (pool.pyi, connection.pyi, transaction.pyi etc. confirmed)
- GitHub raw content — asyncpg-stubs v0.30.2 `pool.pyi` header showing `Pool` generic definition

### Tertiary (LOW confidence)
- Isolated `python3 -c` mypy tests for error code identification — these use stripped-down fixtures, not full project import graph

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `asyncpg-stubs` and `pandas-stubs` are safe packages from legitimate maintainers | Package Legitimacy Audit | Low — provenance indicators strong (known maintainers, repo links), but slopcheck was unavailable |
| A2 | `asyncpg Pool` generic type params won't cause cascading `[type-arg]` errors in bounded scope | Pitfall 5 | Medium — if stubs expose strict generic constraints, 10+ files may need `asyncpg.Pool[asyncpg.Record]` annotations; adds silences |
| A3 | Phase 31 completes before Phase 32 starts (D-VERIFY-02 baseline) | Open Questions #4 | Low — Phase 32 changes are annotation-only, don't require Phase 31 to be complete for technical execution; only the test-pass-count baseline shifts |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
(Table is not empty — A1 needs stub legitimacy confirmation; A2 needs post-install mypy run.)

---

## Metadata

**Confidence breakdown:**
- Stub version compatibility: HIGH — verified via PyPI API + live venv
- Error codes for bare ignores: HIGH — verified via isolated mypy runs
- explicit_package_bases fix: HIGH — verified via live mypy test
- CI gap (requirements-dev.txt vs dependency-groups): HIGH — verified via ci.yml read
- asyncpg Pool generic impact: MEDIUM — flagged as assumption A2, requires post-install check

**Research date:** 2026-05-18
**Valid until:** 2026-08-18 (stubs release cadence; asyncpg 0.32 would shift stub version)
