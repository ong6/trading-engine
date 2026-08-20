#!/usr/bin/env python
"""Vectorized point-in-time re-computation of `screen_results` (design §12.3).

`engine/screen.py` screens ONE date at a time by pulling 400 bars per eligible
name into pandas. That is ~40 s a session — fine nightly, hopeless for 3,800
sessions × 78 replay jobs. This module computes the SAME numbers for a whole
window in one set-based DuckDB pass, using window frames over each ticker's own
bar sequence, which is exactly the positional semantics the live screener has
(`closes[-50:]` == `AVG(close) OVER (… ROWS 49 PRECEDING)`).

Formula parity with engine/screen.py — every lookback below is the live one:

    sma50/150/200      ROWS  49 /149 /199 PRECEDING … CURRENT ROW
    sma200_21ago       ROWS 220 PRECEDING … 21 PRECEDING   (closes[-221:-21])
    low52 / high52     MIN(low) / MAX(high) ROWS 251 PRECEDING … CURRENT
    ret(k)             close / LAG(close, k) − 1     k = 63/126/189/252
    rs_raw             2·r63 + r126 + r189 + r252
    rs_rank            clip(round_even(pct·99), 1, 99), pct = average-rank
                       percentile of rs_raw across that date's eligible set
                       (pandas `rank(method='average', pct=True)`; round_even
                       because numpy rounds halves to even, unlike SQL ROUND)
    checks c1..c7      identical expressions; c8 = rs_rank >= 70
    passes_template    all 8 checks
    base_tight/vol_dryup  identical (reported, not consumed by any strategy)

Point-in-time discipline. A date's row for a ticker is computed from that
ticker's LAST BAR ON OR BEFORE the date — never a later one — and a name whose
last bar is more than 3 trading sessions old is dropped, exactly like the live
`stale_cutoff` rule. Nothing reads a bar after the run_date.

Universe membership (the one honest divergence, `membership=`):
  * 'live'   — `universe.active AND universe.liquid`, the live screener's rule.
               Only meaningful for recent dates: those flags are TODAY's, and
               `liquid` was computed once at bootstrap (2026-07-16).
  * 'prices' — the historical mode: a name is in the universe on date d if it
               has >= 253 stored bars by d, its close on its as-of bar is >= $3
               and its trailing 63-bar median dollar volume is >= $5M (the same
               two floors `engine/collect.py` applies, evaluated point-in-time
               instead of once). DISCLOSURE: `prices` holds only names listed
               TODAY, so this membership is survivor-biased — delisted names are
               absent entirely, not mis-dated.

Universe policy (`universe_policy=`, default `all`). `ex-leveraged` anti-joins
the leveraged/inverse ETPs that `engine/lib/leverage.py` flags out of the
eligible set. It matters MORE here than in the live screen: a 15-year replay
holds these funds through their reverse splits, and the stored back-adjusted
closes for 35 of them exceed $2,000 (SPXU's peaks at $666,400), which produces
order sizes no fill model can honour. Default OFF so a replay reproduces the
live screen exactly unless somebody asks for otherwise, and the chosen policy
is returned to the caller for the result JSON.

Output: rows written into `screen_results` (or another table with that shape).
By default only `passes_template = TRUE` rows are stored (`passing_only`),
because every sim/strategies/* read goes through `passing_ranked` /
`rank_position`, both of which filter to passing rows — the non-passing rows are
several hundred million rows of dead weight for a 15-year replay. Pass
passing_only=False for the equivalence proof, which needs the full frame.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import db  # noqa: E402
from lib import leverage as lev  # noqa: E402

MIN_BARS = 253          # same constant as engine/screen.py
STALE_TRADING_DAYS = 3  # same
WARMUP_SESSIONS = 420   # >= engine/screen.py's WINDOW_BARS (400) → identical SMAs
LIQ_MIN_CLOSE = 3.0     # engine/collect.py liquidity floor
LIQ_MIN_MDV = 5_000_000.0
LIQ_BARS = 63           # ~90 calendar days, the bootstrap floor's window

SCREEN_COLS = [
    "run_date", "ticker", "close", "rs_rank", "template_score",
    "passes_template", "dist_50d", "dist_200d", "off_52w_low",
    "off_52w_high", "base_tight", "vol_dryup", "new_today",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def sessions_between(con, start: date, end: date) -> list[date]:
    """Trading sessions in [start, end] taken from `prices` (self-contained)."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prices WHERE date >= ? AND date <= ? ORDER BY date",
        [start, end],
    ).fetchall()]


