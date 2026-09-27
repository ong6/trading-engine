"""Durable, trial-set-aware lockbox consumption for P16 replay evidence."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Sequence

import duckdb

from engine.lib.provenance import canonical_sha256

_SHA256 = re.compile(r"[0-9a-f]{64}")
_ROLES = frozenset({"initiating", "paired", "cross_model"})
_EVENTS = frozenset(
    {
        "partial",
        "crashed",
        "completed",
        "viewed",
        "arm_artifact_frozen",
        "development_inspected",
    }
)


class LockboxIntegrityError(ValueError):
    """The shared consumption ledger conflicts with its frozen first marker."""


@dataclass(frozen=True)
class ConfirmatoryArm:
    trial_id: str
    execution_id: str
    model_identity_sha256: str
    execution_manifest_sha256: str
    role: Literal["initiating", "paired", "cross_model"]


@dataclass(frozen=True)
class EvaluationClassification:
    tag: Literal["confirmatory", "post_lockbox_exploratory"]
    reason: str
    marker_sha256: str


def _hash(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LockboxIntegrityError(f"invalid_{field}")
    return value


def _iso(value: datetime, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise LockboxIntegrityError(f"invalid_{field}")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_values(sessions: Sequence[date]) -> tuple[str, ...]:
    values = tuple(session.isoformat() for session in sessions)
    if not values or values != tuple(sorted(set(values))):
        raise LockboxIntegrityError("invalid_lockbox_sessions")
    return values


def _arm_payload(arm: ConfirmatoryArm) -> dict:
    if not arm.trial_id or not arm.execution_id or arm.role not in _ROLES:
        raise LockboxIntegrityError("invalid_lockbox_arm")
    _hash(arm.model_identity_sha256, "model_identity_sha256")
    _hash(arm.execution_manifest_sha256, "execution_manifest_sha256")
    return asdict(arm)


def trial_set_sha256(arms: Sequence[ConfirmatoryArm]) -> str:
    payloads = sorted(
        (_arm_payload(arm) for arm in arms),
        key=lambda item: (item["trial_id"], item["execution_id"]),
    )
    if not payloads or len({item["execution_id"] for item in payloads}) != len(payloads):
        raise LockboxIntegrityError("invalid_lockbox_arm_set")
    return canonical_sha256({"arms": payloads})


class LockboxLedger:
    """A shared control DB, deliberately separate from replaceable policy stores."""

    def __init__(self, path: Path):
        if not path.is_absolute() or path.suffix != ".duckdb" or path.is_symlink():
            raise LockboxIntegrityError("invalid_lockbox_ledger_path")
        self.path = path
        self.path.parent.mkdir(parents=False, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_markers (
                    marker_sha256 VARCHAR PRIMARY KEY,
                    experiment_id VARCHAR NOT NULL,
                    cohort_id VARCHAR NOT NULL,
                    committed_at VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL,
                    UNIQUE(experiment_id, cohort_id))"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_sessions (
                    marker_sha256 VARCHAR NOT NULL,
                    session DATE NOT NULL,
                    PRIMARY KEY(marker_sha256, session))"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_arms (
                    marker_sha256 VARCHAR NOT NULL,
                    trial_id VARCHAR NOT NULL,
                    execution_id VARCHAR NOT NULL,
                    model_identity_sha256 VARCHAR NOT NULL,
                    execution_manifest_sha256 VARCHAR NOT NULL,
                    role VARCHAR NOT NULL,
                    PRIMARY KEY(marker_sha256, execution_id))"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_events (
                    event_sha256 VARCHAR PRIMARY KEY,
                    marker_sha256 VARCHAR NOT NULL,
                    execution_id VARCHAR NOT NULL,
                    event_kind VARCHAR NOT NULL,
                    occurred_at VARCHAR NOT NULL,
                    source_sha256 VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL)"""
            )

    def _connect(self):
        return duckdb.connect(str(self.path))

    def marker(self, experiment_id: str, cohort_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT marker_sha256, payload_json FROM w4_lockbox_markers "
                "WHERE experiment_id=? AND cohort_id=?",
                [experiment_id, cohort_id],
            ).fetchone()
        return None if row is None else {**json.loads(row[1]), "marker_sha256": row[0]}


