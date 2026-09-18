"""Frozen credit-confirmed alpha experiment behavior and evidence gates."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from farm import credit_confirmed_experiment as experiment
from sim.strategies import REGISTRY


def _fold(index: int, candidate: bool) -> dict:
    step = 1.025 if candidate else 1.01
    year = 2016 + index
    return {
        "index": index,
        "status": "ok",
        "split_date": f"{year}-01-01",
        "validate_end": f"{year}-12-31",
        "validate": {"max_dd": -0.10 if candidate else -0.09},
        "validate_monthly_equity": [
            [f"{year}-01", 100.0],
            [f"{year}-02", 100.0 * step],
            [f"{year}-03", 100.0 * step * step],
        ],
        "n_rejected": 0,
        "n_pending": 0,
        "n_capacity_rejected": 0,
        "state_rebuild_matches": True,
    }


def _result(config_id: str, scenario: str, candidate: bool) -> dict:
    profile, _delay = experiment.SCENARIOS[scenario]
    return {
        "source_sha256": "source",
        "data_snapshot": {"sha256": "data"},
        "research_input": {
            "sha256": "facts",
            "incomplete_signal_dates": [],
        },
        "protocol": {"anchor": "2026-09-17", "n_folds": 10},
        "fill_model": "v4",
        "execution_profile": {"id": profile},
        "config_id": config_id,
        "folds": [_fold(index, candidate) for index in range(1, 11)],
    }


def _results() -> dict:
    return {
        scenario: {
            experiment.CANDIDATE_ID: _result(
                experiment.CANDIDATE_ID, scenario, True
            ),
            experiment.CONTROL_ID: _result(
                experiment.CONTROL_ID, scenario, False
            ),
        }
        for scenario in experiment.SCENARIOS
    }


def test_clean_material_positive_effect_passes_all_frozen_gates():
    report = experiment.evaluate(_results())

    assert report["decision"] == "PASS-HISTORICAL"
    assert all(report["gates"].values())
    assert report["paper_only"] is True
    assert report["automatic_action"] == "none"


def test_minimum_effect_and_delay_stress_fail_independently():
    results = _results()
    for scenario in results.values():
        for fold in scenario[experiment.CANDIDATE_ID]["folds"]:
            fold["validate_monthly_equity"] = [
                [fold["validate_monthly_equity"][0][0], 100.0],
                [fold["validate_monthly_equity"][1][0], 101.05],
                [fold["validate_monthly_equity"][2][0], 102.11025],
            ]
    delayed = results["delay_1_session_v1"][experiment.CANDIDATE_ID]
    for fold in delayed["folds"]:
        fold["validate_monthly_equity"] = [
            [fold["validate_monthly_equity"][0][0], 100.0],
            [fold["validate_monthly_equity"][1][0], 99.0],
            [fold["validate_monthly_equity"][2][0], 98.01],
        ]

    report = experiment.evaluate(results)

    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["baseline_minimum_effect_met"] is False
    assert report["gates"]["delay_stress_excess_positive"] is False


def test_incomplete_signal_or_scenario_identity_drift_fails_closed():
    results = _results()
    for scenario in results.values():
        for value in scenario.values():
            value["research_input"] = {
                "sha256": "facts-with-gap",
                "incomplete_signal_dates": ["2020-01-31"],
            }
    report = experiment.evaluate(results)
    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["execution_data_and_accounting_clean"] is False

    drift = deepcopy(_results())
    for value in drift["cost_2x_v1"].values():
        value["data_snapshot"] = {"sha256": "different"}
    try:
        experiment.evaluate(drift)
    except ValueError as exc:
        assert "scenario research cohort mismatch" in str(exc)
    else:
        raise AssertionError("scenario identity drift was accepted")


def test_signal_uses_exact_frozen_total_return_comparisons(monkeypatch):
    values = {"SPY": 0.20, "BIL": 0.04, "HYG": 0.03, "LQD": 0.02}
    calls = []

    def total_return(_con, ticker, as_of, lookback):
        calls.append((ticker, as_of, lookback))
        return values[ticker]

    monkeypatch.setattr(experiment, "total_return", total_return)
    as_of = date(2026, 8, 31)
    risk_on, facts = experiment._signal(object(), as_of)
    assert risk_on is True and facts["complete"] is True
    assert calls == [
        ("SPY", as_of, 252),
        ("BIL", as_of, 252),
        ("HYG", as_of, 63),
        ("LQD", as_of, 63),
    ]
    values["HYG"] = values["LQD"]
    assert experiment._signal(object(), as_of)[0] is False


def test_delay_scenario_waits_one_additional_session(monkeypatch):
    month_end, next_session = date(2026, 8, 31), date(2026, 9, 1)

    class Result:
        def fetchone(self):
            return (month_end,)

    class Connection:
        def execute(self, _sql, params):
            class PriorResult:
                def fetchone(self):
                    return (month_end if params[0] == next_session else None,)

            return PriorResult()

    monkeypatch.setattr(
        experiment.calendar, "is_month_signal", lambda _con, day: day == month_end
    )
    assert experiment._decision_date(Connection(), month_end, 1) is None
    assert experiment._decision_date(Connection(), next_session, 1) == month_end


def test_research_strategies_are_not_in_production_registry():
    assert experiment.CANDIDATE_ID not in REGISTRY
    assert experiment.CONTROL_ID not in REGISTRY


def test_replay_scope_installs_and_removes_research_strategies(monkeypatch, tmp_path):
    calls = []

    def run_book(*args, **kwargs):
        assert REGISTRY[experiment.CANDIDATE_ID] is experiment.CreditConfirmedSpy
        assert REGISTRY[experiment.CONTROL_ID] is experiment.CreditConfirmedStaticControl
        assert kwargs["scratch_prepare"] is experiment.prepare_inputs
        calls.append((args[1], kwargs["execution_profile"]))

    monkeypatch.setattr(experiment.runner, "run_book", run_book)
    experiment.run_replays(
        object(), out_dir=tmp_path, scratch_root=tmp_path / "scratch"
    )
    assert len(calls) == 6
    assert experiment.CANDIDATE_ID not in REGISTRY
    assert experiment.CONTROL_ID not in REGISTRY


def test_input_fingerprint_uses_json_safe_control_dates(monkeypatch):
    sessions = [date(2026, 8, 31)]

    class Result:
        def fetchone(self):
            return (0.5,)

    class Connection:
        def execute(self, *_args):
            return Result()

    monkeypatch.setattr(experiment.runner, "data_floor", lambda *_args: date(2008, 1, 1))
    monkeypatch.setattr(
        experiment.protocol,
        "make_folds",
        lambda _anchor: [
            experiment.protocol.Fold(
                1, date(2025, 1, 1), date(2026, 1, 1), date(2026, 12, 31)
            )
        ],
    )
    monkeypatch.setattr(experiment.calendar, "is_month_signal", lambda *_args: True)
    monkeypatch.setattr(
        experiment,
        "_signal",
        lambda _con, day: (True, {"date": day.isoformat(), "complete": True}),
    )

    result = experiment.prepare_inputs(
        Connection(), Connection(), sessions[0], sessions[0], sessions
    )

    assert len(result["sha256"]) == 64
    assert result["fold_controls"][0]["fold_start"] == "2026-08-31"
