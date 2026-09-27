"""Pure P16 evaluation-family report composition and validation."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256
from farm import p16_sequential

EVALUATION_POLICY_ID = "p16-eval-v2"
REPORT_SCHEMA_VERSION = 1
INITIAL_BOOK_IDS = (
    "p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto",
    "p16_construct_ai", "p16_construct_rule",
)


def _time(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("P16 report time is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("P16 report time is invalid")
    return result.astimezone(timezone.utc)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _aggregate(value: object, report_at: datetime) -> dict:
    if not isinstance(value, dict) or value.get("aggregate_sha256") != canonical_sha256({
            key: item for key, item in value.items() if key != "aggregate_sha256"}):
        raise ValueError("P16 factor aggregate identity differs")
    if _time(value.get("report_cutoff")) != report_at:
        raise ValueError("P16 factor aggregate cutoff differs")
    return value


def _prefix_complete(sequential: dict, endpoint: int) -> bool:
    tracks = [sequential.get("primary"), *sequential.get("robustness", [])]
    if len(tracks) != p16_sequential.OFFSETS:
        return False
    for offset, track in enumerate(tracks):
        if not isinstance(track, dict) or track.get("offset") != offset:
            return False
        expected = set(range(offset, endpoint + 1, p16_sequential.OFFSETS))
        consumed = track.get("consumed_session_indices", [])
        skipped = track.get("skipped_decision_indices", [])
        if (track.get("blocked_at") is not None or not isinstance(consumed, list)
                or not isinstance(skipped, list)
                or set(consumed) | set(skipped) != expected
                or set(consumed) & set(skipped)):
            return False
    return True


def build_report(
    *, registration_sha256: str, family_id: str, alpha_allocation_id: str,
    family_ids: list[str], registered_book_ids: list[str], report_at: str,
    origin_endpoint: int, comparison_rows: list[dict], champion_control: dict,
    trial_inventory: dict, transfer_rows: list[dict], sector_coverage: list[dict],
    solver_failures: list[dict], dependency_artifact_sha256s: list[str],
    previous_report_sha256: str | None = None,
) -> dict:
    """Build one common-cutoff report without accepting opaque eligibility flags."""
    registration = _digest(registration_sha256, "P16 registration digest")
    report_time = _time(report_at)
    if (not isinstance(family_id, str) or not family_id
            or type(origin_endpoint) is not int or origin_endpoint < 0
            or not isinstance(family_ids, list) or not family_ids
            or len(family_ids) != len(set(family_ids))
            or not isinstance(registered_book_ids, list)
            or len(registered_book_ids) != len(set(registered_book_ids))
            or dependency_artifact_sha256s != sorted(set(dependency_artifact_sha256s))
            or any(not re.fullmatch(r"[0-9a-f]{64}", item)
                   for item in dependency_artifact_sha256s)):
        raise ValueError("P16 report registration is invalid")
    mapped = {row.get("comparison_id"): row for row in comparison_rows}
    if len(mapped) != len(comparison_rows) or set(mapped) != set(family_ids):
        raise ValueError("P16 report family is incomplete")
    versions = {row.get("trial_id"): row for row in trial_inventory.get("versions", [])}
    common_rows, output_rows, complete_rows = [], [], []
    for comparison_id in family_ids:
        row = mapped[comparison_id]
        sequential = row.get("sequential")
        if (not isinstance(sequential, dict)
                or _time(sequential.get("report_at")) != report_time):
            raise ValueError("P16 sequential report cutoff differs")
        primary = sequential.get("primary")
        if not isinstance(primary, dict):
            raise ValueError("P16 primary sequential state is absent")
        trial_id = _digest(row.get("trial_id"), "challenger trial ID")
        control_id = _digest(row.get("control_trial_id"), "control trial ID")
        registration_row = versions.get(trial_id, {})
        dsr = row.get("deflated_sharpe")
        if not isinstance(dsr, dict) or dsr.get("candidate_trial_id") != trial_id:
            raise ValueError("P16 deflated Sharpe identity differs")
        neutral = _aggregate(row.get("factor_neutral"), report_time)
        champion = _aggregate(row.get("champion_factor_neutral"), report_time)
        evidence_class = registration_row.get("evidence_class")
        identity_complete = bool(registration_row.get("identity_verified") is True
                                 and registration_row.get("status") != "retired")
        prefix_complete = _prefix_complete(sequential, origin_endpoint)
        common_rows.append({
            "comparison_id": comparison_id, "report_at": report_time.isoformat(),
            "origin_endpoint": origin_endpoint, "log_e": primary.get("log_e", 0.0),
            "max_log_e": primary.get("max_log_e", 0.0),
            "evidence_class": evidence_class, "identity_complete": identity_complete,
            "inventory_complete": trial_inventory.get("inventory_complete") is True,
            "prefix_complete": prefix_complete,
            "dsr_probability": dsr.get("probability") if dsr.get("status") == "available" else None,
            "mean_neutral_ic": neutral.get("mean_neutral_ic")
            if neutral.get("status") == "available" else None,
            "mean_champion_ic": champion.get("mean_neutral_ic")
            if champion.get("status") == "available" else None,
        })
        output_rows.append({
            "comparison_id": comparison_id, "trial_id": trial_id,
            "control_trial_id": control_id, "sequential": sequential,
            "deflated_sharpe": dsr, "factor_neutral": neutral,
            "champion_factor_neutral": champion,
        })
        complete_rows.append(bool(
            evidence_class == "prospective" and identity_complete and prefix_complete
            and trial_inventory.get("inventory_complete") is True
            and dsr.get("status") == "available"
            and neutral.get("status") == "available"
            and champion.get("status") == "available"))
    common = p16_sequential.common_report_e_test(
        common_rows, family_ids, report_time.isoformat(), origin_endpoint=origin_endpoint,
        alpha_allocation_id=alpha_allocation_id,
    )
    for index, row in enumerate(output_rows):
        checks = common["eligibility_checks"][index]
        row.update(
            eligibility_checks=checks,
            filter_reasons=[key for key, passed in checks.items() if not passed],
            candidate_for_promotion=p16_sequential.candidate_for_promotion(
                common, row["comparison_id"]),
            descriptive_ebh_selected=common["descriptive_ebh_selected"][index],
        )
    transfer = {row.get("book_id"): row for row in transfer_rows}
    if (len(transfer) != len(transfer_rows) or set(transfer) != set(registered_book_ids)
            or not all(isinstance(row, dict) for row in transfer_rows)):
        raise ValueError("P16 transfer report is incomplete")
    if champion_control.get("comparison_id") in set(family_ids):
        raise ValueError("champion control cannot enter the challenger family")
    body = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluation_policy_id": EVALUATION_POLICY_ID,
        "registration_sha256": registration, "family_id": family_id,
        "family_ids": family_ids, "registered_book_ids": registered_book_ids,
        "alpha_allocation_id": alpha_allocation_id,
        "report_at": report_time.isoformat(), "origin_endpoint": origin_endpoint,
        "status": "available" if all(complete_rows) else "incomplete",
        "trial_inventory": trial_inventory, "comparisons": output_rows,
        "common_report": common,
        "promotion_candidate_ids": [row["comparison_id"] for row in output_rows
                                    if row["candidate_for_promotion"]],
        "descriptive_ebh_comparison_ids": [row["comparison_id"] for row in output_rows
                                           if row["descriptive_ebh_selected"]],
        "champion_control": champion_control,
        "transfer": [transfer[item] for item in registered_book_ids],
        "sector_coverage": sector_coverage, "solver_failures": solver_failures,
        "dependency_artifact_sha256s": dependency_artifact_sha256s,
        "previous_report_sha256": previous_report_sha256,
        "promotion_authority": "owner_review_required", "execution_authority": "none",
    }
    return {**body, "report_sha256": canonical_sha256(body)}


def validate_report(report: dict) -> dict:
    """Validate a retained P16 report and its derived selection fields."""
    if not isinstance(report, dict) or report.get("report_sha256") != canonical_sha256({
            key: value for key, value in report.items() if key != "report_sha256"}):
        raise ValueError("P16 family report hash differs")
    if (report.get("schema_version") != REPORT_SCHEMA_VERSION
            or report.get("evaluation_policy_id") != EVALUATION_POLICY_ID
            or report.get("execution_authority") != "none"
            or report.get("promotion_authority") != "owner_review_required"):
        raise ValueError("P16 family report contract differs")
    common, family_ids = report.get("common_report"), report.get("family_ids")
    rows = report.get("comparisons")
    if (not isinstance(common, dict) or not isinstance(family_ids, list)
            or not isinstance(rows, list)
            or [row.get("comparison_id") for row in rows] != family_ids):
        raise ValueError("P16 family report rows differ")
    promoted, descriptive = [], []
    for index, row in enumerate(rows):
        expected = p16_sequential.candidate_for_promotion(common, row["comparison_id"])
        if (row.get("candidate_for_promotion") is not expected
                or row.get("eligibility_checks") != common["eligibility_checks"][index]
                or row.get("descriptive_ebh_selected")
                is not common["descriptive_ebh_selected"][index]):
            raise ValueError("P16 family report selection differs")
        if expected:
            promoted.append(row["comparison_id"])
        if row["descriptive_ebh_selected"]:
            descriptive.append(row["comparison_id"])
    if (report.get("promotion_candidate_ids") != promoted
            or report.get("descriptive_ebh_comparison_ids") != descriptive):
        raise ValueError("P16 family report selections differ")
    return report
