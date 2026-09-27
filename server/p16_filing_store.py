"""Append-only W3 filing discovery, bundle, work, and decision state."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from engine import bitemporal_facts, p16_filing_parser, p16_filing_sources
from engine.lib import db
from engine.lib.provenance import canonical_sha256

POLICY_ID = "p16-filings-v1"
SOURCE_VERSION = "sec-submissions-v2"
READY_BUNDLES = {"complete", "primary_only", "truncated"}
BUNDLE_STATES = READY_BUNDLES | {"extraction_unavailable", "unsupported_format", "bundle_oversized"}
EXHIBIT_STATES = {"ex99_1", "ex99_sole", "absent"}
WORK_STATES = {"queued", "started", "retry", "complete", "unavailable"}
TERMINAL_WORK = {"complete", "unavailable"}

def _time(value: datetime | str, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} requires an explicit timezone")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)

def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)

def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} is invalid")
    return value
def _verified_receipt(con, receipt_sha256: str) -> dict:
    cursor = con.execute(
        "SELECT schema_version,source,dataset,endpoint,request_payload,request_sha256,"
        "requested_at,received_at,http_status,content_type,response_size_bytes,response_sha256,"
        "response_body,license_class,receipt_sha256 FROM source_response_receipts "
        "WHERE receipt_sha256=?", [receipt_sha256])
    row = cursor.fetchone()
    if row is None:
        raise ValueError("filing receipt is unavailable")
    item = dict(zip((column[0] for column in cursor.description), row, strict=True))
    body = bytes(item.pop("response_body"))
    request_payload, stored_sha = item.pop("request_payload"), item.pop("receipt_sha256")
    identity = {**item, "requested_at": item["requested_at"].isoformat(),
                "received_at": item["received_at"].isoformat()}
    if (hashlib.sha256(request_payload.encode()).hexdigest() != item["request_sha256"]
            or len(body) != item["response_size_bytes"]
            or hashlib.sha256(body).hexdigest() != item["response_sha256"]
            or canonical_sha256(identity) != stored_sha or stored_sha != receipt_sha256):
        raise ValueError("filing receipt identity differs")
    return item

def init_schema(con) -> None:
    bitemporal_facts.init_schema(con)
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_scans (
        scan_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, session_date DATE NOT NULL,
        activation_at TIMESTAMP NOT NULL, started_at TIMESTAMP NOT NULL,
        universe_json VARCHAR NOT NULL, universe_sha256 VARCHAR NOT NULL,
        map_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_sec_request_events (
        event_sha256 VARCHAR PRIMARY KEY, request_id VARCHAR NOT NULL, scan_id VARCHAR NOT NULL,
        consumer VARCHAR NOT NULL, request_kind VARCHAR NOT NULL, attempt INTEGER NOT NULL,
        event_kind VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, status_code INTEGER,
        pause_until TIMESTAMP, blocked BOOLEAN, payload_json VARCHAR NOT NULL,
        payload_sha256 VARCHAR NOT NULL, UNIQUE(request_id,attempt,event_kind))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_cik_responses (
        response_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, scan_id VARCHAR NOT NULL,
        cik VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL,
        accessions_json VARCHAR NOT NULL,
        accessions_sha256 VARCHAR NOT NULL, previous_response_id VARCHAR,
        receipt_sha256 VARCHAR NOT NULL, reused_response_id VARCHAR,
        source_body_sha256 VARCHAR NOT NULL, source_status VARCHAR NOT NULL,
        row_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(scan_id,cik))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_accessions (
        policy_id VARCHAR NOT NULL, accession VARCHAR NOT NULL, cik VARCHAR NOT NULL,
        first_response_id VARCHAR NOT NULL, previous_response_id VARCHAR,
        previous_accessions_sha256 VARCHAR NOT NULL, discovered_at TIMESTAMP NOT NULL,
        activation_at TIMESTAMP NOT NULL, cik_entered_at TIMESTAMP NOT NULL,
        securities_json VARCHAR NOT NULL, primary_security_id VARCHAR NOT NULL,
        metadata_json VARCHAR NOT NULL, metadata_sha256 VARCHAR NOT NULL,
        discovery_status VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE,
        PRIMARY KEY(policy_id,accession))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_work_events (
        event_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL, policy_id VARCHAR NOT NULL,
        work_kind VARCHAR NOT NULL, accession VARCHAR NOT NULL, security_id VARCHAR NOT NULL,
        session_date DATE NOT NULL, sequence INTEGER NOT NULL, status VARCHAR NOT NULL,
        event_at TIMESTAMP NOT NULL, not_before TIMESTAMP NOT NULL,
        input_json VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL, reason VARCHAR,
        UNIQUE(work_id,sequence))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_bundles (
        bundle_sha256 VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, accession VARCHAR NOT NULL,
        revision INTEGER NOT NULL,
        accepted_at TIMESTAMP NOT NULL, available_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL,
        status VARCHAR NOT NULL, eligibility_status VARCHAR NOT NULL,
        exhibit_status VARCHAR NOT NULL, byte_count BIGINT NOT NULL,
        components_json VARCHAR NOT NULL, components_sha256 VARCHAR NOT NULL,
        normalized_json VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL,
        fact_sha256 VARCHAR, row_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(policy_id,accession,revision))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_acceptance (
        resolution_sha256 VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL,
        accession VARCHAR NOT NULL, accepted_at TIMESTAMP NOT NULL,
        resolved_at TIMESTAMP NOT NULL, reference VARCHAR NOT NULL,
        json_crosscheck VARCHAR NOT NULL, input_json VARCHAR NOT NULL,
        input_sha256 VARCHAR NOT NULL, UNIQUE(policy_id,accession))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_score_attempts (
        attempt_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL,
        attempt_number INTEGER NOT NULL, started_at TIMESTAMP NOT NULL,
        request_json VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL,
        runtime_json VARCHAR NOT NULL, runtime_sha256 VARCHAR NOT NULL,
        UNIQUE(work_id,attempt_number))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_decisions (
        decision_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL UNIQUE,
        attempt_sha256 VARCHAR NOT NULL UNIQUE, policy_id VARCHAR NOT NULL,
        accession VARCHAR NOT NULL, security_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
        decided_at TIMESTAMP NOT NULL, response_json VARCHAR, response_sha256 VARCHAR,
        runtime_sha256 VARCHAR NOT NULL, model_latency_ms BIGINT NOT NULL,
        retrieval_latency_ms BIGINT NOT NULL, reason VARCHAR,
        UNIQUE(policy_id,accession,security_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_filing_labels (
        label_sha256 VARCHAR PRIMARY KEY, decision_sha256 VARCHAR NOT NULL,
        horizon INTEGER NOT NULL, entry_basis VARCHAR NOT NULL, labelled_at TIMESTAMP NOT NULL,
        payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL,
        UNIQUE(decision_sha256,horizon,entry_basis))""")

