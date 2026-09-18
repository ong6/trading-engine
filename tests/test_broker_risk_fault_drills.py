"""Broker-risk fault-drill evidence is bounded and source-bound."""

from __future__ import annotations

import subprocess

import pytest

from server import broker_risk_fault_drills


def _passed(_target: str):
    return subprocess.CompletedProcess(("drill",), 0, "passed\n", "")


def test_all_pass_run_is_hash_bound_and_has_no_execution_authority():
    result = broker_risk_fault_drills.run(runner=_passed)

    assert result["status"] == "pass"
    assert result["case_count"] == len(broker_risk_fault_drills.DRILL_CASES)
    assert result["passed_count"] == len(broker_risk_fault_drills.DRILL_CASES)
    assert result["failed_count"] == 0
    assert result["indeterminate_count"] == 0
    assert result["execution_authority"] == "none"
    assert len(result["suite_sha256"]) == 64
    assert len(result["run_sha256"]) == 64


def test_failed_and_indeterminate_cases_never_pass():
    calls = 0

    def mixed(_target: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(("drill",), 7, "", "failed\n")
        return None

    result = broker_risk_fault_drills.run(runner=mixed)

    assert result["status"] == "fail"
    assert result["passed_count"] == 0
    assert result["failed_count"] == 1
    assert result["indeterminate_count"] == len(
        broker_risk_fault_drills.DRILL_CASES
    ) - 1


def test_source_change_during_run_fails_closed(monkeypatch):
    identities = iter(
        (
            {
                "schema_version": 1,
                "suite_id": "broker-risk-boundary-v1",
                "cases": [],
                "source_sha256": "a" * 64,
                "source_file_count": 1,
                "execution_authority": "none",
                "suite_sha256": "b" * 64,
            },
            {
                "schema_version": 1,
                "suite_id": "broker-risk-boundary-v1",
                "cases": [],
                "source_sha256": "c" * 64,
                "source_file_count": 1,
                "execution_authority": "none",
                "suite_sha256": "d" * 64,
            },
        )
    )
    monkeypatch.setattr(
        broker_risk_fault_drills,
        "suite_identity",
        lambda *_args: next(identities),
    )

    with pytest.raises(
        broker_risk_fault_drills.BrokerRiskDrillError,
        match="source changed",
    ):
        broker_risk_fault_drills.run(runner=_passed)
