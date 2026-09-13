"""Shared cross-sectional scan for the unscreened single-name books.

`xs_momentum_12_1` and `xs_reversal_1m` both rank EVERY liquid, active, non-ETF
name in `universe` on a window total return. This module holds the one
set-based DuckDB pass they share so the two books cannot drift apart on what
"the liquid universe" or "a total return" means. Nothing here reads a bar
dated after `as_of`.

Universe (today's `universe` flags — a documented survivorship compromise, the
same one `high_52wk` and `low_vol` carry):

    active AND liquid AND NOT etf          (~2.9k names on 2026-09-01)

`liquid` is set by engine/collect.py: last close ≥ $3 and median dollar volume
≥ $5M. A $39k book split 50 ways puts ~$780 per name, so the fill model's 1%-of-
median-$vol guard (`sim/fills.py`) is never the binding constraint on a name
that carries the flag; `min_price` here is a second, stricter floor so a
momentum rank is not won by a $3 name doubling on nothing.

Total return over a window of SESSIONS, not calendar days:

    (close[end] + Σ dividends ex in (start_date, end_date]) / close[start] − 1

with `end` and `start` expressed as row offsets counted back from `as_of`
(offset 1 = the `as_of` close). Dividends come from `corporate_actions` when the
table exists; when it does not (an in-memory test store, an old copy) the return
degrades to a PRICE return, which is the honest conservative direction, exactly
as `base.dividends_between` does for the single-name helper.
"""
from __future__ import annotations

from datetime import date, timedelta

# Calendar days to pull for `n` sessions. 1.7x covers weekends + holidays with
# margin; the row-number filter does the exact session counting.
_CAL_SLACK = 1.7


def has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [name]).fetchone()
    return bool(row and row[0])


def _sql(with_dividends: bool, *, snapshot: bool = False) -> str:
    div_join = (
        """
    LEFT JOIN (
        SELECT ca.ticker, SUM(ca.value) AS divs
        FROM corporate_actions ca
        JOIN ends e2 ON e2.ticker = ca.ticker
        WHERE ca.kind = 'dividend'
          AND ca.ex_date > e2.start_date AND ca.ex_date <= e2.end_date
        GROUP BY ca.ticker
    ) d ON d.ticker = e.ticker"""
        if with_dividends else ""
    )
    div_term = "COALESCE(d.divs, 0)" if with_dividends else "0"
    candidates = (
        "SELECT ticker FROM universe_snapshot WHERE snapshot_date = ? "
        "AND active AND liquid AND NOT etf"
        if snapshot
        else "SELECT ticker FROM universe WHERE active AND liquid AND NOT etf"
    )
    return f"""
WITH cand AS (
    {candidates}
), px AS (
    SELECT p.ticker, p.date, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
    FROM prices p JOIN cand c ON c.ticker = p.ticker
    WHERE p.date <= ? AND p.date > ? AND p.close > 0
), ends AS (
    SELECT ticker,
           MAX(CASE WHEN rn = 1 THEN close END)  AS last_close,
           MAX(CASE WHEN rn = ? THEN close END)  AS end_close,
           MAX(CASE WHEN rn = ? THEN date  END)  AS end_date,
           MAX(CASE WHEN rn = ? THEN close END)  AS start_close,
           MAX(CASE WHEN rn = ? THEN date  END)  AS start_date,
           CASE WHEN COUNT(*) >= 200
                THEN AVG(CASE WHEN rn <= 200 THEN close END) END AS sma200,
           COUNT(*)                              AS n_bars
    FROM px WHERE rn <= ?
    GROUP BY ticker
    HAVING COUNT(*) >= ?
)
SELECT e.ticker,
       (e.end_close + {div_term}) / e.start_close - 1 AS ret,
       e.last_close, e.sma200
FROM ends e{div_join}
WHERE e.last_close >= ? AND e.start_close > 0 AND e.end_close IS NOT NULL
ORDER BY ret DESC, e.ticker
"""


def window_returns(con, as_of: date, *, start_offset: int, end_offset: int = 1,
                   min_bars: int, min_price: float,
                   universe_snapshot_date: date | None = None) -> list[tuple]:
    """(ticker, total_return, last_close, sma200) for every candidate, best
    return first.

    start_offset / end_offset are 1-based session offsets back from `as_of`:
    12-1 momentum is start_offset=253, end_offset=22 (close 252 sessions ago →
    close 21 sessions ago); a trailing-month return is start_offset=22,
    end_offset=1. `min_bars` is the history a name must have to be ranked at all
    (a name with fewer bars is EXCLUDED, never scored on a shorter window).
    `sma200` is NULL for a name with fewer than 200 bars in the pull.

    ``universe_snapshot_date`` is for provenance checks: it evaluates the same
    rule against that immutable dated membership instead of today's mutable
    ``universe`` flags. Normal strategy execution leaves it unset.
    """
    if end_offset < 1 or start_offset <= end_offset:
        raise ValueError(f"bad offsets start={start_offset} end={end_offset}")
    if min_bars < start_offset:
        raise ValueError(f"min_bars={min_bars} < start_offset={start_offset}: "
                         f"a name could be ranked without its start close")
    depth = max(min_bars, 200)
    floor = as_of - timedelta(days=int(depth * _CAL_SLACK) + 30)
    sql = _sql(
        has_table(con, "corporate_actions"),
        snapshot=universe_snapshot_date is not None,
    )
    params = [] if universe_snapshot_date is None else [universe_snapshot_date]
    return con.execute(
        sql,
        [
            *params,
            as_of,
            floor,
            end_offset,
            end_offset,
            start_offset,
            start_offset,
            depth,
            min_bars,
            min_price,
        ],
    ).fetchall()
