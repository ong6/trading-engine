"""P15 limit-on-open behavior without changing the frozen market-fill path."""
from __future__ import annotations

from math import inf, nan

import pytest

from sim import fills, p15_fills
from tests.conftest import SESSIONS, insert_bars

HISTORY = SESSIONS[:30]
SIGNAL = HISTORY[-1]
FILL = SESSIONS[30]


@pytest.fixture
def liquid(con):
    insert_bars(con, "AAA", HISTORY + [FILL], open_=100.0, close=100.0,
                volume=1_000_000)
    return con


def test_limit_uses_adjusted_open_and_never_clamps_price(liquid):
    market = fills.attempt_fill(liquid, "AAA", "buy", 10, SIGNAL, FILL)
    accepted = p15_fills.attempt_limit_on_open(
        liquid, "AAA", "buy", 10, SIGNAL, FILL, market.fill_px
    )
    rejected = p15_fills.attempt_limit_on_open(
        liquid, "AAA", "buy", 10, SIGNAL, FILL, market.fill_px - 0.01
    )

    assert accepted.status == "filled" and accepted.fill_px == market.fill_px
    assert rejected.status == "rejected"
    assert rejected.reject_reason == "limit_not_reached" and rejected.fill_px is None
    assert rejected.counterfactual_fill_px == market.fill_px


def test_limit_preserves_lookahead_missing_bar_and_liquidity_guards(liquid, con):
    with pytest.raises(ValueError, match="look-ahead"):
        p15_fills.attempt_limit_on_open(liquid, "AAA", "buy", 1, FILL, FILL, 101)
    over_capacity = p15_fills.attempt_limit_on_open(
        liquid, "AAA", "buy", 10_001, SIGNAL, FILL, 1_000_000
    )
    assert over_capacity.status == "rejected"
    assert over_capacity.reject_reason.startswith("illiquid")
    insert_bars(con, "SPY", SESSIONS)
    insert_bars(con, "HALT", HISTORY)
    assert p15_fills.attempt_limit_on_open(
        con, "HALT", "buy", 1, SIGNAL, FILL, 101
    ).status == "pending"


def test_limit_rejects_invalid_terms(liquid):
    with pytest.raises(ValueError, match="buy orders only"):
        p15_fills.attempt_limit_on_open(liquid, "AAA", "sell", 1, SIGNAL, FILL, 101)
    for value in (0, -1, nan, inf):
        with pytest.raises(ValueError, match="finite and positive"):
            p15_fills.attempt_limit_on_open(
                liquid, "AAA", "buy", 1, SIGNAL, FILL, value
            )
