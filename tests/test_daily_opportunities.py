"""P8 deterministic detection, news provenance, model contract, and replay."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.daily_opportunities import detect
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import (
    agent_model_client,
    daily_opportunity_execution,
    daily_opportunity_news,
    daily_opportunity_read_models,
    daily_opportunity_runner,
    daily_opportunity_store,
)
from sim.schema import init_sim_schema

NOW = datetime(2026, 9, 22, 1, 30, tzinfo=timezone.utc)
MARKET_DATE = date(2026, 9, 21)


def _database(path):
    con = db.connect(path)
    db.init_schema(con)
    db.init_screen_policy_schema(con)
    db.init_mining_schema(con)
    init_sim_schema(con)
    sessions = [MARKET_DATE - timedelta(days=i) for i in range(300)]
    sessions = sorted(value for value in sessions if value.weekday() < 5)[-210:]
    for ticker in ("SPY", "FAST", "QUIET"):
        con.execute(
            "INSERT INTO universe VALUES (?, ?, ?, 'NYSE', ?, 'test', ?, TRUE, TRUE, TRUE)",
            [ticker, ticker, ticker, ticker == "SPY", sessions[0]],
        )
        rows = []
        for index, session in enumerate(sessions):
            close = 100 + index
            volume = 1_000_000
            if ticker == "FAST" and session == MARKET_DATE:
                close, volume = 160, 8_000_000
            rows.append((ticker, session, close - 1, close + 1, close - 2, close, volume))
        con.executemany(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    con.executemany(
        "INSERT INTO screen_results (run_date,ticker,close,rs_rank,template_score,"
        "passes_template,dist_50d,dist_200d,off_52w_low,off_52w_high,base_tight,"
        "vol_dryup,new_today,universe_policy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'all')",
        [(MARKET_DATE, "FAST", 160, 99, 8, True, 0.2, 0.3, 1.0, -0.01, False, False, True),
         (MARKET_DATE, "QUIET", 120, 50, 2, False, 0.0, 0.0, 0.5, -0.2, False, False, False)],
    )
    con.execute(
        "INSERT INTO earnings_calendar VALUES ('FAST', ?, ?, FALSE, 'test', ?)",
        [MARKET_DATE + timedelta(days=10), MARKET_DATE, NOW.replace(tzinfo=None)],
    )
    con.close()


def _news_response(ticker, now):
    body = json.dumps({"news": [{
        "title": f"{ticker} announces material trial result",
        "publisher": "Example Wire", "link": "https://example.test/story",
        "providerPublishTime": int((now - timedelta(hours=1)).timestamp()),
    }]}).encode()
    return daily_opportunity_news.Response(body, "application/json", 200, now, now)


def _connector(model_input):
    assessments = []
    for candidate in model_input["candidates"]:
        evidence = [candidate["evidence_id"]]
        if candidate["ticker"] == "FAST":
            assessments.append({
                "ticker": "FAST", "decision": "watch", "action": "none",
                "horizon_sessions": 5, "confidence": 0.7,
                "thesis": "Abnormal price and volume merit confirmation.",
                "invalidation": "Momentum fails below the observed close.",
                "evidence_ids": evidence,
                "alert": {"direction": "above", "price": 165.0, "expires_sessions": 5},
            })
        else:
            assessments.append({
                "ticker": candidate["ticker"], "decision": "ignore", "action": "none",
                "horizon_sessions": 1, "confidence": 0.5, "thesis": "No trade.",
                "invalidation": "New evidence.", "evidence_ids": evidence, "alert": None,
            })
    request = agent_model_client.opportunity_request_payload(model_input)
    return agent_model_client.ConnectorResult(
        output={"schema_version": 1, "assessments": assessments},
        response_id="resp-p8", model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION, proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="upstream-p8",
        model_catalog_entry_sha256=agent_model_client.MODEL_CATALOG_ENTRY_SHA256,
        request_sha256=canonical_sha256(request),
        usage={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
    )


def test_detector_ranks_abnormal_liquid_move_with_point_in_time_evidence(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path, read_only=True)
    result = detect(con, MARKET_DATE, limit=2)
    con.close()

    assert result["candidates"][0]["ticker"] == "FAST"
    assert result["candidates"][0]["relative_volume_20d"] == pytest.approx(8.0)
    assert result["candidates"][0]["earnings"]["next_date"] == "2026-10-01"
    assert result["bundle_sha256"] == canonical_sha256(
        {key: value for key, value in result.items() if key != "bundle_sha256"}
    )


def test_daily_run_records_news_assessments_alert_and_replays_without_calls(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    calls = {"model": 0, "news": 0}

    def generate(payload):
        calls["model"] += 1
        return _connector(payload)

    def news(ticker, now):
        calls["news"] += 1
        return _news_response(ticker, now)

    first = daily_opportunity_runner.run(database=path, now=NOW, generate=generate, fetch_news=news)
    second = daily_opportunity_runner.run(database=path, now=NOW, generate=generate, fetch_news=news)

    assert first == {
        "status": "completed", "market_date": "2026-09-21",
        "assessment_count": 1, "news_status": "available", "paper_order_count": 0,
        "execution_authority": "local_simulator_only", "replayed": False,
    }
    assert second == {**first, "replayed": True}
    assert calls == {"model": 1, "news": 2}
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_news_responses").fetchone() == (2,)
    assert con.execute(
        "SELECT ticker, direction, trigger_price, expires_sessions "
        "FROM daily_opportunity_alerts"
    ).fetchone() == ("FAST", "above", 165.0, 5)
    assert con.execute(
        "SELECT event_type, detail FROM daily_opportunity_alert_events ORDER BY id"
    ).fetchall() == [("opened", "model_watch")]
    con.close()


def test_malformed_or_out_of_bounds_model_output_fails_closed(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)

    def malformed(payload):
        result = _connector(payload)
        result.output["assessments"][0]["alert"]["price"] = 1_000_000
        return result

    result = daily_opportunity_runner.run(
        database=path, now=NOW, generate=malformed, fetch_news=_news_response
    )
    assert result["status"] == "failed"
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_assessments").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_alerts").fetchone() == (0,)
    assert con.execute("SELECT status FROM daily_opportunity_runs").fetchone() == ("failed",)
    con.close()


def test_news_failure_is_explicit_and_does_not_fabricate_headlines():
    def fail(_ticker, _now):
        raise daily_opportunity_news.NewsError("offline")

    result = daily_opportunity_news.capture(["FAST"], now=NOW, fetch=fail)
    assert result["status"] == "unavailable"
    assert result["receipts"] == result["observations"] == []
    assert result["failures"] == [{"ticker": "FAST", "reason": "offline"}]


def test_alert_triggers_only_on_later_bar_and_expires_by_sessions(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    daily_opportunity_runner.run(
        database=path, now=NOW, generate=_connector, fetch_news=_news_response
    )
    con = db.connect(path)
    next_date = date(2026, 9, 22)
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
        [("SPY", next_date, 120, 121, 119, 120, 1_000_000),
         ("FAST", next_date, 164, 166, 160, 165, 2_000_000)],
    )
    with db.transaction(con):
        first = daily_opportunity_store.evaluate_alerts(con, next_date)
    with db.transaction(con):
        second = daily_opportunity_store.evaluate_alerts(con, next_date)
    assert first[0]["ticker"] == "FAST"
    assert second == []
    assert con.execute(
        "SELECT event_type FROM daily_opportunity_alert_events ORDER BY id"
    ).fetchall() == [("opened",), ("triggered",)]
    con.close()


def test_alert_expires_after_its_session_budget(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    daily_opportunity_runner.run(
        database=path, now=NOW, generate=_connector, fetch_news=_news_response
    )
    con = db.connect(path)
    later = date(2026, 9, 30)
    for offset in range(1, 10):
        session = MARKET_DATE + timedelta(days=offset)
        if session.weekday() < 5:
            con.execute(
                "INSERT INTO prices (ticker,date,open,high,low,close,volume) VALUES ('SPY',?,?,?,?,?,?)",
                [session, 120, 121, 119, 120, 1_000_000],
            )
    with db.transaction(con):
        assert daily_opportunity_store.evaluate_alerts(con, later) == []
    assert con.execute(
        "SELECT event_type FROM daily_opportunity_alert_events ORDER BY id"
    ).fetchall() == [("opened",), ("expired",)]
    con.close()


def test_active_isolated_book_gets_only_capped_next_open_pending_order(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=True)
    con.close()

    def swing(payload):
        result = _connector(payload)
        for item in result.output["assessments"]:
            if item["ticker"] == "FAST":
                item.update(decision="swing", action="buy", alert=None)
        return result

    result = daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response
    )
    assert result["paper_order_count"] == 1
    con = db.connect(path, read_only=True)
    order = con.execute(
        "SELECT portfolio_id, ticker, side, qty, signal_date, status FROM sim_orders"
    ).fetchone()
    assert order[:3] == ("daily_opportunity_agent_v1", "FAST", "buy")
    assert order[3] == pytest.approx(1000 / 160)
    assert order[4:] == (MARKET_DATE, "pending")
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_order_attribution").fetchone() == (1,)
    con.close()


def test_status_is_bounded_and_reports_inactive_book(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=False)
    con.close()
    daily_opportunity_runner.run(
        database=path, now=NOW, generate=_connector, fetch_news=_news_response
    )
    con = db.connect(path, read_only=True)
    status = daily_opportunity_read_models.status(con)
    con.close()
    assert status["status"] == "ok"
    assert status["book_active"] is False
    assert status["broker_route"] == "absent"
    assert status["open_alert_count"] == 1
    assert status["paper_order_count"] == 0
    assert status["model"] == agent_model_client.MODEL
    assert status["position_count"] == status["pending_order_count"] == 0
    assert status["schedule"]["on_calendar"] == "Tue..Sat *-*-* 02:00:00 UTC"


def test_activation_requires_exact_empty_book(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=False)
        result = daily_opportunity_execution.activate_book(con, MARKET_DATE)
    assert result["active"] is True
    assert result["execution_authority"] == "local_simulator_only"
    assert con.execute(
        "SELECT active FROM portfolios WHERE id = 'daily_opportunity_agent_v1'"
    ).fetchone() == (True,)
    con.close()
