"""W3 frozen-scope and writer-free scoring runner tests."""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import agent_model_client, p15_scoring_store
from server import p16_filing_client as client
from server import p16_filing_runner as runner
from server import p16_filing_store as store
from sim import nyse

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
ACCESSION = "0000320193-26-000001"
MAP_BODY = b"map.json"
MAP_SHA = hashlib.sha256(MAP_BODY).hexdigest()
READY = {"environ": {"TRADING_ENGINE_SEC_USER_AGENT": "research test@example.com"},
         "legacy_sec_enabled": False}


def _receipt(con, name, at, *, dataset="filing_document", body=None):
    if body is None and dataset == "filing_index":
        body = (f"<html><body><div>Accession Number: {ACCESSION}</div>"
                "<div>Accepted: 2026-09-27 08:01:00</div></body></html>").encode()
    body = name.encode() if body is None else body
    endpoint = ("https://www.sec.gov/files/company_tickers.json" if dataset == "ticker_map"
                else f"https://www.sec.gov/Archives/edgar/data/320193/"
                     f"{ACCESSION.replace('-', '')}/{name}")
    return bitemporal_facts.record_receipt(
        con, source="sec-edgar", dataset=dataset, endpoint=endpoint,
        request={"name": name}, requested_at=at, received_at=at, http_status=200,
        content_type="application/json" if dataset == "ticker_map" else "text/html",
        body=body, license_class="public",
    )["receipt_sha256"]


def _size(con, receipt):
    return con.execute(
        "SELECT response_size_bytes FROM source_response_receipts WHERE receipt_sha256=?",
        [receipt],
    ).fetchone()[0]


def _database(path, securities=("AAPL",)):
    con = db.connect(path)
    store.init_schema(con)
    universe = {"0000320193": {
        "entered_at": (NOW - timedelta(hours=1)).isoformat(),
        "securities": list(securities), "security_tickers": {item: item for item in securities},
        "primary_security_id": securities[0], "selection_sha256": "e" * 64,
    }}
    scan = store.start_scan(
        con, policy_id=store.POLICY_ID, session_date=NOW.date(),
        activation_at=NOW - timedelta(hours=1), started_at=NOW, universe=universe,
        map_sha256=MAP_SHA,
    )
    submissions = {"cik": 320193, "filings": {"recent": {
        "accessionNumber": [ACCESSION], "acceptanceDateTime": ["untrusted"],
        "filingDate": ["2026-09-27"], "form": ["8-K"], "items": ["2.02"],
        "primaryDocument": ["filing.htm"], "reportDate": ["2026-06-30"],
    }}}
    raw = json.dumps(submissions).encode()
    response = runner.p16_filing_sources.SecResponse(
        200, "application/json", {}, raw, NOW, NOW,
        runner.p16_filing_sources.submissions_url(320193), len(raw), True,
    )
    store.commit_cik_success(
        con, scan_id=scan, cik="0000320193", response=response,
        request_payload={"scan_id": scan}, ingested_at=NOW,
    )
    available = NOW + timedelta(minutes=2)
    map_receipt = _receipt(con, "map.json", NOW, dataset="ticker_map", body=MAP_BODY)
    index = _receipt(con, f"{ACCESSION}-index.htm", available, dataset="filing_index")
    primary = _receipt(con, "filing.htm", available)
    store.record_acceptance(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        index_receipt_sha256=index, resolved_at=available,
    )
    text = "Item 2.02 Results were above plan."
    source_sha = hashlib.sha256(b"filing.htm").hexdigest()
    normalized_sha = hashlib.sha256(text.encode()).hexdigest()
    evidence = {"source_sha256": source_sha, "filename": "filing.htm",
                "parser_version": "p16-filings-parser-v1", "normalized_sha256": normalized_sha,
                "start": 0, "end": len(text), "text": text}
    evidence["evidence_id"] = canonical_sha256({key: value for key, value in evidence.items()
                                                 if key != "text"})
    components = [
        {"role": "map", "accession": None, "receipt_sha256": map_receipt,
         "received_at": NOW.isoformat(), "ingested_at": NOW.isoformat(),
         "byte_count": _size(con, map_receipt)},
        {"role": "acceptance_index", "accession": ACCESSION, "receipt_sha256": index,
         "received_at": available.isoformat(), "ingested_at": available.isoformat(),
         "byte_count": _size(con, index)},
        {"role": "primary", "accession": ACCESSION, "receipt_sha256": primary,
         "received_at": available.isoformat(), "ingested_at": available.isoformat(),
         "byte_count": _size(con, primary)},
    ]
    bundle = store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION, components=components,
        normalized_payload={"cik": "0000320193", "accession": ACCESSION,
                            "items": ["2.02"], "spans": [evidence], "truncated": False,
                            "documents": [{"filename": "filing.htm",
                                           "normalized_sha256": normalized_sha}]},
        status="primary_only", exhibit_status="absent",
    )
    store.queue_score_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        security_ids=list(securities), session_date=NOW.date(), queued_at=available,
    )
    con.close()
    return bundle


