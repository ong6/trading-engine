import numpy as np
import pytest

from farm.p16_statistics import (
    deflated_sharpe,
    expected_max_sharpe,
    implied_active_weights,
    neutralize,
    paired_ic,
    transfer_coefficient,
)


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


def test_symmetric_sharpe_has_known_probability_and_pearson_kurtosis():
    result = deflated_sharpe([-1, 1] * 30, trials=1, trial_sharpe_variance=None,
                             min_observations=60)
    assert result["status"] == "available"
    assert result["sharpe"] == 0 and result["sr0"] == 0 and result["skew"] == 0
    assert result["pearson_kurtosis"] == 1 and result["probability"] == 0.5
    deflated = deflated_sharpe([-1, 1] * 30, trials=10, trial_sharpe_variance=0.02,
                               min_observations=60)
    assert deflated["probability"] < 0.5 and deflated["sr0"] > 0
    assert expected_max_sharpe(20, 0.02) > expected_max_sharpe(10, 0.02)


def test_dsr_never_invents_trial_dispersion_or_deletes_bad_returns():
    assert deflated_sharpe([1, 2, 3], trials=1, trial_sharpe_variance=None,
                           min_observations=4)["status"] == "insufficient"
    assert deflated_sharpe([-1, 1] * 30, trials=10, trial_sharpe_variance=None,
                           min_observations=60)["status"] == "dispersion_unavailable"
    assert deflated_sharpe([1] * 60, trials=1, trial_sharpe_variance=None,
                           min_observations=60)["status"] == "zero_variance"
    with pytest.raises(ValueError, match="nonfinite"):
        deflated_sharpe([1, 2, 3, np.nan], trials=1, trial_sharpe_variance=None,
                        min_observations=4)


def test_asymmetric_sharpe_matches_hand_computed_four_moments():
    # Mean=1/3, m2=8/9, m3=11/27, m4=50/27; s^2=160/177 for n=60.
    result = deflated_sharpe([-1, 0, 0, 0, 1, 2] * 10, trials=1,
                             trial_sharpe_variance=None, min_observations=60)
    assert result["sharpe"] == pytest.approx(0.35059473279937714)
    assert result["skew"] == pytest.approx(0.4861359120657514)
    assert result["pearson_kurtosis"] == pytest.approx(2.34375)
    assert result["probability"] == pytest.approx(0.9980475728264107)


def test_transfer_coefficient_includes_the_core_and_does_not_invent_zero_risk():
    weights = implied_active_weights([1, 2, 3], [0.1, 0.2, 0.3], positive_ic=True)
    assert len(weights) == 4 and sum(weights) == pytest.approx(0)
    assert transfer_coefficient(weights, np.array(weights) * 0.05) == pytest.approx(1)
    assert transfer_coefficient(weights, -np.array(weights)) == pytest.approx(-1)
    assert transfer_coefficient([0, 0, 0], [0, 0, 0]) is None
    assert implied_active_weights([1, 2, 3], [0.1, 0.2, 0.3], positive_ic=False) == [0] * 4
