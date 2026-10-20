"""Same-night provisional bars are shown flagged by /candidates, not refused.

2026-10-19: the nightly collect (~22:30 UTC) stored yfinance's provisional
same-session bars, 228 of 4,058 with the open outside high/low (AIG open 80.26
under low 80.37). The read model refused them, so /candidates returned 422.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from server import market_read_models
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe, screen_table

SESSION = date(2026, 10, 19)
SAME_NIGHT = datetime(2026, 10, 19, 22, 30, 13)  # naive UTC, as stored
LATE_SAME_EVENING = datetime(2026, 10, 20, 2, 0)  # 22:00 New York, still 10-19
NEXT_NIGHT = datetime(2026, 10, 20, 22, 30, 13)


def test_bar_is_provisional_until_fetched_after_its_new_york_session_date():
    provisional = market_read_models.bar_is_provisional
    assert provisional(SESSION, SAME_NIGHT) is True
    assert provisional(SESSION, LATE_SAME_EVENING) is True
    assert provisional(SESSION, SAME_NIGHT.replace(tzinfo=timezone.utc)) is True
    assert provisional(SESSION, NEXT_NIGHT) is False
    assert provisional(SESSION, None) is False


def _candidate_store(con, fetched_at: datetime) -> None:
    screen_table(con)
    liquid_universe(con, ("SPY",))
    prior = SESSION - timedelta(days=3)
    insert_bars(con, "SPY", [prior, SESSION], open_=100, close=100.5, high=101, low=99)
    insert_bars(con, "AIG", [prior], open_=79.34, high=80.87, low=79.16, close=80.74)
    insert_bars(con, "AIG", [SESSION], open_=80.26, high=81.325, low=80.37, close=80.66)
    con.execute("UPDATE prices SET fetched_at = ?", [NEXT_NIGHT + timedelta(days=1)])
    con.execute(
        "UPDATE prices SET fetched_at = ? WHERE ticker = 'AIG' AND date = ?",
        [fetched_at, SESSION],
    )


def test_candidate_shows_a_same_night_bar_flagged_instead_of_refusing_it(con):
    _candidate_store(con, SAME_NIGHT)

    result = market_read_models.candidate(con, "AIG")

    assert result["as_of"] == SESSION
    assert [bar["provisional"] for bar in result["bars"]] == [False, True]
    assert result["bars"][-1]["open"] == pytest.approx(80.26)
    assert result["latest_close_date"] == SESSION
    assert result["latest_close"] == pytest.approx(80.66)


def test_candidate_still_refuses_a_settled_bar_with_impossible_geometry(con):
    _candidate_store(con, NEXT_NIGHT)

    with pytest.raises(market_read_models.InadmissiblePriceData) as raised:
        market_read_models.candidate(con, "AIG")

    assert raised.value.detail["bars"] == [{
        "date": "2026-10-19", "open": pytest.approx(80.26), "high": pytest.approx(81.325),
        "low": pytest.approx(80.37), "close": pytest.approx(80.66),
        "reason": "public candidate OHLC geometry is invalid",
    }]


def test_provisional_bar_still_needs_its_close_inside_high_low():
    bar = {
        "date": SESSION, "open": 80.26, "high": 81.325, "low": 80.37, "close": 80.30,
        "volume": 1_000, "provisional": True,
    }

    with pytest.raises(ValueError, match="OHLC geometry is invalid"):
        market_read_models._validate_candidate_bars([bar], SESSION)
    with pytest.raises(ValueError, match="provisional flag is invalid"):
        market_read_models._validate_candidate_bars([{**bar, "provisional": 1}], SESSION)
