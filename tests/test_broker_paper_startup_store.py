"""Durable startup loading proves the retained authority history is complete."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_paper_runtime,
    broker_paper_startup_store,
    broker_risk_control,
)
from tests.test_broker_paper_authority_transcript import HASHES, NOW, _lease
from tests.test_broker_paper_startup_scan import _activation


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _schema(con):
    columns = ", ".join(
        f"{name} {kind} NOT NULL"
        if name != "prior_global_row_sha256"
        else f"{name} {kind}"
        for name, kind in broker_paper_startup_store.RETENTION_COLUMNS
    )
    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} ({columns})"
    )


def _runtime(con):
    broker_risk_control.record_halt(
        con,
        halt_key="startup-store-halt-1",
        account_id="agent-paper-account",
        reason="startup store baseline halt",
        now=NOW - timedelta(seconds=1),
    )
    return broker_paper_runtime.load_runtime_control(con, "agent-paper-account")


def _row(
    lease,
    event,
    *,
    global_sequence,
    prior_global_row_sha256,
    trusted_activation_event_sha256=None,
    candidate_assessment_sha256=HASHES[9],
    startup_assessment_sha256=HASHES[10],
    activation_runtime_epoch_sha256=None,
    **changes,
):
    values = {
        "global_sequence": global_sequence,
        "account_id": lease.account_id,
        "mode": lease.mode,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "lease_payload": _canonical(lease.payload()),
        "event_sequence": event["event_sequence"],
        "event_type": event["event_type"],
        "event_payload": _canonical(event),
        "event_sha256": event["event_sha256"],
        "trusted_activation_event_sha256": (
            trusted_activation_event_sha256 or event["event_sha256"]
        ),
        "candidate_assessment_sha256": candidate_assessment_sha256,
        "startup_assessment_sha256": startup_assessment_sha256,
        "activation_runtime_epoch_sha256": (
            activation_runtime_epoch_sha256 or event["runtime_epoch_sha256"]
        ),
        "prior_global_row_sha256": prior_global_row_sha256,
    }
    values.update(changes)
    body = broker_paper_startup_store._retained_row_body(
        **{
            **values,
            "lease_payload": json.loads(values["lease_payload"]),
            "event_payload": json.loads(values["event_payload"]),
        }
    )
    values["row_sha256"] = canonical_sha256(body)
    return values


def _insert(con, row):
    con.execute(
        f"INSERT INTO {broker_paper_startup_store.RETENTION_TABLE} "
        f"({', '.join(broker_paper_startup_store._COLUMN_NAMES)}) "
        f"VALUES ({', '.join('?' for _ in row)})",
        [row[name] for name in broker_paper_startup_store._COLUMN_NAMES],
    )


def _load(con, runtime, rows, **changes):
    values = {
        "account_id": "agent-paper-account",
        "trusted_row_count": len(rows),
        "trusted_latest_row_sha256": None if not rows else rows[-1]["row_sha256"],
        "now": NOW + timedelta(seconds=10),
    }
    values.update(changes)
    return broker_paper_startup_store.load_and_scan_startup(
        con,
        runtime,
        **values,
    )


def test_missing_or_empty_store_is_safe_only_under_zero_external_head(con):
    runtime = _runtime(con)

    result = _load(con, runtime, [])

    assert result["status"] == "safe_closed"
    assert result["retained_epoch_count"] == 0
    assert result["trusted_retained_row_count"] == 0
    assert result["trusted_latest_retained_row_sha256"] is None
    assert len(result["retention_evidence_sha256"]) == 64
    assert result["startup_authority"] == "none"
    assert result["submission_authority"] == "none"

    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="trusted global head",
    ):
        _load(
            con,
            runtime,
            [],
            trusted_row_count=1,
            trusted_latest_row_sha256="f" * 64,
        )

    _schema(con)
    assert _load(con, runtime, [])["status"] == "safe_closed"


def test_complete_store_reconstructs_all_epochs_and_scans_closed(con):
    runtime = _runtime(con)
    _schema(con)
    first_lease = _lease(
        account_id="agent-paper-account",
        lease_id="paper-lease-1",
        approval_id="operator-approval-1",
        decision_window_id="dual-momentum:2026-09-14:first",
    )
    first_activation = _activation(
        first_lease,
        runtime,
        runtime_epoch_sha256=HASHES[11],
    )
    first = _row(
        first_lease,
        first_activation,
        global_sequence=1,
        prior_global_row_sha256=None,
    )
    second_lease = _lease(
        account_id="agent-paper-account",
        lease_id="paper-lease-2",
        approval_id="operator-approval-2",
        decision_window_id="dual-momentum:2026-09-14:second",
    )
    second_activation = _activation(
        second_lease,
        runtime,
        runtime_epoch_sha256=HASHES[12],
    )
    second = _row(
        second_lease,
        second_activation,
        global_sequence=2,
        prior_global_row_sha256=first["row_sha256"],
    )
    _insert(con, first)
    _insert(con, second)

    result = _load(con, runtime, [first, second])

    assert result["status"] == "safe_closed"
    assert result["retained_epoch_count"] == 2
    assert result["trusted_retained_row_count"] == 2
    assert result["trusted_latest_retained_row_sha256"] == second["row_sha256"]
    assert result["closed_epoch_count"] == 2
    assert [record["state"] for record in result["records"]] == [
        "invalidated_by_restart",
        "invalidated_by_restart",
    ]
    assert result["startup_authority"] == "none"
    assert result["submission_authority"] == "none"


def test_valid_truncated_prefix_and_omitted_rechained_epoch_fail_external_head(con):
    runtime = _runtime(con)
    _schema(con)
    first_lease = _lease(
        account_id="agent-paper-account",
        decision_window_id="dual-momentum:2026-09-14:first",
    )
    first_activation = _activation(
        first_lease,
        runtime,
        runtime_epoch_sha256=HASHES[11],
    )
    first = _row(
        first_lease,
        first_activation,
        global_sequence=1,
        prior_global_row_sha256=None,
    )
    second_lease = _lease(
        account_id="agent-paper-account",
        lease_id="paper-lease-2",
        approval_id="operator-approval-2",
        decision_window_id="dual-momentum:2026-09-14:second",
    )
    second_activation = _activation(
        second_lease,
        runtime,
        runtime_epoch_sha256=HASHES[12],
    )
    second = _row(
        second_lease,
        second_activation,
        global_sequence=2,
        prior_global_row_sha256=first["row_sha256"],
    )
    _insert(con, first)

    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="trusted global head",
    ):
        _load(
            con,
            runtime,
            [first],
            trusted_row_count=2,
            trusted_latest_row_sha256=second["row_sha256"],
        )

    con.execute(
        f"DELETE FROM {broker_paper_startup_store.RETENTION_TABLE}"
    )
    omitted_and_rechained = _row(
        second_lease,
        second_activation,
        global_sequence=1,
        prior_global_row_sha256=None,
    )
    _insert(con, omitted_and_rechained)
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="trusted global head",
    ):
        _load(
            con,
            runtime,
            [omitted_and_rechained],
            trusted_row_count=2,
            trusted_latest_row_sha256=second["row_sha256"],
        )


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"global_sequence": 2}, "global row chain"),
        ({"prior_global_row_sha256": "f" * 64}, "global row chain"),
        ({"account_id": "different-account"}, "binding drifted"),
        ({"mode": "hybrid"}, "binding drifted"),
        ({"event_sequence": 2}, "binding drifted"),
    ],
)
def test_global_chain_and_binding_drift_fail_closed(con, change, detail):
    runtime = _runtime(con)
    _schema(con)
    lease = _lease(account_id="agent-paper-account")
    activation = _activation(
        lease,
        runtime,
        runtime_epoch_sha256=HASHES[11],
    )
    row_arguments = {
        "global_sequence": 1,
        "prior_global_row_sha256": None,
        **change,
    }
    row = _row(lease, activation, **row_arguments)
    _insert(con, row)

    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match=detail,
    ):
        _load(con, runtime, [row])


def test_malformed_payload_and_duplicate_activation_identity_fail_closed(con):
    runtime = _runtime(con)
    _schema(con)
    first_lease = _lease(
        account_id="agent-paper-account",
        decision_window_id="dual-momentum:2026-09-14:first",
    )
    first_activation = _activation(
        first_lease,
        runtime,
        runtime_epoch_sha256=HASHES[11],
    )
    malformed = _row(
        first_lease,
        first_activation,
        global_sequence=1,
        prior_global_row_sha256=None,
        lease_payload=_canonical(first_lease.payload()) + " ",
    )
    _insert(con, malformed)
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="canonical JSON",
    ):
        _load(con, runtime, [malformed])

    con.execute(
        f"DELETE FROM {broker_paper_startup_store.RETENTION_TABLE}"
    )
    first = _row(
        first_lease,
        first_activation,
        global_sequence=1,
        prior_global_row_sha256=None,
    )
    second_lease = _lease(
        account_id="agent-paper-account",
        lease_id="paper-lease-2",
        approval_id="operator-approval-2",
        decision_window_id="dual-momentum:2026-09-14:second",
    )
    second_activation = _activation(
        second_lease,
        runtime,
        runtime_epoch_sha256=HASHES[12],
    )
    second = _row(
        second_lease,
        second_activation,
        global_sequence=2,
        prior_global_row_sha256=first["row_sha256"],
        trusted_activation_event_sha256=first_activation["event_sha256"],
    )
    _insert(con, first)
    _insert(con, second)
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="activation identity is duplicated",
    ):
        _load(con, runtime, [first, second])


def test_per_epoch_gap_and_concurrent_store_change_fail_closed(
    con,
    monkeypatch,
):
    runtime = _runtime(con)
    _schema(con)
    lease = _lease(account_id="agent-paper-account")
    activation = _activation(
        lease,
        runtime,
        runtime_epoch_sha256=HASHES[11],
    )
    gap = _row(
        lease,
        {**activation, "event_sequence": 2},
        global_sequence=1,
        prior_global_row_sha256=None,
        event_sequence=2,
    )
    _insert(con, gap)
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="incomplete|drifted",
    ):
        _load(con, runtime, [gap])

    captured = broker_paper_startup_store._capture_rows(con)
    values = iter((captured, ()))
    monkeypatch.setattr(
        broker_paper_startup_store,
        "_capture_rows",
        lambda *_args: next(values),
    )
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="changed during capture",
    ):
        _load(con, runtime, [gap])


def test_wrong_schema_and_trusted_head_shape_fail_closed(con):
    runtime = _runtime(con)
    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} "
        "(global_sequence BIGINT)"
    )
    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="schema is invalid",
    ):
        _load(con, runtime, [])

    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="count and head are inconsistent",
    ):
        _load(
            con,
            runtime,
            [],
            trusted_latest_row_sha256="f" * 64,
        )


def test_nullable_or_defaulted_required_column_is_not_the_exact_schema(con):
    runtime = _runtime(con)
    columns = ", ".join(
        (
            f"{name} {kind} DEFAULT 1"
            if name == "global_sequence"
            else f"{name} {kind}"
            if name == "prior_global_row_sha256"
            else f"{name} {kind} NOT NULL"
        )
        for name, kind in broker_paper_startup_store.RETENTION_COLUMNS
    )
    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} ({columns})"
    )

    with pytest.raises(
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
        match="schema is invalid",
    ):
        _load(con, runtime, [])


def test_module_has_no_schema_writer_adapter_or_authority_surface():
    assert {
        "append",
        "activate",
        "consume",
        "init_schema",
        "persist",
        "record_halt",
        "reserve",
        "submit",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_startup_store))
    assert set(
        broker_paper_startup_store.load_and_scan_startup.__globals__
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
