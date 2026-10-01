import math
from datetime import date

import numpy as np
import pytest

from farm.study.stats import (
    TradeObservation,
    calendar_day_series,
    calendar_statistics,
    capacity_statistics,
    clustered_trade_stats,
    event_capital,
    fold_statistics,
)
from farm.walkforward.protocol import Fold


def test_entry_session_clustered_se_matches_hand_calculation():
    trades = [
        TradeObservation(date(2024, 1, 2), 0.1, 100, 10_000),
        TradeObservation(date(2024, 1, 2), 0.2, 100, 10_000),
        TradeObservation(date(2024, 1, 3), -0.1, 100, 10_000),
    ]
    result = clustered_trade_stats(trades)
    assert result["mean"] == pytest.approx(1 / 15)
    assert result["se"] == pytest.approx(1 / 9)
    assert result["one_sided_t"] == pytest.approx(0.6)
    assert result["entry_session_clusters"] == 2


def test_calendar_series_keeps_inactive_sessions_and_uses_slot_capital():
    sessions = [date(2024, 1, day) for day in range(2, 7)]
    capital = event_capital(2, 1_000)
    values = calendar_day_series(
        sessions, {sessions[1]: 100, sessions[3]: -50}, capital=capital)
    assert values.tolist() == [0, 0.05, 0, -0.025, 0]
    result = calendar_statistics(
        sessions, values, census_n=7, periods_per_year=252,
        gross_exposure=[0, 1_000, 0, 1_000, 0], traded_notional=4_000,
        capital=capital, bootstrap_draws=200)
    assert result["n_sessions"] == 5 and result["census_n"] == 7
    assert result["exposure"] == pytest.approx(0.2)
    assert result["turnover"] == 2
    assert result["sharpe_annual"] == pytest.approx(
        values.mean() / values.std(ddof=1) * math.sqrt(252))
    assert result["deflated_sharpe"] == pytest.approx(
        __import__("farm.stats.inference", fromlist=["deflated_sharpe"])
        .deflated_sharpe(values, 7)[0])


def test_census_n_is_required_and_nonfinite_calendar_values_fail():
    with pytest.raises(TypeError):
        calendar_statistics([date(2024, 1, 2)], [0])
    with pytest.raises(ValueError, match="census_n"):
        calendar_statistics([date(2024, 1, 2)], [0], census_n=0)
    with pytest.raises(ValueError, match="finite"):
        calendar_statistics([date(2024, 1, 2)], [np.nan], census_n=1)


def test_yearly_fold_statistics_and_last_three_recency():
    folds, dates, returns = [], [], []
    for index, year in enumerate(range(2018, 2024), 1):
        folds.append(Fold(index, date(year - 2, 1, 1), date(year, 1, 1),
                          date(year + 1, 1, 1)))
        dates.extend([date(year, 6, 1), date(year, 12, 1)])
        returns.extend([index / 100, index / 100])
    result = fold_statistics(dates, returns, folds)
    assert result["positive_folds"] == 6
    assert [row["fold"] for row in result["recency"]] == [4, 5, 6]
    assert result["folds"][0]["mean"] == pytest.approx(0.01)


def test_capacity_reports_each_order_and_available_maxima():
    rows = [
        TradeObservation(date(2024, 1, 2), 0, 100, 10_000, 2_000),
        TradeObservation(date(2024, 1, 3), 0, 200, 10_000, None),
    ]
    result = capacity_statistics(rows)
    assert result["max_mdv60_share"] == pytest.approx(0.02)
    assert result["max_auction_volume_share"] == pytest.approx(0.05)
    assert result["orders"][1]["auction_volume_share"] is None
