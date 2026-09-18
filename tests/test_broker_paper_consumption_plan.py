"""Atomic paper-consumption plans remain pure, exact, and non-executable."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_ledger,
    broker_paper_authority_transcript,
    broker_paper_consumption_plan,
    broker_paper_risk_evaluation,
    broker_paper_runtime,
    broker_paper_usage,
    broker_risk,
    broker_risk_control,
)
from tests.test_broker_paper_intent import (
    _hybrid_inputs,
    _intent_bindings,
    _risk_identity,
    _risk_policy,
    _snapshot,
)
from tests.test_broker_paper_risk_evaluation import NOW, _inputs


def _plan_inputs(con):
    (
        lease,
        candidate,
        usage,
        runtime,
        policy,
        identity,
        request,
        snapshot,
    ) = _inputs(con)
    evaluation = broker_paper_risk_evaluation.evaluate_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        policy,
        identity,
        request,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=NOW + timedelta(seconds=1),
    )
    bindings = _intent_bindings(lease)
    return lease, candidate, bindings, usage, evaluation, request


def _build(con, **changes):
    values = list(_plan_inputs(con))
    options = {
        "consumption_key": "paper-consume-1",
        "trusted_candidate_assessment_sha256": values[1][
            "assessment_sha256"
        ],
        "trusted_intent_bindings_sha256": values[2].sha256(),
        "now": NOW + timedelta(seconds=2),
    }
    for key, value in changes.items():
        if isinstance(key, int):
            values[key] = value
        else:
            options[key] = value
    return broker_paper_consumption_plan.build_plan(*values, **options)


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


def _loaded_usage(lease, candidate, runtime, events, *, now):
    return broker_paper_usage.load_open_usage(
        lease,
        tuple(events),
        trusted_event_count=len(events),
        trusted_latest_event_sha256=events[-1]["event_sha256"],
        trusted_activation_event_sha256=events[0]["event_sha256"],
        candidate_assessment_sha256=candidate["assessment_sha256"],
        startup_assessment_sha256=candidate["startup_assessment_sha256"],
        activation_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_control=runtime.control,
        now=now,
    )


def test_exact_inputs_produce_one_canonical_non_authorizing_bundle(con):
    plan = _build(con)

    assert plan["status"] == "ready_for_future_atomic_commit_design_only"
    assert plan["expected_event_sequence"] == 2
    assert plan["order_notional"] == 1_005.0
    assert plan["resulting_consumed_order_count"] == 1
    assert plan["resulting_consumed_notional"] == 1_005.0
    assert plan["persistence_implemented"] is False
    assert plan["transaction_integration_implemented"] is False
    assert plan["submission_integration_implemented"] is False
    assert plan["submission_authority"] == "none"
    assert (
        plan["expected_submission_started"]["submission_state"]
        == "uncertain"
    )
    assert (
        plan["expected_consumption_event"][
            "broker_submission_started_sha256"
        ]
        == plan["expected_submission_started_sha256"]
    )
    broker_ledger.init_broker_ledger_schema(con)
    assert plan["expected_broker_intent_sha256"] == broker_ledger.record_intent(
        con,
        _plan_inputs(con)[5],
        now=NOW + timedelta(seconds=2),
    )
    assert broker_paper_consumption_plan.verify_plan(plan) == plan
    body = {
        key: value
        for key, value in plan.items()
        if key != "atomic_bundle_sha256"
    }
    assert plan["atomic_bundle_sha256"] == canonical_sha256(body)


def test_expected_consumption_event_matches_transcript_contract(con):
    lease, candidate, _bindings, usage, _evaluation, _request = _plan_inputs(
        con
    )
    plan = _build(con)
    expected = plan["expected_consumption_event"]
    event = {
        **expected,
        "event_sha256": canonical_sha256(expected),
    }
    activation = {
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
        "startup_assessment_sha256": candidate[
            "startup_assessment_sha256"
        ],
        "control_event_count": usage.current_control.event_count,
        "control_event_sha256": (
            usage.current_control.latest_event_sha256
        ),
        "runtime_epoch_sha256": usage.current_runtime_epoch_sha256,
    }
    activation["event_sha256"] = canonical_sha256(activation)
    assert activation["event_sha256"] == usage.latest_event_sha256

    result = broker_paper_authority_transcript.verify_transcript(
        lease,
        (activation, event),
        trusted_activation_event_sha256=activation["event_sha256"],
        candidate_assessment_sha256=candidate["assessment_sha256"],
        startup_assessment_sha256=candidate["startup_assessment_sha256"],
        activation_runtime_epoch_sha256=(
            usage.activation_runtime_epoch_sha256
        ),
        current_runtime_epoch_sha256=usage.current_runtime_epoch_sha256,
        current_control=usage.current_control,
        now=NOW + timedelta(seconds=3),
    )

    assert result["consumed_order_count"] == 1
    assert result["consumed_notional"] == 1_005.0


def test_replay_is_proven_from_complete_usage(con):
    lease, candidate, _usage, runtime, policy, identity, request, snapshot = (
        _inputs(con)
    )
    activation = _activation(lease, candidate, runtime)
    first_body = {
        "schema_version": (
            broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
        ),
        "event_type": "consumption_committed",
        "event_sequence": 2,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "occurred_at": (NOW + timedelta(seconds=1)).isoformat().replace(
            "+00:00",
            "Z",
        ),
        "prior_event_sha256": activation["event_sha256"],
        "submission_authority": "none",
        "consumption_key": "paper-consume-1",
        "idempotency_key": request.idempotency_key,
        "eligibility_sha256": "a" * 64,
        "request_sha256": canonical_sha256(
            {
                **{
                    field: getattr(request, field)
                    for field in request.__dataclass_fields__
                    if field != "signal_date"
                },
                "signal_date": request.signal_date.isoformat(),
            }
        ),
        "risk_evaluation_sha256": "b" * 64,
        "broker_submission_started_sha256": "c" * 64,
        "submission_state": "uncertain",
        "order_notional": 500.0,
        "resulting_consumed_order_count": 1,
        "resulting_consumed_notional": 500.0,
    }
    first = {**first_body, "event_sha256": canonical_sha256(first_body)}
    usage = _loaded_usage(
        lease,
        candidate,
        runtime,
        [activation, first],
        now=NOW + timedelta(seconds=2),
    )
    evaluation = broker_paper_risk_evaluation.evaluate_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        policy,
        identity,
        request,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=NOW + timedelta(seconds=3),
    )
    bindings = _intent_bindings(lease)

    with pytest.raises(
        broker_paper_consumption_plan.PaperConsumptionPlanError,
        match="already used",
    ):
        broker_paper_consumption_plan.build_plan(
            lease,
            candidate,
            bindings,
            usage,
            evaluation,
            request,
            consumption_key="paper-consume-1",
            trusted_candidate_assessment_sha256=candidate[
                "assessment_sha256"
            ],
            trusted_intent_bindings_sha256=bindings.sha256(),
            now=NOW + timedelta(seconds=4),
        )


def test_hybrid_mode_uses_the_same_non_authorizing_plan_boundary(con):
    lease, candidate, request, _ordinary_risk, bindings, _usage = (
        _hybrid_inputs()
    )
    broker_risk_control.record_halt(
        con,
        halt_key="hybrid-plan-halt-1",
        account_id=lease.account_id,
        reason="historical halt remains immutable",
        now=NOW - timedelta(seconds=1),
    )
    runtime = broker_paper_runtime.load_runtime_control(con, lease.account_id)
    activation = _activation(lease, candidate, runtime)
    usage = _loaded_usage(
        lease,
        candidate,
        runtime,
        [activation],
        now=NOW + timedelta(seconds=1),
    )
    policy = _risk_policy()
    snapshot = replace(
        _snapshot(),
        operational_halt=True,
        operational_control_sha256=runtime.control_status_sha256,
    )
    evaluation = broker_paper_risk_evaluation.evaluate_open_epoch(
        lease,
        candidate,
        usage,
        runtime,
        policy,
        _risk_identity(policy),
        request,
        snapshot,
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        now=NOW + timedelta(seconds=2),
    )

    plan = broker_paper_consumption_plan.build_plan(
        lease,
        candidate,
        bindings,
        usage,
        evaluation,
        request,
        consumption_key="hybrid-consume-1",
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        trusted_intent_bindings_sha256=bindings.sha256(),
        now=NOW + timedelta(seconds=3),
    )

    assert plan["mode"] == "hybrid"
    assert plan["submission_authority"] == "none"


def test_forged_usage_and_capacity_counters_fail_before_planning(con):
    original = _plan_inputs(con)
    forged_usage = replace(
        original[3],
        usage=replace(
            original[3].usage,
            consumed_order_count=original[0].max_orders,
        ),
        consumed_consumption_keys=(
            "consume-1",
            "consume-2",
            "consume-3",
        ),
        consumed_idempotency_keys=("intent-1", "intent-2", "intent-3"),
        consumed_request_sha256s=("1" * 64, "2" * 64, "3" * 64),
        evidence_sha256="f" * 64,
    )
    with pytest.raises(
        broker_paper_consumption_plan.PaperConsumptionPlanError,
        match="source evidence verification failed",
    ):
        broker_paper_consumption_plan.build_plan(
            *(*original[:3], forged_usage, *original[4:]),
            consumption_key="new-consume",
            trusted_candidate_assessment_sha256=original[1][
                "assessment_sha256"
            ],
            trusted_intent_bindings_sha256=original[2].sha256(),
            now=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"trusted_intent_bindings_sha256": "f" * 64}, "bindings do not match"),
        (
            {"now": NOW + timedelta(seconds=31)},
            "risk or lease window is not open",
        ),
    ],
)
def test_untrusted_or_stale_evidence_fails_closed(con, change, detail):
    with pytest.raises(
        broker_paper_consumption_plan.PaperConsumptionPlanError,
        match=detail,
    ):
        _build(con, **change)


def test_tampered_plan_and_current_submission_interfaces_reject_it(con):
    plan = _build(con)
    with pytest.raises(
        broker_paper_consumption_plan.PaperConsumptionPlanError,
        match="commitments are inconsistent",
    ):
        broker_paper_consumption_plan.verify_plan(
            {
                **plan,
                "expected_consumption_event": {
                    **plan["expected_consumption_event"],
                    "resulting_consumed_order_count": 2,
                },
            }
        )
    with pytest.raises(broker_risk.RiskContractError):
        broker_risk.verify(plan)
    with pytest.raises(broker_risk.RiskContractError):
        broker_ledger.record_risk_decision(
            con,
            request=_plan_inputs(con)[5],
            decision=plan,
        )


def test_module_has_no_writer_adapter_or_authority_surface():
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "record",
        "reserve",
        "submit",
        "submit_order",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_consumption_plan))
    assert set(
        broker_paper_consumption_plan.build_plan.__globals__
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
