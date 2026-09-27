"""Registered numerical and stress checks for P16 portfolio construction."""
from __future__ import annotations

import numpy as np
import pytest

from farm import p16_calibration, p16_optimizer, p16_risk
from farm.p16_projection import Constraints


def test_active_risk_uses_stock_minus_spy_sd_and_five_session_units():
    session = np.arange(120)
    spy = 0.01 * np.sin(session)
    residual = 0.01 * np.cos(3 * session)
    stocks = np.column_stack([2 * spy, spy + residual, spy - residual])

    result = p16_risk.risk_and_alpha(stocks, spy, [-1, 0, 1], [0.03] * 60)

    expected_sigma = np.std(stocks[-60:] - spy[-60:, None], axis=0, ddof=1)
    np.testing.assert_allclose(result["active_volatility_60"], expected_sigma)
    np.testing.assert_allclose(
        result["alpha_h5"], 0.03 * np.sqrt(5) * expected_sigma * result["z_score"],
    )
    assert result["residual_volatility_60"][0] < 1e-14
    assert result["active_volatility_60"][0] > 0
    assert np.linalg.eigvalsh(result["covariance_h5"]).min() >= -1e-14


def test_calibration_ic_is_an_assumption_and_negative_live_ic_produces_zero_alpha():
    rng = np.random.default_rng(17)
    spy = rng.normal(0, 0.01, 120)
    stocks = spy[:, None] + rng.normal(0, 0.02, (120, 5))
    assumed = p16_risk.calibration_risk_and_alpha(stocks, spy, np.arange(5))
    live = p16_risk.risk_and_alpha(stocks, spy, np.arange(5), [-0.03] * 60)

    assert assumed["ic_source"] == "registered_assumption"
    assert assumed["observed_ic_count"] == 0
    assert assumed["assumed_ic"] == 0.03
    assert not live["alpha_h5"].any()


def test_ledoit_wolf_scaled_identity_hand_answers_and_degenerate_case():
    result = p16_risk.ledoit_wolf([[2, 0], [-2, 0], [0, 1], [0, -1]])
    assert result["shrinkage"] == pytest.approx(17 / 18)
    np.testing.assert_allclose(
        result["covariance"], np.diag([31 / 24, 29 / 24]), atol=1e-12,
    )
    zero = p16_risk.ledoit_wolf(np.zeros((120, 4)))
    assert zero["shrinkage"] == 1 and not zero["covariance"].any()


def test_sector_fallback_caps_all_stocks_and_exact_eighty_percent_enables_groups():
    fallback = p16_optimizer.solve(
        [1] * 10, np.eye(10), [1] * 10,
        list("abcdefg") + [None] * 3, [0] * 10 + [1],
        risk_aversion=1, cost=0, band=0,
    )

    assert fallback["status"] == "converged"
    assert fallback["sector_status"] == "sector_unavailable"
    assert fallback["sector_coverage"] == pytest.approx(0.7)
    assert fallback["weights"][:-1].sum() <= 0.3 + 1e-10
    assert Constraints([1] * 5, ["a", "b", "c", "d", None]).sector_status == "available"


def test_known_optimum_band_bounds_and_zero_alpha_core():
    common = dict(
        alpha=[0.0005] * 4, covariance=np.eye(4) * 0.002,
        beta=[1] * 4, sectors=["a", "b", "c", "d"],
        previous=[0, 0, 0, 0, 1], risk_aversion=1.5, cost=0,
        band=0, horizon_sessions=5,
    )
    result = p16_optimizer.solve(**common)
    np.testing.assert_allclose(result["weights"], [1 / 12] * 4 + [2 / 3], atol=2e-7)
    assert result["tracking_error"] == pytest.approx(0.05291502622, abs=2e-6)
    assert result["relative_gradient_mapping"] <= 1e-9
    assert result["violation"] <= 1e-10

    bounded = p16_optimizer.solve(
        [1, 1], np.eye(2), [1, 1], ["a", "b"], [0, 0, 1],
        risk_aversion=1, cost=0, band=0, upper_limits=[0, 0.1],
    )
    np.testing.assert_allclose(bounded["weights"], [0, 0.1, 0.9], atol=1e-8)
    core = p16_optimizer.solve(
        [0], [[1]], [1], ["a"], [0.1, 0.9],
        risk_aversion=1, cost=1,
    )
    assert core["status"] == "zero_alpha_core"
    assert core["weights"].tolist() == [0, 1]


