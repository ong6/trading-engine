"""Chronological, non-activating calibration report for P16 opening measurements."""
from __future__ import annotations

import math
import statistics
from collections import Counter

import numpy as np

from engine.lib.provenance import canonical_sha256
from sim import execution

POLICY_ID = "p16-fills-v1"
TIERS = ("lt_5m", "5m_20m", "20m_50m", "gte_50m")
TRAIN_MIN_ROWS = 100
TRAIN_MIN_SESSIONS = 20
VALIDATION_MIN_ROWS = 40
VALIDATION_MIN_SESSIONS = 10
ADVERSE_QUANTILE = 0.75


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _quantile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), q, method="linear"))


def _errors(actual: list[float], estimate: float, comparator: float) -> dict:
    candidate = [estimate - value for value in actual]
    baseline = [comparator - value for value in actual]
    return {
        "count": len(actual), "estimate_bp": estimate, "comparator_bp": comparator,
        "mae_bp": statistics.mean(abs(value) for value in candidate),
        "comparator_mae_bp": statistics.mean(abs(value) for value in baseline),
        "signed_bias_bp": statistics.mean(candidate),
        "p90_absolute_error_bp": _quantile([abs(value) for value in candidate], 0.9),
    }


def _passes(errors: dict, *, bias: float, p90: float) -> bool:
    comparison = errors["comparator_mae_bp"]
    mae_ok = errors["mae_bp"] == 0 if comparison == 0 else errors["mae_bp"] <= 1.1 * comparison
    return bool(mae_ok and abs(errors["signed_bias_bp"]) <= bias
                and errors["p90_absolute_error_bp"] <= p90)


def _rows_for(observations: list[dict], sessions: set[str], tier: str) -> list[dict]:
    result = []
    for row in observations:
        if (row.get("session_date") not in sessions or row.get("liquidity_tier") != tier
                or row.get("sample_id") != "p16-fills-v1:sample:1"):
            continue
        result.append(row)
    return result


def _coverage(rows: list[dict], field: str) -> float:
    return 0.0 if not rows else sum(_finite(row.get(field)) is not None for row in rows) / len(rows)


def _component_support(rows: list[dict], field: str, minimum_rows: int,
                       minimum_sessions: int) -> bool:
    usable = [row for row in rows if _finite(row.get(field)) is not None]
    return len(usable) >= minimum_rows and len({row["session_date"] for row in usable}) \
        >= minimum_sessions


def _tier_report(tier: str, train: list[dict], validation: list[dict]) -> dict:
    v4_spread = {"lt_5m": 25.0, "5m_20m": 15.0,
                 "20m_50m": 10.0, "gte_50m": 5.0}[tier]
    quote_supported = _component_support(
        train, "quote_target_bp", TRAIN_MIN_ROWS, TRAIN_MIN_SESSIONS)
    quote_validation = _component_support(
        validation, "quote_target_bp", VALIDATION_MIN_ROWS, VALIDATION_MIN_SESSIONS)
    vwap_supported = _component_support(
        train, "vwap_gap_bp", TRAIN_MIN_ROWS, TRAIN_MIN_SESSIONS)
    vwap_validation = _component_support(
        validation, "vwap_gap_bp", VALIDATION_MIN_ROWS, VALIDATION_MIN_SESSIONS)
    quote_estimate = None
    quote_errors = None
    if quote_supported:
        quote_estimate = statistics.median(
            _finite(row["quote_target_bp"]) for row in train
            if _finite(row.get("quote_target_bp")) is not None)
    if quote_estimate is not None and quote_validation:
        quote_actual = [_finite(row["quote_target_bp"]) for row in validation
                        if _finite(row.get("quote_target_bp")) is not None]
        quote_errors = _errors(quote_actual, quote_estimate, v4_spread)
        quote_errors["passes"] = _passes(quote_errors, bias=2.0, p90=10.0)
    adverse = {}
    for side, sign in (("buy", 1), ("sell", -1)):
        estimate, errors = None, None
        if vwap_supported:
            values = [max(0.0, sign * _finite(row["vwap_gap_bp"])) for row in train
                      if _finite(row.get("vwap_gap_bp")) is not None]
            estimate = _quantile(values, ADVERSE_QUANTILE)
        if estimate is not None and vwap_validation:
            actual = [max(0.0, sign * _finite(row["vwap_gap_bp"]))
                      for row in validation if _finite(row.get("vwap_gap_bp")) is not None]
            errors = _errors(actual, estimate, 5.0)
            errors["passes"] = _passes(errors, bias=10.0, p90=50.0)
        adverse[side] = {"estimate_bp": estimate, "validation": errors}
    proxy_train = [row for row in train
                   if _finite(row.get("half_range_proxy_bp")) is not None
                   and _finite(row.get("hlc3_gap_bp")) is not None]
    proxy = {
        "status": "insufficient_data" if not proxy_train else "available",
        "half_range_stress_bp": None if not proxy_train else max(
            v4_spread, statistics.median(row["half_range_proxy_bp"] for row in proxy_train)),
        "adverse_stress_bp": None if not proxy_train else max(
            5.0, _quantile([max(0.0, row["hlc3_gap_bp"]) for row in proxy_train],
                           ADVERSE_QUANTILE)),
        "v5_activation_eligible": False,
    }
    missing = Counter(
        reason for row in [*train, *validation] for reason in row.get("missing_reasons", []))
    supported = bool(
        quote_errors and quote_errors["passes"]
        and all(item["validation"] and item["validation"]["passes"]
                for item in adverse.values())
        and _coverage([*train, *validation], "half_range_proxy_bp") >= 0.8
        and _coverage([*train, *validation], "quote_target_bp") >= 0.8
        and _coverage([*train, *validation], "vwap_gap_bp") >= 0.8)
    return {
        "liquidity_tier": tier, "training_rows": len(train),
        "training_sessions": len({row["session_date"] for row in train}),
        "validation_rows": len(validation),
        "validation_sessions": len({row["session_date"] for row in validation}),
        "coverage": {
            "three_bar": _coverage([*train, *validation], "half_range_proxy_bp"),
            "verified_quote": _coverage([*train, *validation], "quote_target_bp"),
            "verified_vwap": _coverage([*train, *validation], "vwap_gap_bp"),
        },
        "missing_reasons": dict(sorted(missing.items())),
        "quote": {"estimate_bp": quote_estimate, "validation": quote_errors},
        "adverse_by_side": adverse, "proxy_stability": proxy,
        "status": "independent_targets_supported" if supported else
            "insufficient_data" if not (quote_supported and vwap_supported
                                         and quote_validation and vwap_validation)
            else "independent_validation_failed",
    }


