"""P15 pre-open cancel-only policy and evidence tests."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone

import duckdb
import pytest

from engine import bitemporal_facts
from engine.lib import settings
from engine.lib.provenance import canonical_sha256
from server import agent_model_client, daily_opportunity_news, p15_preopen
from sim import p15_books
from tests.conftest import SESSIONS, insert_bars
from tests.test_market_data_sources import held_store_reader
from tests.test_p15_books import _activate, _decision, _seed_decisions


def _result(output, payload):
    return agent_model_client.ConnectorResult(
        output=output, response_id="preopen-response", model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION, proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="preopen-upstream",
        model_catalog_entry_sha256=agent_model_client.MODEL_CATALOG_ENTRY_SHA256,
        request_sha256=canonical_sha256(
            agent_model_client.p15_preopen_request_payload(payload)
        ),
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
    return daily_opportunity_news.Response(
        body, "application/json", 200, now, now + timedelta(seconds=1)
    )


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
        ("alpaca", "market.quote.realtime", now - timedelta(minutes=10)),
        ("alpaca", "intraday.trade", now - timedelta(minutes=5)),
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
        assert con.execute("SELECT status FROM p15_preopen_runs").fetchone() == ("running",)
        assert con.execute("SELECT COUNT(*) FROM p15_preopen_news_responses").fetchone() == (1,)
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"],
             "decision": "cancel" if item["portfolio_id"] == "p15_ai_ranked" else "keep",
             "reason": "New evidence changed the thesis.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]}, payload)

    result = p15_preopen.run(
        con, session_date=session_date, now=now, generate=generate,
        fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
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
                    "execution_quality": 6}
    assert con.execute(
        "SELECT outcome FROM p15_limit_attempts a JOIN p15_order_intents i "
        "ON i.id=a.intent_id WHERE i.portfolio_id='p15_ai_ranked' AND i.ticker='AAA'"
    ).fetchone() == ("cancelled_would_fill",)
    assert con.execute("SELECT COUNT(*) FROM p15_execution_quality").fetchone() == (6,)
    stock_quality = con.execute(
        "SELECT decision_to_order_ms,order_to_attempt_sessions,gap_shortfall_bps,"
        "total_shortfall_bps,cost_bps,status FROM p15_execution_quality "
        "WHERE ticker='AAA' AND status='filled' ORDER BY portfolio_id"
    ).fetchall()
    assert all(row[:5] == pytest.approx((72_000_000, 1, 0, 10, 10))
               and row[5] == "filled" for row in stock_quality)
    assert con.execute(
        "SELECT DISTINCT decision_to_order_ms FROM p15_execution_quality WHERE ticker='SPY'"
    ).fetchall() == [(0.0,)]
    assert p15_preopen.capture_after_open(con, session_date, captured_at=now) == {
        "cancelled_attempts": 0, "counterfactual_labels": 0,
        "execution_quality": 0,
    }
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
    receipt_row = con.execute("SELECT * FROM p15_preopen_news_responses").fetchone()
    con.execute("DELETE FROM p15_preopen_news_responses")
    with pytest.raises(p15_preopen.PreopenError, match="receipt set is incomplete"):
        p15_preopen.run(con, session_date=session_date, now=now)
    con.execute(
        "INSERT INTO p15_preopen_news_responses VALUES (?,?,?,?,?,?,?,?,?,?)",
        list(receipt_row),
    )
    con.execute(
        "DELETE FROM p15_preopen_decisions WHERE id=(SELECT MIN(id) FROM p15_preopen_decisions)"
    )
    with pytest.raises(p15_preopen.PreopenError, match="decision set is incomplete"):
        p15_preopen.run(con, session_date=session_date, now=now)
    con.execute(
        "UPDATE p15_execution_quality SET gap_shortfall_bps=999 "
        "WHERE intent_id=(SELECT MIN(intent_id) FROM p15_execution_quality)"
    )
    with pytest.raises(p15_preopen.PreopenError, match="quality replay differs"):
        p15_preopen.capture_after_open(con, SESSIONS[34], captured_at=later)


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
    assert con.execute(
        "SELECT reason FROM p15_preopen_decisions "
        "WHERE portfolio_id='p15_rule_control'"
    ).fetchone() == ("rule_control_noop",)


def test_preopen_output_cannot_add_resize_or_cite_foreign_evidence(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)

    def invalid(payload):
        intent = payload["intents"][0]
        return _result({"schema_version": 1, "decisions": [{
            "intent_id": intent["intent_id"], "decision": "cancel",
            "reason": "Unsupported", "evidence_ids": ["f" * 64],
            "quantity": 1_000_000,
        }]}, payload)

    result = p15_preopen.run(
        con, session_date=session_date, now=now, generate=invalid,
        fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
    )
    assert result["status"] == "unavailable" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE status='cancelled'"
    ).fetchone() == (0,)


def test_response_after_deadline_is_retained_but_cannot_cancel(con):
    _signal_date, session_date = _setup(con)
    started = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    finished = datetime(2024, 7, 17, 13, 25, tzinfo=timezone.utc)
    times = iter((started + timedelta(seconds=2), finished, finished, finished))

    def cancel_all(payload):
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"], "decision": "cancel",
             "reason": "Adverse update.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]}, payload)

    result = p15_preopen.run(
        con, session_date=session_date, now=started, generate=cancel_all,
        fetch_news=_news, clock=lambda: next(times),
    )

    assert result["status"] == "late" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_preopen_decisions WHERE decision='keep'"
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT response_payload IS NOT NULL FROM p15_preopen_runs"
    ).fetchone() == (True,)
    assert con.execute(
        "SELECT reason FROM p15_preopen_decisions "
        "WHERE portfolio_id='p15_rule_control'"
    ).fetchone() == ("rule_control_noop",)


def test_deadline_crossing_inside_commit_rolls_back_cancellation(con):
    _signal_date, session_date = _setup(con)
    started = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    near = datetime(2024, 7, 17, 13, 24, 59, 900000, tzinfo=timezone.utc)
    late = datetime(2024, 7, 17, 13, 25, tzinfo=timezone.utc)
    times = iter((started + timedelta(seconds=2), near, near, late))

    def cancel_all(payload):
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"], "decision": "cancel",
             "reason": "Adverse update.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]}, payload)

    result = p15_preopen.run(
        con, session_date=session_date, now=started, generate=cancel_all,
        fetch_news=_news, clock=lambda: next(times),
    )

    assert result["status"] == "late" and result["cancelled"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM p15_order_intents WHERE status='cancelled'"
    ).fetchone() == (0,)
    assert con.execute(
        "SELECT reason FROM p15_preopen_decisions "
        "WHERE portfolio_id='p15_rule_control'"
    ).fetchone() == ("rule_control_noop",)


def test_cancelled_limit_miss_gets_attempt_date_counterfactual_label(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)

    def cancel_ai(payload):
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"],
             "decision": "cancel" if item["portfolio_id"] == "p15_ai_ranked" else "keep",
             "reason": "Adverse update.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]}, payload)

    p15_preopen.run(
        con, session_date=session_date, now=now, generate=cancel_ai,
        fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
    )
    con.execute(
        "UPDATE prices SET open=102,high=103,low=101,close=102 "
        "WHERE ticker='AAA' AND date=?", [session_date],
    )
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, SESSIONS[31:35], open_=102, close=105, high=106, low=101)
    labeled_at = datetime(2024, 7, 24, 20, tzinfo=timezone.utc)
    con.execute("UPDATE prices SET fetched_at=?", [labeled_at.replace(tzinfo=None)])

    result = p15_preopen.capture_after_open(con, session_date, captured_at=labeled_at)

    assert result["cancelled_attempts"] == result["counterfactual_labels"] == 1
    assert con.execute(
        "SELECT outcome FROM p15_limit_attempts"
    ).fetchone() == ("cancelled_limit_not_reached",)
    assert con.execute(
        "SELECT attempt_date,entry_px,exit_date FROM p15_limit_labels"
    ).fetchone()[::2] == (session_date, SESSIONS[34])


def test_preopen_rejects_early_invocation_without_writes(con):
    _signal_date, session_date = _setup(con)
    early = datetime(2024, 7, 17, 13, 4, tzinfo=timezone.utc)
    with pytest.raises(p15_preopen.PreopenError, match="outside"):
        p15_preopen.run(con, session_date=session_date, now=early)
    assert not p15_books.table_exists(con, "p15_preopen_runs")


def test_preopen_returns_not_session_on_market_holiday(con):
    signal_date = date(2024, 7, 3)
    holiday = date(2024, 7, 4)
    history = [item for item in SESSIONS if item <= signal_date]
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, history, open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, signal_date,
        created_at=datetime(2024, 7, 3, 20, tzinfo=timezone.utc),
    )

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("holiday pre-open called an external dependency")

    result = p15_preopen.run(
        con,
        session_date=holiday,
        now=datetime(2024, 7, 4, 13, 10, tzinfo=timezone.utc),
        generate=unexpected_call,
        fetch_news=unexpected_call,
    )

    assert result == {
        "status": "not_session",
        "decision_count": 0,
        "cancelled": 0,
    }
    assert con.execute(
        "SELECT DISTINCT status FROM p15_order_intents"
    ).fetchall() == [("pending",)]


@pytest.mark.parametrize("schema,intent_id", [(True, 1), (1, True), (1, 1.0)])
def test_preopen_validation_rejects_non_integer_identities(schema, intent_id):
    with pytest.raises(p15_preopen.PreopenError):
        p15_preopen._validate({"schema_version": schema, "decisions": [{
            "intent_id": intent_id, "decision": "keep", "reason": "test",
            "evidence_ids": ["a" * 64],
        }]}, {1: {"a" * 64}})


def test_no_pending_result_is_durable_and_replayed(con):
    signal_date, session_date = SESSIONS[29:31]
    _activate(con, signal_date)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)

    first = p15_preopen.run(con, session_date=session_date, now=now)
    replay = p15_preopen.run(con, session_date=session_date, now=now)

    assert first["status"] == "no_pending_orders" and first["replayed"] is False
    assert replay["status"] == "no_pending_orders" and replay["replayed"] is True
    assert con.execute("SELECT COUNT(*) FROM p15_preopen_runs").fetchone() == (1,)


def test_slow_failed_news_crossing_deadline_never_calls_model(con):
    _signal_date, session_date = _setup(con)
    started = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    late = datetime(2024, 7, 17, 13, 25, tzinfo=timezone.utc)

    result = p15_preopen.run(
        con, session_date=session_date, now=started,
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("late model call")),
        fetch_news=lambda *_args: (_ for _ in ()).throw(
            daily_opportunity_news.NewsError("slow failure")
        ),
        clock=lambda: late,
    )

    assert result["status"] == "late" and result["cancelled"] == 0
    assert con.execute(
        "SELECT reason FROM p15_preopen_decisions "
        "WHERE portfolio_id='p15_rule_control'"
    ).fetchone() == ("rule_control_noop",)


def test_interrupted_run_recovers_from_exact_retained_input(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    with pytest.raises(KeyboardInterrupt):
        p15_preopen.run(
            con, session_date=session_date, now=now,
            generate=lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
            fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
        )
    retained = json.loads(con.execute(
        "SELECT input_payload FROM p15_preopen_runs WHERE status='running'"
    ).fetchone()[0])
    expected = {item["intent_id"] for item in [
        *retained["intents"], *retained["control_noops"],
    ]}
    con.execute(
        "UPDATE p15_order_intents SET status='rejected' "
        "WHERE id=(SELECT MIN(id) FROM p15_order_intents)"
    )

    result = p15_preopen.run(
        con, session_date=session_date, now=now,
        generate=lambda _payload: (_ for _ in ()).throw(AssertionError("recalled model")),
        fetch_news=lambda *_args: (_ for _ in ()).throw(AssertionError("refetched news")),
        clock=lambda: now,
    )

    assert result["status"] == "unavailable" and result["decision_count"] == 3
    actual = {row[0] for row in con.execute(
        "SELECT intent_id FROM p15_preopen_decisions"
    ).fetchall()}
    assert actual == expected


def test_carried_intent_is_reassessed_and_cancel_capture_backfills_sessions(con):
    signal_date, first_session, second_session = SESSIONS[29:32]
    insert_bars(con, "SPY", SESSIONS[:32], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", SESSIONS[:30], open_=100, close=100, high=101, low=99)
    insert_bars(con, "AAA", [second_session], open_=100, close=100, high=101, low=99)
    _activate(con, signal_date)
    _seed_decisions(con, signal_date, [_decision("AAA", 1, 100)])
    p15_books.queue_orders(
        con, signal_date, created_at=datetime(2024, 7, 16, 20, tzinfo=timezone.utc)
    )

    def decide(payload, choice):
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"], "decision": choice,
             "reason": f"{choice} after review.",
             "evidence_ids": [item["allowed_evidence_ids"][0]]}
            for item in payload["intents"]
        ]}, payload)

    first_now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    assert p15_preopen.run(
        con, session_date=first_session, now=first_now,
        generate=lambda payload: decide(payload, "keep"), fetch_news=_news,
        clock=lambda: first_now + timedelta(seconds=2),
    )["cancelled"] == 0
    assert p15_books.process_pending(con, first_session)["pending"] == 3
    second_now = datetime(2024, 7, 18, 13, 10, tzinfo=timezone.utc)
    assert p15_preopen.run(
        con, session_date=second_session, now=second_now,
        generate=lambda payload: decide(payload, "cancel"), fetch_news=_news,
        clock=lambda: second_now + timedelta(seconds=2),
    )["cancelled"] == 2

    captured = p15_preopen.capture_after_open(
        con, second_session, captured_at=second_now
    )
    assert captured["cancelled_attempts"] == 2
    attempts = con.execute(
        "SELECT i.portfolio_id,a.attempt_date,a.outcome FROM p15_limit_attempts a "
        "JOIN p15_order_intents i ON i.id=a.intent_id WHERE i.status='cancelled' "
        "ORDER BY i.portfolio_id,a.attempt_date"
    ).fetchall()
    assert attempts == [
        ("p15_ai_ranked", first_session, "pending"),
        ("p15_ai_ranked", second_session, "cancelled_would_fill"),
        ("p15_hybrid_veto", first_session, "pending"),
        ("p15_hybrid_veto", second_session, "cancelled_would_fill"),
    ]
    assert con.execute("SELECT COUNT(*) FROM p15_preopen_runs").fetchone() == (2,)


def test_run_database_waits_out_a_concurrent_store_reader(tmp_path, monkeypatch):
    # The pre-open opened the store writer once (wait_s=0), so the API's read connection for
    # the digest's /meta probe failed it on 2026-10-13 and 10-14.
    store = tmp_path / "market.duckdb"
    duckdb.connect(str(store)).close()
    monkeypatch.setattr(p15_preopen, "LOCK_PATH", tmp_path / "preopen.lock")
    monkeypatch.setattr(p15_preopen, "NIGHTLY_LOCK", tmp_path / "nightly.lock")
    with held_store_reader(store, monkeypatch):
        result = p15_preopen.run_database(
            store, now=datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc),
        )
    assert result == {"status": "inactive", "decision_count": 0, "cancelled": 0}


def test_store_wait_leaves_the_preopen_inside_its_deadline_and_unit_timeout():
    # Worst case before the model answers: the store wait, which retries until the deadline
    # less its reserve, then two proxy status checks of two requests each and the generation
    # timeout. Slow news cannot cancel late: the run records "late" and keeps every intent.
    unit = settings.REPO_ROOT / "server" / "trading-engine-p15-preopen"
    timer = unit.with_suffix(".timer").read_text()
    assert f"OnCalendar=Mon..Fri *-*-* {p15_preopen.START:%H:%M:%S} America/New_York" in timer
    assert "AccuracySec" not in timer
    service = unit.with_suffix(".service").read_text()
    timeout_s = 60 * int(re.search(r"^TimeoutStartSec=(\d+)min$", service, re.M)[1])
    start = datetime.combine(date(2024, 7, 17), p15_preopen.START, p15_preopen.ET)
    model_s = 4 * agent_model_client.STATUS_TIMEOUT_SECONDS \
        + agent_model_client.GENERATION_TIMEOUT_SECONDS
    worst_s = p15_preopen.store_wait_s(start) + model_s
    window_s = (datetime.combine(date.min, p15_preopen.DEADLINE)
                - datetime.combine(date.min, p15_preopen.START)).total_seconds()
    assert model_s < p15_preopen.STORE_WAIT_RESERVE_S
    assert worst_s < window_s and worst_s < timeout_s
    late = datetime.combine(date(2024, 7, 17), time(9, 24), p15_preopen.ET)
    assert p15_preopen.store_wait_s(late) == 0.0


# Stored run 6 (session 2026-10-06): the model cancelled STX (intent 42) with allowlisted
# evidence and kept CYPH (intent 44) citing no new evidence. Requiring evidence on the keep
# voided the whole run, so the cancel was lost and intent 42 filled at 856.62.
RUN_6_ALLOWED = {
    41: {"c752f75184c5fa70e1e8869bb19323912b387241716aab149f732cdb8f45b4c0",
         "cec4bad5afa6c5050a8e8213aba0a7168404dca000c0cd9aeea267877b26e756"},
    42: {"f39719abb03dd8054e25ab9878e32359bb671b0da87056487f45e9cc2c601d37",
         "aa6786c75229c0ae98692fba9defd940173c8045a8da7c02e8eb8e2bcd1f4c82",
         "cec4bad5afa6c5050a8e8213aba0a7168404dca000c0cd9aeea267877b26e756"},
    44: {"b1f8205a923b572698739ce8aa5530d2660f8d72abd7b3b1f4a3e19f1dc98bf5",
         "cec4bad5afa6c5050a8e8213aba0a7168404dca000c0cd9aeea267877b26e756"},
}
RUN_6_OUTPUT = {"schema_version": 1, "decisions": [
    {"decision": "keep", "intent_id": 41,
     "evidence_ids": ["c752f75184c5fa70e1e8869bb19323912b387241716aab149f732cdb8f45b4c0"],
     "reason": "New coverage reiterates the known positive Phase III catalyst without "
               "disclosing an invalidating qualification."},
    {"decision": "cancel", "intent_id": 42,
     "evidence_ids": ["f39719abb03dd8054e25ab9878e32359bb671b0da87056487f45e9cc2c601d37",
                      "aa6786c75229c0ae98692fba9defd940173c8045a8da7c02e8eb8e2bcd1f4c82"],
     "reason": "New reporting identifies Toshiba competition as a significant adverse issue "
               "and says the shares are falling, undermining the expected follow-through."},
    {"decision": "keep", "intent_id": 44, "evidence_ids": [],
     "reason": "No new headline or event fact is available to establish an overnight "
               "invalidation."},
]}


def test_stored_run_6_keep_without_new_evidence_no_longer_voids_its_cancel():
    decisions = {item["intent_id"]: item for item in p15_preopen._validate(
        RUN_6_OUTPUT, RUN_6_ALLOWED
    )}
    assert decisions[42]["decision"] == "cancel"
    assert decisions[44] == RUN_6_OUTPUT["decisions"][2]
    assert decisions[41] == RUN_6_OUTPUT["decisions"][0]


def test_unusable_decision_is_kept_without_voiding_valid_siblings():
    allowed = {1: {"a" * 64}, 2: {"b" * 64}, 3: {"c" * 64}}
    decisions = {item["intent_id"]: item for item in p15_preopen._validate(
        {"schema_version": 1, "decisions": [
            {"intent_id": 1, "decision": "cancel", "reason": "Adverse filing.",
             "evidence_ids": ["a" * 64]},
            {"intent_id": 2, "decision": "cancel", "reason": "Foreign evidence.",
             "evidence_ids": ["a" * 64]},
        ]}, allowed,
    )}
    assert decisions[1]["decision"] == "cancel"
    assert decisions[2] == {"intent_id": 2, "decision": "keep",
                            "reason": f"{p15_preopen.INVALID_DECISION_REASON}: evidence",
                            "evidence_ids": ["b" * 64]}
    assert decisions[3]["decision"] == "keep"
    assert decisions[3]["reason"] == f"{p15_preopen.INVALID_DECISION_REASON}: missing"
    # A cancel must still cite allowlisted evidence; without it the intent is kept.
    assert p15_preopen._validate({"schema_version": 1, "decisions": [
        {"intent_id": 1, "decision": "cancel", "reason": "No basis.", "evidence_ids": []},
    ]}, {1: set()}) == [{"intent_id": 1, "decision": "keep",
                         "reason": f"{p15_preopen.INVALID_DECISION_REASON}: evidence",
                         "evidence_ids": []}]


def test_cancel_applies_beside_a_keep_that_cites_no_new_evidence(con):
    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)

    def mixed(payload):
        first, second = payload["intents"]
        return _result({"schema_version": 1, "decisions": [
            {"intent_id": first["intent_id"], "decision": "cancel",
             "reason": "Adverse update.", "evidence_ids": [first["allowed_evidence_ids"][0]]},
            {"intent_id": second["intent_id"], "decision": "keep",
             "reason": "Nothing new.", "evidence_ids": []},
        ]}, payload)

    result = p15_preopen.run(
        con, session_date=session_date, now=now, generate=mixed,
        fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
    )
    assert result["status"] == "completed" and result["cancelled"] == 1
    assert con.execute(
        "SELECT reason FROM p15_preopen_runs WHERE session_date=?", [session_date]
    ).fetchone() == (None,)


def test_session_without_a_preopen_run_is_recorded_missed_and_flagged(con):
    from engine import p15_evaluation
    from tools import p15_evidence_validation

    _signal_date, session_date = _setup(con)
    p15_preopen.init_schema(con)
    # The pre-open crashed on the store lock: the books still executed the entries.
    assert p15_books.process_pending(con, session_date)["filled"]
    generated_at = datetime(2024, 7, 18, 2, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="no pre-open run"):
        p15_evidence_validation.validate_preopen(con, generated_at, ValueError)

    p15_preopen.capture_after_open(con, session_date, captured_at=generated_at)
    p15_preopen.capture_after_open(con, session_date, captured_at=generated_at)

    assert con.execute(
        "SELECT session_date,status,reason FROM p15_preopen_runs"
    ).fetchall() == [(session_date, "missed", p15_preopen.MISSED_REASON)]
    assert sorted(con.execute(
        "SELECT portfolio_id,decision,reason FROM p15_preopen_decisions"
    ).fetchall()) == [("p15_ai_ranked", "keep", "missed_preopen_run"),
                      ("p15_hybrid_veto", "keep", "missed_preopen_run"),
                      ("p15_rule_control", "keep", "rule_control_noop")]
    p15_evidence_validation.validate_preopen(con, generated_at, ValueError)
    coverage = p15_evaluation.preopen(con, generated_at)["coverage"]
    assert coverage == {"ai_entry_session_count": 1, "reviewed_session_count": 0,
                        "unreviewed_sessions": [session_date.isoformat()]}


def test_reviewed_session_counts_toward_preopen_coverage(con):
    from engine import p15_evaluation

    _signal_date, session_date = _setup(con)
    now = datetime(2024, 7, 17, 13, 10, tzinfo=timezone.utc)
    p15_preopen.run(
        con, session_date=session_date, now=now,
        generate=lambda payload: _result({"schema_version": 1, "decisions": [
            {"intent_id": item["intent_id"], "decision": "keep", "reason": "Nothing new.",
             "evidence_ids": []} for item in payload["intents"]
        ]}, payload),
        fetch_news=_news, clock=lambda: now + timedelta(seconds=2),
    )
    p15_books.process_pending(con, session_date)
    generated_at = datetime(2024, 7, 18, 2, 30, tzinfo=timezone.utc)
    p15_preopen.capture_after_open(con, session_date, captured_at=generated_at)
    assert con.execute("SELECT COUNT(*) FROM p15_preopen_runs").fetchone() == (1,)
    assert p15_evaluation.preopen(con, generated_at)["coverage"] == {
        "ai_entry_session_count": 1, "reviewed_session_count": 1, "unreviewed_sessions": [],
    }


def test_run_database_retries_the_store_until_the_deadline_reserve(tmp_path, monkeypatch):
    waits = []
    real_connect = p15_preopen.db.connect

    def connect(path, **kwargs):
        waits.append(kwargs.get("wait_s"))
        return real_connect(path, **kwargs)

    store = tmp_path / "market.duckdb"
    duckdb.connect(str(store)).close()
    monkeypatch.setattr(p15_preopen, "LOCK_PATH", tmp_path / "preopen.lock")
    monkeypatch.setattr(p15_preopen, "NIGHTLY_LOCK", tmp_path / "nightly.lock")
    monkeypatch.setattr(p15_preopen.db, "connect", connect)
    p15_preopen.run_database(store, now=datetime(2024, 7, 17, 13, 5, tzinfo=timezone.utc))
    assert waits == [20 * 60 - p15_preopen.STORE_WAIT_RESERVE_S]
    assert waits[0] > 10 * settings.LOCK_WAIT_DEFAULT_S
