"""W4 split clock, quarantine, and consumer price-series tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from farm.replay.asof import (
    ExactSplitObservations,
    LabelPricePoint,
    PriceSeriesError,
    SplitQuarantineError,
    asof_split_adjusted_bars,
    consumer_price_series,
    freeze_exact_split_observations,
    label_price_point,
    label_split_normalized_return,
    load_exact_split_observations,
    quarantined_exposure_counts,
    reconstruct_unadjusted_bars,
    record_actions_fetch_log,
    split_known_at,
    split_observation_identity,
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
from farm.replay.store import ReplayStoreError, open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "p16_replay_price_actions.json"


def _fixture():
    return json.loads(FIXTURE.read_text())


def _action(**changes):
    action = dict(_fixture()["actions"][0])
    action.update(changes)
    return action


def _observations(tmp_path, action, observed_at):
    root = tmp_path / "research"
    root.mkdir(exist_ok=True)
    path = root / "catalog.duckdb"
    with open_store(
        path, research_root=root, live_db_path=tmp_path / "live.duckdb", kind="catalog"
    ) as con:
        fetch_key = record_actions_fetch_log(
            con, receipt={
                "source": "fixture", "archive_payload_sha256": "a" * 64,
                "actions": [action],
            },
            recorded_at=datetime.fromisoformat(observed_at.replace("Z", "+00:00")),
        )
        registration = freeze_exact_split_observations(
            con, fetch_keys=(fetch_key,),
            frozen_at=datetime(2026, 9, 27, 1, tzinfo=timezone.utc),
        )
        return load_exact_split_observations(con, registration)


def test_split_knowledge_is_registered_convention_with_receipt_sensitivity(tmp_path):
    action = _action()
    assert split_known_at(action, SPLIT_KNOWLEDGE_PRIMARY) == datetime(
        2020, 8, 31, 13, 30, tzinfo=timezone.utc
    )
    assert action["retrieved_at_real"].startswith("2026-")
    assert action["known_at_replay"].startswith("2020-")
    with pytest.raises(SplitQuarantineError, match="first_seen_unavailable"):
        split_known_at(action, SPLIT_KNOWLEDGE_SENSITIVITY)
    observations = _observations(tmp_path, action, "2026-07-29T12:00:00Z")
    assert split_known_at(action, SPLIT_KNOWLEDGE_SENSITIVITY, observations) == datetime(
        2026, 7, 29, 12, tzinfo=timezone.utc
    )
    forged = _action(first_seen_at="2020-01-01T00:00:00Z", observation_sha256="f" * 64)
    with pytest.raises(SplitQuarantineError, match="first_seen_unavailable"):
        split_known_at(forged, SPLIT_KNOWLEDGE_SENSITIVITY)


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


def test_receipt_sensitivity_never_applies_before_new_york_ex_date_open(tmp_path):
    fixture = _fixture()
    action = _action()
    observations = _observations(tmp_path, action, "2026-07-29T12:00:00Z")
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], [action])
    before = asof_split_adjusted_bars(
        rebuilt, [action], as_of=datetime(2020, 8, 31, 1, tzinfo=timezone.utc),
        knowledge_policy=SPLIT_KNOWLEDGE_SENSITIVITY,
        observations=observations,
    )[0]
    assert before["close"] == pytest.approx(499.23)
    assert before["asof_action_ids"] == []


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


def test_labels_use_horizon_split_normalization_for_asset_and_spy(tmp_path):
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
    observations = _observations(tmp_path, action, "2026-07-29T12:00:00Z")
    with pytest.raises(SplitQuarantineError, match="late_split_knowledge"):
        label_split_normalized_return(
            security_id="fixture",
            **{
                **arguments, "actions": [action],
                "knowledge_policy": SPLIT_KNOWLEDGE_SENSITIVITY,
                "observations": observations,
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
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])[0]
    rebuilt["close"] *= 100
    with pytest.raises(PriceSeriesError, match="provenance"):
        label_price_point(rebuilt, "close")


def test_feature_and_label_consumers_require_exact_reconstruction_actions():
    fixture = _fixture()
    rebuilt = reconstruct_unadjusted_bars(fixture["bars"], fixture["actions"])
    with pytest.raises(PriceSeriesError, match="wrong_reconstructed_action_set"):
        asof_split_adjusted_bars(
            rebuilt, [], as_of=datetime(2020, 9, 1, 20, 15, tzinfo=timezone.utc)
        )
    tampered = [dict(rebuilt[0], close=rebuilt[0]["close"] * 100)]
    with pytest.raises(PriceSeriesError, match="tampered_reconstructed_price_series"):
        asof_split_adjusted_bars(
            tampered, fixture["actions"],
            as_of=datetime(2020, 9, 1, 20, 15, tzinfo=timezone.utc),
        )


def test_receipt_sensitivity_counts_missing_or_late_knowledge_as_quarantine():
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


def test_split_observations_and_label_points_reject_forgery_and_mutation(tmp_path):
    action = _action()
    with pytest.raises(SplitQuarantineError, match="unverified_split_observations"):
        ExactSplitObservations("a" * 64, "b" * 64, (), "c" * 64)
    observations = _observations(tmp_path, action, "2026-07-29T12:00:00Z")
    object.__setattr__(observations, "entries", (
        (split_observation_identity(action), datetime(1900, 1, 1, tzinfo=timezone.utc), "a" * 64),
    ))
    with pytest.raises(SplitQuarantineError, match="observations_tampered"):
        split_known_at(action, SPLIT_KNOWLEDGE_SENSITIVITY, observations)

    with pytest.raises(PriceSeriesError, match="unverified_label_price_point"):
        LabelPricePoint(
            "fixture", datetime(2020, 1, 2).date(),
            datetime(2020, 1, 2, 21, 15, tzinfo=timezone.utc), "open", 1.0, 1.0,
            (), "a" * 64, "b" * 64, "c" * 64,
        )
    action = _action(security_id="fixture", ex_date="2020-01-03", new_shares_per_old=2)
    bars = reconstruct_unadjusted_bars([
        {"security_id": "fixture", "session": "2020-01-02", "series": "source_back_adjusted_v1",
         "available_at": "2020-01-02T21:15:00Z", "open": 50, "high": 50, "low": 50,
         "close": 50, "volume": 10},
    ], [action])
    point = label_price_point(bars[0], "open")
    object.__setattr__(point, "price", 5000)
    with pytest.raises(PriceSeriesError, match="tampered_entry_label_price"):
        label_split_normalized_return(
            security_id="fixture", entry_point=point,
            exit_point=label_price_point(bars[0], "close"),
            entry_at=datetime(2020, 1, 2, 14, 30, tzinfo=timezone.utc),
            exit_at=datetime(2020, 1, 2, 21, tzinfo=timezone.utc),
            visible_at=datetime(2020, 1, 2, 21, 15, tzinfo=timezone.utc), actions=[],
        )


def test_split_observation_registration_seals_fetch_time_and_receipt(tmp_path):
    action = _action()
    root = tmp_path / "research"
    root.mkdir()
    path = root / "catalog.duckdb"
    with open_store(
        path, research_root=root, live_db_path=tmp_path / "live.duckdb", kind="catalog"
    ) as con:
        receipt = {
            "source": "fixture", "archive_payload_sha256": "a" * 64,
            "actions": [action],
        }
        with pytest.raises(SplitQuarantineError, match="before_collector_start"):
            record_actions_fetch_log(
                con, receipt=receipt,
                recorded_at=datetime(1900, 1, 1, tzinfo=timezone.utc),
            )
        key = record_actions_fetch_log(
            con, receipt=receipt,
            recorded_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        )
        future_key = record_actions_fetch_log(
            con, receipt={**receipt, "archive_payload_sha256": "b" * 64},
            recorded_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(SplitQuarantineError, match="after_registration"):
            freeze_exact_split_observations(
                con, fetch_keys=(future_key,),
                frozen_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            )
        registration = freeze_exact_split_observations(
            con, fetch_keys=(key,), frozen_at=datetime(2026, 9, 27, tzinfo=timezone.utc)
        )
        con.execute(
            "UPDATE w4_evidence_records SET recorded_at='1900-01-01T00:00:00Z' "
            "WHERE record_type='actions_fetch_log'"
        )
        with pytest.raises(ReplayStoreError, match="seal_verification_failed"):
            load_exact_split_observations(con, registration)


def test_every_price_consumer_has_one_registered_series():
    contract = mandatory_acceptance_contract()
    assert contract["split_knowledge"] == {
        "primary": "registered_ex_date_open_v1",
        "sensitivity": "exact_receipt_first_seen_v1",
        "primary_is_measured_history": False,
        "sensitivity_requires_exact_action_receipt": True,
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
