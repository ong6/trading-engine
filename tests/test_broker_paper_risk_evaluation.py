"""Authority-aware risk evaluation remains pure and non-submittable."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_ledger,
    broker_paper_authority_transcript,
    broker_paper_risk_evaluation,
    broker_paper_risk_projection,
    broker_paper_runtime,
    broker_paper_usage,
    broker_risk,
    broker_risk_control,
)
from tests.test_broker_paper_intent import (
    NOW,
    _candidate,
    _lease,
    _request,
    _risk_identity,
    _risk_policy,
    _snapshot,
)


def _activation(lease, candidate, runtime):
    body = {
        "schema_version": (
            broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
        ),
        "event_type": "activation_recorded",
        "event_sequence": 1,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "occurred_at": NOW.isoformat().replace("+00:00", "Z"),
        "prior_event_sha256": None,
        "submission_authority": "none",
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "startup_assessment_sha256": candidate["startup_assessment_sha256"],
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
    }
    return {**body, "event_sha256": canonical_sha256(body)}


def _inputs(con):
    policy = _risk_policy()
    lease = _lease(policy)
    candidate = _candidate(lease)
    broker_risk_control.record_halt(
        con,
        halt_key="paper-evaluation-halt-1",
        account_id=lease.account_id,
        reason="historical halt remains immutable",
        now=NOW - timedelta(seconds=1),
    )
    runtime = broker_paper_runtime.load_runtime_control(con, lease.account_id)
    activation = _activation(lease, candidate, runtime)
    usage = broker_paper_usage.load_open_usage(
        lease,
        (activation,),
        trusted_event_count=1,
        trusted_latest_event_sha256=activation["event_sha256"],
        trusted_activation_event_sha256=activation["event_sha256"],
        candidate_assessment_sha256=candidate["assessment_sha256"],
        startup_assessment_sha256=candidate["startup_assessment_sha256"],
        activation_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_control=runtime.control,
        now=NOW + timedelta(seconds=1),
    )
    snapshot = replace(
        _snapshot(),
        operational_halt=True,
        operational_control_sha256=runtime.control_status_sha256,
    )
    return lease, candidate, usage, runtime, policy, _risk_identity(policy), _request(), snapshot


def _evaluate(con, *, snapshot_change=None, policy=None, identity=None, request=None, now=None):
    (
        lease,
        candidate,
        usage,
        runtime,
        expected_policy,
        expected_identity,
        expected_request,
        snapshot,
    ) = _inputs(con)
    if snapshot_change:
        snapshot = replace(snapshot, **snapshot_change)
    return broker_paper_risk_evaluation.evaluate_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        policy or expected_policy,
        identity or expected_identity,
        request or expected_request,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=now or snapshot.observed_at + timedelta(seconds=1),
    )


def test_open_epoch_runs_all_twenty_gates_but_cannot_authorize_submission(con):
    evaluation = _evaluate(con)

    assert evaluation.status == "risk_pass_design_only"
    assert evaluation.risk_gate_names == broker_risk.GATE_NAMES
    assert len(evaluation.risk_gates) == 20
    assert all(gate.status == "pass" for gate in evaluation.risk_gates)
    assert evaluation.risk_failed_gates == ()
    assert evaluation.historical_operational_halt is True
    assert evaluation.effective_operational_halt is False
    assert evaluation.risk_evaluation_implemented is True
    assert evaluation.submission_integration_implemented is False
    assert evaluation.submission_authority == "none"
    assert broker_paper_risk_evaluation.verify_evaluation(evaluation) == evaluation
    assert evaluation.evaluation_sha256 == canonical_sha256(evaluation.payload())

    with pytest.raises(broker_risk.RiskContractError):
        broker_risk.verify(evaluation)
    with pytest.raises(broker_risk.RiskContractError):
        broker_ledger.record_risk_decision(
            con,
            request=_request(),
            decision=evaluation,
        )


@pytest.mark.parametrize(
    ("snapshot_change", "failed_gate"),
    [
        ({"instrument_quarantined": True}, "instrument"),
        ({"broker_healthy": False}, "dependency_health"),
        ({"reconciled": False}, "reconciliation"),
        ({"corporate_action_clear": False}, "corporate_action"),
        ({"median_dollar_volume": None}, "liquidity_participation"),
        ({"daily_pnl": -1_000.0}, "daily_loss"),
    ],
)
def test_non_control_failures_remain_blocking_under_open_epoch(
    con,
    snapshot_change,
    failed_gate,
):
    evaluation = _evaluate(con, snapshot_change=snapshot_change)

    assert evaluation.status == "blocked"
    assert failed_gate in evaluation.risk_failed_gates
    assert next(
        gate for gate in evaluation.risk_gates if gate.name == "operational_control"
    ).status == "pass"
    assert evaluation.submission_authority == "none"


def test_risk_policy_identity_request_and_authority_drift_fail_closed(con):
    lease, candidate, usage, runtime, policy, identity, request, snapshot = _inputs(con)

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="binding is invalid",
    ):
        broker_paper_risk_evaluation.evaluate_open_epoch(
            lease,
            candidate,
            usage,
            runtime,
            replace(policy, policy_id="different-risk-policy"),
            identity,
            request,
            snapshot,
            trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
            now=snapshot.observed_at + timedelta(seconds=1),
        )

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="binding is invalid",
    ):
        broker_paper_risk_evaluation.evaluate_open_epoch(
            lease,
            candidate,
            usage,
            runtime,
            policy,
            identity,
            replace(request, symbol="QQQ"),
            snapshot,
            trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
            now=snapshot.observed_at + timedelta(seconds=1),
        )

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="projection failed",
    ):
        broker_paper_risk_evaluation.evaluate_open_epoch(
            lease,
            candidate,
            replace(usage, evidence_sha256="f" * 64),
            runtime,
            policy,
            identity,
            request,
            snapshot,
            trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
            now=snapshot.observed_at + timedelta(seconds=1),
        )


def test_expired_risk_or_lease_never_reports_design_pass(con):
    lease, candidate, usage, runtime, policy, identity, request, snapshot = _inputs(con)

    risk_expired = broker_paper_risk_evaluation.evaluate_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        policy,
        identity,
        request,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=snapshot.observed_at + timedelta(seconds=31),
    )

    assert risk_expired.status == "blocked"
    assert risk_expired.risk_failed_gates == ()
    assert risk_expired.submission_authority == "none"

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="projection failed",
    ):
        broker_paper_risk_evaluation.evaluate_open_epoch(
            lease,
            candidate,
            usage,
            runtime,
            policy,
            identity,
            request,
            snapshot,
            trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
            now=lease.expires_at,
        )


def test_tampered_evaluation_fails_reverification(con):
    evaluation = _evaluate(con)

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="invalid",
    ):
        broker_paper_risk_evaluation.verify_evaluation(
            replace(evaluation, status="blocked")
        )

    with pytest.raises(
        broker_paper_risk_evaluation.PaperRiskEvaluationError,
        match="gate contract",
    ):
        broker_paper_risk_evaluation.verify_evaluation(
            replace(evaluation, risk_gate_names=("invented",))
        )


def test_projection_stays_non_evaluating_and_new_evaluator_has_no_mutation_surface(con):
    lease, candidate, usage, runtime, _policy, _identity, _request, snapshot = _inputs(con)
    projection = broker_paper_risk_projection.project_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=snapshot.observed_at + timedelta(seconds=1),
    )

    assert projection.risk_evaluation_implemented is False
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "record_halt",
        "reserve",
        "submit",
        "submit_order",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_risk_evaluation))
    assert set(
        broker_paper_risk_evaluation.evaluate_open_epoch.__globals__
    ).isdisjoint(
        {
            "duckdb",
            "db",
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
            "BrokerAdapter",
        }
    )
