"""Price-table invariants: bar geometry and one split basis per series.

Split tolerances mirror the reconciler in ``engine/actions.py`` (a test pins them): a
one-session close ratio ``close(t-1) / close(t)`` is split-sized when it lands within 8% (log)
of a split ratio and outside the ambiguity band ``[1/1.44, 1.44]``.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .registry import Context, json_value, register, violation

NEW_YORK = ZoneInfo("America/New_York")
TOL_LOG = math.log(1.08)
MIN_SEPARATION_LOG = math.log(1.44)
BREAK_NEAR_EX_SESSIONS = 5
SCAN_RATIOS = (1.5, 2.0, 3.0, 4.0, 5.0, 10.0)
SCAN_SESSIONS = 63          # about one quarter of sessions for unrecorded breaks
VOLUME_SESSIONS = 5
RECORDED_NEAR_DAYS = 7      # a split row within this many days explains a break


def _fetched_session(fetched_at: datetime | None) -> date | None:
    """New York calendar date of a naive-UTC fetch stamp."""
    if fetched_at is None:
        return None
    return fetched_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(NEW_YORK).date()


@register("ohlc_geometry", "market_data", tables=("prices",))
def ohlc_geometry(ctx: Context) -> tuple[dict, list[dict]]:
    """Every bar has low <= open, close <= high, all four prices finite and positive.

    A bar whose last fetch fell on or before its own New York session date is the
    same-night provisional bar (re-fetched the next night). On the newest session that is
    expected to be imperfect, so it is classed ``provisional``; one on an older session was
    never re-fetched and is ``stale_provisional``; anything else is ``settled``.
    """
    latest, total, latest_bars = ctx.con.execute(
        "SELECT MAX(date), COUNT(*), COUNT(*) FILTER (WHERE date = (SELECT MAX(date) "
        "FROM prices)) FROM prices").fetchone()
    rows = ctx.con.execute(
        """
        SELECT ticker, date, open, high, low, close, fetched_at FROM prices
        WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
           OR NOT (isfinite(open) AND isfinite(high) AND isfinite(low) AND isfinite(close))
           OR LEAST(open, high, low, close) <= 0
           OR high < low OR open > high OR open < low OR close > high OR close < low
        ORDER BY date, ticker
        """).fetchall()
    found = []
    for ticker, day, open_, high, low, close, fetched_at in rows:
        values = (open_, high, low, close)
        if any(value is None or not math.isfinite(value) for value in values):
            shape = "missing_or_nonfinite"
        elif min(values) <= 0:
            shape = "nonpositive"
        elif high < low:
            shape = "high_below_low"
        elif close > high or close < low:
            shape = "close_outside_range"
        else:
            shape = "open_outside_range"
        fetched = _fetched_session(fetched_at)
        if fetched is not None and fetched <= day:
            kind = "provisional" if day == latest else "stale_provisional"
        else:
            kind = "settled"
        found.append(violation(
            f"{ticker} {day.isoformat()}", kind, date=day.isoformat(), shape=shape,
            open=json_value(open_), high=json_value(high), low=json_value(low),
            close=json_value(close), fetched_at=json_value(fetched_at)))
    on_latest = sum(item["detail"]["date"] == (latest.isoformat() if latest else None)
                    for item in found)
    by_class: dict[str, int] = {}
    for item in found:
        by_class[item["class"]] = by_class.get(item["class"], 0) + 1
    facts = {
        "bars": total, "impossible_bars": len(found), "by_class": by_class,
        "latest_session": json_value(latest), "latest_session_bars": latest_bars,
        "latest_session_impossible": on_latest,
        "latest_session_impossible_pct": round(100 * on_latest / latest_bars, 2)
        if latest_bars else None,
    }
    return facts, found


def _ratio_sql() -> str:
    ratios = [*SCAN_RATIOS, *(1 / ratio for ratio in SCAN_RATIOS)]
    return "[" + ", ".join(repr(float(ratio)) for ratio in ratios) + "]::DOUBLE[]"


@register("one_split_basis_per_ticker", "market_data",
          tables=("prices", "universe", "corporate_actions", "split_adjustments"))
def one_split_basis_per_ticker(ctx: Context) -> tuple[dict, list[dict]]:
    """No recorded split of a liquid name leaves its scale break in the stored series.

    For each recorded split outside the ambiguity band, a one-session close ratio matching
    the split ratio within ``BREAK_NEAR_EX_SESSIONS`` sessions of the ex-date means the bars
    before it are still on the pre-split basis. The class is the reconciler's recorded
    outcome (``unadjudicated`` when it has none).
    """
    rows = ctx.con.execute(
        f"""
        WITH liquid AS (SELECT ticker FROM universe WHERE liquid),
        splits AS (
            SELECT c.ticker, c.ex_date, c.value AS ratio, a.outcome
            FROM corporate_actions c JOIN liquid USING (ticker)
            LEFT JOIN split_adjustments a ON a.ticker = c.ticker AND a.ex_date = c.ex_date
            WHERE c.kind = 'split' AND c.value > 0 AND abs(ln(c.value)) >= {MIN_SEPARATION_LOG}
        ),
        series AS (
            SELECT ticker, date, close, lag(close) OVER w AS prev_close,
                   row_number() OVER w AS rn
            FROM prices
            WHERE close > 0 AND isfinite(close) AND ticker IN (SELECT ticker FROM splits)
            WINDOW w AS (PARTITION BY ticker ORDER BY date)
        ),
        anchored AS (
            SELECT s.*, (SELECT MIN(rn) FROM series x
                         WHERE x.ticker = s.ticker AND x.date >= s.ex_date) AS ex_rn
            FROM splits s
        )
        SELECT a.ticker, a.ex_date, a.ratio, a.outcome, x.date, x.prev_close / x.close,
               x.rn - a.ex_rn
        FROM anchored a JOIN series x ON x.ticker = a.ticker
         AND x.rn BETWEEN a.ex_rn - {BREAK_NEAR_EX_SESSIONS} AND a.ex_rn + {BREAK_NEAR_EX_SESSIONS}
        WHERE x.prev_close IS NOT NULL
          AND abs(ln(x.prev_close / x.close) - ln(a.ratio)) <= {TOL_LOG}
        ORDER BY a.ex_date, a.ticker, x.date
        """).fetchall()
    found, seen = [], set()
    for ticker, ex_date, ratio, outcome, break_date, observed, distance in rows:
        if (ticker, ex_date) in seen:
            continue
        seen.add((ticker, ex_date))
        found.append(violation(
            f"{ticker} {ex_date.isoformat()}", outcome or "unadjudicated",
            date=ex_date.isoformat(), ratio=ratio, break_date=break_date.isoformat(),
            observed=round(observed, 6), sessions_from_ex=distance))
    checked = ctx.con.execute(
        f"SELECT COUNT(*) FROM corporate_actions c JOIN universe u ON u.ticker = c.ticker "
        f"AND u.liquid WHERE c.kind = 'split' AND c.value > 0 "
        f"AND abs(ln(c.value)) >= {MIN_SEPARATION_LOG}").fetchone()[0]
    return {"liquid_splits_checked": checked, "mixed_basis": len(found)}, found


@register("split_recorded_vs_restated", "market_data",
          tables=("prices", "universe", "corporate_actions"))
def split_recorded_vs_restated(ctx: Context) -> tuple[dict, list[dict]]:
    """A split-sized break in a liquid name's recent closes has a recorded split near it.

    Over the last ``SCAN_SESSIONS`` sessions: a close ratio matching a split ratio (or its
    inverse), the median volume of the five bars from it shifted by that ratio (within half
    its log size) against the five before, not reversed by the next bar (a single-bar glitch),
    and no ``corporate_actions`` split row within ``RECORDED_NEAR_DAYS`` days.
    """
    days = ctx.con.execute(
        "SELECT date FROM (SELECT DISTINCT date FROM prices) ORDER BY date DESC LIMIT ?",
        [SCAN_SESSIONS + VOLUME_SESSIONS]).fetchall()
    if len(days) < 2:
        return {"scan_from": None, "names_scanned": 0, "unrecorded": 0}, []
    scan_from = days[min(SCAN_SESSIONS, len(days)) - 1][0]
    rows = ctx.con.execute(
        f"""
        WITH series AS (
            SELECT ticker, date, close, lag(close) OVER w AS prev_close,
                   lead(close) OVER w AS next_close,
                   median(NULLIF(volume, 0)) OVER (PARTITION BY ticker ORDER BY date
                       ROWS BETWEEN {VOLUME_SESSIONS} PRECEDING AND 1 PRECEDING) AS volume_before,
                   median(NULLIF(volume, 0)) OVER (PARTITION BY ticker ORDER BY date
                       ROWS BETWEEN CURRENT ROW AND {VOLUME_SESSIONS - 1} FOLLOWING)
                       AS volume_after
            FROM prices
            WHERE date >= ? AND close > 0 AND isfinite(close)
              AND ticker IN (SELECT ticker FROM universe WHERE liquid)
            WINDOW w AS (PARTITION BY ticker ORDER BY date)
        ),
        breaks AS (
            SELECT s.*, ratio, ln(prev_close / close) AS lr
            FROM series s, (SELECT unnest({_ratio_sql()}) AS ratio)
            WHERE date >= ? AND prev_close IS NOT NULL
              AND abs(ln(prev_close / close)) >= {MIN_SEPARATION_LOG}
              AND abs(ln(prev_close / close) - ln(ratio)) <= {TOL_LOG}
        )
        SELECT ticker, date, prev_close, close, next_close, ratio,
               volume_after / volume_before
        FROM breaks b
        WHERE volume_before > 0 AND volume_after > 0
          AND abs(ln(volume_after / volume_before) - ln(ratio)) <= abs(ln(ratio)) / 2
          AND NOT (next_close IS NOT NULL AND abs(ln(close / next_close) + lr) <= {TOL_LOG})
          AND NOT EXISTS (
              SELECT 1 FROM corporate_actions c
              WHERE c.ticker = b.ticker AND c.kind = 'split'
                AND c.ex_date BETWEEN b.date - INTERVAL {RECORDED_NEAR_DAYS} DAY
                                  AND b.date + INTERVAL {RECORDED_NEAR_DAYS} DAY)
        ORDER BY date, ticker
        """, [days[-1][0], scan_from]).fetchall()
    found = [violation(
        f"{ticker} {day.isoformat()}", "unrecorded", date=day.isoformat(),
        ratio=round(ratio, 6), prev_close=prev_close, close=close,
        volume_shift=round(shift, 4)) for ticker, day, prev_close, close, _next, ratio, shift
        in rows]
    names = ctx.con.execute(
        "SELECT COUNT(DISTINCT p.ticker) FROM prices p JOIN universe u ON u.ticker = p.ticker "
        "AND u.liquid WHERE p.date >= ?", [scan_from]).fetchone()[0]
    return {"scan_from": scan_from.isoformat(), "names_scanned": names,
            "unrecorded": len(found)}, found
