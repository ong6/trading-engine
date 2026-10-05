"""Append evidence-backed dispositions without rewriting original failed jobs.

Run under the normal single-writer connection: --job ID --kind cancelled|completed
--reason TEXT --evidence TEXT [--replacement-job ID]. Cancellation records an operator's
intentional stop; completion is an operator attestation backed by retained coverage evidence.
A later successful job with identical parameters is required but cannot alone prove that a
resumable job covered the original window or chunks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

from engine.lib import db
from engine.lib.util import table_exists

CLASSIFICATIONS = {
    "cancelled": "operator cancellation retained with evidence",
    "completed": "operator-attested completion; original failure retained",
}


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _job(con, job_id: int) -> dict:
    cursor = con.execute("SELECT * FROM jobs WHERE id=?", [job_id])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("job identity is absent or duplicated")
    return dict(zip((col[0] for col in cursor.description), rows[0], strict=True))


def _same_request(first: dict, second: dict) -> bool:
    try:
        first_params = json.loads(first["params"])
        second_params = json.loads(second["params"])
    except (TypeError, ValueError):
        return False
    return first["kind"] == second["kind"] and first_params == second_params


def record(con, *, job_id: int, kind: str, reason: str, evidence: str,
           replacement_job: int | None = None) -> dict:
    """Record one immutable disposition; an identical repeat is idempotent."""
    if kind not in CLASSIFICATIONS or not reason.strip() or not evidence.strip():
        raise ValueError("resolution needs kind, reason and retained evidence")
    source = _job(con, job_id)
    if source["state"] != "failed":
        raise ValueError("only a failed job can be resolved")
    replacement = None
    if kind == "completed":
        if replacement_job is None or replacement_job <= job_id:
            raise ValueError("completion needs a later successful replacement job")
        replacement = _job(con, replacement_job)
        if replacement["state"] != "done" or not _same_request(source, replacement):
            raise ValueError("replacement must be done with the same request parameters")
    elif replacement_job is not None:
        raise ValueError("cancellation cannot claim replacement completion")
    body = {"job_id": job_id, "job_sha256": _hash(source), "kind": kind,
            "reason": reason.strip(), "evidence": evidence.strip(),
            "replacement_job": replacement_job,
            "replacement_sha256": _hash(replacement) if replacement else None}
    digest = _hash(body)
    with db.transaction(con):
        con.execute("CREATE TABLE IF NOT EXISTS job_resolutions ("
                    "job_id BIGINT PRIMARY KEY, payload VARCHAR NOT NULL, "
                    "sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL)")
        old = con.execute("SELECT sha256 FROM job_resolutions WHERE job_id=?", [job_id]).fetchone()
        if old is not None and old[0] != digest:
            raise ValueError("job already has a different immutable resolution")
        if old is None:
            con.execute("INSERT INTO job_resolutions VALUES (?,?,?,?)",
                        [job_id, json.dumps(body, sort_keys=True), digest,
                         datetime.now(timezone.utc)])
    return body


def classifications(con) -> dict[int, str]:
    """Only still-valid evidence can classify a failure as resolved history."""
    if not table_exists(con, "job_resolutions"):
        return {}
    rows = con.execute("SELECT job_id,payload,sha256 FROM job_resolutions").fetchall()
    out = {}
    for job_id, raw, digest in rows:
        try:
            body = json.loads(raw)
            source = _job(con, job_id)
            valid = body["job_id"] == job_id and _hash(body) == digest
            valid = valid and source["state"] == "failed" and _hash(source) == body["job_sha256"]
            if body["kind"] == "completed":
                replacement = _job(con, body["replacement_job"])
                valid = (valid and replacement["state"] == "done" and _same_request(source, replacement)
                         and _hash(replacement) == body["replacement_sha256"])
            if valid and body["reason"].strip() and body["evidence"].strip():
                out[job_id] = CLASSIFICATIONS[body["kind"]]
        except (KeyError, TypeError, ValueError):
            continue  # Invalid evidence leaves the original failure actionable.
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    parser.add_argument("--job", required=True, type=int)
    parser.add_argument("--kind", required=True, choices=sorted(CLASSIFICATIONS))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--replacement-job", type=int)
    args = parser.parse_args()
    con = db.connect(args.db)
    try:
        result = record(con, job_id=args.job, kind=args.kind, reason=args.reason,
                        evidence=args.evidence, replacement_job=args.replacement_job)
    finally:
        con.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
