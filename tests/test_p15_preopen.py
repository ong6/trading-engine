"""P15 pre-open cancel-only policy and evidence tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import bitemporal_facts
from server import agent_model_client, daily_opportunity_news, p15_preopen
from sim import p15_books
from tests.conftest import SESSIONS, insert_bars
from tests.test_p15_books import _activate, _decision, _seed_decisions


def _result(output):
    return agent_model_client.ConnectorResult(
        output=output, response_id="preopen-response", model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION, proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="preopen-upstream",
        model_catalog_entry_sha256=agent_model_client.MODEL_CATALOG_ENTRY_SHA256,
        request_sha256="b" * 64,
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def _setup(con):
    signal_date, session_date = SESSIONS[29:31]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[:31], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, signal_date, created_at=datetime(2024, 7, 16, 20, tzinfo=timezone.utc)
    )
    return signal_date, session_date


def _news(ticker, now):
    body = json.dumps({"news": [{
        "title": f"{ticker} changes outlook", "publisher": "Example Wire",
        "link": "https://example.test/update",
        "providerPublishTime": int((now - timedelta(minutes=5)).timestamp()),
    }]}).encode()
    return daily_opportunity_news.Response(body, "application/json", 200, now, now)


def test_preopen_can_only_cancel_ai_and_records_rule_noop(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    observed = []
    bitemporal_facts.init_schema(con)
    receipt = bitemporal_facts.record_receipt(
        con, source="sec", dataset="filing", endpoint="https://example.test/sec",
        request={"ticker": "AAA"}, requested_at=now - timedelta(hours=1),
        received_at=now - timedelta(hours=1), http_status=200,
        content_type="application/json", body=b"{}", license_class="public",
    )
    for source, fact_type, available in (
        ("sec", "sec.filing:8-K", now - timedelta(minutes=30)),
        ("tradingview_unofficial", "intraday.ohlcv.5m", now - timedelta(minutes=20)),
        ("sec", "sec.filing:8-K", now + timedelta(minutes=20)),
    ):
        bitemporal_facts.record_fact(
            con, entity_id=f"AAA:{available.isoformat()}", security_id="AAA",
            fact_type=fact_type, event_at=available - timedelta(minutes=1),
            published_at=available - timedelta(minutes=1), available_at=available,
            ingested_at=available, payload={"headline": "new fact"}, source=source,
            source_version="test", receipt_sha256=receipt["receipt_sha256"],
        )

    def generate(payload):
        observed.append(payload)
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"],
             "decision": "cancel" if item["portfolio_id"] == "p15_ai_ranked" else "keep",
             "reason": "New evidence changed the thesis.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]})

    result = p15_preopen.run(
        con, session_date=session_date, now=now, generate=generate,
        fetch_news=_news, clock=lambda: now,
    )

    assert result["status"] == "completed" and result["cancelled"] == 1
    assert len(observed) == 1 and len(observed[0]["intents"]) == 2
    assert "tradingview_quotes" not in json.dumps(observed[0])
    assert all(len(item["new_event_facts"]) == 1 for item in observed[0]["intents"])
    assert all(item["new_event_facts"][0]["source"] == "sec"
               for item in observed[0]["intents"])
    states = con.execute(
        "SELECT portfolio_id,status FROM p15_order_intents WHERE ticker='AAA' "
        "ORDER BY portfolio_id"
    ).fetchall()
    assert states == [("p15_ai_ranked", "cancelled"),
                      ("p15_hybrid_veto", "pending"),
                      ("p15_rule_control", "pending")]
    decisions = con.execute(
        "SELECT portfolio_id,decision,reason FROM p15_preopen_decisions "
        "ORDER BY portfolio_id"
    ).fetchall()
    assert decisions == [("p15_ai_ranked", "cancel", "New evidence changed the thesis."),
                         ("p15_hybrid_veto", "keep", "New evidence changed the thesis."),
                         ("p15_rule_control", "keep", "rule_control_noop")]
    assert con.execute("SELECT COUNT(*) FROM p15_preopen_news_responses").fetchone() == (1,)
    assert p15_books.process_pending(con, session_date) == {
        "filled": 5, "rejected": 0, "pending": 0,
    }
    post = p15_preopen.capture_after_open(con, session_date, captured_at=now)
    assert post == {"cancelled_attempts": 1, "counterfactual_labels": 0,
                    "execution_quality": 5}
    assert con.execute(
        "SELECT outcome FROM p15_limit_attempts a JOIN p15_order_intents i "
        "ON i.id=a.intent_id WHERE i.portfolio_id='p15_ai_ranked' AND i.ticker='AAA'"
    ).fetchone() == ("cancelled_would_fill",)
    assert con.execute("SELECT COUNT(*) FROM p15_execution_quality").fetchone() == (5,)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id='p15_ai_ranked' "
        "AND ticker='AAA'"
    ).fetchone() == (0,)
    replay = p15_preopen.run(
        con, session_date=session_date, now=now,
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("replayed")),
        fetch_news=lambda *_args: (_ for _ in ()).throw(AssertionError("replayed")),
        clock=lambda: now,
    )
    assert replay["replayed"] is True and replay["cancelled"] == 1
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[31:35], open_=100, close=105, high=106, low=99)
    later = datetime(2024, 7, 24, 20, tzinfo=timezone.utc)
    con.execute("UPDATE prices SET fetched_at=?", [later.replace(tzinfo=None)])
    labeled = p15_preopen.capture_after_open(con, SESSIONS[34], captured_at=later)
    assert labeled["counterfactual_labels"] == 1
    assert con.execute(
        "SELECT attempt_date,exit_date FROM p15_limit_labels"
    ).fetchone() == (session_date, SESSIONS[34])


def test_late_or_invalid_preopen_keeps_every_intent(con):
    _signal_date, session_date = _setup(con)
    late = datetime(2024, 7, 17, 13, 25, tzinfo=timezone.utc)
    result = p15_preopen.run(
        con, session_date=session_date, now=late,
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("late call")),
        fetch_news=lambda *_args: (_ for _ in ()).throw(AssertionError("late fetch")),
        clock=lambda: late,
    )
    assert result["status"] == "late" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE status='cancelled'"
    ).fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM p15_preopen_decisions WHERE decision='keep'"
    ).fetchone() == (3,)


def test_preopen_output_cannot_add_resize_or_cite_foreign_evidence(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)

    def invalid(payload):
        intent = payload["intents"][0]
        return _result({"schema_version": 1, "decisions": [{
            "intent_id": intent["intent_id"], "decision": "cancel",
            "reason": "Unsupported", "evidence_ids": ["f" * 64],
            "quantity": 1_000_000,
        }]})

    result = p15_preopen.run(
        con, session_date=session_date, now=now, generate=invalid,
        fetch_news=_news, clock=lambda: now,
    )
    assert result["status"] == "unavailable" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE status='cancelled'"
    ).fetchone() == (0,)


def test_response_after_deadline_is_retained_but_cannot_cancel(con):
    _signal_date, session_date = _setup(con)
    started = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    finished = datetime(2024, 7, 17, 13, 25, tzinfo=timezone.utc)

    def cancel_all(payload):
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"], "decision": "cancel",
             "reason": "Adverse update.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]})

    result = p15_preopen.run(
        con, session_date=session_date, now=started, generate=cancel_all,
        fetch_news=_news, clock=lambda: finished,
    )

    assert result["status"] == "late" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_preopen_decisions WHERE decision='keep'"
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT response_payload IS NOT NULL FROM p15_preopen_runs"
    ).fetchone() == (True,)


def test_preopen_rejects_early_invocation_without_writes(con):
    _signal_date, session_date = _setup(con)
    early = datetime(2024, 7, 17, 13, 4, tzinfo=timezone.utc)
    with pytest.raises(p15_preopen.PreopenError, match="outside"):
        p15_preopen.run(con, session_date=session_date, now=early)
    assert not p15_books.table_exists(con, "p15_preopen_runs")
