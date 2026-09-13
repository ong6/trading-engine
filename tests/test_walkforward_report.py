"""Benchmark selection in the fold-level walk-forward report."""
import json

import pytest

from farm.walkforward import report
from farm.walkforward.controls import declaration


def _fold(total):
    return {
        "status": "ok",
        "split_date": "2025-01-01",
        "validate_end": "2026-01-01",
        "validate": {"total_return": total},
    }


def _result(config_id, total):
    return {
        "config_id": config_id,
        "folds": [_fold(total)],
        "comparison": declaration(config_id),
        "source_sha256": "same-source",
        "fill_model": "v4",
        "universe_policy": "all",
        "initial_cash": 39_000.0,
        "execution_profile": {"id": "baseline_v1"},
        "data_snapshot": {"sha256": "same-data"},
    }


def test_asset_allocation_verdict_uses_spy_not_ew():
    # The candidate beats SPY but trails EW.  Its registered SPY comparison must
    # therefore PASS; using EW here would incorrectly produce REVIEW.
    results = [
        _result("ew_benchmark", 0.30),
        _result("spy_benchmark", 0.10),
        _result("multi_asset_trend", 0.20),
    ]
    verdict, measured = report.book_verdict(results[2], report._bench_index(results))
    assert measured["control"] == "spy_benchmark"
    assert measured["mean_excess"] == pytest.approx(0.10)
    assert verdict == "PASS"


def test_single_name_verdict_still_uses_ew():
    results = [
        _result("ew_benchmark", 0.30),
        _result("spy_benchmark", 0.10),
        _result("xs_momentum_12_1", 0.20),
    ]
    verdict, measured = report.book_verdict(results[2], report._bench_index(results))
    assert measured["control"] == "ew_benchmark"
    assert measured["mean_excess"] == pytest.approx(-0.10)
    assert verdict == "REVIEW"


def test_verdict_uses_artifact_control_not_current_default():
    candidate = _result("multi_asset_trend", 0.20)
    candidate["comparison"] = {
        "protocol": "historical-test-v1", "control_id": "ew_benchmark",
    }
    ew = _result("ew_benchmark", 0.30)
    ew["comparison"] = {
        "protocol": "historical-test-v1", "control_id": None,
    }
    results = [
        ew,
        _result("spy_benchmark", 0.10),
        candidate,
    ]
    verdict, measured = report.book_verdict(candidate, report._bench_index(results))
    assert measured["control"] == "ew_benchmark"
    assert measured["mean_excess"] == pytest.approx(-0.10)
    assert verdict == "REVIEW"


def test_verdict_suppresses_legacy_or_incompatible_provenance():
    control = _result("spy_benchmark", 0.10)
    legacy = _result("multi_asset_trend", 0.20)
    legacy.pop("source_sha256")
    verdict, measured = report.book_verdict(legacy, report._bench_index([control]))
    assert verdict == "no-benchmark"
    assert measured["control_reason"] == "artifact lacks complete research provenance"

    changed = _result("multi_asset_trend", 0.20)
    changed["source_sha256"] = "other-source"
    verdict, measured = report.book_verdict(changed, report._bench_index([control]))
    assert verdict == "no-benchmark"
    assert measured["control_reason"] == "different research cohort"


def test_fold_row_suppresses_legacy_relative_cells():
    control = _result("spy_benchmark", 0.10)
    legacy = _result("multi_asset_trend", 0.20)
    legacy.pop("comparison")

    benchmark = report._bench_index([control])["spy_benchmark"]
    assert report._compatible_benchmark(benchmark, legacy) is None


def test_verdict_requires_matching_comparison_protocol():
    control = _result("spy_benchmark", 0.10)
    candidate = _result("multi_asset_trend", 0.20)
    candidate["comparison"] = {**candidate["comparison"], "protocol": "changed-v2"}

    verdict, measured = report.book_verdict(candidate, report._bench_index([control]))

    assert verdict == "no-benchmark"
    assert measured["control_reason"] == "different research cohort"


def test_verdict_does_not_compare_incompatible_evidence_classes():
    results = [
        {**_result("ew_benchmark", 0.30),
         "data_quality_class": "current_universe_survivor_biased"},
        {**_result("low_vol", 0.20),
         "data_quality_class": "static_fundamental_lookahead"},
    ]
    verdict, measured = report.book_verdict(results[1], report._bench_index(results))
    assert verdict == "no-benchmark"
    assert measured["n_compared"] == 0


def test_load_results_never_mixes_protocol_anchors(tmp_path):
    old = {**_result("ew_benchmark", 0.3),
           "protocol": {"anchor": "2026-08-28", "train_months": 24,
                        "validate_months": 12, "step_months": 12, "n_folds": 10}}
    new = {**_result("spy_benchmark", 0.1),
           "protocol": {"anchor": "2026-09-04", "train_months": 24,
                        "validate_months": 12, "step_months": 12, "n_folds": 10}}
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    assert [r["config_id"] for r in report.load_results(tmp_path)] == ["spy_benchmark"]


def test_load_results_excludes_retired_artifacts(tmp_path):
    protocol = {"anchor": "2026-09-04", "train_months": 24,
                "validate_months": 12, "step_months": 12, "n_folds": 10}
    live = {**_result("spy_benchmark", 0.1), "protocol": protocol}
    retired = {**_result("news_gated_momo", 0.2), "protocol": protocol}
    (tmp_path / "live.json").write_text(json.dumps(live))
    (tmp_path / "retired.json").write_text(json.dumps(retired))
    assert [r["config_id"] for r in report.load_results(tmp_path)] == ["spy_benchmark"]


