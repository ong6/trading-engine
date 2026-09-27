"""W4 split clock, quarantine, and consumer price-series tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from farm.replay.asof import (
    PriceSeriesError,
    SplitQuarantineError,
    asof_split_adjusted_bars,
    consumer_price_series,
    label_price_point,
    label_split_normalized_return,
    quarantined_exposure_counts,
    raw_price_spot_check,
    reconstruct_unadjusted_bars,
    split_adjustment_actions,
    split_known_at,
    split_outcome,
)
from farm.replay.p15_adapter import prepare_p15_price_inputs
from farm.replay.registration import (
    INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
    PRICE_SERIES_BY_CONSUMER,
    SPLIT_KNOWLEDGE_PRIMARY,
    SPLIT_KNOWLEDGE_SENSITIVITY,
    mandatory_acceptance_contract,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "p16_replay_price_actions.json"


def _fixture():
    return json.loads(FIXTURE.read_text())


def _action(**changes):
    action = dict(_fixture()["actions"][0])
    action.update(changes)
    return action


def test_split_knowledge_uses_registered_primary_and_fixed_lag_sensitivity():
    action = _action()
    assert split_known_at(action, SPLIT_KNOWLEDGE_PRIMARY) == datetime(
        2020, 8, 31, 13, 30, tzinfo=timezone.utc
    )
    assert action["retrieved_at_real"].startswith("2026-")
    assert action["known_at_replay"].startswith("2020-")
    assert split_known_at(action, SPLIT_KNOWLEDGE_SENSITIVITY) == datetime(
        2020, 9, 1, 13, 30, tzinfo=timezone.utc
    )


def test_reconstruction_is_independent_of_late_real_retrieval_clock():
    fixture = _fixture()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])[0]
    assert rebuilt["series"] == "reconstructed_unadjusted_v1"
    for field, expected in fixture["expected_reconstructed"].items():
        assert rebuilt[field] == pytest.approx(expected)
    assert fixture["independent_validation"] == {
        "source": INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
        "status": "required_before_archive_admission",
    }


def test_raw_price_spot_check_uses_registered_independent_source():
    fixture = _fixture()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])
    reference = [{
        "security_id": rebuilt[0]["security_id"],
        "session": rebuilt[0]["session"],
        "source": INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
        "stratum": "split_window",
        **fixture["expected_reconstructed"],
    }]
    assert raw_price_spot_check(rebuilt, reference)["status"] == "pass"
    reference[0]["close"] += 1
    assert raw_price_spot_check(rebuilt, reference)["status"] == "quarantine"


def test_reconstruction_indexes_actions_once_for_many_bars():
    class CountingActions(list):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    fixture = _fixture()
    actions = CountingActions(fixture["actions"])
    reconstruct_unadjusted_bars(fixture["bars"] * 20, actions)
    assert actions.iterations == 1


def test_feature_scale_changes_only_after_split_is_effective_and_known():
    fixture = _fixture()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])
    before = asof_split_adjusted_bars(
        rebuilt,
        fixture["actions"],
        as_of=datetime(2020, 8, 30, 20, 15, tzinfo=timezone.utc),
    )[0]
    after = asof_split_adjusted_bars(
        rebuilt,
        fixture["actions"],
        as_of=datetime(2020, 8, 31, 20, 15, tzinfo=timezone.utc),
    )[0]
    assert before["close"] == pytest.approx(499.23)
    assert before["volume"] == pytest.approx(46_907_500)
    assert after["close"] == pytest.approx(124.8075)
    assert after["volume"] == pytest.approx(187_630_000)


def test_fixed_lag_sensitivity_applies_one_session_after_ex_date():
    fixture = _fixture()
    action = _action()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], [action])
    before = asof_split_adjusted_bars(
        rebuilt, [action], as_of=datetime(2020, 8, 31, 1, tzinfo=timezone.utc),
        knowledge_policy=SPLIT_KNOWLEDGE_SENSITIVITY,
    )[0]
    assert before["close"] == pytest.approx(499.23)
    assert before["asof_action_ids"] == []
    after = asof_split_adjusted_bars(
        rebuilt, [action], as_of=datetime(2020, 9, 1, 20, 15, tzinfo=timezone.utc),
        knowledge_policy=SPLIT_KNOWLEDGE_SENSITIVITY,
    )[0]
    assert after["close"] == pytest.approx(124.8075)
    assert after["asof_action_ids"] == [action["action_id"]]


@pytest.mark.parametrize("outcome", ("applied", "noop_restated"))
def test_only_explicit_trusted_split_outcomes_can_supply_a_ratio(outcome):
    assert split_outcome(_action(outcome=outcome)) == "trusted"


def test_split_adjustment_adapter_uses_ticker_reuse_quarantine_for_mapping():
    rows = [
        {"ticker": "AAA", "ex_date": "2024-01-03", "ratio": 2, "outcome": "applied"},
        {
            "ticker": "OLD", "ex_date": "2024-01-04", "ratio": 3,
            "outcome": "superseded_by_refetch",
        },
    ]
    actions = split_adjustment_actions(
        rows,
        security_ids_by_ticker={"AAA": "security-a", "OLD": "security-old"},
        ticker_reuse_quarantine=frozenset({"OLD"}),
    )
    assert actions[0] == {
        "action_id": "AAA:2024-01-03",
        "security_id": "security-a",
        "stable_mapping": True,
        "kind": "split",
        "ex_date": datetime(2024, 1, 3).date(),
        "outcome": "applied",
        "new_shares_per_old": 2,
    }
    assert split_outcome(actions[0]) == "trusted"
    assert actions[1]["stable_mapping"] is False
    assert split_outcome(actions[1]) == "quarantined"


def test_noop_pre_history_is_explicitly_trusted_without_a_ratio_application():
    assert split_outcome(_action(outcome="noop_pre_history")) == "trusted_noop"


@pytest.mark.parametrize(
    "outcome",
    (
        None,
        "skipped_invalid_ratio",
        "skipped_price_continuity",
        "reverted_false_break",
        "superseded_by_refetch",
        "unexpected_new_value",
    ),
)
def test_all_other_split_outcomes_quarantine(outcome):
    action = _action(outcome=outcome)
    assert split_outcome(action) == "quarantined"
    with pytest.raises(SplitQuarantineError, match="quarantined_split"):
        reconstruct_unadjusted_bars(_fixture()["bars"], [action])


def test_future_split_does_not_change_any_registered_feature_consumer():
    fixture = _fixture()
    future = _action(ex_date="2020-09-30")
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], [future])
    before = asof_split_adjusted_bars(
        rebuilt,
        [future],
        as_of=datetime(2020, 9, 1, 20, 15, tzinfo=timezone.utc),
    )[0]
    assert before["asof_split_factor"] == 1.0
    assert before["close"] == pytest.approx(rebuilt[0]["close"])
    feature_consumers = {
        "atr14",
        "daily_return",
        "relative_strength",
        "screen_253",
        "absolute_return_guard",
        "median_dollar_volume",
        "p15_universe",
        "position_sizing",
    }
    assert {consumer_price_series(name) for name in feature_consumers} == {
        "asof_split_adjusted_v1"
    }


def test_labels_use_horizon_split_normalization_for_asset_and_spy():
    action = _action(
        security_id="fixture",
        ex_date="2020-01-03",
        new_shares_per_old=2,
    )
    bars = reconstruct_unadjusted_bars(
        [
            {"security_id": "fixture", "session": "2020-01-02", "series": "source_back_adjusted_v1",
             "available_at": "2020-01-02T21:15:00Z", "open": 50, "high": 50, "low": 50, "close": 50, "volume": 10},
            {"security_id": "fixture", "session": "2020-01-03", "series": "source_back_adjusted_v1",
             "available_at": "2020-01-03T21:15:00Z", "open": 50, "high": 50, "low": 50, "close": 50, "volume": 20},
        ],
        [action],
    )
    arguments = dict(
        entry_point=label_price_point(bars[0], "open"),
        exit_point=label_price_point(bars[1], "close"),
        entry_at=datetime(2020, 1, 2, 14, 30, tzinfo=timezone.utc),
        exit_at=datetime(2020, 1, 3, 21, tzinfo=timezone.utc),
        visible_at=datetime(2020, 1, 3, 21, 15, tzinfo=timezone.utc),
        actions=[action],
        entry_cost_bps=0,
        exit_cost_bps=0,
    )
    assert label_split_normalized_return(security_id="fixture", **arguments) == pytest.approx(0)
    assert consumer_price_series("asset_label") == "label_split_normalized_v1"
    assert consumer_price_series("spy_label") == "label_split_normalized_v1"
    with pytest.raises(SplitQuarantineError, match="late_split_knowledge"):
        label_split_normalized_return(
            security_id="fixture",
            **{
                **arguments, "actions": [action],
                "knowledge_policy": SPLIT_KNOWLEDGE_SENSITIVITY,
            },
        )


def test_quarantined_held_and_pending_splits_are_counted_per_window():
    bad = _action(outcome="superseded_by_refetch")
    exposures = [
        {
            "window_id": "w1",
            "security_id": bad["security_id"],
            "start": "2020-08-28",
            "end": "2020-09-02",
            "state": state,
        }
        for state in ("held", "pending")
    ]
    assert quarantined_exposure_counts(
        [bad], iter(exposures), registered_windows=("w1", "w2")
    ) == [
        {"window_id": "w1", "held": 1, "pending": 1, "affected_actions": 1},
        {"window_id": "w2", "held": 0, "pending": 0, "affected_actions": 0},
    ]


def test_action_versions_and_label_series_fail_closed():
    fixture = _fixture()
    with pytest.raises(SplitQuarantineError, match="ambiguous_split_action_versions"):
        reconstruct_unadjusted_bars(fixture["bars"], [*fixture["actions"], *fixture["actions"]])
    with pytest.raises(PriceSeriesError, match="wrong_entry_label_price_series"):
        label_split_normalized_return(
            security_id="fixture",
            entry_point={"security_id": "fixture", "series": "asof_split_adjusted_v1", "price": 100},
            exit_point={"security_id": "fixture", "series": "reconstructed_unadjusted_v1", "price": 50},
            entry_at=datetime(2020, 1, 2, 14, 30, tzinfo=timezone.utc),
            exit_at=datetime(2020, 1, 3, 21, tzinfo=timezone.utc),
            visible_at=datetime(2020, 1, 3, 21, 15, tzinfo=timezone.utc),
            actions=[],
        )
def test_feature_and_label_consumers_require_exact_reconstruction_actions():
    fixture = _fixture()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])
    with pytest.raises(PriceSeriesError, match="wrong_reconstructed_action_set"):
        asof_split_adjusted_bars(
            rebuilt, [], as_of=datetime(2020, 9, 1, 20, 15, tzinfo=timezone.utc)
        )
def test_fixed_lag_sensitivity_counts_ex_date_exposures_as_quarantined():
    applied = _action()
    exposures = [{
        "window_id": "w1", "security_id": applied["security_id"],
        "start": "2020-08-28", "end": "2020-09-02", "state": "held",
    }]
    assert quarantined_exposure_counts(
        [applied], exposures, registered_windows=("w1",),
        knowledge_policy=SPLIT_KNOWLEDGE_SENSITIVITY,
    )[0]["held"] == 1


def test_p15_adapter_blocks_quarantined_exposure_before_price_inputs():
    fixture = _fixture()
    bad = _action(outcome="superseded_by_refetch")
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], [])
    exposure = {
        "window_id": "w1", "security_id": bad["security_id"],
        "start": "2020-08-28", "end": "2020-09-02", "state": "held",
    }
    with pytest.raises(SplitQuarantineError, match="p15_replay_exposure_quarantined"):
        prepare_p15_price_inputs(
            rebuilt, [bad], [exposure],
            as_of=datetime(2020, 9, 2, 20, 15, tzinfo=timezone.utc),
            registered_windows=("w1",),
        )


def test_every_price_consumer_has_one_registered_series():
    contract = mandatory_acceptance_contract()
    assert contract["split_knowledge"] == {
        "primary": "registered_ex_date_open_v1",
        "sensitivity": "registered_one_session_after_ex_date_v1",
        "primary_is_measured_history": False,
        "sensitivity_lag_sessions": 1,
    }
    assert contract["held_split_quarantine_estimate"] == {
        "unit": "held_or_pending_action_exposures_per_registered_window",
        "method": "potential_exposure_intersection_then_actual_replay_counts_v1",
        "zero_count_windows_required": True,
        "status": "blocked_until_frozen_archive_preflight",
    }
    assert contract["price_series_by_consumer"] == PRICE_SERIES_BY_CONSUMER
    assert set(PRICE_SERIES_BY_CONSUMER) == {
        "archive_validation",
        "atr14",
        "daily_return",
        "relative_strength",
        "screen_253",
        "absolute_return_guard",
        "median_dollar_volume",
        "p15_universe",
        "position_sizing",
        "open_execution",
        "close_stops_and_marks",
        "asset_label",
        "spy_label",
        "source_provenance",
    }
    with pytest.raises(PriceSeriesError, match="unregistered_price_consumer"):
        consumer_price_series("implicit_adjusted_close")