def _assessment(ticker):
    return {"ticker": ticker, "p_outperform_5": 0.6, "expected_excess_bp_5": 20,
            "expected_excess_bp_10": 30, "action": "watch", "thesis": "Evidence supports upside.",
            "invalidation": "The trend reverses.", "evidence_ids": [], "event_kind": "earnings",
            "guidance_change": "none", "headline_surprise": "unknown",
            "one_off_items": [], "tone": 0.1}


def _scope_history(con, liquidity):
    db.init_schema(con)
    days, current = [], NOW.date() - timedelta(days=1)
    while len(days) < 60:
        if nyse.is_session(current):
            days.append(current)
        current -= timedelta(days=1)
    con.executemany(
        "INSERT INTO universe_snapshot VALUES (?,?,?,?,?,?,?,?)",
        [(NOW.date(), ticker, ticker, "NYSE", False, "test", True, True)
         for ticker in liquidity],
    )
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,source,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(ticker, day, 9.0, 11.0, 8.0, 10.0, volume // 10, "fixture",
          (NOW - timedelta(minutes=1)).replace(tzinfo=None))
         for ticker, volume in liquidity.items() for day in days],
    )


def _result(payload, *, drift=False):
    assessment = _assessment(payload["ticker"])
    assessment["evidence_ids"] = payload["allowed_evidence_ids"]
    identity = client.identity()
    request = client.request_payload(payload)
    return client.FilingConnectorResult(
        output={"schema_version": 1, "assessments": [assessment]},
        response_id="response-1", model="wrong" if drift else identity["model"],
        model_version=identity["model_version"], proxy_version=identity["required_proxy_version"],
        proxy_source_sha256=identity["required_proxy_source_sha256"],
        traecli_runtime=identity["required_traecli_runtime"],
        upstream_model_family=identity["upstream_model_family"], upstream_request_id="upstream-1",
        model_catalog_entry_sha256=identity["model_catalog_entry_sha256"],
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        raw_response_sha256="f" * 64,
    )


def test_readiness_is_inert_without_contact_or_shared_dispatch():
    assert runner.readiness(environ={}, legacy_sec_enabled=False)["status"] == "unconfigured"
    configured = {"TRADING_ENGINE_SEC_USER_AGENT": "research test@example.com"}
    assert runner.readiness(environ=configured, legacy_sec_enabled=True)["status"] == (
        "shared_dispatch_required"
    )
    assert runner.readiness(environ=configured, legacy_sec_enabled=False)["status"] == "ready"


