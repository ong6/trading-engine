"""Tests for pure P16 family-report composition."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from farm import p16_evaluation_report as reports, p16_sequential

NOW = datetime(2027, 1, 4, 21, tzinfo=timezone.utc)
FAMILY = [f"c{index}" for index in range(4)]
TRIALS = [f"{index + 1:064x}" for index in range(4)]
CONTROL = "f" * 64
DEPENDENCIES = [f"{index + 10:064x}" for index in range(4)]


def _aggregate(policy_id: str, value: float) -> dict:
    body = {"status": "available", "policy_id": policy_id,
            "report_cutoff": NOW.isoformat(), "mean_neutral_ic": value,
            "source_report_sha256": []}
    return {**body, "aggregate_sha256": canonical_sha256(body)}


def _comparison(index: int, current: float, maximum: float, **updates) -> dict:
    primary = {"log_e": math.log(current), "max_log_e": math.log(maximum),
               "consumed_session_indices": list(range(0, 101, 5)),
               "skipped_decision_indices": [], "blocked_at": None}
    row = {"comparison_id": FAMILY[index], "trial_id": TRIALS[index],
           "control_trial_id": CONTROL,
           "sequential": {"report_at": NOW.isoformat(), "primary": primary,
                          "robustness": [], "execution_authority": "none"},
           "deflated_sharpe": {"status": "available", "candidate_trial_id": TRIALS[index],
                               "probability": 0.96, "trials": 4},
           "factor_neutral": _aggregate(FAMILY[index], 0.01),
           "champion_factor_neutral": _aggregate("p15-scoring-v1", 0.02)}
    row.update(updates)
    return row


def _inventory(**updates) -> dict:
    value = {"status": "complete", "inventory_complete": True,
             "selection_trial_count": 4, "selection_trial_ids": TRIALS,
             "register_sha256": "a" * 64,
             "versions": [{"trial_id": trial_id, "evidence_class": "prospective",
                           "identity_verified": True, "status": "evaluated"}
                          for trial_id in TRIALS]}
    value.update(updates)
    return value


def _build(*, rows=None, inventory=None, transfer=None):
    return reports.build_report(
        registration_sha256="b" * 64, family_id="p16-family-v1",
        alpha_allocation_id=p16_sequential.ALPHA_ALLOCATION_ID, family_ids=FAMILY,
        registered_book_ids=list(reports.INITIAL_BOOK_IDS), report_at=NOW.isoformat(),
        origin_endpoint=100,
        comparison_rows=rows or [_comparison(index, current, maximum)
                                 for index, (current, maximum) in enumerate(
                                     ((55, 120), (55, 55), (1, 1), (1, 1)))],
        champion_control={"comparison_id": "champion-v-rule", "status": "available"},
        trial_inventory=inventory or _inventory(),
        transfer_rows=transfer or [{"book_id": item, "status": "unavailable"}
                                   for item in reports.INITIAL_BOOK_IDS],
        sector_coverage=[{"market_date": "2027-01-04", "coverage": 1.0}],
        solver_failures=[], dependency_artifact_sha256s=DEPENDENCIES,
    )


def test_report_preserves_family_and_separates_two_multiplicity_rules():
    report = _build()
    assert report["promotion_candidate_ids"] == ["c0"]
    assert report["descriptive_ebh_comparison_ids"] == ["c0", "c1"]
    assert [row["comparison_id"] for row in report["comparisons"]] == FAMILY
    assert report["common_report"]["family_size"] == 4
    assert report["transfer"] == [
        {"book_id": item, "status": "unavailable"} for item in reports.INITIAL_BOOK_IDS]
    assert reports.validate_report(report) is report


def test_report_derives_named_filters_and_keeps_retired_slot():
    inventory = _inventory()
    inventory["versions"][0]["status"] = "retired"
    rows = [_comparison(index, 100, 100) for index in range(4)]
    report = _build(rows=rows, inventory=inventory)
    first = report["comparisons"][0]
    assert first["candidate_for_promotion"] is False
    assert "identity_complete" in first["filter_reasons"]
    assert report["common_report"]["family_size"] == 4


def test_report_rejects_cutoff_identity_and_missing_transfer_slot():
    rows = [_comparison(index, 1, 1) for index in range(4)]
    rows[0]["factor_neutral"] = _aggregate("c0", 0.01) | {
        "report_cutoff": "2027-01-05T00:00:00+00:00"}
    with pytest.raises(ValueError, match="identity differs"):
        _build(rows=rows)
    with pytest.raises(ValueError, match="transfer report is incomplete"):
        _build(transfer=[{"book_id": item, "status": "unavailable"}
                         for item in reports.INITIAL_BOOK_IDS[:-1]])


def test_report_hash_and_allocation_tampering_fail_closed():
    report = _build()
    report["common_report"]["alpha_allocation_sha256"] = "0" * 64
    report["report_sha256"] = canonical_sha256({
        key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="allocation differs"):
        reports.validate_report(report)
    report = _build()
    report["status"] = "changed"
    with pytest.raises(ValueError, match="hash differs"):
        reports.validate_report(report)
