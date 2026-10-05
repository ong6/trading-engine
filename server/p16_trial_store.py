"""Append-only persistence adapter for the canonical P16 trial register."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT
from engine.lib.util import table_exists
from farm import p16_trials

TABLE = "p16_trial_register_v4"
CENSUS_PATH = REPO_ROOT / "docs" / "p16-trial-census.json"
CENSUS_RECORDED_AT = datetime(2026, 9, 28, 7, 12, 29, tzinfo=timezone.utc)
CENSUS_FIELDS = {
    "policy_id", "policy_version", "plan_id", "family", "hypothesis", "trial_kind",
    "evidence_class", "registration_identity", "identity_status", "parent_trial_ids",
    "registered_at", "first_evaluated_at", "retired_at", "status", "evaluation_window",
    "outcome", "n_contribution", "alias_references", "source", "confidence",
    "reconciliation_note",
}
CENSUS_STATUSES = {"registered", "evaluation_started", "evaluated", "retired", "abandoned"}


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
             identity_status: str = "verified", trial_kind: str = "policy",
             n_contribution: int = 1) -> str:
    trial_id, payload = p16_trials.registration(
        policy_id=policy_id, policy_version=policy_version, plan_id=plan_id,
        registration_identity=registration_identity, evidence_class=evidence_class,
        trial_kind=trial_kind,
        parent_trial_ids=parent_trial_ids, registered_at=registered_at,
        identity_status=identity_status, n_contribution=n_contribution)
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


def _census_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("trial census timestamp is invalid")
    match = re.match(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?", value)
    if match is None:
        raise ValueError("trial census timestamp is invalid")
    parsed = datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))
    return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else
            parsed.astimezone(timezone.utc))


def _census_rows(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("trial census is invalid") from exc
    if (not isinstance(rows, list) or not rows
            or any(not isinstance(row, dict) or not CENSUS_FIELDS <= set(row)
                   or not set(row) <= CENSUS_FIELDS | {"cell_count"}
                   or row["plan_id"] not in p16_trials.PLANS
                   or row["status"] not in CENSUS_STATUSES
                   or row["identity_status"] not in {"verified", "provisional"}
                   or set(row["registration_identity"]) != p16_trials.IDENTITY_FIELDS
                   or type(row["n_contribution"]) is not int or row["n_contribution"] < 0
                   or not isinstance(row["parent_trial_ids"], list)
                   or not isinstance(row["alias_references"], list)
                   for row in rows)):
        raise ValueError("trial census is invalid")
    return rows, hashlib.sha256(raw).hexdigest()


def _existing_census(con, snapshot_sha256: str) -> dict | None:
    for row in reversed(_records(con)):
        if row["record_kind"] != "inventory_reconciliation":
            continue
        sources = [item for item in row["payload"].get("sources", [])
                   if str(item.get("source", "")).startswith("census:")]
        if sources and all(item.get("snapshot_sha256") == snapshot_sha256 for item in sources):
            return project_sealed(con, reconciliation_sha256=row["record_sha256"])
    return None


def _resolve_census_parent(by_policy: dict, reference: str, child: dict) -> str | None:
    candidates = [item for item in by_policy.get(reference, ()) if item is not child]
    if len(candidates) == 1:
        return candidates[0]["trial_id"]
    active = [item for item in candidates if item["source"]["retired_at"] is None]
    if len(active) == 1:
        return active[0]["trial_id"]
    for policy_id, options in by_policy.items():
        prefix = f"{policy_id} "
        if reference.startswith(prefix):
            version = reference.removeprefix(prefix)
            matches = [
                item for item in options if item["source"]["policy_version"].startswith(version)
            ]
            if len(matches) == 1:
                return matches[0]["trial_id"]
    return None



def load_census(con, *, path: Path = CENSUS_PATH) -> dict:
    """Load the accepted historical census and seal its exact trial contribution."""
    init_schema(con)
    rows, snapshot_sha = _census_rows(Path(path))
    existing = _existing_census(con, snapshot_sha)
    if existing is not None:
        return existing

    prepared, by_policy = [], defaultdict(list)
    for row in rows:
        registered = (_census_time(row["registered_at"])
                      or _census_time(row["first_evaluated_at"])
                      or _census_time(row["retired_at"]) or CENSUS_RECORDED_AT)
        trial_id, _payload = p16_trials.registration(
            policy_id=row["policy_id"], policy_version=row["policy_version"],
            plan_id=row["plan_id"], registration_identity=row["registration_identity"],
            evidence_class=row["evidence_class"], trial_kind=row["trial_kind"],
            parent_trial_ids=[], registered_at=registered,
            identity_status=row["identity_status"], n_contribution=row["n_contribution"],
        )
        item = {"source": row, "registered_at": registered, "trial_id": trial_id}
        prepared.append(item)
        by_policy[row["policy_id"]].append(item)
    if len({item["trial_id"] for item in prepared}) != len(rows):
        raise ValueError("trial census identity is duplicated")

    for item in prepared:
        item["parent_trial_ids"] = sorted(filter(None, (
            _resolve_census_parent(by_policy, reference, item)
            for reference in item["source"]["parent_trial_ids"]
        )))
    pending, loaded = list(prepared), set()
    while pending:
        ready = [item for item in pending if set(item["parent_trial_ids"]) <= loaded]
        if not ready:
            raise ValueError("trial census parent graph is invalid")
        for item in sorted(ready, key=lambda value: (
                value["registered_at"], value["source"]["policy_id"],
                value["source"]["policy_version"])):
            row = item["source"]
            register(
                con, policy_id=row["policy_id"], policy_version=row["policy_version"],
                plan_id=row["plan_id"], registration_identity=row["registration_identity"],
                evidence_class=row["evidence_class"], trial_kind=row["trial_kind"],
                parent_trial_ids=item["parent_trial_ids"], registered_at=item["registered_at"],
                recorded_at=CENSUS_RECORDED_AT, identity_status=row["identity_status"],
                n_contribution=row["n_contribution"],
            )
            source_ref = {"census": row}
            record_event(
                con, item["trial_id"], "alias", event_at=item["registered_at"],
                recorded_at=CENSUS_RECORDED_AT, source_ref=source_ref,
            )
            row_sha = canonical_sha256(row)
            first = _census_time(row["first_evaluated_at"]) or item["registered_at"]
            first = max(first, item["registered_at"])
            if row["status"] in {"evaluation_started", "evaluated", "abandoned", "retired"}:
                kind = "evaluated" if row["status"] == "retired" else row["status"]
                record_event(
                    con, item["trial_id"], kind, event_at=first,
                    recorded_at=CENSUS_RECORDED_AT,
                    source_ref={"census_row_sha256": row_sha, "lifecycle": kind,
                                "outcome": row["outcome"]},
                )
            if row["status"] == "retired":
                retired = max(_census_time(row["retired_at"]) or first, first)
                record_event(
                    con, item["trial_id"], "retired", event_at=retired,
                    recorded_at=CENSUS_RECORDED_AT,
                    source_ref={"census_row_sha256": row_sha, "lifecycle": "retired"},
                )
            pending.remove(item)
            loaded.add(item["trial_id"])

    records = _records(con, CENSUS_RECORDED_AT)
    entries = [{"source": f"census:{item['source']['plan_id']}",
                "source_key_sha256": canonical_sha256({"census": item["source"]}),
                "trial_id": item["trial_id"], "disposition": "alias",
                "reason": None} for item in prepared]
    attempted_baselines = sorted(
        item["trial_id"] for item in prepared
        if item["source"]["trial_kind"] == "deterministic_baseline"
        and item["source"]["status"] != "registered"
    )
    reconciliation = {
        "scope": "all_plans_and_deterministic_baselines_through_p16",
        "covered_plans": sorted(p16_trials.PLANS),
        "deterministic_baseline_trial_ids": attempted_baselines,
        "sources": [{"source": f"census:{plan_id}", "plan_id": plan_id,
                     "row_count": sum(row["plan_id"] == plan_id for row in rows),
                     "snapshot_sha256": snapshot_sha}
                    for plan_id in sorted(p16_trials.PLANS)],
        "entries": entries, "trial_redirects": {},
        "register_sha256": p16_trials.register_digest(records),
        "sealed_through_sequence": max(row["append_sequence"] for row in records),
        "sealed_row_sha256s": sorted(row["row_sha256"] for row in records),
    }
    reconciliation_sha = record_reconciliation(
        con, recorded_at=CENSUS_RECORDED_AT, reconciliation=reconciliation,
    )
    return project_sealed(con, reconciliation_sha256=reconciliation_sha)
