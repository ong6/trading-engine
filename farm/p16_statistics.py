"""P16 factor adjustment, trial deflation, and transfer diagnostics.

These functions do not modify P15's test or grant trading authority. DSR is the
Bailey--Lopez de Prado approximation, not an always-valid probability guarantee.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from engine.p15_evaluation import spearman
from engine.p16_features import EXPOSURES


def _vector(values) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1:
        raise ValueError("expected a vector")
    return result


def neutralize(outcomes, exposures, sectors, *, min_pairs=20, min_df=10,
               min_coverage=0.8) -> dict:
    """Fit all labelled factor rows, independently of any policy's response mask."""
    y, x = _vector(outcomes), np.asarray(exposures, dtype=float)
    if x.shape != (len(y), len(EXPOSURES)) or len(sectors) != len(y):
        raise ValueError("unaligned factor inputs")
    if min_pairs < 2 or min_df < 1 or not 0 < min_coverage <= 1:
        raise ValueError("invalid factor eligibility settings")
    labels = np.isfinite(y)
    fit = labels & np.all(np.isfinite(x), axis=1)
    n, labelled = int(fit.sum()), int(labels.sum())
    result = {"status": "insufficient", "reason": "exposure_coverage_or_sample",
              "label_count": labelled, "fit_count": n, "fit_mask": fit.tolist(),
              "exposure_coverage": n / labelled if labelled else 0.0,
              "residuals": None, "residual_df": None, "rank": None}
    if n < min_pairs or result["exposure_coverage"] < min_coverage:
        return result
    categories = np.array([
        value.strip().lower() if isinstance(value, str) and value.strip() else "unknown"
        for value in sectors
    ])[fit]
    limits = np.quantile(x[fit], [0.01, 0.99], axis=0, method="linear")
    clipped = np.clip(x[fit], limits[0], limits[1])
    means, scales = clipped.mean(axis=0), clipped.std(axis=0, ddof=0)
    active = scales > 1e-12 * np.maximum(1, np.max(np.abs(clipped), axis=0))
    z = (clipped[:, active] - means[active]) / scales[active]
    names = sorted(set(categories))
    reference = "unknown" if "unknown" in names else names[0]
    dummy_names = [name for name in names if name != reference]
    dummies = np.column_stack([categories == name for name in dummy_names]) if dummy_names else np.empty((n, 0))
    design = np.column_stack([np.ones(n), z, dummies])
    coefficients, _, rank, singular = np.linalg.lstsq(design, y[fit], rcond=1e-10)
    residuals = y[fit] - design @ coefficients
    result.update(rank=int(rank), residual_df=n - int(rank),
                  sector_reference=reference, sectors=names,
                  unknown_sector_count=int((categories == "unknown").sum()),
                  dropped_factors=[EXPOSURES[index] for index in np.flatnonzero(~active)],
                  singular_values=singular.tolist(), winsor_limits=limits.tolist())
    if n - rank < min_df:
        result["reason"] = "residual_degrees_of_freedom"
        return result
    if np.std(residuals) <= 1e-10 * max(float(np.std(y[fit])), 1e-8):
        result["reason"] = "constant_residual"
        return result
    retained = [None] * len(y)
    for index, residual in zip(np.flatnonzero(fit), residuals, strict=True):
        retained[int(index)] = float(residual)
    result.update(status="available", reason=None, residuals=retained)
    return result


def paired_ic(challenger, control, outcomes, *, min_pairs=20) -> dict:
    """Compute both rank ICs on the same intersection; never remove one side only."""
    left, right, y = map(_vector, (challenger, control, outcomes))
    if left.shape != right.shape or left.shape != y.shape:
        raise ValueError("unaligned paired IC inputs")
    mask = np.isfinite(left) & np.isfinite(right) & np.isfinite(y)
    count = int(mask.sum())
    result = {"status": "insufficient", "pair_count": count,
              "excluded_count": len(y) - count, "challenger_ic": None,
              "control_ic": None, "delta_ic": None, "pair_mask": mask.tolist(),
              "reason": "fewer_than_minimum_pairs"}
    if count < min_pairs:
        return result
    first, second = spearman(left[mask].tolist(), y[mask].tolist()), spearman(right[mask].tolist(), y[mask].tolist())
    if first is None or second is None:
        result["reason"] = "constant_score_or_outcome"
        return result
    result.update(status="scored", reason=None, challenger_ic=first, control_ic=second,
                  delta_ic=first - second)
    return result


def expected_max_sharpe(trials: int, trial_sharpe_variance: float) -> float:
    if type(trials) is not int or trials < 1:
        raise ValueError("trial count must be a positive integer")
    if not math.isfinite(trial_sharpe_variance) or trial_sharpe_variance < 0:
        raise ValueError("invalid cross-trial Sharpe variance")
    if trials == 1:
        return 0.0
    euler, normal = 0.5772156649015329, NormalDist()
    return math.sqrt(trial_sharpe_variance) * (
        (1 - euler) * normal.inv_cdf(1 - 1 / trials)
        + euler * normal.inv_cdf(1 - 1 / (trials * math.e)))