def start_scan(con, *, policy_id: str, session_date: date, activation_at: datetime,
               started_at: datetime, universe: dict, map_sha256: str) -> str:
    if not policy_id or not isinstance(session_date, date) or not isinstance(universe, dict):
        raise ValueError("invalid filing scan identity")
    activation, started = _time(activation_at, "activation_at"), _time(started_at, "started_at")
    if activation > started:
        raise ValueError("scan predates activation")
    for cik, scope in universe.items():
        p16_filing_parser.cik_id(cik)
        if (not isinstance(scope, dict) or not isinstance(scope.get("securities"), list)
                or not scope["securities"]
                or any(not isinstance(item, str) or not item for item in scope["securities"])
                or len(scope["securities"]) != len(set(scope["securities"]))):
            raise ValueError("invalid filing scan universe")
        tickers = scope.get("security_tickers")
        if (not isinstance(tickers, dict) or set(tickers) != set(scope["securities"])
                or any(not isinstance(item, str) or not item for item in tickers.values())):
            raise ValueError("invalid filing security tickers")
        _sha(scope.get("selection_sha256"), "filing selection")
        if scope.get("primary_security_id") not in scope["securities"]:
            raise ValueError("invalid primary filing security")
        _time(scope.get("entered_at"), "cik_entered_at")
    universe_sha = canonical_sha256(universe)
    identity = {"policy_id": policy_id, "session_date": session_date.isoformat(),
                "activation_at": activation.isoformat(), "started_at": started.isoformat(),
                "universe_sha256": universe_sha, "map_sha256": _sha(map_sha256, "map_sha256")}
    scan_id, row_sha = canonical_sha256(identity), canonical_sha256({**identity, "universe": universe})
    existing = con.execute("SELECT row_sha256 FROM p16_filing_scans WHERE scan_id=?", [scan_id]).fetchone()
    if existing:
        if existing[0] != row_sha:
            raise ValueError("filing scan replay differs")
        return scan_id
    con.execute("INSERT INTO p16_filing_scans VALUES (?,?,?,?,?,?,?,?,?)",
                [scan_id, policy_id, session_date, activation, started, _json(universe),
                 universe_sha, map_sha256, row_sha])
    return scan_id

def append_dispatch_event(con, event: dict) -> str:
    required = {"request_id", "scan_id", "consumer", "request_kind", "attempt",
                "event_kind", "event_at", "url_sha256"}
    if not isinstance(event, dict) or not required <= set(event):
        raise ValueError("invalid SEC dispatch event")
    if con.execute("SELECT 1 FROM p16_filing_scans WHERE scan_id=?", [event["scan_id"]]).fetchone() is None:
        raise ValueError("SEC dispatch scan is unavailable")
    event_at = _time(event["event_at"], "event_at")
    payload_sha, encoded = canonical_sha256(event), _json(event)
    event_sha = canonical_sha256({"request_id": event["request_id"], "attempt": event["attempt"],
                                  "event_kind": event["event_kind"], "payload_sha256": payload_sha})
    existing = con.execute("SELECT payload_sha256 FROM p16_sec_request_events WHERE event_sha256=?",
                           [event_sha]).fetchone()
    if existing:
        if existing[0] != payload_sha:
            raise ValueError("SEC dispatch event replay differs")
        return event_sha
    pause = event.get("pause_until")
    con.execute("INSERT INTO p16_sec_request_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        event_sha, event["request_id"], event["scan_id"], event["consumer"],
        event["request_kind"], event["attempt"], event["event_kind"], event_at,
        event.get("status_code"), None if pause is None else _time(pause, "pause_until"),
        event.get("blocked"), encoded, payload_sha,
    ])
    return event_sha

def dispatch_state(con, *, scan_id: str, next_session_at: datetime | None = None) -> dict:
    scan = con.execute("SELECT started_at FROM p16_filing_scans WHERE scan_id=?", [scan_id]).fetchone()
    if scan is None:
        raise ValueError("filing scan is unavailable")
    rows = con.execute(
        "SELECT event_kind,event_at,status_code,pause_until,blocked FROM p16_sec_request_events "
        "WHERE scan_id=? ORDER BY event_at,event_sha256", [scan_id],
    ).fetchall()
    pauses = [row[3] for row in rows if row[3] is not None]
    return {"scan_id": scan_id, "scan_started_at": _aware(scan[0]),
            "scan_starts": sum(row[0] == "started" for row in rows),
            "session_403_count": sum(row[0] == "response" and row[2] == 403 for row in rows),
            "pause_until": None if not pauses else _aware(max(pauses)),
            "blocked": any(row[4] is True for row in rows), "next_session_at": next_session_at}

def _scan(con, scan_id: str):
    row = con.execute("SELECT * FROM p16_filing_scans WHERE scan_id=?", [scan_id]).fetchone()
    if row is None:
        raise ValueError("filing scan is unavailable")
    return row

