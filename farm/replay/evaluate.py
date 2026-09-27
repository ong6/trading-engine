"""Registered paired replay endpoint and circular session-block uncertainty."""
from __future__ import annotations

import math
import random
from statistics import fmean
from typing import Mapping, Sequence


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_notes_endpoint(
    rows: Sequence[Mapping],
    *,
    resamples: int = 10_000,
    block_sessions: int = 5,
    seed: int = 1604,
) -> dict:
    """Evaluate notes-minus-no-notes factor-neutral h5 IC by replay session."""
    if resamples < 1 or block_sessions < 1:
        raise ValueError("invalid_replay_bootstrap")
    eligible, excluded = [], []
    for row in rows:
        try:
            notes = float(row["notes_factor_neutral_h5_ic"])
            control = float(row["control_factor_neutral_h5_ic"])
            common = int(row["common_names"])
        except (KeyError, TypeError, ValueError):
            excluded.append(str(row.get("session", "unknown")))
            continue
        if common < 10 or not math.isfinite(notes) or not math.isfinite(control):
            excluded.append(str(row.get("session", "unknown")))
            continue
        eligible.append((str(row["session"]), notes - control))
    if not eligible:
        return {
            "status": "insufficient",
            "eligible_sessions": 0,
            "excluded_sessions": excluded,
        }
    eligible.sort()
    deltas = [value for _session, value in eligible]
    block = min(block_sessions, len(deltas))
    rng, boot = random.Random(seed), []
    for _ in range(resamples):
        sampled = []
        while len(sampled) < len(deltas):
            start = rng.randrange(len(deltas))
            sampled.extend(deltas[(start + offset) % len(deltas)] for offset in range(block))
        boot.append(fmean(sampled[:len(deltas)]))
    estimate = fmean(deltas)
    lower, upper = _quantile(boot, 0.025), _quantile(boot, 0.975)
    one_sided_lower = _quantile(boot, 0.05)
    return {
        "status": "positive_evidence" if one_sided_lower > 0 else "inconclusive",
        "endpoint_id": "notes_minus_no_notes_factor_neutral_h5_ic",
        "estimate": estimate,
        "one_sided_lower_95": one_sided_lower,
        "two_sided_95": [lower, upper],
        "eligible_sessions": len(deltas),
        "excluded_sessions": excluded,
        "block_sessions": block_sessions,
        "resamples": resamples,
        "seed": seed,
    }
