from datetime import date

import numpy as np
import pytest

from engine.lib.provenance import canonical_sha256
from farm.p16_statistics import (
    comparable_trial_variance,
    deflated_sharpe,
    expected_max_sharpe,
    implied_active_weights,
    neutralize,
    paired_ic,
    risk_transfer,
    top_quintile_return,
    transfer_coefficient,
    weight_pearson_tc,
)
from sim import nyse

EPOCH = date(2025, 1, 2)


def _dates(count):
    result, day = [], EPOCH
    for _ in range(count):
        result.append(day.isoformat())
        for _ in range(5):
            day = nyse.next_session(day)
    return result


def _dispersion(returns, *, status="dispersion_unavailable", count=1, variance=None):
    values = np.asarray(returns, dtype=float).tolist()
    return {"status": status, "compatible_trial_count": count,
            "trial_sharpe_variance": variance, "candidate_trial_id": "candidate",
            "candidate_return_sha256": canonical_sha256(values),
            "observation_dates": _dates(len(values)), "horizon": 5,
            "cost_basis": "h5-v1", "epoch_session": EPOCH.isoformat()}


def _dsr(returns, inventory, dispersion):
    return deflated_sharpe(
        returns, trial_inventory=inventory, dispersion=dispersion,
        candidate_trial_id="candidate", observation_dates=_dates(len(returns)),
        epoch_session=EPOCH, horizon=5, cost_basis="h5-v1")


def _factor_fixture():
    score = np.repeat(np.arange(-5, 5, dtype=float), 2)
    residual = np.ravel(np.column_stack([-np.arange(1, 11), np.arange(1, 11)]))
    factors = np.repeat(score[:, None], 6, axis=1)
    return score, 3 * score + residual, factors


def test_linear_factor_null_has_zero_residual_rank_ic_by_hand():
    score, outcomes, factors = _factor_fixture()
    fit = neutralize(outcomes, factors, [None] * 20)
    raw = paired_ic(score, -score, outcomes)
    adjusted = paired_ic(score, -score, fit["residuals"])
    # In each tied-score pair the residual ranks sum to 21, giving zero rank covariance.
    assert fit["status"] == "available" and fit["rank"] == 2 and fit["residual_df"] == 18
    assert raw["challenger_ic"] > 0.8
    assert adjusted["challenger_ic"] == pytest.approx(0, abs=1e-12)
    assert adjusted["control_ic"] == pytest.approx(0, abs=1e-12)
    assert fit["unknown_sector_count"] == 20


def test_regression_is_shared_even_when_a_policy_did_not_answer():
    score, outcomes, factors = _factor_fixture()
    # Four repeated blocks provide enough paired rows after one model fails.
    outcomes, factors, score = np.tile(outcomes, 4), np.tile(factors, (4, 1)), np.tile(score, 4)
    fit = neutralize(outcomes, factors, ["unknown"] * 80)
    partial = score.copy()
    partial[:20] = np.nan
    result = paired_ic(partial, -score, fit["residuals"])
    assert fit["fit_count"] == 80 and result["pair_count"] == 60
    assert result["excluded_count"] == 20


def test_factor_coverage_saturation_and_constant_residual_are_explicit():
    score, outcomes, factors = _factor_fixture()
    no_residual = neutralize(score, factors, [None] * 20)
    assert no_residual["reason"] == "constant_residual" and no_residual["residuals"] is None
    saturated = neutralize(outcomes, factors, [str(index) for index in range(20)])
    assert saturated["reason"] == "residual_degrees_of_freedom"
    missing = factors.copy()
    missing[:10] = np.nan
    assert neutralize(outcomes, missing, [None] * 20)["reason"] == "exposure_coverage_or_sample"
    assert paired_ic([1] * 20, score, outcomes)["reason"] == "constant_score_or_outcome"


def test_winsorization_and_constant_factor_handling_do_not_change_outcomes():
    rng = np.random.default_rng(619)
    factors = rng.normal(size=(60, 6))
    factors[:, 5] = 0
    factors[0, 0] = 1e9
    outcome = rng.normal(size=60)
    before = outcome.copy()
    fit = neutralize(outcome, factors, ["Tech"] * 30 + [None] * 30)
    assert fit["status"] == "available"
    assert fit["winsor_limits"][1][0] < 1e9
    assert fit["dropped_factors"] == ["vol60"]
    assert np.array_equal(outcome, before)


def test_ols_orthogonality_does_not_claim_rank_independence():
    score = np.repeat(np.arange(10, dtype=float), 2)
    outcomes = np.exp(score)
    factors = np.repeat(score[:, None], 6, axis=1)
    fit = neutralize(outcomes, factors, ["unknown"] * 20)
    adjusted = paired_ic(score, -score, fit["residuals"])
    assert fit["status"] == "available"
    assert adjusted["challenger_ic"] == pytest.approx(-0.32121212121212117)