def test_frozen_scope_uses_cutoff_snapshots_and_sixty_session_primary(con):
    p15_scoring_store.init_schema(con)
    bitemporal_facts.init_schema(con)
    body = {"market_date": NOW.date().isoformat(),
            "candidates": [{"ticker": "GOOG"}, {"ticker": "GOOGL"}]}
    universe = {**body, "bundle_sha256": canonical_sha256(body)}
    run = p15_scoring_store.create_run(
        con, market_date=NOW.date(), universe=universe, context={},
        information_cutoff_at=NOW - timedelta(minutes=2),
        started_at=NOW - timedelta(minutes=2), news_receipts=[],
    )
    p15_scoring_store.complete_run(
        con, run["run_id"], trace_sha256="e" * 64,
        completed_at=NOW - timedelta(minutes=1),
    )
    map_body = json.dumps({str(index): {"cik_str": 320193, "ticker": ticker}
                           for index, ticker in enumerate(("GOOG", "GOOGL"))}).encode()
    map_sha = hashlib.sha256(map_body).hexdigest()
    _receipt(con, "map.json", NOW - timedelta(minutes=3), dataset="ticker_map", body=map_body)
    _scope_history(con, {"GOOG": 10, "GOOGL": 20})
    result = runner.frozen_scope(
        con, market_date=NOW.date(), scan_started_at=NOW, map_sha256=map_sha,
    )
    assert result["status"] == "ready"
    assert result["universe"]["0000320193"]["primary_security_id"] == "GOOGL"
    assert result["p15"]["run_id"] == run["run_id"]
    assert result["screen"]["status"] == "unavailable"

    store.init_schema(con)
    store.start_scan(
        con, policy_id=store.POLICY_ID, session_date=NOW.date(),
        activation_at=NOW - timedelta(hours=1), started_at=NOW,
        universe=result["universe"], map_sha256=map_sha,
    )
    later = runner.frozen_scope(
        con, market_date=NOW.date(), scan_started_at=NOW + timedelta(minutes=5),
        map_sha256=map_sha,
    )
    assert later["universe"]["0000320193"]["entered_at"] == NOW.isoformat()
    store.start_scan(
        con, policy_id=store.POLICY_ID, session_date=NOW.date(),
        activation_at=NOW - timedelta(hours=1), started_at=NOW + timedelta(minutes=6),
        universe={}, map_sha256=map_sha,
    )
    reentered = runner.frozen_scope(
        con, market_date=NOW.date(), scan_started_at=NOW + timedelta(minutes=7),
        map_sha256=map_sha,
    )
    assert reentered["universe"]["0000320193"]["entered_at"] == (
        NOW + timedelta(minutes=7)
    ).isoformat()

    with pytest.raises(runner.FilingRunError, match="security master"):
        runner.frozen_scope(
            con, market_date=NOW.date(), scan_started_at=NOW, map_sha256=map_sha,
            aliases={"GOOG": "MSFT"},
        )
    stale = runner.frozen_scope(
        con, market_date=NOW.date(), scan_started_at=NOW + timedelta(days=8),
        map_sha256=map_sha,
    )
    assert stale["status"] == "map_stale"
    con.execute(
        "UPDATE source_response_receipts SET response_body=? WHERE response_sha256=?",
        [b"tampered", map_sha],
    )
    with pytest.raises(runner.FilingRunError, match="identity"):
        runner.frozen_scope(
            con, market_date=NOW.date(), scan_started_at=NOW, map_sha256=map_sha,
        )

    with pytest.raises(runner.FilingRunError, match="timezone"):
        runner.frozen_scope(
            con, market_date=NOW.date(), scan_started_at=NOW.replace(tzinfo=None),
            map_sha256=map_sha,
        )


def test_score_pending_releases_writer_limits_concurrency_and_is_terminal(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database, securities=("GOOG", "GOOGL"))
    barrier = threading.Barrier(2)
    active, peak, lock = 0, 0, threading.Lock()

    def generate(payload):
        nonlocal active, peak
        probe = db.connect(database, wait_s=0)
        probe.close()
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=2)
        with lock:
            active -= 1
        return _result(payload)

    outcome = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3), generate=generate,
        clock=lambda: NOW + timedelta(minutes=4), **READY,
    )
    assert outcome == {"status": "completed", "claimed": 2, "scored": 2,
                       "retried": 0, "unavailable": 0, "model_calls": 2}
    assert peak == 2
    assert runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=5), generate=generate,
        clock=lambda: NOW + timedelta(minutes=6), **READY,
    )["model_calls"] == 0


