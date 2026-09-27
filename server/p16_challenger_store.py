"""Append-only P16 challenger runs, attempts, receipts, and outputs."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

TABLES = {
    "p16_challenger_runs", "p16_challenger_attempts",
    "p16_challenger_receipts", "p16_challenger_outputs",
}
NUMERIC_SCORES = ("p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("P16 challenger times require an explicit timezone")
    return value.astimezone(timezone.utc)


def _hash(value: object, field: str = "P16 identity") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a full hash")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"{field} is invalid")
    return value


def init_schema(con) -> None:
    for table in sorted(TABLES):
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "record_id VARCHAR PRIMARY KEY, parent_id VARCHAR NOT NULL, "
            "recorded_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, "
            "row_sha256 VARCHAR NOT NULL UNIQUE)"
        )


def _decode(row: tuple) -> dict:
    record_id, parent, stamp, raw, digest = row
    try:
        body = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retained P16 challenger evidence is invalid") from exc
    if (
        canonical_sha256(body) != digest
        or canonical_sha256(body.get("key")) != record_id
        or body.get("parent_id") != parent
        or body.get("recorded_at") != stamp.replace(tzinfo=timezone.utc).isoformat()
    ):
        raise ValueError("retained P16 challenger evidence differs")
    return {**body, "record_id": record_id, "row_sha256": digest}


def get(con, table: str, record_id: str) -> dict | None:
    if table not in TABLES:
        raise ValueError("unknown P16 challenger record table")
    if not table_exists(con, table):
        return None
    row = con.execute(
        f"SELECT * FROM {table} WHERE record_id=?", [record_id]).fetchone()
    return None if row is None else _decode(row)


def _put(
    con, table: str, *, key: dict, parent: str, payload: dict,
    recorded_at: datetime,
) -> dict:
    if table not in TABLES or not isinstance(key, dict) or not key \
            or not isinstance(payload, dict):
        raise ValueError("invalid P16 challenger record")
    record_id, stamp = canonical_sha256(key), _utc(recorded_at)
    existing = get(con, table, record_id)
    if existing is not None:
        if (
            existing["key"] != key or existing["parent_id"] != parent
            or existing["data"] != payload
            or existing["recorded_at"] != stamp.isoformat()
        ):
            raise ValueError("P16 challenger immutable record replay differs")
        return existing
    body = {
        "key": key, "parent_id": parent,
        "recorded_at": stamp.isoformat(), "data": payload,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = canonical_sha256(body)
    con.execute(
        f"INSERT INTO {table} VALUES (?,?,?,?,?)",
        [record_id, parent, stamp.replace(tzinfo=None), raw, digest],
    )
    return {**body, "record_id": record_id, "row_sha256": digest}


def start_run(
    con, *, registration_sha256: str, family_id: str, policy_id: str,
    policy_sha256: str, window_id: str, market_date: date,
    information_cutoff_at: datetime, started_at: datetime, tickers: list[str],
    source_identity: dict, treatment_id: str,
    model_contract_sha256: str | None,
) -> dict:
    cutoff, started = _utc(information_cutoff_at), _utc(started_at)
    if (
        not isinstance(market_date, date) or isinstance(market_date, datetime)
        or cutoff > started or not tickers or len(set(tickers)) != len(tickers)
        or any(not isinstance(ticker, str) or not ticker for ticker in tickers)
        or not isinstance(source_identity, dict) or not source_identity
    ):
        raise ValueError("invalid P16 challenger run inputs")
    if model_contract_sha256 is not None:
        _hash(model_contract_sha256, "model contract")
    registration = _hash(registration_sha256, "registration identity")
    key = {
        "registration_sha256": registration,
        "family_id": _text(family_id, "family ID"),
        "policy_id": _text(policy_id, "policy ID"),
        "policy_sha256": _hash(policy_sha256, "policy identity"),
        "window_id": _text(window_id, "window ID"),
    }
    data = {
        "market_date": market_date.isoformat(),
        "information_cutoff_at": cutoff.isoformat(),
        "tickers": tickers,
        "source_identity": source_identity,
        "source_identity_sha256": canonical_sha256(source_identity),
        "treatment_id": _text(treatment_id, "treatment ID"),
        "model_contract_sha256": model_contract_sha256,
    }
    return _put(
        con, "p16_challenger_runs", key=key, parent=registration,
        payload=data, recorded_at=started,
    )


def start_attempt(
    con, run_id: str, *, chunk_index: int, sample_index: int,
    request_payload: dict, treatment: dict, started_at: datetime,
) -> dict:
    run = get(con, "p16_challenger_runs", run_id)
    if (
        run is None or run["data"]["model_contract_sha256"] is None
        or any(type(index) is not int or index < 0 for index in (chunk_index, sample_index))
        or not isinstance(request_payload, dict) or not request_payload
        or not isinstance(treatment, dict) or not treatment
        or _utc(started_at) < datetime.fromisoformat(run["recorded_at"])
    ):
        raise ValueError("invalid or uncatalogued P16 challenger attempt")
    key = {"run_id": run_id, "chunk_index": chunk_index, "sample_index": sample_index}
    data = {
        "request": request_payload,
        "request_sha256": canonical_sha256(request_payload),
        "treatment": treatment,
        "treatment_sha256": canonical_sha256(treatment),
        "model_contract_sha256": run["data"]["model_contract_sha256"],
    }
    return _put(
        con, "p16_challenger_attempts", key=key, parent=run_id,
        payload=data, recorded_at=started_at,
    )


def finish_attempt(
    con, attempt_id: str, *, status: str, receipt: dict,
    completed_at: datetime, reason: str | None = None,
) -> dict:
    attempt = get(con, "p16_challenger_attempts", attempt_id)
    if (
        attempt is None or status not in {"available", "unavailable"}
        or _utc(completed_at) < datetime.fromisoformat(attempt["recorded_at"])
        or not isinstance(receipt, dict)
        or (status == "unavailable" and (not isinstance(reason, str) or not reason))
    ):
        raise ValueError("invalid P16 challenger attempt completion")
    request = attempt["data"]["request"]
    if (
        receipt.get("request") != request
        or receipt.get("request_sha256") != canonical_sha256(request)
    ):
        raise ValueError("P16 challenger response belongs to a different request")
    response = receipt.get("response")
    if response is not None \
            and canonical_sha256(response) != receipt.get("response_sha256"):
        raise ValueError("P16 challenger raw response identity differs")
    if status == "available" and (
        not isinstance(response, dict) or not isinstance(receipt.get("output"), dict)
        or receipt.get("model_contract_sha256")
        != attempt["data"]["model_contract_sha256"]
    ):
        raise ValueError("P16 successful receipt lacks its model or response binding")
    return _put(
        con, "p16_challenger_receipts", key={"attempt_id": attempt_id},
        parent=attempt_id,
        payload={
            "attempt_sha256": attempt["row_sha256"], "status": status,
            "receipt": receipt, "reason": reason,
        },
        recorded_at=completed_at,
    )


def finish_run(
    con, run_id: str, *, rows: list[dict], completed_at: datetime,
    dependency_output_ids: list[str] | None = None, reason: str | None = None,
) -> dict:
    run = get(con, "p16_challenger_runs", run_id)
    if run is None or _utc(completed_at) < datetime.fromisoformat(run["recorded_at"]):
        raise ValueError("P16 challenger run is unavailable or completion predates it")
    if not isinstance(rows, list):
        raise ValueError("P16 challenger output is invalid")
    names = [row.get("ticker") for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or len(set(names)) != len(names) \
            or set(names) != set(run["data"]["tickers"]):
        raise ValueError("P16 challenger output must preserve every frozen candidate")
    for row in rows:
        values = [row.get(field) for field in NUMERIC_SCORES]
        if row.get("scoring_status") == "available":
            if (
                any(isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) for value in values)
                or not 0 <= values[0] <= 1
                or any(abs(value) > 10_000 for value in values[1:])
            ):
                raise ValueError("invalid P16 available score")
        elif row.get("scoring_status") != "unavailable" \
                or any(value is not None for value in values):
            raise ValueError("unavailable P16 scores must stay explicitly null")

    receipts = []
    if table_exists(con, "p16_challenger_attempts"):
        attempts = con.execute(
            "SELECT * FROM p16_challenger_attempts WHERE parent_id=? ORDER BY record_id",
            [run_id],
        ).fetchall()
        for raw in attempts:
            attempt = _decode(raw)
            receipt_id = canonical_sha256({"attempt_id": attempt["record_id"]})
            receipt = get(con, "p16_challenger_receipts", receipt_id)
            if receipt is None or datetime.fromisoformat(receipt["recorded_at"]) > _utc(completed_at):
                raise ValueError("P16 challenger run has an unresolved or future receipt")
            if receipt["parent_id"] != attempt["record_id"] \
                    or receipt["data"]["attempt_sha256"] != attempt["row_sha256"]:
                raise ValueError("P16 challenger receipt no longer binds its attempt")
            receipts.append({
                "attempt_id": attempt["record_id"],
                "receipt_sha256": receipt["row_sha256"],
            })

    dependencies = dependency_output_ids or []
    if dependencies != sorted(set(dependencies)):
        raise ValueError("P16 challenger output dependencies are invalid")
    dependency_rows = [get(con, "p16_challenger_outputs", item) for item in dependencies]
    if any(item is None or item["parent_id"] != run["parent_id"]
           for item in dependency_rows):
        raise ValueError("P16 challenger output dependency differs")
    unavailable = sum(row["scoring_status"] == "unavailable" for row in rows)
    if run["data"]["model_contract_sha256"] is not None and not receipts \
            and (unavailable != len(rows) or not reason):
        raise ValueError("uncalled P16 model run requires explicit unavailability")
    data = {
        "run_sha256": run["row_sha256"],
        "rows": sorted(rows, key=lambda row: row["ticker"]),
        "attempt_sources": receipts,
        "dependency_output_ids": dependencies,
        "candidate_count": len(rows), "unavailable_count": unavailable,
        "reason": reason, "execution_authority": "none",
    }
    return _put(
        con, "p16_challenger_outputs", key={"run_id": run_id}, parent=run["parent_id"],
        payload=data, recorded_at=completed_at,
    )


def output_for_run(con, run_id: str) -> dict | None:
    return get(
        con, "p16_challenger_outputs", canonical_sha256({"run_id": run_id}))
