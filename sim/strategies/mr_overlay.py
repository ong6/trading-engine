"""mr_overlay — daily mean-reversion overlay on passes_template names.

Entry (per name not already held): RSI(2) < rsi_max AND `down_closes` consecutive
down closes; size `weight` of equity, up to `max_concurrent` positions.
Exit (per held name): today's close > yesterday's high, OR a `time_stop`-session
time stop. The regime gate (if set) blocks new entries while risk-off; exits
always proceed.
"""
from __future__ import annotations

from .. import calendar
from ..portfolio import position_open_since
from .base import (
    Order,
    PortfolioView,
    Strategy,
    close_on,
    latest_screen_date,
    n_down_closes,
    passing_ranked,
    recent_closes,
    recent_ohlc,
    regime_risk_off,
    rsi_wilder,
)


class MrOverlay(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        time_stop = p.get("time_stop", 10)
        orders: list[Order] = []

        # --- exits ---
        for tk, qty in pf.positions.items():
            oh = recent_ohlc(con, tk, as_of, 2)  # (date, high, close)
            exit_now = False
            if len(oh) == 2:
                high_yest, close_today = oh[0][1], oh[1][2]
                if high_yest is not None and close_today is not None:
                    exit_now = close_today > high_yest
            if not exit_now:
                since = position_open_since(con, pf.id, tk)
                if since is not None and \
                        calendar.trading_days_between(con, since, as_of) >= time_stop:
                    exit_now = True
            if exit_now:
                orders.append(Order(pf.id, tk, "sell", qty, as_of))

        # --- entries ---
        gated_off = bool(p.get("gated") and regime_risk_off(con, as_of))
        slots = p.get("max_concurrent", 5) - len(pf.positions)
        if gated_off or slots <= 0:
            return orders
        sd = latest_screen_date(con, as_of)
        if sd is None:
            return orders

        need_down = p.get("down_closes", 3)
        rsi_max = p.get("rsi_max", 10)
        weight = p.get("weight", 0.10)
        for tk, _rs in passing_ranked(con, sd):
            if slots <= 0:
                break
            if tk in pf.positions:
                continue
            closes = recent_closes(con, tk, as_of, 25)
            if len(closes) < need_down + 1:
                continue
            if n_down_closes(closes) < need_down:
                continue
            rsi = rsi_wilder(closes, 2)
            if rsi is None or rsi >= rsi_max:
                continue
            price = close_on(con, tk, as_of)
            if not price:
                continue
            orders.append(Order(pf.id, tk, "buy", weight * pf.equity / price, as_of))
            slots -= 1
        return orders
