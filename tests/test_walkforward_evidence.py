"""Tests for published walk-forward evidence validation."""

import json
import os

import pytest

from engine.lib.provenance import canonical_sha256
from farm.walkforward import controls as walkforward_controls
from farm.walkforward.runner import summarize as summarize_folds
from server import walkforward_cohort, walkforward_evidence
from sim import execution
from tests.walkforward_test_helpers import (
    setup_walkforward_recovery,
    walkforward_fold,
    walkforward_protocol,
    walkforward_snapshot,
    write_walkforward_result,
)


def _rewrite_result(path, update):
    payload = json.loads(path.read_text())
    update(payload)
    path.write_text(json.dumps(payload))


def _rewrite_fold(path, update):
    def update_payload(payload):
        update(payload["folds"][0])
        payload["summary"] = summarize_folds(payload["folds"])

    _rewrite_result(path, update_payload)


def test_walkforward_evidence_status_is_current_for_complete_matching_cohort(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))

    result = walkforward_evidence.evidence_status(con, tmp_path)
    assert result == {
        "status": "current",
        "current_source_sha256": "a" * 64,
        "current_source_file_count": 99,
        "cohort_source_sha256": "a" * 64,
        "cohort_anchor": "2026-09-04",
        "cohort_train_months": 24,
        "cohort_validate_months": 12,
        "cohort_step_months": 12,
        "cohort_fill_model": "v4",
        "cohort_universe_policy": "all",
        "cohort_initial_cash": 39_000.0,
        "cohort_execution_profile_id": "baseline_v1",
        "cohort_execution_profile_sha256": canonical_sha256(
            execution.resolve_profile("baseline_v1").as_dict()
        ),
        "cohort_data_snapshot_sha256": walkforward_snapshot()["sha256"],
        "cohort_comparison_protocol": walkforward_controls.CONTROL_PROTOCOL,
        "cohort_signature_sha256": result["cohort_signature_sha256"],
        "cohort_signature_count": 1,
        "expected_results": 2,
        "available_results": 2,
        "diagnostic_list_limit": 100,
        "diagnostic_value_max_chars": 256,
        "missing_results": [],
        "missing_results_count": 0,
        "missing_results_truncated": False,
        "missing_results_values_truncated": False,
        "invalid_files": [],
        "invalid_files_count": 0,
        "invalid_files_truncated": False,
        "invalid_files_values_truncated": False,
        "config_mismatches": [],
        "config_mismatches_count": 0,
        "config_mismatches_truncated": False,
        "config_mismatches_values_truncated": False,
        "registration_mismatches": [],
        "registration_mismatches_count": 0,
        "registration_mismatches_truncated": False,
        "registration_mismatches_values_truncated": False,
        "duplicate_config_ids": [],
        "duplicate_config_ids_count": 0,
        "duplicate_config_ids_truncated": False,
        "duplicate_config_ids_values_truncated": False,
        "invalid_registrations": [],
        "invalid_registrations_count": 0,
        "invalid_registrations_truncated": False,
        "invalid_registrations_values_truncated": False,
    }


def test_walkforward_diagnostic_projection_bounds_lists_and_values():
    limit = walkforward_cohort.DIAGNOSTIC_LIST_LIMIT
    value_limit = walkforward_cohort.DIAGNOSTIC_VALUE_MAX_CHARS
    expected = {f"missing-{index:03}-" + "x" * value_limit for index in range(limit + 2)}
    scan = walkforward_cohort.empty_scan()
    scan["invalid_files"] = [f"invalid-{index:03}.json" for index in range(limit + 1)]

    result = walkforward_cohort._scan_payload(expected, scan, [])

    assert result["expected_results"] == limit + 2
    assert result["missing_results_count"] == limit + 2
    assert len(result["missing_results"]) == limit
    assert result["missing_results_truncated"] is True
    assert result["invalid_files_count"] == limit + 1
    assert len(result["invalid_files"]) == limit
    assert result["invalid_files_truncated"] is True
    assert result["missing_results_values_truncated"] is True
    assert result["invalid_files_values_truncated"] is False
    assert all(len(value) <= value_limit for value in result["missing_results"])
    assert "diagnostic_values_truncated" not in result


