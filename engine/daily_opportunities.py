"""Deterministic daily standout detection for the P8 paper agent.

The detector reads only bars and snapshots dated on or before ``market_date``. It
does not call a model, fetch news, size orders, or mutate the database.
"""
from __future__ import annotations

import math
from datetime import date

import duckdb

from engine.lib.data_quality import active_quarantines
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

SCHEMA_VERSION = 1
MAX_CANDIDATES = 5
MIN_STANDOUT_SCORE = 2.0
MIN_HISTORY = 21
MIN_CLOSE = 3.0
MAX_ABS_DAILY_RETURN = 0.80
P15_MIN_MEDIAN_DOLLAR_VOLUME = 20_000_000.0
P15_MOVER_LIMIT = 40
P15_TREND_LIMIT = 20


class OpportunityError(ValueError):
    """The point-in-time opportunity input is incomplete or invalid."""


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpportunityError(f"{field} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise OpportunityError(f"{field} is invalid")
    return result


def _market_context(con: duckdb.DuckDBPyConnection, market_date: date) -> dict:
    rows = con.execute(
        "SELECT date, close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "AND close > 0 ORDER BY date DESC LIMIT 200",
        [market_date],
    ).fetchall()
    if not rows or rows[0][0] != market_date:
        raise OpportunityError("SPY market-date bar is unavailable")
    closes = [float(row[1]) for row in rows]
    daily_return = None if len(closes) < 2 else closes[0] / closes[1] - 1
    regime = "unknown"
    if len(closes) == 200:
        regime = "risk_on" if closes[0] > sum(closes) / len(closes) else "risk_off"
    body = {
        "market_date": market_date.isoformat(),
        "spy_close": closes[0],
        "spy_daily_return": daily_return,
        "regime": regime,
    }
    return {**body, "evidence_id": canonical_sha256(body)}


def _earnings(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    market_date: date,
    cutoff_at=None,
) -> dict:
    if not table_exists(con, "earnings_calendar"):
        return {"status": "unavailable", "next_date": None, "is_estimate": None}
    cutoff_clause = "" if cutoff_at is None else "AND (fetched_at IS NULL OR fetched_at<=?) "
    params = [ticker, market_date, market_date]
    if cutoff_at is not None:
        params.append(cutoff_at)
    query = (
        "SELECT earnings_date, is_estimate, as_of FROM earnings_calendar "
        "WHERE ticker = ? AND as_of <= ? AND earnings_date >= ? "
        + cutoff_clause
        + "QUALIFY as_of = MAX(as_of) OVER (PARTITION BY ticker) "
        "ORDER BY earnings_date LIMIT 1"
    )
    row = con.execute(query, params).fetchone()
    if row is None:
        return {"status": "no_upcoming_date", "next_date": None, "is_estimate": None}
    return {
        "status": "available",
        "next_date": row[0].isoformat(),
        "is_estimate": bool(row[1]),
        "snapshot_date": row[2].isoformat(),
    }


def _candidate_rows(con: duckdb.DuckDBPyConnection, market_date: date) -> list[tuple]:
    return con.execute(
        f"""
        WITH eligible AS (
          SELECT p.ticker, p.date, p.open, p.close, p.volume,
                 ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
          FROM prices p JOIN universe u ON u.ticker = p.ticker
          WHERE p.date <= ? AND u.active = TRUE AND u.liquid = TRUE AND u.etf = FALSE
            AND p.close >= ? AND {REAL_BAR_SQL}
        ), history AS (
          SELECT ticker,
                 MAX(date) FILTER (WHERE rn = 1) AS latest_date,
                 MAX(open) FILTER (WHERE rn = 1) AS open,
                 MAX(close) FILTER (WHERE rn = 1) AS close,
                 MAX(volume) FILTER (WHERE rn = 1) AS volume,
                 MAX(close) FILTER (WHERE rn = 2) AS prior_close,
                 MAX(close) FILTER (WHERE rn = 6) AS close_5d,
                 MEDIAN(volume) FILTER (WHERE rn BETWEEN 2 AND 21) AS median_volume,
                 COUNT(*) FILTER (WHERE rn <= 21) AS history_count
          FROM eligible WHERE rn <= 21 GROUP BY ticker
        )
        SELECT ticker, open, close, volume, prior_close, close_5d, median_volume
        FROM history WHERE latest_date = ? AND history_count >= ? AND prior_close > 0
          AND open > 0 AND close > 0 AND volume > 0 AND median_volume > 0
        """,
        [market_date, MIN_CLOSE, market_date, MIN_HISTORY],
    ).fetchall()


def _p15_candidate_rows(
    con: duckdb.DuckDBPyConnection, market_date: date, cutoff_at=None
) -> list[tuple]:
    cutoff_clause = "" if cutoff_at is None else "AND (p.fetched_at IS NULL OR p.fetched_at<=?)"
    params = [market_date, MIN_CLOSE]
    if cutoff_at is not None:
        params.append(cutoff_at)
    params.extend([market_date, MIN_HISTORY])
    return con.execute(
        f"""
        WITH eligible AS (
          SELECT p.ticker,p.date,p.open,p.close,p.volume,u.active,u.liquid,u.etf,
                 ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
          FROM prices p JOIN universe u ON u.ticker=p.ticker
          WHERE p.date<=? AND p.close>=? {cutoff_clause} AND {REAL_BAR_SQL}
        ), history AS (
          SELECT ticker,
                 MAX(date) FILTER (WHERE rn=1) AS latest_date,
                 MAX(open) FILTER (WHERE rn=1) AS open,
                 MAX(close) FILTER (WHERE rn=1) AS close,
                 MAX(volume) FILTER (WHERE rn=1) AS volume,
                 MAX(close) FILTER (WHERE rn=2) AS prior_close,
                 MAX(close) FILTER (WHERE rn=6) AS close_5d,
                 MEDIAN(volume) FILTER (WHERE rn BETWEEN 2 AND 21) AS median_volume,
                 MEDIAN(close*volume) FILTER (WHERE rn BETWEEN 2 AND 21)
                   AS median_dollar_volume,
                 MAX(active) AS active,MAX(liquid) AS liquid,MAX(etf) AS etf,
                 COUNT(*) FILTER (WHERE rn<=21) AS history_count
          FROM eligible WHERE rn<=21 GROUP BY ticker
        )
        SELECT ticker,open,close,volume,prior_close,close_5d,median_volume,
               median_dollar_volume,active,liquid,etf
        FROM history WHERE latest_date=? AND history_count>=? AND prior_close>0
          AND open>0 AND close>0 AND volume>0 AND median_volume>0
        """,
        params,
    ).fetchall()


def _standout_score(
    daily_return: float,
    gap_return: float,
    relative_volume: float,
    rs_rank: int | None,
    new_today: bool,
) -> float:
    return (
        abs(daily_return) / 0.03
        + abs(gap_return) / 0.02
        + max(0.0, relative_volume - 1.0)
        + (1.0 if new_today else 0.0)
        + (max(0, int(rs_rank) - 80) / 20 if rs_rank is not None else 0.0)
    )


def detect(
    con: duckdb.DuckDBPyConnection,
    market_date: date,
    *,
    limit: int = MAX_CANDIDATES,
    required_tickers: set[str] | None = None,
) -> dict:
    """Return a stable top-N candidate bundle for one completed market date."""
    if type(market_date) is not date or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise OpportunityError("daily opportunity request is invalid")
    screen_date = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date <= ?", [market_date]
    ).fetchone()[0]
    screen = {}
    if screen_date is not None:
        screen = {
            row[0]: row[1:]
            for row in con.execute(
                "SELECT ticker, rs_rank, template_score, passes_template, new_today "
                "FROM screen_results WHERE run_date = ?", [screen_date]
            ).fetchall()
        }
    candidates = []
    for ticker, open_px, close, volume, prior, close_5d, median_volume in _candidate_rows(
        con, market_date
    ):
        daily_return = _finite(close / prior - 1, "daily return")
        if abs(daily_return) > MAX_ABS_DAILY_RETURN:
            continue
        gap_return = _finite(open_px / prior - 1, "gap return")
        return_5d = None if not close_5d else _finite(close / close_5d - 1, "five-day return")
        relative_volume = _finite(volume / median_volume, "relative volume")
        rs_rank, template_score, passes, new_today = screen.get(ticker, (None, None, False, False))
        score = _standout_score(
            daily_return, gap_return, relative_volume, rs_rank, bool(new_today)
        )
        facts = {
            "ticker": ticker, "market_date": market_date.isoformat(),
            "close": float(close), "daily_return": daily_return,
            "overnight_gap": gap_return, "return_5d": return_5d,
            "relative_volume_20d": relative_volume, "rs_rank": rs_rank,
            "template_score": template_score, "passes_template": bool(passes),
            "new_screen_pass": bool(new_today), "earnings": _earnings(con, ticker, market_date),
            "alert_bounds": {"minimum": float(close) * 0.70, "maximum": float(close) * 1.30},
        }
        if score >= MIN_STANDOUT_SCORE or ticker in (required_tickers or set()):
            candidates.append({**facts, "standout_score": score, "evidence_id": canonical_sha256(facts)})
    candidates.sort(key=lambda item: (-item["standout_score"], item["ticker"]))
    required = required_tickers or set()
    selected = candidates[:limit]
    present = {item["ticker"] for item in selected}
    selected.extend(
        item for item in candidates if item["ticker"] in required - present
    )
    missing_required = required - {item["ticker"] for item in selected}
    if missing_required:
        raise OpportunityError(
            f"required opportunity ticker lacks current admissible data: {sorted(missing_required)}"
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "market_date": market_date.isoformat(),
        "screen_date": None if screen_date is None else screen_date.isoformat(),
        "ranking_version": "daily-standout-v1",
        "market": _market_context(con, market_date),
        "candidates": selected,
        "eligible_count": len(candidates),
    }
    return {**body, "bundle_sha256": canonical_sha256(body)}


