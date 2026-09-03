"""turtle_breakout — daily Donchian breakout on passes_template names, ATR-sized.

Entry (per passing name not held): today's close exceeds the highest close of the
prior `entry_lookback` sessions. Position size risks `risk_frac` of equity against
a `stop_mult`×ATR stop, capped at `max_weight` of equity, up to `max_positions`
concurrent. Entries are blocked entirely while the SPY-200d regime is risk-off.
Exit (per held name): a chandelier trail — close below the highest close since the
entry fill minus `trail_mult`×ATR. Missing ATR / entry date means hold, never exit
on absent data.
"""
from __future__ import annotations

from ..portfolio import position_open_since
from .base import (
    MIN_ORDER_USD,
    Order,
    PortfolioView,
    Strategy,
    atr_wilder,
    close_on,
    highest_close_between,
    latest_screen_date,
    passing_ranked,
    recent_closes,
    regime_risk_off,
)


class TurtleBreakout(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        atr_period = p.get("atr_period", 20)
        orders: list[Order] = []

        # --- exits (chandelier trail off the post-entry peak close) ---
        for tk, qty in pf.positions.items():
            since = position_open_since(con, pf.id, tk)
            if since is None:
                continue
            atr = atr_wilder(con, tk, as_of, atr_period)
            peak = highest_close_between(con, tk, since, as_of)
            close = close_on(con, tk, as_of)
            if atr is None or peak is None or close is None:
                continue
            if close < peak - p.get("trail_mult", 3.0) * atr:
                orders.append(Order(pf.id, tk, "sell", qty, as_of))

        # --- entries ---
        if regime_risk_off(con, as_of):
            return orders
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return orders
        slots = p.get("max_positions", 10) - len(pf.positions)
        if slots <= 0:
            return orders

        lookback = p.get("entry_lookback", 55)
        risk_frac = p.get("risk_frac", 0.0075)
        stop_mult = p.get("stop_mult", 2.5)
        cap = p.get("max_weight", 0.15) * pf.equity
        for tk, _rs in passing_ranked(con, sd):
            if slots <= 0:
                break
            if tk in pf.positions:
                continue
            closes = recent_closes(con, tk, as_of, lookback + 1)
            if len(closes) < lookback + 1:
                continue
            price = float(closes[-1])
            if price <= float(closes[:-1].max()):
                continue
            atr = atr_wilder(con, tk, as_of, atr_period)
            if atr is None or atr <= 0:
                continue
            qty = risk_frac * pf.equity / (stop_mult * atr)
            if qty * price > cap:
                qty = cap / price
            if qty * price < MIN_ORDER_USD:
                continue
            orders.append(Order(pf.id, tk, "buy", qty, as_of))
            slots -= 1
        return orders