def test_walkforward_evidence_status_reports_stale_source(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    write_walkforward_result(tmp_path / "spy.json", "spy", source="b" * 64)
    write_walkforward_result(tmp_path / "sector.json", "sector", source="b" * 64)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "stale-source"
    assert result["cohort_source_sha256"] == "b" * 64


def test_walkforward_evidence_status_rejects_incomplete_or_mixed_cohort(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    assert walkforward_evidence.evidence_status(con, tmp_path)["status"] == "incomplete"

    write_walkforward_result(tmp_path / "sector.json", "sector", anchor="2026-09-05")
    assert walkforward_evidence.evidence_status(con, tmp_path)["status"] == "mixed-cohort"


def test_walkforward_evidence_reports_expected_mixed_publication_as_updating(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy", source="b" * 64)
    write_walkforward_result(tmp_path / "sector.json", "sector", source="a" * 64)
    recovery = {
        "status": "updating",
        "recovery_job_count": 2,
        "recovery_job_counts": {"done": 1, "running": 1},
    }

    result = walkforward_evidence.evidence_status(con, tmp_path, recovery_status=recovery)

    assert result["status"] == "updating"
    assert result["artifact_status"] == "mixed-cohort"
    assert result["refresh_job_count"] == 2
    assert result["refresh_job_counts"] == {"done": 1, "running": 1}


def test_walkforward_evidence_does_not_hide_invalid_artifact_during_recovery(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    (tmp_path / "sector.json").write_text("not json")

    result = walkforward_evidence.evidence_status(
        con,
        tmp_path,
        recovery_status={"status": "updating", "recovery_job_count": 2},
    )

    assert result["status"] == "invalid"
    assert "artifact_status" not in result


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("initial_cash", 100_000.0),
        (
            "execution_profile",
            {
                **execution.resolve_profile("baseline_v1").as_dict(),
                "fixed_adverse_bps": 9.0,
            },
        ),
        ("data_snapshot", walkforward_snapshot({"prices": {"rows": 2}})),
        (
            "comparison",
            {
                "protocol": "controls-v2",
                "control_id": walkforward_controls.EW,
                "evidence_role": "exploratory_historical_comparison",
            },
        ),
    ],
)
def test_walkforward_evidence_status_rejects_mixed_research_assumptions(
    con, tmp_path, monkeypatch, field, changed
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector", **{field: changed})

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "mixed-cohort"
    assert result["cohort_signature_count"] == 2
    assert result["cohort_source_sha256"] is None


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("fill_model", "v5"),
        ("universe_policy", "ex-leveraged"),
        ("data_quality_class", "current_universe_survivor_biased"),
    ],
)
def test_walkforward_evidence_rejects_unregistered_producer_assumption(
    con, tmp_path, monkeypatch, field, changed
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector", **{field: changed})

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_fails_closed_on_invalid_live_universe_policy(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    monkeypatch.setenv("TRADING_ENGINE_UNIVERSE_POLICY", "not-a-policy")
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_registrations"] == ["sector", "spy"]
    assert result["missing_results"] == ["sector", "spy"]


def test_walkforward_evidence_rejects_uniform_unregistered_protocol(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    protocol = walkforward_protocol(train_months=36)
    write_walkforward_result(tmp_path / "spy.json", "spy", protocol=protocol)
    write_walkforward_result(tmp_path / "sector.json", "sector", protocol=protocol)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json", "spy.json"]
    assert result["missing_results"] == ["sector", "spy"]


def test_walkforward_evidence_status_rejects_live_config_mismatch(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(
        tmp_path / "sector.json",
        "sector",
        config_sha256=canonical_sha256({"changed": True}),
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["config_mismatches"] == ["sector"]


@pytest.mark.parametrize(
    "override",
    [
        {"config": {"lookback": 12}},
        {"strategy": "spy_benchmark"},
        {"folds": []},
        {"summary": {}},
        {
            "protocol": {
                **walkforward_protocol(),
                "folds": [
                    {
                        **walkforward_protocol()["folds"][0],
                        "validate_end": "2026-09-03",
                    }
                ],
            }
        },
    ],
)
def test_walkforward_evidence_rejects_incomplete_or_incoherent_result(
    con, tmp_path, monkeypatch, override
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector", **override)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("validate_win_rate", 0.5),
        ("mean_validate_total", 99.0),
        ("median_validate_total", 99.0),
        ("worst_validate_total", 99.0),
        ("best_validate_total", 99.0),
        ("mean_validate_cagr", 99.0),
        ("mean_train_cagr", 99.0),
        ("mean_decay_cagr", 99.0),
        ("mean_validate_sharpe", 99.0),
        ("worst_validate_max_dd", 99.0),
        ("latest_validate_total", 99.0),
        ("unexpected_metric", 99.0),
    ],
)
def test_walkforward_evidence_rejects_forged_summary_metric(
    con, tmp_path, monkeypatch, field, changed
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    _rewrite_result(sector_path, lambda payload: payload["summary"].update({field: changed}))

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


@pytest.mark.parametrize(
    ("path", "changed"),
    [
        (("first_session",), "2014-09-05"),
        (("split_session",), "2016-09-03"),
        (("last_session",), "2017-09-03"),
        (("sessions",), 4),
        (("n_fills",), 0),
        (("n_validate_fills",), 3),
        (("train_start_clamped_to_data_floor",), True),
        (("train", "return_base"), 38_000.0),
        (("train", "equity_start"), 38_000.0),
        (("train", "total_return"), 0.5),
        (("train", "years"), 1.0),
        (("train", "cagr"), 0.5),
        (("train", "vol_ann"), -0.1),
        (("train", "max_dd"), 0.1),
        (("train", "worst_month"), -1.1),
        (("train", "bil_coverage"), 1.1),
        (("train", "sharpe"), "high"),
        (("validate", "equity_start"), 40_000.0),
        (("validate", "total_return"), 0.5),
        (("validate", "equity_end"), 1e308),
        (("validate_monthly_equity", 1, 1), 40_000.0),
        (("validate_monthly_equity", 1, 0), "2016-09"),
    ],
)
def test_walkforward_evidence_rejects_incoherent_successful_fold(
    con, tmp_path, monkeypatch, path, changed
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def corrupt(fold):
        target = fold
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = changed

    _rewrite_fold(sector_path, corrupt)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


@pytest.mark.parametrize("status", ["inert", "skipped"])
def test_walkforward_evidence_accepts_reasoned_non_result_fold(
    con, tmp_path, monkeypatch, status
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def replace_fold(payload):
        geometry = payload["protocol"]["folds"][0]
        payload["folds"][0] = {
            **geometry,
            "status": status,
            "train_start_clamped_to_data_floor": False,
            "reason": "honest terminal outcome",
        }
        payload["summary"] = summarize_folds(payload["folds"])

    _rewrite_result(sector_path, replace_fold)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "current"


@pytest.mark.parametrize("status", ["inert", "skipped"])
def test_walkforward_evidence_rejects_unexplained_non_result_fold(
    con, tmp_path, monkeypatch, status
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def replace_fold(payload):
        payload["folds"][0] = {
            **payload["protocol"]["folds"][0],
            "status": status,
            "train_start_clamped_to_data_floor": False,
            "reason": " ",
        }
        payload["summary"] = summarize_folds(payload["folds"])

    _rewrite_result(sector_path, replace_fold)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_rejects_undisclosed_missing_planned_fold(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def omit_newest(payload):
        payload["protocol"]["folds"].pop()
        payload["protocol"]["n_folds"] -= 1
        payload["folds"].pop()
        payload["summary"]["n_folds_ok"] -= 1
        payload["summary"]["total_validate_fills"] -= 1

    _rewrite_result(sector_path, omit_newest)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_rejects_retained_and_dropped_index_overlap(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def overlap_first(payload):
        payload["dropped_folds"] = [
            {
                **payload["protocol"]["folds"][0],
                "status": "dropped",
                "reason": "test disclosure",
            }
        ]

    _rewrite_result(sector_path, overlap_first)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_rejects_index_outside_planned_grid(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def replace_newest_index(payload):
        payload["protocol"]["folds"][-1]["index"] = 11
        payload["folds"][-1]["index"] = 11

    _rewrite_result(sector_path, replace_newest_index)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_rejects_self_consistent_shifted_fold_dates(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def shift_oldest(payload):
        for fold in (payload["protocol"]["folds"][0], payload["folds"][0]):
            fold["split_date"] = "2016-09-03"

    _rewrite_result(sector_path, shift_oldest)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


@pytest.mark.parametrize(
    "rewrite",
    [
        lambda payload: payload["protocol"].update(anchor="20260904"),
        lambda payload: payload["protocol"]["folds"][0].update(split_date="20160904"),
    ],
)
def test_walkforward_evidence_rejects_noncanonical_protocol_dates(
    con, tmp_path, monkeypatch, rewrite
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")
    _rewrite_result(sector_path, rewrite)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_rejects_undisclosed_data_floor_drop(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(
        tmp_path / "sector.json",
        "sector",
        data_floor="2016-10-07",
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


@pytest.mark.parametrize(
    "data_floor", [None, "not-a-date", "1993-01-01", "2026-09-04"]
)
def test_walkforward_evidence_rejects_invalid_or_exhausting_data_floor(
    con, tmp_path, monkeypatch, data_floor
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector", data_floor=data_floor)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


@pytest.mark.parametrize(
    "dropped_fold",
    [
        {"index": 1, "status": "dropped", "reason": "missing geometry"},
        {
            "index": 1,
            "train_start": "2013-09-04",
            "split_date": "2015-09-04",
            "validate_end": "2016-09-04",
            "status": "ok",
            "reason": "wrong status",
        },
        {
            "index": 1,
            "train_start": "2013-09-04",
            "split_date": "2015-09-04",
            "validate_end": "2016-09-04",
            "status": "dropped",
            "reason": " ",
        },
    ],
)
def test_walkforward_evidence_rejects_malformed_dropped_fold(
    con, tmp_path, monkeypatch, dropped_fold
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def replace_oldest(payload):
        payload["protocol"]["folds"].pop(0)
        payload["protocol"]["n_folds"] -= 1
        payload["folds"].pop(0)
        payload["dropped_folds"] = [dropped_fold]
        payload["summary"]["n_folds_ok"] -= 1
        payload["summary"]["total_validate_fills"] -= 1

    _rewrite_result(sector_path, replace_oldest)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]


def test_walkforward_evidence_accepts_nine_retained_and_one_disclosed_drop(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    con.execute(
        "UPDATE prices SET date = date + "
        "CAST(DATE '2016-01-29' - DATE '1993-05-20' AS INTEGER) "
        "WHERE ticker != 'SPY'"
    )
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")

    def drop_oldest(payload):
        dropped = payload["protocol"]["folds"].pop(0)
        payload["protocol"]["n_folds"] -= 1
        payload["folds"].pop(0)
        payload["data_floor"] = "2016-10-07"
        for index, protocol_fold in enumerate(payload["protocol"]["folds"]):
            if protocol_fold["train_start"] < payload["data_floor"]:
                protocol_fold["train_start"] = payload["data_floor"]
                payload["folds"][index] = walkforward_fold(
                    protocol_fold, clamped=True
                )
        payload["dropped_folds"] = [
            {**dropped, "status": "dropped", "reason": "declared data floor"}
        ]
        payload["summary"] = summarize_folds(payload["folds"])

    _rewrite_result(sector_path, drop_oldest)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "current"
    assert result["available_results"] == 2


@pytest.mark.parametrize(
    "snapshot",
    [
        {"sha256": "d" * 64},
        {"sha256": "d" * 64, "tables": []},
        {"sha256": "not-a-hash", "tables": {}},
        {"sha256": "d" * 64, "tables": {"prices": {"rows": 1}}},
    ],
)
def test_walkforward_evidence_rejects_invalid_or_mismatched_snapshot(
    con, tmp_path, monkeypatch, snapshot
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector", data_snapshot=snapshot)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


@pytest.mark.parametrize(
    "update",
    [
        "initial_cash = 100000",
        "execution_profile = 'cost_2x_v1'",
    ],
)
def test_walkforward_evidence_status_rejects_live_registration_mismatch(
    con, tmp_path, monkeypatch, update
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    con.execute(f"UPDATE portfolios SET {update} WHERE id = 'sector'")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["registration_mismatches"] == ["sector"]


def test_walkforward_evidence_status_rejects_wrong_declared_control(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(
        tmp_path / "sector.json",
        "sector",
        comparison={
            **walkforward_controls.declaration("sector"),
            "control_id": walkforward_controls.SPY,
        },
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["registration_mismatches"] == ["sector"]


@pytest.mark.parametrize(
    "update",
    [
        "config = '[]'",
        "config = '{bad json'",
        "initial_cash = NULL",
        "execution_profile = 'unknown-profile'",
    ],
)
def test_walkforward_evidence_status_fails_closed_on_invalid_registration(
    con, tmp_path, monkeypatch, update
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    con.execute(f"UPDATE portfolios SET {update} WHERE id = 'sector'")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_registrations"] == ["sector"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_fails_closed_on_missing_required_price_history(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    con.execute("DELETE FROM prices WHERE ticker = 'XLRE'")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_registrations"] == ["sector"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_fails_closed_when_prices_are_unavailable(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    con.execute("DROP TABLE prices")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_registrations"] == ["sector", "spy"]
    assert result["missing_results"] == ["sector", "spy"]


def test_walkforward_registration_data_floors_are_bulk_loaded_once(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    con.execute(
        "INSERT INTO portfolios "
        "SELECT 'spy-twin', name, strategy, config, created, active, cash, "
        "initial_cash, execution_profile FROM portfolios WHERE id = 'spy'"
    )
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))

    class RecordingConnection:
        def __init__(self, actual):
            self.actual = actual
            self.price_floor_queries = 0

        def execute(self, statement, parameters=None):
            if "ROW_NUMBER() OVER" in statement and "FROM prices" in statement:
                self.price_floor_queries += 1
            if parameters is None:
                return self.actual.execute(statement)
            return self.actual.execute(statement, parameters)

    recording = RecordingConnection(con)
    result = walkforward_evidence.evidence_status(recording, tmp_path)

    assert result["expected_results"] == 3
    assert result["invalid_registrations"] == []
    assert recording.price_floor_queries == 1


def test_walkforward_evidence_rejects_duplicate_registration_config_key(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    con.execute(
        "UPDATE portfolios SET config = ? WHERE id = 'sector'",
        ['{"lookback": 6, "lookback": 12}'],
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_registrations"] == ["sector"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_status_rejects_duplicate_config_id(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector-a.json", "sector")
    write_walkforward_result(tmp_path / "sector-b.json", "sector")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["duplicate_config_ids"] == ["sector"]
    assert result["invalid_files"] == ["sector-a.json", "sector-b.json"]


def test_walkforward_evidence_status_tracks_duplicate_even_if_first_is_malformed(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector-a.json", "sector", fill_model=None)
    write_walkforward_result(tmp_path / "sector-b.json", "sector")

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["duplicate_config_ids"] == ["sector"]
    assert result["invalid_files"] == ["sector-a.json", "sector-b.json"]


def test_walkforward_evidence_rejects_duplicate_json_key(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")
    payload = sector_path.read_text().replace(
        '"config_id": "sector"',
        '"config_id": "sector", "config_id": "sector"',
        1,
    )
    sector_path.write_text(payload)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_ignores_nonfinite_unregistered_legacy_artifact(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    write_walkforward_result(tmp_path / "sector.json", "sector")
    (tmp_path / "retired.json").write_text('{"config_id": "retired", "metric": NaN}')

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "current"
    assert result["invalid_files"] == []


def test_walkforward_evidence_rejects_nonfinite_registered_artifact(
    con, tmp_path, monkeypatch
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    write_walkforward_result(sector_path, "sector")
    sector_path.write_text(sector_path.read_text().replace('"initial_cash": 39000.0', '"initial_cash": NaN'))

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink", "directory", "fifo"])
def test_walkforward_evidence_rejects_non_regular_result_without_blocking(
    con, tmp_path, monkeypatch, kind
):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    sector_path = tmp_path / "sector.json"
    if kind == "symlink":
        external = tmp_path / "external" / "sector.json"
        external.parent.mkdir()
        write_walkforward_result(external, "sector")
        sector_path.symlink_to(external)
    elif kind == "dangling-symlink":
        sector_path.symlink_to(tmp_path / "missing.json")
    elif kind == "directory":
        sector_path.mkdir()
    else:
        os.mkfifo(sector_path)

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_rejects_oversized_result(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_evidence, "runtime_source_hash", lambda: ("a" * 64, 99))
    write_walkforward_result(tmp_path / "spy.json", "spy")
    (tmp_path / "sector.json").write_bytes(
        b"x" * (walkforward_evidence.walkforward_cohort.MAX_RESULT_FILE_BYTES + 1)
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["invalid_files"] == ["sector.json"]
    assert result["missing_results"] == ["sector"]


def test_walkforward_evidence_status_fails_closed_on_unreadable_source(con, tmp_path, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(
        walkforward_evidence,
        "runtime_source_hash",
        lambda: (_ for _ in ()).throw(OSError("source unavailable")),
    )

    result = walkforward_evidence.evidence_status(con, tmp_path)

    assert result["status"] == "invalid"
    assert result["current_source_sha256"] is None
    assert result["missing_results"] == ["sector", "spy"]
    assert result["cohort_fill_model"] is None
    assert result["registration_mismatches"] == []
