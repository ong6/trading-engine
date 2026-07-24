"""discretionary — the owner's paper book. Orders come ONLY from UI tickets
(server/main.py inserts pending sim_orders after the risk gates); the league
must never generate orders for it. It still participates in fill_pending and
mark-to-market like any other portfolio — this class exists so generate_all's
registry lookup succeeds instead of KeyError-ing the whole nightly step."""
from __future__ import annotations

from .base import PortfolioView, Strategy


class Discretionary(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        return []
