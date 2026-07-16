"""spy_benchmark — buy SPY once at inception and hold. The market yardstick."""
from __future__ import annotations

from .base import Order, PortfolioView, Strategy, close_on


class SpyBenchmark(Strategy):
    cadence = "once"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        tk = pf.params.get("ticker", "SPY")
        if tk in pf.positions:
            return []
        price = close_on(con, tk, as_of)
        if not price:
            return []
        return [Order(pf.id, tk, "buy", pf.equity / price, as_of)]