def session_n_back(con, anchor: date, n: int) -> date:
    """The session `n` sessions before `anchor` (or the earliest stored one)."""
    rows = con.execute(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT ?",
        [anchor, n + 1],
    ).fetchall()
    return rows[-1][0]


def _tickers(con, upto: date) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM prices WHERE date <= ? ORDER BY ticker", [upto]
    ).fetchall()]


# --------------------------------------------------------------------------- #
# the pass
# --------------------------------------------------------------------------- #
_BAR_SQL = """
CREATE OR REPLACE TEMP TABLE _hs_bar AS
WITH b AS (
    SELECT p.ticker, p.date, p.close, p.volume,
           ROW_NUMBER() OVER w                                              AS rn,
           AVG(p.close)  OVER (w ROWS BETWEEN  49 PRECEDING AND CURRENT ROW) AS sma50,
           AVG(p.close)  OVER (w ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) AS sma150,
           AVG(p.close)  OVER (w ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200,
           AVG(p.close)  OVER (w ROWS BETWEEN 220 PRECEDING AND 21 PRECEDING) AS sma200_21ago,
           MIN(p.low)    OVER (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low52,
           MAX(p.high)   OVER (w ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high52,
           MAX(p.close)  OVER (w ROWS BETWEEN  19 PRECEDING AND CURRENT ROW) AS c20max,
           MIN(p.close)  OVER (w ROWS BETWEEN  19 PRECEDING AND CURRENT ROW) AS c20min,
           MAX(p.close)  OVER (w ROWS BETWEEN  39 PRECEDING AND 20 PRECEDING) AS p20max,
           MIN(p.close)  OVER (w ROWS BETWEEN  39 PRECEDING AND 20 PRECEDING) AS p20min,
           AVG(p.volume) OVER (w ROWS BETWEEN   9 PRECEDING AND CURRENT ROW) AS v10,
           AVG(p.volume) OVER (w ROWS BETWEEN  49 PRECEDING AND CURRENT ROW) AS v50,
           MEDIAN(p.close * p.volume)
                         OVER (w ROWS BETWEEN {liq_prev} PRECEDING AND CURRENT ROW) AS mdv,
           LAG(p.close,  63) OVER w AS c63,
           LAG(p.close, 126) OVER w AS c126,
           LAG(p.close, 189) OVER w AS c189,
           LAG(p.close, 252) OVER w AS c252
    FROM prices p
    JOIN _hs_chunk ch ON ch.ticker = p.ticker
    WHERE p.date <= ? AND p.date >= ?
    WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
), bx AS (
    SELECT b.*, si.idx AS bidx,
           LEAD(si.idx) OVER (PARTITION BY b.ticker ORDER BY b.date) AS nidx
    FROM b JOIN _hs_sessions si ON si.run_date = b.date
)
SELECT s.run_date, bx.*
FROM bx,
     LATERAL unnest(range(0, LEAST(COALESCE(bx.nidx, {maxidx} + 1) - bx.bidx,
                                   {stale} + 1))) AS g(gs)
JOIN _hs_window s ON s.idx = bx.bidx + g.gs
WHERE bx.rn >= {min_bars}
"""

_ELIGIBLE_SQL = """
INSERT INTO _hs_raw
SELECT
    m.run_date, m.ticker, m.close,
    2 * (m.close / m.c63  - 1)
      + (m.close / m.c126 - 1)
      + (m.close / m.c189 - 1)
      + (m.close / m.c252 - 1)                                   AS rs_raw,
    m.close / m.sma50  - 1                                       AS dist_50d,
    m.close / m.sma200 - 1                                       AS dist_200d,
    m.close / m.low52  - 1                                       AS off_52w_low,
    m.close / m.high52 - 1                                       AS off_52w_high,
    ((m.c20max - m.c20min) / m.close)
        < 0.5 * ((m.p20max - m.p20min) / m.close)                AS base_tight,
    m.v10 < m.v50                                                AS vol_dryup,
    (m.close > m.sma150 AND m.close > m.sma200)                  AS c1,
    (m.sma150 > m.sma200)                                        AS c2,
    (m.sma200 > m.sma200_21ago)                                  AS c3,
    (m.sma50 > m.sma150 AND m.sma150 > m.sma200)                 AS c4,
    (m.close > m.sma50)                                          AS c5,
    (m.close >= 1.30 * m.low52)                                  AS c6,
    (m.close >= 0.75 * m.high52)                                 AS c7
FROM _hs_bar m
{join}
{where}
"""

