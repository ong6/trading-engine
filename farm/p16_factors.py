"""Compose immutable P16 factor-neutral IC evidence from retained snapshots."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np

from engine.lib.provenance import canonical_sha256
from engine.p16_features import EXPOSURES
from farm.p16_statistics import neutralize, paired_ic
from sim import nyse

CHAMPION = "p15-scoring-v1"
RULE = "p15_rule_control"


def _score(value: object) -> float:
    if value is None:
        return math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise ValueError("policy score is invalid")
    return float(value)


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("factor cutoff is invalid")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("factor cutoff is invalid")
    return result.astimezone(timezone.utc)


def _report(body: dict) -> dict:
    return {**body, "factor_report_sha256": canonical_sha256(body)}


def evaluate_origin(
    origin: dict, exposure_snapshot: dict, *, challenger_scores: dict | None = None,
) -> dict:
    """Fit one outcome cross-section once, then score common policy intersections."""
    if origin.get("input_snapshot_sha256") != canonical_sha256({
            key: value for key, value in origin.items() if key != "input_snapshot_sha256"}):
        raise ValueError("factor origin identity differs")
    report_cutoff = _instant(origin.get("report_cutoff")).isoformat()
    if origin.get("status") == "pending":
        return _report({
            "status": "pending", "reason": "origin_labels_unresolved",
            "market_date": origin.get("market_date"),
            "report_cutoff": report_cutoff,
            "input_snapshot_sha256": origin.get("input_snapshot_sha256"),
            "unresolved_h5_tickers": origin.get("unresolved_h5_tickers", []),
        })
    if origin.get("status") != "available" or not isinstance(origin.get("rows"), list):
        raise ValueError("factor origin is invalid")
    if exposure_snapshot.get("snapshot_sha256") != canonical_sha256({
            key: value for key, value in exposure_snapshot.items() if key != "snapshot_sha256"}):
        raise ValueError("factor exposure identity differs")
    if (exposure_snapshot.get("market_date") != origin.get("market_date")
            or _instant(exposure_snapshot.get("information_cutoff_at"))
            != _instant(origin.get("scoring_information_cutoff_at"))
            or exposure_snapshot.get("exposure_names") != list(EXPOSURES)):
        raise ValueError("factor exposure snapshot does not match scoring origin")
    rows, exposure_rows = origin["rows"], exposure_snapshot.get("candidates")
    if not isinstance(exposure_rows, list):
        raise ValueError("factor exposure candidates are invalid")
    by_ticker = {row.get("ticker"): row for row in exposure_rows}
    tickers = [row.get("ticker") for row in rows]
    if (len(by_ticker) != len(exposure_rows) or set(by_ticker) != set(tickers)
            or len(set(tickers)) != len(tickers)):
        raise ValueError("factor candidate sets differ")
    outcomes = [_score(row.get("net_excess_return")) for row in rows]
    factors, sectors, exclusions = [], [], {}
    for ticker in tickers:
        item = by_ticker[ticker]
        values = item.get("exposures", {})
        factors.append([_score(values.get(name)) for name in EXPOSURES])
        sectors.append(item.get("sector"))
        if item.get("status") != "available":
            exclusions[ticker] = list(item.get("missing_exposures", []))
    fit = neutralize(outcomes, factors, sectors)
    score_columns = {
        CHAMPION: [_score(row.get("champion_score")) for row in rows],
        RULE: [_score(row.get("rule_score")) for row in rows],
    }
    score_sources = {CHAMPION: origin["source"]["trace_sha256"],
                     RULE: origin["source"]["universe_sha256"]}
    for policy_id, item in sorted((challenger_scores or {}).items()):
        if policy_id in score_columns or not isinstance(item, dict):
            raise ValueError("challenger score identity is invalid")
        scores, source = item.get("scores"), item.get("score_snapshot_sha256")
        if not isinstance(scores, dict) or set(scores) != set(tickers) \
                or source != canonical_sha256({
                    "policy_id": policy_id, "market_date": origin["market_date"],
                    "information_cutoff_at": origin["scoring_information_cutoff_at"],
                    "scores": scores,
                }):
            raise ValueError("challenger score snapshot is incomplete")
        score_columns[policy_id] = [_score(scores[ticker]) for ticker in tickers]
        score_sources[policy_id] = source
    common_outcomes = [value if fit["fit_mask"][index] else math.nan
                       for index, value in enumerate(outcomes)]
    comparisons = {}
    for policy_id, scores in score_columns.items():
        if policy_id == RULE:
            continue
        control_id = RULE if policy_id == CHAMPION else CHAMPION
        full = paired_ic(scores, score_columns[control_id], outcomes)
        common = paired_ic(scores, score_columns[control_id], common_outcomes)
        adjusted = (
            paired_ic(scores, score_columns[control_id], fit["residuals"])
            if fit["status"] == "available" else
            {"status": "insufficient", "reason": fit["reason"], "pair_count": 0,
             "challenger_ic": None, "control_ic": None, "delta_ic": None}
        )
        comparisons[policy_id] = {
            "control_id": control_id, "full_sample_raw": full,
            "factor_common_raw": common, "factor_neutral": adjusted,
        }
    body = {
        "status": "available" if fit["status"] == "available" else "insufficient",
        "reason": fit["reason"], "market_date": origin["market_date"],
        "report_cutoff": report_cutoff,
        "input_snapshot_sha256": origin["input_snapshot_sha256"],
        "exposure_snapshot_sha256": exposure_snapshot.get("snapshot_sha256"),
        "score_snapshot_sha256": score_sources, "tickers": tickers,
        "exposure_exclusions": exclusions, "factor_fit": fit, "comparisons": comparisons,
    }
    return _report(body)


def mean_neutral_ic(
    reports: list[dict], policy_id: str, *, activation_date: date, report_cutoff: datetime,
) -> dict:
    """Equal-session mean of available adjusted ICs over one declared interval."""
    if any(row.get("factor_report_sha256") != canonical_sha256({
            key: value for key, value in row.items() if key != "factor_report_sha256"})
            for row in reports):
        raise ValueError("factor report identity differs")
    cutoff = _instant(report_cutoff.isoformat())
    cutoff_date = cutoff.date()
    scheduled, day = [], activation_date
    while day <= cutoff_date:
        if nyse.is_session(day):
            scheduled.append(day)
        day += timedelta(days=1)
    eligible = sorted((row for row in reports if activation_date <= date.fromisoformat(
        row["market_date"]) <= cutoff_date and _instant(row.get("report_cutoff")) <= cutoff),
        key=lambda row: row["market_date"])
    dates = [row["market_date"] for row in eligible]
    if len(dates) != len(set(dates)) or not set(map(date.fromisoformat, dates)) <= set(scheduled):
        raise ValueError("factor reports do not match the session grid")
    values, valid_dates = [], []
    for row in eligible:
        comparison = row.get("comparisons", {}).get(policy_id, {})
        adjusted = comparison.get("factor_neutral", {})
        if adjusted.get("status") == "scored":
            values.append(float(adjusted["challenger_ic"]))
            valid_dates.append(row["market_date"])
    status = "available" if len(values) >= 20 else "insufficient"
    return {
        "status": status, "policy_id": policy_id, "valid_session_count": len(values),
        "scheduled_session_count": len(scheduled),
        "missing_share": 1 - len(values) / len(scheduled) if scheduled else 1.0,
        "mean_neutral_ic": float(np.mean(values)) if status == "available" else None,
        "first_valid_date": valid_dates[0] if valid_dates else None,
        "last_valid_date": valid_dates[-1] if valid_dates else None,
        "activation_date": activation_date.isoformat(), "report_cutoff": cutoff.isoformat(),
        "source_report_sha256": [row.get("factor_report_sha256") for row in eligible],
    }