def p15_universe(
    con: duckdb.DuckDBPyConnection,
    market_date: date,
    *,
    held_tickers: set[str] | None = None,
    information_cutoff_at=None,
) -> dict:
    """Build the deterministic, long-usable P15 scoring universe."""
    if type(market_date) is not date:
        raise OpportunityError("P15 universe market date is invalid")
    held = {ticker.upper() for ticker in (held_tickers or set())}
    screen_date = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date<=?", [market_date]
    ).fetchone()[0]
    screen = {}
    if screen_date is not None:
        screen = {
            row[0]: row[1:]
            for row in con.execute(
                "SELECT ticker,rs_rank,template_score,passes_template,new_today "
                "FROM screen_results WHERE run_date=?",
                [screen_date],
            ).fetchall()
        }
    quarantined = {item["ticker"] for item in active_quarantines(con)}
    candidates = []
    observed_tickers = set()
    for row in _p15_candidate_rows(con, market_date, information_cutoff_at):
        (ticker, open_px, close, volume, prior, close_5d, median_volume,
         median_dollar_volume, active, liquid, etf) = row
        observed_tickers.add(ticker)
        daily_return = _finite(close / prior - 1, "daily return")
        gap_return = _finite(open_px / prior - 1, "gap return")
        return_5d = None if not close_5d else _finite(close / close_5d - 1, "five-day return")
        relative_volume = _finite(volume / median_volume, "relative volume")
        rs_rank, template_score, passes, new_today = screen.get(
            ticker, (None, None, False, False)
        )
        reason = "eligible"
        if abs(daily_return) > MAX_ABS_DAILY_RETURN:
            reason = "extreme_daily_return"
        elif active is not True:
            reason = "inactive"
        elif liquid is not True:
            reason = "illiquid"
        elif etf is True:
            reason = "etf"
        elif float(median_dollar_volume) < P15_MIN_MEDIAN_DOLLAR_VOLUME:
            reason = "low_median_dollar_volume"
        elif ticker in quarantined:
            reason = "quarantined"
        is_held = ticker in held
        if reason != "eligible" and not is_held:
            continue
        facts = {
            "ticker": ticker,
            "market_date": market_date.isoformat(),
            "close": float(close),
            "daily_return": daily_return,
            "overnight_gap": gap_return,
            "return_5d": return_5d,
            "relative_volume_20d": relative_volume,
            "median_dollar_volume_20d": float(median_dollar_volume),
            "rs_rank": rs_rank,
            "template_score": template_score,
            "passes_template": bool(passes),
            "new_screen_pass": bool(new_today),
            "earnings": _earnings(
                con, ticker, market_date, information_cutoff_at
            ),
            "held": is_held,
            "tradeable": reason == "eligible",
            "reason": reason,
        }
        candidates.append({
            **facts,
            "standout_score": _standout_score(
                daily_return, gap_return, relative_volume, rs_rank, bool(new_today)
            ),
        })
    missing_held = held - observed_tickers
    if missing_held:
        raise OpportunityError(
            f"held P15 ticker lacks current admissible price history: {sorted(missing_held)}"
        )
    tradeable = [item for item in candidates if item["tradeable"]]
    movers = sorted(
        (item for item in tradeable if item["daily_return"] > 0),
        key=lambda item: (-item["standout_score"], item["ticker"]),
    )[:P15_MOVER_LIMIT]
    selected = {item["ticker"] for item in movers}
    trends = sorted(
        (item for item in tradeable if item["passes_template"] and item["ticker"] not in selected),
        key=lambda item: (
            item["rs_rank"] is None,
            -(item["rs_rank"] or 0),
            item["ticker"],
        ),
    )[:P15_TREND_LIMIT]
    selected.update(item["ticker"] for item in trends)
    held_only = sorted(
        (item for item in candidates if item["held"] and item["ticker"] not in selected),
        key=lambda item: item["ticker"],
    )
    ordered = [
        *((item, "mover") for item in movers),
        *((item, "trend") for item in trends),
        *((item, "held_only") for item in held_only),
    ]
    baseline_order = sorted(
        (item for item, _stratum in ordered),
        key=lambda item: (
            item["rs_rank"] is None,
            -(item["rs_rank"] or 0),
            -item["standout_score"],
            item["ticker"],
        ),
    )
    baseline_rank = {item["ticker"]: rank for rank, item in enumerate(baseline_order, 1)}
    output = []
    total = len(ordered)
    for ordinal, (candidate, stratum) in enumerate(ordered, 1):
        body = {
            **candidate,
            "stratum": stratum,
            "selection_ordinal": ordinal,
            "baseline_rank": baseline_rank[candidate["ticker"]],
            "baseline_score": total - baseline_rank[candidate["ticker"]] + 1,
        }
        if stratum == "held_only" and body["reason"] == "eligible":
            body.update(tradeable=False, reason="held_only")
        output.append({**body, "evidence_id": canonical_sha256(body)})
    body = {
        "schema_version": 1,
        "universe_version": "p15-universe-v1",
        "market_date": market_date.isoformat(),
        "screen_date": None if screen_date is None else screen_date.isoformat(),
        "market": _market_context(con, market_date),
        "candidates": output,
        "stratum_counts": {
            "mover": len(movers), "trend": len(trends), "held_only": len(held_only),
        },
        "eligible_count": len(tradeable),
    }
    return {**body, "bundle_sha256": canonical_sha256(body)}
