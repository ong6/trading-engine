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
        con, date(2026, 9, 28), triggered_at=now
    )

    assert first == {"created": 2, "examined": 4}
    assert second == {"created": 0, "examined": 4}
    assert con.execute(
        "SELECT source,event_type FROM p15_event_triggers ORDER BY source"
    ).fetchall() == [("rss", "news.headline"), ("sec_8k", "sec.filing:8-K")]


def test_intraday_mover_scan_is_bounded_retained_and_never_mutates_prices(con):
    _database(con)
    for ticker in ("SPY", "AAA", "BBB"):
        insert_bars(con, ticker, SESSIONS[:30], open_=100, close=100, high=101, low=99)
    observed = datetime(2024, 7, 17, 14, 5, tzinfo=timezone.utc)
    before = con.execute("SELECT * FROM prices ORDER BY ticker,date").fetchall()

    def capture(ticker, provider, now):
        price = 105.0 if ticker == "AAA" else 102.0
        quote = {"ticker": ticker, "event_at": now - timedelta(minutes=5),
                 "open": 100.0, "high": price, "low": 99.0,
                 "close": price, "volume": 200_000}
        response = intraday_source.Response(
            body=json.dumps({"ticker": ticker}).encode(), content_type="application/json",
            status_code=200, requested_at=now - timedelta(seconds=2),
            received_at=now - timedelta(seconds=1),
        )
        return {"endpoint": f"https://example.test/{provider}",
                "request": intraday_source.request_identity(provider),
                "response": response, "quotes": [quote]}

    first = p15_event_sources.scan_intraday(con, observed_at=observed, capture=capture)
    second = p15_event_sources.scan_intraday(con, observed_at=observed, capture=capture)

    assert first == {"status": "complete", "universe": 3, "captured": 3,
                     "facts": 3, "triggers": 1, "failures": []}
    assert second["triggers"] == 0
    assert con.execute(
        "SELECT ticker,source,event_type FROM p15_event_triggers"
    ).fetchall() == [("AAA", "intraday_mover", "intraday_mover")]
    assert con.execute(
        "SELECT COUNT(*) FROM bitemporal_facts WHERE fact_type='intraday.ohlcv.5m'"
    ).fetchone() == (3,)
    assert con.execute("SELECT * FROM prices ORDER BY ticker,date").fetchall() == before
