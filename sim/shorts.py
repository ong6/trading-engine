"""Stock locates, borrow accrual and deterministic Reg SHO buy-ins."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import duckdb

from engine.accounts import account_portfolios
from engine.lib.util import table_exists

from . import bar_sources, costs, ledger, nyse
from .schema import next_order_id

ETB_ANNUAL_RATE = 0.0025
MIN_SHORT_PRICE = 5.0
MIN_SHORT_MDV = 5_000_000.0
STALE_AFTER_SESSIONS = 10
BUY_IN_THRESHOLD_SESSIONS = 5
BUY_IN_PENALTY_BPS = 50.0


@dataclass(frozen=True)
class LocateResult:
    available: bool
    classification: str
    reason: str | None
    annual_rate: float | None
    data_stale: bool = False


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            [table],
        ).fetchall()
    }


def _session_days(start: date, end: date) -> int:
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if nyse.is_session(cursor):
            days += 1
    return days


def _previous_sessions(day: date, count: int) -> list[date]:
    out: list[date] = []
    cursor = day
    while len(out) < count:
        if nyse.is_session(cursor):
            out.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(out)


def _event_date_column(columns: set[str]) -> str:
    for candidate in ("session_date", "trade_date", "settlement_date", "date", "as_of"):
        if candidate in columns:
            return candidate
    return "publication_date"


def _published_through(con: duckdb.DuckDBPyConnection, table: str, day: date) -> date | None:
    columns = _columns(con, table)
    if not columns or "publication_date" not in columns:
        return None
    row = con.execute(
        f"SELECT MAX(publication_date) FROM {table} WHERE publication_date<=?",
        [day],
    ).fetchone()
    return row[0] if row else None


def _threshold_dates(
    con: duckdb.DuckDBPyConnection, ticker: str, day: date,
) -> set[date]:
    table = "regsho_threshold"
    columns = _columns(con, table)
    if not columns or not {"ticker", "publication_date"} <= columns:
        return set()
    event_col = _event_date_column(columns)
    return {
        row[0]
        for row in con.execute(
            f"SELECT DISTINCT {event_col} FROM {table} "
            f"WHERE ticker=? AND {event_col}<=? AND publication_date<=?",
            [ticker, day, day],
        ).fetchall()
        if row[0] is not None
    }


def _latest_days_to_cover(
    con: duckdb.DuckDBPyConnection, ticker: str, day: date,
) -> float | None:
    table = "finra_short_interest"
    columns = _columns(con, table)
    if not columns or not {"ticker", "publication_date", "days_to_cover"} <= columns:
        return None
    row = con.execute(
        f"SELECT days_to_cover FROM {table} WHERE ticker=? AND publication_date<=? "
        f"ORDER BY publication_date DESC,{_event_date_column(columns)} DESC LIMIT 1",
        [ticker, day],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def _prior_close(
    con: duckdb.DuckDBPyConnection, ticker: str, day: date, source: str,
) -> float | None:
    if source == "prices":
        table, close_col = "prices", "close"
    elif source == "massive_daily":
        table, close_col = "free_daily_bars_adjusted", "c"
    else:
        raise ValueError(f"unknown price source {source!r}")
    if not _columns(con, table):
        return None
    row = con.execute(
        f"SELECT {close_col} FROM {table} WHERE ticker=? AND date<? "
        "ORDER BY date DESC LIMIT 1",
        [ticker, day],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def locate(
    con_short: duckdb.DuckDBPyConnection,
    ticker: str,
    day: date,
    *,
    market_con: duckdb.DuckDBPyConnection | None = None,
    price_source: str = "prices",
) -> LocateResult:
    """Classify a point-in-time stock locate as ETB or HTB/no-locate."""
    market = market_con or con_short
    newest = max(
        (
            value
            for value in (
                _published_through(con_short, "regsho_threshold", day),
                _published_through(con_short, "finra_short_interest", day),
            )
            if value is not None
        ),
        default=None,
    )
    stale = newest is None or _session_days(newest, day) > STALE_AFTER_SESSIONS
    close = _prior_close(market, ticker, day, price_source)
    mdv = bar_sources.median_dollar_volume(
        market, ticker, day, source=price_source,
    )
    liquid = False
    if table_exists(market, "universe") and "liquid" in _columns(market, "universe"):
        row = market.execute(
            "SELECT liquid FROM universe WHERE ticker=?", [ticker]
        ).fetchone()
        liquid = bool(row and row[0])
    conservative_reason = (
        "price_below_5" if close is None or close < MIN_SHORT_PRICE
        else "mdv_below_5m" if mdv is None or mdv < MIN_SHORT_MDV
        else "not_liquid" if not liquid
        else None
    )
    if conservative_reason:
        return LocateResult(False, "HTB", conservative_reason, None, stale)
    if not stale:
        recent = set(_previous_sessions(day, 5))
        if _threshold_dates(con_short, ticker, day) & recent:
            return LocateResult(False, "HTB", "regsho_threshold", None)
        days_to_cover = _latest_days_to_cover(con_short, ticker, day)
        if days_to_cover is not None and days_to_cover >= 10:
            return LocateResult(False, "HTB", "days_to_cover", None)
    return LocateResult(True, "ETB", None, ETB_ANNUAL_RATE, stale)


def threshold_streak(
    con_short: duckdb.DuckDBPyConnection, ticker: str, day: date,
    sessions: int = BUY_IN_THRESHOLD_SESSIONS,
) -> bool:
    """Whether the name appears for every one of the latest sessions."""
    required = set(_previous_sessions(day, sessions))
    return required <= _threshold_dates(con_short, ticker, day)


def _calendar_days_since_previous_session(day: date) -> int:
    cursor = day - timedelta(days=1)
    while not nyse.is_session(cursor):
        cursor -= timedelta(days=1)
    return (day - cursor).days


def accrue_borrow(
    con: duckdb.DuckDBPyConnection,
    day: date,
    *,
    days: int | None = None,
) -> dict:
    """Debit borrow cost once per held account short and session."""
    span = _calendar_days_since_previous_session(day) if days is None else days
    charged = 0.0
    count = 0
    rows = []
    for settings in account_portfolios(con):
        for ticker, qty in con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<0 "
            "ORDER BY ticker",
            [settings["portfolio_id"]],
        ).fetchall():
            rows.append((settings, ticker, qty))
    for settings, ticker, qty in rows:
        portfolio_id = settings["portfolio_id"]
        exists = con.execute(
            "SELECT 1 FROM sim_cash_events WHERE portfolio_id=? AND event_date=? "
            "AND kind='borrow_fee' AND instrument_id=?",
            [portfolio_id, day, ticker],
        ).fetchone()
        if exists:
            continue
        close = _prior_close(
            con, ticker, nyse.next_session(day), settings["price_source"],
        )
        if close is None:
            continue
        fee = costs.borrow_fee(
            abs(float(qty)) * close, span, session_date=day,
            profile=settings["cost_profile"],
        )
        ledger.apply_cash_event(con, {
            "portfolio_id": portfolio_id,
            "event_date": day,
            "kind": "borrow_fee",
            "amount": -fee,
            "instrument_id": ticker,
            "note": f"{span} calendar day(s)",
        })
        charged += fee
        count += 1
    return {"events": count, "charged": charged}


def queue_buy_ins(
    con: duckdb.DuckDBPyConnection,
    con_short: duckdb.DuckDBPyConnection,
    day: date,
) -> list[int]:
    """Queue next-open covers for five-session threshold-list shorts."""
    queued: list[int] = []
    positions = []
    for settings in account_portfolios(con):
        for ticker, qty in con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<0 "
            "ORDER BY ticker",
            [settings["portfolio_id"]],
        ).fetchall():
            positions.append((settings["portfolio_id"], ticker, qty))
    received = datetime.combine(day, time(20), timezone.utc).replace(tzinfo=None)
    for portfolio_id, ticker, qty in positions:
        if not threshold_streak(con_short, ticker, day):
            continue
        duplicate = con.execute(
            "SELECT 1 FROM sim_orders o JOIN sim_order_details d ON d.order_id=o.id "
            "WHERE o.portfolio_id=? AND o.ticker=? AND o.side='cover' "
            "AND o.status='pending' AND d.state_reason='buy_in'",
            [portfolio_id, ticker],
        ).fetchone()
        if duplicate:
            continue
        order_id = next_order_id(con)
        con.execute(
            "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
            [order_id, portfolio_id, ticker, "cover", abs(float(qty)), day],
        )
        con.execute(
            "INSERT INTO sim_order_details "
            "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
            "received_at,state,state_reason,state_at) "
            "VALUES (?,?,?,'next_open','cover','day',?,?,'queued','buy_in',?)",
            [order_id, ticker, "stock", day, received, received],
        )
        queued.append(order_id)
    return queued
