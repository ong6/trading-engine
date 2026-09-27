from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from farm.p16_sequential import (
    ALPHA,
    ALPHA_ALLOCATION_ID,
    FAMILY_ALPHA,
    FUTURE_FAMILY_ALPHA_RESERVE,
    by_session_offset,
    candidate_for_promotion,
    common_report_e_test,
    mixing_from_pre_activation,
    mixture_test,
)
from sim import nyse

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
REPORT = datetime(2027, 1, 1, tzinfo=timezone.utc)
EPOCH = date(2026, 9, 1)


def _mixture(count=0):
    values = [0.1 + index / 1000 for index in range(count)]
    return mixing_from_pre_activation(values, [f"origin-{index}" for index in range(count)])


def _rows(count=31):
    rows, day = [], EPOCH
    for index in range(count):
        decided = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        rows.append({"session_index": index, "market_date": day.isoformat(),
                     "status": "scored", "delta_ic": 0.5,
                     "input_sha256": f"{index:064x}", "decided_at": decided.isoformat(),
                     "forward_entry_at": (decided + timedelta(days=1)).isoformat(),
                     "labels_available_at": (decided + timedelta(days=7)).isoformat()})
        day = nyse.next_session(day)
    return rows


def _offset(rows):
    return by_session_offset(
        rows, mixture=_mixture(), epoch_session=EPOCH, report_at=REPORT.isoformat())


def _family_row(comparison_id, current, maximum, **changes):
    row = {"comparison_id": comparison_id, "report_at": NOW.isoformat(),
           "origin_endpoint": 100, "log_e": np.log(current), "max_log_e": np.log(maximum),
           "evidence_class": "prospective", "identity_complete": True,
           "inventory_complete": True, "prefix_complete": True,
           "dsr_probability": 0.96, "mean_neutral_ic": 0.01, "mean_champion_ic": 0.02}
    return row | changes


def test_calibration_uses_registered_fallback_until_twenty_distinct_origins():
    fallback = _mixture(19)
    assert fallback["prior_source"] == "registered_fallback"
    assert fallback["scale_sd"] == 0.15 and fallback["grid_points"] == 21
    assert fallback["cap_mass"] == pytest.approx(13 / 21)
    measured = _mixture(20)
    assert measured["prior_source"] == "preactivation_paired_d"
    assert measured["scale_sd"] == 0.01
    with pytest.raises(ValueError, match="origins"):
        mixing_from_pre_activation([0.1] * 20, ["same"] * 20)


def test_one_observation_matches_the_registered_discrete_mixture():
    mixture = _mixture()
    result = mixture_test([2], mixture=mixture)
    expected = sum(weight * (1 + 2 * bet) for weight, bet in
                   zip(mixture["weights"], mixture["lambdas"], strict=True))
    assert np.exp(result["log_e"]) == pytest.approx(expected)
    assert result["component_log_wealth"] == pytest.approx(
        np.log1p(2 * np.asarray(mixture["lambdas"])))


def test_wrong_direction_cannot_pass_and_crossings_are_retained():
    mixture = _mixture()
    assert not mixture_test([-0.5] * 200, mixture=mixture)["unadjusted_crossing"]
    passed = mixture_test([0.5] * 100, mixture=mixture)
    reversed_later = mixture_test([0.5] * 100 + [-2] * 200, mixture=mixture)
    assert passed["unadjusted_crossing"] and reversed_later["unadjusted_crossing"]
    assert reversed_later["first_crossing_index"] == passed["first_crossing_index"]
    assert reversed_later["max_log_e"] == pytest.approx(passed["max_log_e"])


def test_fixed_grid_skips_do_not_repack_primary_offset():
    rows = _rows()
    rows[5].update(status="decision_unavailable", reason="fewer_than_20_candidates",
                   decided_at=NOW.isoformat(),
                   forward_entry_at=(NOW + timedelta(days=1)).isoformat())
    rows[10]["status"] = "pending_label"
    report = _offset(rows)
    assert report["primary"]["consumed_session_indices"] == [0]
    assert report["primary"]["skipped_decision_indices"] == [5]
    assert report["primary"]["blocked_at"] == {"session_index": 10, "reason": "pending_label"}
    rows[10]["status"] = "scored"
    assert _offset(rows)["primary"][
        "consumed_session_indices"] == [0, 10, 15, 20, 25, 30]


def test_grid_rejects_missing_rows_and_uncertified_skips():
    with pytest.raises(ValueError, match="complete ordered"):
        _offset(_rows()[:5] + _rows()[6:])
    rows = _rows(6)
    rows[5].update(status="decision_unavailable", reason="late_label",
                   decided_at=NOW.isoformat(),
                   forward_entry_at=(NOW + timedelta(days=1)).isoformat())
    with pytest.raises(ValueError, match="registered pre-outcome"):
        _offset(rows)
    rows[5]["reason"] = "constant_scores"
    rows[5]["decided_at"] = rows[5]["forward_entry_at"]
    with pytest.raises(ValueError, match="registered pre-outcome"):
        _offset(rows)


def test_grid_binds_market_calendar_cutoff_and_input_identity():
    rows = _rows(6)
    rows[5]["market_date"] = "2026-09-12"
    with pytest.raises(ValueError, match="exchange-session"):
        _offset(rows)
    rows = _rows(6)
    rows[5]["labels_available_at"] = (REPORT + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="input identity"):
        _offset(rows)
    rows = _rows(6)
    rows[5]["input_sha256"] = "z" * 64
    with pytest.raises(ValueError, match="input identity"):
        _offset(rows)


