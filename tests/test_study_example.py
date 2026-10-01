import json

import pytest

from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from farm.study.costs import CostSelection
from farm.study.examples.spy_trend import (
    SPY_200_DAY_TREND,
    _validate_cli_paths,
    run_example,
)
from farm.study.synthetic import generate_market


def test_spy_200_day_example_runs_end_to_end_on_synthetic_data(tmp_path):
    market = generate_market(71, session_count=1_900)
    report = run_example(
        market.data, tmp_path / "report",
        costs=CostSelection("ibkr_tiered_auction_v1", ("baseline_v1",)), census_n=3)
    stored = json.loads((tmp_path / "report" / "report.json").read_text())
    assert stored["run_identity"] == report["run_identity"]
    assert stored["benchmark"] == {"kind": "ticker", "mode": "gross", "ticker": "SPY"}
    assert stored["data"]["primary"]["source"] == "synthetic-primary"
    assert len(stored["folds"]) >= 6
    assert (tmp_path / "report" / "report.md").is_file()
    assert SPY_200_DAY_TREND.parameters["window_sessions"] == 200


def test_example_cli_refuses_live_store_and_tracked_output(tmp_path):
    with pytest.raises(ValueError, match="live default store"):
        _validate_cli_paths(DEFAULT_DB, tmp_path)
    with pytest.raises(ValueError, match="outside tracked"):
        _validate_cli_paths(tmp_path / "copy.duckdb", REPO_ROOT / "data" / "example")
