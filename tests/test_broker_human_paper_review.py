"""Exact-intent human-review packets remain short-lived and non-authorizing."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    agent_shadow_runner,
    broker_human_paper_review,
)
from tests.agent_test_helpers import fixed_etf_market
from tests.test_agent_paper_evidence import (
    NOW,
    _accepted,
    _borrowed_connection,
    _hybrid_context,
    _hybrid_order,
    _hybrid_request,
    _hybrid_run,
    _no_lock,
    _request,
)


def _counts(con) -> dict[str, int]:
    return {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "agent_shadow_attempts",
            "agent_shadow_events",
            "agent_proposals",
            "sim_orders",
            "sim_fills",
        )
    }


def _rehash(packet: dict) -> None:
    body = {
        key: value
        for key, value in packet.items()
        if key != "review_request_sha256"
    }
    packet["review_request_sha256"] = canonical_sha256(body)


def _all_keys(value: object) -> set[str]:
    keys = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            keys.update(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return keys


def _fallback_run(con, monkeypatch):
    fixed_etf_market(con)
    _hybrid_context(monkeypatch, orders=[_hybrid_order()])
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)
    return agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="hybrid",
        policy_id="dual_momentum_hybrid_veto_shadow_v1",
        generate=lambda _model_input: (_ for _ in ()).throw(
            agent_model_client.ConnectorError("Trae proxy is unavailable")
        ),
        connection_factory=lambda: con,
        now=NOW,
    )

def test_agent_only_review_binds_exact_request_without_mutation(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    before = _counts(con)

    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )

    assert packet["schema_version"] == 2
    assert packet["status"] == "awaiting_external_human_review"
    assert packet["mode"] == "agent_only"
    assert packet["policy_id"] == "dual_momentum_agent_shadow_v1"
    assert packet["reserved_portfolio_id"] == "agent_dual_momentum_shadow_v1"
    assert packet["decision_evidence"]["kind"] == "agent_only_accepted_proposal"
    assert packet["decision_evidence"]["terminal_status"] == "shadow_accepted"
    assert packet["order_request"]["symbol"] == "SPY"
    assert packet["order_request"]["quantity"] == 5.0
    assert packet["request_sha256"] == canonical_sha256(packet["order_request"])
    assert packet["review_summary"] == {
        "kind": "validated_agent_proposal",
        "signal_close": 120.0,
        "request_notional": 600.0,
        "maximum_notional": 1_000.0,
        "stop": 90.0,
        "confidence": 0.6,
        "thesis": "Retained evidence supports a bounded paper candidate.",
        "invalidation": "Invalidate if the retained evidence expires.",
        "rationale_classification": "untrusted_model_rationale",
        "deterministic_validation_status": "pass",
    }
    assert {
        "context",
        "context_payload",
        "model_input",
        "model_request",
        "prompt",
        "evidence_ids",
    }.isdisjoint(_all_keys(packet))
    assert broker_human_paper_review.verify(deepcopy(packet)) == packet
    assert (
        broker_human_paper_review.verify_retained(
            con,
            deepcopy(packet),
            reviewed_at=NOW + timedelta(seconds=2),
        )
        == packet
    )
    assert _counts(con) == before


def test_hybrid_allow_review_binds_effective_order(con, monkeypatch):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])

    packet = broker_human_paper_review.build(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
        mode="hybrid",
        generated_at=NOW + timedelta(seconds=1),
    )

    assert packet["mode"] == "hybrid"
    assert packet["policy_id"] == "dual_momentum_hybrid_veto_shadow_v1"
    assert packet["decision_evidence"]["terminal_status"] == "hybrid_allow"
    assert packet["decision_evidence"]["model_failure_fallback_applied"] is False
    assert packet["review_summary"] == {
        "kind": "validated_hybrid_effect",
        "source_portfolio_id": "dual_momentum",
        "signal_close": 100.0,
        "signal_notional": 1_000.0,
        "candidate_order_count": 1,
        "effective_order_count": 1,
        "vetoed_order_count": 0,
        "model_decision": "allow",
        "decision_reason": "Retained evidence supports allow.",
        "reason_classification": "untrusted_model_rationale",
        "requested_order_survived": True,
    }
    assert (
        broker_human_paper_review.verify_retained(
            con,
            deepcopy(packet),
            reviewed_at=NOW + timedelta(seconds=2),
        )
        == packet
    )


def test_hybrid_fallback_is_explicit_in_review_packet(con, monkeypatch):
    result = _fallback_run(con, monkeypatch)

    packet = broker_human_paper_review.build(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
        mode="hybrid",
        generated_at=NOW + timedelta(minutes=1, seconds=1),
    )

    assert packet["decision_evidence"]["terminal_status"] == "hybrid_fallback_allow"
    assert packet["decision_evidence"]["model_failure_fallback_applied"] is True
    assert packet["review_summary"]["model_decision"] is None
    assert (
        packet["review_summary"]["reason_classification"]
        == "registered_model_failure_fallback"
    )
    assert packet["review_summary"]["decision_reason"].startswith(
        "model transport failure"
    )


def test_hybrid_veto_review_shows_surviving_sell_and_removed_buy(
    con,
    monkeypatch,
):
    result = _hybrid_run(
        con,
        monkeypatch,
        orders=[
            _hybrid_order(),
            _hybrid_order(sequence=2, ticker="EFA", side="sell", quantity=4.0),
        ],
        decision="veto",
    )

    packet = broker_human_paper_review.build(
        con,
        _hybrid_request(symbol="EFA", side="sell", quantity=4.0),
        decision_window_id=result["decision_window"],
        mode="hybrid",
        generated_at=NOW + timedelta(seconds=1),
    )

    assert packet["decision_evidence"]["terminal_status"] == "hybrid_veto"
    assert packet["review_summary"]["candidate_order_count"] == 2
    assert packet["review_summary"]["effective_order_count"] == 1
    assert packet["review_summary"]["vetoed_order_count"] == 1
    assert packet["review_summary"]["model_decision"] == "veto"
    assert packet["review_summary"]["requested_order_survived"] is True
    assert packet["order_request"]["side"] == "sell"


def test_vetoed_hybrid_buy_cannot_produce_review_packet(con, monkeypatch):
    result = _hybrid_run(
        con,
        monkeypatch,
        orders=[_hybrid_order()],
        decision="veto",
    )

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="effective order set",
    ):
        broker_human_paper_review.build(
            con,
            _hybrid_request(),
            decision_window_id=result["decision_window"],
            mode="hybrid",
            generated_at=NOW + timedelta(seconds=1),
        )


def test_expired_agent_proposal_cannot_produce_review_packet(con, monkeypatch):
    result = _accepted(con, monkeypatch)

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="expired before human review",
    ):
        broker_human_paper_review.build(
            con,
            _request(),
            decision_window_id=result["decision_window"],
            mode="agent_only",
            generated_at=NOW + agent_shadow_runner.PROPOSAL_VALIDITY,
        )


def test_review_cannot_predate_retained_agent_evidence(con, monkeypatch):
    result = _accepted(con, monkeypatch)

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="precedes retained agent evidence",
    ):
        broker_human_paper_review.build(
            con,
            _request(),
            decision_window_id=result["decision_window"],
            mode="agent_only",
            generated_at=NOW - timedelta(microseconds=1),
        )


def test_review_cannot_predate_retained_hybrid_evidence(con, monkeypatch):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="precedes retained hybrid evidence",
    ):
        broker_human_paper_review.build(
            con,
            _hybrid_request(),
            decision_window_id=result["decision_window"],
            mode="hybrid",
            generated_at=NOW - timedelta(microseconds=1),
        )


@pytest.mark.parametrize(
    "broker_request",
    [
        _request(quantity=9.0),
        _request(symbol="EFA"),
        _request(account_id="different-paper-account"),
    ],
)
def test_request_drift_is_rejected_by_retained_evidence_loader(
    con,
    monkeypatch,
    broker_request,
):
    result = _accepted(con, monkeypatch)

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="does not match",
    ):
        broker_human_paper_review.build(
            con,
            broker_request,
            decision_window_id=result["decision_window"],
            mode="agent_only",
            generated_at=NOW + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("approval_present",), True),
        (("submission_authority",), "paper"),
        (("order_request", "quantity"), 6.0),
        (("review_summary", "confidence"), True),
        (("review_summary", "request_notional"), 501.0),
        (("review_summary", "rationale_classification"), "trusted_fact"),
    ],
)
def test_authority_or_request_tampering_is_rejected_even_with_recomputed_checksum(
    con,
    monkeypatch,
    path,
    value,
):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    target = packet
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _rehash(packet)

    with pytest.raises(broker_human_paper_review.HumanPaperReviewError):
        broker_human_paper_review.verify(packet)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_order_count", True),
        ("effective_order_count", 2),
        ("vetoed_order_count", 1),
        ("model_decision", "veto"),
        ("reason_classification", "trusted_fact"),
        ("requested_order_survived", False),
        ("signal_notional", 999.0),
    ],
)
def test_hybrid_review_summary_rejects_malformed_or_inconsistent_fields(
    con,
    monkeypatch,
    field,
    value,
):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])
    packet = broker_human_paper_review.build(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
        mode="hybrid",
        generated_at=NOW + timedelta(seconds=1),
    )
    packet["review_summary"][field] = value
    _rehash(packet)

    with pytest.raises(broker_human_paper_review.HumanPaperReviewError):
        broker_human_paper_review.verify(packet)


def test_malformed_hybrid_evidence_fails_with_review_error(con, monkeypatch):
    result = _hybrid_run(con, monkeypatch, orders=[_hybrid_order()])
    packet = broker_human_paper_review.build(
        con,
        _hybrid_request(),
        decision_window_id=result["decision_window"],
        mode="hybrid",
        generated_at=NOW + timedelta(seconds=1),
    )
    packet["decision_evidence"] = []
    _rehash(packet)

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="packet is invalid",
    ):
        broker_human_paper_review.verify(packet)


def test_checksum_detects_evidence_tampering_but_is_not_authentication(
    con,
    monkeypatch,
):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    packet["decision_evidence"]["terminal_event_sha256"] = "f" * 64

    with pytest.raises(broker_human_paper_review.HumanPaperReviewError):
        broker_human_paper_review.verify(packet)

    _rehash(packet)
    structurally_verified = broker_human_paper_review.verify(packet)
    assert structurally_verified["approval_source"] == "not_selected"
    assert structurally_verified["signer_policy"] == "not_selected"
    assert structurally_verified["approval_verifier_implemented"] is False
    assert structurally_verified["approval_present"] is False
    assert structurally_verified["submission_authority"] == "none"


def test_retained_verifier_rejects_rehashed_evidence_forgery(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    packet["decision_evidence"]["terminal_event_sha256"] = "f" * 64
    _rehash(packet)
    assert broker_human_paper_review.verify(packet) == packet

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="does not match retained evidence",
    ):
        broker_human_paper_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=2),
        )


def test_retained_verifier_rejects_self_consistent_review_fact_forgery(
    con,
    monkeypatch,
):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    packet["review_summary"]["signal_close"] = 121.0
    packet["review_summary"]["request_notional"] = 605.0
    _rehash(packet)
    assert broker_human_paper_review.verify(packet) == packet

    with pytest.raises(
        broker_human_paper_review.HumanPaperReviewError,
        match="does not match retained evidence",
    ):
        broker_human_paper_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=2),
        )


def test_retained_verifier_rejects_changed_source_evidence(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    con.execute(
        "UPDATE agent_shadow_events SET payload = '{}' "
        "WHERE event_type = 'model_response'"
    )

    with pytest.raises(broker_human_paper_review.HumanPaperReviewError):
        broker_human_paper_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    ("offset", "detail"),
    [
        (timedelta(0), "precedes packet generation"),
        (timedelta(seconds=301), "packet expired"),
    ],
)
def test_retained_verifier_enforces_review_time(
    con,
    monkeypatch,
    offset,
    detail,
):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(broker_human_paper_review.HumanPaperReviewError, match=detail):
        broker_human_paper_review.verify_retained(
            con,
            packet,
            reviewed_at=NOW + offset,
        )


def test_review_ttl_is_bounded_and_verification_grants_nothing(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    packet = broker_human_paper_review.build(
        con,
        _request(),
        decision_window_id=result["decision_window"],
        mode="agent_only",
        generated_at=NOW + timedelta(seconds=1),
    )
    verified = broker_human_paper_review.verify(packet)

    assert (
        broker_human_paper_review._parse_timestamp(
            verified["expires_at"],
            "expiry",
        )
        - broker_human_paper_review._parse_timestamp(
            verified["generated_at"],
            "generation",
        )
    ).total_seconds() <= broker_human_paper_review.REVIEW_TTL_SECONDS
    assert verified["required_operator_decision"] == [
        "approve_exact_intent",
        "reject",
    ]
    assert verified["approval_source"] == "not_selected"
    assert verified["signer_policy"] == "not_selected"
    assert verified["approval_verifier_implemented"] is False
    assert verified["approval_present"] is False
    assert verified["lease_issued"] is False
    assert verified["portfolio_activation_implemented"] is False
    assert verified["paper_order_route"] == "absent"
    assert verified["submission_authority"] == "none"


def test_module_has_no_writer_adapter_api_scheduler_or_authority_surface():
    assert {
        "activate",
        "approve",
        "authorize",
        "cancel_order",
        "create_table",
        "insert",
        "issue",
        "lease",
        "persist",
        "router",
        "schedule",
        "submit",
        "submit_order",
        "update",
    }.isdisjoint(vars(broker_human_paper_review))
