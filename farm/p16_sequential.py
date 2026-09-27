"""Registered P16 bounded e-process and fixed-family promotion logic."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from statistics import NormalDist

import numpy as np

from engine.lib.provenance import canonical_sha256
from sim import nyse

ALPHA = 0.05
FAMILY_ALPHA = 0.04
FUTURE_FAMILY_ALPHA_RESERVE = 0.01
ALPHA_ALLOCATION_ID = "p16-challengers-f1-alpha-0.04-reserve-0.01"
FALLBACK_SD = 0.15
GRID_POINTS = 21
MIN_CALIBRATION_ORIGINS = 20
OFFSETS = 5
TARGET_OBSERVATIONS = 50
NULL = "conditional_mean_paired_ic_difference_nonpositive"
SKIP_REASONS = {"fewer_than_20_candidates", "constant_scores"}
REQUIRED_PROMOTION_CHECKS = {
    "prospective_evidence", "identity_complete", "inventory_complete", "prefix_complete",
    "dsr_probability_at_least_0_95", "mean_neutral_ic_positive", "mean_champion_ic_positive",
}


def _time(value) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("sequential timestamp is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValueError("sequential timestamp requires an explicit timezone")
    return parsed


def mixing_from_pre_activation(differences, origin_ids) -> dict:
    """Freeze the 21-atom prior from >=20 distinct origins, else use s0=.15."""
    values = np.asarray(differences, dtype=float)
    origins = list(origin_ids)
    if (values.ndim != 1 or len(values) != len(origins) or len(set(origins)) != len(origins)
            or not np.all(np.isfinite(values)) or np.any(np.abs(values) > 2)):
        raise ValueError("invalid preactivation paired-IC origins")
    measured = len(values) >= MIN_CALIBRATION_ORIGINS
    scale = max(float(np.std(values, ddof=1)), 0.01) if measured else FALLBACK_SD
    tau2 = scale * scale / TARGET_OBSERVATIONS
    normal = NormalDist()
    theta = np.array([
        math.sqrt(tau2) * normal.inv_cdf(0.5 + 0.5 * (index + 0.5) / GRID_POINTS)
        for index in range(GRID_POINTS)
    ])
    atoms = np.minimum(0.49, theta / (scale * scale))
    lambdas, counts = np.unique(atoms, return_counts=True)
    body = {
        "scale_sd": scale, "tau2": tau2, "target_observations": TARGET_OBSERVATIONS,
        "grid_points": GRID_POINTS, "lambdas": lambdas.tolist(),
        "weights": (counts / GRID_POINTS).tolist(), "origin_count": len(values),
        "origin_ids": origins if measured else [],
        "prior_source": "preactivation_paired_d" if measured else "registered_fallback",
        "cap_mass": float(np.mean(atoms == 0.49)),
    }
    return {**body, "calibration_sha256": canonical_sha256(body)}


def _mixture(mixture: dict) -> tuple[np.ndarray, np.ndarray]:
    lambdas = np.asarray(mixture.get("lambdas"), dtype=float)
    weights = np.asarray(mixture.get("weights"), dtype=float)
    if (lambdas.ndim != 1 or lambdas.shape != weights.shape or not len(lambdas)
            or not np.all(np.isfinite(lambdas)) or np.any(lambdas <= 0)
            or np.any(lambdas >= 0.5) or not np.all(np.isfinite(weights))
            or np.any(weights <= 0) or not np.isclose(weights.sum(), 1, atol=1e-12)
            or mixture.get("calibration_sha256") != canonical_sha256({
                key: value for key, value in mixture.items() if key != "calibration_sha256"})):
        raise ValueError("invalid frozen bounded mixture")
    return lambdas, weights


def mixture_test(differences, *, mixture: dict) -> dict:
    """Recompute a chronological prefix in log space, retaining sufficient state."""
    lambdas, weights = _mixture(mixture)
    values = np.asarray(differences, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(np.abs(values) > 2):
        raise ValueError("paired IC differences must be finite and inside [-2,2]")
    components = np.zeros(len(lambdas))
    path, maximum, first_crossing = [], 0.0, None
    for index, value in enumerate(values):
        components += np.log1p(lambdas * value)
        terms = np.log(weights) + components
        largest = float(terms.max())
        current = largest + math.log(float(np.exp(terms - largest).sum()))
        path.append(current)
        maximum = max(maximum, current)
        if first_crossing is None and maximum >= -math.log(ALPHA):
            first_crossing = index
    current = path[-1] if path else 0.0
    return {
        "method": "bounded_positive_tilt_mixture", "null": NULL, "alpha": ALPHA,
        "observations": len(values), "log_e": current, "max_log_e": maximum,
        "log_e_path": path, "component_log_wealth": components.tolist(),
        "always_valid_p": min(1.0, math.exp(-maximum)),
        "unadjusted_crossing": first_crossing is not None,
        "first_crossing_index": first_crossing,
        "calibration_sha256": mixture.get("calibration_sha256"),
        "input_sha256": canonical_sha256(values.tolist()),
    }


def _market_day(value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, (date, str)):
        raise ValueError("sequential market date is invalid")
    try:
        return value if isinstance(value, date) else date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("sequential market date is invalid") from exc


def by_session_offset(
    records: list[dict], *, mixture: dict, epoch_session: date, report_at: str,
) -> dict:
    """Consume a complete exchange-session grid without repacking skips or gaps."""
    report_time = _time(report_at)
    indices = [row.get("session_index") for row in records]
    if (not isinstance(epoch_session, date) or isinstance(epoch_session, datetime)
            or not nyse.is_session(epoch_session)
            or any(type(index) is not int for index in indices)
            or indices != list(range(len(indices)))):
        raise ValueError("complete ordered exchange-session grid from epoch required")
    expected, current = [], epoch_session
    for _ in records:
        expected.append(current)
        current = nyse.next_session(current)
    if [_market_day(row.get("market_date")) for row in records] != expected:
        raise ValueError("complete ordered exchange-session grid from epoch required")
    results = []
    for offset in range(OFFSETS):
        values, consumed, skipped, inputs, blocked = [], [], [], [], None
        for row in records[offset::OFFSETS]:
            index, status = row["session_index"], row.get("status")
            if status == "decision_unavailable":
                if (row.get("reason") not in SKIP_REASONS
                        or _time(row.get("decided_at")) >= _time(row.get("forward_entry_at"))):
                    raise ValueError("skip is not a registered pre-outcome decision")
                skipped.append(index)
                continue
            if status != "scored":
                blocked = {"session_index": index, "reason": status or "missing_status"}
                break
            digest = row.get("input_sha256")
            if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                    or _time(row.get("decided_at")) >= _time(row.get("forward_entry_at"))
                    or _time(row.get("labels_available_at")) > report_time):
                raise ValueError("scored origin input identity is invalid")
            values.append(row["delta_ic"])
            consumed.append(index)
            inputs.append(digest)
        result = mixture_test(values, mixture=mixture)
        crossing = result.pop("first_crossing_index")
        result.update(
            offset=offset, primary=offset == 0, consumed_session_indices=consumed,
            consumed_input_sha256s=inputs, skipped_decision_indices=skipped,
            blocked_at=blocked,
            first_crossing_session_index=None if crossing is None else consumed[crossing],
        )
        results.append(result)
    return {"epoch_session": epoch_session.isoformat(), "report_at": report_time.isoformat(),
            "primary": results[0], "robustness": results[1:],
            "robustness_is_gating": False, "execution_authority": "none"}


def _multiple(log_evalues, eligible, *, method: str, level: float) -> dict:
    values, gate = np.asarray(log_evalues, float), np.asarray(eligible, bool)
    if (values.ndim != 1 or gate.shape != values.shape or np.any(np.isnan(values))
            or np.any(np.isposinf(values))):
        raise ValueError("invalid family evidence")
    screened, size = np.where(gate, values, -np.inf), len(values)
    selected, threshold = np.zeros(size, bool), None
    if method == "lifetime_e_bonferroni":
        threshold = math.log(size / level) if size else None
        selected = screened >= threshold if size else selected
    elif method == "current_e_bh":
        order = np.argsort(-screened, kind="stable")
        passed = screened[order] >= np.log(size / (level * np.arange(1, size + 1)))
        if passed.any():
            count = int(np.flatnonzero(passed)[-1] + 1)
            selected[order[:count]], threshold = True, math.log(size / (ALPHA * count))
    else:
        raise ValueError("unknown multiplicity method")
    return {"selected": selected.tolist(), "log_threshold": threshold,
            "rejection_count": int(selected.sum())}


def common_report_e_test(
    rows: list[dict], family_ids: list[str], report_at: str, *, origin_endpoint: int,
    alpha_allocation_id: str, level: float = FAMILY_ALPHA,
) -> dict:
    """Compute lifetime e-Bonferroni and descriptive current e-BH at one cutoff."""
    report_time = _time(report_at)
    if level != FAMILY_ALPHA or alpha_allocation_id != ALPHA_ALLOCATION_ID:
        raise ValueError("registered family alpha allocation must be 0.04")
    if len(family_ids) != len(set(family_ids)):
        raise ValueError("duplicate family ID")
    mapped = {row.get("comparison_id"): row for row in rows}
    if len(mapped) != len(rows) or set(mapped) != set(family_ids):
        raise ValueError("incomplete or duplicate registered family")
    ordered = [mapped[item] for item in family_ids]
    if any(_time(row.get("report_at")) != report_time for row in ordered):
        raise ValueError("e-values must share the common report time")
    if any(row.get("origin_endpoint") != origin_endpoint for row in ordered):
        raise ValueError("e-values must share the common origin endpoint")
    checks = []
    for row in ordered:
        dsr, neutral, champion = (row.get("dsr_probability"), row.get("mean_neutral_ic"),
                                  row.get("mean_champion_ic"))
        checks.append({
            "prospective_evidence": row.get("evidence_class") == "prospective",
            "identity_complete": row.get("identity_complete") is True,
            "inventory_complete": row.get("inventory_complete") is True,
            "prefix_complete": row.get("prefix_complete") is True,
            "dsr_probability_at_least_0_95": bool(dsr is not None and math.isfinite(dsr)
                                                     and 0.95 <= dsr <= 1),
            "mean_neutral_ic_positive": bool(neutral is not None and math.isfinite(neutral)
                                                and neutral > 0),
            "mean_champion_ic_positive": bool(champion is not None and math.isfinite(champion)
                                                 and champion > 0),
        })
    gate = [all(check.values()) for check in checks]
    current = np.asarray([row.get("log_e") for row in ordered], float)
    maximum = np.asarray([row.get("max_log_e") for row in ordered], float)
    if (np.any(~np.isfinite(current)) or np.any(~np.isfinite(maximum))
            or np.any(maximum < np.maximum(0, current))):
        raise ValueError("invalid current or running-maximum e-value")
    lifetime = _multiple(maximum, gate, method="lifetime_e_bonferroni", level=level)
    descriptive = _multiple(current, gate, method="current_e_bh", level=level)
    allocation = {"alpha_allocation_id": alpha_allocation_id, "level": level,
                  "comparison_ids": family_ids}
    return {
        **lifetime, "promotion_basis": "lifetime_e_bonferroni", "level": level,
        "alpha_allocation_id": alpha_allocation_id, "family_size": len(family_ids),
        "alpha_allocation_sha256": canonical_sha256(allocation),
        "comparison_ids": family_ids, "report_at": report_time.isoformat(),
        "origin_endpoint": origin_endpoint, "eligibility_checks": checks,
        "eligibility_mask": gate, "current_log_e": current.tolist(),
        "max_log_e": maximum.tolist(),
        "descriptive_ebh_selected": descriptive["selected"],
        "descriptive_ebh_log_threshold": descriptive["log_threshold"],
    }


def candidate_for_promotion(common_report: dict, comparison_id: str) -> bool:
    """Recompute the registered lifetime boundary; never trust stored selection."""
    if (common_report.get("promotion_basis") != "lifetime_e_bonferroni"
            or common_report.get("level") != FAMILY_ALPHA
            or common_report.get("alpha_allocation_id") != ALPHA_ALLOCATION_ID):
        raise ValueError("promotion requires the registered lifetime e-Bonferroni report")
    ids = common_report.get("comparison_ids")
    if not isinstance(ids, list) or ids.count(comparison_id) != 1:
        raise ValueError("comparison ID missing or duplicated")
    index, size = ids.index(comparison_id), len(ids)
    if common_report.get("family_size") != size:
        raise ValueError("family size differs")
    allocation = {"alpha_allocation_id": ALPHA_ALLOCATION_ID, "level": FAMILY_ALPHA,
                  "comparison_ids": ids}
    if common_report.get("alpha_allocation_sha256") != canonical_sha256(allocation):
        raise ValueError("family alpha allocation differs")
    checks, masks, maxima = (common_report.get("eligibility_checks", []),
                             common_report.get("eligibility_mask", []),
                             common_report.get("max_log_e", []))
    if not (len(checks) == len(masks) == len(maxima) == size):
        raise ValueError("unaligned common report output")
    row_checks = checks[index]
    if set(row_checks) != REQUIRED_PROMOTION_CHECKS or any(type(v) is not bool for v in row_checks.values()):
        raise ValueError("promotion eligibility checks differ")
    eligible = all(row_checks.values())
    if type(masks[index]) is not bool or masks[index] != eligible:
        raise ValueError("stored eligibility mask differs")
    return bool(eligible and maxima[index] >= math.log(size / FAMILY_ALPHA))
