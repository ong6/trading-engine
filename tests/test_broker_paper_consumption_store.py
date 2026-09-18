"""Automatic-paper pre-call evidence commits atomically without adapter access."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_ledger,
    broker_paper_consumption_plan,
    broker_paper_consumption_store,
    broker_paper_risk_evaluation,
    broker_paper_startup_store,
    broker_risk_control,
)
from tests.test_broker_paper_consumption_plan import (
    NOW,
    _activation,
    _intent_bindings,
)
from tests.test_broker_paper_risk_evaluation import _inputs


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _authority_schema(con):
    columns = ", ".join(
        (
            f"{name} {kind}"
            if name == "prior_global_row_sha256"
            else f"{name} {kind} NOT NULL"
        )
        for name, kind in broker_paper_startup_store.RETENTION_COLUMNS
    )
    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} ({columns})"
    )


def _risk_schema(con):
    columns = ", ".join(
        (
            f"{name} {kind} PRIMARY KEY"
            if name == "idempotency_key"
            else f"{name} {kind} UNIQUE NOT NULL"
            if name == "evaluation_sha256"
            else f"{name} {kind} NOT NULL"
        )
        for name, kind in broker_paper_consumption_store.RISK_EVIDENCE_COLUMNS
    )
    con.execute(
        f"CREATE TABLE {broker_paper_consumption_store.RISK_EVIDENCE_TABLE} "
        f"({columns})"
    )


def _activation_row(lease, candidate, runtime):
    event = _activation(lease, candidate, runtime)
    values = {
        "global_sequence": 1,
        "account_id": lease.account_id,
        "mode": lease.mode,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "lease_payload": _canonical(lease.payload()),
        "event_sequence": 1,
        "event_type": "activation_recorded",
        "event_payload": _canonical(event),
        "event_sha256": event["event_sha256"],
        "trusted_activation_event_sha256": event["event_sha256"],
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "startup_assessment_sha256": candidate["startup_assessment_sha256"],
        "activation_runtime_epoch_sha256": runtime.runtime_epoch_sha256,
        "prior_global_row_sha256": None,
    }
    body = broker_paper_startup_store._retained_row_body(
        **{
            **values,
            "lease_payload": lease.payload(),
            "event_payload": event,
        }
    )
    return {**values, "row_sha256": canonical_sha256(body)}


def _insert_activation(con, row):
    columns = broker_paper_startup_store._COLUMN_NAMES
    con.execute(
        f"INSERT INTO {broker_paper_startup_store.RETENTION_TABLE} "
        f"({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _ in columns)})",
        [row[name] for name in columns],
    )


def _setup(con):
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
    plan = broker_paper_consumption_plan.build_plan(
        lease,
        candidate,
        bindings,
        usage,
        evaluation,
        request,
        consumption_key="paper-consume-1",
        trusted_candidate_assessment_sha256=candidate["assessment_sha256"],
        trusted_intent_bindings_sha256=bindings.sha256(),
        now=NOW + timedelta(seconds=2),
    )
    _authority_schema(con)
    _risk_schema(con)
    broker_ledger.init_broker_ledger_schema(con)
    activation = _activation_row(lease, candidate, runtime)
    _insert_activation(con, activation)
    return lease, usage, evaluation, runtime, request, plan, activation


def _record(con, values, **changes):
    lease, usage, evaluation, runtime, request, plan, activation = values
    options = {
        "trusted_global_row_count": 1,
        "trusted_latest_global_row_sha256": activation["row_sha256"],
        "now": NOW + timedelta(seconds=3),
    }
    options.update(changes)
    return (
        broker_paper_consumption_store.record_pre_call_for_test_harness(
            con,
            lease,
            usage,
            evaluation,
            runtime,
            request,
            plan,
            **options,
        )
    )


def _counts(con):
    return {
        "authority": con.execute(
            f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
        ).fetchone()[0],
        "risk": con.execute(
            f"SELECT COUNT(*) FROM "
            f"{broker_paper_consumption_store.RISK_EVIDENCE_TABLE}"
        ).fetchone()[0],
        "intent": con.execute(
            "SELECT COUNT(*) FROM broker_intents"
        ).fetchone()[0],
        "submission": con.execute(
            "SELECT COUNT(*) FROM broker_submission_events"
        ).fetchone()[0],
    }


def test_pre_call_commit_persists_all_four_records_without_adapter(con):
    values = _setup(con)
    lease, usage, _evaluation, runtime, request, plan, _activation = values

    result = _record(con, values)

    assert result["status"] == "atomic_pre_call_persisted_for_test_harness"
    assert result["submission_state"] == "uncertain"
    assert result["adapter_called"] is False
    assert result["adapter_integration_implemented"] is False
    assert result["http_route"] == "absent"
    assert result["scheduler"] == "absent"
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    assert _counts(con) == {
        "authority": 2,
        "risk": 1,
        "intent": 1,
        "submission": 1,
    }
    assert (
        broker_ledger.submission_state(con, request.idempotency_key)
        == "uncertain"
    )
    assert (
        broker_ledger.uncertain_submission_request(
            con,
            request.idempotency_key,
        )
        == request
    )
    rows = broker_paper_startup_store._capture_rows(con)
    assert rows is not None
    epochs = broker_paper_startup_store._epochs(
        rows,
        account_id=lease.account_id,
    )
    loaded = broker_paper_consumption_store._actual_usage(
        lease,
        epochs,
        broker_paper_consumption_store.broker_paper_usage.load_open_usage(
            lease,
            epochs[0].events,
            trusted_event_count=2,
            trusted_latest_event_sha256=result[
                "consumption_event_sha256"
            ],
            trusted_activation_event_sha256=(
                epochs[0].trusted_activation_event_sha256
            ),
            candidate_assessment_sha256=(
                epochs[0].candidate_assessment_sha256
            ),
            startup_assessment_sha256=epochs[0].startup_assessment_sha256,
            activation_runtime_epoch_sha256=(
                epochs[0].activation_runtime_epoch_sha256
            ),
            current_runtime_epoch_sha256=runtime.runtime_epoch_sha256,
            current_control=usage.current_control,
            now=NOW + timedelta(seconds=3),
        ),
    )
    assert loaded.usage.consumed_order_count == 1
    assert loaded.usage.consumed_notional == plan["order_notional"]


def test_exact_replay_is_idempotent_and_keeps_submission_uncertain(con):
    values = _setup(con)
    first = _record(con, values)

    replay = _record(
        con,
        values,
        trusted_global_row_count=2,
        trusted_latest_global_row_sha256=first["consumption_row_sha256"],
        now=NOW + timedelta(seconds=20),
    )

    assert replay == first
    assert _counts(con) == {
        "authority": 2,
        "risk": 1,
        "intent": 1,
        "submission": 1,
    }


def test_stale_global_head_and_missing_schemas_fail_before_mutation(con):
    values = _setup(con)
    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="trusted global head",
    ):
        _record(
            con,
            values,
            trusted_latest_global_row_sha256="f" * 64,
        )
    assert _counts(con) == {
        "authority": 1,
        "risk": 0,
        "intent": 0,
        "submission": 0,
    }

    con.execute(
        f"DROP TABLE {broker_paper_consumption_store.RISK_EVIDENCE_TABLE}"
    )
    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="schemas are not exactly preinstalled",
    ):
        _record(con, values)


def test_conflicting_partial_replay_fails_closed(con):
    values = _setup(con)
    _record(con, values)
    con.execute("DELETE FROM broker_submission_events")

    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="inconsistent",
    ):
        _record(
            con,
            values,
            trusted_global_row_count=2,
            trusted_latest_global_row_sha256=con.execute(
                f"SELECT row_sha256 FROM "
                f"{broker_paper_startup_store.RETENTION_TABLE} "
                "ORDER BY global_sequence DESC LIMIT 1"
            ).fetchone()[0],
        )
    assert _counts(con) == {
        "authority": 2,
        "risk": 1,
        "intent": 1,
        "submission": 0,
    }


def test_tampered_risk_evidence_blocks_replay(con):
    values = _setup(con)
    first = _record(con, values)
    con.execute(
        f"UPDATE {broker_paper_consumption_store.RISK_EVIDENCE_TABLE} "
        "SET eligibility_payload = '{}'"
    )

    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="risk evidence is inconsistent",
    ):
        _record(
            con,
            values,
            trusted_global_row_count=2,
            trusted_latest_global_row_sha256=first[
                "consumption_row_sha256"
            ],
        )


def test_orphan_broker_intent_cannot_be_adopted(con):
    values = _setup(con)
    request = values[4]
    broker_ledger.record_intent(
        con,
        request,
        now=NOW + timedelta(seconds=2),
    )

    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="identity conflicts",
    ):
        _record(con, values)

    assert _counts(con) == {
        "authority": 1,
        "risk": 0,
        "intent": 1,
        "submission": 0,
    }


def test_failed_post_write_verification_rolls_back_all_four_records(
    con,
    monkeypatch,
):
    values = _setup(con)
    original = broker_paper_consumption_store._verified_authority_rows
    calls = 0

    def fail_after_writes(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise broker_paper_consumption_store.PaperConsumptionStoreError(
                "injected post-write chain failure"
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(
        broker_paper_consumption_store,
        "_verified_authority_rows",
        fail_after_writes,
    )

    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="injected post-write",
    ):
        _record(con, values)

    assert _counts(con) == {
        "authority": 1,
        "risk": 0,
        "intent": 0,
        "submission": 0,
    }


def test_stale_plan_time_fails_before_mutation(con):
    values = _setup(con)
    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="stale at persistence time",
    ):
        _record(con, values, now=NOW + timedelta(seconds=31))
    assert _counts(con) == {
        "authority": 1,
        "risk": 0,
        "intent": 0,
        "submission": 0,
    }


def test_halt_chain_advance_after_planning_fails_before_mutation(con):
    values = _setup(con)
    broker_risk_control.record_halt(
        con,
        halt_key="paper-consumption-later-halt",
        account_id=values[0].account_id,
        reason="later halt invalidates planned automatic consumption",
        now=NOW + timedelta(seconds=2),
    )

    with pytest.raises(
        broker_paper_consumption_store.PaperConsumptionStoreError,
        match="halt-chain binding changed",
    ):
        _record(con, values)

    assert _counts(con) == {
        "authority": 1,
        "risk": 0,
        "intent": 0,
        "submission": 0,
    }


def test_module_has_no_adapter_route_scheduler_or_schema_writer():
    assert {
        "init_schema",
        "submit",
        "submit_order",
        "schedule",
        "issue_lease",
        "activate",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_consumption_store))
    assert set(
        broker_paper_consumption_store.record_pre_call_for_test_harness.__globals__
    ).isdisjoint(
        {
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
            "BrokerAdapter",
        }
    )
