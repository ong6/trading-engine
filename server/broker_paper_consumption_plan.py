"""Pure plan for one future atomic automatic-paper pre-call commit.

The plan joins already verified authority, retained intent, usage, risk, and
broker-request evidence. It computes the exact commitments a future writer
would have to persist atomically, but it has no database, adapter, lock,
transaction, or submission capability.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

from . import (
    broker_paper_lease,
    broker_paper_risk_evaluation,
    broker_paper_usage,
)
from .broker_contract import (
    SubmitOrderRequest,
    require_identifier,
)
from .broker_paper_intent import (
    HybridPaperIntentBindings,
    PaperIntentBindings,
)
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_risk_evaluation import AuthorityAwareRiskEvaluation
from .broker_paper_usage import LoadedPaperLeaseUsage

PLAN_SCHEMA_VERSION = 1
ELIGIBILITY_SCHEMA_VERSION = 1
BROKER_INTENT_SCHEMA_VERSION = 1
SUBMISSION_STARTED_COMMITMENT_SCHEMA_VERSION = 1
AUTHORITY_EVENT_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperConsumptionPlanError(ValueError):
    """Evidence cannot form one exact, non-executable atomic commit plan."""


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperConsumptionPlanError(f"{label} must be a lowercase SHA-256")
    return value


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise PaperConsumptionPlanError(str(exc)) from exc


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperConsumptionPlanError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "paper consumption plan time").isoformat().replace(
        "+00:00",
        "Z",
    )


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperConsumptionPlanError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperConsumptionPlanError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise PaperConsumptionPlanError(f"{label} is not canonical")
    return _utc(parsed, label)


def _positive(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PaperConsumptionPlanError(
            f"{label} must be a positive finite number"
        )
    return float(value)


def _nonnegative(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise PaperConsumptionPlanError(
            f"{label} must be a nonnegative finite number"
        )
    return float(value)


def _request_payload(request: SubmitOrderRequest) -> dict:
    payload = asdict(request)
    payload["signal_date"] = request.signal_date.isoformat()
    return payload


def _broker_intent_payload(request: SubmitOrderRequest) -> dict:
    return {
        "schema_version": BROKER_INTENT_SCHEMA_VERSION,
        **_request_payload(request),
    }


def _common_intent_matches(
    lease: PaperAuthorityLease,
    request: SubmitOrderRequest,
    request_sha256: str,
    intent: PaperIntentBindings | HybridPaperIntentBindings,
) -> bool:
    return (
        intent.mode == lease.mode
        and intent.policy_id == lease.policy_id
        and intent.policy_registration_sha256
        == lease.policy_registration_sha256
        and intent.data_snapshot_sha256 == lease.data_snapshot_sha256
        and intent.decision_window_id == lease.decision_window_id
        and intent.request_sha256 == request_sha256
        and intent.symbol == request.symbol
        and intent.side == request.side
        and intent.signal_date == request.signal_date
    )


def _verified_sources(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    usage_evidence: LoadedPaperLeaseUsage,
    risk_evaluation: AuthorityAwareRiskEvaluation,
    trusted_candidate_assessment_sha256: str,
) -> tuple[dict, LoadedPaperLeaseUsage, AuthorityAwareRiskEvaluation]:
    try:
        candidate = broker_paper_lease.verify_candidate_assessment(
            candidate_assessment,
            lease,
            trusted_assessment_sha256=trusted_candidate_assessment_sha256,
        )
        usage = broker_paper_usage.verify_loaded_usage(usage_evidence, lease)
        evaluation = broker_paper_risk_evaluation.verify_evaluation(risk_evaluation)
    except (TypeError, ValueError) as exc:
        raise PaperConsumptionPlanError(
            "paper consumption source evidence verification failed"
        ) from exc
    return candidate, usage, evaluation


def _mode_intent_matches(
    lease: PaperAuthorityLease,
    request: SubmitOrderRequest,
    intent_bindings: PaperIntentBindings | HybridPaperIntentBindings,
    evaluation: AuthorityAwareRiskEvaluation,
    planned_at: datetime,
) -> bool:
    if isinstance(intent_bindings, PaperIntentBindings):
        return (
            evaluation.order_notional <= intent_bindings.max_notional
            and planned_at < intent_bindings.proposal_expires_at
        )
    return (
        intent_bindings.terminal_status in {"hybrid_allow", "hybrid_fallback_allow"}
        and intent_bindings.effective_order_included is True
        and request.quantity == intent_bindings.quantity
        and lease.not_before <= intent_bindings.evidence_observed_at <= planned_at
    )


def _eligibility_body(
    *,
    lease: PaperAuthorityLease,
    candidate_assessment_sha256: str,
    intent_bindings_sha256: str,
    usage: LoadedPaperLeaseUsage,
    evaluation: AuthorityAwareRiskEvaluation,
    request_sha256: str,
    consumption_key: str,
    idempotency_key: str,
    planned_at: datetime,
) -> dict:
    return {
        "schema_version": ELIGIBILITY_SCHEMA_VERSION,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "candidate_assessment_sha256": candidate_assessment_sha256,
        "intent_bindings_sha256": intent_bindings_sha256,
        "usage_evidence_sha256": usage.evidence_sha256,
        "transcript_sha256": usage.transcript_sha256,
        "risk_evaluation_sha256": evaluation.evaluation_sha256,
        "request_sha256": request_sha256,
        "consumption_key": consumption_key,
        "idempotency_key": idempotency_key,
        "planned_at": _timestamp(planned_at),
        "risk_expires_at": _timestamp(evaluation.risk_expires_at),
        "lease_expires_at": _timestamp(lease.expires_at),
        "order_notional": evaluation.order_notional,
        "prior_consumed_order_count": usage.usage.consumed_order_count,
        "prior_consumed_notional": usage.usage.consumed_notional,
        "resulting_consumed_order_count": (
            usage.usage.consumed_order_count + 1
        ),
        "resulting_consumed_notional": (
            usage.usage.consumed_notional + evaluation.order_notional
        ),
        "status": "eligible_for_future_atomic_commit_design_only",
        "persistence_implemented": False,
        "submission_integration_implemented": False,
        "submission_authority": "none",
    }


def _expected_commitments(
    *,
    lease: PaperAuthorityLease,
    request: SubmitOrderRequest,
    consumption_key: str,
    planned_at: datetime,
    usage: LoadedPaperLeaseUsage,
    evaluation: AuthorityAwareRiskEvaluation,
    eligibility_sha256: str,
) -> tuple[dict, dict, dict]:
    intent = _broker_intent_payload(request)
    intent_sha256 = canonical_sha256(intent)
    started = {
        "schema_version": SUBMISSION_STARTED_COMMITMENT_SCHEMA_VERSION,
        "event_type": "submission_started",
        "event_sequence": 1,
        "idempotency_key": request.idempotency_key,
        "account_id": request.account_id,
        "intent_sha256": intent_sha256,
        "occurred_at": _timestamp(planned_at),
        "submission_state": "uncertain",
    }
    started_sha256 = canonical_sha256(started)
    consumption = {
        "schema_version": AUTHORITY_EVENT_SCHEMA_VERSION,
        "event_type": "consumption_committed",
        "event_sequence": usage.event_count + 1,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "occurred_at": _timestamp(planned_at),
        "prior_event_sha256": usage.latest_event_sha256,
        "submission_authority": "none",
        "consumption_key": consumption_key,
        "idempotency_key": request.idempotency_key,
        "eligibility_sha256": eligibility_sha256,
        "request_sha256": evaluation.request_sha256,
        "risk_evaluation_sha256": evaluation.evaluation_sha256,
        "broker_submission_started_sha256": started_sha256,
        "submission_state": "uncertain",
        "order_notional": evaluation.order_notional,
        "resulting_consumed_order_count": (
            usage.usage.consumed_order_count + 1
        ),
        "resulting_consumed_notional": (
            usage.usage.consumed_notional + evaluation.order_notional
        ),
    }
    return intent, started, consumption


def verify_plan(plan: object) -> dict:
    """Re-verify the canonical bundle without making it executable."""
    if not isinstance(plan, dict):
        raise PaperConsumptionPlanError("paper consumption plan is invalid")
    expected_fields = {
        "schema_version",
        "status",
        "lease_id",
        "lease_sha256",
        "account_id",
        "mode",
        "candidate_assessment_sha256",
        "intent_bindings_sha256",
        "usage_evidence_sha256",
        "transcript_sha256",
        "risk_evaluation_sha256",
        "request_sha256",
        "consumption_key",
        "idempotency_key",
        "planned_at",
        "risk_expires_at",
        "lease_expires_at",
        "order_notional",
        "prior_consumed_order_count",
        "prior_consumed_notional",
        "resulting_consumed_order_count",
        "resulting_consumed_notional",
        "expected_event_sequence",
        "expected_prior_event_sha256",
        "eligibility",
        "eligibility_sha256",
        "expected_broker_intent",
        "expected_broker_intent_sha256",
        "expected_submission_started",
        "expected_submission_started_sha256",
        "expected_consumption_event",
        "expected_consumption_event_sha256",
        "persistence_implemented",
        "transaction_integration_implemented",
        "submission_integration_implemented",
        "submission_authority",
        "atomic_bundle_sha256",
    }
    if set(plan) != expected_fields:
        raise PaperConsumptionPlanError(
            "paper consumption plan shape is invalid"
        )
    for field in (
        "lease_sha256",
        "candidate_assessment_sha256",
        "intent_bindings_sha256",
        "usage_evidence_sha256",
        "transcript_sha256",
        "risk_evaluation_sha256",
        "request_sha256",
        "expected_prior_event_sha256",
        "eligibility_sha256",
        "expected_broker_intent_sha256",
        "expected_submission_started_sha256",
        "expected_consumption_event_sha256",
        "atomic_bundle_sha256",
    ):
        _sha256(plan[field], field.replace("_", " "))
    _identifier(plan["lease_id"], "paper consumption lease identifier")
    _identifier(plan["account_id"], "paper consumption account identifier")
    _identifier(plan["consumption_key"], "paper consumption identifier")
    _identifier(
        plan["idempotency_key"],
        "paper consumption idempotency key",
    )
    planned_at = _parse_timestamp(
        plan["planned_at"],
        "paper consumption plan time",
    )
    risk_expires_at = _parse_timestamp(
        plan["risk_expires_at"],
        "paper consumption risk expiry",
    )
    lease_expires_at = _parse_timestamp(
        plan["lease_expires_at"],
        "paper consumption lease expiry",
    )
    order_notional = _positive(
        plan["order_notional"],
        "paper consumption order notional",
    )
    prior_notional = _nonnegative(
        plan["prior_consumed_notional"],
        "prior paper consumption notional",
    )
    resulting_notional = _nonnegative(
        plan["resulting_consumed_notional"],
        "resulting paper consumption notional",
    )
    if (
        plan["schema_version"] != PLAN_SCHEMA_VERSION
        or plan["status"] != "ready_for_future_atomic_commit_design_only"
        or plan["mode"] not in {"agent_only", "hybrid"}
        or planned_at >= risk_expires_at
        or planned_at >= lease_expires_at
        or isinstance(plan["prior_consumed_order_count"], bool)
        or not isinstance(plan["prior_consumed_order_count"], int)
        or plan["prior_consumed_order_count"] < 0
        or isinstance(plan["resulting_consumed_order_count"], bool)
        or not isinstance(plan["resulting_consumed_order_count"], int)
        or plan["resulting_consumed_order_count"]
        != plan["prior_consumed_order_count"] + 1
        or not math.isclose(
            resulting_notional,
            prior_notional + order_notional,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or isinstance(plan["expected_event_sequence"], bool)
        or not isinstance(plan["expected_event_sequence"], int)
        or plan["expected_event_sequence"]
        != plan["prior_consumed_order_count"] + 2
        or plan["persistence_implemented"] is not False
        or plan["transaction_integration_implemented"] is not False
        or plan["submission_integration_implemented"] is not False
        or plan["submission_authority"] != "none"
    ):
        raise PaperConsumptionPlanError("paper consumption plan is invalid")

    eligibility = plan["eligibility"]
    intent = plan["expected_broker_intent"]
    started = plan["expected_submission_started"]
    consumption = plan["expected_consumption_event"]
    if not all(
        isinstance(value, dict)
        for value in (eligibility, intent, started, consumption)
    ):
        raise PaperConsumptionPlanError(
            "paper consumption commitments are invalid"
        )
    expected_eligibility = {
        "schema_version": ELIGIBILITY_SCHEMA_VERSION,
        "lease_id": plan["lease_id"],
        "lease_sha256": plan["lease_sha256"],
        "account_id": plan["account_id"],
        "mode": plan["mode"],
        "candidate_assessment_sha256": (
            plan["candidate_assessment_sha256"]
        ),
        "intent_bindings_sha256": plan["intent_bindings_sha256"],
        "usage_evidence_sha256": plan["usage_evidence_sha256"],
        "transcript_sha256": plan["transcript_sha256"],
        "risk_evaluation_sha256": plan["risk_evaluation_sha256"],
        "request_sha256": plan["request_sha256"],
        "consumption_key": plan["consumption_key"],
        "idempotency_key": plan["idempotency_key"],
        "planned_at": plan["planned_at"],
        "risk_expires_at": plan["risk_expires_at"],
        "lease_expires_at": plan["lease_expires_at"],
        "order_notional": plan["order_notional"],
        "prior_consumed_order_count": plan["prior_consumed_order_count"],
        "prior_consumed_notional": plan["prior_consumed_notional"],
        "resulting_consumed_order_count": (
            plan["resulting_consumed_order_count"]
        ),
        "resulting_consumed_notional": plan["resulting_consumed_notional"],
        "status": "eligible_for_future_atomic_commit_design_only",
        "persistence_implemented": False,
        "submission_integration_implemented": False,
        "submission_authority": "none",
    }
    expected_intent_fields = {
        "schema_version",
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
    if (
        set(intent) != expected_intent_fields
        or intent.get("schema_version") != BROKER_INTENT_SCHEMA_VERSION
        or intent.get("idempotency_key") != plan["idempotency_key"]
        or intent.get("account_id") != plan["account_id"]
        or canonical_sha256(
            {
                key: value
                for key, value in intent.items()
                if key != "schema_version"
            }
        )
        != plan["request_sha256"]
    ):
        raise PaperConsumptionPlanError(
            "paper consumption broker intent is inconsistent"
        )
    expected_started = {
        "schema_version": SUBMISSION_STARTED_COMMITMENT_SCHEMA_VERSION,
        "event_type": "submission_started",
        "event_sequence": 1,
        "idempotency_key": plan["idempotency_key"],
        "account_id": plan["account_id"],
        "intent_sha256": plan["expected_broker_intent_sha256"],
        "occurred_at": plan["planned_at"],
        "submission_state": "uncertain",
    }
    expected_consumption = {
        "schema_version": AUTHORITY_EVENT_SCHEMA_VERSION,
        "event_type": "consumption_committed",
        "event_sequence": plan["expected_event_sequence"],
        "lease_id": plan["lease_id"],
        "lease_sha256": plan["lease_sha256"],
        "account_id": plan["account_id"],
        "mode": plan["mode"],
        "occurred_at": plan["planned_at"],
        "prior_event_sha256": plan["expected_prior_event_sha256"],
        "submission_authority": "none",
        "consumption_key": plan["consumption_key"],
        "idempotency_key": plan["idempotency_key"],
        "eligibility_sha256": plan["eligibility_sha256"],
        "request_sha256": plan["request_sha256"],
        "risk_evaluation_sha256": plan["risk_evaluation_sha256"],
        "broker_submission_started_sha256": (
            plan["expected_submission_started_sha256"]
        ),
        "submission_state": "uncertain",
        "order_notional": plan["order_notional"],
        "resulting_consumed_order_count": (
            plan["resulting_consumed_order_count"]
        ),
        "resulting_consumed_notional": plan["resulting_consumed_notional"],
    }
    if (
        eligibility != expected_eligibility
        or started != expected_started
        or consumption != expected_consumption
        or canonical_sha256(eligibility) != plan["eligibility_sha256"]
        or canonical_sha256(intent) != plan["expected_broker_intent_sha256"]
        or canonical_sha256(started)
        != plan["expected_submission_started_sha256"]
        or canonical_sha256(consumption)
        != plan["expected_consumption_event_sha256"]
    ):
        raise PaperConsumptionPlanError(
            "paper consumption commitments are inconsistent"
        )
    body = {
        key: value
        for key, value in plan.items()
        if key != "atomic_bundle_sha256"
    }
    if canonical_sha256(body) != plan["atomic_bundle_sha256"]:
        raise PaperConsumptionPlanError(
            "paper consumption bundle hash does not match"
        )
    return plan


def build_plan(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    intent_bindings: PaperIntentBindings | HybridPaperIntentBindings,
    usage_evidence: LoadedPaperLeaseUsage,
    risk_evaluation: AuthorityAwareRiskEvaluation,
    request: SubmitOrderRequest,
    *,
    consumption_key: str,
    trusted_candidate_assessment_sha256: str,
    trusted_intent_bindings_sha256: str,
    now: datetime,
) -> dict:
    """Build exact future commit bytes after re-verifying every pure input."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(
        intent_bindings,
        (PaperIntentBindings, HybridPaperIntentBindings),
    ):
        raise TypeError("intent_bindings must be a supported paper intent binding")
    if not isinstance(request, SubmitOrderRequest):
        raise TypeError("request must be a SubmitOrderRequest")
    consumption_key = _identifier(
        consumption_key,
        "paper consumption identifier",
    )
    trusted_candidate_assessment_sha256 = _sha256(
        trusted_candidate_assessment_sha256,
        "trusted paper candidate assessment identity",
    )
    trusted_intent_bindings_sha256 = _sha256(
        trusted_intent_bindings_sha256,
        "trusted paper intent binding identity",
    )
    planned_at = _utc(now, "paper consumption plan time")
    candidate, usage, evaluation = _verified_sources(
        lease,
        candidate_assessment,
        usage_evidence,
        risk_evaluation,
        trusted_candidate_assessment_sha256,
    )

    request_payload = _request_payload(request)
    request_sha256 = canonical_sha256(request_payload)
    intent_sha256 = intent_bindings.sha256()
    try:
        candidate_observed_at = _parse_timestamp(
            candidate["observed_at"],
            "paper candidate assessment time",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperConsumptionPlanError(
            "paper candidate assessment time is invalid"
        ) from exc
    evidence_matches = (
        candidate["assessment_sha256"]
        == trusted_candidate_assessment_sha256
        == usage.candidate_assessment_sha256
        == evaluation.candidate_assessment_sha256
        and intent_sha256 == trusted_intent_bindings_sha256
        and evaluation.lease_id == lease.lease_id
        and evaluation.lease_sha256 == lease.sha256()
        and evaluation.account_id == lease.account_id
        and evaluation.usage_evidence_sha256 == usage.evidence_sha256
        and evaluation.transcript_sha256 == usage.transcript_sha256
        and evaluation.runtime_epoch_sha256
        == usage.current_runtime_epoch_sha256
        == usage.activation_runtime_epoch_sha256
        and evaluation.control_event_count
        == usage.current_control.event_count
        and evaluation.control_event_sha256
        == usage.current_control.latest_event_sha256
        and evaluation.request_sha256 == request_sha256
    )
    current_and_passing = (
        evaluation.status == "risk_pass_design_only"
        and not evaluation.risk_failed_gates
        and evaluation.risk_evaluated_at
        <= evaluation.assessed_at
        <= planned_at
        < evaluation.risk_expires_at
        and candidate_observed_at <= planned_at < lease.expires_at
        and usage.observed_at <= evaluation.assessed_at
        and usage.lease_expires_at == lease.expires_at
    )
    intent_matches = _common_intent_matches(
        lease,
        request,
        request_sha256,
        intent_bindings,
    )
    intent_matches = intent_matches and _mode_intent_matches(
        lease, request, intent_bindings, evaluation, planned_at
    )
    unique = (
        consumption_key not in usage.consumed_consumption_keys
        and request.idempotency_key
        not in usage.consumed_idempotency_keys
        and request_sha256 not in usage.consumed_request_sha256s
    )
    within_budget = (
        evaluation.order_notional <= lease.max_order_notional
        and usage.usage.consumed_order_count + 1 <= lease.max_orders
        and usage.usage.consumed_notional + evaluation.order_notional
        <= lease.capital_ceiling
    )
    if not evidence_matches:
        raise PaperConsumptionPlanError(
            "paper consumption evidence bindings do not match"
        )
    if not current_and_passing:
        raise PaperConsumptionPlanError(
            "paper consumption risk or lease window is not open"
        )
    if not intent_matches:
        raise PaperConsumptionPlanError(
            "paper consumption intent does not match"
        )
    if not unique:
        raise PaperConsumptionPlanError(
            "paper consumption identity was already used"
        )
    if not within_budget:
        raise PaperConsumptionPlanError(
            "paper consumption exceeds lease capacity"
        )

    eligibility = _eligibility_body(
        lease=lease,
        candidate_assessment_sha256=candidate["assessment_sha256"],
        intent_bindings_sha256=intent_sha256,
        usage=usage,
        evaluation=evaluation,
        request_sha256=request_sha256,
        consumption_key=consumption_key,
        idempotency_key=request.idempotency_key,
        planned_at=planned_at,
    )
    eligibility_sha256 = canonical_sha256(eligibility)
    intent, started, consumption = _expected_commitments(
        lease=lease,
        request=request,
        consumption_key=consumption_key,
        planned_at=planned_at,
        usage=usage,
        evaluation=evaluation,
        eligibility_sha256=eligibility_sha256,
    )
    body = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "ready_for_future_atomic_commit_design_only",
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "intent_bindings_sha256": intent_sha256,
        "usage_evidence_sha256": usage.evidence_sha256,
        "transcript_sha256": usage.transcript_sha256,
        "risk_evaluation_sha256": evaluation.evaluation_sha256,
        "request_sha256": request_sha256,
        "consumption_key": consumption_key,
        "idempotency_key": request.idempotency_key,
        "planned_at": _timestamp(planned_at),
        "risk_expires_at": _timestamp(evaluation.risk_expires_at),
        "lease_expires_at": _timestamp(lease.expires_at),
        "order_notional": evaluation.order_notional,
        "prior_consumed_order_count": usage.usage.consumed_order_count,
        "prior_consumed_notional": usage.usage.consumed_notional,
        "resulting_consumed_order_count": (
            usage.usage.consumed_order_count + 1
        ),
        "resulting_consumed_notional": (
            usage.usage.consumed_notional + evaluation.order_notional
        ),
        "expected_event_sequence": usage.event_count + 1,
        "expected_prior_event_sha256": usage.latest_event_sha256,
        "eligibility": eligibility,
        "eligibility_sha256": eligibility_sha256,
        "expected_broker_intent": intent,
        "expected_broker_intent_sha256": canonical_sha256(intent),
        "expected_submission_started": started,
        "expected_submission_started_sha256": canonical_sha256(started),
        "expected_consumption_event": consumption,
        "expected_consumption_event_sha256": canonical_sha256(consumption),
        "persistence_implemented": False,
        "transaction_integration_implemented": False,
        "submission_integration_implemented": False,
        "submission_authority": "none",
    }
    return verify_plan(
        {
            **body,
            "atomic_bundle_sha256": canonical_sha256(body),
        }
    )
