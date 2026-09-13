"""Fail-closed checks shared by isolated paired walk-forward experiments."""

from copy import deepcopy

import pytest

from farm import paired_walkforward as paired
from farm.walkforward import protocol
from sim import execution


def _pending(signal_date: str, *, order_id: int = 1) -> dict:
    return {
        "id": order_id,
        "ticker": "SPY",
        "side": "buy",
        "signal_date": signal_date,
    }


def _fold(index: int) -> dict:
    last_session = f"2025-{index:02d}-28"
    return {
        "index": index,
        "status": "ok",
        "split_date": f"2024-{index:02d}-01",
        "validate_end": last_session,
        "last_session": last_session,
        "n_pending": 0,
        "pending_orders": [],
        "n_rejected": 0,
        "n_capacity_rejected": 0,
        "state_rebuild_matches": True,
        "validate": {"max_dd": -0.10},
        "validate_monthly_equity": [
            [f"2025-{index:02d}", 100.0],
            [f"2025-{index:02d}-end", 101.0],
        ],
    }


def _pair() -> tuple[dict, dict]:
    folds = [_fold(index) for index in range(1, protocol.N_FOLDS + 1)]
    return {"folds": folds}, {"folds": deepcopy(folds)}


def test_terminal_pending_clean_accepts_symmetric_terminal_counts():
    candidate, control = _pair()
    for result in (candidate, control):
        fold = result["folds"][-1]
        fold["pending_orders"] = [_pending(fold["last_session"])]
        fold["n_pending"] = 1

    assert paired.terminal_pending_clean(candidate, control) is True


def test_terminal_pending_clean_rejects_asymmetric_pending_counts():
    candidate, control = _pair()
    fold = candidate["folds"][-1]
    fold["pending_orders"] = [_pending(fold["last_session"])]
    fold["n_pending"] = 1

    assert paired.terminal_pending_clean(candidate, control) is False


def test_terminal_pending_clean_rejects_nonterminal_signal_date():
    candidate, control = _pair()
    for result in (candidate, control):
        fold = result["folds"][-1]
        fold["pending_orders"] = [_pending("2000-01-01")]
        fold["n_pending"] = 1

    assert paired.terminal_pending_clean(candidate, control) is False


def test_terminal_pending_clean_rejects_count_detail_mismatch():
    candidate, control = _pair()
    for result in (candidate, control):
        result["folds"][-1]["n_pending"] = 1

    assert paired.terminal_pending_clean(candidate, control) is False


def test_terminal_pending_clean_rejects_missing_fold():
    candidate, control = _pair()
    control["folds"].pop()

    assert paired.terminal_pending_clean(candidate, control) is False


def test_fold_integrity_rejects_duplicate_geometry_and_index():
    candidate, control = _pair()
    candidate["folds"][-1] = deepcopy(candidate["folds"][-2])

    assert paired.execution_check(candidate)["all_folds_ok"] is False
    assert paired.terminal_pending_clean(candidate, control) is False


def test_fold_integrity_rejects_extra_failed_fold():
    candidate, _control = _pair()
    failed = _fold(protocol.N_FOLDS + 1)
    failed["status"] = "failed"
    candidate["folds"].append(failed)

    assert paired.execution_check(candidate)["all_folds_ok"] is False


def _experiment_result(profile_id: str, *, candidate: bool) -> dict:
    result = {
        "source_sha256": "source",
        "source_file_count": 10,
        "fill_model": "v4",
        "initial_cash": 39_000.0,
        "execution_profile": {"id": profile_id},
        "data_snapshot": {"sha256": "data"},
        "data_quality_class": "fixed_etf_history",
        "protocol": {"anchor": "2026-09-04", "n_folds": protocol.N_FOLDS},
        "comparison": {"protocol": "probe-v1"},
        "research_input": {"sha256": "input"},
        "folds": [_fold(index) for index in range(1, protocol.N_FOLDS + 1)],
    }
    if candidate:
        for fold in result["folds"]:
            fold["validate_monthly_equity"][-1][-1] = 102.0
    return result


def _experiment_results() -> dict:
    return {
        profile_id: {
            "candidate": _experiment_result(profile_id, candidate=True),
            "control": _experiment_result(profile_id, candidate=False),
        }
        for profile_id in (execution.BASELINE.id, execution.COST_2X.id)
    }


def _evaluate(results: dict, *, pending_policy: str = "symmetric_terminal") -> dict:
    return paired.evaluate_experiment(
        results,
        profiles=(execution.BASELINE.id, execution.COST_2X.id),
        candidate_id="candidate",
        control_id="control",
        charter_id="PROBE-v1",
        input_complete=lambda result: result["research_input"]["sha256"] == "input",
        mean_block=4,
        pending_policy=pending_policy,
    )


def test_evaluator_requires_drawdown_evidence_for_every_fold():
    results = _experiment_results()
    del results[execution.BASELINE.id]["candidate"]["folds"][-1]["validate"]["max_dd"]

    report = _evaluate(results)

    assert report["decision"] == "REJECT-V1"
    assert report["gates"]["drawdown_within_five_points_every_fold"] is False


def test_evaluator_none_pending_policy_rejects_terminal_intents():
    results = _experiment_results()
    for side in ("candidate", "control"):
        fold = results[execution.BASELINE.id][side]["folds"][-1]
        fold["pending_orders"] = [_pending(fold["last_session"])]
        fold["n_pending"] = 1

    assert _evaluate(results, pending_policy="none")["gates"][
        "execution_data_and_accounting_clean"
    ] is False


def test_evaluator_rejects_unknown_pending_policy():
    with pytest.raises(ValueError, match="unknown pending policy"):
        _evaluate(_experiment_results(), pending_policy="guess")
