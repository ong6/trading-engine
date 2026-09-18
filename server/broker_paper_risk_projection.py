"""Pure authority-aware interpretation of a historically halted risk snapshot.

The projection preserves the original halt and only records that a verified,
open design epoch would satisfy the operational-control gate. It intentionally
returns a distinct type, not ``PreTradeSnapshot``, and cannot be consumed by
the current risk evaluator or broker submission boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

from . import broker_paper_lease, broker_paper_runtime, broker_paper_usage
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_runtime import RuntimeControlBindings
from .broker_risk import PreTradeSnapshot

PROJECTION_SCHEMA_VERSION = 1


class PaperRiskProjectionError(ValueError):
    """Authority evidence cannot produce a safe design-only risk projection."""


@dataclass(frozen=True, slots=True)
class AuthorityAwareRiskProjection:
    """Hash-bound evidence that never clears or replaces the durable halt."""

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
    original_snapshot_sha256: str
    original_operational_control_sha256: str
    historical_operational_halt: bool
    effective_operational_halt: bool
    effective_control_source: str
    observed_at: datetime
    lease_expires_at: datetime
    projection_sha256: str
    risk_evaluation_implemented: bool = False
    submission_authority: str = "none"

    def payload(self) -> dict:
        body = {
            key: value
            for key, value in asdict(self).items()
            if key != "projection_sha256"
        }
        body["schema_version"] = PROJECTION_SCHEMA_VERSION
        body["observed_at"] = self.observed_at.isoformat().replace("+00:00", "Z")
        body["lease_expires_at"] = self.lease_expires_at.isoformat().replace(
            "+00:00",
            "Z",
        )
        return body


def verify_projection(
    projection: AuthorityAwareRiskProjection,
) -> AuthorityAwareRiskProjection:
    """Verify one design-only projection without converting it to risk input."""
    if not isinstance(projection, AuthorityAwareRiskProjection):
        raise TypeError("projection must be an AuthorityAwareRiskProjection")
    if (
        projection.historical_operational_halt is not True
        or projection.effective_operational_halt is not False
        or projection.effective_control_source
        != "verified_open_automatic_paper_epoch_design_only"
        or projection.risk_evaluation_implemented is not False
        or projection.submission_authority != "none"
        or projection.projection_sha256 != canonical_sha256(projection.payload())
    ):
        raise PaperRiskProjectionError("paper risk projection is invalid")
    return projection


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperRiskProjectionError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def project_open_epoch(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    usage_evidence: broker_paper_usage.LoadedPaperLeaseUsage,
    runtime: RuntimeControlBindings,
    snapshot: PreTradeSnapshot,
    *,
    trusted_candidate_assessment_sha256: str,
    now: datetime,
) -> AuthorityAwareRiskProjection:
    """Prove an effective design-only control state without mutating the halt."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(runtime, RuntimeControlBindings):
        raise TypeError("runtime must be RuntimeControlBindings")
    if not isinstance(snapshot, PreTradeSnapshot):
        raise TypeError("snapshot must be a PreTradeSnapshot")
    observed_at = _utc(now, "paper risk projection time")
    try:
        assessment = broker_paper_lease.verify_candidate_assessment(
            candidate_assessment,
            lease,
            trusted_assessment_sha256=trusted_candidate_assessment_sha256,
        )
        usage = broker_paper_usage.verify_loaded_usage(usage_evidence, lease)
        runtime = broker_paper_runtime.verify_runtime_control(
            runtime,
            account_id=lease.account_id,
        )
    except (
        broker_paper_lease.PaperLeaseError,
        broker_paper_runtime.PaperRuntimeError,
        broker_paper_usage.PaperUsageError,
    ) as exc:
        raise PaperRiskProjectionError(
            "paper authority evidence verification failed"
        ) from exc
    if (
        runtime.runtime_epoch_sha256 != usage.current_runtime_epoch_sha256
        or runtime.runtime_epoch_sha256 != usage.activation_runtime_epoch_sha256
        or runtime.control != usage.current_control
        or assessment["assessment_sha256"]
        != usage.candidate_assessment_sha256
        or assessment["startup_assessment_sha256"]
        != usage.startup_assessment_sha256
        or snapshot.operational_halt is not True
        or snapshot.operational_control_sha256 != runtime.control_status_sha256
        or not usage.observed_at <= observed_at < lease.expires_at
    ):
        raise PaperRiskProjectionError(
            "paper authority, runtime, control, or snapshot binding is invalid"
        )
    snapshot_payload = asdict(snapshot)
    for field in ("as_of", "quote_date"):
        snapshot_payload[field] = getattr(snapshot, field).isoformat()
    for field in ("observed_at", "quote_at", "reconciliation_at"):
        snapshot_payload[field] = getattr(snapshot, field).isoformat()
    body = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "candidate_assessment_sha256": assessment["assessment_sha256"],
        "usage_evidence_sha256": usage.evidence_sha256,
        "transcript_sha256": usage.transcript_sha256,
        "runtime_evidence_sha256": runtime.evidence_sha256,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "original_snapshot_sha256": canonical_sha256(snapshot_payload),
        "original_operational_control_sha256": snapshot.operational_control_sha256,
        "historical_operational_halt": True,
        "effective_operational_halt": False,
        "effective_control_source": "verified_open_automatic_paper_epoch_design_only",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "lease_expires_at": lease.expires_at.isoformat().replace("+00:00", "Z"),
        "risk_evaluation_implemented": False,
        "submission_authority": "none",
    }
    return AuthorityAwareRiskProjection(
        lease_id=lease.lease_id,
        lease_sha256=lease.sha256(),
        account_id=lease.account_id,
        candidate_assessment_sha256=assessment["assessment_sha256"],
        usage_evidence_sha256=usage.evidence_sha256,
        transcript_sha256=usage.transcript_sha256,
        runtime_evidence_sha256=runtime.evidence_sha256,
        runtime_epoch_sha256=runtime.runtime_epoch_sha256,
        control_event_count=runtime.control.event_count,
        control_event_sha256=runtime.control.latest_event_sha256,
        original_snapshot_sha256=canonical_sha256(snapshot_payload),
        original_operational_control_sha256=snapshot.operational_control_sha256,
        historical_operational_halt=True,
        effective_operational_halt=False,
        effective_control_source="verified_open_automatic_paper_epoch_design_only",
        observed_at=observed_at,
        lease_expires_at=lease.expires_at,
        projection_sha256=canonical_sha256(body),
    )
