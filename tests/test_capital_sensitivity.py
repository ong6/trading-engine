import json
from pathlib import Path

import pytest

from farm import capital_sensitivity as cs


def test_grid_runs_full_replays_and_isolates_outputs(monkeypatch, tmp_path):
    calls = []

    def fake_replay(con, config_id, window, **kwargs):
        calls.append((config_id, window, kwargs))
        profile_id = kwargs["execution_profile"]
        return {
            "initial_cash": kwargs["initial_cash"], "total_return": 0.1,
            "n_fills": 3, "n_rejected": 0, "n_capacity_rejected": 0,
            "capacity_rejected_notional": 0.0, "p95_participation": 0.001,
            "max_participation": 0.002, "gross_traded_notional": 1000.0,
            "turnover_on_initial_cash": 0.1, "modeled_price_cost_dollars": 1.0,
            "modeled_total_cost_dollars": 1.0,
            "source_sha256": "source-a", "source_file_count": 42,
            "config_sha256": "config-a", "fill_model": "v4",
            "universe_policy": "exclude_leveraged_inverse",
            "data_quality_class": "fixed_etf_history",
            "data_snapshot": {"sha256": "data-a", "tables": {}},
            "execution_profile": {"id": profile_id, "max_participation": 0.01},
        }

    monkeypatch.setattr(cs.replay, "run_replay", fake_replay)
    out = cs.run_grid(
        object(), "probe", "1y", capitals=(10_000.0, 39_000.0),
        profiles=("baseline_v1", "cost_2x_v1"), out_dir=tmp_path / "out",
        scratch_root=tmp_path / "scratch", verbose=False)
    assert len(calls) == 4 and len(out["cells"]) == 4
    assert {c[2]["initial_cash"] for c in calls} == {10_000.0, 39_000.0}
    assert {c[2]["execution_profile"] for c in calls} == {
        "baseline_v1", "cost_2x_v1"}
    for _, _, kwargs in calls:
        assert kwargs["write_result"] is True
        assert Path(kwargs["results_dir"]).is_relative_to(tmp_path / "out")
    assert (tmp_path / "out" / "probe" / "1y" / "summary.json").exists()
    assert (tmp_path / "out" / "probe" / "1y" / "README.md").exists()
    assert out["cohort"] == {
        "config_sha256": "config-a",
        "data_quality_class": "fixed_etf_history",
        "data_snapshot_sha256": "data-a",
        "fill_model": "v4",
        "source_file_count": 42,
        "source_sha256": "source-a",
        "universe_policy": "exclude_leveraged_inverse",
    }
    assert out["capacity_observations"] == [
        {"first_capacity_reject_capital": None,
         "largest_zero_reject_capital": 39000.0,
         "profile_id": "baseline_v1"},
        {"first_capacity_reject_capital": None,
         "largest_zero_reject_capital": 39000.0,
         "profile_id": "cost_2x_v1"},
    ]
    assert all(c["fill_model"] == "v4" for c in out["cells"])
    assert all(c["execution_profile"]["id"] == c["profile_id"]
               for c in out["cells"])
    markdown = (tmp_path / "out" / "probe" / "1y" / "README.md").read_text()
    assert "Total rejects" in markdown
    assert "Market cost $" in markdown
    assert "Total cost $" in markdown
    assert "Largest tested capital with zero capacity rejects" in markdown


def test_grid_rejects_mixed_replay_cohort(monkeypatch, tmp_path):
    calls = 0

    def fake_replay(con, config_id, window, **kwargs):
        nonlocal calls
        calls += 1
        return {
            "initial_cash": kwargs["initial_cash"],
            "execution_profile": {"id": kwargs["execution_profile"],
                                  "max_participation": 0.01},
            "source_sha256": f"source-{calls}", "source_file_count": 42,
            "config_sha256": "config-a", "fill_model": "v4",
            "universe_policy": "exclude_leveraged_inverse",
            "data_quality_class": "fixed_etf_history",
            "data_snapshot": {"sha256": "data-a", "tables": {}},
            "n_capacity_rejected": 0,
        }

    monkeypatch.setattr(cs.replay, "run_replay", fake_replay)
    with pytest.raises(ValueError, match="mixed capital-sensitivity cohort"):
        cs.run_grid(
            object(), "probe", "1y", capitals=(10_000.0, 39_000.0),
            profiles=("baseline_v1",), out_dir=tmp_path / "out",
            scratch_root=tmp_path / "scratch", verbose=False)