def append_work_event(con, *, policy_id: str, work_kind: str, accession: str,
                      security_id: str = "", session_date: date, status: str,
                      event_at: datetime, not_before: datetime, input_payload: dict,
                      reason: str | None = None) -> str:
    if status not in WORK_STATES or work_kind not in {"acceptance", "document", "score"}:
        raise ValueError("invalid filing work event")
    work_id = canonical_sha256({"policy_id": policy_id, "work_kind": work_kind,
                                "accession": accession, "security_id": security_id})
    previous = con.execute(
        "SELECT sequence,status,input_sha256,reason,event_at,not_before FROM p16_filing_work_events "
        "WHERE work_id=? ORDER BY sequence DESC LIMIT 1", [work_id],
    ).fetchone()
    encoded, input_sha = _json(input_payload), canonical_sha256(input_payload)
    if previous:
        if previous[2] != input_sha:
            raise ValueError("filing work input identity differs")
        if previous[1] == status == "queued" and previous[3] == reason:
            return work_id
        if previous[1] in TERMINAL_WORK:
            raise ValueError("filing work is terminal")
        allowed = {"queued": {"started", "unavailable"},
                   "started": {"retry", "complete", "unavailable"},
                   "retry": {"started", "unavailable"}}
        if status not in allowed[previous[1]]:
            raise ValueError("invalid filing work transition")
        if status == "retry":
            prior_retries = int(con.execute(
                "SELECT COUNT(*) FROM p16_filing_work_events WHERE work_id=? AND status='retry'",
                [work_id]).fetchone()[0])
            limit = 1 if work_kind == "score" else 3
            if prior_retries >= limit:
                raise ValueError("filing work retry exhausted")
            if work_kind == "score" and reason != "transport_lost":
                raise ValueError("score retry requires lost transport")
        sequence = int(previous[0]) + 1
    else:
        if status != "queued":
            raise ValueError("filing work must start queued")
        sequence = 1
    event_time, ready = _time(event_at, "event_at"), _time(not_before, "not_before")
    if previous and (event_time < previous[4] or
                     (status == "started" and event_time < previous[5])):
        raise ValueError("filing work chronology differs")
    if status == "retry" and work_kind != "score":
        delay = (5, 30, 120)[prior_retries]
        if ready != event_time + timedelta(seconds=delay):
            raise ValueError("SEC retry delay differs")
    identity = {"work_id": work_id, "policy_id": policy_id, "work_kind": work_kind,
                "accession": accession, "security_id": security_id,
                "session_date": session_date.isoformat(), "sequence": sequence, "status": status,
                "event_at": event_time.isoformat(), "not_before": ready.isoformat(),
                "input_sha256": input_sha, "reason": reason}
    event_sha = canonical_sha256(identity)
    con.execute("INSERT INTO p16_filing_work_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        event_sha, work_id, policy_id, work_kind, accession, security_id, session_date,
        sequence, status, event_time, ready, encoded, input_sha, reason,
    ])
    return work_id

def commit_cik_success(
    con, *, scan_id: str, cik: str, response: p16_filing_sources.SecResponse,
    request_payload: dict, ingested_at: datetime, after_response: Callable[[], None] | None = None,
) -> dict:
    scan = _scan(con, scan_id)
    policy_id, session_date, activation_at, universe = (
        scan[1], scan[2], scan[3], json.loads(scan[5]))
    cik = p16_filing_parser.cik_id(cik)
    if cik not in universe:
        raise ValueError("CIK is outside the frozen scan")
    received, ingested = (_time(response.received_at, "received_at"),
                          _time(ingested_at, "ingested_at"))
    if received > ingested:
        raise ValueError("CIK response chronology differs")
    with db.transaction(con):
        prior = con.execute(
            "SELECT r.response_id,r.accessions_json,r.accessions_sha256,r.receipt_sha256,"
            "r.source_body_sha256,s.response_body FROM p16_filing_cik_responses r "
            "JOIN source_response_receipts s ON s.receipt_sha256=r.receipt_sha256 "
            "WHERE r.policy_id=? AND r.cik=? AND r.scan_id<>? "
            "ORDER BY r.received_at DESC,r.response_id DESC LIMIT 1", [policy_id, cik, scan_id],
        ).fetchone()
        if response.status_code == 200:
            parsed = p16_filing_sources.parse_submissions(response, cik=cik)
            receipt = bitemporal_facts.record_receipt(
                con, source="sec-edgar", dataset="submissions", endpoint=response.final_url,
                request=request_payload, requested_at=response.requested_at,
                received_at=response.received_at, http_status=200,
                content_type=response.content_type, body=response.body, license_class="public",
            )["receipt_sha256"]
        elif response.status_code == 304 and prior is not None:
            verified = p16_filing_sources.Verified304(bytes(prior[5]), prior[4])
            parsed = p16_filing_sources.parse_submissions(
                response, cik=cik, verified_304=verified,
            )
            receipt = prior[3]
        else:
            raise ValueError("untrusted CIK response")
        source_status = parsed["source_status"]
        source_body_sha = _sha(parsed["source_body_sha256"], "source body")
        accessions, prior_id = parsed["response_accessions"], None if prior is None else prior[0]
        accession_sha = canonical_sha256(accessions)
        if source_status == "verified_304" and accession_sha != prior[2]:
            raise ValueError("304 predecessor identity differs")
        response_id = canonical_sha256({"scan_id": scan_id, "cik": cik,
                                        "received_at": received.isoformat(),
                                        "accessions_sha256": accession_sha,
                                        "source_body_sha256": source_body_sha})
        existing = con.execute(
            "SELECT response_id,accessions_sha256,source_body_sha256,ingested_at,source_status "
            "FROM p16_filing_cik_responses WHERE scan_id=? AND cik=?", [scan_id, cik],
        ).fetchone()
        if existing:
            if existing != (response_id, accession_sha, source_body_sha, ingested, source_status):
                raise ValueError("CIK response replay differs")
            result = {"response_id": existing[0], "replayed": True, "queued": 0}
            return result
        prior_accessions = [] if prior is None else json.loads(prior[1])
        known = {row[0] for row in con.execute(
            "SELECT accession FROM p16_filing_accessions WHERE policy_id=?", [policy_id]).fetchall()}
        scope = universe[cik]
        discoveries = p16_filing_sources.classify_discoveries(
            parsed, previous_accessions=prior_accessions, known_accessions=known,
            activation_at=_aware(activation_at), cik_entered_at=scope["entered_at"],
            response_id=response_id, previous_response_id=prior_id,
        )
        row_identity = {"response_id": response_id, "policy_id": policy_id, "scan_id": scan_id,
                        "cik": cik, "received_at": received.isoformat(),
                        "ingested_at": ingested.isoformat(), "accessions_sha256": accession_sha,
                        "previous_response_id": prior_id, "receipt_sha256": receipt,
                        "reused_response_id": prior_id if source_status == "verified_304" else None,
                        "source_body_sha256": source_body_sha, "source_status": source_status}
        con.execute("INSERT INTO p16_filing_cik_responses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            response_id, policy_id, scan_id, cik, received, ingested, _json(accessions), accession_sha,
            prior_id, receipt, prior_id if source_status == "verified_304" else None,
            source_body_sha, source_status, canonical_sha256(row_identity),
        ])
        if after_response:
            after_response()
        queued = 0
        for item in discoveries:
            if item["accession"] in known:
                continue
            metadata = {key: item[key] for key in (
                "form", "filing_date", "report_date", "json_acceptance",
                "primary_filename", "metadata_items", "matched_items")}
            metadata_sha = canonical_sha256(metadata)
            row_identity = {"policy_id": policy_id, "accession": item["accession"], "cik": cik,
                            "first_response_id": response_id, "previous_response_id": prior_id,
                            "previous_accessions_sha256": item["previous_accessions_sha256"],
                            "discovered_at": received.isoformat(),
                            "activation_at": activation_at.isoformat(),
                            "cik_entered_at": _time(scope["entered_at"], "cik_entered_at").isoformat(),
                            "securities": scope["securities"],
                            "primary_security_id": scope["primary_security_id"],
                            "metadata_sha256": metadata_sha, "discovery_status": item["status"]}
            con.execute("INSERT INTO p16_filing_accessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                policy_id, item["accession"], cik, response_id, prior_id,
                item["previous_accessions_sha256"], received, activation_at,
                _time(scope["entered_at"], "cik_entered_at"), _json(scope["securities"]),
                scope["primary_security_id"], _json(metadata), metadata_sha,
                item["status"], canonical_sha256(row_identity),
            ])
            if item["status"] == "acceptance_pending_crosscheck":
                append_work_event(
                    con, policy_id=policy_id, work_kind="acceptance", accession=item["accession"],
                    session_date=session_date, status="queued", event_at=_aware(received),
                    not_before=_aware(received), input_payload={
                        "cik": cik, "accession": item["accession"],
                        "first_response_id": response_id,
                        "previous_accessions_sha256": item["previous_accessions_sha256"],
                    },
                )
                queued += 1
    return {"response_id": response_id, "replayed": False, "queued": queued,
            "discovery_count": len(discoveries)}
