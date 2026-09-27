"""Append-only persistence adapter for the canonical P16 trial register."""
from __future__ import annotations

from datetime import datetime

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_trials

TABLE = "p16_trial_register_v3"


def init_schema(con) -> None:
    con.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        record_sha256 VARCHAR PRIMARY KEY, record_kind VARCHAR NOT NULL, trial_id VARCHAR,
        event_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL, source_sha256 VARCHAR,
        payload VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE)""")


def _append(con, row: tuple) -> str:
    existing = con.execute(f"SELECT * FROM {TABLE} WHERE record_sha256=?", [row[0]]).fetchone()
    if existing is not None:
        p16_trials.decode(existing)
        if existing != row:
            raise ValueError("trial record replay differs")
        return row[0]
    con.execute(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?,?)", row)
    return row[0]


def _records(con, cutoff: datetime | None = None) -> list[dict]:
    rows = con.execute(f"SELECT * FROM {TABLE}" + (
        " WHERE recorded_at<=? ORDER BY recorded_at,record_sha256" if cutoff else
        " ORDER BY recorded_at,record_sha256"), [] if cutoff is None else [cutoff]).fetchall()
    return [p16_trials.decode(row) for row in rows]


def register(con, *, policy_id: str, policy_version: str, plan_id: str,
             registration_identity: dict, evidence_class: str, parent_trial_ids: list[str],
             registered_at: datetime, recorded_at: datetime,
             identity_status: str = "verified", trial_kind: str = "policy") -> str:
    trial_id, payload = p16_trials.registration(
        policy_id=policy_id, policy_version=policy_version, plan_id=plan_id,
        registration_identity=registration_identity, evidence_class=evidence_class,
        trial_kind=trial_kind,
        parent_trial_ids=parent_trial_ids, registered_at=registered_at,
        identity_status=identity_status)
    recorded = p16_trials.timestamp(recorded_at)
    existing = con.execute(f"SELECT * FROM {TABLE} WHERE record_kind='registration' "
                           "AND trial_id=?", [trial_id]).fetchone()
    row = p16_trials.encoded_record("registration", trial_id, registered_at, recorded_at,
                                   payload, None)
    if existing is not None:
        if existing != row:
            raise ValueError("trial registration replay differs")
        return p16_trials.decode(existing)["trial_id"]
    visible = {item["trial_id"] for item in _records(con, recorded)
               if item["record_kind"] == "registration"
               and item["event_at"] <= payload["registered_at"]}
    if not set(parent_trial_ids) <= visible:
        raise ValueError("trial parent is not registered")
    _append(con, row)
    return trial_id


def record_event(con, trial_id: str, event_kind: str, *, event_at: datetime,
                 recorded_at: datetime, source_ref: dict) -> str:
    if event_kind not in p16_trials.KINDS - {"registration", "inventory_reconciliation"} \
            or not isinstance(source_ref, dict) or not source_ref:
        raise ValueError("invalid trial lifecycle event")
    registered = con.execute(f"SELECT event_at,recorded_at FROM {TABLE} "
                             "WHERE record_kind='registration' AND trial_id=?", [trial_id]).fetchone()
    if registered is None or p16_trials.timestamp(event_at) < registered[0] \
            or p16_trials.timestamp(recorded_at) < registered[1]:
        raise ValueError("trial event predates registration")
    if event_kind == "identity_verified":
        registration = p16_trials.decode(con.execute(
            f"SELECT * FROM {TABLE} WHERE record_kind='registration' AND trial_id=?",
            [trial_id]).fetchone())
        expected = canonical_sha256(registration["payload"]["registration_identity"])
        if (set(source_ref) != {"registration_identity_sha256", "evidence_sha256", "reason"}
                or source_ref["registration_identity_sha256"] != expected
                or not p16_trials.sha256_valid(source_ref["evidence_sha256"])
                or not source_ref["reason"]):
            raise ValueError("identity verification is invalid")
    source_sha = canonical_sha256(source_ref)
    row = p16_trials.encoded_record(
        event_kind, trial_id, event_at, recorded_at, {"source_ref": source_ref}, source_sha)
    owner = con.execute(f"SELECT trial_id,record_kind,record_sha256 FROM {TABLE} "
                        "WHERE source_sha256=? AND record_kind=?" + (
                            " LIMIT 1" if event_kind == "alias" else
                            " AND trial_id=? LIMIT 1"),
                        [source_sha, event_kind] + ([] if event_kind == "alias" else [trial_id])).fetchone()
    if owner is not None and owner[0] != trial_id:
        raise ValueError("one evidence alias cannot identify two trials")
    if owner is not None and owner[2] != row[0]:
        raise ValueError("trial event replay differs")
    return _append(con, row)


def record_reconciliation(con, *, recorded_at: datetime, reconciliation: dict) -> str:
    recorded = p16_trials.timestamp(recorded_at)
    records = _records(con, recorded)
    if not p16_trials.reconciliation_valid(reconciliation, records):
        raise ValueError("trial inventory reconciliation is invalid")
    return _append(con, p16_trials.encoded_record(
        "inventory_reconciliation", None, recorded_at, recorded_at, reconciliation, None))


def project(con, *, generated_at: datetime, limit: int = 100) -> dict:
    cutoff = p16_trials.timestamp(generated_at)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid trial projection limit")
    if not table_exists(con, TABLE):
        return {"status": "not_initialized", "inventory_complete": False,
                "selection_trial_count": 0, "registered_trial_count": 0,
                "execution_authority": "none"}
    return p16_trials.project(_records(con, cutoff), limit=limit)
