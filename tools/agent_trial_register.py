"""Bounded, read-only register of every observed agent policy version."""
from __future__ import annotations

import json
from datetime import datetime

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

LIMIT = 100


def project(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> dict:
    rows, total, selection_trials, digest = [], 0, 0, "0" * 64
    cutoff = generated_at.replace(tzinfo=None)

    def add(record: dict, counts: bool = True) -> None:
        nonlocal total, selection_trials, digest
        record["counts_as_selection_trial"] = counts
        total += 1
        selection_trials += counts
        digest = canonical_sha256({"previous": digest, "version": record})
        if len(rows) < LIMIT:
            rows.append(record)

    queries = []
    if table_exists(con, "agent_evaluation_traces"):
        queries.append((
            "canonical_trace",
            "SELECT policy_id,model,model_version,instructions_sha256,toolset_sha256,"
            "model_catalog_entry_sha256,proxy_source_sha256,traecli_runtime,"
            "upstream_model_family,COUNT(*),MIN(observed_at),MAX(observed_at) "
            "FROM agent_evaluation_traces WHERE observed_at<=? GROUP BY 1,2,3,4,5,6,7,8,9 "
            "ORDER BY 1,2,3,4,5,6,7,8,9",
        ))
    for evidence_class, query in queries:
        cursor = con.execute(query, [cutoff])
        while batch := cursor.fetchmany(LIMIT):
            for row in batch:
                add({"policy_id": row[0], "evidence_class": evidence_class,
                     "identity": list(row[1:9]), "observation_count": int(row[9]),
                     "first_observed_at": row[10].isoformat(),
                     "last_observed_at": row[11].isoformat()})
    if table_exists(con, "agent_shadow_attempts"):
        cursor = con.execute(
            "SELECT policy_id,policy_registration_sha256,COUNT(*) FROM agent_shadow_attempts "
            "WHERE started_at<=? GROUP BY 1,2 ORDER BY 1,2", [cutoff])
        while batch := cursor.fetchmany(LIMIT):
            for row in batch:
                add({"policy_id": row[0] or "legacy_unregistered",
                     "evidence_class": "shadow_attempt", "identity": [row[1]],
                     "observation_count": int(row[2])})
    def response_identity(raw, status):
        if raw is None:
            return ("no_model_call", status)
        payload = json.loads(raw)
        return tuple(payload.get(key) for key in (
            "model", "model_version", "proxy_version", "proxy_source_sha256",
            "traecli_runtime", "upstream_model_family", "model_catalog_entry_sha256",
        ))

    if table_exists(con, "p15_preopen_runs"):
        grouped = {}
        for policy, status, response in con.execute(
            "SELECT policy_id,status,response_payload FROM p15_preopen_runs "
            "WHERE started_at<=? ORDER BY id", [cutoff]
        ).fetchall():
            key = (policy, response_identity(response, status))
            grouped[key] = grouped.get(key, 0) + 1
        for (policy, identity), count in sorted(grouped.items()):
            add({"policy_id": policy, "evidence_class": "preopen",
                 "identity": list(identity), "observation_count": count},
                counts=identity[0] != "no_model_call")
    if table_exists(con, "p15_event_windows"):
        grouped = {}
        for window_id, status, response in con.execute(
            "SELECT w.window_id,c.status,c.response_payload FROM p15_event_windows w "
            "LEFT JOIN p15_event_calls c USING(window_id) WHERE w.observed_at<=? ORDER BY w.id",
            [cutoff],
        ).fetchall():
            policy = window_id.split(":", 1)[0]
            key = (policy, response_identity(response, status or "no_call"))
            grouped[key] = grouped.get(key, 0) + 1
        for (policy, identity), count in sorted(grouped.items()):
            add({"policy_id": policy, "evidence_class": "event_shadow",
                 "identity": list(identity), "observation_count": count},
                counts=identity[0] != "no_model_call")
    if all(table_exists(con, table) for table in ("p15_book_contracts", "p15_book_windows")):
        for row in con.execute(
            "SELECT c.portfolio_id,c.mechanics_version,c.config_sha256,COUNT(w.market_date) "
            "FROM p15_book_contracts c JOIN p15_book_windows w USING(portfolio_id) "
            "WHERE w.completed_at<=? GROUP BY 1,2,3 ORDER BY 1", [cutoff]
        ).fetchmany(LIMIT):
            add({"policy_id": row[0], "evidence_class": "comparator_book",
                 "identity": [row[1], row[2]], "observation_count": int(row[3])},
                counts=row[0] != "p15_rule_control")
    return {"status": "capturing" if total else "waiting", "version_count": total,
            "returned_version_count": len(rows), "versions_truncated": len(rows) < total,
            "selection_trial_count": selection_trials, "versions": rows,
            "register_sha256": digest}
