"""Lease usage is derived only from one complete verified transcript."""

from __future__ import annotations

from datetime import timedelta

import pytest

from server import broker_paper_authority_transcript, broker_paper_usage
from tests.test_broker_paper_authority_transcript import (
    HASHES,
    NOW,
    _activation,
    _consumption,
    _lease,
    _revocation,
)


def _load(lease, events, **changes):
    values = {
        "trusted_event_count": len(events),
        "trusted_latest_event_sha256": events[-1]["event_sha256"],
        "trusted_activation_event_sha256": events[0]["event_sha256"],
        "candidate_assessment_sha256": HASHES[9],
        "startup_assessment_sha256": HASHES[10],
        "activation_runtime_epoch_sha256": HASHES[11],
        "current_runtime_epoch_sha256": HASHES[11],
        "current_control": broker_paper_authority_transcript.ControlAnchor(
            event_count=1,
            latest_event_sha256=HASHES[8],
        ),
        "now": NOW + timedelta(seconds=10),
    }
    values.update(changes)
    return broker_paper_usage.load_open_usage(lease, tuple(events), **values)


def test_loader_derives_zero_usage_from_complete_open_activation():
    lease = _lease()
    activation = _activation(lease)

    loaded = _load(lease, [activation])

    assert loaded.usage.lease_id == lease.lease_id
    assert loaded.usage.lease_sha256 == lease.sha256()
    assert loaded.usage.consumed_order_count == 0
    assert loaded.usage.consumed_notional == 0.0
    assert loaded.consumed_consumption_keys == ()
    assert loaded.consumed_idempotency_keys == ()
    assert loaded.consumed_request_sha256s == ()
    assert loaded.event_count == 1
    assert loaded.latest_event_sha256 == activation["event_sha256"]
    assert loaded.transcript_state == "activation_window_open_design_only"
    assert loaded.execution_authority == "none"
    assert len(loaded.transcript_sha256) == 64
    assert len(loaded.evidence_sha256) == 64


def test_loader_recomputes_usage_without_caller_supplied_counters():
    lease = _lease(capital_ceiling=4_000.0, max_orders=3)
    activation = _activation(lease)
    first = _consumption(lease, activation)
    second = _consumption(
        lease,
        first,
        sequence=3,
        key="consume-2",
        idempotency_key="intent-2",
        request_sha256=HASHES[4],
        notional=1_250.0,
        count=2,
        total=2_250.0,
    )

    loaded = _load(lease, [activation, first, second])

    assert loaded.usage.consumed_order_count == 2
    assert loaded.usage.consumed_notional == 2_250.0
    assert loaded.consumed_consumption_keys == ("consume-1", "consume-2")
    assert loaded.consumed_idempotency_keys == ("intent-1", "intent-2")
    assert loaded.consumed_request_sha256s == (HASHES[0], HASHES[4])
    assert "consumed_order_count" not in broker_paper_usage.load_open_usage.__annotations__
    assert "consumed_notional" not in broker_paper_usage.load_open_usage.__annotations__


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"trusted_event_count": 1}, "incomplete"),
        ({"trusted_latest_event_sha256": HASHES[12]}, "wrong head"),
    ],
)
def test_loader_rejects_truncated_or_wrong_head_transcript(changes, detail):
    lease = _lease()
    activation = _activation(lease)
    consumption = _consumption(lease, activation)

    with pytest.raises(broker_paper_usage.PaperUsageError, match=detail):
        _load(lease, [activation, consumption], **changes)


def test_loader_rejects_hash_consistent_counter_tampering():
    lease = _lease()
    activation = _activation(lease)
    consumption = _consumption(
        lease,
        activation,
        count=0,
        total=1_000.0,
    )

    with pytest.raises(
        broker_paper_usage.PaperUsageError,
        match="verification failed",
    ):
        _load(lease, [activation, consumption])


@pytest.mark.parametrize(
    "changes",
    [
        {"current_runtime_epoch_sha256": HASHES[12]},
        {
            "current_control": broker_paper_authority_transcript.ControlAnchor(
                event_count=2,
                latest_event_sha256=HASHES[12],
            )
        },
        {"now": NOW + timedelta(seconds=60)},
    ],
)
def test_loader_rejects_closed_runtime_halt_or_expiry_state(changes):
    lease = _lease()
    activation = _activation(lease)

    with pytest.raises(
        broker_paper_usage.PaperUsageError,
        match="not open",
    ):
        _load(lease, [activation], **changes)


def test_loader_rejects_revoked_or_exhausted_transcript():
    lease = _lease()
    activation = _activation(lease)
    revoked = _revocation(lease, activation)
    with pytest.raises(broker_paper_usage.PaperUsageError, match="not open"):
        _load(
            lease,
            [activation, revoked],
            current_control=broker_paper_authority_transcript.ControlAnchor(
                event_count=2,
                latest_event_sha256=HASHES[12],
            ),
        )

    exhausted_lease = _lease(max_orders=1)
    exhausted_activation = _activation(exhausted_lease)
    consumption = _consumption(exhausted_lease, exhausted_activation)
    with pytest.raises(broker_paper_usage.PaperUsageError, match="not open"):
        _load(exhausted_lease, [exhausted_activation, consumption])


def test_module_has_no_writer_adapter_or_authority_surface():
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "reserve",
        "submit",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_usage))
    assert set(broker_paper_usage.load_open_usage.__globals__).isdisjoint(
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
