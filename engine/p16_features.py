"""Decision-time P16 factor inputs; no labels, fetching, or database writes.

Callers retain this snapshot with the decision and evaluate those retained bytes.
Recomputing it later is not a substitute for the original decision-time inputs.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.p15_event_sources import session_close
from sim import nyse

EXPOSURES = (
    "momentum_12_1", "return_21", "return_1", "log_adv20", "beta60", "vol60",
)
LOOKBACK_SESSIONS = 252
RISK_SESSIONS = 60
VOLUME_SESSIONS = 20


def session_dates(through: date, count: int) -> list[date]:
    """Exactly count exchange dates, oldest first; never count observed rows."""
    if not nyse.is_session(through) or count < 1:
        raise ValueError("factor history requires a session and a positive count")
    dates, current = [], through
    while len(dates) < count:
        if nyse.is_session(current):
            dates.append(current)
        current -= timedelta(days=1)
    return dates[::-1]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("factor cutoff must have an explicit timezone")
    return value.astimezone(timezone.utc)


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        math.isfinite(float(value)) and value > 0
    )


def _factor_values(bars: dict, spy: dict, dates: list[date]) -> dict:
    values = dict.fromkeys(EXPOSURES)
    for field, end, start in (("return_21", -1, -22), ("return_1", -1, -2)):
        if dates[end] in bars and dates[start] in bars:
            values[field] = bars[dates[end]][0] / bars[dates[start]][0] - 1
    if all(day in bars for day in dates):
        values["momentum_12_1"] = bars[dates[-22]][0] / bars[dates[0]][0] - 1
    volume_dates = dates[-VOLUME_SESSIONS - 1:-1]
    if all(day in bars for day in volume_dates):
        values["log_adv20"] = math.log(float(np.median([
            bars[day][0] * bars[day][1] for day in volume_dates
        ])))
    risk_dates = dates[-RISK_SESSIONS - 1:]
    if all(day in bars for day in risk_dates):
        closes = np.array([bars[day][0] for day in risk_dates])
        returns = closes[1:] / closes[:-1] - 1
        values["vol60"] = float(np.std(returns, ddof=1))
        if all(day in spy for day in risk_dates):
            benchmark = np.array([spy[day][0] for day in risk_dates])
            benchmark = benchmark[1:] / benchmark[:-1] - 1
            centered = benchmark - benchmark.mean()
            denominator = float(centered @ centered)
            if denominator > 1e-16:
                values["beta60"] = float((returns - returns.mean()) @ centered / denominator)
    return values


def _sectors(con, names: list[str], market_date: date, cutoff: datetime) -> dict:
    if not names or not table_exists(con, "fundamentals"):
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        "SELECT ticker,as_of,fetched_at,sector,source FROM fundamentals "
        f"WHERE ticker IN ({placeholders}) AND as_of<=? AND fetched_at IS NOT NULL "
        "AND fetched_at<=? QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker "
        "ORDER BY as_of DESC,fetched_at DESC)=1",
        [*names, market_date, cutoff.replace(tzinfo=None)],
    ).fetchall()
    return {ticker: {
        "sector": sector.strip().lower() if isinstance(sector, str) and sector.strip() else "unknown",
        "as_of": as_of.isoformat(), "fetched_at": fetched.isoformat(), "source": source,
    } for ticker, as_of, fetched, sector, source in rows}


def exposure_snapshot(
    con, tickers: list[str], market_date: date, *, information_cutoff_at: datetime,
) -> dict:
    """Retain cutoff-bounded split-adjusted bars and PIT sectors for each name."""
    cutoff = _utc(information_cutoff_at)
    if market_date > cutoff.date():
        raise ValueError("factor market date is after the information cutoff")
    if any(not isinstance(ticker, str) or not ticker.strip() for ticker in tickers):
        raise ValueError("invalid factor ticker")
    names = sorted(set(tickers))
    dates = session_dates(market_date, LOOKBACK_SESSIONS + 1)
    closed_at = datetime.combine(market_date, session_close(market_date),
                                 tzinfo=ZoneInfo("America/New_York"))
    if cutoff < closed_at:
        raise ValueError("factor market session has not closed")
    requested = sorted({*names, "SPY"})
    placeholders = ",".join("?" for _ in requested)
    rows = con.execute(
        "SELECT ticker,date,close,volume,open,high,low,source,fetched_at FROM prices "
        f"WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
        "ORDER BY ticker,date",
        [*requested, dates[0], market_date, cutoff.replace(tzinfo=None)],
    ).fetchall()
    admitted_dates = set(dates)
    history = {name: {} for name in requested}
    source_rows = {name: [] for name in requested}
    for ticker, day, close, volume, opening, high, low, source, fetched in rows:
        if day in admitted_dates and _positive(close) and _positive(volume):
            if day in history[ticker]:
                raise ValueError("ambiguous factor bar")
            history[ticker][day] = (float(close), int(volume))
            source_rows[ticker].append((day.isoformat(), opening, high, low, close,
                                        volume, source, fetched.isoformat()))
    sectors = _sectors(con, names, market_date, cutoff)
    candidates = []
    for ticker in names:
        bars = history[ticker]
        values = _factor_values(bars, history["SPY"], dates)
        missing = [name for name in EXPOSURES if values[name] is None]
        sector = sectors.get(ticker)
        candidates.append({
            "ticker": ticker, "status": "unavailable" if missing else "available",
            "missing_exposures": missing, "exposures": values,
            "sector": sector["sector"] if sector else "unknown",
            "sector_source": sector,
            "real_bar_count": len(bars),
        })
    body = {
        "schema_version": 2, "policy_id": "p16-eval-v2",
        "market_date": market_date.isoformat(), "information_cutoff_at": cutoff.isoformat(),
        "price_basis": "split_adjusted_price_v1",
        "corporate_action_state": "retained_at_information_cutoff",
        "exposure_names": list(EXPOSURES),
        "source_bars_sha256": canonical_sha256(source_rows),
        "sector_snapshot_sha256": canonical_sha256(sectors),
        "candidates": candidates,
    }
    return {**body, "snapshot_sha256": canonical_sha256(body)}
