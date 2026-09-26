"""Canonical P16 policy versions and append-only trial lifecycle events.

Evidence aliases do not create new trials. A failed attempted evaluation counts;
an unused registration does not. Historical imports retain event and ingest times.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

EVENT_KINDS = {"evaluated", "retired", "alias", "identity_verified"}


def _time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trial timestamps must have an explicit timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def init_schema(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS p16_trials (
        trial_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, plan_id VARCHAR NOT NULL,
        catalogued_at TIMESTAMP NOT NULL, registration_identity VARCHAR NOT NULL,
        identity_status VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_trial_events (
        event_sha256 VARCHAR PRIMARY KEY, trial_id VARCHAR NOT NULL, event_kind VARCHAR NOT NULL,
        event_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL, source_ref VARCHAR NOT NULL,
        source_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL)""")


def _trial(row) -> dict:
    trial_id, policy, plan, catalogued, raw, status, row_sha = row
    identity = json.loads(raw)
    body = {"trial_id": trial_id, "policy_id": policy, "plan_id": plan,
            "catalogued_at": catalogued.isoformat(), "registration_identity": identity,
            "identity_status": status}
    if canonical_sha256(body) != row_sha or trial_id != canonical_sha256({
        "policy_id": policy, "registration_identity": identity,
    }):
        raise ValueError("trial registration differs")
    return body


def register(con, *, policy_id: str, plan_id: str, registration_identity: dict,
             catalogued_at: datetime, identity_status: str = "verified") -> str:
    if not policy_id or not plan_id or not isinstance(registration_identity, dict) or not registration_identity:
        raise ValueError("trial policy, plan and full registration identity are required")
    if identity_status not in {"verified", "provisional"}:
        raise ValueError("unknown trial identity status")
    encoded = _json(registration_identity)
    trial_id = canonical_sha256({"policy_id": policy_id,
                                 "registration_identity": registration_identity})
    existing = con.execute("SELECT * FROM p16_trials WHERE trial_id=?", [trial_id]).fetchone()
    if existing is not None:
        _trial(existing)
        return trial_id
    timestamp = _time(catalogued_at)
    body = {"trial_id": trial_id, "policy_id": policy_id, "plan_id": plan_id,
            "catalogued_at": timestamp.isoformat(), "registration_identity": registration_identity,
            "identity_status": identity_status}
    con.execute("INSERT INTO p16_trials VALUES (?,?,?,?,?,?,?)",
                [trial_id, policy_id, plan_id, timestamp, encoded, identity_status, canonical_sha256(body)])
    return trial_id


def record_event(con, trial_id: str, event_kind: str, *, event_at: datetime,
                 recorded_at: datetime, source_ref: dict) -> str:
    event_time, recorded = _time(event_at), _time(recorded_at)
    if event_kind not in EVENT_KINDS or event_time > recorded or not isinstance(source_ref, dict) or not source_ref:
        raise ValueError("invalid trial lifecycle event")
    trial = con.execute("SELECT * FROM p16_trials WHERE trial_id=?", [trial_id]).fetchone()
    if trial is None:
        raise ValueError("trial is not catalogued")
    _trial(trial)
    if recorded < trial[3]:
        raise ValueError("trial event ingest predates its catalogue entry")
    raw, source_sha = _json(source_ref), canonical_sha256(source_ref)
    owners = con.execute("SELECT DISTINCT trial_id FROM p16_trial_events WHERE source_sha256=?",
                         [source_sha]).fetchall()
    if any(owner[0] != trial_id for owner in owners):
        raise ValueError("one evidence alias cannot identify two trials")
    body = {"trial_id": trial_id, "event_kind": event_kind, "event_at": event_time.isoformat(),
            "source_ref": source_ref}
    event_sha = canonical_sha256(body)
    existing = con.execute("SELECT * FROM p16_trial_events WHERE event_sha256=?", [event_sha]).fetchone()
    if existing is not None:
        _event(existing)
        return event_sha
    if con.execute("SELECT 1 FROM p16_trial_events WHERE source_sha256=? AND event_kind=?",
                   [source_sha, event_kind]).fetchone():
        raise ValueError("trial event replay differs")
    row_sha = canonical_sha256({"event_sha256": event_sha, "recorded_at": recorded.isoformat()})
    con.execute("INSERT INTO p16_trial_events VALUES (?,?,?,?,?,?,?,?)",
                [event_sha, trial_id, event_kind, event_time, recorded, raw, source_sha, row_sha])
    return event_sha


def _event(row) -> dict:
    event_sha, trial_id, kind, event_at, recorded, raw, source_sha, row_sha = row
    source = json.loads(raw)
    body = {"trial_id": trial_id, "event_kind": kind, "event_at": event_at.isoformat(),
            "source_ref": source}
    if (canonical_sha256(body) != event_sha or canonical_sha256(source) != source_sha
            or canonical_sha256({"event_sha256": event_sha, "recorded_at": recorded.isoformat()}) != row_sha
            or kind not in EVENT_KINDS or event_at > recorded):
        raise ValueError("trial lifecycle evidence differs")
    return {**body, "event_sha256": event_sha, "recorded_at": recorded.isoformat()}


def project(con, *, generated_at: datetime, inventory_complete: bool, limit: int = 100) -> dict:
    cutoff = _time(generated_at)
    if type(inventory_complete) is not bool or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid trial projection settings")
    output, count, unresolved, digest = [], 0, 0, "0" * 64
    initialized = all(table_exists(con, table) for table in ("p16_trials", "p16_trial_events"))
    if initialized:
        for row in con.execute("SELECT * FROM p16_trials WHERE catalogued_at<=? ORDER BY trial_id",
                               [cutoff]).fetchall():
            trial = _trial(row)
            events = [_event(event) for event in con.execute(
                "SELECT * FROM p16_trial_events WHERE trial_id=? AND recorded_at<=? "
                "ORDER BY recorded_at,event_sha256", [row[0], cutoff]).fetchall()]
            evaluated = [event for event in events if event["event_kind"] == "evaluated"]
            if not evaluated:
                continue
            verified = trial["identity_status"] == "verified" or any(
                event["event_kind"] == "identity_verified" for event in events)
            count += 1
            unresolved += not verified
            item = {"trial_id": row[0], "policy_id": row[1], "plan_id": row[2],
                    "first_evaluated_at": min(event["event_at"] for event in evaluated),
                    "retired": any(event["event_kind"] == "retired" for event in events),
                    "identity_verified": verified, "evidence_alias_count": len(events)}
            digest = canonical_sha256({"previous": digest, "trial": item})
            if len(output) < limit:
                output.append(item)
    return {"status": "not_initialized" if not initialized else
            "complete" if inventory_complete and not unresolved else "incomplete",
            "selection_trial_count": count, "unresolved_identity_count": unresolved,
            "inventory_complete": initialized and inventory_complete, "versions": output,
            "versions_truncated": count > len(output), "register_sha256": digest,
            "execution_authority": "none"}
