"""Execution profiles and the liquidity cap apply to every fill path."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from sim import execution, fills
from tests.conftest import insert_bars

SESSION = date(2026, 10, 12)
NEW_YORK = ZoneInfo("America/New_York")
HISTORY = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)]


def _bars(con, volume=1_000_000):
    insert_bars(con, "XYZ", HISTORY, open_=100, close=100, volume=volume)
    insert_bars(con, "XYZ", [SESSION], open_=102, high=111, low=99, close=110,
                volume=1_000_000)


def _next_open(con, qty, profile):
    return fills.attempt_next_open_fill(con, "XYZ", "buy", qty, date(2026, 10, 9), SESSION,
                                        profile)


def _moo(con, qty, profile):
    return fills.attempt_auction_fill(con, "XYZ", "buy", qty, SESSION,
                                      datetime(2026, 10, 12, 9, 0, tzinfo=NEW_YORK), "moo",
                                      profile)


@pytest.mark.parametrize("profile", sorted(execution.PROFILES))
def test_v2_next_open_charges_the_profile_like_the_league_fill(con, profile):
    _bars(con)
    selected = execution.PROFILES[profile]
    components = execution.cost_components(selected, side="buy", qty=500, open_px=102,
                                           median_dollar_volume=100_000_000)
    result = _next_open(con, 500, profile)
    assert result.status == "filled"
    assert result.cost_bps == pytest.approx(components["market_bps"])
    assert result.impact_bps == pytest.approx(components["impact_bps"])
    assert result.fill_px == pytest.approx(102 * (1 + components["market_bps"] / 1e4))


@pytest.mark.parametrize("profile,expected_bps", [
    ("baseline_v1", 2.5), ("cost_2x_v1", 5.0),
    # half of 5 bp plus 10 bp * sqrt(0.0051 / 0.01) impact
    ("participation_stress_v1", 2.5 + 10 * (0.0051 / 0.01) ** 0.5),
])
def test_v2_auction_applies_the_profile_spread_and_impact(con, profile, expected_bps):
    _bars(con)
    result = _moo(con, 5_000, profile)
    assert result.status == "filled"
    assert result.cost_bps == pytest.approx(expected_bps)
    assert result.fill_px == pytest.approx(102 * (1 + expected_bps / 1e4))


def test_baseline_v2_prices_are_unchanged(con):
    _bars(con)
    assert _next_open(con, 10, None).fill_px == 102 * (1 + (5.0 + 5.0) / 1e4)
    assert _moo(con, 10, None).fill_px == 102 * (1 + 2.5 / 1e4)


def test_zero_median_dollar_volume_rejects_as_illiquid(con):
    _bars(con, volume=0)
    for result in (
        _next_open(con, 10, None),
        _moo(con, 10, None),
        fills.attempt_fill(con, "XYZ", "buy", 10, date(2026, 10, 9), SESSION),
    ):
        assert result.status == "rejected"
        assert result.reject_reason.startswith("illiquid:")
