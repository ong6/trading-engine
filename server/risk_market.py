"""Market and event evidence used by discretionary ticket risk gates."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import numpy as np

from engine.lib.db import REAL_BAR_SQL
from engine.lib.util import table_exists

from . import risk_book

EARNINGS_WINDOW_DAYS = 7


def _gate(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def spy_regime_for_date(
    con: duckdb.DuckDBPyConnection, market_date: date | None
) -> tuple[str, str]:
    """Return SPY's regime at an already resolved operational market date."""
    rows = con.execute(
        f"SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? AND {REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 200",
        [market_date],
    ).fetchall()
    if len(rows) < 200:
        return "unknown", f"SPY has {len(rows)} bars (<200) — regime unknown"
    closes = np.array([row[0] for row in rows], dtype=float)
    moving_average = float(closes.mean())
    latest = float(closes[0])
    label = "risk-off" if latest < moving_average else "risk-on"
    return label, f"SPY {latest:.2f} vs 200d SMA {moving_average:.2f} → {label}"


def spy_regime(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """Return SPY's 200-session regime label and its human-readable evidence."""
    return spy_regime_for_date(con, risk_book.latest_prices_date(con))


def _earnings_rows(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    today: date,
) -> list[tuple] | None:
    try:
        if not table_exists(con, "earnings_calendar"):
            return None
        return con.execute(
            "SELECT earnings_date, is_estimate FROM earnings_calendar "
            "WHERE ticker = ? AND as_of = "
            "(SELECT MAX(as_of) FROM earnings_calendar WHERE ticker = ? AND as_of <= ?)",
            [ticker, ticker, today],
        ).fetchall()
    except duckdb.Error:
        return None


def earnings_window(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    acked: bool,
    *,
    now: datetime | None = None,
) -> dict:
    """Evaluate the latest point-in-time earnings snapshot for one ticker."""
    ack_suffix = " (acknowledged)" if acked else ""
    unknown = _gate(
        "earnings_window",
        "unknown",
        "no earnings data — check manually" + ack_suffix,
    )
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    rows = _earnings_rows(con, ticker, today)
    if not rows:
        return unknown
    horizon = today + timedelta(days=EARNINGS_WINDOW_DAYS)
    upcoming = [
        (day, estimate) for day, estimate in rows if day is not None and today <= day <= horizon
    ]
    if not upcoming:
        return _gate("earnings_window", "pass", f"no earnings within {EARNINGS_WINDOW_DAYS}d")
    earnings_date, is_estimate = min(upcoming, key=lambda item: item[0])
    kind = "estimate" if is_estimate else "confirmed"
    return _gate(
        "earnings_window",
        "fail",
        f"earnings {earnings_date} ({kind}) within {EARNINGS_WINDOW_DAYS}d window",
    )
