"""Pure startup scan for retained automatic-paper authority epochs.

The scanner verifies complete caller-retained transcript bundles against the
current process/control binding. Every prior epoch must be terminal or
invalidated; an epoch that still appears open blocks startup. This module has
no storage writer, activation, risk-evaluation, or submission capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

from . import broker_paper_authority_transcript, broker_paper_runtime
from .broker_paper_lease import PaperAuthorityLease
from .broker_paper_runtime import RuntimeControlBindings

STARTUP_SCAN_SCHEMA_VERSION = 1
MAX_RETAINED_EPOCHS = 256
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


class PaperAuthorityStartupScanError(ValueError):
    """Retained authority history is malformed, incomplete, or ambiguous."""


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PaperAuthorityStartupScanError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PaperAuthorityStartupScanError(f"{label} must be a positive integer")
    return value


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise PaperAuthorityStartupScanError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RetainedAuthorityEpoch:
    """One lease and its complete retained transcript head."""

    lease: PaperAuthorityLease
    events: tuple[dict, ...]
    retained_event_count: int
    retained_latest_event_sha256: str
    trusted_activation_event_sha256: str
    candidate_assessment_sha256: str
    startup_assessment_sha256: str
    activation_runtime_epoch_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.lease, PaperAuthorityLease):
            raise TypeError("lease must be a PaperAuthorityLease")
        if not isinstance(self.events, tuple) or not self.events:
            raise PaperAuthorityStartupScanError(
                "retained authority events must be a nonempty tuple"
            )
        _positive_integer(
            self.retained_event_count,
            "retained authority event count",
        )
        for value, label in (
            (
                self.retained_latest_event_sha256,
                "retained latest authority event identity",
            ),
            (
                self.trusted_activation_event_sha256,
                "trusted activation event identity",
            ),
            (
                self.candidate_assessment_sha256,
                "candidate assessment identity",
            ),
            (
                self.startup_assessment_sha256,
                "startup assessment identity",
            ),
            (
                self.activation_runtime_epoch_sha256,
                "activation runtime epoch identity",
            ),
        ):
            _sha256(value, label)


def scan_startup(
    epochs: tuple[RetainedAuthorityEpoch, ...],
    runtime: RuntimeControlBindings,
    *,
    account_id: str,
    now: datetime,
) -> dict:
    """Verify every retained epoch and require all of them to be closed."""
    if not isinstance(epochs, tuple):
        raise TypeError("epochs must be a tuple")
    if len(epochs) > MAX_RETAINED_EPOCHS:
        raise PaperAuthorityStartupScanError(
            "retained authority epoch count exceeds the startup bound"
        )
    observed_at = _utc(now, "paper authority startup scan time")
    try:
        current = broker_paper_runtime.verify_runtime_control(
            runtime,
            account_id=account_id,
        )
    except (TypeError, ValueError) as exc:
        raise PaperAuthorityStartupScanError(
            "paper authority runtime/control verification failed"
        ) from exc

    lease_ids = set()
    lease_hashes = set()
    activation_hashes = set()
    records = []
    for epoch in epochs:
        if not isinstance(epoch, RetainedAuthorityEpoch):
            raise TypeError("epoch must be a RetainedAuthorityEpoch")
        lease = epoch.lease
        lease_sha256 = lease.sha256()
        if (
            lease.account_id != account_id
            or lease.lease_id in lease_ids
            or lease_sha256 in lease_hashes
            or epoch.trusted_activation_event_sha256 in activation_hashes
        ):
            raise PaperAuthorityStartupScanError(
                "retained authority epoch identity is duplicated or out of scope"
            )
        if (
            len(epoch.events) != epoch.retained_event_count
            or not isinstance(epoch.events[-1], dict)
            or epoch.events[-1].get("event_sha256")
            != epoch.retained_latest_event_sha256
        ):
            raise PaperAuthorityStartupScanError(
                "retained authority epoch is incomplete or has the wrong head"
            )
        try:
            verified = broker_paper_authority_transcript.verify_transcript(
                lease,
                epoch.events,
                trusted_activation_event_sha256=(
                    epoch.trusted_activation_event_sha256
                ),
                candidate_assessment_sha256=epoch.candidate_assessment_sha256,
                startup_assessment_sha256=epoch.startup_assessment_sha256,
                activation_runtime_epoch_sha256=(
                    epoch.activation_runtime_epoch_sha256
                ),
                current_runtime_epoch_sha256=current.runtime_epoch_sha256,
                current_control=current.control,
                now=observed_at,
            )
        except broker_paper_authority_transcript.PaperAuthorityTranscriptError as exc:
            raise PaperAuthorityStartupScanError(
                "retained authority epoch verification failed"
            ) from exc
        if (
            verified["event_count"] != epoch.retained_event_count
            or verified["latest_event_sha256"]
            != epoch.retained_latest_event_sha256
        ):
            raise PaperAuthorityStartupScanError(
                "verified authority epoch conflicts with retained head"
            )
        record_body = {
            "lease_id": lease.lease_id,
            "lease_sha256": lease_sha256,
            "state": verified["state"],
            "event_count": verified["event_count"],
            "latest_event_sha256": verified["latest_event_sha256"],
            "transcript_sha256": verified["transcript_sha256"],
            "activation_runtime_epoch_sha256": (
                epoch.activation_runtime_epoch_sha256
            ),
            "current_runtime_epoch_sha256": current.runtime_epoch_sha256,
        }
        records.append(
            {
                **record_body,
                "record_sha256": canonical_sha256(record_body),
            }
        )
        lease_ids.add(lease.lease_id)
        lease_hashes.add(lease_sha256)
        activation_hashes.add(epoch.trusted_activation_event_sha256)

    open_lease_ids = [
        record["lease_id"]
        for record in records
        if record["state"] == "activation_window_open_design_only"
    ]
    invalid_states = [
        record["state"]
        for record in records
        if record["state"] not in _CLOSED_STATES
        and record["state"] != "activation_window_open_design_only"
    ]
    if invalid_states:  # pragma: no cover - verifier owns the closed state set
        raise PaperAuthorityStartupScanError(
            "retained authority epoch has an unknown state"
        )
    body = {
        "schema_version": STARTUP_SCAN_SCHEMA_VERSION,
        "account_id": account_id,
        "status": "safe_closed" if not open_lease_ids else "blocked",
        "safe_closed": not open_lease_ids,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "runtime_epoch_sha256": current.runtime_epoch_sha256,
        "runtime_control_sha256": current.evidence_sha256,
        "retained_epoch_count": len(records),
        "closed_epoch_count": len(records) - len(open_lease_ids),
        "open_lease_ids": open_lease_ids,
        "records": records,
        "startup_authority": "none",
        "submission_authority": "none",
    }
    return {**body, "scan_sha256": canonical_sha256(body)}
