"""Point-in-time active risk and Grinold alpha inputs for P16 construction."""
from __future__ import annotations

import numpy as np

CALIBRATION_IC = 0.03


def ledoit_wolf(returns) -> dict:
    """Scaled-identity Ledoit--Wolf covariance with the registered MLE convention."""
    values = np.asarray(returns, dtype=float)
    if (values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 1
            or not np.all(np.isfinite(values))):
        raise ValueError("complete finite return matrix required")
    centered = values - values.mean(axis=0)
    observations, names = centered.shape
    sample = centered.T @ centered / observations
    mean_variance = float(np.trace(sample) / names)
    target = mean_variance * np.eye(names)
    delta = float(np.sum((sample - target) ** 2) / names)
    beta = max(0.0, float(
        np.mean(np.sum(centered * centered, axis=1) ** 2) - np.sum(sample * sample)
    ) / (names * observations))
    shrinkage = 1.0 if delta <= 1e-30 else min(1.0, beta / delta)
    covariance = (1 - shrinkage) * sample + shrinkage * target
    return {
        "covariance": (covariance + covariance.T) / 2,
        "shrinkage": shrinkage,
        "sample": sample,
        "target": target,
    }


def risk_and_alpha(stock_returns, spy_returns, scores, trailing_ics) -> dict:
    """Build 5-session alpha and covariance from exact 120/60-session inputs."""
    stocks = np.asarray(stock_returns, dtype=float)
    spy = np.asarray(spy_returns, dtype=float)
    score = np.asarray(scores, dtype=float)
    ics = np.asarray(trailing_ics, dtype=float)
    if (stocks.ndim != 2 or stocks.shape[0] != 120 or spy.shape != (120,)
            or score.shape != (stocks.shape[1],) or ics.shape != (60,)):
        raise ValueError("need complete 120 return sessions and 60 mature ICs")
    if (not all(np.all(np.isfinite(value)) for value in (stocks, spy, score, ics))
            or np.any(np.abs(ics) > 1)):
        raise ValueError("nonfinite or invalid risk input")
    spy_centered = spy[-60:] - spy[-60:].mean()
    spy_variance_sum = float(spy_centered @ spy_centered)
    if spy_variance_sum <= 1e-16:
        raise ValueError("degenerate SPY risk history")
    stock_centered = stocks[-60:] - stocks[-60:].mean(axis=0)
    beta = spy_centered @ stock_centered / spy_variance_sum
    residual = stock_centered - spy_centered[:, None] * beta
    residual_volatility = np.sqrt(np.sum(residual**2, axis=0) / 58)
    active_returns = stocks - spy[:, None]
    active_volatility = np.std(active_returns[-60:], axis=0, ddof=1)
    score_sd = float(score.std(ddof=0))
    z_score = ((score - score.mean()) / score_sd
               if score_sd > 1e-12 else np.zeros_like(score))
    ic = max(0.0, float(ics.mean()))
    alpha_h5 = ic * np.sqrt(5) * active_volatility * z_score
    estimate = ledoit_wolf(active_returns)
    return {
        "alpha_h5": alpha_h5,
        "beta": beta,
        "active_volatility_60": active_volatility,
        "residual_volatility_60": residual_volatility,
        "z_score": z_score,
        "ic": ic,
        "covariance_h5": 5 * estimate["covariance"],
        "shrinkage": estimate["shrinkage"],
    }


def calibration_risk_and_alpha(stock_returns, spy_returns, scores, *, assumed_ic=CALIBRATION_IC):
    """Build preactivation inputs from the registered IC assumption, not evidence."""
    if (not isinstance(assumed_ic, (int, float)) or isinstance(assumed_ic, bool)
            or not np.isfinite(assumed_ic) or not 0 < assumed_ic <= 1):
        raise ValueError("positive registered calibration IC required")
    result = risk_and_alpha(stock_returns, spy_returns, scores, np.full(60, assumed_ic))
    result.update(
        ic_source="registered_assumption", observed_ic_count=0,
        assumed_ic=float(assumed_ic),
    )
    return result
