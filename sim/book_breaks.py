"""Recorded simulator-book breaks and their effective evaluation boundaries."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import duckdb

from engine.lib.util import table_exists

from . import schema

BASELINE_COST_PROFILE = "baseline_v1"
COST_PROFILE_BREAK = "cost_profile"
ACCOUNT_DEFAULTS = {
    "engine": "league",
    "cost_profile": BASELINE_COST_PROFILE,
    "account_type": "cash_legacy",
    "visibility": "public",
    "price_source": "prices",
    "day_trade_rule": "pdt_25k_legacy",
    "allow_short": False,
}


def _ensure_account_table(con: duckdb.DuckDBPyConnection) -> None:
    """Temporary R13 compatibility for p22/base before L0 is re-merged."""
    con.execute(
        """CREATE TABLE IF NOT EXISTS portfolio_accounts (
        portfolio_id VARCHAR PRIMARY KEY,
        engine VARCHAR NOT NULL DEFAULT 'league',
        cost_profile VARCHAR NOT NULL DEFAULT 'baseline_v1',
        account_type VARCHAR NOT NULL DEFAULT 'cash_legacy',
        visibility VARCHAR NOT NULL DEFAULT 'public',
        status VARCHAR,
        price_source VARCHAR NOT NULL DEFAULT 'prices',
        day_trade_rule VARCHAR NOT NULL DEFAULT 'pdt_25k_legacy',
        allow_short BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMP)"""
    )


def portfolio_account(con: duckdb.DuckDBPyConnection, portfolio_id: str) -> dict:
    """Use L0's R13 reader, with a temporary side-table fallback on this base."""
    reader = getattr(schema, "portfolio_account", None)
    if reader is not None:
        return reader(con, portfolio_id)
    active = con.execute(
        "SELECT active FROM portfolios WHERE id=?", [portfolio_id]
    ).fetchone()
    if active is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    values = {**ACCOUNT_DEFAULTS, "status": "active" if active[0] else "inactive"}
    if table_exists(con, "portfolio_accounts"):
        row = con.execute(
            "SELECT engine,cost_profile,account_type,visibility,status,price_source,"
            "day_trade_rule,allow_short,updated_at FROM portfolio_accounts "
            "WHERE portfolio_id=?",
            [portfolio_id],
        ).fetchone()
        if row is not None:
            keys = (
                "engine", "cost_profile", "account_type", "visibility", "status",
                "price_source", "day_trade_rule", "allow_short", "updated_at",
            )
            values.update(dict(zip(keys, row, strict=True)))
            values["status"] = values["status"] or (
                "active" if active[0] else "inactive"
            )
    return {"portfolio_id": portfolio_id, **values}


def set_portfolio_account(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, **fields,
) -> dict:
    """Use L0's R13 writer, with a temporary side-table fallback on this base."""
    writer = getattr(schema, "set_portfolio_account", None)
    if writer is not None:
        return writer(con, portfolio_id, **fields)
    unknown = set(fields) - (set(ACCOUNT_DEFAULTS) | {"status", "updated_at"})
    if unknown:
        raise ValueError(f"unknown portfolio account fields: {sorted(unknown)}")
    current = portfolio_account(con, portfolio_id)
    current.update(fields)
    _ensure_account_table(con)
    con.execute(
        "INSERT OR REPLACE INTO portfolio_accounts VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            portfolio_id,
            current["engine"],
            current["cost_profile"],
            current["account_type"],
            current["visibility"],
            current["status"],
            current["price_source"],
            current["day_trade_rule"],
            current["allow_short"],
            current.get("updated_at"),
        ],
    )
    return portfolio_account(con, portfolio_id)


def latest_break(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    *,
    kind: str = COST_PROFILE_BREAK,
) -> date | None:
    """Return the newest recorded break of ``kind`` for one portfolio."""
    if not table_exists(con, "sim_book_breaks"):
        return None
    row = con.execute(
        "SELECT MAX(break_date) FROM sim_book_breaks "
        "WHERE portfolio_id=? AND kind=?",
        [portfolio_id, kind],
    ).fetchone()
    return None if row is None else row[0]


def effective_cost_profile(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    session_date: date,
) -> str:
    """Resolve the cost profile without charging a migrated book before D0.

    The portfolio column holds the current profile. A future break row supplies
    its ``from_value`` for pre-break replays, which is what keeps a rehearsal of
    the last pre-D0 session byte-equivalent after the migration has run.
    """
    if table_exists(con, "sim_book_breaks"):
        row = con.execute(
            "SELECT from_value,to_value,break_date FROM sim_book_breaks "
            "WHERE portfolio_id=? AND kind=? ORDER BY break_date DESC LIMIT 1",
            [portfolio_id, COST_PROFILE_BREAK],
        ).fetchone()
        if row is not None:
            return str(row[1] if session_date >= row[2] else row[0])
    return str(portfolio_account(con, portfolio_id)["cost_profile"])


def evaluation_start(
    con: duckdb.DuckDBPyConnection,
    portfolio_ids: str | Iterable[str],
    inception: date,
) -> date:
    """Return the common post-break clock start for one book or a comparison."""
    ids = [portfolio_ids] if isinstance(portfolio_ids, str) else list(portfolio_ids)
    starts = [inception]
    starts.extend(
        value for value in (latest_break(con, portfolio_id) for portfolio_id in ids)
        if value is not None
    )
    return max(starts)


def fees_paid(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    *,
    since: date | None = None,
    through: date | None = None,
) -> float:
    """Sum dollar fill fees for a book inside an optional closed date range."""
    if not all(table_exists(con, table) for table in ("sim_fills", "sim_fill_fees")):
        return 0.0
    predicates, parameters = ["f.portfolio_id=?"], [portfolio_id]
    if since is not None:
        predicates.append("f.fill_date>=?")
        parameters.append(since)
    if through is not None:
        predicates.append("f.fill_date<=?")
        parameters.append(through)
    row = con.execute(
        "SELECT COALESCE(SUM(ff.total_usd),0) FROM sim_fills f "
        "JOIN sim_fill_fees ff ON ff.order_id=f.order_id WHERE "
        + " AND ".join(predicates),
        parameters,
    ).fetchone()
    return float(row[0])


def return_since_break(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    equity: float,
    through: date,
) -> float | None:
    """Return from the last pre-break equity mark through ``through``."""
    boundary = latest_break(con, portfolio_id)
    if boundary is None or through < boundary:
        return None
    row = con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id=? AND date<? "
        "ORDER BY date DESC LIMIT 1",
        [portfolio_id, boundary],
    ).fetchone()
    if row is None or row[0] is None or float(row[0]) <= 0:
        return None
    return float(equity) / float(row[0]) - 1.0
