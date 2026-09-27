"""Append-only persistence for P16 evaluation inputs and sequential prefixes."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.p16_features import EXPOSURES
from farm import p16_sequential
from farm.p16_factors import CHAMPION, RULE
from server import p16_trial_store
from sim import nyse

ARTIFACT_KINDS = {
    "evaluation_input", "exposure_snapshot", "policy_scores", "factor_report", "top_quintile",
    "trial_dispersion", "transfer", "sequential_checkpoint", "family_report",
}
DECISION_STATUSES = {"eligible", "decision_unavailable"}
OUTCOME_STATUSES = {"scored", "invalid"}


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


def _date(value: object, field: str) -> date:
    try:
        result = value if isinstance(value, date) and not isinstance(value, datetime) \
            else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    return result


def _payload_time(value: object, field: str) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(
            value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    return _aware(_timestamp(result, field))


def _self_hash(payload: dict, field: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("P16 artifact payload is invalid")
    digest = _digest(payload.get(field), field.replace("_", " "))
    if digest != canonical_sha256({key: value for key, value in payload.items() if key != field}):
        raise ValueError(f"{field.replace('_', ' ')} differs")
    return digest


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
        market_date DATE NOT NULL, event_kind VARCHAR NOT NULL, status VARCHAR NOT NULL,
        reason VARCHAR,
        decided_at TIMESTAMP NOT NULL, forward_entry_at TIMESTAMP NOT NULL,
        labels_available_at TIMESTAMP, delta_ic DOUBLE, source_sha256 VARCHAR NOT NULL,
        recorded_at TIMESTAMP NOT NULL,
        event_sha256 VARCHAR PRIMARY KEY, row_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(registration_sha256,family_id,comparison_id,session_index,event_kind),
        UNIQUE(registration_sha256,family_id,comparison_id,market_date,event_kind)
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


def _record_artifact(
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


def _artifacts_as_of(
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


def _artifact_by_id(con, artifact_sha256: str, *, visible_at: datetime | None = None) -> dict:
    digest = _digest(artifact_sha256, "artifact digest")
    row = con.execute(
        "SELECT * FROM p16_evaluation_artifacts WHERE artifact_sha256=?", [digest],
    ).fetchone()
    if row is None:
        raise ValueError("P16 artifact dependency is absent")
    result = _artifact_row(row)
    if visible_at is not None:
        cutoff = _timestamp(visible_at, "artifact visibility cutoff")
        if result["recorded_at"].replace(tzinfo=None) > cutoff \
                or result["information_cutoff_at"].replace(tzinfo=None) > cutoff:
            raise ValueError("P16 artifact dependency is not visible")
    return result


def record_evaluation_input(
    con, *, registration_sha256: str, payload: dict, recorded_at: datetime,
) -> str:
    """Retain one validated P15 evaluation input snapshot."""
    _self_hash(payload, "input_snapshot_sha256")
    market_date = _date(payload.get("market_date"), "evaluation market date")
    cutoff = _payload_time(payload.get("report_cutoff"), "evaluation report cutoff")
    source = payload.get("source")
    required = {"run_id", "bundle_sha256", "universe_sha256", "context_sha256",
                "source_refs_sha256", "request_sha256", "input_sha256",
                "output_sha256", "trace_sha256"}
    if (payload.get("schema_version") != 1 or payload.get("policy_id") != CHAMPION
            or payload.get("status") not in {"available", "pending"}
            or not isinstance(source, dict) or set(source) != required
            or type(source["run_id"]) is not int or source["run_id"] < 1
            or any(not _digest(source[key], f"evaluation {key}") for key in required - {"run_id"})
            or _digest(payload.get("p15_registration_sha256"), "P15 registration digest") is None):
        raise ValueError("P16 evaluation input is invalid")
    return _record_artifact(
        con, registration_sha256=registration_sha256, artifact_kind="evaluation_input",
        artifact_key=CHAMPION, market_date=market_date, information_cutoff_at=cutoff,
        recorded_at=recorded_at, source_sha256=canonical_sha256({
            "p15_registration_sha256": payload["p15_registration_sha256"], "source": source,
        }), payload=payload,
    )


def record_exposure_snapshot(
    con, *, registration_sha256: str, payload: dict, recorded_at: datetime,
) -> str:
    """Retain one decision-time exposure snapshot before its forward entry."""
    _self_hash(payload, "snapshot_sha256")
    market_date = _date(payload.get("market_date"), "exposure market date")
    cutoff = _payload_time(payload.get("information_cutoff_at"), "exposure cutoff")
    candidates = payload.get("candidates")
    tickers = [row.get("ticker") for row in candidates] if isinstance(candidates, list) else []
    if (payload.get("schema_version") != 2 or payload.get("policy_id") != "p16-eval-v2"
            or payload.get("exposure_names") != list(EXPOSURES) or not candidates
            or len(tickers) != len(set(tickers)) or any(not isinstance(item, str) or not item
                                                        for item in tickers)):
        raise ValueError("P16 exposure snapshot is invalid")
    bars = _digest(payload.get("source_bars_sha256"), "exposure bar digest")
    sectors = _digest(payload.get("sector_snapshot_sha256"), "exposure sector digest")
    next_open = datetime.combine(
        nyse.next_session(market_date), datetime.min.time(), ZoneInfo("America/New_York"),
    ).replace(hour=9, minute=30)
    if _aware(_timestamp(recorded_at, "recorded at")) >= next_open.astimezone(timezone.utc):
        raise ValueError("P16 exposure snapshot was not retained before forward entry")
    return _record_artifact(
        con, registration_sha256=registration_sha256, artifact_kind="exposure_snapshot",
        artifact_key="p16-eval-v2", market_date=market_date,
        information_cutoff_at=cutoff, recorded_at=recorded_at,
        source_sha256=canonical_sha256([bars, sectors]), payload=payload,
    )


def record_policy_scores(
    con, *, registration_sha256: str, payload: dict, recorded_at: datetime,
) -> str:
    """Retain one complete, self-hashed policy score vector."""
    _self_hash(payload, "score_snapshot_sha256")
    policy_id = _text(payload.get("policy_id"), "score policy ID")
    market_date = _date(payload.get("market_date"), "score market date")
    cutoff = _payload_time(payload.get("information_cutoff_at"), "score cutoff")
    scores = payload.get("scores")
    if not isinstance(scores, dict) or not scores or any(
            not isinstance(key, str) or not key for key in scores):
        raise ValueError("P16 policy score snapshot is invalid")
    return _record_artifact(
        con, registration_sha256=registration_sha256, artifact_kind="policy_scores",
        artifact_key=policy_id, market_date=market_date, information_cutoff_at=cutoff,
        recorded_at=recorded_at, source_sha256=payload["score_snapshot_sha256"],
        payload=payload,
    )


def record_factor_report(
    con, *, registration_sha256: str, payload: dict,
    origin_artifact_sha256: str, exposure_artifact_sha256: str,
    score_artifact_sha256s: list[str], recorded_at: datetime,
) -> str:
    """Retain a terminal factor report bound to exact immutable inputs."""
    _self_hash(payload, "factor_report_sha256")
    if payload.get("status") not in {"available", "insufficient"}:
        raise ValueError("only terminal P16 factor reports may be retained")
    market_date = _date(payload.get("market_date"), "factor market date")
    cutoff = _payload_time(payload.get("report_cutoff"), "factor report cutoff")
    origin = _artifact_by_id(con, origin_artifact_sha256, visible_at=cutoff)
    exposure = _artifact_by_id(con, exposure_artifact_sha256, visible_at=cutoff)
    if (origin["artifact_kind"] != "evaluation_input"
            or exposure["artifact_kind"] != "exposure_snapshot"
            or origin["registration_sha256"] != registration_sha256
            or exposure["registration_sha256"] != registration_sha256
            or origin["market_date"] != market_date or exposure["market_date"] != market_date
            or payload.get("input_snapshot_sha256")
            != origin["payload"].get("input_snapshot_sha256")
            or payload.get("exposure_snapshot_sha256")
            != exposure["payload"].get("snapshot_sha256")):
        raise ValueError("P16 factor report dependencies differ")
    if not isinstance(score_artifact_sha256s, list) \
            or score_artifact_sha256s != sorted(set(score_artifact_sha256s)):
        raise ValueError("P16 factor score dependencies are invalid")
    scores = [_artifact_by_id(con, item, visible_at=cutoff)
              for item in score_artifact_sha256s]
    if any(row["artifact_kind"] != "policy_scores"
           or row["registration_sha256"] != registration_sha256
           or row["market_date"] != market_date for row in scores):
        raise ValueError("P16 factor score dependencies differ")
    expected_scores = {row["artifact_key"]: row["payload"].get("score_snapshot_sha256")
                       for row in scores}
    reported_scores = payload.get("score_snapshot_sha256")
    if (not isinstance(reported_scores, dict)
            or {key: value for key, value in reported_scores.items()
                if key not in {CHAMPION, RULE}} != expected_scores):
        raise ValueError("P16 factor score dependencies differ")
    dependencies = [origin, exposure, *scores]
    return _record_artifact(
        con, registration_sha256=registration_sha256, artifact_kind="factor_report",
        artifact_key="p16-factor-v1", market_date=market_date,
        information_cutoff_at=cutoff, recorded_at=recorded_at,
        source_sha256=canonical_sha256([row["row_sha256"] for row in dependencies]),
        payload=payload,
    )


def _session_at(epoch: date, index: int) -> date:
    if (not isinstance(epoch, date) or isinstance(epoch, datetime)
            or not p16_sequential.nyse.is_session(epoch)):
        raise ValueError("sequential epoch is invalid")
    current = epoch
    for _ in range(index):
        current = p16_sequential.nyse.next_session(current)
    return current


def _forward_entry_at(market_date: date) -> datetime:
    return datetime.combine(
        nyse.next_session(market_date), time(9, 30), ZoneInfo("America/New_York"),
    ).astimezone(timezone.utc)


def _trial_visible(con, trial_id: str, at: datetime) -> bool:
    return p16_trial_store.registration_as_of(
        con, trial_id=trial_id, generated_at=_aware(at)) is not None


def _origin_body(
    *, registration_sha256: str, family_id: str, comparison_id: str, trial_id: str,
    control_trial_id: str, epoch_session: date, session_index: int, market_date: date,
    event_kind: str, status: str, reason: str | None, decided_at: datetime,
    forward_entry_at: datetime, labels_available_at: datetime | None,
    delta_ic: float | None, source_sha256: str,
) -> dict:
    if (type(session_index) is not int or session_index < 0
            or not isinstance(market_date, date) or isinstance(market_date, datetime)
            or event_kind not in {"decision", "outcome"}):
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
    if entry != _timestamp(_forward_entry_at(market_date), "derived forward entry"):
        raise ValueError("P16 sequential forward entry differs from the NYSE session grid")
    if decided >= entry:
        raise ValueError("P16 sequential decision is not pre-entry")
    available = None if labels_available_at is None else _timestamp(
        labels_available_at, "labels available at")
    if event_kind == "decision" and status == "eligible":
        if reason is not None or available is not None or delta_ic is not None:
            raise ValueError("P16 eligible sequential decision is invalid")
    elif event_kind == "decision" and status == "decision_unavailable":
        if reason not in p16_sequential.SKIP_REASONS or available is not None \
                or delta_ic is not None:
            raise ValueError("P16 skipped sequential origin is invalid")
    elif event_kind == "outcome" and status == "scored":
        if (available is None or available < entry or isinstance(delta_ic, bool)
                or not isinstance(delta_ic, (int, float)) or not math.isfinite(delta_ic)
                or not -2 <= float(delta_ic) <= 2 or reason is not None):
            raise ValueError("P16 scored sequential origin is invalid")
    elif event_kind == "outcome" and status == "invalid":
        if available is None or not isinstance(reason, str) or not reason or delta_ic is not None:
            raise ValueError("P16 invalid sequential outcome is invalid")
    else:
        raise ValueError("P16 sequential event kind and status differ")
    return {
        "registration_sha256": registration, "family_id": family,
        "comparison_id": comparison, "trial_id": trial, "control_trial_id": control,
        "epoch_session": epoch_session, "session_index": session_index,
        "market_date": market_date, "event_kind": event_kind,
        "status": status, "reason": reason,
        "decided_at": decided, "forward_entry_at": entry,
        "labels_available_at": available, "delta_ic": None if delta_ic is None else float(delta_ic),
        "source_sha256": source,
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
     event_kind, status, reason, decided, entry, available, delta, source_sha,
     recorded, event_sha, row_sha) = row
    body = _origin_body(
        registration_sha256=registration, family_id=family, comparison_id=comparison,
        trial_id=trial, control_trial_id=control, epoch_session=epoch,
        session_index=index, market_date=market_date, event_kind=event_kind,
        status=status, reason=reason,
        decided_at=_aware(decided), forward_entry_at=_aware(entry),
        labels_available_at=None if available is None else _aware(available),
        delta_ic=delta, source_sha256=source_sha,
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


def _record_origin_event(con, *, recorded_at: datetime, **values) -> str:
    body = _origin_body(**values)
    recorded = _timestamp(recorded_at, "recorded at")
    if not _trial_visible(con, body["trial_id"], recorded) \
            or not _trial_visible(con, body["control_trial_id"], recorded):
        raise ValueError("P16 sequential trial identity is not registered")
    if recorded < body["decided_at"] or (
            body["event_kind"] == "decision"
            and recorded >= body["forward_entry_at"]) or (
            body["status"] == "scored" and recorded < body["labels_available_at"]):
        raise ValueError("P16 sequential event time is invalid")
    prior_rows = con.execute(
        "SELECT * FROM p16_sequential_origin_events WHERE registration_sha256=? "
        "AND comparison_id=? AND session_index=? ORDER BY recorded_at,event_kind",
        [body["registration_sha256"], body["comparison_id"], body["session_index"]],
    ).fetchall()
    prior = [_sequential_row(row) for row in prior_rows]
    same = [row for row in prior if row["event_kind"] == body["event_kind"]]
    logical = _logical_origin(body)
    event_sha = canonical_sha256(logical)
    row_sha = canonical_sha256({
        "event_sha256": event_sha, "recorded_at": recorded.isoformat(),
    })
    if same:
        if len(same) != 1 or same[0]["event_sha256"] != event_sha:
            raise ValueError("P16 sequential origin event was replayed differently")
        return same[0]["event_sha256"]
    decisions = [row for row in prior if row["event_kind"] == "decision"]
    terminals = [row for row in prior if row["event_kind"] == "outcome"]
    if body["event_kind"] == "decision":
        if decisions or terminals:
            raise ValueError("P16 sequential decision is duplicated")
    else:
        if len(decisions) != 1 or decisions[0]["status"] != "eligible" or terminals:
            raise ValueError("P16 sequential terminal event has no unique pending decision")
        for field in ("family_id", "trial_id", "control_trial_id", "epoch_session",
                      "market_date", "decided_at", "forward_entry_at"):
            if decisions[0][field] != logical[field]:
                raise ValueError("P16 sequential terminal event changed its decision identity")
    row = (
        body["registration_sha256"], body["family_id"], body["comparison_id"],
        body["trial_id"], body["control_trial_id"], body["epoch_session"],
        body["session_index"], body["market_date"], body["event_kind"],
        body["status"], body["reason"],
        body["decided_at"], body["forward_entry_at"], body["labels_available_at"],
        body["delta_ic"], body["source_sha256"], recorded,
        event_sha, row_sha,
    )
    con.execute("INSERT INTO p16_sequential_origin_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    return event_sha


def record_origin_decision(
    con, *, registration_sha256: str, family_id: str, comparison_id: str,
    trial_id: str, control_trial_id: str, epoch_session: date, session_index: int,
    market_date: date, status: str, reason: str | None, decided_at: datetime,
    forward_entry_at: datetime, source_artifact_sha256: str, recorded_at: datetime,
) -> str:
    """Append the eligible/skip decision before the forward entry."""
    source = _artifact_by_id(con, source_artifact_sha256, visible_at=recorded_at)
    if (source["registration_sha256"] != registration_sha256
            or source["market_date"] != market_date
            or source["artifact_kind"] not in {"evaluation_input", "policy_scores"}
            or source["information_cutoff_at"] > _aware(_timestamp(decided_at, "decided at"))):
        raise ValueError("P16 sequential decision source differs")
    return _record_origin_event(
        con, registration_sha256=registration_sha256, family_id=family_id,
        comparison_id=comparison_id, trial_id=trial_id, control_trial_id=control_trial_id,
        epoch_session=epoch_session, session_index=session_index, market_date=market_date,
        event_kind="decision", status=status, reason=reason, decided_at=decided_at,
        forward_entry_at=forward_entry_at, labels_available_at=None, delta_ic=None,
        source_sha256=source["row_sha256"], recorded_at=recorded_at,
    )


def record_origin_outcome(
    con, *, registration_sha256: str, family_id: str, comparison_id: str,
    trial_id: str, control_trial_id: str, epoch_session: date, session_index: int,
    market_date: date, status: str, decided_at: datetime, forward_entry_at: datetime,
    labels_available_at: datetime, factor_report_sha256: str, recorded_at: datetime,
) -> str:
    """Append a terminal result, deriving the paired IC from its factor report."""
    factor = _artifact_by_id(con, factor_report_sha256, visible_at=recorded_at)
    if (factor["registration_sha256"] != registration_sha256
            or factor["artifact_kind"] != "factor_report"
            or factor["market_date"] != market_date):
        raise ValueError("P16 sequential outcome source differs")
    comparison = factor["payload"].get("comparisons", {}).get(comparison_id, {})
    raw = comparison.get("full_sample_raw", {})
    if status == "scored" and raw.get("status") == "scored":
        delta, reason = raw.get("delta_ic"), None
    elif status == "invalid" and raw.get("status") != "scored":
        delta, reason = None, raw.get("reason") or "comparison_unavailable"
    else:
        raise ValueError("P16 sequential outcome differs from factor report")
    return _record_origin_event(
        con, registration_sha256=registration_sha256, family_id=family_id,
        comparison_id=comparison_id, trial_id=trial_id, control_trial_id=control_trial_id,
        epoch_session=epoch_session, session_index=session_index, market_date=market_date,
        event_kind="outcome", status=status, reason=reason, decided_at=decided_at,
        forward_entry_at=forward_entry_at, labels_available_at=labels_available_at,
        delta_ic=delta, source_sha256=factor["row_sha256"], recorded_at=recorded_at,
    )


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
    result = []
    for index in range(origin_endpoint + 1):
        retained = events.get(index, [])
        decisions = [row for row in retained if row["event_kind"] == "decision"]
        terminals = [row for row in retained if row["event_kind"] == "outcome"]
        if not decisions and not terminals:
            market_date = _session_at(epoch_session, index)
            entry = _forward_entry_at(market_date)
            pending = _aware(cutoff) < entry
            result.append({
                "registration_sha256": registration, "family_id": family,
                "comparison_id": comparison, "trial_id": trial,
                "control_trial_id": control, "epoch_session": epoch_session.isoformat(),
                "session_index": index, "market_date": market_date.isoformat(),
                "event_kind": "derived_gap", "status": (
                    "pending" if pending else "missing_session_record"),
                "reason": "before_forward_entry" if pending else "missing_preentry_decision",
                "decided_at": None, "forward_entry_at": entry.isoformat(),
                "labels_available_at": None, "delta_ic": None,
                "source_sha256": None, "input_sha256": None,
                "derived_not_persisted": True,
            })
            continue
        if len(decisions) != 1 or len(terminals) > 1:
            raise ValueError("P16 sequential origin event history is invalid")
        if terminals:
            result.append({**terminals[0], "input_sha256": terminals[0]["source_sha256"]})
        elif decisions[0]["status"] == "eligible":
            result.append({**decisions[0], "status": "pending", "reason": "label_pending"})
        else:
            result.append(decisions[0])
    return result


def checkpoint_sequential(
    con, *, registration_sha256: str, family_id: str, comparison_id: str,
    trial_id: str, control_trial_id: str, epoch_session: date,
    through_session_index: int, mixture: dict, recorded_at: datetime,
) -> str:
    """Persist recomputed sufficient e-process state through one origin."""
    prefix = sequential_prefix(
        con, registration_sha256=registration_sha256, family_id=family_id,
        comparison_id=comparison_id, trial_id=trial_id,
        control_trial_id=control_trial_id, epoch_session=epoch_session,
        origin_endpoint=through_session_index, report_at=recorded_at,
    )
    if not prefix or prefix[-1]["status"] in {"pending", "invalid"}:
        raise ValueError("P16 sequential checkpoint endpoint is not terminal")
    key = f"{family_id}:{comparison_id}"
    market_date = _session_at(epoch_session, through_session_index)
    prior_rows = _artifacts_as_of(
        con, generated_at=recorded_at, registration_sha256=registration_sha256,
        artifact_kind="sequential_checkpoint", artifact_key=key,
        through_market_date=market_date,
    )
    same = [row for row in prior_rows if row["market_date"] == market_date]
    if same:
        if len(same) != 1 or same[0]["payload"].get(
                "calibration_sha256") != mixture.get("calibration_sha256"):
            raise ValueError("P16 sequential checkpoint was replayed differently")
        return same[0]["artifact_sha256"]
    previous = prior_rows[-1] if prior_rows else None
    state = p16_sequential.by_session_offset(
        prefix, mixture=mixture, epoch_session=epoch_session,
        report_at=recorded_at.isoformat(),
    )
    event_rows = con.execute(
        "SELECT * FROM p16_sequential_origin_events WHERE registration_sha256=? "
        "AND family_id=? AND comparison_id=? AND trial_id=? AND control_trial_id=? "
        "AND epoch_session=? AND session_index<=? AND recorded_at<=? "
        "ORDER BY session_index,event_kind",
        [registration_sha256, family_id, comparison_id, trial_id, control_trial_id,
         epoch_session, through_session_index, _timestamp(recorded_at, "recorded at")],
    ).fetchall()
    verified = [_sequential_row(row) for row in event_rows]
    body = {
        "schema_version": 1, "registration_sha256": registration_sha256,
        "family_id": family_id, "comparison_id": comparison_id,
        "trial_id": trial_id, "control_trial_id": control_trial_id,
        "epoch_session": epoch_session.isoformat(),
        "through_session_index": through_session_index,
        "report_at": _aware(_timestamp(recorded_at, "recorded at")).isoformat(),
        "calibration_sha256": mixture.get("calibration_sha256"),
        "previous_checkpoint_sha256": None if previous is None
        else previous["artifact_sha256"],
        "origin_event_row_sha256s": [row["row_sha256"] for row in verified],
        "sequential": state, "execution_authority": "none",
    }
    payload = {**body, "checkpoint_sha256": canonical_sha256(body)}
    dependencies = [row["row_sha256"] for row in verified]
    if previous is not None:
        dependencies.insert(0, previous["row_sha256"])
    dependencies.append(_digest(mixture.get("calibration_sha256"), "calibration digest"))
    return _record_artifact(
        con, registration_sha256=registration_sha256,
        artifact_kind="sequential_checkpoint", artifact_key=key,
        market_date=market_date, information_cutoff_at=recorded_at,
        recorded_at=recorded_at, source_sha256=canonical_sha256(dependencies),
        payload=payload,
    )


def record_family_report(
    con, *, registration_sha256: str, payload: dict,
    dependency_artifact_sha256s: list[str], recorded_at: datetime,
) -> str:
    """Persist one self-hashed family report and its exact source rows."""
    _self_hash(payload, "report_sha256")
    report_at = _payload_time(payload.get("report_at"), "family report cutoff")
    family_id = _text(payload.get("family_id"), "family ID")
    if (payload.get("evaluation_policy_id") != "p16-eval-v2"
            or payload.get("registration_sha256") != registration_sha256
            or payload.get("execution_authority") != "none"
            or dependency_artifact_sha256s != sorted(set(dependency_artifact_sha256s))
            or payload.get("dependency_artifact_sha256s") != dependency_artifact_sha256s):
        raise ValueError("P16 family report identity differs")
    dependencies = [_artifact_by_id(con, item, visible_at=report_at)
                    for item in dependency_artifact_sha256s]
    if not dependencies or any(
            row["registration_sha256"] != registration_sha256 for row in dependencies):
        raise ValueError("P16 family report dependencies differ")
    previous_rows = _artifacts_as_of(
        con, generated_at=report_at, registration_sha256=registration_sha256,
        artifact_kind="family_report", artifact_key=family_id,
    )
    matching = [row for row in previous_rows
                if row["payload"].get("report_sha256") == payload["report_sha256"]]
    if matching:
        if len(matching) != 1:
            raise ValueError("P16 family report is duplicated")
        return matching[0]["artifact_sha256"]
    previous = previous_rows[-1] if previous_rows else None
    expected_previous = None if previous is None else previous["artifact_sha256"]
    if payload.get("previous_report_sha256") != expected_previous:
        raise ValueError("P16 family report chain differs")
    market_date = max(row["market_date"] for row in dependencies)
    return _record_artifact(
        con, registration_sha256=registration_sha256, artifact_kind="family_report",
        artifact_key=family_id, market_date=market_date,
        information_cutoff_at=report_at, recorded_at=recorded_at,
        source_sha256=canonical_sha256([
            *[row["row_sha256"] for row in dependencies],
            *([] if previous is None else [previous["row_sha256"]]),
        ]),
        payload=payload,
    )


def family_report_as_of(
    con, *, generated_at: datetime, registration_sha256: str | None = None,
    expected_report_sha256: str | None = None,
) -> dict | None:
    """Return the latest visible family report after validating its exact chain."""
    rows = _artifacts_as_of(
        con, generated_at=generated_at, registration_sha256=registration_sha256,
        artifact_kind="family_report",
    )
    if not rows:
        return None
    latest = rows[-1]
    if expected_report_sha256 is not None \
            and latest["artifact_sha256"] != _digest(
                expected_report_sha256, "expected report digest"):
        raise ValueError("P16 family report head differs")
    by_id = {row["artifact_sha256"]: row for row in rows}
    current, seen = latest, set()
    while current is not None:
        if current["artifact_sha256"] in seen:
            raise ValueError("P16 family report chain is cyclic")
        seen.add(current["artifact_sha256"])
        _self_hash(current["payload"], "report_sha256")
        dependencies = [_artifact_by_id(con, dependency, visible_at=generated_at)
                        for dependency in current["payload"].get(
                            "dependency_artifact_sha256s", [])]
        previous = current["payload"].get("previous_report_sha256")
        prior = None if previous is None else by_id.get(previous)
        expected_source = canonical_sha256([
            *[row["row_sha256"] for row in dependencies],
            *([] if prior is None else [prior["row_sha256"]]),
        ])
        if current["source_sha256"] != expected_source:
            raise ValueError("P16 family report dependencies differ")
        current = prior
        if previous is not None and current is None:
            raise ValueError("P16 family report chain is incomplete")
    return latest