def test_score_pending_is_inert_until_sec_readiness_is_satisfied(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    called = False

    def generate(_payload):
        nonlocal called
        called = True

    assert runner.score_pending(database, generate=generate)["status"] == "unconfigured"
    assert called is False


def test_runner_lock_limits_two_concurrent_invocations_to_two_calls(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database, securities=("A", "B", "C", "D"))
    barrier = threading.Barrier(2)
    active, peak, guard = 0, 0, threading.Lock()

    def generate(payload):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=2)
        with guard:
            active -= 1
        return _result(payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: runner.score_pending(
            database, observed_at=NOW + timedelta(minutes=3), generate=generate,
            clock=lambda: NOW + timedelta(minutes=4), **READY,
        ), range(2)))
    assert sum(result["model_calls"] for result in results) == 4
    assert peak == 2


def test_runner_lock_is_shared_across_database_files(tmp_path, monkeypatch):
    databases = [tmp_path / "first.duckdb", tmp_path / "second.duckdb"]
    for database in databases:
        _database(database, securities=("A", "B"))
    monkeypatch.setattr(runner, "MODEL_LOCK", tmp_path / "host.lock")
    barrier = threading.Barrier(2)
    active, peak, guard = 0, 0, threading.Lock()

    def generate(payload):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=2)
        with guard:
            active -= 1
        return _result(payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda database: runner.score_pending(
            database, observed_at=NOW + timedelta(minutes=3), generate=generate,
            clock=lambda: NOW + timedelta(minutes=4), **READY,
        ), databases))
    assert sum(result["model_calls"] for result in results) == 4
    assert peak == 2


def test_each_result_records_its_actual_completion_time(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database, securities=("A", "B"))
    local = threading.local()

    def generate(payload):
        local.ticker = payload["ticker"]
        return _result(payload)

    def clock():
        return NOW + timedelta(minutes=4 if local.ticker == "A" else 5)

    runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3), generate=generate,
        clock=clock, **READY,
    )
    con = db.connect(database, read_only=True)
    assert dict(con.execute(
        "SELECT security_id,decided_at FROM p16_filing_decisions"
    ).fetchall()) == {"A": (NOW + timedelta(minutes=4)).replace(tzinfo=None),
                      "B": (NOW + timedelta(minutes=5)).replace(tzinfo=None)}
    con.close()


