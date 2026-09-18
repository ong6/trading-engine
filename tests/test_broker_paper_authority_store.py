"""Activation persistence is atomic, idempotent, and non-submittable."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from server import (
    broker_paper_activation_plan,
    broker_paper_authority_store,
    broker_paper_startup_store,
)
from tests.test_broker_paper_activation_plan import _build, _inputs
from tests.test_broker_paper_lease import NOW, _assess, _bindings, _lease


def _schema(con):
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


def _prepared(con):
    values = _inputs(con)
    return values[0], _build(con, values)


def _record(con, lease, plan, **changes):
    options = {"now": NOW + timedelta(seconds=3)}
    options.update(changes)
    return broker_paper_authority_store.record_activation_for_test_harness(
        con,
        lease,
        plan,
        **options,
    )


def test_activation_append_is_exact_atomic_and_non_submittable(con):
    lease, plan = _prepared(con)
    _schema(con)

    result = _record(con, lease, plan)

    assert result["status"] == "activation_persisted_for_test_harness"
    assert result["persistence_implemented"] is True
    assert result["runtime_activation_implemented"] is False
    assert result["consumption_implemented"] is False
    assert result["adapter_integration_implemented"] is False
    assert result["http_route"] == "absent"
    assert result["scheduler"] == "absent"
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    rows = broker_paper_startup_store._capture_rows(con)
    assert rows is not None
    assert len(rows) == 1
    assert rows[0][0] == 1
    assert rows[0][3] == lease.lease_id
    assert rows[0][7] == "activation_recorded"
    assert rows[0][-1] == result["activation_row_sha256"]
    epochs = broker_paper_startup_store._epochs(
        rows,
        account_id=lease.account_id,
    )
    assert len(epochs) == 1
    assert epochs[0].lease == lease
    assert epochs[0].events[0]["event_sha256"] == (
        result["activation_event_sha256"]
    )


def test_exact_replay_is_idempotent_even_after_plan_freshness_window(con):
    lease, plan = _prepared(con)
    _schema(con)
    first = _record(con, lease, plan)

    replay = _record(
        con,
        lease,
        plan,
        now=NOW + timedelta(seconds=59),
    )

    assert replay == first
    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
    ).fetchone() == (1,)


def test_conflicting_activation_for_same_lease_fails_closed(con):
    values = _inputs(con)
    lease = values[0]
    first_plan = _build(con, values)
    conflicting_plan = _build(
        con,
        values,
        now=NOW + timedelta(seconds=3),
    )
    _schema(con)
    _record(
        con,
        lease,
        conflicting_plan,
        now=NOW + timedelta(seconds=4),
    )

    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="identity conflicts",
    ):
        _record(con, lease, first_plan)

    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
    ).fetchone() == (1,)


def test_valid_intervening_append_rejects_stale_planned_global_head(con):
    values = _inputs(con)
    lease, _candidate, startup, scan, runtime = values
    stale_plan = _build(con, values)
    other_lease = _lease(
        account_id=lease.account_id,
        lease_id="paper-lease-2",
        approval_id="operator-approval-2",
        decision_window_id="dual-momentum:2026-09-14:second",
    )
    other_candidate = _assess(
        other_lease,
        bindings=_bindings(
            other_lease,
            startup_assessment_sha256=startup["assessment_sha256"],
        ),
        now=NOW + timedelta(seconds=1),
    )
    other_plan = broker_paper_activation_plan.build_plan(
        other_lease,
        other_candidate,
        startup,
        scan,
        runtime,
        trusted_candidate_assessment_sha256=other_candidate[
            "assessment_sha256"
        ],
        trusted_startup_assessment_sha256=startup["assessment_sha256"],
        trusted_startup_scan_sha256=scan["scan_sha256"],
        trusted_retention_evidence_sha256=scan["retention_evidence_sha256"],
        now=NOW + timedelta(seconds=2),
    )
    _schema(con)
    _record(con, other_lease, other_plan)

    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="does not match the activation plan head",
    ):
        _record(con, lease, stale_plan)

    rows = broker_paper_startup_store._capture_rows(con)
    assert rows is not None
    assert len(rows) == 1
    assert rows[0][3] == other_lease.lease_id


def test_missing_or_inexact_schema_and_stale_first_write_fail_closed(con):
    lease, plan = _prepared(con)
    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="not preinstalled",
    ):
        _record(con, lease, plan)

    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} "
        "(global_sequence BIGINT)"
    )
    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="not preinstalled",
    ):
        _record(con, lease, plan)

    con.execute(
        f"DROP TABLE {broker_paper_startup_store.RETENTION_TABLE}"
    )
    _schema(con)
    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="stale at persistence time",
    ):
        _record(
            con,
            lease,
            plan,
            now=NOW + timedelta(seconds=33),
        )
    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
    ).fetchone() == (0,)


def test_plan_and_lease_binding_are_reverified_before_transaction(con):
    lease, plan = _prepared(con)
    _schema(con)
    tampered = deepcopy(plan)
    tampered["account_id"] = "different-account"

    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="plan verification failed",
    ):
        _record(con, lease, tampered)

    different_lease = _lease(
        account_id=lease.account_id,
        lease_id="paper-lease-2",
        approval_id="operator-approval-2",
    )
    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="does not match the supplied lease",
    ):
        _record(con, different_lease, plan)
    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
    ).fetchone() == (0,)


def test_failed_post_insert_chain_verification_rolls_back(
    con,
    monkeypatch,
):
    lease, plan = _prepared(con)
    _schema(con)
    original = broker_paper_authority_store._verified_rows
    calls = 0

    def fail_after_insert(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise broker_paper_authority_store.PaperAuthorityStoreError(
                "injected complete-chain verification failure"
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(
        broker_paper_authority_store,
        "_verified_rows",
        fail_after_insert,
    )

    with pytest.raises(
        broker_paper_authority_store.PaperAuthorityStoreError,
        match="injected complete-chain",
    ):
        _record(con, lease, plan)

    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_paper_startup_store.RETENTION_TABLE}"
    ).fetchone() == (0,)


def test_module_has_no_route_scheduler_adapter_or_schema_surface():
    assert {
        "init_schema",
        "submit",
        "submit_order",
        "schedule",
        "issue_lease",
        "consume",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_authority_store))
    assert set(
        broker_paper_authority_store.record_activation_for_test_harness.__globals__
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
