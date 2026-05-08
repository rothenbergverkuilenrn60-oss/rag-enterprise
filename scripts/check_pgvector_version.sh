#!/usr/bin/env bash
# scripts/check_pgvector_version.sh — Phase 8 Wave 0 environment gate
#
# Asserts the connected PostgreSQL server has pgvector extension >= 0.8.0
# (required for SET LOCAL hnsw.iterative_scan = 'relaxed_order' — pgvector CHANGELOG 0.8.0).
#
# Usage:
#   PG_DSN=postgresql://rag:rag@localhost:5432/ragdb bash scripts/check_pgvector_version.sh
#   (defaults to the conftest.py DSN if PG_DSN is unset)
#
# Exit codes:
#   0 — extension present and version >= 0.8.0
#   1 — extension missing
#   2 — version < 0.8.0
#   3 — connection failed

set -euo pipefail

PG_DSN="${PG_DSN:-postgresql://rag:rag@localhost:5432/ragdb}"
REQUIRED_MAJOR=0
REQUIRED_MINOR=8

if ! command -v psql >/dev/null 2>&1; then
    echo "[check_pgvector_version] psql not on PATH; skipping (CI host responsibility)" >&2
    exit 0
fi

VERSION=$(psql "$PG_DSN" -tAc \
    "SELECT extversion FROM pg_extension WHERE extname='vector';" 2>/dev/null) \
    || { echo "[check_pgvector_version] connection failed: $PG_DSN" >&2; exit 3; }

if [[ -z "$VERSION" ]]; then
    echo "[check_pgvector_version] FAIL: pgvector extension not installed" >&2
    exit 1
fi

MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)

if (( MAJOR < REQUIRED_MAJOR )) || \
   (( MAJOR == REQUIRED_MAJOR && MINOR < REQUIRED_MINOR )); then
    echo "[check_pgvector_version] FAIL: pgvector $VERSION < required ${REQUIRED_MAJOR}.${REQUIRED_MINOR}.0" >&2
    echo "    hnsw.iterative_scan requires pgvector >= 0.8.0 (added 2024-10-30)" >&2
    echo "    Upgrade: apt-get install postgresql-16-pgvector or rebuild from source." >&2
    exit 2
fi

echo "[check_pgvector_version] OK: pgvector $VERSION (>= ${REQUIRED_MAJOR}.${REQUIRED_MINOR}.0)"
exit 0