def test_transport_retries_once_with_identical_request_then_stops(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    payloads = []

    def unavailable(payload):
        payloads.append(payload)
        raise agent_model_client.ConnectorError("Trae proxy is unavailable")

    first = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3), generate=unavailable,
        clock=lambda: NOW + timedelta(minutes=4), **READY,
    )
    second = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=5), generate=unavailable,
        clock=lambda: NOW + timedelta(minutes=6), **READY,
    )
    assert first["retried"] == 1 and second["unavailable"] == 1
    assert payloads[0] == payloads[1]
    con = db.connect(database, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM p16_filing_decisions").fetchone() == (1,)
    assert con.execute(
        "SELECT COUNT(DISTINCT request_sha256) FROM p16_filing_score_attempts"
    ).fetchone() == (1,)
    con.close()


def _strand_attempt(database, attempt_number):
    con = db.connect(database)
    claimed = store.claim_score_capacity(
        con, session_date=NOW.date(), now=NOW + timedelta(minutes=3), batch_size=1,
    )["claimed"]
    work = runner._work(con, claimed[0])
    payload = runner.build_input(con, work, cutoff_at=NOW + timedelta(minutes=3))
    request = client.request_payload(payload)
    store.record_score_attempt(
        con, work_id=work["work_id"], started_at=NOW + timedelta(minutes=3),
        request_payload=request, runtime_identity=client.identity(),
    )
    if attempt_number == 2:
        store.append_work_event(
            con, policy_id=work["policy_id"], work_kind="score", accession=work["accession"],
            security_id=work["security_id"], session_date=work["session_date"], status="retry",
            event_at=NOW + timedelta(minutes=4), not_before=NOW + timedelta(minutes=4),
            input_payload=json.loads(work["input_json"]), reason="transport_lost",
        )
        store.claim_score_capacity(
            con, session_date=NOW.date(), now=NOW + timedelta(minutes=5), batch_size=1,
        )
        store.record_score_attempt(
            con, work_id=work["work_id"], started_at=NOW + timedelta(minutes=5),
            request_payload=request, runtime_identity=client.identity(),
        )
    con.close()


def test_orphaned_first_attempt_retries_identically(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    _strand_attempt(database, 1)
    result = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=6), generate=_result,
        clock=lambda: NOW + timedelta(minutes=7), **READY,
    )
    assert result["scored"] == 1
    con = db.connect(database, read_only=True)
    assert con.execute("SELECT COUNT(*),COUNT(DISTINCT request_sha256) "
                       "FROM p16_filing_score_attempts").fetchone() == (2, 1)
    con.close()


def test_orphaned_second_attempt_is_terminal_without_third_call(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    _strand_attempt(database, 2)
    result = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=6),
        generate=lambda _payload: pytest.fail("third call is forbidden"),
        clock=lambda: NOW + timedelta(minutes=7), **READY,
    )
    assert result["unavailable"] == 1 and result["model_calls"] == 0
    con = db.connect(database, read_only=True)
    assert con.execute("SELECT reason FROM p16_filing_decisions").fetchone() == (
        "transport:orphaned_call",
    )
    con.close()


