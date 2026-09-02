"""The fill model — honest by design (execution design §2).

An order created from a close-of-day-t signal fills at the day t+1 OPEN. There
are **no same-bar fills, ever**: `assert fill_date > signal_date` is enforced in
exactly one place (`attempt_fill`) and is the single look-ahead guard.

Per-side cost is deliberately worse than any backtest assumption:

    slippage_bps = max(half_spread_bps, 5) + 5          # +5/side = 10bp round-trip

    half_spread_bps (from 60-bar median dollar volume, conservative tiers):
        >= $50M -> 5 bp
        >= $20M -> 10 bp
        >= $5M  -> 15 bp
        else    -> 25 bp

    buys  fill at open * (1 + slippage_bps/1e4)
    sells fill at open * (1 - slippage_bps/1e4)

Liquidity guard: order notional (qty * open) may not exceed 1% of the name's
60-bar median daily dollar volume → the order is REJECTED (partial fills are not
modeled in v1). If the fill-date bar is missing (halt / delisting), has a non-positive open,
or printed zero volume (nobody traded — dead quotes from the feed look exactly
like this) the order stays pending; after 3 trading days with still no
tradeable bar it rejects as 'no_bar'. A bar is never invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

from . import calendar

MEDVOL_BARS = 60          # lookback for median dollar volume
MAX_NOTIONAL_FRAC = 0.01  # order may not exceed 1% of median daily $vol
PENDING_MAX_DAYS = 3      # trading days a bar may be missing before 'no_bar'


@dataclass
class FillResult:
    """Outcome of attempting to fill one order on a given date."""
    status: str                 # 'filled' | 'rejected' | 'pending'
    reject_reason: str | None = None
    open_px: float | None = None
    fill_px: float | None = None
    slippage_bps: float | None = None
    median_dollar_vol: float | None = None


def median_dollar_vol(
    con: duckdb.DuckDBPyConnection, ticker: str, as_of: date, bars: int = MEDVOL_BARS
) -> float | None:
    """Median of close*volume over the last `bars` sessions STRICTLY BEFORE
    `as_of`.

    The window excludes `as_of` itself (date < as_of): `as_of` is the fill date,
    so including its own close×volume in the liquidity cap and slippage tier would
    consume information from the bar being traded — a small look-ahead. Returns
    None if the name has no bars at all in the window.
    """
    row = con.execute(
        """
        SELECT MEDIAN(close * volume) FROM (
            SELECT close, volume FROM prices
            WHERE ticker = ? AND date < ?
            ORDER BY date DESC LIMIT ?
        )
        """,
        [ticker, as_of, bars],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def half_spread_bps(mdv: float | None) -> float:
    """Conservative liquidity-tiered half-spread estimate (documented above)."""
    if mdv is None:
        return 25.0
    if mdv >= 50_000_000:
        return 5.0
    if mdv >= 20_000_000:
        return 10.0
    if mdv >= 5_000_000:
        return 15.0
    return 25.0


def slippage_bps_for(mdv: float | None) -> float:
    """Per-side slippage in bps: max(half_spread, 5) + 5 (the +5 = 10bp r/t)."""
    return max(half_spread_bps(mdv), 5.0) + 5.0


def attempt_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
) -> FillResult:
    """Try to fill one order at `fill_date`'s open. The ONLY look-ahead guard.

    - Asserts fill_date > signal_date (no same-bar fills, ever).
    - Missing bar: 'pending' until PENDING_MAX_DAYS trading days elapse, then
      'rejected' with reason 'no_bar' (a bar is never fabricated).
    - Liquidity guard: notional > 1% of median $vol → 'rejected' ('illiquid').
    - Otherwise 'filled' at the slippage-adjusted open.
    """
    assert fill_date > signal_date, (
        f"look-ahead violation: fill_date {fill_date} !> signal_date {signal_date}"
    )

    bar = con.execute(
        "SELECT open, volume FROM prices WHERE ticker = ? AND date = ?",
        [ticker, fill_date],
    ).fetchone()

    if bar is None or bar[0] is None or bar[0] <= 0 or not bar[1]:
        # No TRADEABLE bar on the fill date — halt / delisting / missing data.
        # Three shapes count as "no bar": the row is absent; `open` is NULL or
        # non-positive (an `open = 0.0` row would fill a buy for $0 and book
        # free shares — 4 such rows exist in the store); or `volume` is NULL/0.
        # yfinance keeps emitting a dead quote as a zero-volume bar after a
        # name stops trading (BUILDLOG 2026-08-20c), and nobody could have
        # traded at it. A thin name's legitimate zero-volume day simply waits a
        # session; after PENDING_MAX_DAYS it rejects as 'no_bar' like any halt.
        elapsed = calendar.trading_days_between(con, signal_date, fill_date)
        if elapsed >= PENDING_MAX_DAYS:
            return FillResult(status="rejected", reject_reason="no_bar")
        return FillResult(status="pending")

    open_px = float(bar[0])
    mdv = median_dollar_vol(con, ticker, fill_date)

    # Liquidity guard (partial fills not modeled v1).
    if mdv is not None and qty * open_px > MAX_NOTIONAL_FRAC * mdv:
        return FillResult(
            status="rejected",
            reject_reason=f"illiquid: notional ${qty * open_px:,.0f} > 1% of "
            f"median $vol ${mdv:,.0f}",
            open_px=open_px,
            median_dollar_vol=mdv,
        )

    slip = slippage_bps_for(mdv)
    if side == "buy":
        fill_px = open_px * (1 + slip / 1e4)
    elif side == "sell":
        fill_px = open_px * (1 - slip / 1e4)
    else:  # pragma: no cover - guarded upstream
        raise ValueError(f"bad side {side!r}")

    return FillResult(
        status="filled",
        open_px=open_px,
        fill_px=fill_px,
        slippage_bps=slip,
        median_dollar_vol=mdv,
    )