def test_grid_rejects_wrong_execution_profile_stamp(monkeypatch, tmp_path):
    def fake_replay(con, config_id, window, **kwargs):
        return {
            "initial_cash": kwargs["initial_cash"],
            "execution_profile": {"id": "wrong"},
            "source_sha256": "source-a", "source_file_count": 42,
            "config_sha256": "config-a", "fill_model": "v4",
            "universe_policy": "exclude_leveraged_inverse",
            "data_quality_class": "fixed_etf_history",
            "data_snapshot": {"sha256": "data-a", "tables": {}},
            "n_capacity_rejected": 0,
        }

    monkeypatch.setattr(cs.replay, "run_replay", fake_replay)
    with pytest.raises(ValueError, match="execution profile mismatch"):
        cs.run_grid(
            object(), "probe", "1y", capitals=(10_000.0,),
            profiles=("baseline_v1",), out_dir=tmp_path / "out",
            scratch_root=tmp_path / "scratch", verbose=False)


def test_rebuild_summary_uses_complete_existing_cells(tmp_path):
    root = tmp_path / "probe" / "1y"
    for profile_id in ("baseline_v1", "cost_2x_v1"):
        for capital in (10_000.0, 39_000.0):
            cell_dir = root / "cells" / profile_id / cs.capital_slug(capital)
            cell_dir.mkdir(parents=True)
            rejected = 2 if capital == 39_000.0 else 0
            result = {
                "initial_cash": capital, "total_return": 0.1, "max_dd": -0.1,
                "n_fills": 3, "n_rejected": rejected,
                "n_capacity_rejected": rejected,
                "capacity_rejected_notional": 500.0 if rejected else 0.0,
                "p95_participation": 0.001, "max_participation": 0.002,
                "gross_traded_notional": 1000.0,
                "turnover_on_initial_cash": 0.1,
                "modeled_price_cost_dollars": 1.0,
                "modeled_total_cost_dollars": 1.5,
                "source_sha256": "source-a", "source_file_count": 42,
                "config_sha256": "config-a", "fill_model": "v4",
                "universe_policy": "all",
                "data_quality_class": "fixed_etf_history",
                "data_snapshot": {"sha256": "data-a", "tables": {}},
                "execution_profile": cs.execution.resolve_profile(profile_id).as_dict(),
            }
            (cell_dir / "probe__1y.json").write_text(json.dumps(result))

    out = cs.rebuild_summary(
        "probe", "1y", capitals=(10_000.0, 39_000.0),
        profiles=("baseline_v1", "cost_2x_v1"), out_dir=tmp_path)

    assert len(out["cells"]) == 4
    assert out["capacity_observations"] == [
        {"first_capacity_reject_capital": 39000.0,
         "largest_zero_reject_capital": 10000.0,
         "profile_id": "baseline_v1"},
        {"first_capacity_reject_capital": 39000.0,
         "largest_zero_reject_capital": 10000.0,
         "profile_id": "cost_2x_v1"},
    ]
    assert (root / "summary.json").exists()
    assert (root / "README.md").exists()


def test_rebuild_summary_fails_closed_when_a_cell_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing capital-sensitivity cell"):
        cs.rebuild_summary(
            "probe", "1y", capitals=(10_000.0,), profiles=("baseline_v1",),
            out_dir=tmp_path)


def test_capacity_observation_reports_no_passing_tested_capital():
    rows = [
        {"profile_id": "baseline_v1", "initial_cash": 10_000.0,
         "n_capacity_rejected": 4},
        {"profile_id": "baseline_v1", "initial_cash": 39_000.0,
         "n_capacity_rejected": 25},
    ]
    assert cs.capacity_observations(rows, ("baseline_v1",)) == [{
        "profile_id": "baseline_v1",
        "largest_zero_reject_capital": None,
        "first_capacity_reject_capital": 10_000.0,
    }]
