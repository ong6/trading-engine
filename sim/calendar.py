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

from . import nyse


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
    (d is the latest bar — ALWAYS the case for the live league) the question is
    answered from the published NYSE holiday rules (`nyse.py`), which is public
    calendar knowledge and not a price peek. The old fallback (`weekday() == 4`)
    skipped every week whose last session was a Thursday (Good Friday,
    Christmas 2026, New Year 2027, …).
    """
    nxt = next_trading_day(con, d)
    if nxt is None:
        return nyse.is_last_session_of_week(d)
    return d.isocalendar()[:2] != nxt.isocalendar()[:2]


def is_month_signal(con: duckdb.DuckDBPyConnection, d: date) -> bool:
    """True if d is the last trading session of its calendar month.

    Latest-bar fallback uses the NYSE rule calendar (see is_week_signal). The old
    fallback fired only when the NEXT CALENDAR DAY rolled the month, so a month
    ending on a weekend (e.g. Oct 2026 → last session Fri 10-30) never produced a
    monthly signal for any monthly book: ~29% of month-ends were silently skipped.
    """
    nxt = next_trading_day(con, d)
    if nxt is None:
        return nyse.is_last_session_of_month(d)
    return (d.year, d.month) != (nxt.year, nxt.month)
