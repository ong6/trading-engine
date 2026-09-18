"""Read-only derivation of lease usage from a complete verified transcript.

This module never accepts consumed counters from its caller. It verifies the
full proposed authority transcript against a trusted retained head, requires
the design-only authority epoch to remain open, and derives ``PaperLeaseUsage``
from the verifier result. It does not persist, consume, activate, or authorize
anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

from . import broker_paper_authority_transcript
from .broker_contract import require_identifier
from .broker_paper_authority_transcript import ControlAnchor
from .broker_paper_intent import PaperLeaseUsage
from .broker_paper_lease import PaperAuthorityLease

USAGE_EVIDENCE_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperUsageError(ValueError):
    """Retained authority history cannot produce trusted current usage."""


@dataclass(frozen=True, slots=True)
class LoadedPaperLeaseUsage:
    """Derived usage plus the exact verified transcript identity."""

    usage: PaperLeaseUsage
    consumed_consumption_keys: tuple[str, ...]
    consumed_idempotency_keys: tuple[str, ...]
    consumed_request_sha256s: tuple[str, ...]
    transcript_sha256: str
    event_count: int
    latest_event_sha256: str
    candidate_assessment_sha256: str
    startup_assessment_sha256: str
    activation_runtime_epoch_sha256: str
    current_runtime_epoch_sha256: str
    current_control: ControlAnchor
    observed_at: datetime
    lease_expires_at: datetime
    evidence_sha256: str
    transcript_state: str = "activation_window_open_design_only"
    execution_authority: str = "none"


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperUsageError(f"{label} must be a lowercase SHA-256")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PaperUsageError(f"{label} must be a positive integer")
    return value


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperUsageError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperUsageError(f"{label} is invalid") from exc
    if (
        parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
        or parsed.isoformat().replace("+00:00", "Z") != value
    ):
        raise PaperUsageError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)


def _evidence_body(loaded: LoadedPaperLeaseUsage) -> dict:
    return {
        "schema_version": USAGE_EVIDENCE_SCHEMA_VERSION,
        "lease_id": loaded.usage.lease_id,
        "lease_sha256": loaded.usage.lease_sha256,
        "consumed_consumption_keys": list(
            loaded.consumed_consumption_keys
        ),
        "consumed_idempotency_keys": list(
            loaded.consumed_idempotency_keys
        ),
        "consumed_request_sha256s": list(
            loaded.consumed_request_sha256s
        ),
        "transcript_sha256": loaded.transcript_sha256,
        "event_count": loaded.event_count,
        "latest_event_sha256": loaded.latest_event_sha256,
        "candidate_assessment_sha256": loaded.candidate_assessment_sha256,
        "startup_assessment_sha256": loaded.startup_assessment_sha256,
        "activation_runtime_epoch_sha256": (
            loaded.activation_runtime_epoch_sha256
        ),
        "current_runtime_epoch_sha256": loaded.current_runtime_epoch_sha256,
        "current_control": loaded.current_control.payload(),
        "observed_at": loaded.observed_at.isoformat().replace("+00:00", "Z"),
        "lease_expires_at": loaded.lease_expires_at.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "transcript_state": loaded.transcript_state,
        "usage_sha256": loaded.usage.sha256(),
        "execution_authority": loaded.execution_authority,
    }


def verify_loaded_usage(
    loaded: LoadedPaperLeaseUsage,
    lease: PaperAuthorityLease,
) -> LoadedPaperLeaseUsage:
    """Re-verify one derived usage object without accepting replacement counters."""
    if not isinstance(loaded, LoadedPaperLeaseUsage):
        raise TypeError("loaded must be a LoadedPaperLeaseUsage")
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if (
        not isinstance(loaded.usage, PaperLeaseUsage)
        or not isinstance(loaded.current_control, ControlAnchor)
        or type(loaded.observed_at) is not datetime
        or loaded.observed_at.utcoffset() is None
        or loaded.observed_at.utcoffset().total_seconds() != 0
        or type(loaded.lease_expires_at) is not datetime
        or loaded.lease_expires_at.utcoffset() is None
        or loaded.lease_expires_at.utcoffset().total_seconds() != 0
    ):
        raise PaperUsageError("loaded paper usage evidence is invalid")
    if (
        not isinstance(loaded.consumed_consumption_keys, tuple)
        or not isinstance(loaded.consumed_idempotency_keys, tuple)
        or not isinstance(loaded.consumed_request_sha256s, tuple)
        or loaded.usage.lease_id != lease.lease_id
        or loaded.usage.lease_sha256 != lease.sha256()
        or len(loaded.consumed_consumption_keys)
        != loaded.usage.consumed_order_count
        or len(loaded.consumed_idempotency_keys)
        != loaded.usage.consumed_order_count
        or len(loaded.consumed_request_sha256s)
        != loaded.usage.consumed_order_count
        or isinstance(loaded.event_count, bool)
        or not isinstance(loaded.event_count, int)
        or loaded.event_count != loaded.usage.consumed_order_count + 1
        or len(set(loaded.consumed_consumption_keys))
        != len(loaded.consumed_consumption_keys)
        or len(set(loaded.consumed_idempotency_keys))
        != len(loaded.consumed_idempotency_keys)
        or len(set(loaded.consumed_request_sha256s))
        != len(loaded.consumed_request_sha256s)
        or loaded.transcript_state != "activation_window_open_design_only"
        or loaded.execution_authority != "none"
        or loaded.lease_expires_at != lease.expires_at
        or loaded.observed_at < lease.not_before
        or loaded.observed_at >= loaded.lease_expires_at
        or loaded.evidence_sha256 != canonical_sha256(_evidence_body(loaded))
    ):
        raise PaperUsageError("loaded paper usage evidence is invalid")
    for value, label in (
        (loaded.transcript_sha256, "paper transcript identity"),
        (loaded.latest_event_sha256, "latest paper event identity"),
        (
            loaded.candidate_assessment_sha256,
            "paper candidate assessment identity",
        ),
        (loaded.startup_assessment_sha256, "paper startup identity"),
        (
            loaded.activation_runtime_epoch_sha256,
            "paper activation runtime identity",
        ),
        (
            loaded.current_runtime_epoch_sha256,
            "paper current runtime identity",
        ),
    ):
        _sha256(value, label)
    for value in loaded.consumed_consumption_keys:
        try:
            require_identifier(value, "paper consumption identifier")
        except ValueError as exc:
            raise PaperUsageError("loaded paper usage evidence is invalid") from exc
    for value in loaded.consumed_idempotency_keys:
        try:
            require_identifier(value, "paper consumption idempotency key")
        except ValueError as exc:
            raise PaperUsageError("loaded paper usage evidence is invalid") from exc
    for value in loaded.consumed_request_sha256s:
        _sha256(value, "consumed request identity")
    return loaded


def _verified_result(
    result: object,
    *,
    lease: PaperAuthorityLease,
    trusted_event_count: int,
    trusted_latest_event_sha256: str,
) -> dict:
    expected_fields = {
        "schema_version",
        "lease_id",
        "lease_sha256",
        "account_id",
        "mode",
        "state",
        "event_count",
        "latest_event_sha256",
        "consumed_order_count",
        "consumed_notional",
        "remaining_order_count",
        "remaining_notional",
        "observed_at",
        "lease_expires_at",
        "activation_runtime_epoch_sha256",
        "current_runtime_epoch_sha256",
        "activation_control",
        "current_control",
        "runtime_activation_implemented",
        "runtime_consumption_implemented",
        "submission_authority",
        "transcript_sha256",
    }
    if not isinstance(result, dict) or set(result) != expected_fields:
        raise PaperUsageError("verified paper authority transcript shape is invalid")
    body = {
        key: value for key, value in result.items() if key != "transcript_sha256"
    }
    if (
        result["schema_version"]
        != broker_paper_authority_transcript.TRANSCRIPT_SCHEMA_VERSION
        or result["lease_id"] != lease.lease_id
        or result["lease_sha256"] != lease.sha256()
        or result["account_id"] != lease.account_id
        or result["mode"] != lease.mode
        or result["event_count"] != trusted_event_count
        or result["latest_event_sha256"] != trusted_latest_event_sha256
        or result["transcript_sha256"] != canonical_sha256(body)
        or result["runtime_activation_implemented"] is not False
        or result["runtime_consumption_implemented"] is not False
        or result["submission_authority"] != "none"
    ):
        raise PaperUsageError("verified paper authority transcript binding is invalid")
    if result["state"] != "activation_window_open_design_only":
        raise PaperUsageError("paper authority transcript is not open for future consumption")
    return result


def load_open_usage(
    lease: PaperAuthorityLease,
    events: tuple[dict, ...],
    *,
    trusted_event_count: int,
    trusted_latest_event_sha256: str,
    trusted_activation_event_sha256: str,
    candidate_assessment_sha256: str,
    startup_assessment_sha256: str,
    activation_runtime_epoch_sha256: str,
    current_runtime_epoch_sha256: str,
    current_control: ControlAnchor,
    now: datetime,
) -> LoadedPaperLeaseUsage:
    """Derive current counters from one complete, open transcript."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(events, tuple) or not events:
        raise PaperUsageError("paper authority transcript must be a nonempty tuple")
    trusted_event_count = _positive_integer(
        trusted_event_count,
        "trusted paper authority event count",
    )
    trusted_latest_event_sha256 = _sha256(
        trusted_latest_event_sha256,
        "trusted latest authority event identity",
    )
    if (
        len(events) != trusted_event_count
        or not isinstance(events[-1], dict)
        or events[-1].get("event_sha256") != trusted_latest_event_sha256
    ):
        raise PaperUsageError("paper authority transcript is incomplete or has the wrong head")
    try:
        result = broker_paper_authority_transcript.verify_transcript(
            lease,
            events,
            trusted_activation_event_sha256=trusted_activation_event_sha256,
            candidate_assessment_sha256=candidate_assessment_sha256,
            startup_assessment_sha256=startup_assessment_sha256,
            activation_runtime_epoch_sha256=activation_runtime_epoch_sha256,
            current_runtime_epoch_sha256=current_runtime_epoch_sha256,
            current_control=current_control,
            now=now,
        )
    except broker_paper_authority_transcript.PaperAuthorityTranscriptError as exc:
        raise PaperUsageError("paper authority transcript verification failed") from exc
    verified = _verified_result(
        result,
        lease=lease,
        trusted_event_count=trusted_event_count,
        trusted_latest_event_sha256=trusted_latest_event_sha256,
    )
    usage = PaperLeaseUsage(
        lease_id=lease.lease_id,
        lease_sha256=lease.sha256(),
        consumed_order_count=verified["consumed_order_count"],
        consumed_notional=verified["consumed_notional"],
    )
    consumption_events = tuple(
        event
        for event in events
        if event.get("event_type") == "consumption_committed"
    )
    loaded = LoadedPaperLeaseUsage(
        usage=usage,
        consumed_consumption_keys=tuple(
            event["consumption_key"] for event in consumption_events
        ),
        consumed_idempotency_keys=tuple(
            event["idempotency_key"] for event in consumption_events
        ),
        consumed_request_sha256s=tuple(
            event["request_sha256"] for event in consumption_events
        ),
        transcript_sha256=verified["transcript_sha256"],
        event_count=verified["event_count"],
        latest_event_sha256=verified["latest_event_sha256"],
        candidate_assessment_sha256=candidate_assessment_sha256,
        startup_assessment_sha256=startup_assessment_sha256,
        activation_runtime_epoch_sha256=verified[
            "activation_runtime_epoch_sha256"
        ],
        current_runtime_epoch_sha256=verified["current_runtime_epoch_sha256"],
        current_control=ControlAnchor(**verified["current_control"]),
        observed_at=_parse_utc(verified["observed_at"], "paper usage observation time"),
        lease_expires_at=_parse_utc(
            verified["lease_expires_at"],
            "paper usage lease expiry",
        ),
        evidence_sha256="0" * 64,
    )
    return LoadedPaperLeaseUsage(
        **{
            field: getattr(loaded, field)
            for field in loaded.__dataclass_fields__
            if field != "evidence_sha256"
        },
        evidence_sha256=canonical_sha256(_evidence_body(loaded)),
    )
