"""Strategy interface + shared signal/sizing helpers.

A strategy turns close-of-`as_of_date` information into a list of Orders. The
contract: `generate_orders(con, pf, as_of_date)` may read price/screen data ONLY
with date <= as_of_date. Orders are *intents*; fills.py decides if/when/at what
price they execute (always at a later bar's open).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

MIN_ORDER_USD = 50.0  # skip dust rebalancing below this notional


@dataclass
class Order:
    portfolio_id: str
    ticker: str
    side: str          # 'buy' | 'sell'
    qty: float
    signal_date: date


@dataclass
class PortfolioView:
    """A portfolio's decision-time state, handed to a strategy."""
    id: str
    params: dict
    cash: float
    positions: dict          # {ticker: qty}
    equity: float            # MTM at as_of close


class Strategy:
    """Base strategy. Subclasses set `cadence` and implement generate_orders."""
    cadence = "daily"        # 'daily' | 'weekly' | 'monthly' | 'once'

    def generate_orders(
        self, con: duckdb.DuckDBPyConnection, pf: PortfolioView, as_of: date
    ) -> list[Order]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# screen / regime reads (all with date <= as_of)
# --------------------------------------------------------------------------- #
def latest_screen_date(con, as_of: date) -> date | None:
    row = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date <= ?", [as_of]
    ).fetchone()
    return row[0] if row else None


def passing_ranked(con, screen_date: date) -> list[tuple[str, int]]:
    """(ticker, rs_rank) for passes_template names, best RS first."""
    return con.execute(
        "SELECT ticker, rs_rank FROM screen_results "
        "WHERE run_date = ? AND passes_template ORDER BY rs_rank DESC, ticker",
        [screen_date],
    ).fetchall()


def rank_position(con, screen_date: date) -> dict[str, int]:
    """{ticker: 1-based rank among passing names by RS} — for banding tests."""
    out = {}
    for i, (tk, _rs) in enumerate(passing_ranked(con, screen_date), start=1):
        out[tk] = i
    return out


def regime_risk_off(con, as_of: date) -> bool:
    """SPY close < its 200-session SMA at as_of → risk-off. Unknown (SPY absent
    / <200 bars) is treated as NOT risk-off (don't block on missing data)."""
    spy = con.execute(
        "SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "ORDER BY date DESC LIMIT 200",
        [as_of],
    ).fetchall()
    if len(spy) < 200:
        return False
    closes = np.array([r[0] for r in spy], dtype=float)
    return closes[0] < closes.mean()


def close_on(con, ticker: str, as_of: date) -> float | None:
    row = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        [ticker, as_of],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def recent_closes(con, ticker: str, as_of: date, n: int) -> np.ndarray:
    rows = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, n],
    ).fetchall()
    return np.array([r[0] for r in reversed(rows)], dtype=float)


def recent_ohlc(con, ticker: str, as_of: date, n: int):
    rows = con.execute(
        "SELECT date, high, close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, n],
    ).fetchall()
    return list(reversed(rows))


def total_return(con, ticker: str, as_of: date, lookback: int) -> float | None:
    """close(as_of) / close(lookback sessions ago) - 1, or None if too short."""
    rows = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, lookback + 1],
    ).fetchall()
    if len(rows) < lookback + 1:
        return None
    last = rows[0][0]
    past = rows[lookback][0]
    if past in (None, 0) or last is None:
        return None
    return last / past - 1


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #
def rsi_wilder(closes: np.ndarray, period: int = 2) -> float | None:
    """Standard Wilder RSI. Needs > period closes. Returns the latest value."""
    if closes is None or len(closes) <= period:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr_wilder(con, ticker: str, as_of: date, period: int = 20) -> float | None:
    """Wilder-smoothed ATR at as_of. None if fewer than period+1 bars, or if any
    high/low/close in the window is NULL (never patch a missing bar)."""
    rows = con.execute(
        "SELECT high, low, close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, period * 3 + 1],
    ).fetchall()
    if len(rows) < period + 1:
        return None
    bars = list(reversed(rows))
    if any(v is None for bar in bars for v in bar):
        return None
    trs = []
    for i in range(1, len(bars)):
        hi, lo, _ = bars[i]
        prev_close = bars[i - 1][2]
        trs.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


def highest_close_between(con, ticker: str, start_date: date, end_date: date):
    """Max close in (start_date, end_date] — the chandelier-exit reference peak."""
    row = con.execute(
        "SELECT MAX(close) FROM prices WHERE ticker = ? AND date > ? AND date <= ?",
        [ticker, start_date, end_date],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def n_down_closes(closes: np.ndarray) -> int:
    """How many consecutive down closes end the series (close[i] < close[i-1])."""
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            n += 1
        else:
            break
    return n


# --------------------------------------------------------------------------- #
# sizing
# --------------------------------------------------------------------------- #
def rebalance_orders(
    con, pf: PortfolioView, as_of: date, target_weights: dict[str, float],
    *, allow_buys: bool = True,
) -> list[Order]:
    """Emit buy/sell orders moving `pf` toward target_weights (of equity).

    Held names absent from targets are sold in full. Dust deltas below
    MIN_ORDER_USD are skipped. If allow_buys is False (risk-off gate) only sell
    orders are emitted — entries are blocked, exits proceed.
    """
    orders: list[Order] = []
    names = set(target_weights) | set(pf.positions)
    for tk in sorted(names):
        price = close_on(con, tk, as_of)
        if price is None or price <= 0:
            continue
        target_qty = target_weights.get(tk, 0.0) * pf.equity / price
        cur_qty = pf.positions.get(tk, 0.0)
        delta = target_qty - cur_qty
        if abs(delta) * price < MIN_ORDER_USD:
            continue
        if delta > 0:
            if allow_buys:
                orders.append(Order(pf.id, tk, "buy", delta, as_of))
        else:
            orders.append(Order(pf.id, tk, "sell", -delta, as_of))
    return orders