def record_acceptance(
    con, *, policy_id: str, accession: str, resolved_at: datetime,
    sgml_receipt_sha256: str | None = None, index_receipt_sha256: str | None = None,
) -> dict:
    accession_row = con.execute(
        "SELECT cik,metadata_json FROM p16_filing_accessions WHERE policy_id=? AND accession=?",
        [policy_id, accession],
    ).fetchone()
    references = {"sgml": (sgml_receipt_sha256, "complete_submission"),
                  "index": (index_receipt_sha256, "filing_index")}
    supplied = {name: values for name, values in references.items() if values[0] is not None}
    if accession_row is None or not supplied:
        raise ValueError("acceptance reference receipt is unavailable")
    resolved = _time(resolved_at, "resolved_at")
    receipt_times, values = [], {}
    archive_prefix = p16_filing_sources.archive_url(
        accession_row[0], accession,
    ).rsplit("/", 1)[0] + "/"
    for name, (receipt_sha, dataset) in supplied.items():
        receipt = con.execute(
            "SELECT source,dataset,endpoint,received_at,http_status,response_body "
            "FROM source_response_receipts "
            "WHERE receipt_sha256=?", [receipt_sha],
        ).fetchone()
        if (receipt is None or receipt[0] != "sec-edgar" or receipt[1] != dataset
                or not receipt[2].startswith(archive_prefix) or receipt[4] != 200
                or receipt[3] > resolved):
            raise ValueError("acceptance reference receipt is unavailable")
        receipt_times.append(receipt[3])
        raw = bytes(receipt[5])
        values[name] = (p16_filing_parser.submission_acceptance(
            raw, cik=accession_row[0], accession=accession,
        ) if name == "sgml" else p16_filing_parser.index_acceptance(
            raw, accession=accession,
        ))
    metadata = json.loads(accession_row[1])
    result = p16_filing_parser.resolve_acceptance(
        json_value=metadata["json_acceptance"], sgml_value=values.get("sgml"),
        index_value=values.get("index"), reference_received_at=_aware(min(receipt_times)),
    )
    if result["status"] != "resolved":
        raise ValueError("acceptance reference is unresolved")
    inputs = {"reference_receipts": {name: item[0] for name, item in supplied.items()},
              "sgml_value": values.get("sgml"), "index_value": values.get("index"),
              "json_value": metadata["json_acceptance"]}
    identity = {"policy_id": policy_id, "accession": accession,
                "accepted_at": result["accepted_at"], "reference": result["reference"],
                "json_crosscheck": result["json_crosscheck"],
                "input_sha256": canonical_sha256(inputs)}
    resolution_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT resolution_sha256 FROM p16_filing_acceptance WHERE policy_id=? AND accession=?",
        [policy_id, accession],
    ).fetchone()
    if existing:
        if existing[0] != resolution_sha:
            raise ValueError("acceptance resolution replay differs")
        return {**result, "resolution_sha256": resolution_sha, "replayed": True}
    con.execute("INSERT INTO p16_filing_acceptance VALUES (?,?,?,?,?,?,?,?,?)", [
        resolution_sha, policy_id, accession, _time(result["accepted_at"], "accepted_at"),
        resolved, result["reference"], result["json_crosscheck"], _json(inputs),
        identity["input_sha256"],
    ])
    return {**result, "resolution_sha256": resolution_sha, "replayed": False}