def build_report(registration: dict, observations: list[dict], *, generated_at: str) -> dict:
    """Fit only on S0..S59 and evaluate frozen estimates on S60..S79."""
    sessions = registration.get("sessions")
    if (registration.get("registration_id") != POLICY_ID or not isinstance(sessions, list)
            or len(sessions) != 80 or len(set(sessions)) != 80
            or registration.get("calendar_sha256") != canonical_sha256(sessions)
            or registration.get("training_sessions") != sessions[:60]
            or registration.get("validation_sessions") != sessions[60:]):
        raise ValueError("fill calibration registration differs")
    train_dates, validation_dates = set(sessions[:60]), set(sessions[60:])
    if any(row.get("session_date") not in train_dates | validation_dates
           for row in observations):
        raise ValueError("fill calibration observation is outside the registered split")
    tiers = [_tier_report(tier, _rows_for(observations, train_dates, tier),
                          _rows_for(observations, validation_dates, tier)) for tier in TIERS]
    pairs = [abs(float(row["cross_source_open_gap_bp"])) for row in observations
             if _finite(row.get("cross_source_open_gap_bp")) is not None]
    source_screen = {
        "count": len(pairs),
        "median_absolute_gap_bp": None if not pairs else statistics.median(pairs),
        "fraction_over_100bp": None if not pairs else sum(value > 100 for value in pairs) / len(pairs),
    }
    source_screen["status"] = (
        "cross_source_unverified" if len(pairs) < 100 else
        "source_disagreement" if source_screen["median_absolute_gap_bp"] > 10
        or source_screen["fraction_over_100bp"] > 0.05 else "supported")
    statuses = {row["status"] for row in tiers}
    body = {
        "schema_version": 1, "policy_id": POLICY_ID,
        "registration_sha256": registration["registration_sha256"],
        "generated_at": generated_at, "status": "independent_targets_supported"
        if statuses == {"independent_targets_supported"} and source_screen["status"] == "supported"
        else "collecting" if "insufficient_data" in statuses else "measurement_unverified"
        if source_screen["status"] != "supported" else "independent_validation_failed",
        "adverse_estimator": "positive_side_signed_gap_quantile_0.75",
        "tiers": tiers, "source_disagreement": source_screen,
        "execution_basis": "continuous_opening_measurement_only",
        "independent_targets_verified": statuses == {"independent_targets_supported"},
        "execution_basis_verified": False, "v5_activation_eligible": False,
        "default_execution_profile": execution.DEFAULT_PROFILE_ID,
        "existing_cohorts_unchanged": True,
    }
    return {**body, "report_sha256": canonical_sha256(body)}


def markdown(report: dict) -> str:
    if report.get("report_sha256") != canonical_sha256({
            key: value for key, value in report.items() if key != "report_sha256"}):
        raise ValueError("fill calibration report identity differs")
    lines = [
        "# P16 fill calibration", "", f"Status: **{report['status']}**", "",
        "This is continuous-opening measurement only. It does not validate auction execution,",
        "does not activate fill model v5, and leaves `baseline_v1` unchanged.", "",
        "| Liquidity tier | Train | Validation | Quote | Buy adverse | Sell adverse | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    def value(item):
        return "unavailable" if item is None else f"{item:.2f} bp"
    for row in report["tiers"]:
        lines.append(
            f"| {row['liquidity_tier']} | {row['training_rows']} | "
            f"{row['validation_rows']} | {value(row['quote']['estimate_bp'])} | "
            f"{value(row['adverse_by_side']['buy']['estimate_bp'])} | "
            f"{value(row['adverse_by_side']['sell']['estimate_bp'])} | {row['status']} |")
    lines.extend([
        "", f"Cross-source check: **{report['source_disagreement']['status']}**.",
        "", "Execution basis verified: **no**. v5 activation eligible: **no**.", "",
    ])
    return "\n".join(lines)
