import json

from farm.backtest import report


def _result(config_id, quality):
    return {
        "config_id": config_id, "data_quality_class": quality,
        "start_date": "2024-01-01", "end_date": "2025-01-01",
        "total_return": 0.2, "cagr": 0.2, "vol_ann": 0.1,
        "sharpe": 1.0, "sharpe_ex_bil": 0.9, "max_dd": -0.1,
        "worst_month": -0.05, "n_fills": 10,
    }


def test_benchmark_spreads_require_same_evidence_class():
    candidate = _result("ew_benchmark", "current_universe_survivor_biased")
    spy = _result("spy_benchmark", "fixed_etf_history")
    row = report._row(candidate, {"spy_benchmark": spy})
    assert "`current_universe_survivor_biased`" in row
    # vs-SPY must be missing because the two histories carry different bias.
    assert "| · | · | reference |" in row
    assert row.rstrip().endswith("| 10 |")


def test_benchmark_spreads_require_complete_provenance():
    candidate = _result("sector_momentum", "fixed_etf_history")
    spy = _result("spy_benchmark", "fixed_etf_history")
    assert "**uncontrolled absolute simulation**" in report._row(
        candidate, {"spy_benchmark": spy}
    )

    cohort = {
        "source_sha256": "source", "fill_model": "v4", "universe_policy": "all",
        "initial_cash": 39_000.0,
        "execution_profile": {"id": "baseline_v1", "fixed_adverse_bps": 5.0},
        "data_snapshot": {"sha256": "data"},
    }
    candidate.update(cohort)
    spy.update(cohort)
    assert "cohort-matched" in report._row(candidate, {"spy_benchmark": spy})


def test_cohort_signature_includes_capital_profile_and_data_snapshot():
    base = {"source_sha256": "s", "fill_model": "v4", "universe_policy": "all",
            "initial_cash": 39_000.0, "execution_profile": {"id": "baseline_v1"},
            "data_snapshot": {"sha256": "data-a"}}
    changed = {**base, "initial_cash": 100_000.0}
    assert report._cohort_signature(base) != report._cohort_signature(changed)
    changed_profile = {
        **base,
        "execution_profile": {"id": "baseline_v1", "fixed_adverse_bps": 99.0},
    }
    assert report._cohort_signature(base) != report._cohort_signature(changed_profile)


def test_report_selects_one_cohort_across_all_windows_and_lists_exclusions(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        report, "EXPECTED_GRID",
        [("ew_benchmark", "6mo"), ("ew_benchmark", "1y"),
         ("spy_benchmark", "6mo"), ("spy_benchmark", "1y"),
         ("sector_momentum", "1y")],
    )
    monkeypatch.setattr(report, "RETAINED_RESULTS", [])
    monkeypatch.setattr(report, "runtime_source_hash", lambda: ("current", 1))
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    rows = [
        {**_result("ew_benchmark", "fixed_etf_history"), "window": "6mo",
         "name": "EW", "strategy": "ew_benchmark", "cadence": "monthly",
         "source_sha256": "old", "fill_model": "v3"},
        {**_result("spy_benchmark", "fixed_etf_history"), "window": "6mo",
         "name": "SPY", "strategy": "spy_benchmark", "cadence": "once",
         "source_sha256": "old", "fill_model": "v3"},
        {**_result("ew_benchmark", "fixed_etf_history"), "window": "1y",
         "name": "EW", "strategy": "ew_benchmark", "cadence": "monthly",
         "source_sha256": "new", "fill_model": "v4"},
        {**_result("spy_benchmark", "fixed_etf_history"), "window": "1y",
         "name": "SPY", "strategy": "spy_benchmark", "cadence": "once",
         "source_sha256": "new", "fill_model": "v4"},
        {**_result("sector_momentum", "fixed_etf_history"), "window": "1y",
         "name": "Sector", "strategy": "sector_momentum", "cadence": "monthly",
         "source_sha256": "new", "fill_model": "v4"},
    ]
    for i, row in enumerate(rows):
        (results_dir / f"{i}.json").write_text(json.dumps(row))

    report.write_reports(results_dir, tmp_path / "out")
    text = (tmp_path / "out" / "README.md").read_text()

    assert "source `new` (stale source); fill model `v4`" in text
    assert "## Window: 1y" in text
    assert "## Window: 6mo" not in text
    assert "**Excluded as incompatible/stale:** 2 artifact(s)" in text
    assert "`ew_benchmark__6mo`" in text
    assert "`spy_benchmark__6mo`" in text