def test_factor_coverage_boundary_is_exactly_eighty_percent():
    rng = np.random.default_rng(1601)
    outcomes, factors = rng.normal(size=25), rng.normal(size=(25, 6))
    factors[:5] = np.nan
    assert neutralize(outcomes, factors, ["unknown"] * 25)["status"] == "available"
    outcomes = np.r_[outcomes, 0.5]
    factors = np.vstack([factors, np.full(6, np.nan)])
    assert neutralize(outcomes, factors, ["unknown"] * 26)["status"] == "insufficient"


def test_symmetric_sharpe_has_known_probability_and_pearson_kurtosis():
    inventory = {"status": "complete", "selection_trial_count": 1,
                 "selection_trial_ids": ["candidate"], "register_sha256": "a" * 64}
    returns = [-1, 1] * 30
    unavailable = _dispersion(returns)
    result = _dsr(returns, inventory, unavailable)
    assert result["status"] == "available"
    assert result["sharpe"] == 0 and result["sr0"] == 0 and result["skew"] == 0
    assert result["pearson_kurtosis"] == 1 and result["probability"] == 0.5
    inventory["selection_trial_count"] = 10
    inventory["selection_trial_ids"] = ["candidate", *[f"trial-{index}" for index in range(9)]]
    inventory["selection_trial_ids"].sort()
    dispersion = _dispersion(returns, status="available", count=2, variance=0.02)
    deflated = _dsr(returns, inventory, dispersion)
    assert deflated["probability"] < 0.5 and deflated["sr0"] > 0
    assert expected_max_sharpe(20, 0.02) > expected_max_sharpe(10, 0.02)


def test_dsr_never_invents_trial_dispersion_or_deletes_bad_returns():
    one = {"status": "complete", "selection_trial_count": 1, "register_sha256": "a" * 64}
    one["selection_trial_ids"] = ["candidate"]
    many = one | {"selection_trial_count": 10,
                  "selection_trial_ids": sorted(
                      ["candidate", *[f"trial-{index}" for index in range(9)]])}
    assert _dsr([1, 2, 3], one, _dispersion([1, 2, 3]))["status"] == "insufficient"
    returns = [-1, 1] * 30
    assert _dsr(returns, many, _dispersion(returns))["status"] == "dispersion_unavailable"
    returns = [1] * 60
    assert _dsr(returns, one, _dispersion(returns))["status"] == "zero_variance"
    with pytest.raises(ValueError, match="nonfinite"):
        _dsr([1, 2, 3, np.nan], one, _dispersion([1, 2, 3, np.nan]))


def test_asymmetric_sharpe_matches_hand_computed_four_moments():
    # Mean=1/3, m2=8/9, m3=11/27, m4=50/27; s^2=160/177 for n=60.
    returns = [-1, 0, 0, 0, 1, 2] * 10
    result = _dsr(returns,
                   {"status": "complete", "selection_trial_count": 1,
                    "selection_trial_ids": ["candidate"],
                    "register_sha256": "a" * 64}, _dispersion(returns))
    assert result["sharpe"] == pytest.approx(0.35059473279937714)
    assert result["skew"] == pytest.approx(0.4861359120657514)
    assert result["pearson_kurtosis"] == pytest.approx(2.34375)
    assert result["probability"] == pytest.approx(0.9980475728264107)


def test_primary_transfer_is_stock_only_and_legacy_diagnostic_stays_named():
    result = transfer_coefficient([-1, 0, 1], [1, 2, 4], [1, 1, 0.75], positive_ic=True)
    assert result["status"] == "available" and result["tc_diagonal"] == pytest.approx(1)
    weights = implied_active_weights([1, 2, 3], [0.1, 0.2, 0.3], positive_ic=True)
    assert len(weights) == 4 and sum(weights) == pytest.approx(0)
    assert weight_pearson_tc(weights, np.array(weights) * 0.05) == pytest.approx(1)
    assert weight_pearson_tc(weights, -np.array(weights)) == pytest.approx(-1)
    assert weight_pearson_tc([0, 0, 0], [0, 0, 0]) is None
    assert implied_active_weights([1, 2, 3], [0.1, 0.2, 0.3], positive_ic=False) == [0] * 4
    assert transfer_coefficient([1, 2], [1, 1], [0, 0], positive_ic=True)["reason"] == (
        "constant_score_or_implemented_risk")
    assert transfer_coefficient([1, 2], [1, 1], [1, 0], positive_ic=True,
                                held_unscored_weight=0.1)["reason"] == (
        "held_name_missing_score_or_risk")
    assert risk_transfer([1, 2], [1, 2], np.eye(2)) == pytest.approx(1)


