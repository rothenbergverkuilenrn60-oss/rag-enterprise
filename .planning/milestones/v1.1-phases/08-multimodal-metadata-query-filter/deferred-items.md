# Phase 8 — Deferred Items

Out-of-scope discoveries during plan execution. Not fixed in 08-01.

## 08-01 (Wave 0)

### ruff F541 in config/settings.py (lines 404-406)
- Discovered while running `ruff check config/settings.py` after Task 1 edit.
- Pre-existing f-string-without-placeholders in the SECRET_KEY validator error message.
- Not caused by 08-01 changes (we only added one line: `pgvector_ef_search_filtered`).
- Recommend a chore commit in a future plan to switch the three lines to plain strings or concatenate to a single f-string.

### mypy --strict generic-type warning at utils/models.py:93
- `dict` used without type parameters in an existing field (NOT one of the new section_* fields).
- Pre-existing; outside Wave-0 scope.
- The two new fields (`section_id: str = ""`, `section_title: str = ""`) introduce zero new mypy errors — confirmed by isolating diff.
