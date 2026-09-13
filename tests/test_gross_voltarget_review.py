import json
from copy import deepcopy

import pytest

from farm import gross_voltarget_review as review


def _result(config_id, strategy, returns, vols, drawdowns, *, provenance=True):
    result = {
        "config_id": config_id,
        "strategy": strategy,
        "fill_model": "v4",
        "initial_cash": 39_000.0,
        "screen_source": "hist",
        "universe_policy": "all",
        "span_start": "2014-01-01",
        "span_end": "2026-01-01",
        "sessions": 3_000,
        "screen_rows": 1_000,
        "protocol": {"anchor": "2026-01-01", "n_folds": len(returns)},
        "folds": [
            {
                "index": i,
                "status": "ok",
                "validate": {"total_return": ret, "vol_ann": vol, "max_dd": dd},
            }
            for i, (ret, vol, dd) in enumerate(zip(returns, vols, drawdowns, strict=True), 1)
        ],
    }
    if provenance:
        result.update(
            source_sha256="source-a",
            data_snapshot={"sha256": "data-a"},
            execution_profile={"id": "baseline_v1"},
        )
    return result


def _write_fixture(tmp_path, *, provenance=True):
    dynamic_dir = tmp_path / "dynamic"
    static_dir = tmp_path / "static"
    dynamic_dir.mkdir()
    static_dir.mkdir()
    bench = _result("ew_benchmark", "ew_benchmark", [0.10, 0.10, 0.10],
                    [0.20, 0.30, 0.40], [-0.20] * 3, provenance=provenance)
    for root in (dynamic_dir, static_dir):
        (root / "ew_benchmark.json").write_text(json.dumps(bench))
    for config_id in review.EXPECTED_DYNAMIC_IDS:
        value = _result(config_id, "ew_gross_voltarget", [0.09, 0.11, 0.13],
                        [0.10, 0.20, 0.30], [-0.10] * 3, provenance=provenance)
        (dynamic_dir / f"{config_id}.json").write_text(json.dumps(value))
    for i, config_id in enumerate(sorted(review.EXPECTED_STATIC_IDS)):
        vol = 0.08 + i * 0.06
        value = _result(config_id, "ew_static_exposure", [0.08] * 3,
                        [vol] * 3, [-0.10] * 3, provenance=provenance)
        (static_dir / f"{config_id}.json").write_text(json.dumps(value))
    return dynamic_dir, static_dir


def test_evaluate_uses_nearest_static_fold_and_never_promotes(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path)

    result = review.evaluate(dynamic_dir, static_dir)

    assert result["decision"] == "INCONCLUSIVE-LEGACY"
    assert result["automatic_action"] == "none"
    assert result["provenance_complete"] is True
    assert len(result["rows"]) == 9
    row = result["rows"][0]
    assert [fold["matched_static_vol_ann"] for fold in row["folds"]] == [
        pytest.approx(0.08), pytest.approx(0.20), pytest.approx(0.32)
    ]


def test_evaluate_marks_missing_provenance_as_legacy(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path, provenance=False)
    assert review.evaluate(dynamic_dir, static_dir)["provenance_complete"] is False


def test_evaluate_ignores_duplicate_benchmark_run_timing(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path)
    path = static_dir / "ew_benchmark.json"
    result = json.loads(path.read_text())
    result["generated_utc"] = "later"
    result["runtime_s"] = 99.0
    result["folds"][0]["runtime_s"] = 9.0
    path.write_text(json.dumps(result))

    assert review.evaluate(dynamic_dir, static_dir)["decision"] == "INCONCLUSIVE-LEGACY"


def test_evaluate_rejects_economically_different_benchmarks(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path)
    path = static_dir / "ew_benchmark.json"
    result = json.loads(path.read_text())
    result["folds"][0]["validate"]["total_return"] += 0.01
    path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="benchmark folds differ"):
        review.evaluate(dynamic_dir, static_dir)


def test_evaluate_rejects_mismatched_cohort(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path)
    path = next(dynamic_dir.glob("sweep__*.json"))
    result = json.loads(path.read_text())
    result["fill_model"] = "changed"
    path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="cohort mismatch"):
        review.evaluate(dynamic_dir, static_dir)


def test_evaluate_rejects_non_ok_fold(tmp_path):
    dynamic_dir, static_dir = _write_fixture(tmp_path)
    path = next(dynamic_dir.glob("sweep__*.json"))
    result = json.loads(path.read_text())
    result = deepcopy(result)
    result["folds"][0]["status"] = "inert"
    path.write_text(json.dumps(result))

    with pytest.raises(ValueError, match="is not ok"):
        review.evaluate(dynamic_dir, static_dir)
