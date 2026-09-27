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
    label_split_normalized_return,
    quarantined_exposure_counts,
    reconstruct_unadjusted_bars,
    split_known_at,
    split_outcome,
)
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


def test_split_knowledge_is_registered_convention_with_receipt_sensitivity():
    action = _action()
    assert split_known_at(action, SPLIT_KNOWLEDGE_PRIMARY) == datetime(
        2020, 8, 31, 13, 30, tzinfo=timezone.utc
    )
    assert action["retrieved_at_real"].startswith("2026-")
    assert action["known_at_replay"].startswith("2020-")
    with pytest.raises(SplitQuarantineError, match="first_seen_unavailable"):
        split_known_at(action, SPLIT_KNOWLEDGE_SENSITIVITY)
    observed = _action(
        first_seen_at="2026-07-29T12:00:00Z", observation_sha256="a" * 64
    )
    assert split_known_at(observed, SPLIT_KNOWLEDGE_SENSITIVITY) == datetime(
        2026, 7, 29, 12, tzinfo=timezone.utc
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


@pytest.mark.parametrize("outcome", ("applied", "noop_restated"))
def test_only_explicit_trusted_split_outcomes_can_supply_a_ratio(outcome):
    assert split_outcome(_action(outcome=outcome)) == "trusted"


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
    arguments = dict(
        entry_raw=100.0,
        exit_raw=50.0,
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
    late = {**action, "first_seen_at": "2020-01-04T00:00:00Z", "observation_sha256": "b" * 64}
    with pytest.raises(SplitQuarantineError, match="late_split_knowledge"):
        label_split_normalized_return(
            security_id="fixture",
            **{**arguments, "actions": [late], "knowledge_policy": SPLIT_KNOWLEDGE_SENSITIVITY},
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
    assert quarantined_exposure_counts([bad], exposures) == [
        {"window_id": "w1", "held": 1, "pending": 1, "affected_actions": 1}
    ]


def test_every_price_consumer_has_one_registered_series():
    contract = mandatory_acceptance_contract()
    assert contract["split_knowledge"] == {
        "primary": "registered_ex_date_open_v1",
        "sensitivity": "exact_receipt_first_seen_v1",
        "primary_is_measured_history": False,
        "sensitivity_requires_exact_action_receipt": True,
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
