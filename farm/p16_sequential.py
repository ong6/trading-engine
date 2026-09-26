"""One-sided bounded mixture sequential test for paired IC differences.

For D in [-2,2] and each frozen bet lambda in [0,.5), 1+lambda*D
is nonnegative and has conditional expectation <=1 under E[D|past]<=0.
A fixed positive mixture of their product processes is a test supermartingale;
Ville's inequality gives the .05 anytime crossing bound. Nonoverlap alone does
not prove the conditional-mean null, and this is not a Gaussian plug-in test.
"""
from __future__ import annotations

import math

import numpy as np

ALPHA = 0.05
OFFSETS = 5
GRID_POINTS = 64
NULL = "conditional_mean_paired_ic_difference_nonpositive"


def _prior(mixing_variance: float) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(mixing_variance, bool) or not math.isfinite(mixing_variance) or mixing_variance <= 0:
        raise ValueError("mixing variance must be positive, finite and frozen before labels")
    bets = (np.arange(GRID_POINTS) + 0.5) / (2 * GRID_POINTS)
    squared = bets * bets
    with np.errstate(over="ignore"):
        log_weights = -(squared - squared.min()) / (2 * mixing_variance)
    log_weights -= np.log(np.exp(log_weights).sum())
    return bets, log_weights


def mixture_test(differences, *, mixing_variance: float) -> dict:
    """Evaluate one fixed chronological prefix with a discrete half-normal bet prior.

    The variance controls the prior on bets, not an estimated null noise variance.
    The runner must retain its preactivation calibration source and freeze it.
    """
    bets, prior = _prior(mixing_variance)
    values = np.asarray(differences, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(np.abs(values) > 2):
        raise ValueError("paired IC differences must be finite and inside [-2,2]")
    components = np.zeros(GRID_POINTS)
    maximum = current = 0.0
    first_crossing = None
    for index, value in enumerate(values):
        components += np.log1p(bets * value)
        terms = prior + components
        largest = float(terms.max())
        current = largest + math.log(float(np.exp(terms - largest).sum()))
        maximum = max(maximum, current)
        if first_crossing is None and maximum >= -math.log(ALPHA):
            first_crossing = index
    return {"method": "bounded_betting_mixture", "null": NULL, "alpha": ALPHA,
            "mixing_variance": mixing_variance, "grid_points": GRID_POINTS,
            "observations": len(values), "log_e_value": current,
            "max_log_e_value": maximum, "log_anytime_p_bound": -maximum,
            "rejected": first_crossing is not None, "first_crossing_index": first_crossing,
            "status": "rejected" if first_crossing is not None else "collecting"}


def by_session_offset(records: list[dict], *, mixing_variance: float) -> dict:
    """Use frozen exchange-session indices; missing dates never renumber offsets.

    A pending/invalid outcome blocks later consumption in that offset. Only
    decision_unavailable (known before outcomes) may be skipped. Its provenance
    is checked by the runner; future label absence is not such a decision.
    """
    indices = [row["session_index"] for row in records]
    if any(type(index) is not int or index < 0 for index in indices) or len(set(indices)) != len(indices):
        raise ValueError("session indices must be unique nonnegative exchange indices")
    by_index = {row["session_index"]: row for row in records}
    results = []
    for offset in range(OFFSETS):
        prefix, consumed, skipped, blocked = [], [], [], None
        for index in range(offset, max(indices, default=-1) + 1, OFFSETS):
            row = by_index.get(index)
            if row is None:
                blocked = {"session_index": index, "reason": "missing_session_record"}
                break
            if row["status"] == "decision_unavailable":
                skipped.append(row["session_index"])
                continue
            if row["status"] != "scored":
                blocked = {"session_index": row["session_index"], "reason": row["status"]}
                break
            prefix.append(row["delta_ic"])
            consumed.append(row["session_index"])
        result = mixture_test(prefix, mixing_variance=mixing_variance)
        crossing = result.pop("first_crossing_index")
        result.update(offset=offset, consumed_session_indices=consumed,
                      skipped_decision_indices=skipped, blocked_at=blocked,
                      first_crossing_session_index=None if crossing is None else consumed[crossing],
                      primary=offset == 0)
        results.append(result)
    return {"primary": results[0], "robustness": results[1:],
            "robustness_is_gating": False, "execution_authority": "none"}