def test_orphaned_prior_session_attempt_is_recovered(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    _strand_attempt(database, 1)
    con = db.connect(database)
    con.execute("UPDATE p16_filing_work_events SET session_date=?", [NOW.date() - timedelta(days=1)])
    con.close()
    result = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=6),
        generate=lambda _payload: pytest.fail("prior-session work must not run today"),
        clock=lambda: NOW + timedelta(minutes=7), **READY,
    )
    assert result["model_calls"] == 0
    con = db.connect(database, read_only=True)
    assert con.execute(
        "SELECT status FROM p16_filing_work_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone() == ("unavailable",)
    assert con.execute("SELECT reason FROM p16_filing_decisions").fetchone() == (
        "transport:orphaned_prior_session",
    )
    con.close()


def test_score_pending_rejects_naive_external_timestamp(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    with pytest.raises(runner.FilingRunError, match="timezone"):
        runner.score_pending(
            database, observed_at=NOW.replace(tzinfo=None), generate=_result, **READY,
        )


def test_exchange_session_date_survives_next_utc_day(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    evening = datetime(2026, 9, 28, 2, tzinfo=timezone.utc)
    result = runner.score_pending(
        database, observed_at=evening, generate=_result,
        clock=lambda: evening + timedelta(minutes=1), **READY,
    )
    assert result["scored"] == 1


@pytest.mark.parametrize("target", [
    "normalized", "evidence", "components", "scope", "accession", "response", "receipt",
    "receipt_metadata",
])
def test_build_input_rejects_tampered_retained_lineage(tmp_path, target):
    database = tmp_path / f"{target}.duckdb"
    _database(database)
    con = db.connect(database)
    if target in {"normalized", "evidence"}:
        value = json.loads(con.execute(
            "SELECT normalized_json FROM p16_filing_bundles"
        ).fetchone()[0])
        if target == "normalized":
            value["spans"][0]["text"] += " altered"
        else:
            value["spans"][0]["evidence_id"] = "0" * 64
        con.execute("UPDATE p16_filing_bundles SET normalized_json=?", [json.dumps(value)])
    elif target == "components":
        value = json.loads(con.execute(
            "SELECT components_json FROM p16_filing_bundles"
        ).fetchone()[0])
        value[0]["byte_count"] += 1
        con.execute("UPDATE p16_filing_bundles SET components_json=?", [json.dumps(value)])
    elif target == "scope":
        value = json.loads(con.execute("SELECT universe_json FROM p16_filing_scans").fetchone()[0])
        value["0000320193"]["security_tickers"]["AAPL"] = "MSFT"
        con.execute("UPDATE p16_filing_scans SET universe_json=?", [json.dumps(value)])
    elif target == "accession":
        con.execute("UPDATE p16_filing_accessions SET primary_security_id='MSFT'")
    elif target == "response":
        con.execute("UPDATE p16_filing_cik_responses SET accessions_json='[]'")
    elif target == "receipt":
        receipt = con.execute("SELECT receipt_sha256 FROM p16_filing_cik_responses").fetchone()[0]
        con.execute(
            "UPDATE source_response_receipts SET response_body=? WHERE receipt_sha256=?",
            [b"tampered", receipt],
        )
    else:
        receipt = con.execute("SELECT receipt_sha256 FROM p16_filing_cik_responses").fetchone()[0]
        con.execute(
            "UPDATE source_response_receipts SET content_type='text/plain' WHERE receipt_sha256=?",
            [receipt],
        )
    work_id = con.execute(
        "SELECT work_id FROM p16_filing_work_events WHERE status='queued' AND work_kind='score'"
    ).fetchone()[0]
    with pytest.raises(runner.FilingRunError, match="identity|lineage"):
        runner.build_input(con, runner._work(con, work_id), cutoff_at=NOW + timedelta(minutes=3))
    con.close()


def test_invalid_model_response_retains_error_provenance(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)

    def invalid(_payload):
        error = agent_model_client.ModelOutputError(
            "bad output", response_id="response-bad", request_sha256="a" * 64,
            response_sha256="b" * 64,
            usage={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
        )
        error.raw_response_sha256 = "c" * 64
        raise error

    runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3), generate=invalid,
        clock=lambda: NOW + timedelta(minutes=4), **READY,
    )
    con = db.connect(database, read_only=True)
    payload = json.loads(con.execute("SELECT response_json FROM p16_filing_decisions").fetchone()[0])
    assert payload["response_id"] == "response-bad"
    assert payload["response_sha256"] == "b" * 64
    assert payload["raw_response_sha256"] == "c" * 64
    con.close()


def test_terminal_transport_response_retains_raw_provenance(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)

    def rejected(_payload):
        error = agent_model_client.ConnectorError("Trae proxy returned HTTP 500")
        error.raw_response_sha256 = "d" * 64
        raise error

    result = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3), generate=rejected,
        clock=lambda: NOW + timedelta(minutes=4), **READY,
    )
    assert result["unavailable"] == 1 and result["retried"] == 0
    con = db.connect(database, read_only=True)
    payload = json.loads(con.execute("SELECT response_json FROM p16_filing_decisions").fetchone()[0])
    assert payload["raw_response_sha256"] == "d" * 64
    con.close()


def test_identity_drift_is_terminal_without_retry(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    result = runner.score_pending(
        database, observed_at=NOW + timedelta(minutes=3),
        generate=lambda payload: _result(payload, drift=True),
        clock=lambda: NOW + timedelta(minutes=4), **READY,
    )
    assert result["unavailable"] == 1 and result["retried"] == 0
    con = db.connect(database, read_only=True)
    assert con.execute(
        "SELECT reason FROM p16_filing_decisions"
    ).fetchone()[0].startswith("invalid:filing model identity differs")
    payload = json.loads(con.execute("SELECT response_json FROM p16_filing_decisions").fetchone()[0])
    assert payload["raw_response_sha256"] == "f" * 64
    con.close()
