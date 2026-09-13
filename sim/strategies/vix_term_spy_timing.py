"""Research-only VIX-term SPY timer and exposure-matched static control.

These classes implement charter ``VIX-TERM-SPY-2026-09-07-v1``. They are absent
from the production registry and configs. The isolated experiment runner installs
them only while replaying scratch databases containing a labelled reconstruction
of the public VIX/VIX3M close history.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy
from .research_spy_bil import ASSETS as RESEARCH_ASSETS
from .research_spy_bil import transition_orders

CONTANGO_THRESHOLD = 0.95
STATIC_SPY_WEIGHT = 3442 / 4266
ASSETS = RESEARCH_ASSETS


def _ratio(con, as_of, *, previous: bool = False) -> float | None:
    comparator = "<" if previous else "="
    row = con.execute(
        "SELECT v.value, m.value FROM macro_signals v "
        "JOIN macro_signals m ON m.obs_date = v.obs_date "
        "WHERE v.series = 'vix' AND m.series = 'vix3m' "
        f"AND v.obs_date {comparator} ? "
        "AND v.fetch_as_of <= ? AND m.fetch_as_of <= ? "
        "AND v.value > 0 AND m.value > 0 "
        "ORDER BY v.obs_date DESC LIMIT 1",
        [as_of, as_of, as_of],
    ).fetchone()
    return None if row is None else float(row[0]) / float(row[1])


def _state_changed(con, as_of) -> tuple[bool, bool] | None:
    current = _ratio(con, as_of)
    if current is None:
        return None
    prior = _ratio(con, as_of, previous=True)
    risk_on = current < CONTANGO_THRESHOLD
    return risk_on, prior is None or risk_on != (prior < CONTANGO_THRESHOLD)


class VixTermSpyTiming(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        state = _state_changed(con, as_of)
        if state is None:
            return []
        risk_on, changed = state
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed
        )


class VixTermStaticExposure(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        state = _state_changed(con, as_of)
        if state is None:
            return []
        risk_on, changed = state
        return transition_orders(
            con, pf, as_of, risk_on=risk_on, changed=changed,
            static_spy_weight=STATIC_SPY_WEIGHT,
        )