def test_invalid_and_nonconverged_inputs_never_return_an_executable_target():
    with pytest.raises(ValueError, match="semidefinite"):
        p16_optimizer.solve(
            [1], [[-1]], [1], ["a"], [0, 1], risk_aversion=1, cost=0,
        )
    with pytest.raises(ValueError, match="infeasible beta"):
        Constraints([1, 1], ["a", "b"], beta_bounds=(1.2, 1.3))
    result = p16_optimizer.solve(
        [0.13], [[1]], [1], ["a"], [0, 1],
        risk_aversion=1, cost=0, band=0, max_iterations=1,
    )
    assert result["status"] == "not_converged" and result["weights"] is None


def test_registered_lambda_grid_selects_shared_target_and_records_solve_time():
    assert p16_calibration.DEFAULT_LAMBDA_GRID.tolist() == pytest.approx(
        np.logspace(-1, 3, 17),
    )
    common = dict(
        alpha=[0.0005] * 4, covariance=np.eye(4) * 0.002,
        beta=[1] * 4, sectors=["a", "b", "c", "d"],
        previous=[0, 0, 0, 0, 1], cost=0, band=0, horizon_sessions=5,
    )
    result = p16_calibration.calibrate_lambda(
        [dict(common, book_id="ai"), dict(common, book_id="rule")],
        grid=[1, 1.5, 2],
    )
    assert result["status"] == "calibrated"
    assert result["selected_lambda"] == 1.5
    assert result["selected_at_grid_endpoint"] is False
    assert all(row["solve_seconds_total"] >= 0 for row in result["curve"])
    assert all(len(row["solve_timings"]) == 2 for row in result["curve"])


def test_calibration_retains_failure_and_distinguishes_incomplete(monkeypatch):
    original = p16_optimizer.solve

    def fail_one(*args, **kwargs):
        if kwargs["risk_aversion"] == 1:
            raise RuntimeError("injected numerical failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(p16_optimizer, "solve", fail_one)
    common = dict(
        alpha=[0.0005] * 4, covariance=np.eye(4) * 0.002,
        beta=[1] * 4, sectors=["a", "b", "c", "d"],
        previous=[0, 0, 0, 0, 1], cost=0, band=0, horizon_sessions=5,
    )
    result = p16_calibration.calibrate_lambda(
        [dict(common, book_id="ai"), dict(common, book_id="rule")], grid=[1, 1.5],
    )
    assert result["status"] == "calibrated" and result["selected_lambda"] == 1.5
    assert result["curve"][0]["status"] == "not_converged"
    assert len(result["curve"][0]["failures"]) == 2
    incomplete = p16_calibration.calibrate_lambda(
        [dict(common, book_id="ai")], grid=[1],
    )
    assert incomplete["status"] == "calibration_incomplete"


@pytest.mark.parametrize("seed", range(20261020, 20261044))
@pytest.mark.parametrize("cost", [0.01, 0.0005])
@pytest.mark.parametrize("risk_aversion", [0.1, 5.0, 1_000.0])
def test_adaptive_projection_full_144_case_noncore_stress(seed, cost, risk_aversion):
    """Mandatory accepted stress: 24 seeds x 2 costs x 3 lambdas, zero failures."""
    rng = np.random.default_rng(seed)
    names = 5 + seed % 7
    beta = rng.uniform(0.5, 1.6, names)
    beta[0], beta[1] = 0.7, 1.3
    common = rng.normal(0, 0.012, (120, 1))
    active = rng.normal(0, 0.012, (120, names))
    covariance = 5 * p16_risk.ledoit_wolf(common * (beta - 1) + active)["covariance"]
    previous_stock = np.full(names, 0.1 / names)
    previous = np.r_[previous_stock, 0.9]
    alpha = (2 * risk_aversion * covariance @ previous_stock
             + rng.uniform(-0.00025, 0.00025, names))

    result = p16_optimizer.solve(
        alpha, covariance, beta, [str(index % 4) for index in range(names)], previous,
        risk_aversion=risk_aversion, cost=cost, horizon_sessions=5,
    )

    assert result["status"] == "converged", (seed, cost, risk_aversion)
    assert result["relative_gradient_mapping"] <= 1e-9
    assert result["violation"] <= 1e-10
    assert np.all(result["weights"] >= 0)
    assert result["prox_cycle_budget"] >= 20_000