def record_bundle(
    con, *, policy_id: str, accession: str, components: list[dict],
    normalized_payload: dict, status: str, exhibit_status: str,
) -> str:
    if status not in BUNDLE_STATES or exhibit_status not in EXHIBIT_STATES:
        raise ValueError("invalid filing bundle status")
    if not components or not isinstance(normalized_payload, dict):
        raise ValueError("filing bundle evidence is missing")
    if any(not isinstance(item, dict) or item.get("role") not in {
            "map", "acceptance_index", "acceptance_sgml", "primary", "exhibit"}
           or isinstance(item.get("byte_count"), bool) or not isinstance(item.get("byte_count"), int)
           or item["byte_count"] <= 0 for item in components):
        raise ValueError("invalid filing bundle component")
    components = sorted((dict(item) for item in components), key=lambda item: item["role"])
    roles = [item["role"] for item in components]
    acceptance = con.execute(
        "SELECT accepted_at,input_json FROM p16_filing_acceptance WHERE policy_id=? AND accession=?",
        [policy_id, accession],
    ).fetchone()
    if acceptance is None:
        raise ValueError("filing acceptance is unresolved")
    reference_receipts = json.loads(acceptance[1])["reference_receipts"]
    expected_roles = {"map", "primary", *(f"acceptance_{name}" for name in reference_receipts)}
    if status in READY_BUNDLES and exhibit_status in {"ex99_1", "ex99_sole"}:
        expected_roles.add("exhibit")
    if ((status == "complete") != (exhibit_status in {"ex99_1", "ex99_sole"})
            or (status == "primary_only" and exhibit_status != "absent")):
        raise ValueError("filing bundle status is inconsistent")
    if set(roles) != expected_roles or len(roles) != len(set(roles)):
        raise ValueError("filing bundle roles are incomplete")
    available = max(_time(item["received_at"], "received_at") for item in components)
    ingested = max(_time(item["ingested_at"], "ingested_at") for item in components)
    byte_count = sum(item["byte_count"] for item in components)
    if byte_count > p16_filing_sources.MAX_BUNDLE_BYTES:
        status = "bundle_oversized"
    receipt_ids = [item["receipt_sha256"] for item in components]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise ValueError("filing bundle receipt is unavailable")
    accession_row = con.execute(
        "SELECT a.cik,a.activation_at,a.cik_entered_at,a.metadata_json,s.map_sha256 "
        "FROM p16_filing_accessions a "
        "JOIN p16_filing_cik_responses r ON r.response_id=a.first_response_id "
        "JOIN p16_filing_scans s ON s.scan_id=r.scan_id "
        "WHERE a.policy_id=? AND a.accession=?",
        [policy_id, accession],
    ).fetchone()
    if accession_row is None:
        raise ValueError("filing accession is unavailable")
    archive_prefix = p16_filing_sources.archive_url(
        accession_row[0], accession,
    ).rsplit("/", 1)[0] + "/"
    expected_datasets = {"map": "ticker_map", "acceptance_index": "filing_index",
                         "acceptance_sgml": "complete_submission",
                         "primary": "filing_document", "exhibit": "filing_document"}
    for item in components:
        receipt = con.execute(
            "SELECT source,dataset,endpoint,received_at,response_size_bytes,http_status,"
            "response_sha256 FROM source_response_receipts "
            "WHERE receipt_sha256=?",
            [item["receipt_sha256"]],
        ).fetchone()
        allowed_dataset = expected_datasets[item["role"]]
        if (receipt is None or receipt[0] != "sec-edgar"
                or (receipt[1] not in allowed_dataset if isinstance(allowed_dataset, set)
                    else receipt[1] != allowed_dataset)
                or receipt[3] != _time(item["received_at"], "received_at")
                or int(receipt[4]) != item["byte_count"]
                or receipt[5] != 200
                or _time(item["ingested_at"], "ingested_at") < receipt[3]
                or (item["role"] != "map" and item.get("accession") != accession)
                or (item["role"] != "map" and not receipt[2].startswith(archive_prefix))
                or (item["role"] == "map" and receipt[6] != accession_row[4])
                or (item["role"] == "map" and item.get("accession") is not None)):
            raise ValueError("filing bundle receipt is unavailable")
    component_receipts = {item["role"].removeprefix("acceptance_"): item["receipt_sha256"]
                          for item in components if item["role"].startswith("acceptance_")}
    if component_receipts != reference_receipts:
        raise ValueError("filing acceptance receipt differs")
    accepted = acceptance[0]
    if accepted > available or available > ingested:
        raise ValueError("filing bundle chronology is invalid")
    normalized_sha, components_sha = canonical_sha256(normalized_payload), canonical_sha256(components)
    if normalized_payload.get("accession") != accession or normalized_payload.get("cik") != accession_row[0]:
        raise ValueError("filing normalized identity differs")
    form = json.loads(accession_row[3])["form"]
    fact_type, entity_id = f"sec.filing:{form.casefold()}", f"sec-cik:{accession_row[0]}"
    prior_facts = [dict(zip(("entity_id", "fact_type", "event_at", "normalized_sha256"), row,
                           strict=True)) for row in con.execute(
        "SELECT entity_id,fact_type,event_at,normalized_sha256 FROM bitemporal_facts "
        "WHERE entity_id=? AND fact_type=? AND event_at=?", [entity_id, fact_type, accepted],
    ).fetchall()]
    eligibility = p16_filing_parser.filing_eligibility(
        {"accession": accession, "accepted_at": _aware(accepted), "available_at": _aware(available),
         "entity_id": entity_id, "fact_type": fact_type, "event_at": _aware(accepted),
         "normalized_sha256": normalized_sha}, prior_facts,
        activation_at=_aware(accession_row[1]), cik_entered_at=_aware(accession_row[2]),
    )
    identity = {"policy_id": policy_id, "accession": accession,
                "normalized_sha256": normalized_sha, "components_sha256": components_sha,
                "accepted_at": accepted.isoformat(), "available_at": available.isoformat(),
                "ingested_at": ingested.isoformat(), "byte_count": byte_count,
                "source_version": SOURCE_VERSION, "parser_version": p16_filing_parser.PARSER_VERSION,
                "status": status, "eligibility_status": eligibility,
                "exhibit_status": exhibit_status}
    bundle_sha = canonical_sha256(identity)
    if con.execute("SELECT 1 FROM p16_filing_bundles WHERE bundle_sha256=?", [bundle_sha]).fetchone():
        return bundle_sha
    revision = int(con.execute(
        "SELECT COALESCE(MAX(revision),0)+1 FROM p16_filing_bundles "
        "WHERE policy_id=? AND accession=?", [policy_id, accession],
    ).fetchone()[0])
    with db.transaction(con):
        fact_sha = None
        if status in READY_BUNDLES and eligibility == "eligible":
            primary_receipt = next(
                item["receipt_sha256"] for item in components if item["role"] == "primary"
            )
            fact_sha = bitemporal_facts.record_fact(
                con, entity_id=entity_id, security_id=None, fact_type=fact_type,
                event_at=_aware(accepted), published_at=_aware(accepted),
                available_at=_aware(available), ingested_at=_aware(ingested), payload=normalized_payload,
                source="sec-edgar", source_version=SOURCE_VERSION,
                receipt_sha256=primary_receipt,
            )["fact_sha256"]
        con.execute("INSERT INTO p16_filing_bundles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            bundle_sha, policy_id, accession, revision, accepted, available, ingested,
            status, eligibility, exhibit_status,
            byte_count, _json(components), components_sha, _json(normalized_payload), normalized_sha,
            fact_sha, canonical_sha256({**identity, "revision": revision, "fact_sha256": fact_sha}),
        ])
    return bundle_sha