def test_common_report_separates_current_ebh_from_lifetime_bonferroni():
    rows = [_family_row(f"c{index}", current, maximum) for index, (current, maximum) in
            enumerate(((55, 120), (55, 55), (1, 1), (1, 1)))]
    report = common_report_e_test(
        rows, [f"c{index}" for index in range(4)], NOW.isoformat(), origin_endpoint=100,
        alpha_allocation_id=ALPHA_ALLOCATION_ID,
    )
    assert report["selected"] == [True, False, False, False]
    assert report["descriptive_ebh_selected"] == [True, True, False, False]
    assert candidate_for_promotion(report, "c0")
    report["selected"] = [False, True, True, True]
    assert candidate_for_promotion(report, "c0")
    assert not candidate_for_promotion(report, "c1")


def test_negative_champion_ic_and_incomplete_inventory_never_promote():
    rows = [_family_row("negative", 100, 100, mean_champion_ic=-0.01),
            _family_row("incomplete", 100, 100, inventory_complete=False)]
    report = common_report_e_test(
        rows, ["negative", "incomplete"], NOW.isoformat(), origin_endpoint=100,
        alpha_allocation_id=ALPHA_ALLOCATION_ID,
    )
    assert report["selected"] == [False, False]
    assert not candidate_for_promotion(report, "negative")
    assert not candidate_for_promotion(report, "incomplete")


def test_common_report_rejects_wrong_level_time_family_and_maximum():
    row = _family_row("c0", 2, 2)
    with pytest.raises(ValueError, match="0.04"):
        common_report_e_test([row], ["c0"], NOW.isoformat(), origin_endpoint=100,
                             alpha_allocation_id="future-family", level=0.1)
    with pytest.raises(ValueError, match="0.04"):
        common_report_e_test([row], ["c0"], NOW.isoformat(), origin_endpoint=100,
                             alpha_allocation_id="second-family-alpha-0.05")
    with pytest.raises(ValueError, match="common report time"):
        common_report_e_test([row | {"report_at": (NOW + timedelta(days=1)).isoformat()}],
                             ["c0"], NOW.isoformat(), origin_endpoint=100,
                             alpha_allocation_id=ALPHA_ALLOCATION_ID)
    with pytest.raises(ValueError, match="timestamp"):
        common_report_e_test([row], ["c0"], "not-a-time", origin_endpoint=100,
                             alpha_allocation_id=ALPHA_ALLOCATION_ID)
    with pytest.raises(ValueError, match="registered family"):
        common_report_e_test([row], ["c0", "missing"], NOW.isoformat(), origin_endpoint=100,
                             alpha_allocation_id=ALPHA_ALLOCATION_ID)
    row["max_log_e"] = -1
    with pytest.raises(ValueError, match="running-maximum"):
        common_report_e_test([row], ["c0"], NOW.isoformat(), origin_endpoint=100,
                             alpha_allocation_id=ALPHA_ALLOCATION_ID)


def test_candidate_revalidates_family_allocation_identity():
    report = common_report_e_test(
        [_family_row("c0", 100, 100)], ["c0"], NOW.isoformat(), origin_endpoint=100,
        alpha_allocation_id=ALPHA_ALLOCATION_ID)
    report["alpha_allocation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="allocation differs"):
        candidate_for_promotion(report, "c0")
    report["alpha_allocation_id"] = "another-family"
    with pytest.raises(ValueError, match="registered lifetime"):
        candidate_for_promotion(report, "c0")


def test_bounded_null_simulation_counts_any_crossing():
    rng, mixture = np.random.default_rng(162026), _mixture()
    shocks = rng.choice([-2.0, 2.0], size=(1000, 200))
    hits = [mixture_test(path, mixture=mixture)["unadjusted_crossing"] for path in shocks]
    assert np.mean(hits) < ALPHA


def test_fixed_family_uses_point_zero_four_and_reserves_point_zero_one():
    ids = [f"c{index}" for index in range(8)]
    rows = [_family_row(item, 1, 200 if index == 0 else 1)
            for index, item in enumerate(ids)]
    report = common_report_e_test(
        rows, ids, NOW.isoformat(), origin_endpoint=100,
        alpha_allocation_id=ALPHA_ALLOCATION_ID,
    )
    assert FAMILY_ALPHA == 0.04 and FUTURE_FAMILY_ALPHA_RESERVE == 0.01
    assert FAMILY_ALPHA + FUTURE_FAMILY_ALPHA_RESERVE == ALPHA
    assert report["log_threshold"] == pytest.approx(np.log(200))
    assert report["selected"] == [True, False, False, False, False, False, False, False]


def test_invalid_bounds_and_mixture_are_rejected():
    mixture = _mixture()
    with pytest.raises(ValueError, match="inside"):
        mixture_test([2.01], mixture=mixture)
    with pytest.raises(ValueError, match="mixture"):
        mixture_test([0], mixture={"lambdas": [0.5], "weights": [1]})
    mixture = _mixture()
    mixture["lambdas"][0] /= 2
    with pytest.raises(ValueError, match="mixture"):
        mixture_test([0], mixture=mixture)
