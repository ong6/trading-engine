"""Read-only production data attachments for account execution.

The main engine database deliberately does not contain Massive daily/minute bars or
point-in-time short data.  Production entry points attach those isolated databases
for the duration of one request/run and expose only temporary compatibility views.
Unit callers can continue to plant the same tables directly in an in-memory store.
"""
from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import duckdb

from engine.lib.settings import REPO_ROOT

SOURCE_PATHS = {
    "account_daily": ("TRADING_ENGINE_FREE_SOURCES_DB", "free-sources.duckdb"),
    "account_minute": ("TRADING_ENGINE_MASSIVE_MINUTE_DB", "massive-minute.duckdb"),
    "account_short": ("TRADING_ENGINE_SHORT_DATA_DB", "short-data.duckdb"),
}
SOURCE_TABLES = {
    "account_daily": ("free_daily_bars",),
    "account_minute": ("massive_minute_bars",),
    "account_short": ("regsho_threshold", "finra_short_interest"),
}


def _path(name: str, filename: str, environ: Mapping[str, str]) -> Path:
    configured = environ.get(name)
    if configured:
        value = Path(configured).expanduser()
        return value if value.is_absolute() else REPO_ROOT / value
    return REPO_ROOT / "store" / "pit" / filename


def _quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _main_has(con: duckdb.DuckDBPyConnection, relation: str) -> bool:
    current = con.execute("SELECT current_database()").fetchone()[0]
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_catalog IN (?, 'temp') "
        "AND table_name=? LIMIT 1",
        [current, relation],
    ).fetchone() is not None


def _attached_has(
    con: duckdb.DuckDBPyConnection, alias: str, relation: str,
) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_catalog=? "
        "AND table_name=? LIMIT 1",
        [alias, relation],
    ).fetchone() is not None


@contextmanager
def production_sources(
    con: duckdb.DuckDBPyConnection,
    *,
    environ: Mapping[str, str] = os.environ,
) -> Iterator[duckdb.DuckDBPyConnection | None]:
    """Attach available account data stores read-only and yield the short source.

    Missing stores stay explicit: daily/minute readers return no bar and shorts are
    refused as ``locate_unavailable``.  No production entry point silently falls
    back from an account's selected source to the operational ``prices`` table.
    """
    attached: list[str] = []
    views: list[str] = []
    try:
        for alias, (environment_name, filename) in SOURCE_PATHS.items():
            path = _path(environment_name, filename, environ)
            if not path.is_file():
                continue
            con.execute(f"ATTACH {_quote(path)} AS {alias} (READ_ONLY)")
            attached.append(alias)
            for relation in SOURCE_TABLES[alias]:
                if _main_has(con, relation) or not _attached_has(con, alias, relation):
                    continue
                con.execute(
                    f"CREATE TEMP VIEW {relation} AS "
                    f"SELECT * FROM {alias}.main.{relation}"
                )
                views.append(relation)
        short_ready = all(
            _main_has(con, relation) for relation in SOURCE_TABLES["account_short"]
        )
        yield con if short_ready else None
    finally:
        for relation in reversed(views):
            con.execute(f"DROP VIEW IF EXISTS {relation}")
        for alias in reversed(attached):
            con.execute(f"DETACH {alias}")


__all__ = ["production_sources"]
