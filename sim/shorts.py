"""Stock locates, borrow accrual and deterministic Reg SHO buy-ins."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    day: date,
    source: str,
    available_at: datetime | None = None,
) -> float | None:
    return bar_sources.latest_close(
        con, ticker, day, source=source, available_at=available_at,
        strictly_before=True,
    )


def short_data_available(con_short: duckdb.DuckDBPyConnection | None) -> bool:
    """Both point-in-time locate inputs must be attached and readable."""
    return bool(
        con_short is not None
        and table_exists(con_short, "regsho_threshold")
        and table_exists(con_short, "finra_short_interest")
    )


def _liquid_as_of(
    con: duckdb.DuckDBPyConnection, ticker: str, day: date,
) -> bool:
    """Use a dated liquid flag when present, else the current-universe fallback."""
    snapshot_columns = _columns(con, "universe_snapshot")
    if {"snapshot_date", "ticker", "liquid"} <= snapshot_columns:
        row = con.execute(
            "SELECT liquid FROM universe_snapshot WHERE ticker=? AND snapshot_date<=? "
            "ORDER BY snapshot_date DESC LIMIT 1",
            [ticker, day],
        ).fetchone()
        if row is not None:
            return bool(row[0])
    # Legacy stores have no dated liquidity history. Their current flag is an
    # explicit compatibility limitation, never a substitute when a snapshot exists.
    if table_exists(con, "universe") and "liquid" in _columns(con, "universe"):
        row = con.execute(
            "SELECT liquid FROM universe WHERE ticker=?", [ticker]
        ).fetchone()
        return bool(row and row[0])
    return False


def locate(
    con_short: duckdb.DuckDBPyConnection,
    ticker: str,
    day: date,
    *,
    market_con: duckdb.DuckDBPyConnection | None = None,
    price_source: str = "prices",
    available_at: datetime | None = None,
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
    close = _prior_close(
        market, ticker, day, price_source, available_at=available_at,
    )
    mdv = bar_sources.median_dollar_volume(
        market, ticker, day, source=price_source, available_at=available_at,
    )
    liquid = _liquid_as_of(market, ticker, day)
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
    portfolio_id: str | None = None,
) -> dict:
    """Debit borrow cost once per held account short and session."""
    default_span = _calendar_days_since_previous_session(day)
    charged = 0.0
    count = 0
    rows = []
    settings_rows = [
        settings for settings in account_portfolios(con, active_only=False)
        if settings["status"] in {"active", "halted"}
        and (portfolio_id is None or settings["portfolio_id"] == portfolio_id)
    ]
    for settings in settings_rows:
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
        if days is not None:
            portions = [(abs(float(qty)), days)]
        else:
            last = con.execute(
                "SELECT MAX(event_date) FROM sim_cash_events WHERE portfolio_id=? "
                "AND instrument_id=? AND kind='borrow_fee' AND event_date<?",
                [portfolio_id, ticker, day],
            ).fetchone()[0]
            prior = day - timedelta(days=default_span)
            start_floor = last or prior
            portions = []
            covered = 0.0
            for lot_qty, opened in con.execute(
                "SELECT ABS(qty),opened_session FROM sim_position_lots "
                "WHERE portfolio_id=? AND instrument_id=? AND qty<0",
                [portfolio_id, ticker],
            ).fetchall():
                span = max((day - max(start_floor, opened)).days, 0)
                portions.append((float(lot_qty), span))
                covered += float(lot_qty)
            if covered + 1e-12 < abs(float(qty)):
                portions.append((abs(float(qty)) - covered, default_span))
        fee = sum(
            costs.borrow_fee(
                portion_qty * close, span, session_date=day,
                profile=settings["cost_profile"],
            )
            for portion_qty, span in portions
            if span > 0
        )
        if fee <= 0:
            continue
        charged_days = max((span for _qty, span in portions), default=0)
        ledger.apply_cash_event(con, {
            "portfolio_id": portfolio_id,
            "event_date": day,
            "kind": "borrow_fee",
            "amount": -fee,
            "instrument_id": ticker,
            "note": f"up to {charged_days} calendar day(s)",
        })
        charged += fee
        count += 1
    return {"events": count, "charged": charged}


def queue_buy_ins(
    con: duckdb.DuckDBPyConnection,
    con_short: duckdb.DuckDBPyConnection,
    day: date,
    *,
    portfolio_id: str | None = None,
) -> list[int]:
    """Queue next-open covers for five-session threshold-list shorts."""
    queued: list[int] = []
    positions = []
    for settings in account_portfolios(con, active_only=False):
        if settings["status"] not in {"active", "halted", "retiring"}:
            continue
        if portfolio_id is not None and settings["portfolio_id"] != portfolio_id:
            continue
        for ticker, qty in con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<0 "
            "ORDER BY ticker",
            [settings["portfolio_id"]],
        ).fetchall():
            positions.append((settings["portfolio_id"], ticker, qty))
    _opened, received = bar_sources.session_bounds(day)
    for portfolio_id, ticker, qty in positions:
        if not threshold_streak(con_short, ticker, day):
            continue
        duplicate = con.execute(
            "SELECT 1 FROM sim_orders o JOIN sim_order_details d ON d.order_id=o.id "
            "WHERE o.portfolio_id=? AND o.ticker=? AND o.side='cover' "
            "AND o.status='pending' AND d.state_reason LIKE 'buy_in%'",
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
