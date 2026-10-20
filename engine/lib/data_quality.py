"""Research data-quality labels and deterministic store fingerprints."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal

from engine.lib.util import table_exists

FIXED_ETF_HISTORY = "fixed_etf_history"
CURRENT_UNIVERSE_SURVIVOR_BIASED = "current_universe_survivor_biased"
STATIC_FUNDAMENTAL_LOOKAHEAD = "static_fundamental_lookahead"

PRICE_VALIDATOR_VERSION = "price-admission-v15.1"
OHLC = ("open", "high", "low", "close")
COMMON_SPLIT_FACTORS = (1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 50, 100, 200, 500, 1000)


@lru_cache(maxsize=128)
def session_schedule(year: int) -> pd.DataFrame:
    """Historical NYSE sessions, including early closes and exceptional closures."""
    return mcal.get_calendar("NYSE").schedule(
        start_date=f"{year}-01-01", end_date=f"{year}-12-31",
    )


def price_bar_reasons(bar, *, check_volume: bool = True) -> list[str]:
    """Scalar invariants only: unusual returns and flat trades are valid."""
    reasons = []
    values = {}
    for field in OHLC:
        value = bar.get(field)
        if value is None or value is pd.NA:
            reasons.append(f"{field}_null")
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            reasons.append(f"{field}_nonfinite")
            continue
        if not math.isfinite(number):
            reasons.append(f"{field}_nonfinite")
        elif number <= 0:
            reasons.append(f"{field}_nonpositive")
        else:
            values[field] = number
    if len(values) == 4:
        if values["high"] < max(values["open"], values["close"], values["low"]):
            reasons.append("high_geometry")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            reasons.append("low_geometry")
    if check_volume:
        try:
            volume = bar.get("volume")
            # Preserve integral BIGINT values without converting them through float.
            integer = int(volume)
            if integer < 0:
                reasons.append("volume_negative")
            elif integer > 2**63 - 1 or integer != volume:
                reasons.append("volume_unrepresentable")
        except (TypeError, ValueError, OverflowError):
            reasons.append("volume_unrepresentable")
    return reasons


def observation_reasons(bar, *, intraday: bool = False) -> list[str]:
    reasons = price_bar_reasons(bar)
    ticker = bar.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip() or ticker != ticker.strip().upper():
        reasons.append("invalid_ticker")
    try:
        if intraday:
            ts = pd.Timestamp(bar.get("ts"))
            if pd.isna(ts):
                raise ValueError("missing timestamp")
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            day = ts.tz_convert("America/New_York").date()
        else:
            ts = pd.Timestamp(bar.get("date"))
            if pd.isna(ts) or ts.time() != datetime.min.time():
                raise ValueError("not a daily date")
            day = ts.date()
        schedule = session_schedule(day.year)
        key = pd.Timestamp(day)
        if key not in schedule.index:
            reasons.append("off_calendar")
        elif intraday:
            row = schedule.loc[key]
            interval = bar.get("interval")
            if interval not in ("1m", "5m"):
                reasons.append("invalid_interval")
            elif not row.market_open <= ts < row.market_close:
                reasons.append("off_calendar")
            elif (ts - row.market_open).total_seconds() % (60 if interval == "1m" else 300):
                reasons.append("invalid_interval")
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_date")
    return reasons


def split_like_factor(ratio: float) -> float | None:
    """Match the registered ±8% log band without applying any adjustment."""
    if ratio <= 0 or not math.isfinite(ratio):
        return None
    return next((factor for factor in (*COMMON_SPLIT_FACTORS,
                                       *(1 / f for f in COMMON_SPLIT_FACTORS))
                 if abs(math.log(ratio / factor)) <= math.log(1.08)), None)

def price_bar_sql(open_col="open", high_col="high", low_col="low",
                  close_col="close", volume_col="volume") -> str:
    """SQL counterpart of scalar admission; zero-volume observations are valid."""
    o, h, lo, c, v = open_col, high_col, low_col, close_col, volume_col
    finite = " AND ".join(f"isfinite({col}) AND {col}>0" for col in (o, h, lo, c))
    return (f"({finite} AND isfinite({v}) AND {v}>=0 AND {v}=trunc({v}) "
            f"AND {v}<=9223372036854775807 AND {h}>={o} AND {h}>={c} "
            f"AND {h}>={lo} AND {lo}<={o} AND {lo}<={c})")


def trusted_bar_sql(open_col="open", high_col="high", low_col="low",
                    close_col="close", volume_col="volume") -> str:
    """Admission geometry plus the money path's existing traded-volume gate."""
    scalar = price_bar_sql(open_col, high_col, low_col, close_col, volume_col)
    return f"({scalar} AND {volume_col}>0)"


