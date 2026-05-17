"""Unit tests for utils.asyncpg_helper.prepare_dsn (Plan 26-01 / TD-03).

Pure function — no asyncpg dependency, no I/O, no fixtures beyond the env-var
bootstrap convention used across the test suite.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from utils.asyncpg_helper import prepare_dsn


def test_strips_asyncpg_scheme() -> None:
    dsn, ssl = prepare_dsn("postgresql+asyncpg://u:p@h/d")
    assert dsn == "postgresql://u:p@h/d"
    assert ssl == {}


def test_strips_ssl_disable_query_param() -> None:
    dsn, ssl = prepare_dsn("postgresql://u@h/d?ssl=disable")
    assert dsn == "postgresql://u@h/d"
    assert ssl == {"ssl": "disable"}


def test_strips_ssl_disable_ampersand_param() -> None:
    dsn, ssl = prepare_dsn("postgresql://u@h/d?other=1&ssl=disable")
    assert dsn == "postgresql://u@h/d?other=1"
    assert ssl == {"ssl": "disable"}


def test_no_ssl_returns_empty_kwarg() -> None:
    dsn, ssl = prepare_dsn("postgresql://u@h/d")
    assert dsn == "postgresql://u@h/d"
    assert ssl == {}


def test_no_scheme_change_returns_dsn_unchanged() -> None:
    dsn_in = "postgresql://u@h/d"
    dsn_out, _ = prepare_dsn(dsn_in)
    assert dsn_out == dsn_in


def test_combines_scheme_and_ssl_strip() -> None:
    dsn, ssl = prepare_dsn("postgresql+asyncpg://u@h/d?ssl=disable")
    assert dsn == "postgresql://u@h/d"
    assert ssl == {"ssl": "disable"}


def test_returns_tuple_str_dict() -> None:
    result = prepare_dsn("postgresql://u@h/d")
    assert isinstance(result, tuple)
    assert isinstance(result[0], str)
    assert isinstance(result[1], dict)


# ------ A1 (eng-review): short-form scheme strip ------
def test_strips_postgres_short_asyncpg_scheme() -> None:
    """v1.6 audit code stripped only `+asyncpg`; helper must handle both schemes
    so audit's `postgres+asyncpg://` DSNs still produce valid asyncpg input."""
    dsn, ssl = prepare_dsn("postgres+asyncpg://u@h/d")
    assert dsn == "postgres://u@h/d"
    assert ssl == {}


# ------ C1 (eng-review): malformed URL after strip ------
def test_strips_ssl_disable_with_following_params() -> None:
    """v1.6 token-loop produced `postgresql://u@h/d&other=1` (leading `&`,
    no `?`) — asyncpg rejects. C1 fix: handle ssl-at-start-with-other-params."""
    dsn, ssl = prepare_dsn("postgresql://u@h/d?ssl=disable&other=1")
    assert dsn == "postgresql://u@h/d?other=1"
    assert ssl == {"ssl": "disable"}
