from datetime import date, datetime, timedelta, timezone

import pytest

from farm.p16_diagnostics import (
    book_comparison_status,
    decision_day,
    event_ic,
    first_daily_windows,
    paired_brier,
)


def test_first_window_uses_ny_date_and_does_not_skip_failures():
    now = datetime(2024, 7, 2, 1, tzinfo=timezone.utc)
    rows = [
        {"policy_id": "hourly", "window_id": "a", "observed_at": now, "status": "unavailable"},
        {"policy_id": "hourly", "window_id": "b", "observed_at": now + timedelta(hours=1),
         "status": "completed"},
        {"policy_id": "hourly", "window_id": "c", "observed_at": now + timedelta(days=1),
         "status": "completed"},
    ]
    assert decision_day(now) == date(2024, 7, 1)
    assert [row["window_id"] for row in first_daily_windows(rows[::-1])] == ["a", "c"]


def test_brier_pairs_samples_and_lags_exchange_sessions():
    observed = datetime(2024, 7, 1, 21, tzinfo=timezone.utc)
    matured = datetime(2024, 7, 9, 21, tzinfo=timezone.utc)
    rows = [{"market_date": date(2024, 7, 1), "observed_at": observed, "labeled_at": matured,
             "p_outperform_5": 0.1, "baseline_score": index % 3,
             "net_excess_return": 0.01 if index % 2 else -0.01} for index in range(30)]
    current = {"market_date": date(2024, 7, 10),
               "observed_at": datetime(2024, 7, 10, 21, tzinfo=timezone.utc),
               "labeled_at": datetime(2024, 7, 18, 21, tzinfo=timezone.utc),
               "p_outperform_5": 0.8, "baseline_score": 1, "net_excess_return": 0.02}
    report = paired_brier([*rows, current])
    assert report["climatology"] == pytest.approx({"paired_count": 1, "model_brier": 0.04,
                                                  "control_brier": 0.25})
    assert report["baseline_logistic"] == pytest.approx(report["climatology"])
    # Dataset still contains two dates, but July 2 is only five exchange sessions back.
    for row in rows:
        row["market_date"] = date(2024, 7, 2)
    assert paired_brier([*rows, current])["baseline_logistic"]["paired_count"] == 0
    for row in rows:
        row["labeled_at"] = current["observed_at"] + timedelta(seconds=1)
    assert paired_brier([*rows, current])["climatology"]["paired_count"] == 0


def test_next_bar_ic_excludes_prior_close_and_uses_equal_label_costs():
    now = datetime(2024, 7, 1, 15, tzinfo=timezone.utc)
    rows = [{"labeled_at": now + timedelta(days=10), "decision_at": now,
             "entry_at": now + timedelta(minutes=5), "label_basis": "next_bar",
             "missing_bar_status": "complete", "expected_excess_bp_5": index,
             "asset_return": index / 100, "spy_return": 0.02} for index in range(5)]
    stale = {**rows[0], "entry_at": now - timedelta(days=1),
             "missing_bar_status": "missing_next_bar_last_available_close",
             "expected_excess_bp_5": 1000, "asset_return": -1}
    late = {**rows[0], "labeled_at": now + timedelta(days=12)}
    report = event_ic([*rows, stale, late], generated_at=now + timedelta(days=11))
    assert report["ic"] == pytest.approx(1)
    assert report["label_count"] == 5
    assert report["excluded_counts"] == {"no_later_bar": 1, "not_yet_available": 1}
    assert report["cost_basis"] == "flat_20bp_both_legs"
    with pytest.raises(ValueError, match="cannot be pooled"):
        event_ic([*rows, {**rows[0], "label_basis": "next_session_open"}],
                 generated_at=now + timedelta(days=11))


def test_primary_kill_ends_book_comparison_before_trade_count_gate():
    assert book_comparison_status("kill", eligible=False, final_look=False) == "killed"