_RANK_SQL = """
CREATE OR REPLACE TEMP TABLE _hs_ranked AS
WITH r AS (
    SELECT *,
           RANK() OVER (PARTITION BY run_date ORDER BY rs_raw)      AS rmin,
           COUNT(*) OVER (PARTITION BY run_date, rs_raw)            AS nties,
           COUNT(rs_raw) OVER (PARTITION BY run_date)               AS ndate
    FROM _hs_raw
), p AS (
    SELECT *,
           CASE WHEN rs_raw IS NULL OR ndate = 0 THEN NULL
                ELSE (rmin + (nties - 1) / 2.0) / ndate END        AS pct
    FROM r
), k AS (
    SELECT *,
           CAST(COALESCE(LEAST(GREATEST(round_even(pct * 99, 0), 1), 99), 1)
                AS INTEGER)                                        AS rs_rank
    FROM p
)
SELECT run_date, ticker, close, rs_rank, dist_50d, dist_200d, off_52w_low,
       off_52w_high, base_tight, vol_dryup,
       CAST(c1 AS INT) + CAST(c2 AS INT) + CAST(c3 AS INT) + CAST(c4 AS INT)
       + CAST(c5 AS INT) + CAST(c6 AS INT) + CAST(c7 AS INT)
       + CAST(rs_rank >= 70 AS INT)                                AS template_score
FROM k
"""


