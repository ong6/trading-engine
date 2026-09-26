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
              "control_ic": None, "delta_ic": None, "reason": "fewer_than_minimum_pairs"}
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


def deflated_sharpe(returns, *, trials: int, trial_sharpe_variance: float | None,
                    min_observations: int) -> dict:
    """Use unannualised, comparable, nonoverlapping h5 returns and all-plans N.

    The caller supplies the frozen minimum and comparable cross-trial variance;
    neither is inferred from the candidate's favourable outcome or its own variance.
    """
    series = _vector(returns)
    if not np.all(np.isfinite(series)):
        raise ValueError("nonfinite DSR return; do not silently remove periods")
    if type(min_observations) is not int or min_observations < 4:
        raise ValueError("DSR minimum must be a registered integer of at least four")
    expected_max_sharpe(trials, 0.0 if trial_sharpe_variance is None else trial_sharpe_variance)
    result = {"status": "insufficient", "observations": len(series), "trials": trials,
              "probability": None, "sharpe": None, "sr0": None,
              "skew": None, "pearson_kurtosis": None,
              "method": "bailey_lopez_de_prado_approximation",
              "minimum_observations": min_observations}
    if len(series) < min_observations:
        return result
    if trials > 1 and (trial_sharpe_variance is None or trial_sharpe_variance <= 0):
        result["status"] = "dispersion_unavailable"
        return result
    benchmark = expected_max_sharpe(trials, trial_sharpe_variance or 0.0)
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


def transfer_coefficient(implied_active, actual_active) -> float | None:
    """Pearson correlation of aligned active weights, including core and cash."""
    left, right = map(_vector, (implied_active, actual_active))
    if left.shape != right.shape or not all(np.all(np.isfinite(v)) for v in (left, right)):
        raise ValueError("unaligned or nonfinite active weights")
    if len(left) < 2:
        return None
    left, right = left - left.mean(), right - right.mean()
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    return None if denominator <= 1e-15 else float(np.clip(left @ right / denominator, -1, 1))
