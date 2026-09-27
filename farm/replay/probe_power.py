"""Exact pooled operating characteristics for preflight-frozen probe sizes."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from farm.replay.registration import PROBE_EQUIVALENCE_DELTA


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _distribution(total: int, probability: float) -> np.ndarray:
    values = np.arange(total + 1)
    if probability == 0:
        result = np.zeros(total + 1)
        result[0] = 1
        return result
    if probability == 1:
        result = np.zeros(total + 1)
        result[-1] = 1
        return result
    logs = np.array([_log_comb(total, int(value)) for value in values])
    return np.exp(
        logs + values * math.log(probability) + (total - values) * math.log1p(-probability)
    )


def pooled_power(
    month_sizes: Sequence[int], baseline_n: int, baseline_p: float, historical_p: float
) -> float:
    if (
        not month_sizes
        or any(isinstance(size, bool) or size < 1 for size in month_sizes)
        or baseline_n < 1
        or not 0 <= baseline_p <= 1
        or not 0 <= historical_p <= 1
    ):
        raise ValueError("invalid_probe_power_inputs")
    total = sum(month_sizes)
    values = np.arange(total + 1)
    combinations = np.array([_log_comb(total, int(value)) for value in values])
    historical_cdf = _distribution(total, historical_p).cumsum()
    answer = 0.0
    for correct, weight in enumerate(_distribution(baseline_n, baseline_p)):
        if weight < 1e-16:
            continue
        limit = min(1.0, correct / baseline_n + PROBE_EQUIVALENCE_DELTA)
        if limit == 1:
            probability = 1.0
        elif limit == 0:
            probability = float(historical_p == 0)
        else:
            cutoff_cdf = np.exp(
                combinations
                + values * math.log(limit)
                + (total - values) * math.log1p(-limit)
            ).cumsum()
            cutoff = int(np.searchsorted(cutoff_cdf, 0.05, side="right")) - 1
            probability = float(historical_cdf[cutoff]) if cutoff >= 0 else 0.0
        answer += float(weight) * probability
    return answer


def power_preflight(
    month_sizes: Sequence[int], baseline_n: int, *, scenarios=(0.20, 0.25, 0.35, 0.50)
) -> dict:
    rows = []
    for null in scenarios:
        null_pass = pooled_power(month_sizes, baseline_n, null, null)
        contaminated_pass = pooled_power(month_sizes, baseline_n, null, min(1.0, null + 0.10))
        rows.append({
            "null": null,
            "full_window_null_pass_lower": max(0.0, null_pass - 0.05),
            "contaminated_pass_upper": contaminated_pass,
        })
    ready = all(
        row["full_window_null_pass_lower"] >= 0.90
        and row["contaminated_pass_upper"] <= 0.10
        for row in rows
    )
    return {"status": "ready" if ready else "power_insufficient", "rows": rows}
