"""Evaluation gates for FIXED-ETF-REBAL-2026-09-07-v1."""
from copy import deepcopy

from farm import fixed_etf_rebalancing as experiment
from sim import execution
from sim.strategies import REGISTRY


def _fold(index, candidate=False, *, dd=-0.10):
    step = 1.02 if candidate else 1.01
    return {
        "index": index,
        "status": "ok",
        "split_date": f"202{index}-01-01",
        "validate_end": f"202{index}-12-31",
        "validate": {"max_dd": dd},
        "validate_monthly_equity": [
            [f"202{index}-01", 100.0],
            [f"202{index}-02", 100.0 * step],
            [f"202{index}-03", 100.0 * step * step],
        ],
        "n_rejected": 0,
        "n_pending": 0,
        "n_capacity_rejected": 0,
        "initial_entry_missing_assets": [],
        "missing_required_signal_prices": [],
        "state_rebuild_matches": True,
    }


def _result(config_id, profile_id, candidate=False):
    return {
        "config_id": config_id,
        "source_sha256": "source",
        "source_file_count": 100,
        "fill_model": "v4",
        "initial_cash": 39_000.0,
        "execution_profile": {"id": profile_id},
        "data_snapshot": {"sha256": "data"},
        "data_quality_class": "fixed_etf_history",
        "protocol": {"anchor": "2026-09-04", "n_folds": 10},
        "comparison": {"protocol": experiment.COMPARISON_PROTOCOL},
        "folds": [_fold(i, candidate, dd=-0.12 if candidate else -0.10)
                  for i in range(1, 11)],
    }


def _results():
    return {
        profile: {
            experiment.CANDIDATE_ID: _result(experiment.CANDIDATE_ID, profile, True),
            experiment.CONTROL_ID: _result(experiment.CONTROL_ID, profile, False),
        }
        for profile in experiment.PROFILES
    }


def test_all_gates_pass_for_clean_positive_pair():
    report = experiment.evaluate(_results())
    assert report["decision"] == "PASS-HISTORICAL"
    assert all(report["gates"].values())
    assert report["paper_only"] is True and report["automatic_action"] == "none"


def test_any_failed_gate_rejects_v1():
    results = _results()
    fold = results[execution.BASELINE.id][experiment.CANDIDATE_ID]["folds"][0]
    fold["n_capacity_rejected"] = 1
    report = experiment.evaluate(results)
    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["execution_and_accounting_clean"] is False


def test_drawdown_gate_is_paired_and_every_fold():
    results = _results()
    results[execution.BASELINE.id][experiment.CANDIDATE_ID]["folds"][3]["validate"]["max_dd"] = -0.20
    report = experiment.evaluate(results)
    assert report["gates"]["drawdown_within_five_points_every_fold"] is False


def test_mixed_cohort_fails_closed():
    results = _results()
    changed = deepcopy(results[execution.BASELINE.id][experiment.CANDIDATE_ID])
    changed["source_sha256"] = "different"
    results[execution.BASELINE.id][experiment.CANDIDATE_ID] = changed
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "cohort mismatch" in str(exc)
    else:
        raise AssertionError("mixed cohort was accepted")


def test_cross_profile_source_mismatch_fails_closed():
    results = _results()
    for result in results[execution.COST_2X.id].values():
        result["source_sha256"] = "different"
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "baseline/stress" in str(exc)
    else:
        raise AssertionError("cross-profile mismatch was accepted")


def test_books_are_frozen_and_rebuild_checked():
    book = experiment._book(experiment.CANDIDATE_ID, execution.BASELINE.id)
    assert book["expected_assets"] == ("SPY", "IEF", "GLD")
    assert book["quarter_end_signals"] is True
    assert book["verify_rebuild_state"] is True
    assert book["data_quality_class"] == "fixed_etf_history"
    assert book["comparison"]["control_id"] == experiment.CONTROL_ID


def test_replays_scope_research_strategies_and_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_run_book(*args, **kwargs):
        assert REGISTRY[experiment.CONTROL_ID] is experiment.FixedEtfBuyHold
        assert REGISTRY[experiment.CANDIDATE_ID] is experiment.FixedEtfRebalanced
        calls.append((args[1], kwargs["execution_profile"]))

    monkeypatch.setattr(experiment.runner, "run_book", fake_run_book)
    experiment.run_replays(object(), out_dir=tmp_path, scratch_root=tmp_path / "scratch")

    assert len(calls) == 4
    assert experiment.CONTROL_ID not in REGISTRY
    assert experiment.CANDIDATE_ID not in REGISTRY


def test_replay_failure_still_removes_research_strategies(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise RuntimeError("probe")

    monkeypatch.setattr(experiment.runner, "run_book", fail)
    try:
        experiment.run_replays(object(), out_dir=tmp_path, scratch_root=tmp_path / "scratch")
    except RuntimeError as exc:
        assert str(exc) == "probe"
    else:
        raise AssertionError("probe failure was swallowed")

    assert experiment.CONTROL_ID not in REGISTRY
    assert experiment.CANDIDATE_ID not in REGISTRY
