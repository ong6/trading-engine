"""Versioned P16 diagnostics for P15 follow-ups; frozen P15 gates stay intact."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from engine.p15_evaluation import _logistic, spearman
from engine.p16_features import session_dates

ET = ZoneInfo("America/New_York")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("diagnostic timestamp must have an explicit timezone")
    return value.astimezone(timezone.utc)


def decision_day(observed_at: datetime):
    return _utc(observed_at).astimezone(ET).date()


def first_daily_windows(windows: list[dict]) -> list[dict]:
    """Choose the first window, including failed windows; never pick a later winner."""
    chosen = {}
    for row in sorted(windows, key=lambda item: (_utc(item["observed_at"]), item["window_id"])):
        chosen.setdefault((row["policy_id"], decision_day(row["observed_at"])), row)
    return list(chosen.values())


def _paired_errors(pairs: list[tuple[float, float, float]]) -> dict:
    count = len(pairs)
    return {"paired_count": count,
            "model_brier": sum((p - y) ** 2 for p, _, y in pairs) / count if count else None,
            "control_brier": sum((p - y) ** 2 for _, p, y in pairs) / count if count else None}


def paired_brier(rows: list[dict]) -> dict:
    """Compare probabilities on identical samples, using only then-mature labels.

    Rows are available h5 decisions with market_date, observed_at, labeled_at,
    p_outperform_5, baseline_score and net_excess_return. The logistic training
    cutoff is six exchange sessions, even when the dataset has missing dates.
    """
    climate, logistic = [], []
    if any(not math.isfinite(float(row[field])) for row in rows
           for field in ("p_outperform_5", "baseline_score", "net_excess_return")):
        raise ValueError("nonfinite diagnostic value")
    for row in rows:
        probability = float(row["p_outperform_5"])
        if not 0 <= probability <= 1:
            raise ValueError("invalid diagnostic probability")
        target = float(row["net_excess_return"] > 0)
        known = [prior for prior in rows if prior["market_date"] < row["market_date"]
                 and _utc(prior["labeled_at"]) <= _utc(row["observed_at"])]
        if known:
            base_rate = sum(prior["net_excess_return"] > 0 for prior in known) / len(known)
            climate.append((probability, base_rate, target))
        lagged_date = session_dates(row["market_date"], 7)[0]
        fit = _logistic([(float(prior["baseline_score"]), float(prior["net_excess_return"] > 0))
                         for prior in known if prior["market_date"] <= lagged_date])
        if fit is not None:
            intercept, slope, center, scale = fit
            logit = intercept + slope * (float(row["baseline_score"]) - center) / scale
            prediction = 1 / (1 + math.exp(-max(-30, min(30, logit))))
            logistic.append((probability, prediction, target))
    return {"climatology": _paired_errors(climate), "baseline_logistic": _paired_errors(logistic),
            "logistic_lag_exchange_sessions": 6}


def event_ic(rows: list[dict], *, generated_at: datetime) -> dict:
    """Exclude prior-close substitutes from next-bar IC; retain exclusion counts."""
    usable, excluded = [], {}
    cutoff = _utc(generated_at)
    if len({row["label_basis"] for row in rows}) > 1:
        raise ValueError("event label bases cannot be pooled")
    for row in rows:
        reason = None
        if _utc(row["labeled_at"]) > cutoff or _utc(row["decision_at"]) > cutoff:
            reason = "not_yet_available"
        elif row["label_basis"] == "next_bar" and (
            row["missing_bar_status"] == "missing_next_bar_last_available_close"
            or _utc(row["entry_at"]) <= _utc(row["decision_at"])
        ):
            reason = "no_later_bar"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
        else:
            # Both legs pay the same flat 20 bp; this is a descriptive label,
            # independent of the simulator's fill/cost model and execution P&L.
            values = [float(row[field]) for field in (
                "expected_excess_bp_5", "asset_return", "spy_return")]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("nonfinite event value")
            usable.append((values[0], values[1] - values[2]))
    ic = spearman([row[0] for row in usable], [row[1] for row in usable]) if len(usable) >= 5 else None
    return {"status": "available" if ic is not None else "insufficient",
            "label_count": len(usable), "excluded_counts": excluded, "ic": ic,
            "cost_basis": "flat_20bp_both_legs", "execution_authority": "none"}


def book_comparison_status(primary_status: str, *, eligible: bool, final_look: bool) -> str:
    if primary_status == "kill":
        return "killed"
    return "ready" if eligible else "inconclusive" if final_look else "collecting"
