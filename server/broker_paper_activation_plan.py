"""Pure plan for one future automatic-paper activation commit.

The plan re-verifies an admissible lease assessment, complete startup
readiness, retained-authority startup scan, and current process/control
binding. It emits the exact activation event a future writer would have to
persist, but has no database, transaction, adapter, route, or authority.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

from . import (
    broker_paper_lease,
    broker_paper_runtime,
    broker_paper_startup_scan,
    broker_paper_startup_store,
    broker_startup_readiness,
)
from .broker_contract import require_identifier
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_runtime import RuntimeControlBindings

PLAN_SCHEMA_VERSION = 1
ACTIVATION_EVENT_SCHEMA_VERSION = 2
MAX_ACTIVATION_EVIDENCE_AGE_SECONDS = 30
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLOSED_STATES = frozenset(
    {
        "revoked",
        "invalidated_by_restart",
        "invalidated_by_halt",
        "expired",
        "exhausted",
    }
)


class PaperActivationPlanError(ValueError):
    """Evidence cannot form one exact, non-executable activation plan."""


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperActivationPlanError(f"{label} must be a lowercase SHA-256")
    return value


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise PaperActivationPlanError(str(exc)) from exc


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperActivationPlanError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "paper activation plan time").isoformat().replace(
        "+00:00",
        "Z",
    )


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperActivationPlanError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperActivationPlanError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise PaperActivationPlanError(f"{label} is not canonical")
    return _utc(parsed, label)


def _verify_startup_scan(
    scan: object,
    runtime: RuntimeControlBindings,
    *,
    account_id: str,
    trusted_scan_sha256: str,
    trusted_retention_evidence_sha256: str,
) -> dict:
    expected_fields = {
        "schema_version",
        "account_id",
        "status",
        "safe_closed",
        "observed_at",
        "runtime_epoch_sha256",
        "runtime_control_sha256",
        "retained_epoch_count",
        "closed_epoch_count",
        "open_lease_ids",
        "records",
        "startup_authority",
        "submission_authority",
        "scan_sha256",
        "retention_schema_version",
        "trusted_retained_row_count",
        "trusted_latest_retained_row_sha256",
        "retention_evidence_sha256",
    }
    if not isinstance(scan, dict) or set(scan) != expected_fields:
        raise PaperActivationPlanError(
            "paper authority startup scan shape is invalid"
        )
    trusted_scan_sha256 = _sha256(
        trusted_scan_sha256,
        "trusted paper authority startup scan identity",
    )
    _sha256(scan["scan_sha256"], "paper authority startup scan identity")
    _sha256(
        scan["retention_evidence_sha256"],
        "paper authority retention evidence identity",
    )
    trusted_retention_evidence_sha256 = _sha256(
        trusted_retention_evidence_sha256,
        "trusted paper authority retention evidence identity",
    )
    trusted_row_count = scan["trusted_retained_row_count"]
    trusted_head = scan["trusted_latest_retained_row_sha256"]
    if (
        isinstance(trusted_row_count, bool)
        or not isinstance(trusted_row_count, int)
        or trusted_row_count < 0
        or (
            trusted_row_count == 0
            and trusted_head is not None
        )
        or (
            trusted_row_count > 0
            and _sha256(
                trusted_head,
                "trusted retained authority head",
            )
            is None
        )
    ):
        raise PaperActivationPlanError(
            "paper authority retained global head is invalid"
        )
    observed_at = _parse_timestamp(
        scan["observed_at"],
        "paper authority startup scan time",
    )
    records = scan["records"]
    if not isinstance(records, list):
        raise PaperActivationPlanError(
            "paper authority startup scan records are invalid"
        )
    lease_ids = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "lease_id",
            "lease_sha256",
            "state",
            "event_count",
            "latest_event_sha256",
            "transcript_sha256",
            "activation_runtime_epoch_sha256",
            "current_runtime_epoch_sha256",
            "record_sha256",
        }:
            raise PaperActivationPlanError(
                "paper authority startup scan record is invalid"
            )
        _identifier(record["lease_id"], "retained paper lease identifier")
        for field in (
            "lease_sha256",
            "latest_event_sha256",
            "transcript_sha256",
            "activation_runtime_epoch_sha256",
            "current_runtime_epoch_sha256",
            "record_sha256",
        ):
            _sha256(record[field], field.replace("_", " "))
        record_body = {
            key: value
            for key, value in record.items()
            if key != "record_sha256"
        }
        if (
            record["state"] not in _CLOSED_STATES
            or isinstance(record["event_count"], bool)
            or not isinstance(record["event_count"], int)
            or record["event_count"] < 1
            or record["current_runtime_epoch_sha256"]
            != runtime.runtime_epoch_sha256
            or canonical_sha256(record_body) != record["record_sha256"]
        ):
            raise PaperActivationPlanError(
                "paper authority startup scan record is invalid"
            )
        lease_ids.append(record["lease_id"])
    scan_body = {
        key: value
        for key, value in scan.items()
        if key
        not in {
            "scan_sha256",
            "retention_schema_version",
            "trusted_retained_row_count",
            "trusted_latest_retained_row_sha256",
            "retention_evidence_sha256",
        }
    }
    retention_body = {
        "schema_version": scan["retention_schema_version"],
        "account_id": account_id,
        "trusted_retained_row_count": trusted_row_count,
        "trusted_latest_retained_row_sha256": trusted_head,
        "scan_sha256": scan["scan_sha256"],
        "runtime_evidence_sha256": runtime.evidence_sha256,
        "execution_authority": "none",
    }
    if (
        scan["schema_version"]
        != broker_paper_startup_scan.STARTUP_SCAN_SCHEMA_VERSION
        or scan["retention_schema_version"]
        != broker_paper_startup_store.RETENTION_SCHEMA_VERSION
        or scan["account_id"] != account_id
        or scan["status"] != "safe_closed"
        or scan["safe_closed"] is not True
        or scan["runtime_epoch_sha256"] != runtime.runtime_epoch_sha256
        or scan["runtime_control_sha256"] != runtime.evidence_sha256
        or isinstance(scan["retained_epoch_count"], bool)
        or not isinstance(scan["retained_epoch_count"], int)
        or scan["retained_epoch_count"] != len(records)
        or isinstance(scan["closed_epoch_count"], bool)
        or not isinstance(scan["closed_epoch_count"], int)
        or scan["closed_epoch_count"] != len(records)
        or scan["open_lease_ids"] != []
        or lease_ids != sorted(set(lease_ids))
        or trusted_row_count < scan["retained_epoch_count"]
        or scan["startup_authority"] != "none"
        or scan["submission_authority"] != "none"
        or canonical_sha256(scan_body) != scan["scan_sha256"]
        or scan["scan_sha256"] != trusted_scan_sha256
        or canonical_sha256(retention_body)
        != scan["retention_evidence_sha256"]
        or scan["retention_evidence_sha256"]
        != trusted_retention_evidence_sha256
    ):
        raise PaperActivationPlanError(
            "paper authority startup scan is not safe and complete"
        )
    return {**scan, "_observed_at": observed_at}


def verify_plan(plan: object) -> dict:
    """Re-verify one canonical activation plan without making it executable."""
    expected_fields = {
        "schema_version",
        "status",
        "lease_id",
        "lease_sha256",
        "account_id",
        "mode",
        "candidate_assessment_sha256",
        "startup_assessment_sha256",
        "startup_scan_sha256",
        "retention_evidence_sha256",
        "expected_prior_global_row_count",
        "expected_prior_global_row_sha256",
        "runtime_evidence_sha256",
        "runtime_epoch_sha256",
        "control_event_count",
        "control_event_sha256",
        "planned_at",
        "lease_expires_at",
        "expected_activation_event",
        "expected_activation_event_sha256",
        "persistence_implemented",
        "transaction_integration_implemented",
        "submission_integration_implemented",
        "submission_authority",
        "activation_bundle_sha256",
    }
    if not isinstance(plan, dict) or set(plan) != expected_fields:
        raise PaperActivationPlanError("paper activation plan shape is invalid")
    for field in (
        "lease_sha256",
        "candidate_assessment_sha256",
        "startup_assessment_sha256",
        "startup_scan_sha256",
        "retention_evidence_sha256",
        "runtime_evidence_sha256",
        "runtime_epoch_sha256",
        "control_event_sha256",
        "expected_activation_event_sha256",
        "activation_bundle_sha256",
    ):
        _sha256(plan[field], field.replace("_", " "))
    _identifier(plan["lease_id"], "paper activation lease identifier")
    _identifier(plan["account_id"], "paper activation account identifier")
    planned_at = _parse_timestamp(plan["planned_at"], "paper activation plan time")
    lease_expires_at = _parse_timestamp(
        plan["lease_expires_at"],
        "paper activation lease expiry",
    )
    event = plan["expected_activation_event"]
    expected_event = {
        "schema_version": ACTIVATION_EVENT_SCHEMA_VERSION,
        "event_type": "activation_recorded",
        "event_sequence": 1,
        "lease_id": plan["lease_id"],
        "lease_sha256": plan["lease_sha256"],
        "account_id": plan["account_id"],
        "mode": plan["mode"],
        "occurred_at": plan["planned_at"],
        "prior_event_sha256": None,
        "submission_authority": "none",
        "candidate_assessment_sha256": (
            plan["candidate_assessment_sha256"]
        ),
        "startup_assessment_sha256": plan["startup_assessment_sha256"],
        "control_event_count": plan["control_event_count"],
        "control_event_sha256": plan["control_event_sha256"],
        "runtime_epoch_sha256": plan["runtime_epoch_sha256"],
    }
    body = {
        key: value
        for key, value in plan.items()
        if key != "activation_bundle_sha256"
    }
    if (
        plan["schema_version"] != PLAN_SCHEMA_VERSION
        or plan["status"] != "ready_for_future_activation_commit_design_only"
        or plan["mode"] not in {"agent_only", "hybrid"}
        or planned_at >= lease_expires_at
        or isinstance(plan["expected_prior_global_row_count"], bool)
        or not isinstance(plan["expected_prior_global_row_count"], int)
        or plan["expected_prior_global_row_count"] < 0
        or (
            plan["expected_prior_global_row_count"] == 0
            and plan["expected_prior_global_row_sha256"] is not None
        )
        or (
            plan["expected_prior_global_row_count"] > 0
            and _sha256(
                plan["expected_prior_global_row_sha256"],
                "expected prior retained authority head",
            )
            is None
        )
        or isinstance(plan["control_event_count"], bool)
        or not isinstance(plan["control_event_count"], int)
        or plan["control_event_count"] < 1
        or event != expected_event
        or canonical_sha256(event)
        != plan["expected_activation_event_sha256"]
        or plan["persistence_implemented"] is not False
        or plan["transaction_integration_implemented"] is not False
        or plan["submission_integration_implemented"] is not False
        or plan["submission_authority"] != "none"
        or canonical_sha256(body) != plan["activation_bundle_sha256"]
    ):
        raise PaperActivationPlanError("paper activation plan is invalid")
    return plan


def build_plan(
    lease: PaperAuthorityLease,
    candidate_assessment: object,
    startup_assessment: object,
    startup_scan: object,
    runtime: RuntimeControlBindings,
    *,
    trusted_candidate_assessment_sha256: str,
    trusted_startup_assessment_sha256: str,
    trusted_startup_scan_sha256: str,
    trusted_retention_evidence_sha256: str,
    now: datetime,
) -> dict:
    """Build exact future activation bytes after re-verifying every input."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    planned_at = _utc(now, "paper activation plan time")
    try:
        candidate = broker_paper_lease.verify_candidate_assessment(
            candidate_assessment,
            lease,
            trusted_assessment_sha256=trusted_candidate_assessment_sha256,
        )
        startup = broker_startup_readiness.verify_assessment(
            startup_assessment,
            account_id=lease.account_id,
            trusted_assessment_sha256=trusted_startup_assessment_sha256,
        )
        runtime = broker_paper_runtime.verify_runtime_control(
            runtime,
            account_id=lease.account_id,
        )
        scan = _verify_startup_scan(
            startup_scan,
            runtime,
            account_id=lease.account_id,
            trusted_scan_sha256=trusted_startup_scan_sha256,
            trusted_retention_evidence_sha256=(
                trusted_retention_evidence_sha256
            ),
        )
    except (TypeError, ValueError) as exc:
        raise PaperActivationPlanError(
            "paper activation source evidence verification failed"
        ) from exc

    candidate_at = _parse_timestamp(
        candidate["observed_at"],
        "paper candidate assessment time",
    )
    startup_at = _parse_timestamp(
        startup["observed_at"],
        "paper startup assessment time",
    )
    scan_at = scan["_observed_at"]
    control = startup["operational_control"]
    if (
        candidate["startup_assessment_sha256"]
        != startup["assessment_sha256"]
        or startup["operational_control_sha256"]
        != runtime.control_status_sha256
        or control["event_count"] != runtime.control.event_count
        or control["latest_event_sha256"]
        != runtime.control.latest_event_sha256
        or not lease.not_before <= candidate_at <= planned_at < lease.expires_at
        or not startup_at <= planned_at
        or not scan_at <= planned_at
        or (planned_at - startup_at).total_seconds()
        > MAX_ACTIVATION_EVIDENCE_AGE_SECONDS
        or (planned_at - scan_at).total_seconds()
        > MAX_ACTIVATION_EVIDENCE_AGE_SECONDS
    ):
        raise PaperActivationPlanError(
            "paper activation evidence is stale or does not match"
        )
    if any(
        record["lease_id"] == lease.lease_id
        or record["lease_sha256"] == lease.sha256()
        for record in scan["records"]
    ):
        raise PaperActivationPlanError(
            "paper activation lease identity was already retained"
        )

    event = {
        "schema_version": ACTIVATION_EVENT_SCHEMA_VERSION,
        "event_type": "activation_recorded",
        "event_sequence": 1,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "occurred_at": _timestamp(planned_at),
        "prior_event_sha256": None,
        "submission_authority": "none",
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "startup_assessment_sha256": startup["assessment_sha256"],
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
    }
    body = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "ready_for_future_activation_commit_design_only",
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "candidate_assessment_sha256": candidate["assessment_sha256"],
        "startup_assessment_sha256": startup["assessment_sha256"],
        "startup_scan_sha256": scan["scan_sha256"],
        "retention_evidence_sha256": scan["retention_evidence_sha256"],
        "expected_prior_global_row_count": (
            scan["trusted_retained_row_count"]
        ),
        "expected_prior_global_row_sha256": (
            scan["trusted_latest_retained_row_sha256"]
        ),
        "runtime_evidence_sha256": runtime.evidence_sha256,
        "runtime_epoch_sha256": runtime.runtime_epoch_sha256,
        "control_event_count": runtime.control.event_count,
        "control_event_sha256": runtime.control.latest_event_sha256,
        "planned_at": _timestamp(planned_at),
        "lease_expires_at": _timestamp(lease.expires_at),
        "expected_activation_event": event,
        "expected_activation_event_sha256": canonical_sha256(event),
        "persistence_implemented": False,
        "transaction_integration_implemented": False,
        "submission_integration_implemented": False,
        "submission_authority": "none",
    }
    return verify_plan(
        {
            **body,
            "activation_bundle_sha256": canonical_sha256(body),
        }
    )