def queue_score_work(con, *, policy_id: str, accession: str, security_ids: list[str],
                     session_date: date, queued_at: datetime) -> list[str]:
    if not security_ids or len(security_ids) != len(set(security_ids)) or any(not item for item in security_ids):
        raise ValueError("invalid score security set")
    scope = con.execute(
        "SELECT securities_json FROM p16_filing_accessions WHERE policy_id=? AND accession=?",
        [policy_id, accession],
    ).fetchone()
    if scope is None or not set(security_ids) <= set(json.loads(scope[0])):
        raise ValueError("score security is outside the frozen filing scope")
    bundle = con.execute(
        "SELECT bundle_sha256,available_at,ingested_at FROM p16_filing_bundles "
        "WHERE policy_id=? AND accession=? "
        "AND status IN ('complete','primary_only','truncated') AND eligibility_status='eligible' "
        "ORDER BY revision LIMIT 1",
        [policy_id, accession],
    ).fetchone()
    if bundle is None:
        raise ValueError("eligible filing bundle is unavailable")
    queued = _time(queued_at, "queued_at")
    if queued < max(bundle[1], bundle[2]):
        raise ValueError("score work predates its filing bundle")
    return [append_work_event(
        con, policy_id=policy_id, work_kind="score", accession=accession,
        security_id=security_id, session_date=session_date, status="queued",
        event_at=_aware(queued), not_before=_aware(queued),
        input_payload={"bundle_sha256": bundle[0], "security_id": security_id},
    ) for security_id in sorted(security_ids)]
