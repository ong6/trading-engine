"""Sell-in-May experiment isolation and fail-closed decision gates."""
from copy import deepcopy

from farm import sell_in_may_experiment as experiment
from sim import execution
from sim.strategies import REGISTRY


def _fold(index, candidate=False, *, pending=None, dd=-0.10):
    step = 1.02 if candidate else 1.01
    pending = pending or []
    return {
        "index": index, "status": "ok", "last_session": f"202{index}-12-31",
        "split_date": f"202{index}-01-01", "validate_end": f"202{index}-12-31",
        "validate": {"max_dd": dd},
        "validate_monthly_equity": [
            [f"202{index}-01", 100.0], [f"202{index}-02", 100.0 * step],
            [f"202{index}-03", 100.0 * step * step],
        ],
        "n_rejected": 0, "n_pending": len(pending),
        "pending_orders": pending, "n_capacity_rejected": 0,
        "state_rebuild_matches": True,
    }


def _input():
    return {
        "class": experiment.DATA_CLASS, "sha256": "bars", "session_count": 3019,
        "winter_session_count": 1480,
        "derived_spy_weight": experiment.STATIC_SPY_WEIGHT,
        "frozen_spy_weight": experiment.STATIC_SPY_WEIGHT,
        "missing_price_sessions": [],
    }


def _result(config_id, profile_id, candidate=False):
    return {
        "config_id": config_id, "source_sha256": "source", "source_file_count": 100,
        "fill_model": "v4", "initial_cash": 39_000.0,
        "execution_profile": {"id": profile_id},
        "data_snapshot": {"sha256": "data"}, "data_quality_class": experiment.DATA_CLASS,
        "protocol": {"anchor": "2026-09-04", "n_folds": 10},
        "comparison": {"protocol": experiment.COMPARISON_PROTOCOL},
        "research_input": _input(),
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


def test_clean_positive_pair_passes_historical_gate():
    report = experiment.evaluate(_results())
    assert report["decision"] == "PASS-HISTORICAL"
    assert all(report["gates"].values())
    assert report["paper_only"] is True and report["automatic_action"] == "none"


def test_asymmetric_terminal_pending_rejects_v1():
    results = _results()
    for profile in experiment.PROFILES:
        fold = results[profile][experiment.CANDIDATE_ID]["folds"][-1]
        fold["pending_orders"] = [{
            "id": 1, "ticker": "SPY", "side": "buy",
            "signal_date": fold["last_session"],
        }]
        fold["n_pending"] = 1
    report = experiment.evaluate(results)
    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["execution_data_and_accounting_clean"] is False


def test_input_hash_mismatch_fails_closed():
    results = _results()
    results[execution.BASELINE.id][experiment.CANDIDATE_ID]["research_input"][
        "sha256"
    ] = "changed"
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "cohort mismatch" in str(exc)
    else:
        raise AssertionError("mismatched input cohort was accepted")


def test_cross_profile_source_mismatch_fails_closed():
    results = deepcopy(_results())
    for result in results[execution.COST_2X.id].values():
        result["source_sha256"] = "changed"
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "baseline/stress" in str(exc)
    else:
        raise AssertionError("cross-profile mismatch was accepted")


def test_replays_scope_registry_and_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_run_book(*args, **kwargs):
        assert REGISTRY[experiment.CONTROL_ID] is experiment.SellInMayStaticExposure
        assert REGISTRY[experiment.CANDIDATE_ID] is experiment.SellInMaySpy
        assert kwargs["scratch_prepare"] is experiment.capture_price_input
        calls.append((args[1], kwargs["execution_profile"]))

    monkeypatch.setattr(experiment.runner, "run_book", fake_run_book)
    experiment.run_replays(object(), out_dir=tmp_path, scratch_root=tmp_path / "scratch")
    assert len(calls) == 4
    assert experiment.CONTROL_ID not in REGISTRY
    assert experiment.CANDIDATE_ID not in REGISTRY