def begin_lockbox_consumption(
    ledger: LockboxLedger,
    *,
    experiment_id: str,
    cohort_id: str,
    sessions: Sequence[date],
    confirmatory_arms: Sequence[ConfirmatoryArm],
    initiating_execution_id: str,
    expected_trial_set_sha256: str,
    committed_at: datetime,
    registration_as_of: Callable[[str, datetime], object | None],
) -> str:
    """Atomically commit the complete first trial set before any dispatch or view."""
    session_values = _session_values(sessions)
    arm_payloads = sorted(
        (_arm_payload(arm) for arm in confirmatory_arms),
        key=lambda item: (item["trial_id"], item["execution_id"]),
    )
    actual_trial_set = trial_set_sha256(confirmatory_arms)
    if _hash(expected_trial_set_sha256, "trial_set_sha256") != actual_trial_set:
        raise LockboxIntegrityError("trial_set_digest_mismatch")
    initiating = [
        arm for arm in arm_payloads if arm["execution_id"] == initiating_execution_id
    ]
    if len(initiating) != 1 or initiating[0]["role"] != "initiating":
        raise LockboxIntegrityError("initiating_arm_missing")
    for arm in arm_payloads:
        if registration_as_of(arm["trial_id"], committed_at) is None:
            raise LockboxIntegrityError("trial_not_registered_as_of_marker")

    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "cohort_id": cohort_id,
        "sessions": list(session_values),
        "arms": arm_payloads,
        "initiating_execution_id": initiating_execution_id,
        "trial_set_sha256": actual_trial_set,
        "committed_at": _iso(committed_at, "committed_at"),
    }
    marker_sha256 = canonical_sha256(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with ledger._connect() as con:
        existing = con.execute(
            "SELECT marker_sha256, payload_json FROM w4_lockbox_markers "
            "WHERE experiment_id=? AND cohort_id=?",
            [experiment_id, cohort_id],
        ).fetchone()
        if existing is not None:
            if existing == (marker_sha256, encoded):
                return marker_sha256
            raise LockboxIntegrityError("lockbox_first_marker_conflict")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "INSERT INTO w4_lockbox_markers VALUES (?,?,?,?,?)",
                [marker_sha256, experiment_id, cohort_id, payload["committed_at"], encoded],
            )
            con.executemany(
                "INSERT INTO w4_lockbox_sessions VALUES (?,?)",
                [(marker_sha256, session) for session in session_values],
            )
            con.executemany(
                "INSERT INTO w4_lockbox_arms VALUES (?,?,?,?,?,?)",
                [
                    (
                        marker_sha256,
                        arm["trial_id"],
                        arm["execution_id"],
                        arm["model_identity_sha256"],
                        arm["execution_manifest_sha256"],
                        arm["role"],
                    )
                    for arm in arm_payloads
                ],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return marker_sha256


def append_lockbox_event(
    ledger: LockboxLedger,
    marker_sha256: str,
    *,
    execution_id: str,
    event_kind: str,
    occurred_at: datetime,
    source_sha256: str,
) -> str:
    if not execution_id or event_kind not in _EVENTS:
        raise LockboxIntegrityError("invalid_lockbox_event")
    payload = {
        "marker_sha256": _hash(marker_sha256, "marker_sha256"),
        "execution_id": execution_id,
        "event_kind": event_kind,
        "occurred_at": _iso(occurred_at, "occurred_at"),
        "source_sha256": _hash(source_sha256, "source_sha256"),
    }
    event_sha256 = canonical_sha256(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with ledger._connect() as con:
        if con.execute(
            "SELECT 1 FROM w4_lockbox_markers WHERE marker_sha256=?", [marker_sha256]
        ).fetchone() is None:
            raise LockboxIntegrityError("lockbox_marker_missing")
        existing = con.execute(
            "SELECT payload_json FROM w4_lockbox_events WHERE event_sha256=?",
            [event_sha256],
        ).fetchone()
        if existing is None:
            con.execute(
                "INSERT INTO w4_lockbox_events VALUES (?,?,?,?,?,?,?)",
                [
                    event_sha256,
                    marker_sha256,
                    execution_id,
                    event_kind,
                    payload["occurred_at"],
                    source_sha256,
                    encoded,
                ],
            )
        elif existing[0] != encoded:
            raise LockboxIntegrityError("lockbox_event_conflict")
    return event_sha256


def evaluation_tag(
    ledger: LockboxLedger,
    *,
    experiment_id: str,
    cohort_id: str,
    trial_id: str,
    execution_id: str,
    model_identity_sha256: str,
    execution_manifest_sha256: str,
    sessions: Sequence[date],
    evaluated_at: datetime,
) -> EvaluationClassification:
    requested = set(_session_values(sessions))
    _iso(evaluated_at, "evaluated_at")
    with ledger._connect() as con:
        marker_row = con.execute(
            "SELECT marker_sha256, payload_json FROM w4_lockbox_markers "
            "WHERE experiment_id=? AND cohort_id=?",
            [experiment_id, cohort_id],
        ).fetchone()
        if marker_row is None:
            raise LockboxIntegrityError("lockbox_marker_missing")
        marker_sha256, encoded = marker_row
        marker = json.loads(encoded)
        if not requested <= set(marker["sessions"]):
            return EvaluationClassification(
                "post_lockbox_exploratory", "sessions_not_in_first_marker", marker_sha256
            )
        identity = (
            trial_id,
            execution_id,
            _hash(model_identity_sha256, "model_identity_sha256"),
            _hash(execution_manifest_sha256, "execution_manifest_sha256"),
        )
        matched = next(
            (
                arm
                for arm in marker["arms"]
                if (
                    arm["trial_id"],
                    arm["execution_id"],
                    arm["model_identity_sha256"],
                    arm["execution_manifest_sha256"],
                )
                == identity
            ),
            None,
        )
        if matched is None:
            return EvaluationClassification(
                "post_lockbox_exploratory", "identity_not_in_first_trial_set", marker_sha256
            )
        events = con.execute(
            "SELECT execution_id, event_kind, occurred_at FROM w4_lockbox_events "
            "WHERE marker_sha256=? ORDER BY occurred_at, event_sha256",
            [marker_sha256],
        ).fetchall()
    freezes = {execution: occurred for execution, kind, occurred in events if kind == "arm_artifact_frozen"}
    inspections = [occurred for _execution, kind, occurred in events if kind == "development_inspected"]
    if inspections and (
        len(freezes) < len(marker["arms"])
        or min(inspections) < max(freezes.values())
    ):
        return EvaluationClassification(
            "post_lockbox_exploratory",
            "cross_model_inspection_before_both_frozen",
            marker_sha256,
        )
    return EvaluationClassification("confirmatory", "registered_first_trial_set", marker_sha256)


def dispatch_lockbox(
    ledger: LockboxLedger,
    *,
    dispatch: Callable[[str], object],
    begin: dict,
) -> object:
    """Commit and close the marker transaction before calling the provider boundary."""
    marker_sha256 = begin_lockbox_consumption(ledger, **begin)
    return dispatch(marker_sha256)