def verified_score_bundle(con, *, bundle_sha256: str, policy_id: str, accession: str) -> dict:
    """Load a scoreable bundle only after rechecking its immutable identity and evidence."""
    cursor = con.execute(
        "SELECT b.*,a.cik,s.universe_json,s.universe_sha256 AS scan_universe_sha256,"
        "s.row_sha256 AS scan_row_sha256,s.session_date AS scan_session_date,"
        "s.activation_at AS scan_activation_at,s.started_at AS scan_started_at,"
        "s.map_sha256 AS scan_map_sha256 FROM p16_filing_bundles b JOIN p16_filing_accessions a "
        "ON a.policy_id=b.policy_id AND a.accession=b.accession JOIN p16_filing_cik_responses r "
        "ON r.response_id=a.first_response_id JOIN p16_filing_scans s ON s.scan_id=r.scan_id "
        "WHERE b.bundle_sha256=? AND b.policy_id=? AND b.accession=? "
        "AND b.eligibility_status='eligible'", [bundle_sha256, policy_id, accession],
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("eligible filing bundle is unavailable")
    item = dict(zip((column[0] for column in cursor.description), row, strict=True))
    try:
        components = json.loads(item["components_json"])
        normalized = json.loads(item["normalized_json"])
        universe = json.loads(item["universe_json"])
    except (TypeError, ValueError) as exc:
        raise ValueError("filing bundle encoding is invalid") from exc
    acur = con.execute(
        "SELECT * FROM p16_filing_accessions WHERE policy_id=? AND accession=?",
        [policy_id, accession])
    arow = acur.fetchone()
    anames = [column[0] for column in acur.description]
    rcur = con.execute("SELECT * FROM p16_filing_cik_responses WHERE response_id=?",
                       [None if arow is None else arow[3]])
    rrow = rcur.fetchone()
    rnames = [column[0] for column in rcur.description]
    if arow is None or rrow is None:
        raise ValueError("filing accession lineage is unavailable")
    accession_row = dict(zip(anames, arow, strict=True))
    response_row = dict(zip(rnames, rrow, strict=True))
    securities, metadata = (json.loads(accession_row[key])
                             for key in ("securities_json", "metadata_json"))
    response_identity = {key: response_row[key] for key in (
        "response_id", "policy_id", "scan_id", "cik", "accessions_sha256",
        "previous_response_id", "receipt_sha256", "reused_response_id",
        "source_body_sha256", "source_status")}
    response_identity.update(received_at=response_row["received_at"].isoformat(),
                             ingested_at=response_row["ingested_at"].isoformat())
    accession_identity = {key: accession_row[key] for key in (
        "policy_id", "accession", "cik", "first_response_id", "previous_response_id",
        "previous_accessions_sha256", "primary_security_id", "metadata_sha256",
        "discovery_status")}
    accession_identity.update(discovered_at=accession_row["discovered_at"].isoformat(),
                              activation_at=accession_row["activation_at"].isoformat(),
                              cik_entered_at=accession_row["cik_entered_at"].isoformat(),
                              securities=securities)
    raw_receipt = _verified_receipt(con, response_row["receipt_sha256"])
    response_id = canonical_sha256({key: response_identity[key] for key in (
        "scan_id", "cik", "received_at", "accessions_sha256", "source_body_sha256")})
    if (canonical_sha256(json.loads(response_row["accessions_json"]))
            != response_row["accessions_sha256"] or response_id != response_row["response_id"]
            or canonical_sha256(response_identity) != response_row["row_sha256"]
            or canonical_sha256(metadata) != accession_row["metadata_sha256"]
            or canonical_sha256(accession_identity) != accession_row["row_sha256"]
            or normalized.get("cik") != accession_row["cik"]
            or raw_receipt["response_sha256"] != response_row["source_body_sha256"]):
        raise ValueError("filing accession lineage differs")
    scan_identity = {
        "policy_id": item["policy_id"], "session_date": item["scan_session_date"].isoformat(),
        "activation_at": item["scan_activation_at"].isoformat(),
        "started_at": item["scan_started_at"].isoformat(),
        "universe_sha256": item["scan_universe_sha256"],
        "map_sha256": item["scan_map_sha256"],
    }
    if (canonical_sha256(universe) != item["scan_universe_sha256"]
            or canonical_sha256({**scan_identity, "universe": universe})
            != item["scan_row_sha256"]):
        raise ValueError("filing scan identity differs")
    identity = {
        "policy_id": item["policy_id"], "accession": item["accession"],
        "normalized_sha256": item["normalized_sha256"], "components_sha256": item["components_sha256"],
        "accepted_at": item["accepted_at"].isoformat(), "available_at": item["available_at"].isoformat(),
        "ingested_at": item["ingested_at"].isoformat(), "byte_count": item["byte_count"],
        "source_version": SOURCE_VERSION, "parser_version": p16_filing_parser.PARSER_VERSION,
        "status": item["status"], "eligibility_status": item["eligibility_status"],
        "exhibit_status": item["exhibit_status"],
    }
    if (canonical_sha256(components) != item["components_sha256"]
            or canonical_sha256(normalized) != item["normalized_sha256"]
            or canonical_sha256(identity) != item["bundle_sha256"]
            or canonical_sha256({**identity, "revision": item["revision"],
                                 "fact_sha256": item["fact_sha256"]}) != item["row_sha256"]):
        raise ValueError("filing bundle identity differs")
    receipts = set()
    for component in components:
        receipt = _verified_receipt(con, component.get("receipt_sha256"))
        receipts.add(receipt["response_sha256"])
    documents = {(doc.get("filename"), doc.get("normalized_sha256"))
                 for doc in normalized.get("documents", ()) if isinstance(doc, dict)}
    for span in normalized.get("spans", ()):
        lineage = {key: span.get(key) for key in (
            "source_sha256", "filename", "parser_version", "normalized_sha256", "start", "end"
        )}
        if (not isinstance(span, dict) or span.get("source_sha256") not in receipts
                or (span.get("filename"), span.get("normalized_sha256")) not in documents
                or span.get("evidence_id") != canonical_sha256(lineage)):
            raise ValueError("filing evidence identity differs")
    return {**item, "components": components, "normalized": normalized, "universe": universe}
def queue_document_work(
    con, *, policy_id: str, accession: str, session_date: date,
    queued_at: datetime, index_receipt_sha256: str, selected_exhibit: str | None,
) -> str:
    row = con.execute(
        "SELECT dataset,endpoint FROM source_response_receipts WHERE receipt_sha256=?",
        [index_receipt_sha256],
    ).fetchone()
    accession_path = accession.replace("-", "")
    if (row is None or row[0] not in {"filing_index", "complete_submission"}
            or accession_path not in row[1]):
        raise ValueError("document index receipt is unavailable")
    if selected_exhibit is not None:
        p16_filing_parser.safe_filename(selected_exhibit)
    return append_work_event(
        con, policy_id=policy_id, work_kind="document", accession=accession,
        session_date=session_date, status="queued", event_at=queued_at, not_before=queued_at,
        input_payload={"index_receipt_sha256": index_receipt_sha256,
                       "selected_exhibit": selected_exhibit},
    )
def pending_work(con, *, work_kind: str, now: datetime, session_date: date | None = None) -> list[dict]:
    params = [work_kind, _time(now, "now")]
    where = "work_kind=? AND not_before<=?"
    if session_date is not None:
        where += " AND session_date=?"
        params.append(session_date)
    cursor = con.execute(
        "SELECT work_id,policy_id,work_kind,accession,security_id,session_date,status,event_at,"
        "not_before,input_json,input_sha256,MIN(event_at) OVER (PARTITION BY work_id) queued_at "
        f"FROM p16_filing_work_events WHERE {where} "
        "QUALIFY sequence=MAX(sequence) OVER (PARTITION BY work_id) "
        "AND status IN ('queued','retry') ORDER BY queued_at,accession,security_id", params,
    )
    names = [item[0] for item in cursor.description]
    return [{**dict(zip(names, row, strict=True)), "input": json.loads(row[9])}
            for row in cursor.fetchall()]
def claim_score_capacity(
    con, *, session_date: date, now: datetime, limit: int = 60, batch_size: int = 60,
    in_transaction: bool = False,
) -> dict:
    if (type(limit) is not int or not 1 <= limit <= 60 or type(batch_size) is not int
            or not 1 <= batch_size <= 60 or not isinstance(in_transaction, bool)):
        raise ValueError("invalid filing score capacity")
    rows = pending_work(con, work_kind="score", now=now, session_date=session_date)
    started_ids = {row[0] for row in con.execute(
        "SELECT DISTINCT work_id FROM p16_filing_work_events "
        "WHERE work_kind='score' AND session_date=? AND status='started'", [session_date],
    ).fetchall()}
    remaining = max(0, limit - len(started_ids))
    claimed, unavailable = [], []
    with nullcontext() if in_transaction else db.transaction(con):
        for row in rows:
            admitted = row["work_id"] in started_ids or remaining > 0
            if admitted and len(claimed) >= batch_size:
                continue
            status, reason = (("started", None) if admitted else
                              ("unavailable", "capacity_unavailable"))
            append_work_event(
                con, policy_id=row["policy_id"], work_kind="score", accession=row["accession"],
                security_id=row["security_id"], session_date=session_date, status=status,
                event_at=now, not_before=now, input_payload=row["input"], reason=reason,
            )
            (claimed if status == "started" else unavailable).append(row["work_id"])
            if status == "started" and row["work_id"] not in started_ids:
                started_ids.add(row["work_id"])
                remaining -= 1
    return {"claimed": claimed, "capacity_unavailable": unavailable}
def record_score_attempt(con, *, work_id: str, started_at: datetime,
                         request_payload: dict, runtime_identity: dict) -> str:
    work = con.execute(
        "SELECT policy_id,accession,security_id,status,event_at FROM p16_filing_work_events "
        "WHERE work_id=? ORDER BY sequence DESC LIMIT 1", [work_id],
    ).fetchone()
    if work is None or work[3] != "started" or not request_payload or not runtime_identity:
        raise ValueError("score work is not ready for an attempt")
    attempt_number = int(con.execute(
        "SELECT COUNT(*) FROM p16_filing_work_events WHERE work_id=? AND status='started'",
        [work_id],
    ).fetchone()[0])
    if not 1 <= attempt_number <= 2:
        raise ValueError("score transport retry exhausted")
    started = _time(started_at, "started_at")
    if started < work[4]:
        raise ValueError("score attempt predates its claim")
    request_sha, runtime_sha = canonical_sha256(request_payload), canonical_sha256(runtime_identity)
    identity = {"work_id": work_id, "attempt_number": attempt_number,
                "started_at": started.isoformat(), "request_sha256": request_sha,
                "runtime_sha256": runtime_sha}
    attempt_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT attempt_sha256 FROM p16_filing_score_attempts WHERE work_id=? AND attempt_number=?",
        [work_id, attempt_number],
    ).fetchone()
    if existing:
        if existing[0] != attempt_sha:
            raise ValueError("score attempt replay differs")
        return attempt_sha
    first_request = con.execute(
        "SELECT request_sha256,runtime_sha256 FROM p16_filing_score_attempts "
        "WHERE work_id=? ORDER BY attempt_number LIMIT 1",
        [work_id],
    ).fetchone()
    if first_request and first_request != (request_sha, runtime_sha):
        raise ValueError("score retry request identity differs")
    if attempt_number > 1 and first_request is None:
        raise ValueError("score retry predecessor is unavailable")
    con.execute("INSERT INTO p16_filing_score_attempts VALUES (?,?,?,?,?,?,?,?)", [
        attempt_sha, work_id, attempt_number, started, _json(request_payload), request_sha,
        _json(runtime_identity), runtime_sha,
    ])
    return attempt_sha
