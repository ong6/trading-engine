"""VIX-term experiment isolation and fail-closed decision gates."""
from copy import deepcopy
from datetime import date

import duckdb

from farm import vix_term_experiment as experiment
from sim import execution
from sim.strategies import REGISTRY


def _fold(index, candidate=False, *, dd=-0.10):
    step = 1.02 if candidate else 1.01
    return {
        "index": index, "status": "ok",
        "split_date": f"202{index}-01-01", "validate_end": f"202{index}-12-31",
        "validate": {"max_dd": dd},
        "validate_monthly_equity": [
            [f"202{index}-01", 100.0], [f"202{index}-02", 100.0 * step],
            [f"202{index}-03", 100.0 * step * step],
        ],
        "n_rejected": 0, "n_pending": 0, "n_capacity_rejected": 0,
        "state_rebuild_matches": True,
    }


def _result(config_id, profile_id, candidate=False):
    return {
        "config_id": config_id, "source_sha256": "source", "source_file_count": 100,
        "fill_model": "v4", "initial_cash": 39_000.0,
        "execution_profile": {"id": profile_id},
        "data_snapshot": {"sha256": "data"},
        "data_quality_class": experiment.DATA_CLASS,
        "protocol": {"anchor": "2026-09-03", "n_folds": 10},
        "comparison": {"protocol": experiment.COMPARISON_PROTOCOL},
        "research_input": {
            "class": experiment.DATA_CLASS, "sha256": "macro", "pair_count": 100,
            "session_count": 100, "missing_macro_sessions": [],
            "missing_price_sessions": [],
        },
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


def test_missing_macro_session_rejects_v1():
    results = _results()
    for profile_id in experiment.PROFILES:
        for config_id in (experiment.CANDIDATE_ID, experiment.CONTROL_ID):
            results[profile_id][config_id]["research_input"][
                "missing_macro_sessions"
            ] = ["2020-01-02"]
            results[profile_id][config_id]["research_input"][
                "pair_count"
            ] = 99
    report = experiment.evaluate(results)
    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["execution_data_and_accounting_clean"] is False


def test_macro_hash_mismatch_fails_closed():
    results = _results()
    results[execution.BASELINE.id][experiment.CANDIDATE_ID]["research_input"][
        "sha256"
    ] = "changed"
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "cohort mismatch" in str(exc)
    else:
        raise AssertionError("mismatched macro cohort was accepted")


def test_substantive_cross_profile_mismatch_fails_closed():
    results = deepcopy(_results())
    for result in results[execution.COST_2X.id].values():
        result["data_snapshot"]["sha256"] = "changed"
    try:
        experiment.evaluate(results)
    except ValueError as exc:
        assert "baseline/stress" in str(exc)
    else:
        raise AssertionError("cross-profile mismatch was accepted")


def test_prepare_reconstruction_is_complete_and_scratch_only(con):
    dates = [date(2024, 6, 3), date(2024, 6, 4)]
    for ticker in experiment.ASSETS:
        con.executemany(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES (?,?,100,100,100,100,1000000)", [(ticker, d) for d in dates]
        )
    con.execute(
        "CREATE TABLE macro_signals(series VARCHAR, obs_date DATE, value DOUBLE, "
        "fetch_as_of DATE, PRIMARY KEY(series, obs_date))"
    )
    con.executemany(
        "INSERT INTO macro_signals VALUES (?,?,?,?)",
        [(series, d, value, date(2026, 9, 7)) for d in dates
         for series, value in (("vix", 18.0), ("vix3m", 20.0))],
    )
    scratch = duckdb.connect()
    scratch.execute("CREATE TABLE macro_signals(series VARCHAR, obs_date DATE, "
                    "value DOUBLE, fetch_as_of DATE)")
    result = experiment.prepare_reconstructed_macro(
        con, scratch, dates[0], dates[-1], dates
    )
    assert result["pair_count"] == result["session_count"] == 2
    assert result["missing_macro_sessions"] == result["missing_price_sessions"] == []
    assert scratch.execute("SELECT bool_and(fetch_as_of=obs_date) FROM macro_signals").fetchone()[0]
    assert con.execute("SELECT min(fetch_as_of) FROM macro_signals").fetchone()[0] == date(2026, 9, 7)
    scratch.close()


def test_replays_scope_registry_and_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_run_book(*args, **kwargs):
        assert REGISTRY[experiment.CONTROL_ID] is experiment.VixTermStaticExposure
        assert REGISTRY[experiment.CANDIDATE_ID] is experiment.VixTermSpyTiming
        assert kwargs["scratch_prepare"] is experiment.prepare_reconstructed_macro
        calls.append((args[1], kwargs["execution_profile"]))

    monkeypatch.setattr(experiment.runner, "run_book", fake_run_book)
    experiment.run_replays(object(), out_dir=tmp_path, scratch_root=tmp_path / "scratch")
    assert len(calls) == 4
    assert experiment.CONTROL_ID not in REGISTRY
    assert experiment.CANDIDATE_ID not in REGISTRY
