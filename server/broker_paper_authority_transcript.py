"""Pure verifier for a proposed automatic-paper authority event transcript.

This module defines the crash/restart semantics a future durable authority
writer must satisfy. It does not create, append, activate, consume, revoke, or
persist events and cannot call a broker adapter. Even a valid open transcript
has no submission authority in the current runtime.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from engine.lib.provenance import canonical_sha256

from .broker_contract import require_identifier
from .broker_paper_lease import PaperAuthorityLease

TRANSCRIPT_SCHEMA_VERSION = 2
EVENT_TYPES = (
    "activation_recorded",
    "consumption_committed",
    "revocation_recorded",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PaperAuthorityTranscriptError(ValueError):
    """A proposed authority transcript is malformed or internally inconsistent."""


def _identifier(value: object, label: str) -> str:
    try:
        return require_identifier(value, label)
    except ValueError as exc:
        raise PaperAuthorityTranscriptError(str(exc)) from exc


def _sha256(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperAuthorityTranscriptError(f"{label} must be a lowercase SHA-256")
    return value


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperAuthorityTranscriptError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PaperAuthorityTranscriptError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperAuthorityTranscriptError(f"{label} is invalid") from exc
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise PaperAuthorityTranscriptError(f"{label} is not canonical")
    return _utc(parsed, label)


def _positive(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PaperAuthorityTranscriptError(
            f"{label} must be a positive finite number"
        )
    return float(value)


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PaperAuthorityTranscriptError(
            f"{label} must be a nonnegative integer"
        )
    return value


@dataclass(frozen=True, slots=True)
class ControlAnchor:
    """Verified position in the append-only operational-halt chain."""

    event_count: int
    latest_event_sha256: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.event_count, bool)
            or not isinstance(self.event_count, int)
            or self.event_count < 1
        ):
            raise PaperAuthorityTranscriptError(
                "control anchor event count must be positive"
            )
        _sha256(self.latest_event_sha256, "control anchor identity")

    def payload(self) -> dict:
        return {
            "event_count": self.event_count,
            "latest_event_sha256": self.latest_event_sha256,
        }


def _event(
    value: object,
    *,
    sequence: int,
    prior_event_sha256: str | None,
) -> tuple[dict, datetime]:
    if not isinstance(value, dict):
        raise PaperAuthorityTranscriptError("paper authority event is invalid")
    event_type = value.get("event_type")
    common = {
        "schema_version",
        "event_type",
        "event_sequence",
        "lease_id",
        "lease_sha256",
        "account_id",
        "mode",
        "occurred_at",
        "prior_event_sha256",
        "submission_authority",
        "event_sha256",
    }
    specific = {
        "activation_recorded": {
            "candidate_assessment_sha256",
            "startup_assessment_sha256",
            "control_event_count",
            "control_event_sha256",
            "runtime_epoch_sha256",
        },
        "consumption_committed": {
            "consumption_key",
            "idempotency_key",
            "eligibility_sha256",
            "request_sha256",
            "risk_evaluation_sha256",
            "broker_submission_started_sha256",
            "submission_state",
            "order_notional",
            "resulting_consumed_order_count",
            "resulting_consumed_notional",
        },
        "revocation_recorded": {
            "revocation_key",
            "reason",
            "control_event_count",
            "control_event_sha256",
        },
    }
    if event_type not in EVENT_TYPES or set(value) != common | specific[event_type]:
        raise PaperAuthorityTranscriptError("paper authority event shape is invalid")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
        or value["event_sequence"] != sequence
        or value["prior_event_sha256"] != prior_event_sha256
        or value["submission_authority"] != "none"
    ):
        raise PaperAuthorityTranscriptError(
            "paper authority event sequence or authority is invalid"
        )
    for field, label in (
        ("lease_id", "paper authority lease identifier"),
        ("account_id", "paper authority account identifier"),
    ):
        _identifier(value[field], label)
    if value["mode"] not in {"agent_only", "hybrid"}:
        raise PaperAuthorityTranscriptError("paper authority mode is invalid")
    _sha256(value["lease_sha256"], "paper authority lease identity")
    _sha256(value["prior_event_sha256"], "prior authority event identity", optional=True)
    event_sha256 = _sha256(value["event_sha256"], "paper authority event identity")
    body = {key: item for key, item in value.items() if key != "event_sha256"}
    if canonical_sha256(body) != event_sha256:
        raise PaperAuthorityTranscriptError("paper authority event hash does not match")
    return value, _parse_utc(value["occurred_at"], "paper authority event time")


def _activation(
    event: dict,
    *,
    lease: PaperAuthorityLease,
    trusted_activation_event_sha256: str,
    candidate_assessment_sha256: str,
    startup_assessment_sha256: str,
    runtime_epoch_sha256: str,
) -> ControlAnchor:
    for field in (
        "candidate_assessment_sha256",
        "startup_assessment_sha256",
        "control_event_sha256",
        "runtime_epoch_sha256",
    ):
        _sha256(event[field], field.replace("_", " "))
    if (
        event["event_type"] != "activation_recorded"
        or event["event_sha256"] != trusted_activation_event_sha256
        or event["lease_id"] != lease.lease_id
        or event["lease_sha256"] != lease.sha256()
        or event["account_id"] != lease.account_id
        or event["mode"] != lease.mode
        or event["candidate_assessment_sha256"] != candidate_assessment_sha256
        or event["startup_assessment_sha256"] != startup_assessment_sha256
        or event["runtime_epoch_sha256"] != runtime_epoch_sha256
    ):
        raise PaperAuthorityTranscriptError(
            "paper authority activation binding is invalid"
        )
    return ControlAnchor(
        event_count=event["control_event_count"],
        latest_event_sha256=event["control_event_sha256"],
    )


def _control_relation(
    older: ControlAnchor,
    newer: ControlAnchor,
    *,
    label: str,
) -> Literal["same", "advanced"]:
    if newer.event_count < older.event_count:
        raise PaperAuthorityTranscriptError(f"{label} control chain moved backward")
    if newer.event_count == older.event_count:
        if newer.latest_event_sha256 != older.latest_event_sha256:
            raise PaperAuthorityTranscriptError(f"{label} control anchor conflicts")
        return "same"
    return "advanced"


def verify_transcript(
    lease: PaperAuthorityLease,
    events: tuple[dict, ...],
    *,
    trusted_activation_event_sha256: str,
    candidate_assessment_sha256: str,
    startup_assessment_sha256: str,
    activation_runtime_epoch_sha256: str,
    current_runtime_epoch_sha256: str,
    current_control: ControlAnchor,
    now: datetime,
) -> dict:
    """Verify a proposed event chain without making it executable."""
    if not isinstance(lease, PaperAuthorityLease):
        raise TypeError("lease must be a PaperAuthorityLease")
    if not isinstance(events, tuple) or not events:
        raise PaperAuthorityTranscriptError(
            "paper authority transcript must be a nonempty tuple"
        )
    if not isinstance(current_control, ControlAnchor):
        raise TypeError("current_control must be a ControlAnchor")
    trusted_activation_event_sha256 = _sha256(
        trusted_activation_event_sha256,
        "trusted activation event identity",
    )
    candidate_assessment_sha256 = _sha256(
        candidate_assessment_sha256,
        "candidate assessment identity",
    )
    startup_assessment_sha256 = _sha256(
        startup_assessment_sha256,
        "startup assessment identity",
    )
    activation_runtime_epoch_sha256 = _sha256(
        activation_runtime_epoch_sha256,
        "activation runtime epoch identity",
    )
    current_runtime_epoch_sha256 = _sha256(
        current_runtime_epoch_sha256,
        "current runtime epoch identity",
    )
    observed_at = _utc(now, "paper authority transcript time")

    verified = []
    prior_hash = None
    prior_time = None
    for sequence, raw in enumerate(events, 1):
        event, occurred_at = _event(
            raw,
            sequence=sequence,
            prior_event_sha256=prior_hash,
        )
        if prior_time is not None and occurred_at < prior_time:
            raise PaperAuthorityTranscriptError(
                "paper authority event time moved backward"
            )
        if (
            event["lease_id"] != lease.lease_id
            or event["lease_sha256"] != lease.sha256()
            or event["account_id"] != lease.account_id
            or event["mode"] != lease.mode
        ):
            raise PaperAuthorityTranscriptError(
                "paper authority event conflicts with lease"
            )
        verified.append((event, occurred_at))
        prior_hash = event["event_sha256"]
        prior_time = occurred_at

    activation_event, activated_at = verified[0]
    activation_control = _activation(
        activation_event,
        lease=lease,
        trusted_activation_event_sha256=trusted_activation_event_sha256,
        candidate_assessment_sha256=candidate_assessment_sha256,
        startup_assessment_sha256=startup_assessment_sha256,
        runtime_epoch_sha256=activation_runtime_epoch_sha256,
    )
    if not lease.not_before <= activated_at < lease.expires_at:
        raise PaperAuthorityTranscriptError(
            "paper authority activation is outside the lease window"
        )
    if observed_at < activated_at:
        raise PaperAuthorityTranscriptError(
            "paper authority transcript is observed before activation"
        )

    consumed_count = 0
    consumed_notional = 0.0
    consumption_keys = set()
    idempotency_keys = set()
    request_hashes = set()
    revoked_event = None
    revoked_control = None
    for event, occurred_at in verified[1:]:
        if revoked_event is not None:
            raise PaperAuthorityTranscriptError(
                "paper authority event follows terminal revocation"
            )
        if event["event_type"] == "activation_recorded":
            raise PaperAuthorityTranscriptError(
                "paper authority transcript has multiple activations"
            )
        if occurred_at >= lease.expires_at:
            raise PaperAuthorityTranscriptError(
                "paper authority event is outside the lease window"
            )
        if event["event_type"] == "revocation_recorded":
            _identifier(event["revocation_key"], "paper revocation identifier")
            reason = event["reason"]
            if (
                not isinstance(reason, str)
                or not reason
                or reason != reason.strip()
                or len(reason) > 512
                or not reason.isprintable()
            ):
                raise PaperAuthorityTranscriptError(
                    "paper authority revocation reason is invalid"
                )
            revoked_control = ControlAnchor(
                event_count=event["control_event_count"],
                latest_event_sha256=event["control_event_sha256"],
            )
            if (
                _control_relation(
                    activation_control,
                    revoked_control,
                    label="revocation",
                )
                != "advanced"
            ):
                raise PaperAuthorityTranscriptError(
                    "paper authority revocation requires a later halt event"
                )
            revoked_event = event
            continue
        if event["event_type"] != "consumption_committed":
            raise PaperAuthorityTranscriptError(
                "paper authority event order is invalid"
            )
        consumption_key = _identifier(
            event["consumption_key"],
            "paper consumption identifier",
        )
        idempotency_key = _identifier(
            event["idempotency_key"],
            "paper consumption idempotency key",
        )
        for field in (
            "eligibility_sha256",
            "request_sha256",
            "risk_evaluation_sha256",
            "broker_submission_started_sha256",
        ):
            _sha256(event[field], field.replace("_", " "))
        if event["submission_state"] != "uncertain":
            raise PaperAuthorityTranscriptError(
                "paper consumption must commit with uncertain submission state"
            )
        if (
            consumption_key in consumption_keys
            or idempotency_key in idempotency_keys
            or event["request_sha256"] in request_hashes
        ):
            raise PaperAuthorityTranscriptError(
                "paper authority transcript repeats a consumed intent"
            )
        order_notional = _positive(
            event["order_notional"],
            "paper consumption order notional",
        )
        consumed_count += 1
        consumed_notional += order_notional
        if (
            event["resulting_consumed_order_count"] != consumed_count
            or isinstance(event["resulting_consumed_notional"], bool)
            or not isinstance(event["resulting_consumed_notional"], (int, float))
            or not math.isclose(
                float(event["resulting_consumed_notional"]),
                consumed_notional,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            or order_notional > lease.max_order_notional
            or consumed_count > lease.max_orders
            or consumed_notional > lease.capital_ceiling
        ):
            raise PaperAuthorityTranscriptError(
                "paper authority consumption exceeds or misstates lease capacity"
            )
        consumption_keys.add(consumption_key)
        idempotency_keys.add(idempotency_key)
        request_hashes.add(event["request_sha256"])

    control_relation = _control_relation(
        revoked_control or activation_control,
        current_control,
        label="current",
    )
    if revoked_event is not None:
        state = "revoked"
    elif current_runtime_epoch_sha256 != activation_runtime_epoch_sha256:
        state = "invalidated_by_restart"
    elif control_relation == "advanced":
        state = "invalidated_by_halt"
    elif observed_at >= lease.expires_at:
        state = "expired"
    elif (
        consumed_count >= lease.max_orders
        or consumed_notional >= lease.capital_ceiling
    ):
        state = "exhausted"
    else:
        state = "activation_window_open_design_only"

    body = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.sha256(),
        "account_id": lease.account_id,
        "mode": lease.mode,
        "state": state,
        "event_count": len(verified),
        "latest_event_sha256": verified[-1][0]["event_sha256"],
        "consumed_order_count": consumed_count,
        "consumed_notional": consumed_notional,
        "remaining_order_count": lease.max_orders - consumed_count,
        "remaining_notional": lease.capital_ceiling - consumed_notional,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "lease_expires_at": lease.expires_at.isoformat().replace("+00:00", "Z"),
        "activation_runtime_epoch_sha256": activation_runtime_epoch_sha256,
        "current_runtime_epoch_sha256": current_runtime_epoch_sha256,
        "activation_control": activation_control.payload(),
        "current_control": current_control.payload(),
        "runtime_activation_implemented": False,
        "runtime_consumption_implemented": False,
        "submission_authority": "none",
    }
    return {**body, "transcript_sha256": canonical_sha256(body)}
