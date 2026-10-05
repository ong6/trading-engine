"""Append-only P16 challenger runs, attempts, receipts, and outputs."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from server import p16_store, p16_trial_store

TABLES = {
    "p16_challenger_runs", "p16_challenger_attempts",
    "p16_challenger_receipts", "p16_challenger_outputs",
}
NUMERIC_SCORES = ("p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")
ACTIONS = {"ignore", "watch", "buy_candidate", "exit"}
RUN_MODES = {"prospective", "dry_run", "development", "lockbox"}
ENSEMBLE_COMPONENT_POLICIES = (
    "c-model-gpt-5.5-max", "c-model-gpt-5.6-terra-max",
)


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
    p16_store.init_schema(con)
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


def _validated_attempt_manifest(attempt_manifest, model_contract_sha256, tickers) -> list[dict]:
    manifest = []
    for item in attempt_manifest:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "chunk_index",
                "sample_index",
                "source_request_sha256",
                "source_input_sha256",
                "source_tickers",
            }
            or any(
                type(item[key]) is not int or item[key] < 0
                for key in ("chunk_index", "sample_index")
            )
            or not isinstance(item["source_tickers"], list)
            or item["source_tickers"] != sorted(set(item["source_tickers"]))
            or not item["source_tickers"]
            or any(not isinstance(ticker, str) or not ticker for ticker in item["source_tickers"])
        ):
            raise ValueError("invalid P16 challenger attempt manifest")
        _hash(item["source_request_sha256"], "source request identity")
        _hash(item["source_input_sha256"], "source input identity")
        manifest.append(dict(item))
    manifest.sort(key=lambda item: (item["chunk_index"], item["sample_index"]))
    pairs = [(item["chunk_index"], item["sample_index"]) for item in manifest]
    if (
        len(pairs) != len(set(pairs))
        or (model_contract_sha256 is None and manifest)
        or (model_contract_sha256 is not None and not manifest)
    ):
        raise ValueError("invalid P16 challenger attempt manifest")
    if manifest:
        chunk_tickers = {}
        for item in manifest:
            existing_tickers = chunk_tickers.setdefault(item["chunk_index"], item["source_tickers"])
            if existing_tickers != item["source_tickers"]:
                raise ValueError("invalid P16 challenger attempt manifest")
        flattened = [ticker for names in chunk_tickers.values() for ticker in names]
        if len(flattened) != len(set(flattened)) or set(flattened) != set(tickers):
            raise ValueError("invalid P16 challenger attempt manifest")
    return manifest


def start_run(
    con, *, registration_sha256: str, family_id: str, policy_id: str,
    trial_id: str, window_id: str, market_date: date, run_mode: str,
    information_cutoff_at: datetime, started_at: datetime, tickers: list[str],
    source_identity: dict, treatment_id: str,
    model_contract_sha256: str | None, attempt_manifest: list[dict],
    dependency_policy_ids: list[str],
) -> dict:
    cutoff, started = _utc(information_cutoff_at), _utc(started_at)
    if (
        not isinstance(market_date, date) or isinstance(market_date, datetime)
        or cutoff > started or not tickers or len(set(tickers)) != len(tickers)
        or any(not isinstance(ticker, str) or not ticker for ticker in tickers)
        or not isinstance(source_identity, dict) or not source_identity
        or run_mode not in RUN_MODES or not isinstance(attempt_manifest, list)
        or not isinstance(dependency_policy_ids, list)
    ):
        raise ValueError("invalid P16 challenger run inputs")
    if model_contract_sha256 is not None:
        _hash(model_contract_sha256, "model contract")
    manifest = _validated_attempt_manifest(attempt_manifest, model_contract_sha256, tickers)
    dependencies = sorted(dependency_policy_ids)
    if (dependencies != sorted(set(dependencies))
            or (policy_id == "c-ensemble"
                and dependencies != sorted(ENSEMBLE_COMPONENT_POLICIES))
            or (policy_id != "c-ensemble" and dependencies)):
        raise ValueError("invalid P16 challenger dependency policy set")
    registration = _hash(registration_sha256, "registration identity")
    trial = p16_trial_store.registration_as_of(
        con, trial_id=_hash(trial_id, "trial identity"), generated_at=started,
    )
    if (trial is None or trial["payload"].get("policy_id") != policy_id
            or trial["payload"].get("trial_kind") != "policy"
            or trial["payload"].get("identity_status") != "verified"
            or (run_mode == "prospective"
                and trial["payload"].get("evidence_class") != "prospective")):
        raise ValueError("P16 challenger trial identity differs")
    key = {
        "registration_sha256": registration,
        "family_id": _text(family_id, "family ID"),
        "policy_id": _text(policy_id, "policy ID"),
        "trial_id": trial_id,
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
        "attempt_manifest": manifest,
        "dependency_policy_ids": dependencies,
        "run_mode": run_mode,
    }
    result = _put(
        con, "p16_challenger_runs", key=key, parent=registration,
        payload=data, recorded_at=started,
    )
    if run_mode != "dry_run":
        event_at = datetime.fromisoformat(result["recorded_at"])
        p16_trial_store.record_event(
            con, trial_id, "evaluation_started", event_at=event_at,
            recorded_at=event_at, source_ref={
                "p16_challenger_run_sha256": result["row_sha256"],
                "registration_sha256": registration,
            },
        )
    return result


def start_attempt(
    con, run_id: str, *, chunk_index: int, sample_index: int,
    request_payload: dict, treatment: dict, started_at: datetime,
) -> dict:
    run = get(con, "p16_challenger_runs", run_id)
    if (
        run is None or run["data"]["model_contract_sha256"] is None
        or output_for_run(con, run_id) is not None
        or any(type(index) is not int or index < 0 for index in (chunk_index, sample_index))
        or not isinstance(request_payload, dict) or not request_payload
        or not isinstance(treatment, dict) or not treatment
        or _utc(started_at) < datetime.fromisoformat(run["recorded_at"])
    ):
        raise ValueError("invalid or uncatalogued P16 challenger attempt")
    manifest = {(item["chunk_index"], item["sample_index"]): item
                for item in run["data"].get("attempt_manifest", [])}
    expected = manifest.get((chunk_index, sample_index))
    if (expected is None
            or treatment.get("original_sha256") != expected["source_input_sha256"]):
        raise ValueError("P16 challenger attempt differs from its frozen source grid")
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


def _validate_output_rows(rows: list[dict]) -> None:
    for row in rows:
        values = [row.get(field) for field in NUMERIC_SCORES]
        if row.get("scoring_status") == "available":
            if (
                any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in values
                )
                or not 0 <= values[0] <= 1
                or any(abs(value) > 10_000 for value in values[1:])
                or row.get("action") not in ACTIONS
                or any(
                    not isinstance(row.get(field), str)
                    or not row[field].strip()
                    or len(row[field]) > 1_000
                    for field in ("thesis", "invalidation")
                )
                or not isinstance(row.get("evidence_ids"), list)
                or not row["evidence_ids"]
                or len(row["evidence_ids"]) != len(set(row["evidence_ids"]))
                or any(not isinstance(value, str) or not value for value in row["evidence_ids"])
            ):
                raise ValueError("invalid P16 available output")
        elif (
            row.get("scoring_status") != "unavailable"
            or any(value is not None for value in values)
            or row.get("action") != "unavailable"
            or row.get("thesis") is not None
            or row.get("invalidation") is not None
            or not isinstance(row.get("unavailable_reason"), str)
            or not row["unavailable_reason"].strip()
            or not isinstance(row.get("evidence_ids"), list)
            or not row["evidence_ids"]
        ):
            raise ValueError("unavailable P16 output must stay explicitly null")



def _validated_run_receipts(
    con, run_id: str, run: dict, rows: list[dict], completed_at: datetime
) -> list[dict]:
    receipts = []
    statuses = {}
    attempt_pairs = []
    if table_exists(con, "p16_challenger_attempts"):
        attempts = con.execute(
            "SELECT * FROM p16_challenger_attempts WHERE parent_id=? ORDER BY record_id",
            [run_id],
        ).fetchall()
        for raw in attempts:
            attempt = _decode(raw)
            attempt_pairs.append((attempt["key"]["chunk_index"], attempt["key"]["sample_index"]))
            receipt_id = canonical_sha256({"attempt_id": attempt["record_id"]})
            receipt = get(con, "p16_challenger_receipts", receipt_id)
            if receipt is None or datetime.fromisoformat(receipt["recorded_at"]) > _utc(
                completed_at
            ):
                raise ValueError("P16 challenger run has an unresolved or future receipt")
            if (
                receipt["parent_id"] != attempt["record_id"]
                or receipt["data"]["attempt_sha256"] != attempt["row_sha256"]
            ):
                raise ValueError("P16 challenger receipt no longer binds its attempt")
            receipts.append(
                {
                    "attempt_id": attempt["record_id"],
                    "receipt_sha256": receipt["row_sha256"],
                    "status": receipt["data"]["status"],
                }
            )
            statuses[(attempt["key"]["chunk_index"], attempt["key"]["sample_index"])] = receipt[
                "data"
            ]["status"]
    expected_pairs = [
        (item["chunk_index"], item["sample_index"])
        for item in run["data"].get("attempt_manifest", [])
    ]
    if sorted(attempt_pairs) != expected_pairs:
        raise ValueError("P16 challenger attempt grid is incomplete")
    output_by_ticker = {row["ticker"]: row["scoring_status"] for row in rows}
    for chunk_index in sorted(
        {item["chunk_index"] for item in run["data"].get("attempt_manifest", [])}
    ):
        manifest_rows = [
            item for item in run["data"]["attempt_manifest"] if item["chunk_index"] == chunk_index
        ]
        expected_status = (
            "available"
            if all(
                statuses[(item["chunk_index"], item["sample_index"])] == "available"
                for item in manifest_rows
            )
            else "unavailable"
        )
        if any(
            output_by_ticker[ticker] != expected_status
            for ticker in manifest_rows[0]["source_tickers"]
        ):
            raise ValueError("P16 challenger output violates whole-chunk availability")

    return receipts


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
    _validate_output_rows(rows)

    receipts = _validated_run_receipts(con, run_id, run, rows, completed_at)

    dependencies = dependency_output_ids or []
    if dependencies != sorted(set(dependencies)):
        raise ValueError("P16 challenger output dependencies are invalid")
    dependency_rows = [get(con, "p16_challenger_outputs", item) for item in dependencies]
    dependency_runs = [
        None if item is None else get(
            con, "p16_challenger_runs", item["key"].get("run_id", ""))
        for item in dependency_rows
    ]
    if any(item is None or source is None or item["parent_id"] != run["parent_id"]
           or source["key"]["family_id"] != run["key"]["family_id"]
           or source["data"]["market_date"] != run["data"]["market_date"]
           or source["data"]["information_cutoff_at"]
           != run["data"]["information_cutoff_at"]
           or source["data"]["tickers"] != run["data"]["tickers"]
           or source["data"]["source_identity_sha256"]
           != run["data"]["source_identity_sha256"]
           for item, source in zip(dependency_rows, dependency_runs, strict=True)):
        raise ValueError("P16 challenger output dependency differs")
    dependency_policies = sorted(source["key"]["policy_id"] for source in dependency_runs)
    if dependency_policies != run["data"].get("dependency_policy_ids", []):
        raise ValueError("P16 challenger output dependency policy set differs")
    unavailable = sum(row["scoring_status"] == "unavailable" for row in rows)
    if run["data"]["model_contract_sha256"] is not None and not receipts \
            and (unavailable != len(rows) or not reason):
        raise ValueError("uncalled P16 model run requires explicit unavailability")
    if (run["data"]["model_contract_sha256"] is not None and receipts
            and all(item["status"] == "unavailable" for item in receipts)
            and unavailable != len(rows)):
        raise ValueError("unavailable P16 attempts cannot support available output")
    data = {
        "run_sha256": run["row_sha256"],
        "rows": sorted(rows, key=lambda row: row["ticker"]),
        "attempt_sources": receipts,
        "dependency_output_ids": dependencies,
        "candidate_count": len(rows), "unavailable_count": unavailable,
        "reason": reason, "execution_authority": "none",
    }
    result = _put(
        con, "p16_challenger_outputs", key={"run_id": run_id}, parent=run["parent_id"],
        payload=data, recorded_at=completed_at,
    )
    if run["data"]["run_mode"] != "dry_run":
        event_at = datetime.fromisoformat(result["recorded_at"])
        p16_trial_store.record_event(
            con, run["key"]["trial_id"],
            "failed" if unavailable == len(rows) else "evaluated",
            event_at=event_at, recorded_at=event_at,
            source_ref={
                "p16_challenger_output_sha256": result["row_sha256"],
                "registration_sha256": run["key"]["registration_sha256"],
            },
        )
    return result


def output_for_run(con, run_id: str) -> dict | None:
    return get(
        con, "p16_challenger_outputs", canonical_sha256({"run_id": run_id}))


def find_run(
    con, *, registration_sha256: str, family_id: str, policy_id: str,
    market_date: date, run_mode: str,
) -> dict | None:
    """Find one verified logical run for restart-safe orchestration."""
    if run_mode not in RUN_MODES or not table_exists(con, "p16_challenger_runs"):
        return None
    rows = [_decode(row) for row in con.execute(
        "SELECT * FROM p16_challenger_runs ORDER BY recorded_at,record_id"
    ).fetchall()]
    matches = [row for row in rows if (
        row["key"].get("registration_sha256") == registration_sha256
        and row["key"].get("family_id") == family_id
        and row["key"].get("policy_id") == policy_id
        and row["data"].get("market_date") == market_date.isoformat()
        and row["data"].get("run_mode") == run_mode
    )]
    if len(matches) > 1:
        raise ValueError("P16 challenger run identity is ambiguous")
    if not matches:
        return None
    run = matches[0]
    return {**run, "output": output_for_run(con, run["record_id"])}


def publish_score_snapshot(
    con, output_id: str, *, evaluation_tickers: list[str], recorded_at: datetime,
) -> tuple[str, dict]:
    """Publish one prospective challenger output in W1's exact score contract."""
    output = get(con, "p16_challenger_outputs", output_id)
    if output is None:
        raise ValueError("P16 challenger output is absent")
    run = get(con, "p16_challenger_runs", output["key"].get("run_id", ""))
    if run is None or run["data"].get("run_mode") != "prospective":
        raise ValueError("only prospective P16 output may enter evaluation")
    rows = output["data"].get("rows")
    tickers = [row.get("ticker") for row in rows] if isinstance(rows, list) else []
    if (not isinstance(evaluation_tickers, list) or not evaluation_tickers
            or len(evaluation_tickers) != len(set(evaluation_tickers))
            or set(evaluation_tickers) - set(tickers)):
        raise ValueError("P16 evaluation ticker set differs from challenger output")
    by_ticker = {row["ticker"]: row for row in rows}
    scores = {
        ticker: by_ticker[ticker]["expected_excess_bp_5"]
        if by_ticker[ticker]["scoring_status"] == "available" else None
        for ticker in evaluation_tickers
    }
    body = {
        "policy_id": run["key"]["policy_id"],
        "market_date": run["data"]["market_date"],
        "information_cutoff_at": run["data"]["information_cutoff_at"],
        "scores": scores,
    }
    payload = {**body, "score_snapshot_sha256": canonical_sha256(body)}
    artifact_id = p16_store.record_policy_scores(
        con, registration_sha256=run["key"]["registration_sha256"], payload=payload,
        recorded_at=recorded_at,
    )
    return artifact_id, payload