def trusted_bar(values) -> bool:
    """Use admission's scalar rule before requiring a traded money observation."""
    if values is None or len(values) != 5:
        return False
    bar = dict(zip((*OHLC, "volume"), values, strict=True))
    return not price_bar_reasons(bar) and bar["volume"] > 0


FIXED_ETF_STRATEGIES = frozenset({
    "spy_benchmark", "dual_momentum", "dual_momentum_gated",
    "sector_momentum", "multi_asset_trend", "sleeve_alloc",
})
STATIC_FUNDAMENTAL_STRATEGIES = frozenset({"low_vol", "ew_sector_capped"})


def quality_class(strategy: str) -> str:
    if strategy in STATIC_FUNDAMENTAL_STRATEGIES:
        return STATIC_FUNDAMENTAL_LOOKAHEAD
    if strategy in FIXED_ETF_STRATEGIES:
        return FIXED_ETF_HISTORY
    return CURRENT_UNIVERSE_SURVIVOR_BIASED


def quarantine_reason(con, ticker: str) -> str | None:
    """Reason for an explicitly active primary-data quarantine, if any."""
    if not table_exists(con, "price_quarantine"):
        return None
    row = con.execute(
        "SELECT reason FROM price_quarantine WHERE ticker = ? AND status = 'active'",
        [ticker.upper()],
    ).fetchone()
    return None if row is None else str(row[0])


def active_quarantines(con) -> list[dict]:
    if not table_exists(con, "price_quarantine"):
        return []
    return [
        {"ticker": tk, "reason": reason, "evidence": evidence,
         "confirmed_at": _json_value(confirmed)}
        for tk, reason, evidence, confirmed in con.execute(
            "SELECT ticker, reason, evidence, confirmed_at FROM price_quarantine "
            "WHERE status = 'active' ORDER BY ticker"
        ).fetchall()
    ]


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _table_summary(con, table: str, date_col: str,
                   watermark_col: str | None = None) -> dict:
    if not table_exists(con, table):
        return {"exists": False, "rows": 0, "min_date": None,
                "max_date": None, "latest_fetch": None}
    watermark = (
        f", MAX({watermark_col})" if watermark_col else ", NULL"
    )
    row = con.execute(
        f"SELECT COUNT(*), MIN({date_col}), MAX({date_col}){watermark} FROM {table}"
    ).fetchone()
    return {
        "exists": True,
        "rows": int(row[0]),
        "min_date": _json_value(row[1]),
        "max_date": _json_value(row[2]),
        "latest_fetch": _json_value(row[3]),
    }


def data_snapshot(con) -> dict:
    """Small deterministic identity for research-relevant source tables."""
    tables = {
        "prices": _table_summary(con, "prices", "date", "fetched_at"),
        "corporate_actions": _table_summary(
            con, "corporate_actions", "ex_date", "fetched_at"),
        "universe_snapshot": _table_summary(
            con, "universe_snapshot", "snapshot_date"),
        "fundamentals": _table_summary(con, "fundamentals", "as_of", "fetched_at"),
    }
    quarantines = active_quarantines(con)
    tables["price_quarantine"] = {
        "active_count": len(quarantines),
        "active_tickers": [q["ticker"] for q in quarantines],
    }
    payload = json.dumps(tables, sort_keys=True, separators=(",", ":"))
    return {"sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "tables": tables}
