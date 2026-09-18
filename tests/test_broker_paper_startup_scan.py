"""Startup authority scan proves every retained epoch is closed."""

from __future__ import annotations

from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_paper_authority_transcript,
    broker_paper_runtime,
    broker_paper_startup_scan,
    broker_risk_control,
)
from tests.test_broker_paper_authority_transcript import HASHES, NOW, _lease


def _runtime(con):
    broker_risk_control.record_halt(
        con,
        halt_key="startup-scan-halt-1",
        account_id="agent-paper-account",
        reason="startup scan baseline halt",
        now=NOW - timedelta(seconds=1),
    )
    return broker_paper_runtime.load_runtime_control(con, "agent-paper-account")


def _activation(lease, runtime, *, runtime_epoch_sha256=None):
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
        "candidate_assessment_sha256": HASHES[9],
        "startup_assessment_sha256": HASHES[10],
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "runtime_epoch_sha256": (
            runtime_epoch_sha256 or runtime.runtime_epoch_sha256
        ),
    }
    return {**body, "event_sha256": canonical_sha256(body)}


def _epoch(lease, activation, **changes):
    values = {
        "lease": lease,
        "events": (activation,),
        "retained_event_count": 1,
        "retained_latest_event_sha256": activation["event_sha256"],
        "trusted_activation_event_sha256": activation["event_sha256"],
        "candidate_assessment_sha256": HASHES[9],
        "startup_assessment_sha256": HASHES[10],
        "activation_runtime_epoch_sha256": activation["runtime_epoch_sha256"],
    }
    values.update(changes)
    return broker_paper_startup_scan.RetainedAuthorityEpoch(**values)


def test_empty_startup_scan_is_safe_closed_and_non_authorizing(con):
    runtime = _runtime(con)

    result = broker_paper_startup_scan.scan_startup(
        (),
        runtime,
        account_id="agent-paper-account",
        now=NOW + timedelta(seconds=10),
    )

    assert result["status"] == "safe_closed"
    assert result["safe_closed"] is True
    assert result["retained_epoch_count"] == 0
    assert result["closed_epoch_count"] == 0
    assert result["open_lease_ids"] == []
    assert result["startup_authority"] == "none"
    assert result["submission_authority"] == "none"


def test_prior_process_open_epoch_is_verified_as_restart_invalidated(con):
    runtime = _runtime(con)
    lease = _lease()
    activation = _activation(
        lease,
        runtime,
        runtime_epoch_sha256="f" * 64,
    )

    result = broker_paper_startup_scan.scan_startup(
        (_epoch(lease, activation),),
        runtime,
        account_id=lease.account_id,
        now=NOW + timedelta(seconds=10),
    )

    assert result["status"] == "safe_closed"
    assert result["safe_closed"] is True
    assert result["closed_epoch_count"] == 1
    assert result["open_lease_ids"] == []
    assert result["records"][0]["state"] == "invalidated_by_restart"
    assert len(result["records"][0]["record_sha256"]) == 64
    body = {key: value for key, value in result.items() if key != "scan_sha256"}
    assert result["scan_sha256"] == canonical_sha256(body)


def test_current_process_open_epoch_blocks_startup(con):
    runtime = _runtime(con)
    lease = _lease()
    activation = _activation(lease, runtime)

    result = broker_paper_startup_scan.scan_startup(
        (_epoch(lease, activation),),
        runtime,
        account_id=lease.account_id,
        now=NOW + timedelta(seconds=10),
    )

    assert result["status"] == "blocked"
    assert result["safe_closed"] is False
    assert result["closed_epoch_count"] == 0
    assert result["open_lease_ids"] == [lease.lease_id]
    assert result["records"][0]["state"] == (
        "activation_window_open_design_only"
    )
    assert result["submission_authority"] == "none"


@pytest.mark.parametrize(
    "changes",
    [
        {"retained_event_count": 2},
        {"retained_latest_event_sha256": "f" * 64},
    ],
)
def test_startup_scan_rejects_incomplete_or_wrong_head(con, changes):
    runtime = _runtime(con)
    lease = _lease()
    activation = _activation(lease, runtime)

    with pytest.raises(
        broker_paper_startup_scan.PaperAuthorityStartupScanError,
        match="incomplete|wrong head",
    ):
        broker_paper_startup_scan.scan_startup(
            (_epoch(lease, activation, **changes),),
            runtime,
            account_id=lease.account_id,
            now=NOW + timedelta(seconds=10),
        )


def test_startup_scan_rejects_duplicate_epoch_identity(con):
    runtime = _runtime(con)
    lease = _lease()
    activation = _activation(lease, runtime, runtime_epoch_sha256="f" * 64)
    epoch = _epoch(lease, activation)

    with pytest.raises(
        broker_paper_startup_scan.PaperAuthorityStartupScanError,
        match="duplicated",
    ):
        broker_paper_startup_scan.scan_startup(
            (epoch, epoch),
            runtime,
            account_id=lease.account_id,
            now=NOW + timedelta(seconds=10),
        )


def test_startup_scan_rejects_tampered_event(con):
    runtime = _runtime(con)
    lease = _lease()
    activation = _activation(lease, runtime)
    tampered = {**activation, "account_id": "different-account"}
    epoch = _epoch(
        lease,
        activation,
        events=(tampered,),
        retained_latest_event_sha256=tampered["event_sha256"],
    )

    with pytest.raises(
        broker_paper_startup_scan.PaperAuthorityStartupScanError,
        match="verification failed",
    ):
        broker_paper_startup_scan.scan_startup(
            (epoch,),
            runtime,
            account_id=lease.account_id,
            now=NOW + timedelta(seconds=10),
        )


def test_module_has_no_writer_or_authority_surface():
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "record_halt",
        "reserve",
        "submit",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_startup_scan))
    assert set(broker_paper_startup_scan.scan_startup.__globals__).isdisjoint(
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
