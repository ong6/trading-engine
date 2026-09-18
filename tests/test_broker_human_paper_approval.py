"""Human decision authentication remains exact, external, and non-authorizing."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_human_paper_approval,
    broker_human_paper_approval_store,
    broker_human_paper_review,
)
from tests.test_agent_paper_evidence import NOW, _accepted, _request
from tests.test_broker_human_paper_review import _counts

AUTHENTICATOR = b"externally-produced-authenticator"


def _packet(con, monkeypatch) -> dict:
    result = _accepted(con, monkeypatch)
    return broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )


def _policy(**changes) -> broker_human_paper_approval.HumanApprovalPolicy:
    values = {
        "approval_source_id": "operator-controlled-offline-source",
        "signer_policy_id": "paper-review-signers",
        "signer_policy_version": "v1",
        "authenticator_algorithm": "external-test-algorithm",
        "authorized_signer_identities": ("operator-one",),
        "authorized_modes": ("agent_only", "hybrid"),
        "authorized_policy_ids": (
            "dual_momentum_agent_shadow_v1",
            "dual_momentum_hybrid_veto_shadow_v1",
        ),
        "authorized_account_ids": (
            "agent_dual_momentum_shadow_v1",
            "hybrid_dual_momentum_shadow_v1",
        ),
        "valid_from": NOW,
        "valid_until": NOW + timedelta(seconds=300),
        "max_approval_seconds": 120,
    }
    values.update(changes)
    return broker_human_paper_approval.HumanApprovalPolicy(**values)


def _envelope(
    packet: dict,
    **changes,
) -> broker_human_paper_approval.HumanApprovalEnvelope:
    values = {
        "approval_id": "one-use-approval-1",
        "approval_source_id": "operator-controlled-offline-source",
        "signer_policy_id": "paper-review-signers",
        "signer_policy_version": "v1",
        "signer_identity": "operator-one",
        "authenticator_algorithm": "external-test-algorithm",
        "decision": "approve_exact_intent",
        "review_request_sha256": packet["review_request_sha256"],
        "request_sha256": packet["request_sha256"],
        "issued_at": NOW + timedelta(seconds=2),
        "not_before": NOW + timedelta(seconds=2),
        "expires_at": NOW + timedelta(seconds=60),
        "authenticator_base64": base64.b64encode(AUTHENTICATOR).decode("ascii"),
    }
    values.update(changes)
    return broker_human_paper_approval.HumanApprovalEnvelope(**values)


def _accept_expected(envelope, calls):
    def verify(algorithm, signer_identity, signed_bytes, authenticator):
        calls.append((algorithm, signer_identity, signed_bytes, authenticator))
        return (
            algorithm == envelope.authenticator_algorithm
            and signer_identity == envelope.signer_identity
            and signed_bytes == envelope.signing_bytes()
            and authenticator == AUTHENTICATOR
        )

    return verify


def test_closed_policy_and_envelope_parsers_round_trip_without_trusting_them():
    policy = _policy()
    packet_identity = {
        "review_request_sha256": "a" * 64,
        "request_sha256": "b" * 64,
    }
    envelope = _envelope(packet_identity)

    parsed_policy = broker_human_paper_approval.policy_from_payload(
        deepcopy(policy.payload())
    )
    parsed_envelope = broker_human_paper_approval.envelope_from_payload(
        deepcopy(envelope.payload())
    )
    assert parsed_policy == policy
    assert parsed_policy.sha256() == policy.sha256()
    assert parsed_envelope == envelope
    assert parsed_envelope.sha256() == envelope.sha256()
    assert (
        broker_human_paper_approval.policy_from_json(
            json.dumps(policy.payload(), separators=(",", ":"))
        )
        == policy
    )
    assert (
        broker_human_paper_approval.envelope_from_json(
            json.dumps(envelope.payload(), separators=(",", ":")).encode()
        )
        == envelope
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("schema_version",), 2),
        (("authorized_modes",), ("agent_only", "hybrid")),
        (("authorized_modes",), ["hybrid", "agent_only"]),
        (("authorized_signer_identities",), ["operator-one", "operator-one"]),
        (("valid_from",), "2026-09-13T12:00:00+00:00"),
        (("valid_until",), "2026-09-13T12:05:00.000000Z"),
        (("max_approval_seconds",), 120.0),
    ],
)
def test_policy_parser_rejects_noncanonical_or_wrongly_typed_fields(path, value):
    payload = _policy().payload()
    payload[path[0]] = value

    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        broker_human_paper_approval.policy_from_payload(payload)


def test_policy_parser_rejects_missing_and_unknown_fields():
    missing = _policy().payload()
    missing.pop("approval_source_id")
    extra = {**_policy().payload(), "public_key": "not-accepted"}

    for payload in (missing, extra):
        with pytest.raises(
            broker_human_paper_approval.HumanPaperApprovalError,
            match="shape is invalid",
        ):
            broker_human_paper_approval.policy_from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("issued_at", "2026-09-13T12:00:02+00:00"),
        ("not_before", "2026-09-13T12:00:02.000000Z"),
        ("expires_at", "2026-09-13T12:01:00+00:00"),
        ("decision", "approve"),
        ("authenticator_base64", "not-base64!"),
    ],
)
def test_envelope_parser_rejects_noncanonical_or_wrongly_typed_fields(field, value):
    payload = _envelope(
        {
            "review_request_sha256": "a" * 64,
            "request_sha256": "b" * 64,
        }
    ).payload()
    payload[field] = value

    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        broker_human_paper_approval.envelope_from_payload(payload)


def test_envelope_parser_rejects_missing_and_unknown_fields():
    envelope = _envelope(
        {
            "review_request_sha256": "a" * 64,
            "request_sha256": "b" * 64,
        }
    ).payload()
    missing = deepcopy(envelope)
    missing.pop("signer_identity")
    extra = {**envelope, "submission_authority": "paper"}

    for payload in (missing, extra):
        with pytest.raises(
            broker_human_paper_approval.HumanPaperApprovalError,
            match="shape is invalid",
        ):
            broker_human_paper_approval.envelope_from_payload(payload)


@pytest.mark.parametrize(
    ("loader", "payload"),
    [
        (
            broker_human_paper_approval.policy_from_json,
            b'{"schema_version":1,"schema_version":1}',
        ),
        (
            broker_human_paper_approval.envelope_from_json,
            b'{"approval_id":"one","approval_id":"two"}',
        ),
        (broker_human_paper_approval.policy_from_json, b"[]"),
        (broker_human_paper_approval.envelope_from_json, b"null"),
        (broker_human_paper_approval.policy_from_json, b""),
        (broker_human_paper_approval.envelope_from_json, b"\xff"),
    ],
)
def test_json_parsers_reject_duplicate_keys_non_objects_empty_and_invalid_utf8(
    loader,
    payload,
):
    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        loader(payload)


def test_json_parsers_enforce_independent_size_limits():
    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="exceeds",
    ):
        broker_human_paper_approval.policy_from_json(
            b"x" * (broker_human_paper_approval.MAX_POLICY_JSON_BYTES + 1)
        )
    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="exceeds",
    ):
        broker_human_paper_approval.envelope_from_json(
            b"x" * (broker_human_paper_approval.MAX_ENVELOPE_JSON_BYTES + 1)
        )


def test_explicit_external_policy_authenticates_exact_decision_without_authority(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet)
    before = _counts(con)
    calls = []

    result = broker_human_paper_approval.verify_authenticated_decision(
        envelope,
        deepcopy(packet),
        policy,
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=_accept_expected(envelope, calls),
        observed_at=NOW + timedelta(seconds=3),
    )

    assert len(calls) == 1
    assert result["status"] == "authenticated_decision_design_evidence"
    assert result["decision"] == "approve_exact_intent"
    assert result["approval_id"] == "one-use-approval-1"
    assert result["review_request_sha256"] == packet["review_request_sha256"]
    assert result["request_sha256"] == packet["request_sha256"]
    assert result["envelope_sha256"] == envelope.sha256()
    assert result["signing_payload_sha256"] == canonical_sha256(
        envelope.signing_payload()
    )
    assert result["selected_policy_sha256"] == policy.sha256()
    assert result["packet_integrity_verified"] is True
    assert result["retained_evidence_revalidated"] is False
    assert result["authenticator_verified"] is True
    assert result["policy_scope_verified"] is True
    assert result["trust_source_loader_implemented"] is False
    assert result["one_use_enforcement_implemented"] is False
    assert result["human_order_approval_granted"] is False
    assert result["persistence_implemented"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    body = {key: value for key, value in result.items() if key != "verification_sha256"}
    assert result["verification_sha256"] == canonical_sha256(body)
    assert _counts(con) == before


def test_retained_composition_reloads_evidence_before_authentication_without_authority(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet)
    before = _counts(con)
    calls = []

    result = broker_human_paper_approval.verify_retained_authenticated_decision(
        con,
        envelope,
        deepcopy(packet),
        policy,
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=_accept_expected(envelope, calls),
        observed_at=NOW + timedelta(seconds=3),
    )

    assert len(calls) == 1
    assert result["status"] == "authenticated_decision_design_evidence"
    assert result["packet_integrity_verified"] is True
    assert result["retained_evidence_revalidated"] is True
    assert result["authenticator_verified"] is True
    assert result["trust_source_loader_implemented"] is False
    assert result["one_use_enforcement_implemented"] is False
    assert result["human_order_approval_granted"] is False
    assert result["persistence_implemented"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    body = {key: value for key, value in result.items() if key != "verification_sha256"}
    assert result["verification_sha256"] == canonical_sha256(body)
    assert _counts(con) == before


def test_retained_composition_rejects_rehashed_forgery_before_authenticator(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    forged = deepcopy(packet)
    forged["decision_evidence"]["terminal_event_sha256"] = "f" * 64
    forged_body = {
        key: value
        for key, value in forged.items()
        if key != "review_request_sha256"
    }
    forged["review_request_sha256"] = canonical_sha256(forged_body)
    policy = _policy()
    envelope = _envelope(forged)
    calls = []

    assert broker_human_paper_review.verify(forged) == forged
    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="does not match retained evidence",
    ):
        broker_human_paper_approval.verify_retained_authenticated_decision(
            con,
            envelope,
            forged,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: calls.append(_args) or True,
            observed_at=NOW + timedelta(seconds=3),
        )
    assert calls == []


def test_reject_decision_can_be_authenticated_but_grants_no_authority(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet, decision="reject")

    result = broker_human_paper_approval.verify_authenticated_decision(
        envelope,
        packet,
        policy,
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=_accept_expected(envelope, []),
        observed_at=NOW + timedelta(seconds=3),
    )

    assert result["decision"] == "reject"
    assert result["human_order_approval_granted"] is False
    assert result["submission_authority"] == "none"


def test_signing_payload_is_canonical_and_excludes_authenticator(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    envelope = _envelope(packet)

    assert envelope.signing_bytes().decode("ascii") == (
        '{"approval_id":"one-use-approval-1",'
        '"approval_source_id":"operator-controlled-offline-source",'
        '"authenticator_algorithm":"external-test-algorithm",'
        '"decision":"approve_exact_intent",'
        '"expires_at":"2026-09-13T12:01:00Z",'
        '"issued_at":"2026-09-13T12:00:02Z",'
        '"not_before":"2026-09-13T12:00:02Z",'
        f'"request_sha256":"{packet["request_sha256"]}",'
        f'"review_request_sha256":"{packet["review_request_sha256"]}",'
        '"schema_version":1,'
        '"signer_identity":"operator-one",'
        '"signer_policy_id":"paper-review-signers",'
        '"signer_policy_version":"v1"}'
    )
    assert "authenticator_base64" not in envelope.signing_payload()
    assert envelope.payload()["authenticator_base64"] == base64.b64encode(
        AUTHENTICATOR
    ).decode("ascii")


@pytest.mark.parametrize(
    "policy_change",
    [
        {"approval_source_id": "different-source"},
        {"signer_policy_id": "different-policy"},
        {"signer_policy_version": "v2"},
        {"authenticator_algorithm": "different-algorithm"},
        {"authorized_signer_identities": ("operator-two",)},
        {"authorized_modes": ("hybrid",)},
        {"authorized_policy_ids": ("different-policy",)},
        {"authorized_account_ids": ("different-account",)},
    ],
)
def test_selected_policy_must_match_envelope_and_exact_paper_scope(
    con,
    monkeypatch,
    policy_change,
):
    packet = _packet(con, monkeypatch)
    policy = _policy(**policy_change)
    envelope = _envelope(packet)

    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        broker_human_paper_approval.verify_authenticated_decision(
            envelope,
            packet,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: True,
            observed_at=NOW + timedelta(seconds=3),
        )


def test_caller_cannot_substitute_a_different_policy_under_selected_hash(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    changed = replace(policy, max_approval_seconds=30)

    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="explicitly selected policy identity",
    ):
        broker_human_paper_approval.verify_authenticated_decision(
            _envelope(packet),
            packet,
            changed,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: True,
            observed_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    "envelope_change",
    [
        {"review_request_sha256": "a" * 64},
        {"request_sha256": "b" * 64},
        {"issued_at": NOW},
        {"not_before": NOW + timedelta(seconds=10)},
        {"expires_at": NOW + timedelta(seconds=130)},
    ],
)
def test_exact_packet_request_and_time_bindings_fail_closed(
    con,
    monkeypatch,
    envelope_change,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet, **envelope_change)

    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        broker_human_paper_approval.verify_authenticated_decision(
            envelope,
            packet,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: True,
            observed_at=NOW + timedelta(seconds=3),
        )


def test_tampered_review_packet_fails_before_authenticator_call(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    tampered = deepcopy(packet)
    tampered["order_request"]["quantity"] = 6.0
    policy = _policy()
    calls = []

    with pytest.raises(broker_human_paper_approval.HumanPaperApprovalError):
        broker_human_paper_approval.verify_authenticated_decision(
            _envelope(packet),
            tampered,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: calls.append(_args) or True,
            observed_at=NOW + timedelta(seconds=3),
        )
    assert calls == []


@pytest.mark.parametrize("verifier_result", [False, None, 1, "true"])
def test_external_verifier_must_return_literal_true(
    con,
    monkeypatch,
    verifier_result,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()

    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="authenticator verification failed",
    ):
        broker_human_paper_approval.verify_authenticated_decision(
            _envelope(packet),
            packet,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: verifier_result,
            observed_at=NOW + timedelta(seconds=3),
        )


def test_external_verifier_exception_fails_closed(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    policy = _policy()

    def unavailable(*_args):
        raise RuntimeError("external trust source unavailable")

    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="authenticator verification failed",
    ):
        broker_human_paper_approval.verify_authenticated_decision(
            _envelope(packet),
            packet,
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=unavailable,
            observed_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "not-base64!",
        base64.b64encode(b"x" * 16_385).decode("ascii"),
        base64.b64encode(b"authenticator").decode("ascii").rstrip("="),
    ],
)
def test_authenticator_encoding_is_bounded_canonical_base64(
    con,
    monkeypatch,
    encoded,
):
    packet = _packet(con, monkeypatch)

    with pytest.raises(
        broker_human_paper_approval.HumanPaperApprovalError,
        match="authenticator is invalid",
    ):
        _envelope(packet, authenticator_base64=encoded)


def test_module_has_no_selected_policy_key_store_writer_or_authority_surface():
    assert {
        "activate",
        "approve",
        "create_table",
        "insert",
        "issue",
        "load_trust_store",
        "persist",
        "private_key",
        "submit",
        "submit_order",
        "trust_store",
        "update",
        "write",
    }.isdisjoint(vars(broker_human_paper_approval))


def _record(
    con,
    packet,
    policy,
    envelope,
    *,
    observed_at=NOW + timedelta(seconds=3),
    recorded_at=NOW + timedelta(seconds=4),
):
    broker_human_paper_approval_store.init_schema(con)
    return broker_human_paper_approval_store.record_retained_authenticated_decision(
        con,
        envelope,
        deepcopy(packet),
        policy,
        selected_policy_sha256=policy.sha256(),
        authenticator_verifier=_accept_expected(envelope, []),
        observed_at=observed_at,
        recorded_at=recorded_at,
    )


def test_authenticated_decision_observation_is_hash_chained_and_non_authorizing(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet)
    before = _counts(con)

    result = _record(con, packet, policy, envelope)

    assert result["status"] == "authenticated_decision_observed_non_authorizing"
    assert result["observation_sequence"] == 1
    assert result["approval_id"] == envelope.approval_id
    assert result["envelope_sha256"] == envelope.sha256()
    assert result["review_request_sha256"] == packet["review_request_sha256"]
    assert result["request_sha256"] == packet["request_sha256"]
    assert result["decision"] == "approve_exact_intent"
    assert result["prior_observation_sha256"] is None
    assert result["authenticated_evidence_replay_protection"] is True
    assert result["production_authority_consumption_implemented"] is False
    assert result["human_order_approval_granted"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    assert result["observation_sha256"] == canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key != "observation_sha256"
        }
    )
    assert _counts(con) == before
    assert broker_human_paper_approval_store.status(con) == {
        "schema_version": 1,
        "status": "initialized",
        "observation_count": 1,
        "approve_observation_count": 1,
        "reject_observation_count": 0,
        "latest_recorded_at": "2026-09-13T12:00:04Z",
        "latest_observation_sha256": result["observation_sha256"],
        "authenticated_evidence_replay_protection_implemented": True,
        "production_authority_consumption_implemented": False,
        "trust_source_loader_implemented": False,
        "human_order_approval_granted": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def test_exact_authenticated_evidence_replay_is_idempotent(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet)

    first = _record(con, packet, policy, envelope)
    replay = (
        broker_human_paper_approval_store.record_retained_authenticated_decision(
            con,
            envelope,
            deepcopy(packet),
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: pytest.fail(
                "exact retained replay must not re-authenticate"
            ),
            observed_at=NOW + timedelta(seconds=180),
            recorded_at=NOW + timedelta(seconds=181),
        )
    )

    assert replay == first
    assert con.execute(
        "SELECT COUNT(*) FROM broker_human_paper_approval_observations"
    ).fetchone() == (1,)


@pytest.mark.parametrize(
    "envelope_changes",
    [
        {"decision": "reject"},
        {"approval_id": "one-use-approval-2"},
    ],
)
def test_conflicting_approval_or_request_identity_reuse_fails_closed(
    con,
    monkeypatch,
    envelope_changes,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    first = _envelope(packet)
    _record(con, packet, policy, first)
    conflicting = _envelope(packet, **envelope_changes)

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="conflicts with retained evidence",
    ):
        _record(con, packet, policy, conflicting)

    assert con.execute(
        "SELECT approval_id, decision FROM "
        "broker_human_paper_approval_observations"
    ).fetchall() == [("one-use-approval-1", "approve_exact_intent")]


def test_authenticated_rejection_is_retained_but_never_grants_authority(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet, decision="reject")

    result = _record(con, packet, policy, envelope)
    status = broker_human_paper_approval_store.status(con)

    assert result["decision"] == "reject"
    assert result["human_order_approval_granted"] is False
    assert result["submission_authority"] == "none"
    assert status["approve_observation_count"] == 0
    assert status["reject_observation_count"] == 1


def test_distinct_authenticated_observations_form_one_global_chain(
    con,
    monkeypatch,
):
    result = _accepted(con, monkeypatch)
    first_request = _request()
    second_request = _request(quantity=4.0)
    first_packet = broker_human_paper_review.build(
        con,
        first_request,
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    second_packet = broker_human_paper_review.build(
        con,
        second_request,
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    policy = _policy()

    first = _record(con, first_packet, policy, _envelope(first_packet))
    second = _record(
        con,
        second_packet,
        policy,
        _envelope(second_packet, approval_id="one-use-approval-2"),
        observed_at=NOW + timedelta(seconds=5),
        recorded_at=NOW + timedelta(seconds=6),
    )

    assert first["observation_sequence"] == 1
    assert second["observation_sequence"] == 2
    assert second["prior_observation_sha256"] == first["observation_sha256"]
    assert second["request_sha256"] != first["request_sha256"]
    assert broker_human_paper_approval_store.status(con)[
        "latest_observation_sha256"
    ] == second["observation_sha256"]


def test_complete_history_requires_exact_independently_trusted_count_and_head(
    con,
    monkeypatch,
):
    empty = broker_human_paper_approval_store.verify_complete_history(
        con,
        trusted_observation_count=0,
        trusted_latest_observation_sha256=None,
    )
    assert empty["status"] == "complete_history_verified_non_authorizing"
    assert empty["trusted_observation_count"] == 0
    assert empty["trusted_latest_observation_sha256"] is None
    assert empty["independent_head_required"] is True
    assert empty["approval_selection_implemented"] is False
    assert empty["human_order_approval_granted"] is False
    assert empty["submission_authority"] == "none"

    packet = _packet(con, monkeypatch)
    event = _record(con, packet, _policy(), _envelope(packet))
    result = broker_human_paper_approval_store.verify_complete_history(
        con,
        trusted_observation_count=1,
        trusted_latest_observation_sha256=event["observation_sha256"],
    )

    assert result["trusted_observation_count"] == 1
    assert result["trusted_latest_observation_sha256"] == event[
        "observation_sha256"
    ]
    assert result["approve_observation_count"] == 1
    assert result["reject_observation_count"] == 0
    assert result["history_evidence_sha256"] == canonical_sha256(
        {
            key: value
            for key, value in result.items()
            if key != "history_evidence_sha256"
        }
    )
    assert result["human_order_approval_granted"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"


def test_truncated_or_wrong_approval_history_cannot_match_trusted_head(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    event = _record(con, packet, _policy(), _envelope(packet))

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="trusted head",
    ):
        broker_human_paper_approval_store.verify_complete_history(
            con,
            trusted_observation_count=2,
            trusted_latest_observation_sha256="f" * 64,
        )

    con.execute(
        f"DELETE FROM {broker_human_paper_approval_store.TABLE}"
    )
    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="trusted head",
    ):
        broker_human_paper_approval_store.verify_complete_history(
            con,
            trusted_observation_count=1,
            trusted_latest_observation_sha256=event["observation_sha256"],
        )


@pytest.mark.parametrize(
    ("trusted_count", "trusted_head", "detail"),
    [
        (True, None, "count is invalid"),
        (-1, None, "count is invalid"),
        (0, "f" * 64, "count and head are inconsistent"),
        (1, None, "identity is invalid"),
    ],
)
def test_trusted_approval_head_shape_fails_closed(
    con,
    trusted_count,
    trusted_head,
    detail,
):
    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match=detail,
    ):
        broker_human_paper_approval_store.verify_complete_history(
            con,
            trusted_observation_count=trusted_count,
            trusted_latest_observation_sha256=trusted_head,
        )


def test_approval_history_change_during_verification_fails_closed(
    con,
    monkeypatch,
):
    packet = _packet(con, monkeypatch)
    event = _record(con, packet, _policy(), _envelope(packet))
    captured = broker_human_paper_approval_store._capture_rows(con)
    values = iter((captured, ("present", ())))
    monkeypatch.setattr(
        broker_human_paper_approval_store,
        "_capture_rows",
        lambda *_args: next(values),
    )

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="changed during verification",
    ):
        broker_human_paper_approval_store.verify_complete_history(
            con,
            trusted_observation_count=1,
            trusted_latest_observation_sha256=event["observation_sha256"],
        )


def test_approval_history_schema_appearance_during_verification_fails_closed(
    con,
    monkeypatch,
):
    values = iter((("missing", ()), ("present", ())))
    monkeypatch.setattr(
        broker_human_paper_approval_store,
        "_capture_rows",
        lambda *_args: next(values),
    )

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="changed during verification",
    ):
        broker_human_paper_approval_store.verify_complete_history(
            con,
            trusted_observation_count=0,
            trusted_latest_observation_sha256=None,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        (
            "UPDATE broker_human_paper_approval_observations "
            "SET envelope_payload = ?",
            '{"tampered":true}',
        ),
        (
            "UPDATE broker_human_paper_approval_observations "
            "SET prior_observation_sha256 = ?",
            "f" * 64,
        ),
        (
            "UPDATE broker_human_paper_approval_observations "
            "SET observation_sha256 = ?",
            "f" * 64,
        ),
    ],
)
def test_retained_approval_payload_or_chain_tampering_fails_closed(
    con,
    monkeypatch,
    mutation,
):
    packet = _packet(con, monkeypatch)
    _record(con, packet, _policy(), _envelope(packet))
    query, value = mutation
    con.execute(query, [value])

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="stored",
    ):
        broker_human_paper_approval_store.status(con)


def test_missing_approval_ledger_fails_before_authentication(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    policy = _policy()
    envelope = _envelope(packet)
    calls = []

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="not initialized",
    ):
        broker_human_paper_approval_store.record_retained_authenticated_decision(
            con,
            envelope,
            deepcopy(packet),
            policy,
            selected_policy_sha256=policy.sha256(),
            authenticator_verifier=lambda *_args: calls.append(_args) or True,
            observed_at=NOW + timedelta(seconds=3),
            recorded_at=NOW + timedelta(seconds=4),
        )

    assert calls == []
    assert broker_human_paper_approval_store.TABLE not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }


def test_recording_failure_rolls_back_new_observation(con, monkeypatch):
    packet = _packet(con, monkeypatch)
    broker_human_paper_approval_store.init_schema(con)
    original = broker_human_paper_approval_store._verified_events
    calls = 0

    def fail_post_write(actual):
        nonlocal calls
        calls += 1
        events = original(actual)
        if calls == 2:
            raise broker_human_paper_approval_store.HumanPaperApprovalStoreError(
                "forced post-write verification failure"
            )
        return events

    monkeypatch.setattr(
        broker_human_paper_approval_store,
        "_verified_events",
        fail_post_write,
    )

    with pytest.raises(
        broker_human_paper_approval_store.HumanPaperApprovalStoreError,
        match="forced post-write",
    ):
        _record(con, packet, _policy(), _envelope(packet))

    assert con.execute(
        f"SELECT COUNT(*) FROM {broker_human_paper_approval_store.TABLE}"
    ).fetchone() == (0,)


def test_approval_observation_store_has_no_route_adapter_or_submission_surface():
    assert {
        "activate",
        "approve",
        "cancel",
        "issue_lease",
        "route",
        "submit",
        "submit_order",
    }.isdisjoint(vars(broker_human_paper_approval_store))