def screen_sessions(con, sessions: list[date], *, membership: str = "prices",
                    passing_only: bool = True, table: str = "screen_results",
                    chunk_tickers: int = 1500, tickers: list[str] | None = None,
                    universe_policy: str | None = None,
                    verbose: bool = True) -> int:
    """Compute + insert screen rows for every date in `sessions`. Returns rows.

    The connection must be writable and hold `prices` (and `universe` when
    membership='live'). Existing rows for those dates are NOT deleted — the
    caller owns the append-only decision (a scratch DB starts empty).
    """
    if not sessions:
        return 0
    if membership not in ("prices", "live"):
        raise ValueError(f"membership must be 'prices' or 'live', got {membership!r}")
    policy = lev.resolve_policy(universe_policy)
    t0 = time.time()
    end = max(sessions)
    warm_start = session_n_back(con, min(sessions), WARMUP_SESSIONS)

    # Global session index (staleness is measured in trading sessions).
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _hs_sessions AS "
        "SELECT ROW_NUMBER() OVER (ORDER BY date) AS idx, date AS run_date "
        "FROM (SELECT DISTINCT date FROM prices WHERE date <= ?)", [end])
    maxidx = con.execute("SELECT MAX(idx) FROM _hs_sessions").fetchone()[0]
    con.execute("CREATE OR REPLACE TEMP TABLE _hs_window AS "
                "SELECT idx, run_date FROM _hs_sessions WHERE run_date IN "
                f"({', '.join(['?'] * len(sessions))})", sessions)

    con.execute("""
        CREATE OR REPLACE TEMP TABLE _hs_raw (
            run_date DATE, ticker VARCHAR, close DOUBLE, rs_raw DOUBLE,
            dist_50d DOUBLE, dist_200d DOUBLE, off_52w_low DOUBLE,
            off_52w_high DOUBLE, base_tight BOOLEAN, vol_dryup BOOLEAN,
            c1 BOOLEAN, c2 BOOLEAN, c3 BOOLEAN, c4 BOOLEAN, c5 BOOLEAN,
            c6 BOOLEAN, c7 BOOLEAN)
    """)

    if membership == "live":
        join = "JOIN universe u ON u.ticker = m.ticker"
        where = "WHERE u.active AND u.liquid"
    else:
        join = ""
        where = (f"WHERE m.close >= {LIQ_MIN_CLOSE} AND m.mdv >= {LIQ_MIN_MDV}")

    # The exclusion is an anti-join on a ticker list classified in PYTHON, not a
    # regex rewritten in SQL: one implementation of the rules, no drift. It is
    # appended to whichever membership WHERE clause is in force, so the two
    # filters compose instead of one silently replacing the other.
    n_excluded = 0
    if policy == lev.POLICY_EX_LEVERAGED:
        n_excluded = lev.register_exclusion(con)
        where += " AND m.ticker NOT IN (SELECT ticker FROM _lev_excluded)"
        if verbose:
            print(f"[hist_screen] policy {policy}: {n_excluded} leveraged/inverse "
                  f"ETPs excluded from every session", flush=True)

    all_tickers = tickers if tickers is not None else _tickers(con, end)
    bar_sql = _BAR_SQL.format(min_bars=MIN_BARS, stale=STALE_TRADING_DAYS,
                              maxidx=maxidx, liq_prev=LIQ_BARS - 1)
    elig_sql = _ELIGIBLE_SQL.format(join=join, where=where)

    for i in range(0, len(all_tickers), chunk_tickers):
        chunk = all_tickers[i:i + chunk_tickers]
        con.execute("CREATE OR REPLACE TEMP TABLE _hs_chunk (ticker VARCHAR)")
        con.executemany("INSERT INTO _hs_chunk VALUES (?)", [(t,) for t in chunk])
        con.execute(bar_sql, [end, warm_start])
        con.execute(elig_sql)
        if verbose:
            n = con.execute("SELECT COUNT(*) FROM _hs_raw").fetchone()[0]
            print(f"[hist_screen] tickers {i + len(chunk)}/{len(all_tickers)} "
                  f"→ {n:,} eligible (ticker, date) rows "
                  f"[{time.time() - t0:.0f}s]", flush=True)

    con.execute(_RANK_SQL)
    # new_today: passes today and did not pass on the previous run_date in the
    # window. The first window date has no predecessor → False (live's first_run).
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _hs_prev AS "
        "SELECT run_date, LAG(run_date) OVER (ORDER BY run_date) AS prev "
        "FROM (SELECT DISTINCT run_date FROM _hs_ranked)")
    filt = "WHERE k.template_score = 8" if passing_only else ""
    con.execute(f"""
        INSERT INTO {table} ({', '.join(SCREEN_COLS)})
        SELECT k.run_date, k.ticker, k.close, k.rs_rank, k.template_score,
               k.template_score = 8 AS passes_template,
               k.dist_50d, k.dist_200d, k.off_52w_low, k.off_52w_high,
               k.base_tight, k.vol_dryup,
               COALESCE(k.template_score = 8 AND pv.prev IS NOT NULL
                        AND NOT EXISTS (SELECT 1 FROM _hs_ranked q
                                        WHERE q.ticker = k.ticker
                                          AND q.run_date = pv.prev
                                          AND q.template_score = 8), FALSE)
               AS new_today
        FROM _hs_ranked k JOIN _hs_prev pv ON pv.run_date = k.run_date
        {filt}
    """)
    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for t in ("_hs_bar", "_hs_raw", "_hs_ranked", "_hs_chunk", "_hs_sessions",
              "_hs_window", "_hs_prev", "_lev_excluded"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    if verbose:
        print(f"[hist_screen] {len(sessions)} sessions → {n:,} rows in "
              f"{time.time() - t0:.0f}s ({'passing only' if passing_only else 'all rows'}, "
              f"membership={membership}, policy={policy})", flush=True)
    return n


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Vectorized historical screen.")
    ap.add_argument("--db", required=True, help="DuckDB path (a SCRATCH copy)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--membership", default="prices", choices=["prices", "live"])
    ap.add_argument("--all-rows", action="store_true",
                    help="store non-passing rows too (equivalence proof)")
    ap.add_argument("--table", default="screen_results")
    ap.add_argument("--universe-policy", default=None, choices=list(lev.POLICIES),
                    help=f"'all' (DEFAULT) or 'ex-leveraged'. Env: {lev.POLICY_ENV}")
    args = ap.parse_args()

    con = db.connect(args.db)
    db.init_schema(con)
    days = sessions_between(con, date.fromisoformat(args.start),
                            date.fromisoformat(args.end))
    print(f"[hist_screen] {len(days)} sessions {days[0]} → {days[-1]}")
    screen_sessions(con, days, membership=args.membership,
                    passing_only=not args.all_rows, table=args.table,
                    universe_policy=args.universe_policy)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
