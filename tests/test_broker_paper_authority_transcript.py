"""Pure paper-authority transcript semantics remain non-executable."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    broker_paper_authority_transcript,
    broker_paper_lease,
)

NOW = datetime(2026, 9, 14, 14, 30, tzinfo=timezone.utc)
HASHES = tuple(format(index, "x") * 64 for index in range(1, 14))


def _lease(**changes):
    identity = agent_model_client.identity()
    values = {
        "lease_id": "paper-lease-1",
        "approval_id": "operator-approval-1",
        "approved_by": "operator-1",
        "approval_evidence_sha256": HASHES[0],
        "authority_stage": "automatic_paper",
        "environment": "simulator",
        "mode": "agent_only",
        "policy_id": "dual-momentum-agent-shadow-v1",
        "policy_registration_sha256": HASHES[1],
        "account_id": "agent-paper-account",
        "strategy_id": "dual-momentum",
        "strategy_config_sha256": HASHES[2],
        "data_snapshot_sha256": HASHES[3],
        "transport": identity["transport"],
        "endpoint": identity["endpoint"],
        "model": identity["model"],
        "model_version": "provider-revision-1",
        "required_proxy_version": identity["required_proxy_version"],
        "prompt_sha256": identity["instructions_sha256"],
        "toolset_sha256": identity["toolset_sha256"],
        "execution_profile_id": "baseline-v1",
        "execution_profile_sha256": HASHES[4],
        "risk_policy_id": "paper-risk-v1",
        "risk_policy_sha256": HASHES[5],
        "release_manifest_sha256": HASHES[6],
        "authority_readiness_sha256": HASHES[7],
        "decision_window_id": "dual-momentum:2026-09-14",
        "allowed_symbols": ("BIL", "EFA", "SPY"),
        "capital_ceiling": 3_000.0,
        "max_order_notional": 2_000.0,
        "max_orders": 2,
        "approved_at": NOW - timedelta(seconds=2),
        "not_before": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(seconds=60),
    }
    values.update(changes)
    return broker_paper_lease.PaperAuthorityLease(**values)


def _with_hash(body):
    return {**body, "event_sha256": canonical_sha256(body)}


def _activation(lease, *, control_count=1, control_sha256=HASHES[8]):
    return _with_hash(
        {
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
            "control_event_count": control_count,
            "control_event_sha256": control_sha256,
            "runtime_epoch_sha256": HASHES[11],
        }
    )


def _consumption(
    lease,
    prior,
    *,
    sequence=2,
    key="consume-1",
    idempotency_key="intent-1",
    request_sha256=HASHES[0],
    notional=1_000.0,
    count=1,
    total=1_000.0,
):
    return _with_hash(
        {
            "schema_version": (
                broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
            ),
            "event_type": "consumption_committed",
            "event_sequence": sequence,
            "lease_id": lease.lease_id,
            "lease_sha256": lease.sha256(),
            "account_id": lease.account_id,
            "mode": lease.mode,
            "occurred_at": (
                NOW + timedelta(seconds=sequence - 1)
            ).isoformat().replace("+00:00", "Z"),
            "prior_event_sha256": prior["event_sha256"],
            "submission_authority": "none",
            "consumption_key": key,
            "idempotency_key": idempotency_key,
            "eligibility_sha256": HASHES[1],
            "request_sha256": request_sha256,
            "risk_evaluation_sha256": HASHES[2],
            "broker_submission_started_sha256": HASHES[3],
            "submission_state": "uncertain",
            "order_notional": notional,
            "resulting_consumed_order_count": count,
            "resulting_consumed_notional": total,
        }
    )


def _revocation(
    lease,
    prior,
    *,
    sequence=2,
    control_count=2,
    control_sha256=HASHES[12],
):
    return _with_hash(
        {
            "schema_version": (
                broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
            ),
            "event_type": "revocation_recorded",
            "event_sequence": sequence,
            "lease_id": lease.lease_id,
            "lease_sha256": lease.sha256(),
            "account_id": lease.account_id,
            "mode": lease.mode,
            "occurred_at": (
                NOW + timedelta(seconds=sequence - 1)
            ).isoformat().replace("+00:00", "Z"),
            "prior_event_sha256": prior["event_sha256"],
            "submission_authority": "none",
            "revocation_key": "revoke-1",
            "reason": "operator halt",
            "control_event_count": control_count,
            "control_event_sha256": control_sha256,
        }
    )


def _verify(lease, events, **changes):
    activation = events[0]
    values = {
        "trusted_activation_event_sha256": activation["event_sha256"],
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
    return broker_paper_authority_transcript.verify_transcript(
        lease,
        tuple(events),
        **values,
    )


def test_valid_activation_transcript_is_design_only_and_non_authorizing():
    lease = _lease()
    activation = _activation(lease)

    result = _verify(lease, [activation])

    assert result["state"] == "activation_window_open_design_only"
    assert result["consumed_order_count"] == 0
    assert result["remaining_order_count"] == 2
    assert result["runtime_activation_implemented"] is False
    assert result["runtime_consumption_implemented"] is False
    assert result["submission_authority"] == "none"
    body = {key: value for key, value in result.items() if key != "transcript_sha256"}
    assert result["transcript_sha256"] == canonical_sha256(body)


def test_exact_consumption_sequence_recomputes_capacity_and_exhaustion():
    lease = _lease()
    activation = _activation(lease)
    first = _consumption(lease, activation)
    second = _consumption(
        lease,
        first,
        sequence=3,
        key="consume-2",
        idempotency_key="intent-2",
        request_sha256=HASHES[4],
        notional=2_000.0,
        count=2,
        total=3_000.0,
    )

    result = _verify(lease, [activation, first, second])

    assert result["state"] == "exhausted"
    assert result["consumed_order_count"] == 2
    assert result["consumed_notional"] == 3_000.0
    assert result["remaining_order_count"] == 0
    assert result["remaining_notional"] == 0.0
    assert result["submission_authority"] == "none"


@pytest.mark.parametrize(
    ("changes", "state"),
    [
        ({"current_runtime_epoch_sha256": HASHES[12]}, "invalidated_by_restart"),
        (
            {
                "current_control": broker_paper_authority_transcript.ControlAnchor(
                    event_count=2,
                    latest_event_sha256=HASHES[12],
                )
            },
            "invalidated_by_halt",
        ),
        ({"now": NOW + timedelta(seconds=60)}, "expired"),
    ],
)
def test_restart_halt_and_expiry_close_the_design_epoch(changes, state):
    lease = _lease()

    result = _verify(lease, [_activation(lease)], **changes)

    assert result["state"] == state
    assert result["submission_authority"] == "none"


def test_explicit_revocation_is_terminal_and_requires_a_later_halt():
    lease = _lease()
    activation = _activation(lease)
    revoked = _revocation(lease, activation)

    result = _verify(
        lease,
        [activation, revoked],
        current_control=broker_paper_authority_transcript.ControlAnchor(
            event_count=2,
            latest_event_sha256=HASHES[12],
        ),
    )

    assert result["state"] == "revoked"
    assert result["submission_authority"] == "none"

    invalid = _revocation(
        lease,
        activation,
        control_count=1,
        control_sha256=HASHES[8],
    )
    with pytest.raises(
        broker_paper_authority_transcript.PaperAuthorityTranscriptError,
        match="later halt",
    ):
        _verify(lease, [activation, invalid])


def test_event_after_revocation_is_rejected():
    lease = _lease()
    activation = _activation(lease)
    revoked = _revocation(lease, activation)
    later = _consumption(
        lease,
        revoked,
        sequence=3,
    )

    with pytest.raises(
        broker_paper_authority_transcript.PaperAuthorityTranscriptError,
        match="terminal revocation",
    ):
        _verify(
            lease,
            [activation, revoked, later],
            current_control=broker_paper_authority_transcript.ControlAnchor(
                event_count=2,
                latest_event_sha256=HASHES[12],
            ),
        )


@pytest.mark.parametrize(
    "second_changes",
    [
        {"key": "consume-1"},
        {"idempotency_key": "intent-1"},
        {"request_sha256": HASHES[0]},
    ],
)
def test_consumed_intent_identity_cannot_be_reused(second_changes):
    lease = _lease(capital_ceiling=4_000.0)
    activation = _activation(lease)
    first = _consumption(lease, activation)
    defaults = {
        "sequence": 3,
        "key": "consume-2",
        "idempotency_key": "intent-2",
        "request_sha256": HASHES[4],
        "notional": 1_000.0,
        "count": 2,
        "total": 2_000.0,
    }
    defaults.update(second_changes)
    second = _consumption(lease, first, **defaults)

    with pytest.raises(
        broker_paper_authority_transcript.PaperAuthorityTranscriptError,
        match="repeats a consumed intent",
    ):
        _verify(lease, [activation, first, second])


@pytest.mark.parametrize(
    "event",
    [
        lambda lease, activation: _consumption(
            lease,
            activation,
            notional=2_001.0,
            total=2_001.0,
        ),
        lambda lease, activation: _consumption(
            lease,
            activation,
            count=2,
        ),
        lambda lease, activation: {
            **_consumption(lease, activation),
            "submission_state": "acknowledged",
        },
    ],
)
def test_capacity_and_atomic_pre_call_state_fail_closed(event):
    lease = _lease()
    activation = _activation(lease)
    consumption = event(lease, activation)
    if consumption["event_sha256"] != canonical_sha256(
        {key: value for key, value in consumption.items() if key != "event_sha256"}
    ):
        body = {
            key: value
            for key, value in consumption.items()
            if key != "event_sha256"
        }
        consumption = _with_hash(body)

    with pytest.raises(broker_paper_authority_transcript.PaperAuthorityTranscriptError):
        _verify(lease, [activation, consumption])


def test_tampering_or_untrusted_activation_fails_closed():
    lease = _lease()
    activation = _activation(lease)
    tampered = {**activation, "account_id": "different-account"}

    with pytest.raises(
        broker_paper_authority_transcript.PaperAuthorityTranscriptError,
        match="hash does not match",
    ):
        _verify(lease, [tampered])
    with pytest.raises(
        broker_paper_authority_transcript.PaperAuthorityTranscriptError,
        match="activation binding",
    ):
        _verify(
            lease,
            [activation],
            trusted_activation_event_sha256=HASHES[12],
        )


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
    }.isdisjoint(vars(broker_paper_authority_transcript))
    assert set(
        broker_paper_authority_transcript.verify_transcript.__globals__
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
