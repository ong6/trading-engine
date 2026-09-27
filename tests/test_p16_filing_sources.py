"""W3/W4 shared SEC dispatcher and discovery contract tests."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from engine import p16_filing_sources as sources

NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
ACCESSION = "0000320193-26-000001"
CONTACT = {"TRADING_ENGINE_SEC_USER_AGENT": "Research contact@example.test"}


class FakeClock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def request(clock, *, name="one", consumer="p16-filings", url=None):
    return sources.SecRequest(
        name, "scan-a", consumer, "submissions", url or sources.submissions_url(320193), 1,
        clock(), clock(),
    )


def response(clock, req, *, status=200, headers=None, body=b"{}", final_url=None,
             complete=True, observed=None):
    return sources.SecResponse(
        status, "application/json", headers or {}, body, clock(), clock(),
        final_url or req.url, len(body) if observed is None else observed, complete,
    )


def test_contact_gate_prevents_every_network_and_state_call(tmp_path):
    calls = []
    with pytest.raises(sources.SecUnavailable, match="unconfigured"):
        sources.dispatch(
            request(FakeClock()), load_state=lambda: calls.append("state"),
            append_event=calls.append, fetch=lambda *_: calls.append("fetch"),
            lock_path=tmp_path / "lock", environ={},
        )
    assert calls == []


def test_dispatch_spacing_is_shared_across_w3_and_w4_without_writer_hold(tmp_path):
    clock, starts = FakeClock(), []
    events = {"p16-filings": [], "p16-textlab": []}
    writer_open = False

    def load_state(consumer):
        nonlocal writer_open
        writer_open = True
        state = {"scan_starts": len(events[consumer]),
                 "scan_id": "scan-a", "scan_started_at": NOW}
        writer_open = False
        return state

    def append(consumer, event):
        nonlocal writer_open
        writer_open = True
        events[consumer].append(event)
        writer_open = False

    def fetch(url, user_agent):
        assert not writer_open and user_agent == CONTACT["TRADING_ENGINE_SEC_USER_AGENT"]
        starts.append(clock())
        return response(clock, request(clock, url=url))

    def sleep(seconds):
        assert not writer_open
        clock.sleep(seconds)

    for consumer in ("p16-filings", "p16-textlab"):
        req = request(clock, name=consumer, consumer=consumer)
        sources.dispatch(req, load_state=lambda consumer=consumer: load_state(consumer),
                         append_event=lambda event, consumer=consumer: append(consumer, event), fetch=fetch,
                         clock=clock, sleep=sleep, lock_path=tmp_path / "lock", environ=CONTACT)
    assert starts[1] - starts[0] == timedelta(milliseconds=250)
    assert [events[name][0]["consumer"] for name in events] == ["p16-filings", "p16-textlab"]
    assert {event["request_kind"] for rows in events.values() for event in rows} == {"submissions"}
    assert {event["scan_id"] for rows in events.values() for event in rows} == {"scan-a"}


def test_dispatch_lock_serializes_contending_consumers(tmp_path):
    clock, events = FakeClock(), []
    entered, release = threading.Event(), threading.Event()
    active = maximum = 0
    guard = threading.Lock()

    def load_state():
        return {"scan_id": "scan-a", "scan_started_at": NOW,
                "scan_starts": sum(event["event_kind"] == "started" for event in events)}

    def fetch(url, _user_agent):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
            first = len([event for event in events if event["event_kind"] == "started"]) == 1
        if first:
            entered.set()
            assert release.wait(2)
        result = response(clock, request(clock, url=url))
        with guard:
            active -= 1
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sources.dispatch, request(clock, name="w3"),
                            load_state=load_state, append_event=events.append, fetch=fetch,
                            clock=clock, sleep=clock.sleep, lock_path=tmp_path / "lock",
                            environ=CONTACT)
        assert entered.wait(2)
        second = pool.submit(sources.dispatch, request(clock, name="w4", consumer="p16-textlab"),
                             load_state=load_state, append_event=events.append, fetch=fetch,
                             clock=clock, sleep=clock.sleep, lock_path=tmp_path / "lock",
                             environ=CONTACT)
        time.sleep(0.02)
        assert not second.done()
        release.set()
        first.result()
        second.result()
    assert maximum == 1


def test_scan_lease_refuses_overlap(tmp_path):
    with sources.scan_lease(tmp_path / "scan.lock"):
        with pytest.raises(sources.SecUnavailable, match="scan_in_progress"):
            with sources.scan_lease(tmp_path / "scan.lock"):
                pass


@pytest.mark.parametrize(
    ("state", "reason"),
    [({"scan_starts": 240}, "scan_request_cap"),
     ({}, "scan_wall_cap"),
     ({"pause_until": NOW + timedelta(minutes=1)}, "dispatcher_paused")],
)
def test_dispatch_caps_and_pause_prevent_calls(tmp_path, state, reason):
    clock, calls = FakeClock(NOW + (timedelta(seconds=240) if reason == "scan_wall_cap" else timedelta())) , []
    state = {"scan_id": "scan-a", "scan_started_at": NOW, **state}
    req = sources.SecRequest("cap", "scan-a", "p16-filings", "submissions",
                             sources.submissions_url(320193), 1, NOW, NOW)
    with pytest.raises(sources.SecUnavailable, match=reason):
        sources.dispatch(req, load_state=lambda: state, append_event=calls.append,
                         fetch=lambda *_: calls.append("fetch"), clock=clock,
                         lock_path=tmp_path / reason, environ=CONTACT)
    assert calls == []


@pytest.mark.parametrize(
    ("status", "state", "headers", "expected_reason", "expected_pause"),
    [(429, {}, {"Retry-After": "7"}, "http_429", NOW + timedelta(seconds=7)),
     (403, {"session_403_count": 1, "next_session_at": NOW + timedelta(days=1)}, {},
      "repeated_403", NOW + timedelta(days=1))],
)
def test_backoff_is_durable_and_never_retries_inline(
    tmp_path, status, state, headers, expected_reason, expected_pause,
):
    clock, events, calls = FakeClock(), [], []
    state = {"scan_id": "scan-a", "scan_started_at": NOW, **state}
    req = request(clock, name=str(status))

    def fetch(_url, _user_agent):
        calls.append(status)
        return response(clock, req, status=status, headers=headers)

    sources.dispatch(req, load_state=lambda: state, append_event=events.append,
                     fetch=fetch, clock=clock, lock_path=tmp_path / str(status), environ=CONTACT)
    assert calls == [status]
    assert events[-1]["reason"] == expected_reason
    assert events[-1]["pause_until"] == expected_pause.isoformat()


def test_shared_backoff_survives_et_session_rollover(tmp_path):
    clock, events = FakeClock(), []
    first = request(clock, name="w3")
    sources.dispatch(
        first, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW},
        append_event=events.append,
        fetch=lambda *_: response(clock, first, status=429, headers={"Retry-After": "90000"}),
        clock=clock, lock_path=tmp_path / "shared", environ=CONTACT,
    )
    clock.now = NOW + timedelta(days=1)
    second = sources.SecRequest(
        "w4", "scan-b", "p16-textlab", "submissions", sources.submissions_url(320193),
        1, clock(), clock(),
    )
    with pytest.raises(sources.SecUnavailable, match="dispatcher_paused"):
        sources.dispatch(
            second, load_state=lambda: {"scan_id": "scan-b", "scan_started_at": clock()},
            append_event=events.append, fetch=lambda *_: pytest.fail("must stay paused"),
            clock=clock, lock_path=tmp_path / "shared", environ=CONTACT,
        )


def test_repeated_403_without_calendar_state_blocks_and_alerts(tmp_path):
    clock, events = FakeClock(), []
    req = request(clock)
    sources.dispatch(
        req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW,
                                 "session_403_count": 1},
        append_event=events.append,
        fetch=lambda *_: response(clock, req, status=403), clock=clock,
        lock_path=tmp_path / "403", environ=CONTACT,
    )
    assert events[-1]["event_kind"] == "response"
    assert events[-1]["blocked"] is True and events[-1]["alert"] is True
    assert events[-1]["pause_until"] is None


def test_repeated_403_with_past_session_state_also_blocks(tmp_path):
    clock, events = FakeClock(), []
    req = request(clock)
    sources.dispatch(
        req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW,
                                 "session_403_count": 1,
                                 "next_session_at": NOW - timedelta(seconds=1)},
        append_event=events.append, fetch=lambda *_: response(clock, req, status=403),
        clock=clock, lock_path=tmp_path / "403-past", environ=CONTACT,
    )
    assert events[-1]["reason"] == "repeated_403_calendar_unavailable"
    assert events[-1]["blocked"] is True


def test_scan_deadline_is_rechecked_after_reservation(tmp_path):
    clock, events, calls = FakeClock(NOW + timedelta(seconds=239)), [], []
    req = sources.SecRequest("late", "scan-a", "p16-filings", "submissions",
                             sources.submissions_url(320193), 1, clock(), NOW)

    def append(event):
        events.append(event)
        if event["event_kind"] == "started":
            clock.sleep(1)

    with pytest.raises(sources.SecUnavailable, match="scan_wall_cap"):
        sources.dispatch(
            req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW},
            append_event=append, fetch=lambda *_: calls.append("fetch"), clock=clock,
            lock_path=tmp_path / "deadline", environ=CONTACT,
        )
    assert calls == [] and events[-1]["event_kind"] == "failed"


def test_url_and_redirect_guards_reject_untrusted_locations(tmp_path):
    clock, calls = FakeClock(), []
    bad = request(clock, url="https://example.test/Archives/edgar/data/1/file.htm")
    with pytest.raises(sources.SecUnavailable, match="invalid_sec_url"):
        sources.dispatch(bad, load_state=dict, append_event=calls.append,
                         lock_path=tmp_path / "bad", environ=CONTACT)
    assert calls == []
    req = request(clock)
    with pytest.raises(sources.SecUnavailable, match="invalid_response"):
        sources.dispatch(
            req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW},
            append_event=calls.append,
            fetch=lambda *_: response(clock, req, status=302, final_url="https://example.test/x"),
            clock=clock, lock_path=tmp_path / "redirect", environ=CONTACT,
        )
    assert calls[-1]["event_kind"] == "failed"


def test_http_fetch_retains_only_bounded_prefix(monkeypatch):
    class Raw:
        status_code = 200
        headers = {"content-type": "text/plain"}
        url = sources.archive_url(320193, ACCESSION, "release.htm")

        @staticmethod
        def iter_content(_size):
            yield b"x" * sources.MAX_RESPONSE_BYTES
            yield b"overflow"

        def close(self):
            self.closed = True

    seen, raw = {}, Raw()

    def get(url, **kwargs):
        seen.update({"url": url, **kwargs})
        return raw

    monkeypatch.setattr(sources.requests, "get", get)
    result = sources._http_fetch(Raw.url, CONTACT["TRADING_ENGINE_SEC_USER_AGENT"])
    assert result.complete is False
    assert len(result.body) == sources.MAX_RESPONSE_BYTES
    assert result.observed_size_bytes > sources.MAX_RESPONSE_BYTES
    assert raw.closed is True
    assert seen["allow_redirects"] is False
    assert seen["timeout"] == (5, 20)
    req = request(FakeClock(), url=Raw.url)
    assert sources.bundle_size_status([result]) == "response_oversized"
    large = response(FakeClock(), req, body=b"x", observed=4_000_001)
    assert sources.bundle_size_status([large, large]) == "bundle_oversized"


def test_dispatch_never_returns_an_oversized_receipt_candidate(tmp_path):
    clock, events = FakeClock(), []
    req = request(clock)
    oversized = response(
        clock, req, body=b"x" * sources.MAX_RESPONSE_BYTES,
        observed=sources.MAX_RESPONSE_BYTES + 1, complete=False,
    )
    with pytest.raises(sources.SecUnavailable, match="response_oversized"):
        sources.dispatch(
            req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW},
            append_event=events.append, fetch=lambda *_: oversized, clock=clock,
            lock_path=tmp_path / "oversized", environ=CONTACT,
        )
    assert events[-1]["complete"] is False


def test_archive_url_uses_bounded_index_name_and_rejects_traversal():
    assert sources.archive_url(320193, ACCESSION).endswith(f"/{ACCESSION}-index.htm")
    with pytest.raises(ValueError, match="unsafe"):
        sources.archive_url(320193, ACCESSION, "../release.htm")


def test_ticker_map_inverts_classes_and_expires_after_seven_days():
    body = json.dumps({
        "0": {"cik_str": 320193, "ticker": "AAPL"},
        "1": {"cik_str": 1652044, "ticker": "GOOG"},
        "2": {"cik_str": 1652044, "ticker": "GOOGL"},
    }).encode()
    clock, req = FakeClock(), request(FakeClock(), url=sources.TICKER_MAP_URL)
    snapshot = sources.parse_ticker_map(response(clock, req, body=body))
    assert snapshot["cik_tickers"]["0001652044"] == ["GOOG", "GOOGL"]
    assert sources.ticker_map_status(snapshot, at=NOW + timedelta(days=7)) == "ready"
    assert sources.ticker_map_status(snapshot, at=NOW + timedelta(days=7, seconds=1)) == "map_stale"
    with pytest.raises(ValueError, match="untrusted"):
        sources.parse_ticker_map(response(clock, req, status=500, body=body))


def test_json_parsers_require_complete_success_or_verified_304():
    clock, req = FakeClock(), request(FakeClock())
    body = json.dumps({"cik": 320193, "filings": {"recent": {
        key: [] for key in ("accessionNumber", "acceptanceDateTime", "filingDate", "form",
                            "items", "primaryDocument", "reportDate")
    }}}).encode()
    with pytest.raises(ValueError, match="untrusted"):
        sources.parse_submissions(response(clock, req, status=500, body=body), cik=320193)
    with pytest.raises(ValueError, match="untrusted"):
        sources.parse_submissions(response(clock, req, status=304, body=b""), cik=320193)
    prior = sources.Verified304(body, hashlib.sha256(body).hexdigest())
    reused = sources.parse_submissions(response(clock, req, status=304, body=b""),
                                       cik=320193, verified_304=prior)
    assert reused["source_status"] == "verified_304"


def test_dispatch_304_reuses_only_the_verified_prior_body(tmp_path):
    clock, events = FakeClock(), []
    req = request(clock)
    body = json.dumps({"cik": 320193, "filings": {"recent": {
        key: [] for key in ("accessionNumber", "acceptanceDateTime", "filingDate", "form",
                            "items", "primaryDocument", "reportDate")
    }}}).encode()
    not_modified = response(clock, req, status=304, body=b"")
    dispatched = sources.dispatch(
        req, load_state=lambda: {"scan_id": "scan-a", "scan_started_at": NOW},
        append_event=events.append, fetch=lambda *_: not_modified, clock=clock,
        lock_path=tmp_path / "304", environ=CONTACT,
    )
    parsed = sources.parse_submissions(
        dispatched, cik=320193,
        verified_304=sources.Verified304(body, hashlib.sha256(body).hexdigest()),
    )
    assert parsed["source_status"] == "verified_304"
    assert parsed["response_accessions"] == []


def test_submissions_classification_preserves_prior_snapshot_and_strict_threshold():
    payload = {"cik": 320193, "filings": {"recent": {
        "accessionNumber": [ACCESSION], "acceptanceDateTime": ["untrusted"],
        "filingDate": ["2026-09-27"], "form": ["8-K"], "items": ["2.02,7.01"],
        "primaryDocument": ["primary.htm"], "reportDate": ["2026-06-30"],
    }}}
    clock, req = FakeClock(), request(FakeClock())
    parsed = sources.parse_submissions(
        response(clock, req, body=json.dumps(payload).encode()), cik="0000320193",
    )
    rows = sources.classify_discoveries(
        parsed, activation_at=NOW, cik_entered_at=NOW + timedelta(minutes=1),
        response_id="response-a", previous_response_id="response-prior",
    )
    assert rows[0]["status"] == "acceptance_pending_crosscheck"
    assert rows[0]["matched_items"] == ["2.02", "7.01"]
    assert rows[0]["response_id"] == "response-a"
    assert rows[0]["previous_response_id"] == "response-prior"
    assert len(rows[0]["previous_accessions_sha256"]) == 64
    assert sources.resolve_pending(rows[0])["status"] == "acceptance_pending_crosscheck"
    before = sources.resolve_pending(
        rows[0], index_value="2026-09-27 08:01:00",
        reference_received_at=NOW + timedelta(minutes=2),
    )
    assert before["status"] == "bundle_pending"
    eligible = sources.resolve_pending(
        rows[0], json_value="2026-09-27T08:02:00Z", sgml_value="20260927080200",
        reference_received_at=NOW + timedelta(minutes=3),
        normalized_sha256="a" * 64, available_at=NOW + timedelta(minutes=3),
    )
    assert eligible["status"] == "eligible"
    assert eligible["reference"] == "sgml"
    assert eligible["json_crosscheck"] == "eastern_clock_matches"
    duplicate = sources.resolve_pending(
        rows[0], sgml_value="20260927080200", reference_received_at=NOW + timedelta(minutes=3),
        normalized_sha256="a" * 64, available_at=NOW + timedelta(minutes=3),
        prior_facts=[{key: eligible[key] for key in
                     ("entity_id", "fact_type", "event_at", "normalized_sha256")}],
    )
    assert duplicate["status"] == "duplicate"
    assert sources.classify_discoveries(
        parsed, known_accessions={ACCESSION}, previous_accessions={ACCESSION},
        activation_at=NOW, cik_entered_at=NOW, response_id="response-b",
    )[0]["status"] == "already_queued_or_consumed"
    parsed["filings"][0]["metadata_items"] = ()
    assert sources.classify_discoveries(
        parsed, known_accessions={ACCESSION}, activation_at=NOW, cik_entered_at=NOW,
        response_id="response-c",
    )[0]["status"] == "already_queued_or_consumed"


def test_scheduler_services_one_document_then_two_ciks_and_lends_slots():
    assert list(sources.scheduled_work(["d1", "d2", "d3"], ["c1", "c2", "c3"])) == [
        "d1", "c1", "c2", "d2", "c3", "d3",
    ]
