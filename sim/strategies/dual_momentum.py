"""dual_momentum — classic GEM on SPY vs EFA, cash proxy BIL.

Monthly: pick the 12-month (252-session) total-return winner of the risk assets;
hold it 100% if it beats BIL's 12-mo return, else go to cash. If BIL is missing
its return is taken as 0 (cash earns nothing) — never fabricated. The regime gate
(if configured) also forces cash while risk-off; since GEM already exits to cash
in weak tapes the gate rarely binds.
"""
from __future__ import annotations

from .base import (
    PortfolioView, Strategy, rebalance_orders, regime_risk_off, total_return,
)


class DualMomentum(Strategy):
    cadence = "monthly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        p = pf.params
        lookback = p.get("lookback", 252)
        rets = {}
        for a in p.get("assets", ["SPY", "EFA"]):
            r = total_return(con, a, as_of, lookback)
            if r is not None:
                rets[a] = r
        if not rets:
            return []  # not enough history yet — do nothing (never guess)
        winner = max(rets, key=rets.get)
        bil = total_return(con, p.get("cash_proxy", "BIL"), as_of, lookback)
        bil = 0.0 if bil is None else bil

        gated_off = bool(p.get("gated") and regime_risk_off(con, as_of))
        go_risk = rets[winner] > bil and not gated_off
        targets = {winner: 1.0} if go_risk else {}
        return rebalance_orders(con, pf, as_of, targets, allow_buys=not gated_off)
