"""Durable, trial-set-aware lockbox consumption for P16 replay evidence."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from farm.replay.store import ReplayStoreError, checked_store_path, open_store

_SHA256 = re.compile(r"[0-9a-f]{64}")
_ROLES = frozenset({"initiating", "paired", "cross_model"})
_EVENTS = frozenset(
    {
        "dispatched",
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
    endpoint_sha256: str
    development_artifact_sha256: str
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
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
    _hash(arm.endpoint_sha256, "endpoint_sha256")
    _hash(arm.development_artifact_sha256, "development_artifact_sha256")
    return asdict(arm)


def trial_set_sha256(arms: Sequence[ConfirmatoryArm], sessions: Sequence[date]) -> str:
    payloads = sorted(
        (_arm_payload(arm) for arm in arms),
        key=lambda item: (item["trial_id"], item["execution_id"]),
    )
    if not payloads or len({item["execution_id"] for item in payloads}) != len(payloads):
        raise LockboxIntegrityError("invalid_lockbox_arm_set")
    return canonical_sha256({"arms": payloads, "sessions": list(_session_values(sessions))})


class LockboxLedger:
    """A shared control DB, deliberately separate from replaceable policy stores."""

    def __init__(self, path: Path, *, research_root: Path, live_db_path: Path):
        if path.suffix != ".duckdb":
            raise LockboxIntegrityError("invalid_lockbox_ledger_path")
        self.research_root, self.live_db_path = research_root, live_db_path
        self.path = self._checked_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            store = open_store(
                self.path, research_root=self.research_root,
                live_db_path=self.live_db_path, kind="control",
            )
            con = store.__enter__()
        except ReplayStoreError as exc:
            raise LockboxIntegrityError(f"invalid_lockbox_ledger_store:{exc}") from exc
        try:
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
                """CREATE TABLE IF NOT EXISTS w4_lockbox_first_sessions (
                    session DATE PRIMARY KEY,
                    marker_sha256 VARCHAR NOT NULL)"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_arms (
                    marker_sha256 VARCHAR NOT NULL,
                    trial_id VARCHAR NOT NULL,
                    execution_id VARCHAR NOT NULL,
                    model_identity_sha256 VARCHAR NOT NULL,
                    execution_manifest_sha256 VARCHAR NOT NULL,
                    endpoint_sha256 VARCHAR NOT NULL,
                    development_artifact_sha256 VARCHAR NOT NULL,
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
                    event_index INTEGER NOT NULL,
                    payload_json VARCHAR NOT NULL)"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_event_state (
                    marker_sha256 VARCHAR PRIMARY KEY,
                    event_count INTEGER NOT NULL,
                    chain_sha256 VARCHAR NOT NULL)"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS w4_lockbox_event_chain (
                    marker_sha256 VARCHAR NOT NULL,
                    event_index INTEGER NOT NULL,
                    event_sha256 VARCHAR,
                    chain_sha256 VARCHAR NOT NULL,
                    PRIMARY KEY(marker_sha256, event_index))"""
            )
        finally:
            store.__exit__(None, None, None)

    def _checked_path(self, path: Path) -> Path:
        try:
            return checked_store_path(
                path, research_root=self.research_root, live_db_path=self.live_db_path
            )
        except ReplayStoreError as exc:
            raise LockboxIntegrityError(f"invalid_lockbox_ledger_path:{exc}") from exc

    def _connect(self):
        con = engine_db.connect(self._checked_path(self.path))
        row = con.execute("SELECT store_kind FROM w4_store_identity").fetchone()
        if row != ("control",):
            con.close()
            raise LockboxIntegrityError("lockbox_ledger_not_control_store")
        return con

    def marker(self, experiment_id: str, cohort_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT marker_sha256, payload_json FROM w4_lockbox_markers "
                "WHERE experiment_id=? AND cohort_id=?",
                [experiment_id, cohort_id],
            ).fetchone()
            if row is None:
                return None
            payload, _events = _validate_marker_children(con, row[0], row[1])
            return {**payload, "marker_sha256": row[0]}


def _validate_marker_children(con, marker_sha256: str, encoded: str) -> tuple[dict, list]:
    """Verify every child required by an immutable marker and its event chain."""
    payload = json.loads(encoded)
    if canonical_sha256(payload) != marker_sha256:
        raise LockboxIntegrityError("lockbox_marker_payload_tampered")
    sessions = [row[0].isoformat() for row in con.execute(
        "SELECT session FROM w4_lockbox_sessions WHERE marker_sha256=? ORDER BY session",
        [marker_sha256],
    ).fetchall()]
    arms = [dict(zip(
        ("trial_id", "execution_id", "model_identity_sha256", "execution_manifest_sha256",
         "endpoint_sha256", "development_artifact_sha256", "role"), row,
        strict=True,
    )) for row in con.execute(
        "SELECT trial_id,execution_id,model_identity_sha256,execution_manifest_sha256,"
        "endpoint_sha256,development_artifact_sha256,role FROM w4_lockbox_arms "
        "WHERE marker_sha256=? ORDER BY trial_id,execution_id", [marker_sha256],
    ).fetchall()]
    owners = con.execute(
        "SELECT session,marker_sha256 FROM w4_lockbox_first_sessions "
        "WHERE session IN (SELECT UNNEST(?::DATE[]))", [payload["sessions"]],
    ).fetchall()
    derived = _derived_session_owners(con, payload["sessions"])
    if (sessions != payload["sessions"] or arms != payload["arms"]
            or {row[0].isoformat(): row[1] for row in owners} != derived
            or len(owners) != len(sessions)):
        raise LockboxIntegrityError("lockbox_marker_children_tampered")
    events = con.execute(
        "SELECT event_sha256,execution_id,event_kind,occurred_at,source_sha256,event_index,payload_json "
        "FROM w4_lockbox_events WHERE marker_sha256=? ORDER BY event_index", [marker_sha256],
    ).fetchall()
    state = con.execute(
        "SELECT event_count,chain_sha256 FROM w4_lockbox_event_state WHERE marker_sha256=?",
        [marker_sha256],
    ).fetchone()
    chain_rows = con.execute(
        "SELECT event_index,event_sha256,chain_sha256 FROM w4_lockbox_event_chain "
        "WHERE marker_sha256=? ORDER BY event_index", [marker_sha256],
    ).fetchall()
    chain = canonical_sha256({"marker_sha256": marker_sha256, "events": []})
    expected_chain_rows = [(0, None, chain)]
    for expected_index, row in enumerate(events, start=1):
        event_sha, execution, kind, occurred, source_sha, index, event_json = row
        event_payload = json.loads(event_json)
        expected = {
            "marker_sha256": marker_sha256, "execution_id": execution,
            "event_kind": kind, "occurred_at": occurred, "source_sha256": source_sha,
            "event_index": index,
        }
        if index != expected_index or canonical_sha256(event_payload) != event_sha or event_payload != expected:
            raise LockboxIntegrityError("lockbox_event_history_tampered")
        chain = canonical_sha256({"previous": chain, "event_sha256": event_sha})
        expected_chain_rows.append((expected_index, event_sha, chain))
    if state != (len(events), chain) or chain_rows != expected_chain_rows:
        raise LockboxIntegrityError("lockbox_event_history_tampered")
    return payload, events


def _derived_session_owners(con, sessions: Sequence[str], exclude: str | None = None) -> dict:
    requested, owners = set(sessions), {}
    rows = con.execute(
        "SELECT marker_sha256,payload_json FROM w4_lockbox_markers "
        "ORDER BY committed_at,marker_sha256"
    ).fetchall()
    for marker_sha256, encoded in rows:
        if marker_sha256 == exclude:
            continue
        payload = json.loads(encoded)
        if canonical_sha256(payload) != marker_sha256:
            raise LockboxIntegrityError("lockbox_marker_payload_tampered")
        for session in payload.get("sessions", []):
            if session in requested:
                owners.setdefault(session, marker_sha256)
    return owners


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
    registration_as_of: Callable[[str, datetime], Mapping | None],
) -> str:
    """Atomically commit the complete first trial set before any dispatch or view."""
    session_values = _session_values(sessions)
    arm_payloads = sorted(
        (_arm_payload(arm) for arm in confirmatory_arms),
        key=lambda item: (item["trial_id"], item["execution_id"]),
    )
    actual_trial_set = trial_set_sha256(confirmatory_arms, sessions)
    if _hash(expected_trial_set_sha256, "trial_set_sha256") != actual_trial_set:
        raise LockboxIntegrityError("trial_set_digest_mismatch")
    initiating = [
        arm for arm in arm_payloads if arm["execution_id"] == initiating_execution_id
    ]
    if len(initiating) != 1 or initiating[0]["role"] != "initiating":
        raise LockboxIntegrityError("initiating_arm_missing")
    for arm in arm_payloads:
        registered = registration_as_of(arm["trial_id"], committed_at)
        if not isinstance(registered, Mapping):
            raise LockboxIntegrityError("trial_not_registered_as_of_marker")
        registration = dict(registered)
        registration_sha256 = registration.pop("registration_sha256", None)
        expected = {
            **arm,
            "status": "registered",
            "sessions": list(session_values),
            "trial_set_sha256": actual_trial_set,
            "authority": "historical_research_only",
        }
        if any(registration.get(key) != value for key, value in expected.items()):
            raise LockboxIntegrityError("registered_trial_identity_mismatch")
        registered_at = registration.get("registered_at")
        try:
            registered_at = datetime.fromisoformat(str(registered_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise LockboxIntegrityError("invalid_trial_registered_at") from exc
        if registered_at.tzinfo is None or registered_at > committed_at:
            raise LockboxIntegrityError("trial_not_registered_as_of_marker")
        if registration_sha256 != canonical_sha256(registration):
            raise LockboxIntegrityError("registered_trial_digest_mismatch")

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
                _validate_marker_children(con, marker_sha256, encoded)
                return marker_sha256
            raise LockboxIntegrityError("lockbox_first_marker_conflict")
        latest = con.execute("SELECT MAX(committed_at) FROM w4_lockbox_markers").fetchone()[0]
        if latest is not None and payload["committed_at"] <= latest:
            raise LockboxIntegrityError("non_monotone_lockbox_marker")
        with engine_db.transaction(con):
            con.execute(
                "INSERT INTO w4_lockbox_markers VALUES (?,?,?,?,?)",
                [marker_sha256, experiment_id, cohort_id, payload["committed_at"], encoded],
            )
            con.executemany(
                "INSERT INTO w4_lockbox_sessions VALUES (?,?)",
                [(marker_sha256, session) for session in session_values],
            )
            con.executemany(
                "INSERT INTO w4_lockbox_arms VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        marker_sha256,
                        arm["trial_id"],
                        arm["execution_id"],
                        arm["model_identity_sha256"],
                        arm["execution_manifest_sha256"],
                        arm["endpoint_sha256"],
                        arm["development_artifact_sha256"],
                        arm["role"],
                    )
                    for arm in arm_payloads
                ],
            )
            for session in session_values:
                history = _derived_session_owners(con, (session,), marker_sha256).get(session)
                owner = con.execute(
                    "SELECT marker_sha256 FROM w4_lockbox_first_sessions WHERE session=?", [session]
                ).fetchone()
                if history is not None and owner != (history,):
                    raise LockboxIntegrityError("lockbox_first_session_history_tampered")
                if history is None and owner is None:
                    con.execute(
                        "INSERT INTO w4_lockbox_first_sessions VALUES (?,?)",
                        [session, marker_sha256],
                    )
            con.execute(
                "INSERT INTO w4_lockbox_event_state VALUES (?,?,?)",
                [marker_sha256, 0, canonical_sha256({"marker_sha256": marker_sha256, "events": []})],
            )
            con.execute(
                "INSERT INTO w4_lockbox_event_chain VALUES (?,?,?,?)",
                [marker_sha256, 0, None, canonical_sha256({"marker_sha256": marker_sha256, "events": []})],
            )
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
    marker_sha256 = _hash(marker_sha256, "marker_sha256")
    occurred = _iso(occurred_at, "occurred_at")
    source_sha256 = _hash(source_sha256, "source_sha256")
    with ledger._connect() as con:
        marker = con.execute(
            "SELECT committed_at, payload_json FROM w4_lockbox_markers WHERE marker_sha256=?",
            [marker_sha256],
        ).fetchone()
        if marker is None:
            raise LockboxIntegrityError("lockbox_marker_missing")
        marker_payload, events = _validate_marker_children(con, marker_sha256, marker[1])
        arm_ids = {arm["execution_id"] for arm in marker_payload["arms"]}
        if event_kind != "development_inspected" and execution_id not in arm_ids:
            raise LockboxIntegrityError("event_execution_not_registered")
        if event_kind == "dispatched":
            expected_source = canonical_sha256(
                {"marker_sha256": marker_sha256, "dispatch": "initiating_execution_once"}
            )
            if execution_id != marker_payload["initiating_execution_id"] or source_sha256 != expected_source:
                raise LockboxIntegrityError("invalid_lockbox_dispatch")
            if any(row[2] == "dispatched" for row in events):
                raise LockboxIntegrityError("lockbox_already_dispatched")
        if event_kind == "arm_artifact_frozen":
            expected = con.execute(
                "SELECT development_artifact_sha256 FROM w4_lockbox_arms "
                "WHERE marker_sha256=? AND execution_id=?", [marker_sha256, execution_id],
            ).fetchone()
            if expected is None or source_sha256 != expected[0]:
                raise LockboxIntegrityError("unregistered_arm_artifact")
        if occurred < marker[0]:
            raise LockboxIntegrityError("event_before_lockbox_marker")
        previous = con.execute(
            "SELECT MAX(occurred_at) FROM w4_lockbox_events "
            "WHERE marker_sha256=? AND execution_id=?",
            [marker_sha256, execution_id],
        ).fetchone()[0]
        if previous is not None and occurred < previous:
            raise LockboxIntegrityError("non_monotone_lockbox_event")
        existing = con.execute(
            "SELECT event_sha256 FROM w4_lockbox_events WHERE marker_sha256=? "
            "AND execution_id=? AND event_kind=? AND occurred_at=? AND source_sha256=?",
            [marker_sha256, execution_id, event_kind, occurred, source_sha256],
        ).fetchone()
        if existing is not None:
            return existing[0]
        state = con.execute(
            "SELECT event_count,chain_sha256 FROM w4_lockbox_event_state WHERE marker_sha256=?",
            [marker_sha256],
        ).fetchone()
        if state is None:
            raise LockboxIntegrityError("lockbox_event_history_tampered")
        payload = {
            "marker_sha256": marker_sha256, "execution_id": execution_id,
            "event_kind": event_kind, "occurred_at": occurred,
            "source_sha256": source_sha256, "event_index": state[0] + 1,
        }
        event_sha256 = canonical_sha256(payload)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        chain = canonical_sha256({"previous": state[1], "event_sha256": event_sha256})
        with engine_db.transaction(con):
            con.execute(
                "INSERT INTO w4_lockbox_events VALUES (?,?,?,?,?,?,?,?)",
                [
                    event_sha256,
                    marker_sha256,
                    execution_id,
                    event_kind,
                    payload["occurred_at"],
                    source_sha256,
                    payload["event_index"],
                    encoded,
                ],
            )
            con.execute(
                "UPDATE w4_lockbox_event_state SET event_count=?,chain_sha256=? "
                "WHERE marker_sha256=?", [state[0] + 1, chain, marker_sha256],
            )
            con.execute(
                "INSERT INTO w4_lockbox_event_chain VALUES (?,?,?,?)",
                [marker_sha256, state[0] + 1, event_sha256, chain],
            )
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
    endpoint_sha256: str,
    development_artifact_sha256: str,
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
        marker, all_events = _validate_marker_children(con, marker_sha256, encoded)
        evaluated = _iso(evaluated_at, "evaluated_at")
        if evaluated < marker["committed_at"]:
            raise LockboxIntegrityError("evaluation_before_lockbox_marker")
        if requested != set(marker["sessions"]):
            return EvaluationClassification(
                "post_lockbox_exploratory", "sessions_not_exact_first_marker", marker_sha256
            )
        owner_rows = con.execute(
            "SELECT CAST(session AS VARCHAR),marker_sha256 FROM w4_lockbox_first_sessions "
            "WHERE session IN (SELECT UNNEST(?::DATE[]))", [list(requested)]
        ).fetchall()
        if dict(owner_rows) != {session: marker_sha256 for session in requested}:
            return EvaluationClassification(
                "post_lockbox_exploratory", "sessions_consumed_by_prior_marker", marker_sha256
            )
        identity = (
            trial_id,
            execution_id,
            _hash(model_identity_sha256, "model_identity_sha256"),
            _hash(execution_manifest_sha256, "execution_manifest_sha256"),
            _hash(endpoint_sha256, "endpoint_sha256"),
            _hash(development_artifact_sha256, "development_artifact_sha256"),
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
                    arm["endpoint_sha256"],
                    arm["development_artifact_sha256"],
                )
                == identity
            ),
            None,
        )
        if matched is None:
            return EvaluationClassification(
                "post_lockbox_exploratory", "identity_not_in_first_trial_set", marker_sha256
            )
        events = [row for row in all_events if row[3] <= evaluated]
    arm_ids = {arm["execution_id"] for arm in marker["arms"]}
    freezes = {execution: occurred for _sha, execution, kind, occurred, _source, _index, _json in events
               if kind == "arm_artifact_frozen" and execution in arm_ids}
    inspections = [occurred for _sha, _execution, kind, occurred, _source, _index, _json in events
                   if kind == "development_inspected"]
    if inspections and (
        set(freezes) != arm_ids
        or min(inspections) < max(freezes.values())
    ):
        return EvaluationClassification(
            "post_lockbox_exploratory",
            "cross_model_inspection_before_both_frozen",
            marker_sha256,
        )
    interrupted = [(occurred, source) for _sha, execution, kind, occurred, source, _index, _json in events
                   if execution == identity[1] and kind in {"partial", "crashed"}]
    if interrupted:
        reconciled = all(
            any(
                execution == identity[1] and kind == "completed" and occurred >= interrupted_at
                and source == receipt
                for _sha, execution, kind, occurred, source, _index, _json in events
            )
            for interrupted_at, receipt in interrupted
        )
        if not reconciled:
            return EvaluationClassification(
                "post_lockbox_exploratory", "interrupted_receipt_not_reconciled", marker_sha256
            )
    completions = {
        source for _sha, execution, kind, _occurred, source, _index, _json in events
        if execution == identity[1] and kind == "completed"
    }
    if len(completions) > 1:
        return EvaluationClassification(
            "post_lockbox_exploratory", "conflicting_completed_receipts", marker_sha256
        )
    return EvaluationClassification("confirmatory", "registered_first_trial_set", marker_sha256)


def dispatch_lockbox(
    ledger: LockboxLedger,
    *,
    dispatch: Callable[[str], object],
    begin: dict,
) -> object:
    """Commit and close the marker transaction before calling the provider boundary."""
    existing = ledger.marker(begin["experiment_id"], begin["cohort_id"])
    if existing is not None:
        raise LockboxIntegrityError("lockbox_already_dispatched")
    marker_sha256 = begin_lockbox_consumption(ledger, **begin)
    dispatch_sha256 = canonical_sha256(
        {"marker_sha256": marker_sha256, "dispatch": "initiating_execution_once"}
    )
    marker = ledger.marker(begin["experiment_id"], begin["cohort_id"])
    append_lockbox_event(
        ledger, marker_sha256,
        execution_id=marker["initiating_execution_id"], event_kind="dispatched",
        occurred_at=datetime.fromisoformat(marker["committed_at"].replace("Z", "+00:00")),
        source_sha256=dispatch_sha256,
    )
    return dispatch(marker_sha256)