def record_decision(con, *, attempt_sha256: str, status: str, decided_at: datetime,
                    response_payload: dict | None, reason: str | None = None) -> str:
    if (status not in {"scored", "unavailable"}
            or (status == "scored" and not isinstance(response_payload, dict))
            or (response_payload is not None and not isinstance(response_payload, dict))):
        raise ValueError("invalid filing decision")
    attempt = con.execute(
        "SELECT work_id,attempt_number,started_at,runtime_sha256 FROM p16_filing_score_attempts "
        "WHERE attempt_sha256=?", [attempt_sha256],
    ).fetchone()
    if attempt is None:
        raise ValueError("score attempt is unavailable")
    work = con.execute(
        "SELECT policy_id,accession,security_id,session_date,input_json,status "
        "FROM p16_filing_work_events WHERE work_id=? ORDER BY sequence DESC LIMIT 1",
        [attempt[0]],
    ).fetchone()
    decided = _time(decided_at, "decided_at")
    model_latency_ms = round((decided - attempt[2]).total_seconds() * 1000)
    if model_latency_ms < 0 or (status == "unavailable") != bool(reason):
        raise ValueError("invalid filing decision chronology or reason")
    if work is None:
        raise ValueError("score attempt is not active")
    start_count = int(con.execute(
        "SELECT COUNT(*) FROM p16_filing_work_events WHERE work_id=? AND status='started'",
        [attempt[0]],
    ).fetchone()[0])
    if attempt[1] != start_count:
        raise ValueError("score attempt is not current")
    work_input = json.loads(work[4])
    bundle = con.execute(
        "SELECT available_at,ingested_at FROM p16_filing_bundles "
        "WHERE bundle_sha256=? AND policy_id=? AND accession=?",
        [work_input.get("bundle_sha256"), work[0], work[1]],
    ).fetchone()
    if bundle is None or max(bundle) > attempt[2]:
        raise ValueError("score attempt bundle is unavailable")
    retrieval_latency_ms = round((decided - bundle[0]).total_seconds() * 1000)
    response_sha = None if response_payload is None else canonical_sha256(response_payload)
    identity = {"work_id": attempt[0], "attempt_sha256": attempt_sha256, "status": status,
                "decided_at": decided.isoformat(), "response_sha256": response_sha,
                "runtime_sha256": attempt[3], "model_latency_ms": model_latency_ms,
                "retrieval_latency_ms": retrieval_latency_ms, "reason": reason}
    decision_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT decision_sha256 FROM p16_filing_decisions WHERE work_id=?", [attempt[0]],
    ).fetchone()
    if existing:
        if existing[0] != decision_sha:
            raise ValueError("filing decision replay differs")
        return decision_sha
    if work[5] != "started":
        raise ValueError("score attempt is not active")
    with db.transaction(con):
        con.execute("INSERT INTO p16_filing_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            decision_sha, attempt[0], attempt_sha256, work[0], work[1], work[2], status,
            decided, None if response_payload is None else _json(response_payload), response_sha,
            attempt[3], model_latency_ms, retrieval_latency_ms, reason,
        ])
        append_work_event(
            con, policy_id=work[0], work_kind="score", accession=work[1],
            security_id=work[2], session_date=work[3],
            status="complete" if status == "scored" else "unavailable",
            event_at=_aware(decided), not_before=_aware(decided),
            input_payload=json.loads(work[4]), reason=reason,
        )
    return decision_sha

def record_label(con, *, decision_sha256: str, horizon: int, entry_basis: str,
                 labelled_at: datetime, payload: dict) -> str:
    decision = con.execute(
        "SELECT decided_at,status FROM p16_filing_decisions WHERE decision_sha256=?",
        [decision_sha256],
    ).fetchone()
    if (decision is None or decision[1] != "scored" or horizon not in {1, 5, 10, 20}
            or entry_basis not in {"next_bar", "next_session_open"}
            or not isinstance(payload, dict) or payload.get("status") not in {"available", "unavailable"}):
        raise ValueError("invalid filing label")
    labelled = _time(labelled_at, "labelled_at")
    if labelled < decision[0]:
        raise ValueError("filing label predates its decision")
    if payload["status"] == "available":
        _sha(payload.get("price_series_sha256"), "price series")
    payload_sha = canonical_sha256(payload)
    identity = {"decision_sha256": decision_sha256, "horizon": horizon,
                "entry_basis": entry_basis, "labelled_at": labelled.isoformat(),
                "payload_sha256": payload_sha}
    label_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT label_sha256 FROM p16_filing_labels WHERE decision_sha256=? AND horizon=? "
        "AND entry_basis=?", [decision_sha256, horizon, entry_basis],
    ).fetchone()
    if existing:
        if existing[0] != label_sha:
            raise ValueError("filing label replay differs")
        return label_sha
    con.execute("INSERT INTO p16_filing_labels VALUES (?,?,?,?,?,?,?)", [
        label_sha, decision_sha256, horizon, entry_basis, labelled, _json(payload), payload_sha,
    ])
    return label_sha

def exhibit_retry_status(con, *, policy_id: str, accession: str, observed_at: datetime) -> str:
    row = con.execute(
        "SELECT a.discovered_at,w.status,w.reason,w.input_json FROM p16_filing_accessions a "
        "JOIN p16_filing_work_events w ON w.policy_id=a.policy_id AND w.accession=a.accession "
        "AND w.work_kind='document' WHERE a.policy_id=? AND a.accession=? "
        "QUALIFY w.sequence=MAX(w.sequence) OVER (PARTITION BY w.work_id)",
        [policy_id, accession],
    ).fetchone()
    if row is None:
        raise ValueError("filing document state is unavailable")
    selected = json.loads(row[3])["selected_exhibit"]
    if selected is None:
        return "absent"
    if row[1] == "complete":
        return "ready"
    if row[2] != "http_404":
        return "pending"
    return ("extraction_unavailable" if _time(observed_at, "observed_at") >= row[0] +
            timedelta(minutes=15) else "pending")
