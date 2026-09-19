"""Read-only human-review packet for one exact future simulator intent.

The packet is derived from retained agent-only or hybrid decision evidence and
is short-lived so an operator reviews one immutable request, not a reusable
capability. This module does not select a trust source or signer policy,
accept an approval, issue a lease, persist state, or submit an order.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import duckdb

from engine.lib.provenance import canonical_sha256

from . import agent_paper_evidence
from .broker_contract import SubmitOrderRequest, require_identifier

REVIEW_SCHEMA_VERSION = 2
REVIEW_TTL_SECONDS = 300
REVIEW_SCOPE = "one_exact_simulator_intent"
STATUS = "awaiting_external_human_review"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HumanPaperReviewError(ValueError):
    """Retained evidence cannot produce one exact human-review packet."""


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise HumanPaperReviewError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "human paper review time").isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HumanPaperReviewError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanPaperReviewError(f"{label} is invalid") from exc
    if _timestamp(parsed) != value:
        raise HumanPaperReviewError(f"{label} is invalid")
    return parsed


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HumanPaperReviewError(f"{label} is invalid")
    return value


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise HumanPaperReviewError(str(exc)) from exc


def _finite(value: object, label: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        raise HumanPaperReviewError(f"{label} is invalid")
    return float(value)


def _text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise HumanPaperReviewError(f"{label} is invalid")
    return value


def _request_payload(request: SubmitOrderRequest) -> dict:
    return {
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "symbol": request.symbol,
        "side": request.side,
        "quantity": request.quantity,
        "signal_date": request.signal_date.isoformat(),
        "order_type": request.order_type,
        "time_in_force": request.time_in_force,
        "extended_hours": request.extended_hours,
    }


def _request(value: object) -> SubmitOrderRequest:
    if not isinstance(value, dict):
        raise HumanPaperReviewError("human paper review order request is invalid")
    expected_fields = {
        "idempotency_key",
        "account_id",
        "symbol",
        "side",
        "quantity",
        "signal_date",
        "order_type",
        "time_in_force",
        "extended_hours",
    }
    if set(value) != expected_fields:
        raise HumanPaperReviewError("human paper review order request is invalid")
    try:
        return SubmitOrderRequest(
            idempotency_key=value["idempotency_key"],
            account_id=value["account_id"],
            symbol=value["symbol"],
            side=value["side"],
            quantity=value["quantity"],
            signal_date=datetime.strptime(
                value["signal_date"],
                "%Y-%m-%d",
            ).date(),
            order_type=value["order_type"],
            time_in_force=value["time_in_force"],
            extended_hours=value["extended_hours"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HumanPaperReviewError(
            "human paper review order request is invalid"
        ) from exc


def _agent_evidence(loaded: agent_paper_evidence.LoadedAgentPaperIntent) -> dict:
    bindings = loaded.bindings
    return {
        "kind": "agent_only_accepted_proposal",
        "attempt_id": loaded.attempt_id,
        "proposal_record_id": loaded.proposal_record_id,
        "proposal_sha256": bindings.proposal_sha256,
        "validation_sha256": bindings.validation_sha256,
        "terminal_event_sha256": loaded.terminal_event_sha256,
        "terminal_status": bindings.proposal_status,
        "intent_bindings_sha256": bindings.sha256(),
        "loaded_evidence_sha256": loaded.evidence_sha256,
    }


def _hybrid_evidence(
    loaded: agent_paper_evidence.LoadedHybridPaperIntent,
) -> dict:
    bindings = loaded.bindings
    return {
        "kind": "hybrid_effective_order",
        "attempt_id": loaded.attempt_id,
        "candidate_sha256": bindings.candidate_sha256,
        "effective_orders_sha256": bindings.effective_orders_sha256,
        "terminal_event_sha256": loaded.terminal_event_sha256,
        "terminal_status": bindings.terminal_status,
        "model_failure_fallback_applied": (
            bindings.terminal_status == "hybrid_fallback_allow"
        ),
        "intent_bindings_sha256": bindings.sha256(),
        "loaded_evidence_sha256": loaded.evidence_sha256,
    }


def _review_summary(
    loaded: (
        agent_paper_evidence.LoadedAgentPaperIntent
        | agent_paper_evidence.LoadedHybridPaperIntent
    ),
) -> dict:
    if isinstance(loaded, agent_paper_evidence.LoadedAgentPaperIntent):
        return {
            "kind": "validated_agent_proposal",
            "signal_close": loaded.signal_close,
            "request_notional": loaded.request_notional,
            "maximum_notional": loaded.bindings.max_notional,
            "stop": loaded.stop,
            "confidence": loaded.confidence,
            "thesis": loaded.thesis,
            "invalidation": loaded.invalidation,
            "rationale_classification": "untrusted_model_rationale",
            "deterministic_validation_status": "pass",
        }
    return {
        "kind": "validated_hybrid_effect",
        "source_portfolio_id": loaded.source_portfolio_id,
        "signal_close": loaded.signal_close,
        "signal_notional": loaded.signal_notional,
        "candidate_order_count": loaded.candidate_order_count,
        "effective_order_count": loaded.effective_order_count,
        "vetoed_order_count": loaded.vetoed_order_count,
        "model_decision": loaded.model_decision,
        "decision_reason": loaded.decision_reason,
        "reason_classification": (
            "registered_model_failure_fallback"
            if loaded.bindings.terminal_status == "hybrid_fallback_allow"
            else "untrusted_model_rationale"
        ),
        "requested_order_survived": True,
    }


def _body(
    loaded: (
        agent_paper_evidence.LoadedAgentPaperIntent
        | agent_paper_evidence.LoadedHybridPaperIntent
    ),
    *,
    generated_at: datetime,
) -> dict:
    generated_at = _utc(generated_at, "human paper review generation time")
    bindings = loaded.bindings
    if isinstance(loaded, agent_paper_evidence.LoadedAgentPaperIntent):
        if generated_at < loaded.evidence_observed_at:
            raise HumanPaperReviewError(
                "human review precedes retained agent evidence"
            )
        if generated_at >= bindings.proposal_expires_at:
            raise HumanPaperReviewError(
                "accepted agent proposal expired before human review"
            )
        evidence = _agent_evidence(loaded)
        expires_at = min(
            bindings.proposal_expires_at,
            generated_at + timedelta(seconds=REVIEW_TTL_SECONDS),
        )
    elif isinstance(loaded, agent_paper_evidence.LoadedHybridPaperIntent):
        if generated_at < bindings.evidence_observed_at:
            raise HumanPaperReviewError(
                "human review precedes retained hybrid evidence"
            )
        evidence = _hybrid_evidence(loaded)
        expires_at = generated_at + timedelta(seconds=REVIEW_TTL_SECONDS)
    else:
        raise TypeError("loaded evidence must be a supported paper intent")
    request = _request_payload(loaded.request)
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": STATUS,
        "review_scope": REVIEW_SCOPE,
        "environment": "simulator",
        "mode": bindings.mode,
        "policy_id": bindings.policy_id,
        "policy_registration_sha256": bindings.policy_registration_sha256,
        "reserved_portfolio_id": loaded.request.account_id,
        "decision_window_id": bindings.decision_window_id,
        "context_sha256": bindings.context_sha256,
        "data_snapshot_sha256": bindings.data_snapshot_sha256,
        "order_request": request,
        "request_sha256": canonical_sha256(request),
        "decision_evidence": evidence,
        "review_summary": _review_summary(loaded),
        "generated_at": _timestamp(generated_at),
        "expires_at": _timestamp(expires_at),
        "required_operator_decision": ["approve_exact_intent", "reject"],
        "approval_source": "not_selected",
        "signer_policy": "not_selected",
        "approval_verifier_implemented": False,
        "approval_present": False,
        "lease_issued": False,
        "portfolio_activation_implemented": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
    }


def _evidence_scalars_valid(
    evidence: dict, evidence_fields: set[str], integer_fields: set[str]
) -> bool:
    hash_fields = evidence_fields - {
        "kind",
        "terminal_status",
        "model_failure_fallback_applied",
        *integer_fields,
    }
    return all(
        isinstance(evidence[field], int)
        and not isinstance(evidence[field], bool)
        and evidence[field] > 0
        for field in integer_fields
    ) and all(
        isinstance(evidence[field], str)
        and _SHA256.fullmatch(evidence[field]) is not None
        for field in hash_fields
    )


def _decision_evidence_valid(mode: object, evidence: object) -> bool:
    common_fields = {
        "attempt_id",
        "terminal_event_sha256",
        "terminal_status",
        "intent_bindings_sha256",
        "loaded_evidence_sha256",
    }
    if mode == "agent_only":
        evidence_fields = common_fields | {
            "kind",
            "proposal_record_id",
            "proposal_sha256",
            "validation_sha256",
        }
        integer_fields = {"attempt_id", "proposal_record_id"}
        valid = (
            isinstance(evidence, dict)
            and set(evidence) == evidence_fields
            and evidence.get("kind") == "agent_only_accepted_proposal"
            and evidence.get("terminal_status") == "shadow_accepted"
        )
    elif mode == "hybrid":
        evidence_fields = common_fields | {
            "kind",
            "candidate_sha256",
            "effective_orders_sha256",
            "model_failure_fallback_applied",
        }
        integer_fields = {"attempt_id"}
        valid = (
            isinstance(evidence, dict)
            and set(evidence) == evidence_fields
            and evidence.get("kind") == "hybrid_effective_order"
            and evidence.get("terminal_status")
            in {"hybrid_allow", "hybrid_veto", "hybrid_fallback_allow"}
            and type(evidence.get("model_failure_fallback_applied")) is bool
            and evidence["model_failure_fallback_applied"]
            is (evidence["terminal_status"] == "hybrid_fallback_allow")
        )
    else:
        return False
    return valid and _evidence_scalars_valid(evidence, evidence_fields, integer_fields)


def verify(packet: object) -> dict:
    """Verify packet integrity without treating it as approval or authority."""
    expected_fields = {
        "schema_version",
        "status",
        "review_scope",
        "environment",
        "mode",
        "policy_id",
        "policy_registration_sha256",
        "reserved_portfolio_id",
        "decision_window_id",
        "context_sha256",
        "data_snapshot_sha256",
        "order_request",
        "request_sha256",
        "decision_evidence",
        "review_summary",
        "generated_at",
        "expires_at",
        "required_operator_decision",
        "approval_source",
        "signer_policy",
        "approval_verifier_implemented",
        "approval_present",
        "lease_issued",
        "portfolio_activation_implemented",
        "paper_order_route",
        "submission_authority",
        "review_request_sha256",
    }
    if not isinstance(packet, dict) or set(packet) != expected_fields:
        raise HumanPaperReviewError("human paper review packet shape is invalid")
    body = {
        key: value for key, value in packet.items() if key != "review_request_sha256"
    }
    request = packet["order_request"]
    evidence = packet["decision_evidence"]
    review_summary = packet["review_summary"]
    request_value = _request(request)
    normalized_request = _request_payload(request_value)
    generated_at = _parse_timestamp(
        packet["generated_at"],
        "human paper review generation time",
    )
    expires_at = _parse_timestamp(
        packet["expires_at"],
        "human paper review expiry",
    )
    evidence_valid = _decision_evidence_valid(packet["mode"], evidence)
    if packet["mode"] == "agent_only":
        summary_valid = (
            isinstance(review_summary, dict)
            and set(review_summary)
            == {
                "kind",
                "signal_close",
                "request_notional",
                "maximum_notional",
                "stop",
                "confidence",
                "thesis",
                "invalidation",
                "rationale_classification",
                "deterministic_validation_status",
            }
            and review_summary.get("kind") == "validated_agent_proposal"
            and review_summary.get("rationale_classification")
            == "untrusted_model_rationale"
            and review_summary.get("deterministic_validation_status") == "pass"
        )
        if summary_valid:
            signal_close = _finite(
                review_summary["signal_close"],
                "human review signal close",
                positive=True,
            )
            request_notional = _finite(
                review_summary["request_notional"],
                "human review request notional",
                positive=True,
            )
            maximum_notional = _finite(
                review_summary["maximum_notional"],
                "human review maximum notional",
                positive=True,
            )
            stop = review_summary["stop"]
            summary_valid = (
                (stop is None or _finite(stop, "human review stop", positive=True) > 0)
                and 0
                <= _finite(
                    review_summary["confidence"],
                    "human review confidence",
                )
                <= 1
                and math.isclose(
                    request_notional,
                    request_value.quantity * signal_close,
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                )
                and request_notional <= maximum_notional
            )
            _text(review_summary["thesis"], "human review thesis", 4_096)
            _text(
                review_summary["invalidation"],
                "human review invalidation",
                2_048,
            )
    elif packet["mode"] == "hybrid":
        summary_valid = (
            isinstance(review_summary, dict)
            and set(review_summary)
            == {
                "kind",
                "source_portfolio_id",
                "signal_close",
                "signal_notional",
                "candidate_order_count",
                "effective_order_count",
                "vetoed_order_count",
                "model_decision",
                "decision_reason",
                "reason_classification",
                "requested_order_survived",
            }
            and review_summary.get("kind") == "validated_hybrid_effect"
            and review_summary.get("requested_order_survived") is True
        )
        if summary_valid:
            _identifier(
                review_summary["source_portfolio_id"],
                "human review source portfolio identifier",
            )
            signal_close = _finite(
                review_summary["signal_close"],
                "human review signal close",
                positive=True,
            )
            signal_notional = _finite(
                review_summary["signal_notional"],
                "human review signal notional",
                positive=True,
            )
            counts = tuple(
                review_summary[field]
                for field in (
                    "candidate_order_count",
                    "effective_order_count",
                    "vetoed_order_count",
                )
            )
            terminal_status = (
                evidence.get("terminal_status")
                if isinstance(evidence, dict)
                else None
            )
            expected_decision = {
                "hybrid_allow": "allow",
                "hybrid_veto": "veto",
                "hybrid_fallback_allow": None,
            }.get(terminal_status)
            expected_classification = (
                "registered_model_failure_fallback"
                if terminal_status == "hybrid_fallback_allow"
                else "untrusted_model_rationale"
            )
            summary_valid = (
                all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in counts
                )
                and counts[0] > 0
                and counts[1] > 0
                and counts[0] - counts[1] == counts[2]
                and review_summary["model_decision"] == expected_decision
                and review_summary["reason_classification"]
                == expected_classification
                and math.isclose(
                    signal_notional,
                    request_value.quantity * signal_close,
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                )
            )
            _text(
                review_summary["decision_reason"],
                "human review decision reason",
                agent_paper_evidence.MAX_RESULT_REASON_CHARS,
            )
    else:
        summary_valid = False
    if (
        type(packet["schema_version"]) is not int
        or packet["schema_version"] != REVIEW_SCHEMA_VERSION
        or packet["status"] != STATUS
        or packet["review_scope"] != REVIEW_SCOPE
        or packet["environment"] != "simulator"
        or not isinstance(packet["reserved_portfolio_id"], str)
        or packet["reserved_portfolio_id"] != request_value.account_id
        or packet["required_operator_decision"]
        != ["approve_exact_intent", "reject"]
        or packet["approval_source"] != "not_selected"
        or packet["signer_policy"] != "not_selected"
        or packet["approval_verifier_implemented"] is not False
        or packet["approval_present"] is not False
        or packet["lease_issued"] is not False
        or packet["portfolio_activation_implemented"] is not False
        or packet["paper_order_route"] != "absent"
        or packet["submission_authority"] != "none"
        or canonical_sha256(normalized_request) != canonical_sha256(request)
        or packet["request_sha256"] != canonical_sha256(request)
        or not generated_at < expires_at
        or (expires_at - generated_at).total_seconds() > REVIEW_TTL_SECONDS
        or not evidence_valid
        or not summary_valid
        or packet["review_request_sha256"] != canonical_sha256(body)
    ):
        raise HumanPaperReviewError("human paper review packet is invalid")
    _identifier(packet["policy_id"], "human paper review policy identifier")
    _identifier(
        packet["decision_window_id"],
        "human paper review decision-window identifier",
    )
    for field in (
        "policy_registration_sha256",
        "context_sha256",
        "data_snapshot_sha256",
        "request_sha256",
        "review_request_sha256",
    ):
        _hash(packet[field], f"human paper review {field}")
    return packet


def verify_retained(
    con: duckdb.DuckDBPyConnection,
    packet: object,
    *,
    reviewed_at: datetime,
) -> dict:
    """Rebuild one unexpired packet from retained evidence without approving it."""
    verified = verify(packet)
    reviewed_at = _utc(reviewed_at, "human paper review observation time")
    generated_at = _parse_timestamp(
        verified["generated_at"],
        "human paper review generation time",
    )
    expires_at = _parse_timestamp(
        verified["expires_at"],
        "human paper review expiry",
    )
    if reviewed_at < generated_at:
        raise HumanPaperReviewError(
            "human paper review observation precedes packet generation"
        )
    if reviewed_at >= expires_at:
        raise HumanPaperReviewError("human paper review packet expired")
    request = _request(verified["order_request"])
    try:
        if verified["mode"] == "agent_only":
            loaded = agent_paper_evidence.load_agent_only_intent(
                con,
                request,
                decision_window_id=verified["decision_window_id"],
            )
        else:
            loaded = agent_paper_evidence.load_hybrid_intent(
                con,
                request,
                decision_window_id=verified["decision_window_id"],
            )
    except agent_paper_evidence.AgentPaperEvidenceError as exc:
        raise HumanPaperReviewError(str(exc)) from exc
    expected_body = _body(loaded, generated_at=generated_at)
    expected = {
        **expected_body,
        "review_request_sha256": canonical_sha256(expected_body),
    }
    if verified != expected:
        raise HumanPaperReviewError(
            "human paper review packet does not match retained evidence"
        )
    return verified


def build(
    con: duckdb.DuckDBPyConnection,
    request: SubmitOrderRequest,
    *,
    decision_window_id: str,
    mode: str,
    generated_at: datetime,
) -> dict:
    """Load retained evidence and produce one non-authorizing review packet."""
    try:
        if mode == "agent_only":
            loaded = agent_paper_evidence.load_agent_only_intent(
                con,
                request,
                decision_window_id=decision_window_id,
            )
        elif mode == "hybrid":
            loaded = agent_paper_evidence.load_hybrid_intent(
                con,
                request,
                decision_window_id=decision_window_id,
            )
        else:
            raise HumanPaperReviewError("human paper review mode is invalid")
    except agent_paper_evidence.AgentPaperEvidenceError as exc:
        raise HumanPaperReviewError(str(exc)) from exc
    body = _body(loaded, generated_at=generated_at)
    return verify(
        {
            **body,
            "review_request_sha256": canonical_sha256(body),
        }
    )
