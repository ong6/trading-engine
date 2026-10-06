"""Point-in-time daily and minute bar readers for account execution.

The account engine can settle from the operational ``prices`` and
``intraday_prices`` tables or from attached copies of the isolated Massive
stores.  Readers never invent a bar and apply an availability cutoff whenever
the source exposes one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import duckdb

from . import order_types

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DailyBar:
    ticker: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    source: str
    bar_ref: str


@dataclass(frozen=True)
class MinuteBar:
    ticker: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    source: str
    bar_ref: str


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            [table],
        ).fetchall()
    }


def _naive_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def session_bounds(session_date: date) -> tuple[datetime, datetime]:
    """UTC-naive regular-session bounds, including recurring early closes."""
    opened = datetime.combine(session_date, order_types.MARKET_OPEN, NEW_YORK)
    closed = order_types.session_close(session_date)
    return _naive_utc(opened), _naive_utc(closed)


def daily_bar(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    session_date: date,
    *,
    source: str = "prices",
    available_at: datetime | None = None,
) -> DailyBar | None:
    """Return one tradeable daily bar available by ``available_at``."""
    if source == "prices":
        table = "prices"
        names = ("open", "high", "low", "close", "volume", None)
    elif source == "massive_daily":
        # Execution must see the bar as captured, not today's split-restated
        # research view.  A later split must never rewrite an old fill input.
        table = "free_daily_bars"
        names = ("o", "h", "l", "c", "volume", "vwap")
    else:
        raise ValueError(f"unknown daily bar source {source!r}")
    columns = _columns(con, table)
    if not columns:
        return None
    open_col, high_col, low_col, close_col, volume_col, vwap_col = names
    if not {"ticker", "date", open_col, close_col, volume_col} <= columns:
        return None
    high_expr = high_col if high_col in columns else open_col
    low_expr = low_col if low_col in columns else close_col
    vwap_expr = vwap_col if vwap_col and vwap_col in columns else "NULL"
    where = "ticker=? AND date=?"
    params: list[object] = [ticker, session_date]
    if available_at is not None:
        stamp = "first_fetched_at" if "first_fetched_at" in columns else (
            "fetched_at" if "fetched_at" in columns else None
        )
        if stamp:
            where += f" AND {stamp} IS NOT NULL AND {stamp}<=?"
            params.append(_naive_utc(available_at))
    ordering = (
        "fetched_at DESC,source_sha256 DESC" if source == "massive_daily"
        else "date DESC"
    )
    row = con.execute(
        f"SELECT {open_col},{high_expr},{low_expr},{close_col},{volume_col},"
        f"{vwap_expr} FROM {table} WHERE {where} ORDER BY {ordering} LIMIT 1",
        params,
    ).fetchone()
    if row is None or any(row[index] is None for index in range(5)):
        return None
    values = [float(row[index]) for index in range(5)]
    if any(value <= 0 for value in values):
        return None
    return DailyBar(
        ticker=ticker,
        session_date=session_date,
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
        volume=values[4],
        vwap=None if row[5] is None else float(row[5]),
        source=source,
        bar_ref=f"{source}:{ticker}:{session_date.isoformat()}",
    )


def minute_bars(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    session_date: date,
    *,
    source: str = "intraday_prices",
    available_at: datetime | None = None,
) -> list[MinuteBar]:
    """Return ascending regular-session one-minute bars for one session."""
    if source == "intraday_prices":
        table, ts_col = "intraday_prices", "ts"
        names = ("open", "high", "low", "close", "volume", None)
    elif source == "massive_minute":
        table, ts_col = "massive_minute_bars", "ts_utc"
        names = ("o", "h", "l", "c", "v", "vw")
    else:
        raise ValueError(f"unknown minute bar source {source!r}")
    columns = _columns(con, table)
    if not columns:
        return []
    open_col, high_col, low_col, close_col, volume_col, vwap_col = names
    required = {"ticker", ts_col, open_col, high_col, low_col, close_col, volume_col}
    if not required <= columns:
        return []
    opened, closed = session_bounds(session_date)
    where = f"ticker=? AND {ts_col}>=? AND {ts_col}<?"
    params: list[object] = [ticker, opened, closed]
    if source == "intraday_prices" and "interval" in columns:
        where += " AND interval='1m'"
    if available_at is not None:
        if "fetched_at" in columns:
            where += " AND fetched_at IS NOT NULL AND fetched_at<=?"
            params.append(_naive_utc(available_at))
        elif "as_of" in columns:
            where += " AND as_of IS NOT NULL AND as_of<=?"
            params.append(available_at.date())
    vwap_expr = vwap_col if vwap_col and vwap_col in columns else "NULL"
    rows = con.execute(
        f"SELECT {ts_col},{open_col},{high_col},{low_col},{close_col},"
        f"{volume_col},{vwap_expr} FROM {table} WHERE {where} ORDER BY {ts_col}",
        params,
    ).fetchall()
    out: list[MinuteBar] = []
    for row in rows:
        if any(row[index] is None for index in range(1, 6)):
            continue
        values = [float(row[index]) for index in range(1, 6)]
        if any(value <= 0 for value in values):
            continue
        stamp = _naive_utc(row[0])
        out.append(MinuteBar(
            ticker=ticker,
            ts=stamp,
            open=values[0],
            high=values[1],
            low=values[2],
            close=values[3],
            volume=values[4],
            vwap=None if row[6] is None else float(row[6]),
            source=source,
            bar_ref=f"{source}:{ticker}:{stamp.isoformat()}",
        ))
    return out


def minute_session_complete(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    session_date: date,
    *,
    source: str = "intraday_prices",
    available_at: datetime | None = None,
) -> bool:
    """Whether captured bars reach the final minute of the session."""
    _opened, closed = session_bounds(session_date)
    bars = minute_bars(
        con, ticker, session_date, source=source, available_at=available_at,
    )
    return bool(bars and bars[-1].ts >= closed - timedelta(minutes=1))


def latest_close(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    on_or_before: date,
    *,
    source: str = "prices",
    available_at: datetime | None = None,
    strictly_before: bool = False,
) -> float | None:
    """Latest unadjusted close admitted by date and availability time."""
    if source == "prices":
        table, close_col = "prices", "close"
    elif source == "massive_daily":
        table, close_col = "free_daily_bars", "c"
    else:
        raise ValueError(f"unknown daily bar source {source!r}")
    columns = _columns(con, table)
    if not columns:
        return None
    operator = "<" if strictly_before else "<="
    where = f"ticker=? AND date{operator}?"
    params: list[object] = [ticker, on_or_before]
    stamp = "first_fetched_at" if "first_fetched_at" in columns else (
        "fetched_at" if "fetched_at" in columns else None
    )
    if available_at is not None and stamp:
        where += f" AND {stamp} IS NOT NULL AND {stamp}<=?"
        params.append(_naive_utc(available_at))
    order = "date DESC"
    if source == "massive_daily":
        order += ",fetched_at DESC,source_sha256 DESC"
    row = con.execute(
        f"SELECT {close_col} FROM {table} WHERE {where} ORDER BY {order} LIMIT 1",
        params,
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def median_dollar_volume(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    as_of: date,
    *,
    source: str = "prices",
    bars: int = 60,
    available_at: datetime | None = None,
) -> float | None:
    """Median close×volume over bars strictly before ``as_of``."""
    if source == "prices":
        table, close_col = "prices", "close"
    elif source == "massive_daily":
        table, close_col = "free_daily_bars", "c"
    else:
        raise ValueError(f"unknown daily bar source {source!r}")
    columns = _columns(con, table)
    if not columns:
        return None
    where = "ticker=? AND date<?"
    params: list[object] = [ticker, as_of]
    if available_at is not None:
        stamp = "first_fetched_at" if "first_fetched_at" in columns else (
            "fetched_at" if "fetched_at" in columns else None
        )
        if stamp:
            where += f" AND {stamp} IS NOT NULL AND {stamp}<=?"
            params.append(_naive_utc(available_at))
    params.append(bars)
    canonical = (
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY fetched_at DESC,"
        "source_sha256 DESC)=1 " if source == "massive_daily" else ""
    )
    row = con.execute(
        f"SELECT MEDIAN({close_col}*volume) FROM ("
        f"SELECT {close_col},volume,date FROM {table} WHERE {where} {canonical}"
        "ORDER BY date DESC LIMIT ?)",
        params,
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])
