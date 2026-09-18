"""Pure eligibility checks for one future automatic-paper lease consumption.

This module binds one broker-neutral order intent and one verified risk
decision to an admitted paper-lease candidate. It does not activate or consume
a lease, reserve capacity, persist state, or submit an order. A passing result
is therefore evidence for a future atomic consumption mechanism only.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Literal

from engine.lib.provenance import canonical_sha256

from . import broker_paper_lease, broker_risk
from .broker_contract import SubmitOrderRequest, require_identifier, require_symbol
from .broker_paper_lease import PaperAuthorityLease

ELIGIBILITY_SCHEMA_VERSION = 1
INTENT_BINDINGS_SCHEMA_VERSION = 1
USAGE_SCHEMA_VERSION = 1
LEASE_ASSESSMENT_GATE_NAMES = broker_paper_lease.CANDIDATE_GATE_NAMES
GATE_NAMES = (
    "trusted_candidate_assessment",
    "lease_time_window",
    "trusted_agent_intent",
    "exact_risk_request",
    "risk_identity",
    "risk_pass_and_freshness",
    "lease_budget",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperIntentError(ValueError):
    """Future paper-consumption evidence violates the closed contract."""


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise PaperIntentError(str(exc)) from exc


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperIntentError(f"{label} must be a lowercase SHA-256")
    return value


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperIntentError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _nonnegative(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise PaperIntentError(f"{label} must be a nonnegative finite number")
    return float(value)


def _positive(value: object, label: str) -> float:
    number = _nonnegative(value, label)
    if number == 0:
        raise PaperIntentError(f"{label} must be a positive finite number")
    return number


def _request_payload(request: SubmitOrderRequest) -> dict:
    payload = asdict(request)
    payload["signal_date"] = request.signal_date.isoformat()
    return payload


@dataclass(frozen=True, slots=True)
class PaperIntentBindings:
    """Trusted agent-only facts absent from the broker-risk decision."""

    mode: Literal["agent_only"]
    policy_id: str
    policy_registration_sha256: str
    data_snapshot_sha256: str
    context_sha256: str
    proposal_id: str
    proposal_sha256: str
    proposal_status: Literal["shadow_accepted"]
    validation_sha256: str
    validation_status: Literal["pass"]
    decision_window_id: str
    request_sha256: str
    symbol: str
    side: Literal["buy", "sell"]
    max_notional: float
    signal_date: date
    proposal_expires_at: datetime

    def __post_init__(self) -> None:
        if self.mode != "agent_only":
            raise PaperIntentError("agent-only paper intent mode is invalid")
        _identifier(self.policy_id, "paper intent policy identifier")
        _identifier(self.proposal_id, "paper intent proposal identifier")
        _identifier(
            self.decision_window_id,
            "paper intent decision-window identifier",
        )
        _sha256(
            self.policy_registration_sha256,
            "paper intent policy registration identity",
        )
        _sha256(
            self.data_snapshot_sha256,
            "paper intent data snapshot identity",
        )
        _sha256(self.context_sha256, "paper intent context identity")
        _sha256(self.proposal_sha256, "paper intent proposal identity")
        _sha256(self.validation_sha256, "paper intent validation identity")
        _sha256(self.request_sha256, "paper intent request identity")
        try:
            require_symbol(self.symbol)
        except ValueError as exc:
            raise PaperIntentError(str(exc)) from exc
        if self.side not in {"buy", "sell"}:
            raise PaperIntentError("paper intent side is invalid")
        object.__setattr__(
            self,
            "max_notional",
            _positive(self.max_notional, "paper intent notional ceiling"),
        )
        if self.proposal_status != "shadow_accepted":
            raise PaperIntentError("paper intent proposal status is invalid")
        if self.validation_status != "pass":
            raise PaperIntentError("paper intent validation status is invalid")
        if type(self.signal_date) is not date:
            raise PaperIntentError("paper intent signal date is invalid")
        object.__setattr__(
            self,
            "proposal_expires_at",
            _utc(self.proposal_expires_at, "paper intent proposal expiry"),
        )

    def payload(self) -> dict:
        body = asdict(self)
        body["schema_version"] = INTENT_BINDINGS_SCHEMA_VERSION
        body["signal_date"] = self.signal_date.isoformat()
        body["proposal_expires_at"] = self.proposal_expires_at.isoformat().replace(
            "+00:00",
            "Z",
        )
        return body

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class HybridPaperIntentBindings:
    """Trusted hybrid candidate/outcome facts absent from broker risk."""

    mode: Literal["hybrid"]
    policy_id: str
    policy_registration_sha256: str
    data_snapshot_sha256: str
    context_sha256: str
    decision_window_id: str
    candidate_sha256: str
    terminal_event_sha256: str
    terminal_status: Literal[
        "hybrid_allow",
        "hybrid_veto",
        "hybrid_fallback_allow",
    ]
    effective_orders_sha256: str
    effective_order_included: Literal[True]
    veto_eligible: bool
    request_sha256: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    signal_date: date
    evidence_observed_at: datetime

    def __post_init__(self) -> None:
        if self.mode != "hybrid":
            raise PaperIntentError("hybrid paper intent mode is invalid")
        _identifier(self.policy_id, "hybrid policy identifier")
        _identifier(
            self.decision_window_id,
            "hybrid decision-window identifier",
        )
        for value, label in (
            (
                self.policy_registration_sha256,
                "hybrid policy registration identity",
            ),
            (self.data_snapshot_sha256, "hybrid data snapshot identity"),
            (self.context_sha256, "hybrid context identity"),
            (self.candidate_sha256, "hybrid candidate identity"),
            (self.terminal_event_sha256, "hybrid terminal event identity"),
            (self.effective_orders_sha256, "hybrid effective-orders identity"),
            (self.request_sha256, "hybrid request identity"),
        ):
            _sha256(value, label)
        if self.terminal_status not in {
            "hybrid_allow",
            "hybrid_veto",
            "hybrid_fallback_allow",
        }:
            raise PaperIntentError("hybrid terminal status is invalid")
        if self.effective_order_included is not True:
            raise PaperIntentError("hybrid intent must be in the effective order set")
        if type(self.veto_eligible) is not bool:
            raise PaperIntentError("hybrid veto eligibility must be boolean")
        if self.terminal_status == "hybrid_veto" and self.veto_eligible:
            raise PaperIntentError("hybrid veto removed the requested buy order")
        try:
            require_symbol(self.symbol)
        except ValueError as exc:
            raise PaperIntentError(str(exc)) from exc
        if self.side not in {"buy", "sell"}:
            raise PaperIntentError("hybrid intent side is invalid")
        object.__setattr__(
            self,
            "quantity",
            _positive(self.quantity, "hybrid intent quantity"),
        )
        if type(self.signal_date) is not date:
            raise PaperIntentError("hybrid intent signal date is invalid")
        object.__setattr__(
            self,
            "evidence_observed_at",
            _utc(self.evidence_observed_at, "hybrid evidence observation time"),
        )

    def payload(self) -> dict:
        body = asdict(self)
        body["schema_version"] = INTENT_BINDINGS_SCHEMA_VERSION
        body["signal_date"] = self.signal_date.isoformat()
        body["evidence_observed_at"] = self.evidence_observed_at.isoformat().replace(
            "+00:00",
            "Z",
        )
        return body

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class PaperLeaseUsage:
    """Externally retained current usage supplied by a future atomic consumer."""

    lease_id: str
    lease_sha256: str
    consumed_order_count: int
    consumed_notional: float

    def __post_init__(self) -> None:
        _identifier(self.lease_id, "paper usage lease identifier")
        _sha256(self.lease_sha256, "paper usage lease identity")
        if (
            isinstance(self.consumed_order_count, bool)
            or not isinstance(self.consumed_order_count, int)
            or self.consumed_order_count < 0
        ):
            raise PaperIntentError(
                "paper consumed order count must be a nonnegative integer"
            )
        object.__setattr__(
            self,
            "consumed_notional",
            _nonnegative(
                self.consumed_notional,
                "paper consumed notional",
            ),
        )

    def payload(self) -> dict:
        return {
            "schema_version": USAGE_SCHEMA_VERSION,
            **asdict(self),
        }

    def sha256(self) -> str:
        return canonical_sha256(self.payload())


def _verify_assessment(
    assessment: object,
    *,
    lease: PaperAuthorityLease,
    trusted_assessment_sha256: str,
) -> dict:
    try:
        return broker_paper_lease.verify_candidate_assessment(
            assessment,
            lease,
            trusted_assessment_sha256=trusted_assessment_sha256,
        )
    except broker_paper_lease.PaperLeaseError as exc:
        raise PaperIntentError(str(exc)) from exc


def assess_future_consumption(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    request: SubmitOrderRequest,
    risk_decision: object,
    intent_bindings: PaperIntentBindings | HybridPaperIntentBindings,
    usage: PaperLeaseUsage,
    *,
    trusted_assessment_sha256: str,
    trusted_intent_bindings_sha256: str,
    trusted_usage_sha256: str,
    now: datetime,
) -> dict:
    """Check one intent without activating, consuming, or granting authority."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    if not isinstance(
        intent_bindings,
        (PaperIntentBindings, HybridPaperIntentBindings),
    ):
        raise TypeError("intent_bindings must be a supported paper intent binding")
    if not isinstance(usage, PaperLeaseUsage):
        raise TypeError("usage must be a PaperLeaseUsage")
    trusted_assessment_sha256 = _sha256(
        trusted_assessment_sha256,
        "trusted paper assessment identity",
    )
    trusted_intent_bindings_sha256 = _sha256(
        trusted_intent_bindings_sha256,
        "trusted paper intent binding identity",
    )
    trusted_usage_sha256 = _sha256(
        trusted_usage_sha256,
        "trusted paper usage identity",
    )
    observed_at = _utc(now, "paper intent assessment time")
    assessment = _verify_assessment(
        candidate_assessment,
        lease=lease,
        trusted_assessment_sha256=trusted_assessment_sha256,
    )
    assessment_observed_at = datetime.fromisoformat(
        assessment["observed_at"].replace("Z", "+00:00")
    )
    verified_risk = broker_risk.verify(risk_decision)

    lease_sha256 = lease.sha256()
    request_payload = _request_payload(request)
    request_sha256 = canonical_sha256(request_payload)
    order_notional = verified_risk["computed"]["notional"]
    usage_trusted = (
        usage.sha256() == trusted_usage_sha256
        and usage.lease_id == lease.lease_id
        and usage.lease_sha256 == lease_sha256
    )
    common_intent_matches = (
        intent_bindings.sha256() == trusted_intent_bindings_sha256
        and intent_bindings.mode == lease.mode
        and intent_bindings.policy_id == lease.policy_id
        and intent_bindings.policy_registration_sha256
        == lease.policy_registration_sha256
        and intent_bindings.data_snapshot_sha256 == lease.data_snapshot_sha256
        and intent_bindings.decision_window_id == lease.decision_window_id
        and intent_bindings.request_sha256 == request_sha256
        and intent_bindings.symbol == request.symbol
        and intent_bindings.side == request.side
        and intent_bindings.signal_date == request.signal_date
    )
    if isinstance(intent_bindings, PaperIntentBindings):
        intent_matches = (
            common_intent_matches
            and order_notional <= intent_bindings.max_notional
            and observed_at < intent_bindings.proposal_expires_at
        )
    else:
        intent_matches = (
            common_intent_matches
            and request.quantity == intent_bindings.quantity
            and lease.not_before
            <= intent_bindings.evidence_observed_at
            <= observed_at
        )
    exact_risk_request = (
        verified_risk["request"] == request_payload
        and verified_risk["request_sha256"] == request_sha256
    )
    risk_policy = verified_risk["policy"]
    risk_identity = verified_risk["identity"]
    risk_identity_matches = (
        request.account_id == lease.account_id
        and request.symbol in lease.allowed_symbols
        and risk_policy["policy_id"] == lease.risk_policy_id
        and verified_risk["policy_sha256"] == lease.risk_policy_sha256
        and risk_policy["account_id"] == lease.account_id
        and risk_policy["strategy_id"] == lease.strategy_id
        and risk_policy["release_sha256"] == lease.release_manifest_sha256
        and risk_policy["strategy_config_sha256"]
        == lease.strategy_config_sha256
        and risk_policy["execution_profile_id"] == lease.execution_profile_id
        and risk_policy["execution_profile_sha256"]
        == lease.execution_profile_sha256
        and risk_policy["allowed_symbols"] == list(lease.allowed_symbols)
        and risk_identity["policy_id"] == lease.risk_policy_id
        and risk_identity["strategy_id"] == lease.strategy_id
        and risk_identity["release_sha256"] == lease.release_manifest_sha256
        and risk_identity["strategy_config_sha256"]
        == lease.strategy_config_sha256
        and risk_identity["execution_profile_id"] == lease.execution_profile_id
        and risk_identity["execution_profile_sha256"]
        == lease.execution_profile_sha256
    )
    try:
        risk_evaluated_at = datetime.fromisoformat(verified_risk["evaluated_at"])
        risk_expires_at = datetime.fromisoformat(verified_risk["expires_at"])
    except (TypeError, ValueError) as exc:
        raise PaperIntentError("paper risk validity interval is invalid") from exc
    risk_fresh = (
        verified_risk["status"] == "pass"
        and verified_risk["execution_authority"] == "none"
        and lease.not_before <= risk_evaluated_at <= observed_at
        and observed_at < risk_expires_at
        and risk_evaluated_at < lease.expires_at
    )
    budget_valid = (
        usage_trusted
        and usage.consumed_order_count <= lease.max_orders
        and usage.consumed_notional <= lease.capital_ceiling
        and order_notional <= lease.max_order_notional
        and usage.consumed_order_count + 1 <= lease.max_orders
        and usage.consumed_notional + order_notional <= lease.capital_ceiling
    )
    gates = (
        {
            "name": "trusted_candidate_assessment",
            "status": (
                "pass"
                if assessment["assessment_sha256"]
                == trusted_assessment_sha256
                else "blocked"
            ),
        },
        {
            "name": "lease_time_window",
            "status": (
                "pass"
                if lease.not_before
                <= assessment_observed_at
                <= observed_at
                < lease.expires_at
                else "blocked"
            ),
        },
        {
            "name": "trusted_agent_intent",
            "status": "pass" if intent_matches else "blocked",
        },
        {
            "name": "exact_risk_request",
            "status": "pass" if exact_risk_request else "blocked",
        },
        {
            "name": "risk_identity",
            "status": "pass" if risk_identity_matches else "blocked",
        },
        {
            "name": "risk_pass_and_freshness",
            "status": "pass" if risk_fresh else "blocked",
        },
        {
            "name": "lease_budget",
            "status": "pass" if budget_valid else "blocked",
        },
    )
    if tuple(gate["name"] for gate in gates) != GATE_NAMES:
        raise PaperIntentError("paper intent gate contract changed")
    blockers = [gate["name"] for gate in gates if gate["status"] == "blocked"]
    body = {
        "schema_version": ELIGIBILITY_SCHEMA_VERSION,
        "lease_id": lease.lease_id,
        "lease_sha256": lease_sha256,
        "candidate_assessment_sha256": assessment["assessment_sha256"],
        "intent_bindings_sha256": intent_bindings.sha256(),
        "usage_sha256": usage.sha256(),
        "request_sha256": request_sha256,
        "risk_decision_sha256": verified_risk["decision_sha256"],
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "lease_expires_at": lease.expires_at.isoformat().replace("+00:00", "Z"),
        "risk_expires_at": risk_expires_at.isoformat().replace("+00:00", "Z"),
        "order_notional": order_notional,
        "resulting_consumed_order_count": usage.consumed_order_count + 1,
        "resulting_consumed_notional": usage.consumed_notional + order_notional,
        "status": "eligible_for_future_consumption" if not blockers else "blocked",
        "candidate_eligible": not blockers,
        "activation_implemented": False,
        "consumption_implemented": False,
        "submission_authority": "none",
        "gates": list(gates),
        "blockers": blockers,
    }
    return {**body, "eligibility_sha256": canonical_sha256(body)}
