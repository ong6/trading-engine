"""Research-only sell-in-May SPY rule and exposure-matched control.

Implements charter ``SELL-IN-MAY-SPY-2026-09-07-v1``. Neither class is in
production CONFIGS or REGISTRY; the isolated experiment runner installs them
only while its scratch replays execute.
"""
from __future__ import annotations

from datetime import date

from sim import nyse

from .base import PortfolioView, Strategy
from .research_spy_bil import ASSETS as RESEARCH_ASSETS
from .research_spy_bil import transition_orders

WINTER_MONTHS = frozenset({11, 12, 1, 2, 3, 4})
STATIC_SPY_WEIGHT = 1480 / 3019
ASSETS = RESEARCH_ASSETS


def is_winter_session(d: date) -> bool:
    """Whether a scheduled NYSE session belongs to November through April."""
    if not nyse.is_session(d):
        raise ValueError(f"sell-in-May state requested for non-session {d}")
    return d.month in WINTER_MONTHS


def _next_state(as_of: date) -> tuple[bool, bool]:
    next_session = nyse.next_session(as_of)
    current = is_winter_session(as_of)
    wanted = is_winter_session(next_session)
    return wanted, current != wanted


class SellInMaySpy(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        risk_on, changed = _next_state(as_of)
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed
        )


class SellInMayStaticExposure(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        risk_on, changed = _next_state(as_of)
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed,
            static_spy_weight=STATIC_SPY_WEIGHT,
        )
