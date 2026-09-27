"""Durable W3 filing response-set, bundle, and work-state tests."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts
from engine import p16_filing_sources as sources
from engine.lib.provenance import canonical_sha256
from server import p16_filing_store as store

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
ACCESSION = "0000320193-26-000001"
AMENDMENT = "0000320193-26-000002"
MAP_BODY = b"map.json"
MAP_SHA256 = hashlib.sha256(MAP_BODY).hexdigest()


def _response(payload, *, at=NOW, status=200, body=None):
    raw = json.dumps(payload).encode() if body is None else body
    return sources.SecResponse(status, "application/json", {}, raw, at, at,
                               sources.submissions_url(320193), len(raw), True)


def _payload(accessions=(ACCESSION,), *, items="2.02"):
    size = len(accessions)
    return {"cik": 320193, "filings": {"recent": {
        "accessionNumber": list(accessions),
        "acceptanceDateTime": ["untrusted"] * size,
        "filingDate": ["2026-09-27"] * size,
        "form": ["8-K"] * size, "items": [items] * size,
        "primaryDocument": [f"filing-{index}.htm" for index in range(size)],
        "reportDate": ["2026-06-30"] * size,
    }}}


def _scan(con, *, at=NOW, securities=None):
    store.init_schema(con)
    return store.start_scan(
        con, policy_id=store.POLICY_ID, session_date=at.date(),
        activation_at=NOW - timedelta(hours=1), started_at=at,
        universe={"0000320193": {"entered_at": (NOW - timedelta(hours=1)).isoformat(),
                                 "securities": securities or ["AAPL"],
                                 "security_tickers": {
                                     item: item for item in (securities or ["AAPL"])
                                 },
                                 "selection_sha256": "e" * 64,
                                 "primary_security_id": (securities or ["AAPL"])[0]}},
        map_sha256=MAP_SHA256,
    )


def _commit(con, scan_id, payload, *, at=NOW, response=None, after_response=None):
    response = response or _response(payload, at=at)
    return store.commit_cik_success(
        con, scan_id=scan_id, cik="0000320193", response=response,
        request_payload={"scan_id": scan_id, "cik": "0000320193"}, ingested_at=at,
        after_response=after_response,
    )


def test_cik_success_atomically_binds_prior_set_and_pending_work(con):
    scan_id = _scan(con)
    result = _commit(con, scan_id, _payload())
    assert result["queued"] == 1
    response_row = con.execute(
        "SELECT accessions_sha256,previous_response_id FROM p16_filing_cik_responses"
    ).fetchone()
    accession = con.execute(
        "SELECT previous_accessions_sha256,discovery_status FROM p16_filing_accessions"
    ).fetchone()
    assert response_row == (canonical_sha256([ACCESSION]), None)
    assert accession == (canonical_sha256([]), "acceptance_pending_crosscheck")
    pending = store.pending_work(con, work_kind="acceptance", now=NOW)
    assert len(pending) == 1 and pending[0]["accession"] == ACCESSION


def test_failure_after_response_rolls_back_every_cik_row(con):
    scan_id = _scan(con)

    def fail():
        raise RuntimeError("injected crash")

    with pytest.raises(RuntimeError, match="injected"):
        _commit(con, scan_id, _payload(), after_response=fail)
    for table in ("p16_filing_cik_responses", "p16_filing_accessions",
                  "p16_filing_work_events", "source_response_receipts"):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_invalid_response_does_not_advance_and_verified_304_reuses_identity(con):
    first_scan = _scan(con)
    payload = _payload()
    _commit(con, first_scan, payload)
    bad_scan = _scan(con, at=NOW + timedelta(minutes=1))
    failed = _response(payload, at=NOW + timedelta(minutes=1), status=500)
    with pytest.raises(ValueError, match="untrusted"):
        _commit(con, bad_scan, payload, at=NOW + timedelta(minutes=1), response=failed)
    assert con.execute("SELECT COUNT(*) FROM p16_filing_cik_responses").fetchone() == (1,)
    third_scan = _scan(con, at=NOW + timedelta(minutes=2))
    not_modified = _response(payload, at=NOW + timedelta(minutes=2), status=304, body=b"")
    result = _commit(
        con, third_scan, payload, at=NOW + timedelta(minutes=2), response=not_modified,
    )
    rows = con.execute(
        "SELECT response_id,previous_response_id,reused_response_id,source_body_sha256 "
        "FROM p16_filing_cik_responses ORDER BY received_at"
    ).fetchall()
    assert result["queued"] == 0 and rows[1][1] == rows[0][0] == rows[1][2]
    assert rows[1][3] == rows[0][3]


def test_reappearance_changed_bytes_amendment_and_same_day_are_distinct(con):
    first = _scan(con)
    _commit(con, first, _payload())
    second = _scan(con, at=NOW + timedelta(minutes=1))
    changed = _payload((ACCESSION, AMENDMENT), items="2.02,7.01")
    result = _commit(con, second, changed, at=NOW + timedelta(minutes=1))
    assert result["queued"] == 1
    rows = con.execute(
        "SELECT accession,previous_response_id,discovery_status FROM p16_filing_accessions "
        "ORDER BY accession"
    ).fetchall()
    assert rows[0][0] == ACCESSION and rows[1][0] == AMENDMENT
    assert rows[1][1] is not None and rows[1][2] == "acceptance_pending_crosscheck"
    assert con.execute("SELECT COUNT(*) FROM p16_filing_work_events").fetchone() == (2,)


def _record_receipt(
    con, name, at, *, dataset="filing_document", accession=ACCESSION,
    size=1, body=None, http_status=200,
):
    if body is None and dataset == "filing_index":
        body = (f"<html><body><div>Accession Number: {accession}</div>"
                "<div>Accepted: 2026-09-27 08:01:00</div></body></html>").encode()
    body = name.encode() * size if body is None else body
    endpoint = (sources.TICKER_MAP_URL if dataset == "ticker_map" else
                sources.archive_url(320193, accession, name))
    return bitemporal_facts.record_receipt(
        con, source="sec-edgar", dataset=dataset, endpoint=endpoint,
        request={"name": name}, requested_at=at, received_at=at,
        http_status=http_status, content_type="text/html", body=body, license_class="public",
    )["receipt_sha256"]


def _receipt_size(con, receipt_sha256):
    return con.execute(
        "SELECT response_size_bytes FROM source_response_receipts WHERE receipt_sha256=?",
        [receipt_sha256],
    ).fetchone()[0]


def _ready_bundle(con, *, at=NOW + timedelta(minutes=2)):
    scan_id = _scan(con)
    _commit(con, scan_id, _payload())
    map_receipt = _record_receipt(con, "map.json", NOW, dataset="ticker_map", accession=None)
    index_receipt = _record_receipt(
        con, f"{ACCESSION}-index.htm", at, dataset="filing_index",
    )
    primary_receipt = _record_receipt(con, "primary.htm", at)
    store.record_acceptance(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        index_receipt_sha256=index_receipt, resolved_at=at,
    )
    components = [
        {"role": "map", "accession": None, "receipt_sha256": map_receipt,
         "received_at": NOW.isoformat(), "ingested_at": NOW.isoformat(),
         "byte_count": _receipt_size(con, map_receipt)},
        {"role": "acceptance_index", "accession": ACCESSION,
         "receipt_sha256": index_receipt,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": _receipt_size(con, index_receipt)},
        {"role": "primary", "accession": ACCESSION, "receipt_sha256": primary_receipt,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": _receipt_size(con, primary_receipt)},
    ]
    bundle = store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION, components=components,
        normalized_payload={"cik": "0000320193", "accession": ACCESSION},
        status="primary_only", exhibit_status="absent",
    )
    return bundle, at


def test_bundle_uses_latest_required_receipt_and_first_bundle_for_dual_classes(con):
    scan_id = _scan(con, securities=["GOOG", "GOOGL"])
    _commit(con, scan_id, _payload())
    map_at = NOW
    first_at, last_at = NOW + timedelta(minutes=2), NOW + timedelta(minutes=3)
    map_receipt = _record_receipt(con, "map.json", map_at, dataset="ticker_map", accession=None)
    index_receipt = _record_receipt(con, f"{ACCESSION}-index.htm", first_at,
                                    dataset="filing_index")
    first_receipt = _record_receipt(con, "primary.htm", first_at)
    last_receipt = _record_receipt(con, "exhibit.htm", last_at)
    store.record_acceptance(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        index_receipt_sha256=index_receipt, resolved_at=first_at,
    )
    components = [
        {"role": "map", "accession": None, "receipt_sha256": map_receipt,
         "received_at": map_at.isoformat(), "ingested_at": map_at.isoformat(),
         "byte_count": len(b"map.json")},
        {"role": "acceptance_index", "accession": ACCESSION,
         "receipt_sha256": index_receipt,
         "received_at": first_at.isoformat(), "ingested_at": first_at.isoformat(),
         "byte_count": _receipt_size(con, index_receipt)},
        {"role": "primary", "accession": ACCESSION, "receipt_sha256": first_receipt,
         "received_at": first_at.isoformat(), "ingested_at": first_at.isoformat(),
         "byte_count": len(b"primary.htm")},
        {"role": "exhibit", "accession": ACCESSION, "receipt_sha256": last_receipt,
         "received_at": last_at.isoformat(), "ingested_at": last_at.isoformat(),
         "byte_count": len(b"exhibit.htm")},
    ]
    first_bundle = store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        components=components,
        normalized_payload={"cik": "0000320193", "accession": ACCESSION, "text": "first"},
        status="complete", exhibit_status="ex99_1",
    )
    assert store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        components=list(reversed(components)),
        normalized_payload={"cik": "0000320193", "accession": ACCESSION, "text": "first"},
        status="complete", exhibit_status="ex99_1",
    ) == first_bundle
    changed_bundle = store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        components=components,
        normalized_payload={"cik": "0000320193", "accession": ACCESSION, "text": "changed"},
        status="complete", exhibit_status="ex99_1",
    )
    assert changed_bundle != first_bundle
    assert con.execute(
        "SELECT available_at FROM p16_filing_bundles WHERE bundle_sha256=?", [first_bundle]
    ).fetchone()[0] == last_at.replace(tzinfo=None)
    work_ids = store.queue_score_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        security_ids=["GOOG", "GOOGL"], session_date=NOW.date(), queued_at=last_at,
    )
    assert len(set(work_ids)) == 2
    payloads = [json.loads(row[0]) for row in con.execute(
        "SELECT input_json FROM p16_filing_work_events WHERE work_kind='score' ORDER BY security_id"
    ).fetchall()]
    assert {item["bundle_sha256"] for item in payloads} == {first_bundle}


def test_acceptance_and_bundle_require_exact_successful_frozen_receipts(con):
    scan_id = _scan(con)
    _commit(con, scan_id, _payload())
    at = NOW + timedelta(minutes=2)
    wrong_index = _record_receipt(
        con, f"{ACCESSION}-index.htm", at, dataset="filing_index",
        body=b"<html><body>Accepted: 2026-09-27 08:01:00</body></html>",
    )
    with pytest.raises(ValueError, match="accession differs"):
        store.record_acceptance(
            con, policy_id=store.POLICY_ID, accession=ACCESSION,
            index_receipt_sha256=wrong_index, resolved_at=at,
        )

    index_receipt = _record_receipt(
        con, f"{ACCESSION}-index.htm", at, dataset="filing_index",
    )
    store.record_acceptance(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        index_receipt_sha256=index_receipt, resolved_at=at,
    )
    map_receipt = _record_receipt(con, "map.json", NOW, dataset="ticker_map", accession=None)
    primary = _record_receipt(con, "primary.htm", at)
    components = [
        {"role": "map", "accession": None, "receipt_sha256": map_receipt,
         "received_at": NOW.isoformat(), "ingested_at": NOW.isoformat(),
         "byte_count": _receipt_size(con, map_receipt)},
        {"role": "acceptance_index", "accession": ACCESSION,
         "receipt_sha256": index_receipt,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": _receipt_size(con, index_receipt)},
        {"role": "primary", "accession": ACCESSION, "receipt_sha256": primary,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": _receipt_size(con, primary)},
    ]
    bad_map = _record_receipt(
        con, "other-map.json", NOW, dataset="ticker_map", accession=None,
    )
    wrong_map_components = [dict(item) for item in components]
    wrong_map_components[0].update(
        receipt_sha256=bad_map, byte_count=_receipt_size(con, bad_map),
    )
    normalized = {"cik": "0000320193", "accession": ACCESSION}
    with pytest.raises(ValueError, match="receipt is unavailable"):
        store.record_bundle(
            con, policy_id=store.POLICY_ID, accession=ACCESSION,
            components=wrong_map_components, normalized_payload=normalized,
            status="primary_only", exhibit_status="absent",
        )

    failed_primary = _record_receipt(
        con, "failed-primary.htm", at, http_status=404,
    )
    failed_components = [dict(item) for item in components]
    failed_components[2].update(
        receipt_sha256=failed_primary,
        byte_count=_receipt_size(con, failed_primary),
    )
    with pytest.raises(ValueError, match="receipt is unavailable"):
        store.record_bundle(
            con, policy_id=store.POLICY_ID, accession=ACCESSION,
            components=failed_components, normalized_payload=normalized,
            status="primary_only", exhibit_status="absent",
        )


def test_score_capacity_marks_every_excess_row_unavailable(con):
    security_ids = [f"CLASS-{index:02d}" for index in range(65)]
    scan_id = _scan(con, securities=security_ids)
    _commit(con, scan_id, _payload())
    at = NOW + timedelta(minutes=2)
    map_receipt = _record_receipt(con, "map.json", NOW, dataset="ticker_map", accession=None)
    index_receipt = _record_receipt(con, f"{ACCESSION}-index.htm", at, dataset="filing_index")
    receipt = _record_receipt(con, "primary.htm", at)
    store.record_acceptance(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        index_receipt_sha256=index_receipt, resolved_at=at,
    )
    components = [
        {"role": "map", "accession": None, "receipt_sha256": map_receipt,
         "received_at": NOW.isoformat(), "ingested_at": NOW.isoformat(),
         "byte_count": len(b"map.json")},
        {"role": "acceptance_index", "accession": ACCESSION,
         "receipt_sha256": index_receipt,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": _receipt_size(con, index_receipt)},
        {"role": "primary", "accession": ACCESSION, "receipt_sha256": receipt,
         "received_at": at.isoformat(), "ingested_at": at.isoformat(),
         "byte_count": len(b"primary.htm")},
    ]
    bundle = store.record_bundle(
        con, policy_id=store.POLICY_ID, accession=ACCESSION, components=components,
        normalized_payload={"cik": "0000320193", "accession": ACCESSION},
        status="primary_only", exhibit_status="absent",
    )
    store.queue_score_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        security_ids=security_ids[:5],
        session_date=NOW.date(), queued_at=at,
    )
    first = store.claim_score_capacity(
        con, session_date=NOW.date(), now=NOW + timedelta(minutes=2),
    )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="CLASS-00", session_date=NOW.date(), status="retry",
        event_at=at + timedelta(seconds=1), not_before=at + timedelta(seconds=1),
        input_payload={"bundle_sha256": bundle, "security_id": "CLASS-00"},
        reason="transport_lost",
    )
    store.queue_score_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        security_ids=security_ids[5:], session_date=NOW.date(),
        queued_at=NOW + timedelta(minutes=3),
    )
    second = store.claim_score_capacity(
        con, session_date=NOW.date(), now=NOW + timedelta(minutes=4),
    )
    assert len(first["claimed"]) == 5
    assert len(second["claimed"]) == 56
    assert len(second["capacity_unavailable"]) == 5
    assert con.execute(
        "SELECT COUNT(DISTINCT work_id) FROM p16_filing_work_events WHERE status='started'"
    ).fetchone() == (60,)
    assert con.execute(
        "SELECT COUNT(*) FROM p16_filing_work_events WHERE reason='capacity_unavailable'"
    ).fetchone() == (5,)


def test_work_retry_is_once_and_input_identity_is_immutable(con):
    _scan(con)
    work_id = store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="AAPL", session_date=NOW.date(), status="queued",
        event_at=NOW, not_before=NOW, input_payload={"request": "same"},
    )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="AAPL", session_date=NOW.date(), status="started",
        event_at=NOW, not_before=NOW, input_payload={"request": "same"},
    )
    with pytest.raises(ValueError, match="requires lost transport"):
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
            security_id="AAPL", session_date=NOW.date(), status="retry",
            event_at=NOW, not_before=NOW, input_payload={"request": "same"},
            reason="invalid_output",
        )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="AAPL", session_date=NOW.date(), status="retry",
        event_at=NOW, not_before=NOW, input_payload={"request": "same"},
        reason="transport_lost",
    )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="AAPL", session_date=NOW.date(), status="started",
        event_at=NOW, not_before=NOW, input_payload={"request": "same"},
    )
    with pytest.raises(ValueError, match="identity differs"):
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
            security_id="AAPL", session_date=NOW.date(), status="unavailable",
            event_at=NOW, not_before=NOW, input_payload={"request": "changed"},
        )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
        security_id="AAPL", session_date=NOW.date(), status="unavailable",
        event_at=NOW, not_before=NOW, input_payload={"request": "same"}, reason="transport_lost",
    )
    with pytest.raises(ValueError, match="terminal"):
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="score", accession=ACCESSION,
            security_id="AAPL", session_date=NOW.date(), status="retry",
            event_at=NOW, not_before=NOW, input_payload={"request": "same"},
        )
    assert work_id


def test_sec_retries_use_registered_durable_delays(con):
    _scan(con)
    payload = {"request": "same"}
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
        session_date=NOW.date(), status="queued", event_at=NOW, not_before=NOW,
        input_payload=payload,
    )
    current = NOW
    for delay in (5, 30, 120):
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
            session_date=NOW.date(), status="started", event_at=current, not_before=current,
            input_payload=payload,
        )
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
            session_date=NOW.date(), status="retry", event_at=current,
            not_before=current + timedelta(seconds=delay), input_payload=payload,
        )
        current += timedelta(seconds=delay)
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
        session_date=NOW.date(), status="started", event_at=current, not_before=current,
        input_payload=payload,
    )
    with pytest.raises(ValueError, match="retry exhausted"):
        store.append_work_event(
            con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
            session_date=NOW.date(), status="retry", event_at=current,
            not_before=current + timedelta(seconds=120), input_payload=payload,
        )


def test_score_attempt_decision_and_label_are_append_only(con):
    _bundle, available_at = _ready_bundle(con)
    with pytest.raises(ValueError, match="predates its filing bundle"):
        store.queue_score_work(
            con, policy_id=store.POLICY_ID, accession=ACCESSION,
            security_ids=["AAPL"], session_date=NOW.date(),
            queued_at=available_at - timedelta(microseconds=1),
        )
    work_id = store.queue_score_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        security_ids=["AAPL"], session_date=NOW.date(), queued_at=available_at,
    )[0]
    started_at = available_at + timedelta(seconds=1)
    claimed = store.claim_score_capacity(
        con, session_date=NOW.date(), now=started_at,
    )
    assert claimed["claimed"] == [work_id]
    request = {"filing": ACCESSION}
    runtime = {"model": "fixed"}
    attempt = store.record_score_attempt(
        con, work_id=work_id, started_at=started_at,
        request_payload=request, runtime_identity=runtime,
    )
    decided_at = started_at + timedelta(seconds=2)
    decision = store.record_decision(
        con, attempt_sha256=attempt, status="scored",
        decided_at=decided_at, response_payload={"score": 0.6},
    )
    assert con.execute(
        "SELECT model_latency_ms,retrieval_latency_ms FROM p16_filing_decisions"
    ).fetchone() == (2_000, 3_000)
    label = store.record_label(
        con, decision_sha256=decision, horizon=5, entry_basis="next_session_open",
        labelled_at=decided_at + timedelta(days=6),
        payload={"status": "available", "price_series_sha256": "b" * 64, "net_excess": 0.1},
    )
    assert label == store.record_label(
        con, decision_sha256=decision, horizon=5, entry_basis="next_session_open",
        labelled_at=decided_at + timedelta(days=6),
        payload={"status": "available", "price_series_sha256": "b" * 64, "net_excess": 0.1},
    )
    with pytest.raises(ValueError, match="decision replay differs"):
        store.record_decision(
            con, attempt_sha256=attempt, status="scored",
            decided_at=decided_at + timedelta(seconds=1), response_payload={"score": 0.7},
        )


def test_selected_exhibit_404_is_derived_from_durable_work(con):
    scan_id = _scan(con)
    _commit(con, scan_id, _payload())
    index = _record_receipt(con, f"{ACCESSION}-index.htm", NOW, dataset="filing_index")
    work_id = store.queue_document_work(
        con, policy_id=store.POLICY_ID, accession=ACCESSION, session_date=NOW.date(),
        queued_at=NOW, index_receipt_sha256=index, selected_exhibit="release.htm",
    )
    payload = {"index_receipt_sha256": index, "selected_exhibit": "release.htm"}
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
        session_date=NOW.date(), status="started", event_at=NOW, not_before=NOW,
        input_payload=payload,
    )
    store.append_work_event(
        con, policy_id=store.POLICY_ID, work_kind="document", accession=ACCESSION,
        session_date=NOW.date(), status="retry", event_at=NOW,
        not_before=NOW + timedelta(seconds=5), input_payload=payload, reason="http_404",
    )
    assert work_id
    assert store.exhibit_retry_status(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        observed_at=NOW + timedelta(minutes=14, seconds=59),
    ) == "pending"
    assert store.exhibit_retry_status(
        con, policy_id=store.POLICY_ID, accession=ACCESSION,
        observed_at=NOW + timedelta(minutes=15),
    ) == "extraction_unavailable"