def test_load_results_retains_registered_retirement_evidence(tmp_path):
    protocol = {"anchor": "2026-09-04", "train_months": 24,
                "validate_months": 12, "step_months": 12, "n_folds": 10}
    control = {**_result("spy_benchmark", 0.1), "protocol": protocol,
               "fill_model": "v3", "universe_policy": "all"}
    retired = {**_result("multi_asset_trend", 0.2), "protocol": protocol,
               "fill_model": "v3", "universe_policy": "all"}
    (tmp_path / "control.json").write_text(json.dumps(control))
    (tmp_path / "retired.json").write_text(json.dumps(retired))
    assert {r["config_id"] for r in report.load_results(tmp_path)} == {
        "spy_benchmark", "multi_asset_trend",
    }


def test_report_labels_retained_result_as_retired(tmp_path):
    protocol = {"anchor": "2026-09-04", "train_months": 24,
                "validate_months": 12, "step_months": 12, "n_folds": 10}
    for cid, total in (("spy_benchmark", 0.1), ("multi_asset_trend", 0.2)):
        fold = {**_fold(total), "index": 1, "train_start": "2023-01-01",
                "n_validate_fills": 1, "validate_universe": 10,
                "train": {"start_date": "2023-01-01", "end_date": "2025-01-01",
                          "total_return": 0.1, "cagr": 0.05},
                "validate": {"start_date": "2025-01-01", "end_date": "2026-01-01",
                             "total_return": total, "cagr": total, "vol_ann": 0.1,
                             "sharpe": 1.0, "max_dd": -0.1}}
        payload = {"config_id": cid, "name": cid, "strategy": cid,
                   "cadence": "monthly", "protocol": protocol,
                   "fill_model": "v3", "universe_policy": "all",
                   "folds": [fold],
                   "summary": {"n_folds_ok": 1, "validate_win_rate": 1.0,
                               "mean_validate_total": total}}
        payload.pop("source_sha256", None)
        (tmp_path / f"{cid}.json").write_text(json.dumps(payload))
    out = tmp_path / "out"
    report.write_reports(tmp_path, out)
    assert "RETIRED (no-benchmark)" in (out / "README.md").read_text()
    retired_page = (out / "multi_asset_trend.md").read_text()
    assert "verdict **RETIRED (no-benchmark)**" in retired_page
    assert "Legacy/unstamped artifact" in retired_page
    assert "Relative comparison unavailable" in retired_page
    assert "Reference benchmark" not in retired_page


def test_load_results_never_mixes_fill_models(tmp_path):
    proto = {"anchor": "2026-09-04", "train_months": 24,
             "validate_months": 12, "step_months": 12, "n_folds": 10}
    old = {**_result("ew_benchmark", 0.3), "protocol": proto,
           "fill_model": "v2", "universe_policy": "all"}
    new = {**_result("spy_benchmark", 0.1), "protocol": proto,
           "fill_model": "v3", "universe_policy": "all"}
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    assert [r["config_id"] for r in report.load_results(tmp_path)] == ["spy_benchmark"]


def test_load_results_never_mixes_source_trees_but_keeps_legacy_retirement(tmp_path):
    proto = {"anchor": "2026-09-04", "train_months": 24,
             "validate_months": 12, "step_months": 12, "n_folds": 10}
    common = {"protocol": proto, "fill_model": "v3", "universe_policy": "all"}
    payloads = [
        {**_result("spy_benchmark", 0.1), **common, "source_sha256": "tree-a"},
        {**_result("dual_momentum", 0.2), **common, "source_sha256": "tree-a"},
        {**_result("ew_benchmark", 0.3), **common, "source_sha256": "tree-b"},
        {**_result("sector_momentum", 0.4), **common, "source_sha256": None},
        {**_result("multi_asset_trend", 0.5), **common, "source_sha256": None},
    ]
    for payload in payloads:
        (tmp_path / f"{payload['config_id']}.json").write_text(json.dumps(payload))
    loaded = report.load_results(tmp_path)
    assert {r["config_id"] for r in loaded} == {
        "spy_benchmark", "dual_momentum", "multi_asset_trend",
    }
    assert next(r for r in loaded if r["config_id"] == "multi_asset_trend").get(
        "source_sha256") is None


@pytest.mark.parametrize("field,a,b", [
    ("initial_cash", 39_000.0, 100_000.0),
    ("execution_profile", {"id": "baseline_v1"}, {"id": "cost_2x_v1"}),
    (
        "execution_profile",
        {"id": "baseline_v1", "fixed_adverse_bps": 5.0},
        {"id": "baseline_v1", "fixed_adverse_bps": 25.0},
    ),
    ("data_snapshot", {"sha256": "before"}, {"sha256": "after"}),
    (
        "comparison",
        {"protocol": "control-v1", "control_id": "spy_benchmark"},
        {"protocol": "control-v2", "control_id": "spy_benchmark"},
    ),
])
def test_load_results_never_mixes_capital_cost_or_data_cohorts(tmp_path, field, a, b):
    proto = {"anchor": "2026-09-04", "train_months": 24,
             "validate_months": 12, "step_months": 12, "n_folds": 10}
    common = {"protocol": proto, "fill_model": "v4", "universe_policy": "all",
              "source_sha256": "same-tree"}
    left = {**_result("spy_benchmark", 0.1), **common, field: a}
    right = {**_result("dual_momentum", 0.2), **common, field: b}
    (tmp_path / "left.json").write_text(json.dumps(left))
    (tmp_path / "right.json").write_text(json.dumps(right))
    loaded = report.load_results(tmp_path)
    assert len(loaded) == 1
