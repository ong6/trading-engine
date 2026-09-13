"""Research-only turn-of-month SPY rule and exposure-matched control.

Implements charter ``TURN-OF-MONTH-SPY-2026-09-07-v1``. Neither class is in
production CONFIGS or REGISTRY; the isolated experiment runner installs them
only while its scratch replays execute.
"""
from __future__ import annotations

from datetime import date, timedelta

from sim import nyse

from .base import PortfolioView, Strategy
from .research_spy_bil import ASSETS as RESEARCH_ASSETS
from .research_spy_bil import transition_orders

STATIC_SPY_WEIGHT = 577 / 3019
ASSETS = RESEARCH_ASSETS


def _session_number_in_month(d: date) -> int:
    current = date(d.year, d.month, 1)
    number = 0
    while current <= d:
        if nyse.is_session(current):
            number += 1
        current += timedelta(days=1)
    return number


def is_turn_session(d: date) -> bool:
    """Final NYSE session or first three NYSE sessions of a month."""
    if not nyse.is_session(d):
        raise ValueError(f"turn-of-month state requested for non-session {d}")
    return nyse.is_last_session_of_month(d) or _session_number_in_month(d) <= 3


def _next_state(as_of: date) -> tuple[bool, bool]:
    next_session = nyse.next_session(as_of)
    current = is_turn_session(as_of)
    wanted = is_turn_session(next_session)
    return wanted, current != wanted


class TurnOfMonthSpy(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        risk_on, changed = _next_state(as_of)
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed
        )


class TurnOfMonthStaticExposure(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        risk_on, changed = _next_state(as_of)
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed,
            static_spy_weight=STATIC_SPY_WEIGHT,
        )