def test_top_quintile_selection_is_fixed_before_labels():
    rows = [{"ticker": f"T{index:02d}", "score": 1 if index < 5 else 0,
             "label_status": "terminal", "net_excess": index / 100,
             "uninvestable": index == 0} for index in range(20)]
    result = top_quintile_return(rows)
    assert result["status"] == "available"
    assert result["selected_tickers"] == ["T00", "T01", "T02", "T03"]
    assert result["net_excess"] == pytest.approx(0.015)
    assert result["uninvestable"] == ["T00"]
    rows[0]["label_status"] = "pending"
    rows[0]["net_excess"] = None
    pending = top_quintile_return(rows)
    assert pending["status"] == "pending" and pending["selected_tickers"] == result["selected_tickers"]


def test_comparable_trial_variance_requires_common_dates_horizon_and_cost():
    dates = _dates(5)
    rows = [
        {"trial_id": "a", "observation_dates": dates, "horizon": 5,
         "cost_basis": "h5-v1", "returns": [-1, 1, -1, 1, 0]},
        {"trial_id": "b", "observation_dates": dates, "horizon": 5,
         "cost_basis": "h5-v1", "returns": [-2, 1, -1, 2, 1]},
        {"trial_id": "wrong", "observation_dates": dates[:-1] + ["2026-12-01"],
         "horizon": 5, "cost_basis": "h5-v1", "returns": [-1, 1, -1, 1, 0]},
    ]
    result = comparable_trial_variance(rows, candidate_trial_id="a", epoch_session=EPOCH)
    assert result["status"] == "available" and result["compatible_trial_count"] == 2
    assert result["compatibility_coverage"] == pytest.approx(2 / 3)
    assert result["excluded"] == {"wrong": "incompatible_dates_horizon_or_cost"}
    with pytest.raises(ValueError, match="identities"):
        comparable_trial_variance(
            rows + [rows[0]], candidate_trial_id="a", epoch_session=EPOCH)


def test_comparable_dates_bind_offset_zero_but_allow_predictable_gaps():
    dates = _dates(3)
    sparse = [dates[0], dates[2]]
    rows = [
        {"trial_id": "a", "observation_dates": sparse, "horizon": 5,
         "cost_basis": "h5-v1", "returns": [-1, 1]},
        {"trial_id": "b", "observation_dates": sparse, "horizon": 5,
         "cost_basis": "h5-v1", "returns": [-2, 1]},
    ]
    assert comparable_trial_variance(
        rows, candidate_trial_id="a", epoch_session=EPOCH)["status"] == "available"
    shifted = nyse.next_session(EPOCH)
    with pytest.raises(ValueError, match="offset-0"):
        comparable_trial_variance(
            [row | {"observation_dates": [shifted.isoformat()]} for row in rows],
            candidate_trial_id="a", epoch_session=EPOCH)


def test_dsr_minimum_is_fixed_at_sixty_and_inventory_is_bound():
    inventory = {"status": "complete", "selection_trial_count": 2,
                 "selection_trial_ids": ["candidate", "other"],
                 "register_sha256": "a" * 64}
    returns = [-1, 1] * 29 + [1]
    dispersion = _dispersion(returns, status="available", count=2, variance=0.02)
    assert _dsr(returns, inventory, dispersion)["status"] == "insufficient"
    incomplete = inventory | {"status": "incomplete"}
    returns = [-1, 1] * 30
    assert _dsr(returns, incomplete,
                 _dispersion(returns, status="available", count=2, variance=0.02))[
                     "status"] == "inventory_incomplete"


def test_dsr_rejects_dispersion_from_a_different_candidate_stream():
    inventory = {"status": "complete", "selection_trial_count": 2,
                 "selection_trial_ids": ["candidate", "other"],
                 "register_sha256": "a" * 64}
    dispersion = _dispersion([-1, 1] * 30, status="available", count=2, variance=0.02)
    with pytest.raises(ValueError, match="differs"):
        _dsr([1, -1] * 30, inventory, dispersion)
    daily, day = [], date(2025, 1, 2)
    for _ in range(60):
        daily.append(day.isoformat())
        day = nyse.next_session(day)
    with pytest.raises(ValueError, match="offset-0"):
        deflated_sharpe(
            [-1, 1] * 30, trial_inventory=inventory, dispersion=dispersion,
            candidate_trial_id="candidate", observation_dates=daily,
            epoch_session=EPOCH, horizon=5, cost_basis="h5-v1")
    with pytest.raises(ValueError, match="canonical trial inventory"):
        _dsr([-1, 1] * 30, inventory | {
            "selection_trial_ids": ["other", "third"]}, dispersion)