def top_quintile_return(rows: list[dict]) -> dict:
    """Build one fixed top-quintile h5 sleeve without outcome-based reselection."""
    tickers = [row.get("ticker") for row in rows]
    if any(not isinstance(ticker, str) or not ticker for ticker in tickers) or len(set(tickers)) != len(tickers):
        raise ValueError("top-quintile candidate identities are invalid")
    scored = [row for row in rows if isinstance(row.get("score"), (int, float))
              and not isinstance(row.get("score"), bool) and math.isfinite(row["score"])]
    result = {"status": "insufficient", "eligible_count": len(rows), "scored_count": len(scored),
              "selected_count": 0, "selected_tickers": [], "net_excess": None,
              "uninvestable": [], "reason": "fewer_than_20_scored_names"}
    if len(scored) < 20:
        return result
    selected = sorted(scored, key=lambda row: (-row["score"], row["ticker"]))[:len(scored) // 5]
    result.update(selected_count=len(selected), selected_tickers=[row["ticker"] for row in selected])
    statuses = {row.get("label_status") for row in selected}
    if statuses != {"terminal"}:
        result.update(status="pending" if statuses <= {"terminal", "pending"} else "invalid",
                      reason="selected_labels_not_terminal")
        return result
    values = np.asarray([row.get("net_excess") for row in selected], dtype=float)
    if not np.all(np.isfinite(values)):
        result.update(status="invalid", reason="selected_label_nonfinite")
        return result
    result.update(status="available", reason=None, net_excess=float(values.mean()),
                  uninvestable=[row["ticker"] for row in selected if row.get("uninvestable")])
    return result


def comparable_trial_variance(rows: list[dict], *, candidate_trial_id: str) -> dict:
    """Estimate cross-trial Sharpe variance only on one exact h5/date/cost basis."""
    trial_ids = [row.get("trial_id") for row in rows]
    if any(not isinstance(item, str) or not item for item in trial_ids) or len(set(trial_ids)) != len(trial_ids):
        raise ValueError("comparable trial identities are invalid")
    matches = [row for row in rows if row.get("trial_id") == candidate_trial_id]
    if len(matches) != 1:
        raise ValueError("candidate trial is missing or duplicated")
    candidate = matches[0]
    dates = candidate.get("observation_dates")
    basis = (dates, candidate.get("horizon"), candidate.get("cost_basis"))
    if not isinstance(dates, list) or len(dates) != len(set(dates)) or basis[1] != 5:
        raise ValueError("candidate comparison basis is invalid")
    sharpes, included, excluded = [], [], {}
    for row in rows:
        row_basis = (row.get("observation_dates"), row.get("horizon"), row.get("cost_basis"))
        if row_basis != basis:
            excluded[row.get("trial_id")] = "incompatible_dates_horizon_or_cost"
            continue
        returns = _vector(row.get("returns"))
        if len(returns) != len(dates) or not np.all(np.isfinite(returns)):
            raise ValueError("comparable trial return series is invalid")
        sd = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        if sd <= 1e-15:
            excluded[row.get("trial_id")] = "zero_variance"
            continue
        sharpes.append(float(returns.mean() / sd))
        included.append(row["trial_id"])
    variance = float(np.var(sharpes, ddof=1)) if len(sharpes) >= 2 else None
    available = variance is not None and variance > 0
    return {"status": "available" if available else "dispersion_unavailable",
            "compatible_trial_count": len(sharpes), "inventory_rows": len(rows),
            "compatibility_coverage": len(sharpes) / len(rows) if rows else 0.0,
            "trial_sharpe_variance": variance if available else None,
            "compatible_trial_ids": included, "excluded": excluded,
            "observation_dates": dates, "horizon": basis[1], "cost_basis": basis[2]}


def deflated_sharpe(returns, *, trial_inventory: dict, dispersion: dict) -> dict:
    """Apply fixed-T DSR using all-plan N and compatible cross-trial dispersion."""
    series = _vector(returns)
    if not np.all(np.isfinite(series)):
        raise ValueError("nonfinite DSR return; do not silently remove periods")
    trials = trial_inventory.get("selection_trial_count")
    digest = trial_inventory.get("register_sha256")
    if (type(trials) is not int or trials < 1 or not isinstance(digest, str)
            or len(digest) != 64):
        raise ValueError("canonical trial inventory is invalid")
    variance = dispersion.get("trial_sharpe_variance")
    expected_max_sharpe(trials, 0.0 if variance is None else variance)
    result = {"status": "insufficient", "observations": len(series), "trials": trials,
              "compatible_trials": dispersion.get("compatible_trial_count"),
              "trial_sharpe_variance": variance, "register_sha256": digest,
              "probability": None, "sharpe": None, "sr0": None,
              "skew": None, "pearson_kurtosis": None,
              "method": "bailey_lopez_de_prado_approximation",
              "minimum_observations": 60}
    if trial_inventory.get("status") != "complete":
        result["status"] = "inventory_incomplete"
        return result
    if len(series) < 60:
        return result
    if trials > 1 and (dispersion.get("status") != "available" or variance is None or variance <= 0
                       or dispersion.get("compatible_trial_count", 0) < 2):
        result["status"] = "dispersion_unavailable"
        return result
    benchmark = expected_max_sharpe(trials, variance or 0.0)
    result["sr0"] = benchmark
    sd = float(np.std(series, ddof=1))
    if sd <= 1e-15:
        result["status"] = "zero_variance"
        return result
    sharpe = float(series.mean() / sd)
    centered = series - series.mean()
    variance = float(np.mean(centered**2))
    skew = float(np.mean(centered**3) / variance**1.5)
    kurtosis = float(np.mean(centered**4) / variance**2)
    denominator = 1 - skew * sharpe + (kurtosis - 1) * sharpe**2 / 4
    result.update(sharpe=sharpe, skew=skew, pearson_kurtosis=kurtosis)
    if not math.isfinite(denominator) or denominator <= 1e-12:
        result["status"] = "invalid_moment_denominator"
        return result
    statistic = (sharpe - benchmark) * math.sqrt(len(series) - 1) / math.sqrt(denominator)
    result.update(status="available", statistic=statistic, probability=NormalDist().cdf(statistic))
    return result


def implied_active_weights(scores, residual_volatility, *, positive_ic: bool) -> list[float]:
    """Signed diagnostic vector: names followed by SPY. Never an order target."""
    score, volatility = map(_vector, (scores, residual_volatility))
    if score.shape != volatility.shape or not all(np.all(np.isfinite(v)) for v in (score, volatility)):
        raise ValueError("unaligned or nonfinite transfer inputs")
    if np.any(volatility <= 1e-8):
        raise ValueError("residual risk unavailable")
    if not positive_ic or len(score) < 2 or score.std() <= 1e-12:
        return [0.0] * (len(score) + 1)
    names = (score - score.mean()) / score.std(ddof=0) / volatility
    active = np.r_[names, -names.sum()]
    return (active / np.abs(active).sum()).tolist()


def weight_pearson_tc(implied_active, actual_active) -> float | None:
    """Legacy full-instrument Pearson diagnostic, including SPY and cash."""
    left, right = map(_vector, (implied_active, actual_active))
    if left.shape != right.shape or not all(np.all(np.isfinite(v)) for v in (left, right)):
        raise ValueError("unaligned or nonfinite active weights")
    if len(left) < 2:
        return None
    left, right = left - left.mean(), right - right.mean()
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    return None if denominator <= 1e-15 else float(np.clip(left @ right / denominator, -1, 1))


def transfer_coefficient(scores, active_volatility, stock_active_weights, *,
                         positive_ic: bool, held_unscored_weight: float = 0.0) -> dict:
    """Primary stock-only diagonal-risk TC: corr(z, sigma * active weight)."""
    score, sigma, active = map(_vector, (scores, active_volatility, stock_active_weights))
    result = {"status": "unavailable", "tc_diagonal": None, "reason": None,
              "stock_count": len(score), "held_unscored_weight": held_unscored_weight}
    if (score.shape != sigma.shape or score.shape != active.shape
            or not all(np.all(np.isfinite(value)) for value in (score, sigma, active))):
        raise ValueError("unaligned or nonfinite stock transfer inputs")
    if held_unscored_weight < 0 or not math.isfinite(held_unscored_weight):
        raise ValueError("held unscored weight is invalid")
    if held_unscored_weight > 1e-15:
        result["reason"] = "held_name_missing_score_or_risk"
        return result
    if len(score) < 2:
        result["reason"] = "fewer_than_two_stocks"
        return result
    if np.any(sigma <= 0):
        result["reason"] = "nonpositive_active_volatility"
        return result
    if not positive_ic:
        result["reason"] = "nonpositive_trailing_ic"
        return result
    z = (score - score.mean()) / score.std(ddof=0) if score.std(ddof=0) > 1e-15 else score * 0
    implemented = sigma * active
    value = weight_pearson_tc(z, implemented)
    if value is None:
        result["reason"] = "constant_score_or_implemented_risk"
        return result
    result.update(status="available", tc_diagonal=value, reason=None)
    return result


def risk_transfer(alpha, active, covariance) -> float | None:
    """Optional full-covariance TC; singular matrices are unavailable."""
    alpha, active = map(_vector, (alpha, active))
    covariance = np.asarray(covariance, dtype=float)
    if (alpha.shape != active.shape or covariance.shape != (len(alpha), len(alpha))
            or not all(np.all(np.isfinite(value)) for value in (alpha, active, covariance))
            or not np.allclose(covariance, covariance.T, atol=1e-12)):
        raise ValueError("unaligned or invalid full-covariance transfer inputs")
    if np.linalg.eigvalsh(covariance).min() <= 1e-14:
        return None
    implemented, potential = float(active @ covariance @ active), float(
        alpha @ np.linalg.solve(covariance, alpha))
    if implemented <= 1e-15 or potential <= 1e-15:
        return None
    return float(np.clip(alpha @ active / math.sqrt(implemented * potential), -1, 1))
