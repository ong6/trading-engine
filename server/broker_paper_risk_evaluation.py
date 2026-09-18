"""Pure design-only risk evaluation for a verified automatic-paper epoch.

This module is the reviewed handoff between authority evidence and the
existing twenty-gate risk calculation. It changes only the ephemeral
``operational_halt`` input after re-verifying the complete open epoch. The
durable halt and original snapshot remain immutable.

The returned dataclass deliberately omits the ordinary risk-decision payload
accepted by the broker ledger and submission coordinator. It cannot be
persisted or submitted by the current runtime.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Literal

from engine.lib.provenance import canonical_sha256

from . import broker_paper_risk_projection, broker_risk
from .broker_contract import SubmitOrderRequest
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_runtime import RuntimeControlBindings
from .broker_paper_usage import LoadedPaperLeaseUsage
from .broker_risk import PreTradeSnapshot, RiskIdentity, RiskPolicy

EVALUATION_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperRiskEvaluationError(ValueError):
    """Authority evidence cannot produce a design-only risk evaluation."""


@dataclass(frozen=True, slots=True)
class PaperRiskGate:
    """One immutable gate copied from the standard risk evaluator."""

    name: str
    status: Literal["pass", "fail"]
    detail: str

    def payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AuthorityAwareRiskEvaluation:
    """Distinct, non-submittable evidence from the standard twenty gates."""

    lease_id: str
    lease_sha256: str
    account_id: str
    candidate_assessment_sha256: str
    usage_evidence_sha256: str
    transcript_sha256: str
    runtime_evidence_sha256: str
    runtime_epoch_sha256: str
    control_event_count: int
    control_event_sha256: str
    projection_sha256: str
    policy_sha256: str
    identity_sha256: str
    request_sha256: str
    original_snapshot_sha256: str
    effective_snapshot_sha256: str
    ephemeral_risk_decision_sha256: str
    assessed_at: datetime
    risk_evaluated_at: datetime
    risk_expires_at: datetime
    lease_expires_at: datetime
    status: Literal["risk_pass_design_only", "blocked"]
    risk_gate_names: tuple[str, ...]
    risk_gates: tuple[PaperRiskGate, ...]
    risk_failed_gates: tuple[str, ...]
    order_notional: float
    computed_sha256: str
    historical_operational_halt: Literal[True] = True
    effective_operational_halt: Literal[False] = False
    risk_evaluation_implemented: Literal[True] = True
    submission_integration_implemented: Literal[False] = False
    submission_authority: Literal["none"] = "none"
    evaluation_sha256: str = ""

    def payload(self) -> dict:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "lease_id": self.lease_id,
            "lease_sha256": self.lease_sha256,
            "account_id": self.account_id,
            "candidate_assessment_sha256": (
                self.candidate_assessment_sha256
            ),
            "usage_evidence_sha256": self.usage_evidence_sha256,
            "transcript_sha256": self.transcript_sha256,
            "runtime_evidence_sha256": self.runtime_evidence_sha256,
            "runtime_epoch_sha256": self.runtime_epoch_sha256,
            "control_event_count": self.control_event_count,
            "control_event_sha256": self.control_event_sha256,
            "projection_sha256": self.projection_sha256,
            "policy_sha256": self.policy_sha256,
            "identity_sha256": self.identity_sha256,
            "request_sha256": self.request_sha256,
            "original_snapshot_sha256": self.original_snapshot_sha256,
            "effective_snapshot_sha256": self.effective_snapshot_sha256,
            "ephemeral_risk_decision_sha256": (
                self.ephemeral_risk_decision_sha256
            ),
            "assessed_at": _timestamp(self.assessed_at),
            "risk_evaluated_at": _timestamp(self.risk_evaluated_at),
            "risk_expires_at": _timestamp(self.risk_expires_at),
            "lease_expires_at": _timestamp(self.lease_expires_at),
            "status": self.status,
            "risk_gate_names": list(self.risk_gate_names),
            "risk_gates": [gate.payload() for gate in self.risk_gates],
            "risk_failed_gates": list(self.risk_failed_gates),
            "order_notional": self.order_notional,
            "computed_sha256": self.computed_sha256,
            "historical_operational_halt": (
                self.historical_operational_halt
            ),
            "effective_operational_halt": self.effective_operational_halt,
            "risk_evaluation_implemented": self.risk_evaluation_implemented,
            "submission_integration_implemented": (
                self.submission_integration_implemented
            ),
            "submission_authority": self.submission_authority,
        }


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperRiskEvaluationError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "paper risk evaluation time").isoformat().replace(
        "+00:00",
        "Z",
    )


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise PaperRiskEvaluationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PaperRiskEvaluationError(f"{label} is invalid") from exc
    return _utc(parsed, label)


def _snapshot_payload(snapshot: PreTradeSnapshot) -> dict:
    payload = asdict(snapshot)
    payload["as_of"] = snapshot.as_of.isoformat()
    payload["quote_date"] = snapshot.quote_date.isoformat()
    for field in ("observed_at", "quote_at", "reconciliation_at"):
        payload[field] = getattr(snapshot, field).isoformat()
    return payload


def _policy_payload(policy: RiskPolicy) -> dict:
    payload = asdict(policy)
    payload["allowed_symbols"] = list(policy.allowed_symbols)
    return payload


def _identity_payload(identity: RiskIdentity) -> dict:
    return asdict(identity)


def _request_payload(request: SubmitOrderRequest) -> dict:
    payload = asdict(request)
    payload["signal_date"] = request.signal_date.isoformat()
    return payload


def _risk_bindings_match(
    lease: PaperAuthorityLease,
    policy: RiskPolicy,
    identity: RiskIdentity,
    request: SubmitOrderRequest,
) -> bool:
    policy_sha256 = canonical_sha256(_policy_payload(policy))
    return (
        policy_sha256 == lease.risk_policy_sha256
        and policy.policy_id == lease.risk_policy_id
        and policy.account_id == lease.account_id
        and policy.strategy_id == lease.strategy_id
        and policy.release_sha256 == lease.release_manifest_sha256
        and policy.strategy_config_sha256 == lease.strategy_config_sha256
        and policy.execution_profile_id == lease.execution_profile_id
        and policy.execution_profile_sha256
        == lease.execution_profile_sha256
        and set(lease.allowed_symbols).issubset(policy.allowed_symbols)
        and lease.capital_ceiling <= policy.capital_ceiling
        and lease.max_order_notional <= policy.max_order_notional
        and identity.policy_id == policy.policy_id
        and identity.strategy_id == policy.strategy_id
        and identity.release_sha256 == policy.release_sha256
        and identity.strategy_config_sha256
        == policy.strategy_config_sha256
        and identity.execution_profile_id == policy.execution_profile_id
        and identity.execution_profile_sha256
        == policy.execution_profile_sha256
        and request.account_id == lease.account_id
        and request.symbol in lease.allowed_symbols
    )


def verify_evaluation(
    evaluation: AuthorityAwareRiskEvaluation,
) -> AuthorityAwareRiskEvaluation:
    """Verify the closed design-evidence shape without creating a risk decision."""
    if not isinstance(evaluation, AuthorityAwareRiskEvaluation):
        raise TypeError("evaluation must be an AuthorityAwareRiskEvaluation")
    for field in (
        "lease_sha256",
        "candidate_assessment_sha256",
        "usage_evidence_sha256",
        "transcript_sha256",
        "runtime_evidence_sha256",
        "runtime_epoch_sha256",
        "control_event_sha256",
        "projection_sha256",
        "policy_sha256",
        "identity_sha256",
        "request_sha256",
        "original_snapshot_sha256",
        "effective_snapshot_sha256",
        "ephemeral_risk_decision_sha256",
        "computed_sha256",
        "evaluation_sha256",
    ):
        value = getattr(evaluation, field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise PaperRiskEvaluationError(
                "paper risk evaluation identity is invalid"
            )
    if (
        isinstance(evaluation.control_event_count, bool)
        or not isinstance(evaluation.control_event_count, int)
        or evaluation.control_event_count < 1
        or isinstance(evaluation.order_notional, bool)
        or not isinstance(evaluation.order_notional, (int, float))
        or not math.isfinite(evaluation.order_notional)
        or evaluation.order_notional <= 0
    ):
        raise PaperRiskEvaluationError(
            "paper risk evaluation computed values are invalid"
        )
    if (
        evaluation.risk_gate_names != broker_risk.GATE_NAMES
        or len(evaluation.risk_gates) != len(broker_risk.GATE_NAMES)
        or tuple(gate.name for gate in evaluation.risk_gates)
        != broker_risk.GATE_NAMES
        or any(
            not isinstance(gate, PaperRiskGate)
            or gate.status not in {"pass", "fail"}
            or not gate.detail
            or len(gate.detail) > 512
            for gate in evaluation.risk_gates
        )
    ):
        raise PaperRiskEvaluationError(
            "paper risk evaluation gate contract is invalid"
        )
    failed = tuple(
        gate.name for gate in evaluation.risk_gates if gate.status == "fail"
    )
    risk_fresh = (
        evaluation.risk_evaluated_at
        <= evaluation.assessed_at
        < evaluation.risk_expires_at
        and evaluation.assessed_at < evaluation.lease_expires_at
    )
    expected_status = (
        "risk_pass_design_only"
        if not failed and risk_fresh
        else "blocked"
    )
    if (
        evaluation.risk_failed_gates != failed
        or evaluation.status != expected_status
        or evaluation.historical_operational_halt is not True
        or evaluation.effective_operational_halt is not False
        or evaluation.risk_evaluation_implemented is not True
        or evaluation.submission_integration_implemented is not False
        or evaluation.submission_authority != "none"
        or evaluation.evaluation_sha256
        != canonical_sha256(evaluation.payload())
    ):
        raise PaperRiskEvaluationError("paper risk evaluation is invalid")
    return evaluation


def evaluate_open_epoch(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    usage_evidence: LoadedPaperLeaseUsage,
    runtime: RuntimeControlBindings,
    policy: RiskPolicy,
    identity: RiskIdentity,
    request: SubmitOrderRequest,
    snapshot: PreTradeSnapshot,
    *,
    trusted_candidate_assessment_sha256: str,
    now: datetime,
) -> AuthorityAwareRiskEvaluation:
    """Run all standard risk gates under a verified ephemeral epoch override."""
    if not isinstance(policy, RiskPolicy):
        raise TypeError("policy must be a RiskPolicy")
    if not isinstance(identity, RiskIdentity):
        raise TypeError("identity must be a RiskIdentity")
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    if not isinstance(snapshot, PreTradeSnapshot):
        raise TypeError("snapshot must be a PreTradeSnapshot")
    assessed_at = _utc(now, "paper risk assessment time")
    if not _risk_bindings_match(lease, policy, identity, request):
        raise PaperRiskEvaluationError(
            "paper lease, policy, identity, or request binding is invalid"
        )
    try:
        projection = broker_paper_risk_projection.project_open_epoch(
            lease,
            candidate_assessment,
            usage_evidence,
            runtime,
            snapshot,
            trusted_candidate_assessment_sha256=(
                trusted_candidate_assessment_sha256
            ),
            now=assessed_at,
        )
    except (
        broker_paper_risk_projection.PaperRiskProjectionError,
        TypeError,
        ValueError,
    ) as exc:
        raise PaperRiskEvaluationError(
            "paper authority risk projection failed"
        ) from exc

    effective_snapshot = replace(snapshot, operational_halt=False)
    risk_decision = broker_risk.evaluate(
        policy,
        identity,
        request,
        effective_snapshot,
    )
    try:
        verified = broker_risk.verify(risk_decision)
    except broker_risk.RiskContractError as exc:  # pragma: no cover
        raise PaperRiskEvaluationError(
            "ephemeral paper risk decision failed verification"
        ) from exc
    risk_evaluated_at = _parse_timestamp(
        verified["evaluated_at"],
        "paper risk evaluated time",
    )
    risk_expires_at = _parse_timestamp(
        verified["expires_at"],
        "paper risk expiry",
    )
    risk_gates = tuple(
        PaperRiskGate(
            name=gate["name"],
            status=gate["status"],
            detail=gate["detail"],
        )
        for gate in verified["gates"]
    )
    failed = tuple(verified["failed_gates"])
    risk_fresh = (
        risk_evaluated_at <= assessed_at < risk_expires_at
        and assessed_at < lease.expires_at
    )
    values = {
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "candidate_assessment_sha256": (
            projection.candidate_assessment_sha256
        ),
        "usage_evidence_sha256": projection.usage_evidence_sha256,
        "transcript_sha256": projection.transcript_sha256,
        "runtime_evidence_sha256": projection.runtime_evidence_sha256,
        "runtime_epoch_sha256": projection.runtime_epoch_sha256,
        "control_event_count": projection.control_event_count,
        "control_event_sha256": projection.control_event_sha256,
        "projection_sha256": projection.projection_sha256,
        "policy_sha256": verified["policy_sha256"],
        "identity_sha256": verified["identity_sha256"],
        "request_sha256": verified["request_sha256"],
        "original_snapshot_sha256": projection.original_snapshot_sha256,
        "effective_snapshot_sha256": verified["snapshot_sha256"],
        "ephemeral_risk_decision_sha256": verified["decision_sha256"],
        "assessed_at": assessed_at,
        "risk_evaluated_at": risk_evaluated_at,
        "risk_expires_at": risk_expires_at,
        "lease_expires_at": lease.expires_at,
        "status": (
            "risk_pass_design_only"
            if verified["status"] == "pass" and risk_fresh
            else "blocked"
        ),
        "risk_gate_names": broker_risk.GATE_NAMES,
        "risk_gates": risk_gates,
        "risk_failed_gates": failed,
        "order_notional": verified["computed"]["notional"],
        "computed_sha256": canonical_sha256(verified["computed"]),
    }
    pending = AuthorityAwareRiskEvaluation(**values)
    result = AuthorityAwareRiskEvaluation(
        **values,
        evaluation_sha256=canonical_sha256(pending.payload()),
    )
    return verify_evaluation(result)
