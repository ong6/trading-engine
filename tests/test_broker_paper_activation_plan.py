"""Automatic-paper activation plans remain pure and non-executable."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_paper_activation_plan,
    broker_paper_authority_transcript,
    broker_paper_runtime,
    broker_paper_startup_store,
    broker_risk_control,
    broker_startup_readiness,
)
from tests.test_broker_paper_lease import _assess, _bindings, _lease
from tests.test_broker_risk_snapshot import ACCOUNT, NOW, _Adapter
from tests.test_broker_startup_readiness import _record_reconciliation


def _inputs(con):
    lease = _lease(account_id=ACCOUNT)
    adapter = _Adapter()
    _record_reconciliation(
        con,
        adapter,
        observed_at=NOW - timedelta(seconds=2),
    )
    broker_risk_control.record_halt(
        con,
        halt_key="activation-plan-halt-1",
        account_id=ACCOUNT,
        reason="historical halt remains immutable",
        now=NOW - timedelta(seconds=1),
    )
    startup = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )
    candidate = _assess(
        lease,
        bindings=_bindings(
            lease,
            startup_assessment_sha256=startup["assessment_sha256"],
        ),
        now=NOW + timedelta(seconds=1),
    )
    runtime = broker_paper_runtime.load_runtime_control(con, ACCOUNT)
    scan = broker_paper_startup_store.load_and_scan_startup(
        con,
        runtime,
        account_id=ACCOUNT,
        trusted_row_count=0,
        trusted_latest_row_sha256=None,
        now=NOW + timedelta(seconds=1),
    )
    return lease, candidate, startup, scan, runtime


def _build(con, values=None, **changes):
    lease, candidate, startup, scan, runtime = values or _inputs(con)
    options = {
        "trusted_candidate_assessment_sha256": candidate["assessment_sha256"],
        "trusted_startup_assessment_sha256": startup["assessment_sha256"],
        "trusted_startup_scan_sha256": scan["scan_sha256"],
        "trusted_retention_evidence_sha256": (
            scan["retention_evidence_sha256"]
        ),
        "now": NOW + timedelta(seconds=2),
    }
    options.update(changes)
    return broker_paper_activation_plan.build_plan(
        lease,
        candidate,
        startup,
        scan,
        runtime,
        **options,
    )


def test_exact_inputs_produce_one_canonical_non_authorizing_activation(con):
    values = _inputs(con)
    lease, candidate, startup, _scan, runtime = values

    plan = _build(con, values)

    assert plan["status"] == "ready_for_future_activation_commit_design_only"
    assert plan["persistence_implemented"] is False
    assert plan["transaction_integration_implemented"] is False
    assert plan["submission_integration_implemented"] is False
    assert plan["submission_authority"] == "none"
    event = plan["expected_activation_event"]
    assert event["event_sequence"] == 1
    assert event["prior_event_sha256"] is None
    assert event["candidate_assessment_sha256"] == candidate["assessment_sha256"]
    assert event["startup_assessment_sha256"] == startup["assessment_sha256"]
    assert event["control_event_count"] == runtime.control.event_count
    assert event["control_event_sha256"] == runtime.control.latest_event_sha256
    assert event["runtime_epoch_sha256"] == runtime.runtime_epoch_sha256
    assert plan["expected_activation_event_sha256"] == canonical_sha256(event)
    assert broker_paper_activation_plan.verify_plan(plan) == plan

    retained = {**event, "event_sha256": canonical_sha256(event)}
    verified = broker_paper_authority_transcript.verify_transcript(
        lease,
        (retained,),
        trusted_activation_event_sha256=retained["event_sha256"],
        candidate_assessment_sha256=candidate["assessment_sha256"],
        startup_assessment_sha256=startup["assessment_sha256"],
        activation_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        current_control=runtime.control,
        now=NOW + timedelta(seconds=3),
    )
    assert verified["state"] == "activation_window_open_design_only"
    assert verified["submission_authority"] == "none"


def test_self_consistent_forged_startup_readiness_fails_closed(con):
    values = list(_inputs(con))
    forged = {
        **values[2],
        "account_active": False,
    }
    forged_body = {
        key: value
        for key, value in forged.items()
        if key != "assessment_sha256"
    }
    forged["assessment_sha256"] = canonical_sha256(forged_body)
    values[2] = forged

    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="source evidence verification failed",
    ):
        _build(
            con,
            values,
            trusted_startup_assessment_sha256=forged["assessment_sha256"],
        )


def test_changed_halt_chain_invalidates_prior_startup_evidence(con):
    values = list(_inputs(con))
    broker_risk_control.record_halt(
        con,
        halt_key="activation-plan-halt-2",
        account_id=ACCOUNT,
        reason="later halt invalidates activation evidence",
        now=NOW + timedelta(seconds=1),
    )
    values[4] = broker_paper_runtime.load_runtime_control(con, ACCOUNT)
    values[3] = broker_paper_startup_store.load_and_scan_startup(
        con,
        values[4],
        account_id=ACCOUNT,
        trusted_row_count=0,
        trusted_latest_row_sha256=None,
        now=NOW + timedelta(seconds=1),
    )

    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="stale or does not match",
    ):
        _build(
            con,
            values,
            trusted_startup_scan_sha256=values[3]["scan_sha256"],
            trusted_retention_evidence_sha256=(
                values[3]["retention_evidence_sha256"]
            ),
        )


def test_stale_startup_or_scan_evidence_fails_closed(con):
    values = _inputs(con)

    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="stale or does not match",
    ):
        _build(con, values, now=NOW + timedelta(seconds=31))


def test_reused_lease_identity_in_closed_history_fails_closed(con):
    values = list(_inputs(con))
    scan = deepcopy(values[3])
    record_body = {
        "lease_id": values[0].lease_id,
        "lease_sha256": values[0].sha256(),
        "state": "invalidated_by_restart",
        "event_count": 1,
        "latest_event_sha256": "1" * 64,
        "transcript_sha256": "2" * 64,
        "activation_runtime_epoch_sha256": "3" * 64,
        "current_runtime_epoch_sha256": values[4].runtime_epoch_sha256,
    }
    scan["records"] = [
        {**record_body, "record_sha256": canonical_sha256(record_body)}
    ]
    scan["retained_epoch_count"] = 1
    scan["closed_epoch_count"] = 1
    scan["trusted_retained_row_count"] = 1
    scan["trusted_latest_retained_row_sha256"] = "4" * 64
    scan_body = {
        key: value
        for key, value in scan.items()
        if key
        not in {
            "scan_sha256",
            "retention_schema_version",
            "trusted_retained_row_count",
            "trusted_latest_retained_row_sha256",
            "retention_evidence_sha256",
        }
    }
    scan["scan_sha256"] = canonical_sha256(scan_body)
    retention_body = {
        "schema_version": scan["retention_schema_version"],
        "account_id": ACCOUNT,
        "trusted_retained_row_count": scan["trusted_retained_row_count"],
        "trusted_latest_retained_row_sha256": (
            scan["trusted_latest_retained_row_sha256"]
        ),
        "scan_sha256": scan["scan_sha256"],
        "runtime_evidence_sha256": values[4].evidence_sha256,
        "execution_authority": "none",
    }
    scan["retention_evidence_sha256"] = canonical_sha256(retention_body)
    values[3] = scan

    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="lease identity was already retained",
    ):
        _build(
            con,
            values,
            trusted_startup_scan_sha256=scan["scan_sha256"],
            trusted_retention_evidence_sha256=(
                scan["retention_evidence_sha256"]
            ),
        )


def test_tampered_plan_and_source_evidence_fail_closed(con):
    values = list(_inputs(con))
    plan = _build(con, values)
    tampered = deepcopy(plan)
    tampered["expected_activation_event"]["control_event_count"] += 1

    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="invalid",
    ):
        broker_paper_activation_plan.verify_plan(tampered)

    values[1] = {**values[1], "assessment_sha256": "f" * 64}
    with pytest.raises(
        broker_paper_activation_plan.PaperActivationPlanError,
        match="source evidence verification failed",
    ):
        _build(con, values)


def test_module_has_no_writer_adapter_route_or_submission_surface():
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
    }.isdisjoint(vars(broker_paper_activation_plan))
    assert set(
        broker_paper_activation_plan.build_plan.__globals__
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
