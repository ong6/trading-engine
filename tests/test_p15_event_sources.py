"""P15 RSS source and deterministic text-trigger tests."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts, p15_event_sources
from engine.lib import db
from server import intraday_source
from tests.conftest import SESSIONS, insert_bars


def _database(con):
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    con.executemany(
        "INSERT INTO universe VALUES (?, ?, ?, 'NYSE', FALSE, 'test', DATE '2026-01-01',"
        "TRUE,TRUE,TRUE)",
        [("AAA", "AAA", "Acme Corporation"), ("BBB", "BBB", "Beta Holdings")],
    )
    con.executemany(
        "INSERT INTO screen_results (run_date,ticker,close,rs_rank,template_score,"
        "passes_template,dist_50d,dist_200d,off_52w_low,off_52w_high,base_tight,"
        "vol_dryup,new_today) VALUES (DATE '2026-09-25',?,?,?,1,TRUE,0,0,1,0,FALSE,FALSE,FALSE)",
        [("AAA", 100, 99), ("BBB", 100, 98)],
    )


def _line(title, guid, published="Fri, 25 Sep 2026 21:00:00 +0000"):
    return json.dumps({"title": title, "link": f"https://example.test/{guid}",
                       "guid": guid, "pubDate": published, "source": "test",
                       "scraped_at": "2026-09-25T21:05:00Z"}) + "\n"


def _receipt(con, observed):
    return bitemporal_facts.record_receipt(
        con, source="test", dataset="events", endpoint="https://example.test/events",
        request={}, requested_at=observed, received_at=observed, http_status=200,
        content_type="application/json", body=b"{}", license_class="public",
    )["receipt_sha256"]


def _fact(con, receipt, *, entity, fact_type, available, payload, source):
    return bitemporal_facts.record_fact(
        con, entity_id=entity, security_id="AAA", fact_type=fact_type,
        event_at=available - timedelta(seconds=1), published_at=None,
        available_at=available, ingested_at=available, payload=payload,
        source=source, source_version="test", receipt_sha256=receipt,
    )


def test_rss_ingest_maps_only_cashtag_or_exact_company_and_is_resumable(con, tmp_path):
    _database(con)
    path = tmp_path / "news.jsonl"
    path.write_text(
        _line("$AAA raises guidance", "one")
        + _line("Beta Holdings files an update", "two")
        + _line("Unrelated market story", "three")
    )
    now = datetime(2026, 9, 25, 21, 10, tzinfo=timezone.utc)

    result = p15_event_sources.ingest_rss(con, path, now=now)
    replay = p15_event_sources.ingest_rss(con, path, now=now)

    assert result["lines"] == 3 and result["facts"] == 3 and result["unmapped"] == 1
    assert replay == {"status": "current", "lines": 0, "facts": 0, "unmapped": 0}
    rows = con.execute(
        "SELECT security_id,normalized_payload,available_at FROM bitemporal_facts "
        "WHERE fact_type='news.headline' ORDER BY entity_id"
    ).fetchall()
    assert {row[0] for row in rows} == {"AAA", "BBB", None}
    assert all(set(json.loads(row[1])) == {"title"} and row[2] == now.replace(tzinfo=None)
               for row in rows)
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)


def test_forward_checkpoint_skips_history_and_rejects_rotation(con, tmp_path):
    _database(con)
    path = tmp_path / "news.jsonl"
    path.write_text(_line("$AAA old", "old"))
    now = datetime(2026, 9, 25, 21, 10, tzinfo=timezone.utc)
    first = p15_event_sources.initialize_rss_checkpoint(con, path, now=now)
    replay = p15_event_sources.initialize_rss_checkpoint(con, path, now=now)
    assert first["replayed"] is False and replay["replayed"] is True
    assert p15_event_sources.ingest_rss(con, path, now=now)["lines"] == 0
    path.write_text("")
    with pytest.raises(p15_event_sources.EventSourceError, match="rotated or truncated"):
        p15_event_sources.ingest_rss(con, path, now=now)


def test_rss_read_defers_bytes_appended_after_open(con, tmp_path, monkeypatch):
    _database(con)
    path = tmp_path / "news.jsonl"
    first_line = _line("$AAA first", "one")
    second_line = _line("$BBB second", "two")
    path.write_text(first_line)
    real_read = p15_event_sources.os.read
    appended = False

    def append_then_read(descriptor, count):
        nonlocal appended
        if not appended:
            with path.open("a") as handle:
                handle.write(second_line)
            appended = True
        return real_read(descriptor, count)

    monkeypatch.setattr(p15_event_sources.os, "read", append_then_read)
    first = p15_event_sources.ingest_rss(
        con, path, now=datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)
    )
    second = p15_event_sources.ingest_rss(
        con, path, now=datetime(2026, 9, 28, 13, 35, tzinfo=timezone.utc)
    )

    assert first["lines"] == first["facts"] == 1
    assert first["byte_offset"] == len(first_line.encode())
    assert second["lines"] == second["facts"] == 1
    assert con.execute(
        "SELECT available_at FROM bitemporal_facts ORDER BY available_at"
    ).fetchall() == [
        (datetime(2026, 9, 28, 13, 30),),
        (datetime(2026, 9, 28, 13, 35),),
    ]


def test_malformed_rss_line_is_retained_and_does_not_block_later_headline(con, tmp_path):
    _database(con)
    path = tmp_path / "news.jsonl"
    invalid = "{not-json}\n"
    path.write_text(invalid + _line("$AAA valid", "valid"))
    now = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)

    result = p15_event_sources.ingest_rss(con, path, now=now)

    assert result["status"] == "partial_invalid" and result["lines"] == 1
    assert result["byte_offset"] == path.stat().st_size
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (1,)
    failure = con.execute(
        "SELECT byte_offset,byte_count,invalid_lines,failure_payload FROM p15_rss_failures"
    ).fetchone()
    assert failure[:3] == (0, path.stat().st_size, 1)
    assert json.loads(failure[3]) == [{
        "line_number": 1,
        "line_sha256": __import__("hashlib").sha256(invalid.strip().encode()).hexdigest(),
        "reason": "invalid_json_or_timestamp",
    }]
    assert con.execute(
        "SELECT security_id FROM bitemporal_facts WHERE fact_type='news.headline'"
    ).fetchone() == ("AAA",)
    assert p15_event_sources.ingest_rss(con, path, now=now)["status"] == "current"


def test_text_triggers_deduplicate_rss_and_only_admit_8k(con, tmp_path):
    _database(con)
    path = tmp_path / "news.jsonl"
    path.write_text(_line("$AAA first", "one") + _line("$AAA second", "two"))
    now = datetime(2026, 9, 28, 13, 35, tzinfo=timezone.utc)
    p15_event_sources.ingest_rss(con, path, now=now - timedelta(minutes=2))
    receipt = bitemporal_facts.record_receipt(
        con, source="sec_edgar", dataset="submissions", endpoint="https://example.test/sec",
        request={}, requested_at=now - timedelta(minutes=1),
        received_at=now - timedelta(minutes=1), http_status=200,
        content_type="application/json", body=b"{}", license_class="public",
    )
    for form in ("8-K", "10-Q"):
        bitemporal_facts.record_fact(
            con, entity_id=f"sec:{form}", security_id="AAA",
            fact_type=f"sec.filing:{form}", event_at=now - timedelta(minutes=2),
            published_at=now - timedelta(minutes=2), available_at=now - timedelta(minutes=1),
            ingested_at=now - timedelta(minutes=1), payload={"form": form},
            source="sec_edgar", source_version="test",
            receipt_sha256=receipt["receipt_sha256"],
        )

    first = p15_event_sources.create_text_triggers(
        con, date(2026, 9, 28), triggered_at=now
    )
    second = p15_event_sources.create_text_triggers(
        con, date(2026, 9, 28), triggered_at=now + timedelta(minutes=15)
    )

    assert first == {"created": 2, "examined": 3}
    assert second == {"created": 0, "examined": 0}
    assert con.execute(
        "SELECT source,event_type FROM p15_event_triggers ORDER BY source"
    ).fetchall() == [("rss", "news.headline"), ("sec_8k", "sec.filing:8-K")]


def test_intraday_mover_scan_is_bounded_retained_and_never_mutates_prices(con):
    _database(con)
    for ticker in ("SPY", "AAA", "BBB"):
        insert_bars(con, ticker, SESSIONS[:30], open_=100, close=100, high=101, low=99)
    observed = datetime(2024, 7, 17, 14, 5, tzinfo=timezone.utc)
    con.execute("UPDATE screen_results SET run_date=?", [SESSIONS[29]])
    con.execute("UPDATE prices SET fetched_at=?", [
        (observed - timedelta(days=1)).replace(tzinfo=None)
    ])
    before = con.execute("SELECT * FROM prices ORDER BY ticker,date").fetchall()

    def capture(ticker, provider, now):
        price = 105.0 if ticker == "AAA" else 102.0
        quotes = [
            {"ticker": ticker, "event_at": now - timedelta(minutes=5),
             "open": 100.0, "high": price, "low": 99.0,
             "close": price, "volume": 100_000},
            {"ticker": ticker, "event_at": now - timedelta(minutes=10),
             "open": 100.0, "high": price, "low": 99.0,
             "close": price - 0.5, "volume": 100_000},
        ]
        response = intraday_source.Response(
            body=json.dumps({"ticker": ticker}).encode(), content_type="application/json",
            status_code=200, requested_at=now - timedelta(seconds=2),
            received_at=now - timedelta(seconds=1),
        )
        return {"endpoint": f"https://example.test/{provider}",
                "request": intraday_source.request_identity(provider),
                "response": response, "quotes": quotes}

    first = p15_event_sources.scan_intraday(con, observed_at=observed, capture=capture)
    second = p15_event_sources.scan_intraday(con, observed_at=observed, capture=capture)

    assert first == {"status": "complete", "universe": 3, "captured": 3,
                     "facts": 6, "triggers": 1, "failures": []}
    assert second["triggers"] == 0
    assert con.execute(
        "SELECT ticker,source,event_type FROM p15_event_triggers"
    ).fetchall() == [("AAA", "intraday_mover", "intraday_mover")]
    assert con.execute(
        "SELECT COUNT(*) FROM bitemporal_facts WHERE fact_type='intraday.ohlcv.5m'"
    ).fetchone() == (6,)
    mover_payload = json.loads(con.execute(
        "SELECT f.normalized_payload FROM p15_event_triggers t "
        "JOIN bitemporal_facts f ON f.fact_sha256=t.fact_sha256"
    ).fetchone()[0])
    source_time = con.execute(
        "SELECT event_at FROM bitemporal_facts WHERE fact_sha256=?",
        [mover_payload["source_fact_sha256"]],
    ).fetchone()[0]
    assert source_time == (observed - timedelta(minutes=5)).replace(tzinfo=None)
    assert con.execute("SELECT * FROM prices ORDER BY ticker,date").fetchall() == before


def test_rss_segment_rolls_back_before_checkpoint_on_fact_failure(con, tmp_path, monkeypatch):
    _database(con)
    path = tmp_path / "news.jsonl"
    path.write_text(_line("$AAA first", "one") + _line("$BBB second", "two"))
    now = datetime(2026, 9, 25, 21, 10, tzinfo=timezone.utc)
    real = bitemporal_facts.record_fact
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted")
        return real(*args, **kwargs)

    monkeypatch.setattr(bitemporal_facts, "record_fact", fail_second)
    with pytest.raises(RuntimeError, match="interrupted"):
        p15_event_sources.ingest_rss(con, path, now=now)
    assert con.execute("SELECT COUNT(*) FROM source_response_receipts").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM bitemporal_facts").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM p15_rss_checkpoints").fetchone() == (0,)


def test_ambiguous_company_name_remains_unmapped(con, tmp_path):
    _database(con)
    con.execute("UPDATE universe SET name='Shared Company'")
    path = tmp_path / "news.jsonl"
    path.write_text(_line("Shared Company announces results", "shared"))

    p15_event_sources.ingest_rss(
        con, path, now=datetime(2026, 9, 25, 21, 10, tzinfo=timezone.utc)
    )

    assert con.execute(
        "SELECT security_id FROM bitemporal_facts WHERE fact_type='news.headline'"
    ).fetchone() == (None,)


def test_trigger_recovery_uses_immutable_start_not_mutable_rss_checkpoint(con):
    _database(con)
    start = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)
    p15_event_sources.initialize_event_evidence(con, now=start)
    receipt = _receipt(con, start + timedelta(minutes=1))
    _fact(con, receipt, entity="sec:AAA:8k", fact_type="sec.filing:8-K",
          available=start + timedelta(minutes=1), payload={"form": "8-K"},
          source="sec_edgar")
    con.execute(
        "INSERT INTO p15_rss_checkpoints VALUES (?,?,?,?,?)",
        [p15_event_sources.RSS_SOURCE, 1, 1, "test", start + timedelta(minutes=4)],
    )

    result = p15_event_sources.create_text_triggers(
        con, start.date(), triggered_at=start + timedelta(minutes=5)
    )

    assert result == {"created": 1, "examined": 1}
    assert con.execute("SELECT source FROM p15_event_triggers").fetchone() == ("sec_8k",)


def test_trigger_recovery_does_not_require_rss_and_keeps_source_sessions_distinct(con):
    _database(con)
    con.execute("UPDATE screen_results SET run_date=DATE '2026-09-24'")
    start = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)
    p15_event_sources.initialize_event_evidence(con, now=start)
    receipt = _receipt(con, start)
    _fact(con, receipt, entity="rss:friday:AAA", fact_type="news.headline",
          available=start + timedelta(minutes=1), payload={"title": "$AAA Friday"},
          source="local_rss")
    monday = datetime(2026, 9, 28, 13, 35, tzinfo=timezone.utc)
    _fact(con, receipt, entity="rss:monday:AAA", fact_type="news.headline",
          available=monday - timedelta(minutes=1), payload={"title": "$AAA Monday"},
          source="local_rss")
    _fact(con, receipt, entity="mover:monday:AAA", fact_type="p15.event.intraday_mover",
          available=monday - timedelta(minutes=2), payload={"event_type": "intraday_mover"},
          source="yfinance")

    result = p15_event_sources.create_text_triggers(
        con, monday.date(), triggered_at=monday
    )

    assert result == {"created": 3, "examined": 3}
    assert con.execute(
        "SELECT session_date,source FROM p15_event_triggers ORDER BY session_date,source"
    ).fetchall() == [
        (date(2026, 9, 25), "rss"),
        (date(2026, 9, 28), "intraday_mover"),
        (date(2026, 9, 28), "rss"),
    ]
    assert con.execute("SELECT COUNT(*) FROM p15_rss_checkpoints").fetchone() == (0,)


def test_ineligible_sec_facts_cannot_crowd_out_later_valid_trigger(con):
    _database(con)
    start = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)
    p15_event_sources.initialize_event_evidence(con, now=start)
    receipt = _receipt(con, start)
    for index in range(1_001):
        available = start + timedelta(microseconds=index)
        _fact(con, receipt, entity=f"sec:10q:{index}", fact_type="sec.filing:10-Q",
              available=available, payload={"form": "10-Q"}, source="sec_edgar")
    _fact(con, receipt, entity="sec:8k:valid", fact_type="sec.filing:8-K",
          available=start + timedelta(minutes=1), payload={"form": "8-K"},
          source="sec_edgar")
    _fact(con, receipt, entity="foreign:headline", fact_type="news.headline",
          available=start + timedelta(minutes=2), payload={"title": "$AAA foreign"},
          source="unregistered")

    result = p15_event_sources.create_text_triggers(
        con, start.date(), triggered_at=start + timedelta(minutes=5)
    )

    assert result == {"created": 1, "examined": 1}
    assert con.execute("SELECT event_type FROM p15_event_triggers").fetchone() == (
        "sec.filing:8-K",
    )


def test_after_close_fact_is_immediately_assigned_to_next_session(con):
    _database(con)
    start = datetime(2026, 11, 27, 17, 40, tzinfo=timezone.utc)
    p15_event_sources.initialize_event_evidence(con, now=start)
    receipt = _receipt(con, start)
    available = datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)
    _fact(con, receipt, entity="rss:after-close", fact_type="news.headline",
          available=available, payload={"title": "$AAA after close"}, source="local_rss")

    result = p15_event_sources.create_text_triggers(
        con, date(2026, 11, 27), triggered_at=available + timedelta(minutes=1)
    )

    assert result == {"created": 1, "examined": 1}
    assert con.execute(
        "SELECT session_date,triggered_at FROM p15_event_triggers"
    ).fetchone() == (date(2026, 11, 30), datetime(2026, 11, 27, 18, 2))
    assert con.execute(
        "SELECT scanned_through_at FROM p15_event_source_state"
    ).fetchone() == (datetime(2026, 11, 27, 18, 2),)
