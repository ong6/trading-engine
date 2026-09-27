"""Append-only persistence for P16 evaluation inputs and sequential prefixes."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_sequential

ARTIFACT_KINDS = {
    "origin", "exposure", "policy_scores", "factor_report", "top_quintile",
    "trial_dispersion", "transfer", "sequential_checkpoint", "family_report",
}
ORIGIN_STATUSES = {"scored", "decision_unavailable", "pending", "invalid"}


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
    con.execute("""CREATE TABLE IF NOT EXISTS p16_evaluation_artifacts (
        artifact_sha256 VARCHAR PRIMARY KEY, artifact_kind VARCHAR NOT NULL,
        artifact_key VARCHAR NOT NULL, market_date DATE NOT NULL,
        information_cutoff_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL,
        source_sha256 VARCHAR NOT NULL, payload_json VARCHAR NOT NULL,
        payload_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL,
        UNIQUE(artifact_kind,artifact_key,market_date,information_cutoff_at)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_sequential_origins (
        comparison_id VARCHAR NOT NULL, session_index INTEGER NOT NULL,
        market_date DATE NOT NULL, status VARCHAR NOT NULL, reason VARCHAR,
        decided_at TIMESTAMP NOT NULL, forward_entry_at TIMESTAMP NOT NULL,
        labels_available_at TIMESTAMP, delta_ic DOUBLE, input_sha256 VARCHAR,
        recorded_at TIMESTAMP NOT NULL, row_sha256 VARCHAR NOT NULL,
        PRIMARY KEY(comparison_id,session_index), UNIQUE(comparison_id,market_date)
    )""")


def _artifact_row(row: tuple) -> dict:
    (artifact_id, kind, key, market_date, cutoff, recorded, source_sha, raw,
     payload_sha, row_sha) = row
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored P16 artifact payload is invalid") from exc
    logical = {
        "artifact_kind": kind, "artifact_key": key,
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
    con, *, artifact_kind: str, artifact_key: str, market_date: date,
    information_cutoff_at: datetime, recorded_at: datetime, source_sha256: str,
    payload: dict,
) -> str:
    """Insert one immutable artifact; exact retries are idempotent."""
    if artifact_kind not in ARTIFACT_KINDS or not isinstance(market_date, date) \
            or isinstance(market_date, datetime) or not isinstance(payload, dict):
        raise ValueError("P16 artifact is invalid")
    key = _text(artifact_key, "artifact key")
    source = _digest(source_sha256, "artifact source digest")
    cutoff = _timestamp(information_cutoff_at, "information cutoff")
    recorded = _timestamp(recorded_at, "recorded at")
    if recorded < cutoff:
        raise ValueError("P16 artifact was recorded before its cutoff")
    payload_sha = canonical_sha256(payload)
    logical = {
        "artifact_kind": artifact_kind, "artifact_key": key,
        "market_date": market_date.isoformat(),
        "information_cutoff_at": cutoff.isoformat(), "source_sha256": source,
        "payload_sha256": payload_sha,
    }
    artifact_id = canonical_sha256(logical)
    row_sha = canonical_sha256({
        "artifact_sha256": artifact_id, "recorded_at": recorded.isoformat(),
    })
    row = (artifact_id, artifact_kind, key, market_date, cutoff, recorded, source,
           json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
           payload_sha, row_sha)
    existing = con.execute(
        "SELECT * FROM p16_evaluation_artifacts WHERE artifact_kind=? AND artifact_key=? "
        "AND market_date=? AND information_cutoff_at=?",
        [artifact_kind, key, market_date, cutoff],
    ).fetchone()
    if existing is not None:
        if _artifact_row(existing)["artifact_sha256"] != artifact_id:
            raise ValueError("P16 artifact logical key was replayed differently")
        return artifact_id
    con.execute("INSERT INTO p16_evaluation_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    return artifact_id


def artifacts_as_of(
    con, *, generated_at: datetime, artifact_kind: str | None = None,
    artifact_key: str | None = None, through_market_date: date | None = None,
) -> list[dict]:
    """Return verified artifacts visible at a common report instant."""
    cutoff = _timestamp(generated_at, "generated at")
    if not table_exists(con, "p16_evaluation_artifacts"):
        return []
    clauses, values = ["information_cutoff_at<=?", "recorded_at<=?"], [cutoff, cutoff]
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


def _origin_body(
    *, comparison_id: str, session_index: int, market_date: date, status: str,
    reason: str | None, decided_at: datetime, forward_entry_at: datetime,
    labels_available_at: datetime | None, delta_ic: float | None,
    input_sha256: str | None,
) -> dict:
    if (type(session_index) is not int or session_index < 0
            or not isinstance(market_date, date) or isinstance(market_date, datetime)
            or status not in ORIGIN_STATUSES):
        raise ValueError("P16 sequential origin is invalid")
    comparison = _text(comparison_id, "comparison ID")
    decided = _timestamp(decided_at, "decided at")
    entry = _timestamp(forward_entry_at, "forward entry at")
    if decided >= entry:
        raise ValueError("P16 sequential decision is not pre-entry")
    available = None if labels_available_at is None else _timestamp(
        labels_available_at, "labels available at")
    if status == "scored":
        if (available is None or isinstance(delta_ic, bool)
                or not isinstance(delta_ic, (int, float)) or not math.isfinite(delta_ic)
                or not -2 <= float(delta_ic) <= 2 or reason is not None):
            raise ValueError("P16 scored sequential origin is invalid")
        digest = _digest(input_sha256, "sequential input digest")
    elif status == "decision_unavailable":
        if reason not in p16_sequential.SKIP_REASONS or delta_ic is not None \
                or labels_available_at is not None or input_sha256 is not None:
            raise ValueError("P16 skipped sequential origin is invalid")
        digest = None
    else:
        if not isinstance(reason, str) or not reason or delta_ic is not None \
                or input_sha256 is not None:
            raise ValueError("P16 blocked sequential origin is invalid")
        digest = None
    return {
        "comparison_id": comparison, "session_index": session_index,
        "market_date": market_date, "status": status, "reason": reason,
        "decided_at": decided, "forward_entry_at": entry,
        "labels_available_at": available, "delta_ic": None if delta_ic is None else float(delta_ic),
        "input_sha256": digest,
    }


def record_sequential_origin(con, *, recorded_at: datetime, **values) -> str:
    """Append one origin in the immutable registered exchange-session grid."""
    body = _origin_body(**values)
    recorded = _timestamp(recorded_at, "recorded at")
    known = [body["decided_at"], body["forward_entry_at"]]
    if body["labels_available_at"] is not None:
        known.append(body["labels_available_at"])
    if recorded < max(known):
        raise ValueError("P16 sequential origin was recorded before known inputs")
    logical = {
        **body,
        "market_date": body["market_date"].isoformat(),
        "decided_at": body["decided_at"].isoformat(),
        "forward_entry_at": body["forward_entry_at"].isoformat(),
        "labels_available_at": None if body["labels_available_at"] is None
        else body["labels_available_at"].isoformat(),
    }
    row_sha = canonical_sha256({**logical, "recorded_at": recorded.isoformat()})
    row = (*body.values(), recorded, row_sha)
    existing = con.execute(
        "SELECT * FROM p16_sequential_origins WHERE comparison_id=? AND session_index=?",
        [body["comparison_id"], body["session_index"]],
    ).fetchone()
    if existing is not None:
        if _sequential_row(existing)["row_sha256"] != row_sha:
            raise ValueError("P16 sequential origin was replayed differently")
        return row_sha
    con.execute("INSERT INTO p16_sequential_origins VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
    return row_sha


def _sequential_row(row: tuple) -> dict:
    (comparison, index, market_date, status, reason, decided, entry, available,
     delta, input_sha, recorded, row_sha) = row
    body = _origin_body(
        comparison_id=comparison, session_index=index, market_date=market_date,
        status=status, reason=reason, decided_at=_aware(decided),
        forward_entry_at=_aware(entry),
        labels_available_at=None if available is None else _aware(available),
        delta_ic=delta, input_sha256=input_sha,
    )
    logical = {
        **body, "market_date": market_date.isoformat(),
        "decided_at": decided.isoformat(), "forward_entry_at": entry.isoformat(),
        "labels_available_at": None if available is None else available.isoformat(),
    }
    expected = canonical_sha256({**logical, "recorded_at": recorded.isoformat()})
    if expected != row_sha:
        raise ValueError("stored P16 sequential origin differs")
    return {
        **logical, "decided_at": _aware(decided).isoformat(),
        "forward_entry_at": _aware(entry).isoformat(),
        "labels_available_at": None if available is None else _aware(available).isoformat(),
        "recorded_at": _aware(recorded), "row_sha256": row_sha,
    }


def sequential_prefix(
    con, *, comparison_id: str, origin_endpoint: int, report_at: datetime,
) -> list[dict]:
    """Load exactly indices 0..origin_endpoint visible by the report instant."""
    comparison = _text(comparison_id, "comparison ID")
    if type(origin_endpoint) is not int or origin_endpoint < -1:
        raise ValueError("origin endpoint is invalid")
    cutoff = _timestamp(report_at, "report at")
    if not table_exists(con, "p16_sequential_origins"):
        rows = []
    else:
        rows = con.execute(
            "SELECT * FROM p16_sequential_origins WHERE comparison_id=? "
            "AND session_index<=? AND recorded_at<=? ORDER BY session_index",
            [comparison, origin_endpoint, cutoff],
        ).fetchall()
    result = [_sequential_row(row) for row in rows]
    if [row["session_index"] for row in result] != list(range(origin_endpoint + 1)):
        raise ValueError("P16 sequential prefix is incomplete")
    return result
