import json

import pytest

from farm.sweep import sweep


def _result(config_id: str) -> dict:
    return {
        "config_id": config_id,
        "source_sha256": "source-a",
        "fill_model": "v4",
        "universe_policy": "all",
        "initial_cash": 39_000.0,
        "execution_profile": {"id": "baseline_v1"},
        "data_snapshot": {"sha256": "data-a"},
        "protocol": {"anchor": "2026-09-04", "n_folds": 10},
        "data_quality_class": "current_universe_survivor_biased",
        "folds": [{
            "first_session": "2024-01-01",
            "last_session": "2024-12-31",
            "status": "ok",
            "validate": {"total_return": 0.10, "max_dd": -0.10},
        }],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "source-b"),
        ("fill_model", "v3"),
        ("universe_policy", "exclude-leveraged"),
        ("initial_cash", 100_000.0),
        ("execution_profile", {"id": "cost_2x_v1"}),
        ("execution_profile", {"id": "baseline_v1", "commission_bps": 99}),
        ("data_snapshot", {"sha256": "data-b"}),
        ("protocol", {"anchor": "2026-09-05", "n_folds": 10}),
    ],
)
def test_rank_excludes_candidate_from_different_research_cohort(
        tmp_path, field, value):
    results = tmp_path / "probe" / "results"
    results.mkdir(parents=True)
    bench = _result("ew_benchmark")
    candidate = _result("sweep__probe__candidate")
    candidate[field] = value
    (results / "ew_benchmark.json").write_text(json.dumps(bench))
    (results / "sweep__probe__candidate.json").write_text(json.dumps(candidate))

    ranked = sweep.rank("probe", out_root=tmp_path, n_trials=1)

    assert ranked["rows"] == []
    assert ranked["excluded"] == [{
        "id": "sweep__probe__candidate",
        "reason": "different research cohort from benchmark",
    }]


def test_rank_excludes_candidate_from_different_evidence_class(tmp_path):
    results = tmp_path / "probe" / "results"
    results.mkdir(parents=True)
    bench = _result("ew_benchmark")
    candidate = _result("sweep__probe__candidate")
    candidate["data_quality_class"] = "static_fundamental_lookahead"
    (results / "ew_benchmark.json").write_text(json.dumps(bench))
    (results / "sweep__probe__candidate.json").write_text(json.dumps(candidate))

    ranked = sweep.rank("probe", out_root=tmp_path, n_trials=1)

    assert ranked["rows"] == []
    assert ranked["excluded"] == [{
        "id": "sweep__probe__candidate",
        "reason": "different data-quality class from benchmark",
    }]


def test_rank_fails_closed_when_benchmark_provenance_is_missing(tmp_path):
    results = tmp_path / "probe" / "results"
    results.mkdir(parents=True)
    bench = _result("ew_benchmark")
    del bench["data_snapshot"]
    (results / "ew_benchmark.json").write_text(json.dumps(bench))

    with pytest.raises(SystemExit, match="benchmark has invalid research provenance"):
        sweep.rank("probe", out_root=tmp_path, n_trials=1)


def test_rank_excludes_candidate_with_missing_provenance(tmp_path):
    results = tmp_path / "probe" / "results"
    results.mkdir(parents=True)
    bench = _result("ew_benchmark")
    candidate = _result("sweep__probe__candidate")
    del candidate["source_sha256"]
    (results / "ew_benchmark.json").write_text(json.dumps(bench))
    (results / "sweep__probe__candidate.json").write_text(json.dumps(candidate))

    ranked = sweep.rank("probe", out_root=tmp_path, n_trials=1)
    assert ranked["rows"] == []
    assert ranked["excluded"][0]["reason"] == "missing required research provenance"
