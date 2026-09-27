"""Append-only persistence adapter for the canonical P16 trial register."""
from __future__ import annotations

from datetime import datetime

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_trials

TABLE = "p16_trial_register_v4"


def init_schema(con) -> None:
    con.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        record_sha256 VARCHAR PRIMARY KEY, record_kind VARCHAR NOT NULL, trial_id VARCHAR,
        event_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL, source_sha256 VARCHAR,
        payload VARCHAR NOT NULL, append_sequence BIGINT NOT NULL UNIQUE,
        row_sha256 VARCHAR NOT NULL UNIQUE)""")


def _append(
    con, *, kind: str, trial_id: str | None, event_at: datetime,
    recorded_at: datetime, payload: dict, source_sha: str | None,
) -> str:
    probe = p16_trials.encoded_record(
        kind, trial_id, event_at, recorded_at, payload, source_sha, 1)
    existing = con.execute(
        f"SELECT * FROM {TABLE} WHERE record_sha256=?", [probe[0]]).fetchone()
    if existing is not None:
        p16_trials.decode(existing)
        expected = p16_trials.encoded_record(
            kind, trial_id, event_at, recorded_at, payload, source_sha, existing[-2])
        if existing != expected:
            raise ValueError("trial record replay differs")
        return existing[0]
    sequence = int(con.execute(
        f"SELECT COALESCE(MAX(append_sequence),0)+1 FROM {TABLE}").fetchone()[0])
    row = p16_trials.encoded_record(
        kind, trial_id, event_at, recorded_at, payload, source_sha, sequence)
    con.execute(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?,?,?)", row)
    return row[0]


def _records(con, cutoff: datetime | None = None, *,
             through_sequence: int | None = None) -> list[dict]:
    clauses, values = [], []
    if cutoff is not None:
        clauses.append("recorded_at<=?")
        values.append(cutoff)
    if through_sequence is not None:
        clauses.append("append_sequence<=?")
        values.append(through_sequence)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = con.execute(
        f"SELECT * FROM {TABLE}{where} ORDER BY append_sequence", values).fetchall()
    return [p16_trials.decode(row) for row in rows]


def registration_as_of(con, *, trial_id: str, generated_at: datetime) -> dict | None:
    """Return a validated registration visible at the requested instant."""
    if not p16_trials.sha256_valid(trial_id):
        raise ValueError("trial ID is invalid")
    if not table_exists(con, TABLE):
        return None
    cutoff = p16_trials.timestamp(generated_at)
    row = con.execute(
        f"SELECT * FROM {TABLE} WHERE record_kind='registration' "
        "AND trial_id=? AND recorded_at<=?", [trial_id, cutoff],
    ).fetchone()
    return None if row is None else p16_trials.decode(row)


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
    if existing is not None:
        decoded = p16_trials.decode(existing)
        if (decoded["event_at"] != payload["registered_at"]
                or decoded["recorded_at"] != recorded.isoformat()
                or decoded["payload"] != payload):
            raise ValueError("trial registration replay differs")
        return decoded["trial_id"]
    visible = {item["trial_id"] for item in _records(con, recorded)
               if item["record_kind"] == "registration"
               and item["event_at"] <= payload["registered_at"]}
    if not set(parent_trial_ids) <= visible:
        raise ValueError("trial parent is not registered")
    _append(
        con, kind="registration", trial_id=trial_id, event_at=registered_at,
        recorded_at=recorded_at, payload=payload, source_sha=None)
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
    payload = {"source_ref": source_ref}
    record_sha = p16_trials.encoded_record(
        event_kind, trial_id, event_at, recorded_at, payload, source_sha, 1)[0]
    owner = con.execute(f"SELECT trial_id,record_kind,record_sha256 FROM {TABLE} "
                        "WHERE source_sha256=? AND record_kind=?" + (
                            " LIMIT 1" if event_kind == "alias" else
                            " AND trial_id=? LIMIT 1"),
                        [source_sha, event_kind] + ([] if event_kind == "alias" else [trial_id])).fetchone()
    if owner is not None and owner[0] != trial_id:
        raise ValueError("one evidence alias cannot identify two trials")
    if owner is not None and owner[2] != record_sha:
        raise ValueError("trial event replay differs")
    return _append(
        con, kind=event_kind, trial_id=trial_id, event_at=event_at,
        recorded_at=recorded_at, payload=payload, source_sha=source_sha)


def record_reconciliation(con, *, recorded_at: datetime, reconciliation: dict) -> str:
    recorded = p16_trials.timestamp(recorded_at)
    future = con.execute(
        f"SELECT 1 FROM {TABLE} WHERE recorded_at>? LIMIT 1", [recorded],
    ).fetchone()
    if future is not None:
        raise ValueError("trial reconciliation predates an appended record")
    records = _records(con, recorded)
    if not p16_trials.reconciliation_valid(reconciliation, records):
        raise ValueError("trial inventory reconciliation is invalid")
    return _append(
        con, kind="inventory_reconciliation", trial_id=None, event_at=recorded_at,
        recorded_at=recorded_at, payload=reconciliation, source_sha=None)


def project_sealed(con, *, reconciliation_sha256: str, limit: int = 100) -> dict:
    """Project the immutable prefix named by one exact reconciliation record."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid trial projection limit")
    row = con.execute(
        f"SELECT * FROM {TABLE} WHERE record_sha256=?",
        [reconciliation_sha256],
    ).fetchone()
    if row is None:
        raise ValueError("trial reconciliation is absent")
    reconciliation = p16_trials.decode(row)
    if reconciliation["record_kind"] != "inventory_reconciliation":
        raise ValueError("trial reconciliation identity differs")
    bound = reconciliation["payload"].get("sealed_through_sequence")
    records = _records(con, through_sequence=bound)
    return p16_trials.project([*records, reconciliation], limit=limit)


def project(con, *, generated_at: datetime, limit: int = 100) -> dict:
    cutoff = p16_trials.timestamp(generated_at)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid trial projection limit")
    if not table_exists(con, TABLE):
        return {"status": "not_initialized", "inventory_complete": False,
                "selection_trial_count": 0, "selection_trial_ids": [],
                "registered_trial_count": 0,
                "execution_authority": "none"}
    return p16_trials.project(_records(con, cutoff), limit=limit)
