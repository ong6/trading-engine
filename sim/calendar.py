"""Trading-calendar helpers derived entirely from the `prices` table.

The set of trading days is public exchange-calendar knowledge (not look-ahead
into price *values*), so cadence and fill-timing may consult which dates are
trading sessions. Signal *computations* still only read price data with
date <= as_of_date; the no-same-bar-fill rule (fill_date > signal_date) lives in
fills.py and is the real look-ahead guard.
"""
from __future__ import annotations

from datetime import date

import duckdb


def next_trading_day(con: duckdb.DuckDBPyConnection, d: date) -> date | None:
    """First trading session strictly after d, or None if d is the latest."""
    row = con.execute(
        "SELECT MIN(date) FROM prices WHERE date > ?", [d]
    ).fetchone()
    return row[0] if row else None


def trading_days_between(con: duckdb.DuckDBPyConnection, a: date, b: date) -> int:
    """Count of trading sessions in (a, b] — i.e. how many sessions b is after a.

    COUNT(DISTINCT date), not COUNT(*): `prices` holds one row per (ticker, date),
    so a plain row count returns the number of price rows in the window (thousands
    per session) rather than the number of sessions.
    """
    return con.execute(
        "SELECT COUNT(DISTINCT date) FROM prices WHERE date > ? AND date <= ?", [a, b]
    ).fetchone()[0]


def is_week_signal(con: duckdb.DuckDBPyConnection, d: date) -> bool:
    """True if d is the last trading session of its ISO week.

    Determined from the exchange calendar: the next trading session after d
    falls in a later ISO (year, week). If there is no next session in the DB
    (d is the latest bar) we cannot yet know the week has closed, so fall back
    to a Friday check — an honest, reproducible rule with no future price peek.
    """
    nxt = next_trading_day(con, d)
    if nxt is None:
        return d.weekday() == 4  # Friday
    return d.isocalendar()[:2] != nxt.isocalendar()[:2]


def is_month_signal(con: duckdb.DuckDBPyConnection, d: date) -> bool:
    """True if d is the last trading session of its calendar month."""
    from datetime import timedelta

    nxt = next_trading_day(con, d)
    if nxt is None:
        # Latest bar: signal only if the next calendar day rolls the month.
        return (d + timedelta(days=1)).month != d.month
    return (d.year, d.month) != (nxt.year, nxt.month)
