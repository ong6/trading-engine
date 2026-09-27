"""Append-only persistence for P16 evaluation inputs and sequential prefixes."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_sequential
from server import p16_trial_store

ARTIFACT_KINDS = {
    "origin", "exposure", "policy_scores", "factor_report", "top_quintile",
    "trial_dispersion", "transfer", "sequential_checkpoint", "family_report",
}
ORIGIN_EVENTS = {"pending", "scored", "decision_unavailable", "invalid"}


def _timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"{field} is invalid")
    return value


def init_schema(con) -> None:
    p16_trial_store.init_schema(con)
    con.execute("""CREATE TABLE IF NOT EXISTS p16_evaluation_artifacts (
        artifact_sha256 VARCHAR PRIMARY KEY, registration_sha256 VARCHAR NOT NULL,
        artifact_kind VARCHAR NOT NULL,
        artifact_key VARCHAR NOT NULL, market_date DATE NOT NULL,
        information_cutoff_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL,
        source_sha256 VARCHAR NOT NULL, payload_json VARCHAR NOT NULL,
        payload_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL,
        UNIQUE(registration_sha256,artifact_kind,artifact_key,market_date,information_cutoff_at)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_sequential_origin_events (
        registration_sha256 VARCHAR NOT NULL, family_id VARCHAR NOT NULL,
        comparison_id VARCHAR NOT NULL, trial_id VARCHAR NOT NULL,
        control_trial_id VARCHAR NOT NULL,
        epoch_session DATE NOT NULL, session_index INTEGER NOT NULL,
        market_date DATE NOT NULL, event_kind VARCHAR NOT NULL, reason VARCHAR,
        decided_at TIMESTAMP NOT NULL, forward_entry_at TIMESTAMP NOT NULL,
        labels_available_at TIMESTAMP, delta_ic DOUBLE, input_sha256 VARCHAR,
        source_sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL,
        event_sha256 VARCHAR PRIMARY KEY, row_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(registration_sha256,comparison_id,session_index,event_kind)
    )""")


def _artifact_row(row: tuple) -> dict:
    (artifact_id, registration_sha, kind, key, market_date, cutoff, recorded, source_sha, raw,
     payload_sha, row_sha) = row
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored P16 artifact payload is invalid") from exc
    logical = {
        "registration_sha256": registration_sha, "artifact_kind": kind, "artifact_key": key,
        "market_date": market_date.isoformat(),
        "information_cutoff_at": cutoff.isoformat(), "source_sha256": source_sha,
        "payload_sha256": canonical_sha256(payload),
    }
    expected_id = canonical_sha256(logical)
    expected_row = canonical_sha256({
        "artifact_sha256": expected_id, "recorded_at": recorded.isoformat(),
    })
    if (kind not in ARTIFACT_KINDS or payload_sha != logical["payload_sha256"]
            or artifact_id != expected_id or row_sha != expected_row):
        raise ValueError("stored P16 artifact identity differs")
    return {
        **logical, "artifact_sha256": artifact_id, "recorded_at": _aware(recorded),
        "information_cutoff_at": _aware(cutoff), "market_date": market_date,
        "payload": payload, "row_sha256": row_sha,
    }


def record_artifact(
    con, *, registration_sha256: str, artifact_kind: str, artifact_key: str, market_date: date,
    information_cutoff_at: datetime, recorded_at: datetime, source_sha256: str,
    payload: dict,
) -> str:
    """Insert one immutable artifact; exact retries are idempotent."""
    if artifact_kind not in ARTIFACT_KINDS or not isinstance(market_date, date) \
            or isinstance(market_date, datetime) or not isinstance(payload, dict):
        raise ValueError("P16 artifact is invalid")
    key = _text(artifact_key, "artifact key")
    registration = _digest(registration_sha256, "registration digest")
    source = _digest(source_sha256, "artifact source digest")
    cutoff = _timestamp(information_cutoff_at, "information cutoff")
    recorded = _timestamp(recorded_at, "recorded at")
    if recorded < cutoff:
        raise ValueError("P16 artifact was recorded before its cutoff")
    payload_sha = canonical_sha256(payload)
    logical = {
        "registration_sha256": registration, "artifact_kind": artifact_kind,
        "artifact_key": key,
        "market_date": market_date.isoformat(),
        "information_cutoff_at": cutoff.isoformat(), "source_sha256": source,
        "payload_sha256": payload_sha,
    }
    artifact_id = canonical_sha256(logical)
    row_sha = canonical_sha256({
        "artifact_sha256": artifact_id, "recorded_at": recorded.isoformat(),
    })
    row = (artifact_id, registration, artifact_kind, key, market_date, cutoff, recorded, source,
           json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
           payload_sha, row_sha)
    existing = con.execute(
        "SELECT * FROM p16_evaluation_artifacts WHERE registration_sha256=? "
        "AND artifact_kind=? AND artifact_key=? AND market_date=? AND information_cutoff_at=?",
        [registration, artifact_kind, key, market_date, cutoff],
    ).fetchone()
    if existing is not None:
        if _artifact_row(existing)["artifact_sha256"] != artifact_id:
            raise ValueError("P16 artifact logical key was replayed differently")
        return artifact_id
    con.execute("INSERT INTO p16_evaluation_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    return artifact_id


def artifacts_as_of(
    con, *, generated_at: datetime, registration_sha256: str | None = None,
    artifact_kind: str | None = None,
    artifact_key: str | None = None, through_market_date: date | None = None,
) -> list[dict]:
    """Return verified artifacts visible at a common report instant."""
    cutoff = _timestamp(generated_at, "generated at")
    if not table_exists(con, "p16_evaluation_artifacts"):
        return []
    clauses, values = ["information_cutoff_at<=?", "recorded_at<=?"], [cutoff, cutoff]
    if registration_sha256 is not None:
        clauses.append("registration_sha256=?")
        values.append(_digest(registration_sha256, "registration digest"))
    if artifact_kind is not None:
        if artifact_kind not in ARTIFACT_KINDS:
            raise ValueError("P16 artifact kind is invalid")
        clauses.append("artifact_kind=?")
        values.append(artifact_kind)
    if artifact_key is not None:
        clauses.append("artifact_key=?")
        values.append(_text(artifact_key, "artifact key"))
    if through_market_date is not None:
        clauses.append("market_date<=?")
        values.append(through_market_date)
    rows = con.execute(
        "SELECT * FROM p16_evaluation_artifacts WHERE " + " AND ".join(clauses)
        + " ORDER BY market_date,information_cutoff_at,artifact_kind,artifact_key",
        values,
    ).fetchall()
    return [_artifact_row(row) for row in rows]


def _session_at(epoch: date, index: int) -> date:
    if (not isinstance(epoch, date) or isinstance(epoch, datetime)
            or not p16_sequential.nyse.is_session(epoch)):
        raise ValueError("sequential epoch is invalid")
    current = epoch
    for _ in range(index):
        current = p16_sequential.nyse.next_session(current)
    return current


def _trial_visible(con, trial_id: str, at: datetime) -> bool:
    return p16_trial_store.registration_as_of(
        con, trial_id=trial_id, generated_at=_aware(at)) is not None


def _origin_body(
    *, registration_sha256: str, family_id: str, comparison_id: str, trial_id: str,
    control_trial_id: str, epoch_session: date, session_index: int, market_date: date,
    status: str, reason: str | None, decided_at: datetime, forward_entry_at: datetime,
    labels_available_at: datetime | None, delta_ic: float | None,
    input_sha256: str | None, source_sha256: str,
) -> dict:
    if (type(session_index) is not int or session_index < 0
            or not isinstance(market_date, date) or isinstance(market_date, datetime)
            or status not in ORIGIN_EVENTS):
        raise ValueError("P16 sequential origin event is invalid")
    registration = _digest(registration_sha256, "registration digest")
    family = _text(family_id, "family ID")
    comparison = _text(comparison_id, "comparison ID")
    trial = _digest(trial_id, "trial ID")
    control = _digest(control_trial_id, "control trial ID")
    source = _digest(source_sha256, "sequential source digest")
    if trial == control or market_date != _session_at(epoch_session, session_index):
        raise ValueError("P16 sequential origin is off its registered identity or session grid")
    decided = _timestamp(decided_at, "decided at")
    entry = _timestamp(forward_entry_at, "forward entry at")
    if decided >= entry:
        raise ValueError("P16 sequential decision is not pre-entry")
    available = None if labels_available_at is None else _timestamp(
        labels_available_at, "labels available at")
    digest = None
    if status == "scored":
        if (available is None or available < entry or isinstance(delta_ic, bool)
                or not isinstance(delta_ic, (int, float)) or not math.isfinite(delta_ic)
                or not -2 <= float(delta_ic) <= 2 or reason is not None):
            raise ValueError("P16 scored sequential origin is invalid")
        digest = _digest(input_sha256, "sequential input digest")
    elif status == "decision_unavailable":
        if reason not in p16_sequential.SKIP_REASONS or delta_ic is not None \
                or available is not None or input_sha256 is not None:
            raise ValueError("P16 skipped sequential origin is invalid")
    elif (not isinstance(reason, str) or not reason or delta_ic is not None
          or input_sha256 is not None or (status == "pending" and available is not None)):
        raise ValueError("P16 blocked sequential origin is invalid")
    return {
        "registration_sha256": registration, "family_id": family,
        "comparison_id": comparison, "trial_id": trial, "control_trial_id": control,
        "epoch_session": epoch_session, "session_index": session_index,
        "market_date": market_date, "status": status, "reason": reason,
        "decided_at": decided, "forward_entry_at": entry,
        "labels_available_at": available, "delta_ic": None if delta_ic is None else float(delta_ic),
        "input_sha256": digest, "source_sha256": source,
    }


def _logical_origin(body: dict) -> dict:
    return {
        **body, "epoch_session": body["epoch_session"].isoformat(),
        "market_date": body["market_date"].isoformat(),
        "decided_at": _aware(body["decided_at"]).isoformat(),
        "forward_entry_at": _aware(body["forward_entry_at"]).isoformat(),
        "labels_available_at": None if body["labels_available_at"] is None
        else _aware(body["labels_available_at"]).isoformat(),
    }


def _sequential_row(row: tuple) -> dict:
    (registration, family, comparison, trial, control, epoch, index, market_date,
     status, reason, decided, entry, available, delta, input_sha, source_sha,
     recorded, event_sha, row_sha) = row
    body = _origin_body(
        registration_sha256=registration, family_id=family, comparison_id=comparison,
        trial_id=trial, control_trial_id=control, epoch_session=epoch,
        session_index=index, market_date=market_date, status=status, reason=reason,
        decided_at=_aware(decided), forward_entry_at=_aware(entry),
        labels_available_at=None if available is None else _aware(available),
        delta_ic=delta, input_sha256=input_sha, source_sha256=source_sha,
    )
    logical = _logical_origin(body)
    expected_event = canonical_sha256(logical)
    expected_row = canonical_sha256({
        "event_sha256": expected_event, "recorded_at": recorded.isoformat(),
    })
    if event_sha != expected_event or row_sha != expected_row:
        raise ValueError("stored P16 sequential origin event differs")
    return {
        **logical, "decided_at": _aware(decided).isoformat(),
        "forward_entry_at": _aware(entry).isoformat(),
        "labels_available_at": None if available is None else _aware(available).isoformat(),
        "recorded_at": _aware(recorded), "event_sha256": event_sha,
        "row_sha256": row_sha,
    }


def record_sequential_origin(con, *, recorded_at: datetime, **values) -> str:
    """Append a pre-entry decision or its later terminal outcome event."""
    body = _origin_body(**values)
    recorded = _timestamp(recorded_at, "recorded at")
    if not _trial_visible(con, body["trial_id"], recorded) \
            or not _trial_visible(con, body["control_trial_id"], recorded):
        raise ValueError("P16 sequential trial identity is not registered")
    if recorded < body["decided_at"] or (
            body["status"] in {"pending", "decision_unavailable"}
            and recorded >= body["forward_entry_at"]) or (
            body["status"] == "scored" and recorded < body["labels_available_at"]):
        raise ValueError("P16 sequential event time is invalid")
    prior_rows = con.execute(
        "SELECT * FROM p16_sequential_origin_events WHERE registration_sha256=? "
        "AND comparison_id=? AND session_index=? ORDER BY recorded_at,event_kind",
        [body["registration_sha256"], body["comparison_id"], body["session_index"]],
    ).fetchall()
    prior = [_sequential_row(row) for row in prior_rows]
    same = [row for row in prior if row["status"] == body["status"]]
    logical = _logical_origin(body)
    event_sha = canonical_sha256(logical)
    row_sha = canonical_sha256({
        "event_sha256": event_sha, "recorded_at": recorded.isoformat(),
    })
    if same:
        if len(same) != 1 or same[0]["event_sha256"] != event_sha:
            raise ValueError("P16 sequential origin event was replayed differently")
        return same[0]["event_sha256"]
    decisions = [row for row in prior if row["status"] in {"pending", "decision_unavailable"}]
    terminals = [row for row in prior if row["status"] in {"scored", "invalid"}]
    if body["status"] in {"pending", "decision_unavailable"}:
        if decisions or terminals:
            raise ValueError("P16 sequential decision is duplicated")
    else:
        if len(decisions) != 1 or decisions[0]["status"] != "pending" or terminals:
            raise ValueError("P16 sequential terminal event has no unique pending decision")
        for field in ("family_id", "trial_id", "control_trial_id", "epoch_session",
                      "market_date", "decided_at", "forward_entry_at"):
            if decisions[0][field] != logical[field]:
                raise ValueError("P16 sequential terminal event changed its decision identity")
    row = (
        body["registration_sha256"], body["family_id"], body["comparison_id"],
        body["trial_id"], body["control_trial_id"], body["epoch_session"],
        body["session_index"], body["market_date"], body["status"], body["reason"],
        body["decided_at"], body["forward_entry_at"], body["labels_available_at"],
        body["delta_ic"], body["input_sha256"], body["source_sha256"], recorded,
        event_sha, row_sha,
    )
    con.execute("INSERT INTO p16_sequential_origin_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    return event_sha


def sequential_prefix(
    con, *, registration_sha256: str, family_id: str, comparison_id: str,
    trial_id: str, control_trial_id: str, epoch_session: date,
    origin_endpoint: int, report_at: datetime,
) -> list[dict]:
    """Project exact decision rows 0..endpoint, matured only by report_at."""
    registration = _digest(registration_sha256, "registration digest")
    family = _text(family_id, "family ID")
    comparison = _text(comparison_id, "comparison ID")
    trial = _digest(trial_id, "trial ID")
    control = _digest(control_trial_id, "control trial ID")
    if type(origin_endpoint) is not int or origin_endpoint < -1:
        raise ValueError("origin endpoint is invalid")
    cutoff = _timestamp(report_at, "report at")
    if not table_exists(con, "p16_sequential_origin_events"):
        rows = []
    else:
        rows = con.execute(
            "SELECT * FROM p16_sequential_origin_events WHERE registration_sha256=? "
            "AND family_id=? AND comparison_id=? AND trial_id=? AND control_trial_id=? "
            "AND epoch_session=? AND session_index<=? AND recorded_at<=? "
            "ORDER BY session_index,recorded_at,event_kind",
            [registration, family, comparison, trial, control, epoch_session,
             origin_endpoint, cutoff],
        ).fetchall()
    events: dict[int, list[dict]] = {}
    for row in map(_sequential_row, rows):
        events.setdefault(row["session_index"], []).append(row)
    if sorted(events) != list(range(origin_endpoint + 1)):
        raise ValueError("P16 sequential prefix is missing a retained decision")
    result = []
    for index in range(origin_endpoint + 1):
        decisions = [row for row in events[index]
                     if row["status"] in {"pending", "decision_unavailable"}]
        terminals = [row for row in events[index] if row["status"] in {"scored", "invalid"}]
        if len(decisions) != 1 or len(terminals) > 1:
            raise ValueError("P16 sequential origin event history is invalid")
        result.append(terminals[0] if terminals else decisions[0])
    return result
