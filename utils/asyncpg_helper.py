"""asyncpg DSN normalization helper.

Centralizes the SQLAlchemy-style DSN transformations that asyncpg's URL parser
does not understand natively. Consumed by `services/memory` and `services/audit`
pool builders (see Plans 26-03, 26-04).

Pure function — no asyncpg dependency, no logging, no settings import.
"""

from __future__ import annotations


def prepare_dsn(dsn: str) -> tuple[str, dict[str, str]]:
    """Normalize a SQLAlchemy-flavored DSN for direct asyncpg consumption.

    Two transformations, both centralizing what was duplicated in v1.6
    (services/memory/memory_service.py:163-172 +
    services/audit/audit_service.py:261-270):

    1. Strip `postgresql+asyncpg://` (and the short-form `postgres+asyncpg://`)
       so asyncpg parses the scheme.
    2. Strip `?ssl=disable` / `&ssl=disable` tokens out of the URL and
       return them as a separate `{"ssl": "disable"}` kwarg dict — asyncpg's
       URL parser otherwise treats `ssl` as a server_setting and raises
       `CantChangeRuntimeParamError`.

    Returns `(clean_dsn, ssl_kwarg)`. Caller forwards `ssl_kwarg` via
    `**ssl_kwarg` to `asyncpg.create_pool` or `asyncpg.connect`. When no
    `ssl=disable` token is present, the second tuple member is an empty
    dict (not None) so callers can unconditionally splat it.
    """
    # Scheme strip — order matters: longer prefix first so the longer
    # replace consumes `postgresql+asyncpg://` cleanly before the shorter
    # `postgres+asyncpg://` rule can fire on already-stripped text.
    clean_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    clean_dsn = clean_dsn.replace("postgres+asyncpg://", "postgres://")

    # C1 (eng-review): order matters. Handle the four ssl-token positions:
    #   1. `&ssl=disable`          → strip cleanly (last of N params)
    #   2. `?ssl=disable&`         → strip prefix-with-delimiter (first of N)
    #   3. `?ssl=disable`          → strip sole-param case (no other params)
    # The middle-of-N case (`?a=1&ssl=disable&b=2`) reduces to case 1.
    ssl_kwarg: dict[str, str] = {}
    if "&ssl=disable" in clean_dsn:
        clean_dsn = clean_dsn.replace("&ssl=disable", "")
        ssl_kwarg["ssl"] = "disable"
    if "?ssl=disable&" in clean_dsn:
        clean_dsn = clean_dsn.replace("?ssl=disable&", "?")
        ssl_kwarg["ssl"] = "disable"
    if "?ssl=disable" in clean_dsn:
        clean_dsn = clean_dsn.replace("?ssl=disable", "")
        ssl_kwarg["ssl"] = "disable"

    return clean_dsn, ssl_kwarg
