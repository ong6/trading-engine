"""Performance statistics for one replay's daily EQUITY curve.

(Was farm/backtest/stats.py until 2026-09-03; return-series inference lives in
farm.stats.inference. This module owns the single `max_drawdown` definition.)

Input is always a book's `sim_equity` series — the mark-to-market the league
itself wrote, one row per session, cash + Σ qty×close. No returns are
reconstructed from fills or prices, so whatever the league did (including cash
drag, rejected orders and dividend credits) is inside these numbers.

Formulas (all on the daily equity closes E_0 … E_n, r_t = E_t/E_{t−1} − 1):

    total return   E_n / E_0 − 1
    years          (date_n − date_0) in days / 365.25   (calendar, not sessions)
    CAGR           (E_n / E_0)^(1/years) − 1
    ann. vol       stdev(r, ddof=1) · √252
    Sharpe (raw)   mean(r) / stdev(r, ddof=1) · √252          (rf = 0)
    Sharpe (exBIL) mean(r − r_bil) / stdev(r − r_bil, ddof=1) · √252, computed
                   only over the sub-span where BIL has bars (BIL's first bar is
                   2007-05-30); `bil_coverage` reports the fraction of the
                   window covered, and a window with < 50% coverage returns None
                   rather than a number computed off a stub.
                   r_bil is BIL's daily TOTAL return, (close_t + dps_t)/close_{t−1}
                   − 1 with dps the dividend going ex on t — a price-only BIL is
                   ~0% by construction and would make the excess Sharpe a lie.
    max drawdown   min(E_t / running_max(E) − 1)              (≤ 0)
    worst month    min over calendar months of E_monthend / E_prev_monthend − 1

√252 is used because the league steps exchange sessions, and `prices` averages
~252 sessions/yr. CAGR deliberately uses calendar years so a window that starts
or ends mid-month is not silently annualized on a different clock than the label
("1y") implies.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

TRADING_DAYS = 252.0


def bil_daily_returns(con, start: date, end: date) -> dict[date, float]:
    """BIL's daily TOTAL return by date over [start, end] (empty if no bars)."""
    rows = con.execute(
        "SELECT date, close FROM prices WHERE ticker = 'BIL' AND date >= ? "
        "AND date <= ? ORDER BY date", [start, end]).fetchall()
    if len(rows) < 2:
        return {}
    divs = dict(con.execute(
        "SELECT ex_date, value FROM corporate_actions WHERE ticker = 'BIL' "
        "AND kind = 'dividend' AND ex_date >= ? AND ex_date <= ?",
        [start, end]).fetchall())
    out: dict[date, float] = {}
    for i in range(1, len(rows)):
        d, c = rows[i]
        prev = rows[i - 1][1]
        if prev in (None, 0) or c is None:
            continue
        out[d] = (float(c) + float(divs.get(d, 0.0))) / float(prev) - 1.0
    return out


def _sharpe(r: np.ndarray) -> float:
    if len(r) < 2:
        return float("nan")
    sd = float(r.std(ddof=1))
    if sd <= 0:
        return float("nan")
    return float(r.mean()) / sd * math.sqrt(TRADING_DAYS)


def max_drawdown(equity: np.ndarray) -> float:
    """Most negative peak-to-trough on an equity curve (<= 0); 0.0 for an empty series."""
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def worst_month(dates: list[date], equity: np.ndarray) -> float:
    """Worst calendar-month return of the month-end equity series."""
    month_end: dict[tuple[int, int], float] = {}
    for d, e in zip(dates, equity):
        month_end[(d.year, d.month)] = float(e)
    keys = sorted(month_end)
    if len(keys) < 2:
        return float("nan")
    rets = [month_end[keys[i]] / month_end[keys[i - 1]] - 1.0
            for i in range(1, len(keys))]
    return float(min(rets))


def equity_stats(dates: list[date], equity_list: list[float],
                 bil: dict[date, float] | None = None) -> dict:
    """Full stat pack for one equity curve. `bil` from bil_daily_returns()."""
    eq = np.asarray(equity_list, dtype=float)
    n = len(eq)
    out: dict = {
        "n_sessions": n,
        "start_date": dates[0].isoformat() if n else None,
        "end_date": dates[-1].isoformat() if n else None,
        "equity_start": float(eq[0]) if n else None,
        "equity_end": float(eq[-1]) if n else None,
    }
    if n < 2 or eq[0] <= 0:
        return {**out, "total_return": None, "cagr": None, "vol_ann": None,
                "sharpe": None, "sharpe_ex_bil": None, "bil_coverage": 0.0,
                "max_dd": None, "worst_month": None}

    r = eq[1:] / eq[:-1] - 1.0
    years = (dates[-1] - dates[0]).days / 365.25
    total = float(eq[-1] / eq[0] - 1.0)
    out["total_return"] = total
    out["years"] = years
    out["cagr"] = float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0) if years > 0 else None
    out["vol_ann"] = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
    out["sharpe"] = _sharpe(r)
    out["max_dd"] = max_drawdown(eq)
    out["worst_month"] = worst_month(dates, eq)

    cov, sh_ex = 0.0, None
    if bil:
        pairs = [(r[i], bil[dates[i + 1]]) for i in range(len(r))
                 if dates[i + 1] in bil]
        cov = len(pairs) / len(r) if len(r) else 0.0
        if cov >= 0.5 and len(pairs) >= 2:
            ex = np.array([a - b for a, b in pairs], dtype=float)
            sh_ex = _sharpe(ex)
    out["bil_coverage"] = cov
    out["sharpe_ex_bil"] = sh_ex
    return out
