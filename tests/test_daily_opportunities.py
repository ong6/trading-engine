"""P8 deterministic detection, news provenance, model contract, and replay."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.daily_opportunities import detect
from engine.gap_volume_candidate import select
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import (
    agent_evaluation,
    agent_model_client,
    daily_opportunity_execution,
    daily_opportunity_news,
    daily_opportunity_read_models,
    daily_opportunity_runner,
    daily_opportunity_store,
    daily_opportunity_tools,
)
from sim import league
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
            close = 100 + index * 0.1
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


def _tool_connector(model_input):
    assessment = model_input["assessment"]
    request = agent_model_client.trade_tool_request_payload(model_input)
    return agent_model_client.ConnectorResult(
        output={"name": "submit_paper_trade", "call_id": "call-p8",
                "arguments": assessment},
        response_id="resp-tool-p8", model=agent_model_client.MODEL,
        model_version=agent_model_client.MODEL_VERSION, proxy_version="0.7",
        proxy_source_sha256=agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        traecli_runtime=agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="upstream-tool-p8",
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
    assert select(result)["ticker"] == "FAST"


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
        "paper_order_ids": [], "execution_authority": "local_simulator_only",
        "replayed": False,
    }
    assert second == {**first, "replayed": True}
    assert calls == {"model": 1, "news": 2}
    con = db.connect(path, read_only=True)
    assert agent_evaluation.status(con)["trace_count"] == 1
    assert agent_evaluation.status(con)["decision_count"] == 1
    assert agent_evaluation.status(con)["label_count"] == 0
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_news_responses").fetchone() == (2,)
    assert con.execute(
        "SELECT ticker, direction, trigger_price, expires_sessions "
        "FROM daily_opportunity_alerts"
    ).fetchone() == ("FAST", "above", 165.0, 5)
    assert con.execute(
        "SELECT event_type, detail FROM daily_opportunity_alert_events ORDER BY id"
    ).fetchall() == [("opened", "model_watch")]
    con.close()


def test_evaluation_trace_replay_rejects_identity_drift(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    daily_opportunity_runner.run(
        database=path, now=NOW, generate=_connector, fetch_news=_news_response
    )
    con = db.connect(path)
    row = con.execute(
        "SELECT id, window_id, policy_id, cadence, prompt_role, market_date, observed_at, "
        "completed_at, information_cutoff_at, source_kind, source_identifier, source_refs, "
        "input_payload, output_payload, request_sha256, response_id, model, model_version, "
        "instructions_sha256, toolset_sha256, model_catalog_entry_sha256, proxy_source_sha256, "
        "traecli_runtime, upstream_model_family, upstream_request_id, latency_ms, input_tokens, "
        "output_tokens, total_tokens, terminal_status, execution_authority FROM agent_evaluation_traces"
    ).fetchone()
    columns = [item[0] for item in con.description]
    stored = dict(zip(columns, row, strict=True))
    decisions = [json.loads(item[0]) for item in con.execute(
        "SELECT decision_payload FROM agent_evaluation_decisions ORDER BY id"
    ).fetchall()]
    trace = {
        "window_id": stored["window_id"], "policy_id": stored["policy_id"],
        "cadence": stored["cadence"], "prompt_role": stored["prompt_role"],
        "market_date": stored["market_date"],
        "observed_at": stored["observed_at"].replace(tzinfo=timezone.utc),
        "completed_at": stored["completed_at"].replace(tzinfo=timezone.utc),
        "information_cutoff_at": stored["information_cutoff_at"].replace(tzinfo=timezone.utc),
        "source_kind": stored["source_kind"], "source_identifier": stored["source_identifier"],
        "source_refs": json.loads(stored["source_refs"]),
        "input_payload": json.loads(stored["input_payload"]),
        "output_payload": json.loads(stored["output_payload"]),
        "request_sha256": stored["request_sha256"], "response_id": stored["response_id"],
        "model": stored["model"], "model_version": stored["model_version"],
        "instructions_sha256": stored["instructions_sha256"],
        "toolset_sha256": stored["toolset_sha256"],
        "model_catalog_entry_sha256": stored["model_catalog_entry_sha256"],
        "proxy_source_sha256": stored["proxy_source_sha256"],
        "traecli_runtime": stored["traecli_runtime"],
        "upstream_model_family": stored["upstream_model_family"],
        "upstream_request_id": stored["upstream_request_id"],
        "latency_ms": stored["latency_ms"],
        "usage": {"input_tokens": stored["input_tokens"],
                  "output_tokens": stored["output_tokens"],
                  "total_tokens": stored["total_tokens"]},
        "terminal_status": stored["terminal_status"],
        "execution_authority": stored["execution_authority"], "decisions": decisions,
    }
    assert agent_evaluation.record_trace(con, trace)["replayed"] is True
    trace["output_payload"] = {"changed": True}
    with pytest.raises(agent_evaluation.EvaluationError, match="differs"):
        agent_evaluation.record_trace(con, trace)
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


def test_evaluation_labels_wait_for_horizon_and_replay_exactly(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    daily_opportunity_runner.run(
        database=path, now=NOW, generate=_connector, fetch_news=_news_response
    )
    con = db.connect(path)
    decision = con.execute(
        "SELECT ticker FROM agent_evaluation_decisions ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for offset in range(1, 32):
        session = MARKET_DATE + timedelta(days=offset)
        if session.weekday() >= 5:
            continue
        for ticker in {"SPY", decision}:
            con.execute(
                "INSERT OR IGNORE INTO prices (ticker,date,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?)",
                [ticker, session, 100, 102, 98, 101, 1_000_000],
            )
    with db.transaction(con):
        first = agent_evaluation.label_mature(con, labeled_at=NOW + timedelta(days=32))
    with db.transaction(con):
        second = agent_evaluation.label_mature(con, labeled_at=NOW + timedelta(days=32))
    assert first["inserted"] == 4
    assert second["inserted"] == 0
    assert con.execute(
        "SELECT horizon_sessions FROM agent_evaluation_labels ORDER BY horizon_sessions"
    ).fetchall() == [(1,), (5,), (10,), (20,)]
    con.close()


def test_hourly_trace_labels_start_after_observation_date(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    agent_evaluation.init_schema(con)
    trace = {
        "window_id": "hourly_market_watch_v1:2026-09-22T15",
        "policy_id": "hourly_market_watch_v1", "cadence": "hourly",
        "prompt_role": "rapid_catalyst_watch", "market_date": MARKET_DATE,
        "observed_at": datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
        "information_cutoff_at": datetime(2026, 9, 22, 15, 1, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 9, 22, 15, 2, tzinfo=timezone.utc),
        "source_kind": "jsonl_artifact", "source_identifier": "test:window",
        "source_refs": [{"kind": "artifact", "sha256": "a" * 64}],
        "input_payload": {"test": True}, "output_payload": {"test": True},
        "request_sha256": "b" * 64, "response_id": "response-test",
        "model": agent_model_client.MODEL, "model_version": agent_model_client.MODEL_VERSION,
        "instructions_sha256": "c" * 64, "toolset_sha256": "d" * 64,
        "model_catalog_entry_sha256": "e" * 64, "proxy_source_sha256": "f" * 64,
        "traecli_runtime": agent_model_client.REQUIRED_TRAECLI_RUNTIME,
        "upstream_model_family": agent_model_client.UPSTREAM_MODEL_FAMILY,
        "upstream_request_id": "upstream-test", "latency_ms": 100.0,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "terminal_status": "completed", "execution_authority": "none",
        "decisions": [{"ticker": "FAST", "decision": "watch", "action": "none",
                       "horizon_sessions": 5, "confidence": 0.5}],
    }
    agent_evaluation.record_trace(con, trace)
    con.executemany(
        "INSERT OR IGNORE INTO prices (ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
        [("SPY", date(2026, 9, 22), 100, 101, 99, 100, 1_000_000),
         ("FAST", date(2026, 9, 22), 100, 101, 99, 100, 1_000_000),
         ("SPY", date(2026, 9, 23), 101, 102, 100, 101, 1_000_000),
         ("FAST", date(2026, 9, 23), 101, 103, 100, 102, 1_000_000)],
    )
    with db.transaction(con):
        agent_evaluation.label_mature(con, labeled_at=NOW + timedelta(days=3))
    assert con.execute(
        "SELECT entry_date FROM agent_evaluation_labels WHERE horizon_sessions=1"
    ).fetchone() == (date(2026, 9, 23),)
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
        database=path, now=NOW, generate=swing, fetch_news=_news_response,
        tool_generate=_tool_connector,
    )
    assert result["paper_order_count"] == 1
    con = db.connect(path, read_only=True)
    assessment_id = con.execute(
        "SELECT id FROM daily_opportunity_assessments WHERE ticker = 'FAST'"
    ).fetchone()[0]
    con.close()
    tool_result = daily_opportunity_tools.submit(
        assessment_id, database=path, now=NOW + timedelta(minutes=1),
        generate=_tool_connector, lock_path=tmp_path / "tool.lock",
    )
    replay = daily_opportunity_tools.submit(
        assessment_id, database=path, now=NOW + timedelta(minutes=2),
        generate=lambda _payload: pytest.fail("replay must not call model"),
        lock_path=tmp_path / "tool.lock",
    )
    assert tool_result["paper_order_id"] == result["paper_order_ids"][0]
    assert replay["replayed"] is True
    assert replay["paper_order_id"] == tool_result["paper_order_id"]
    assert replay["execution_authority"] == "local_simulator_only"
    con = db.connect(path, read_only=True)
    order = con.execute(
        "SELECT portfolio_id, ticker, side, qty, signal_date, status FROM sim_orders"
    ).fetchone()
    assert order[:3] == ("daily_opportunity_agent_v1", "FAST", "buy")
    assert order[3] == pytest.approx(1000 / 160)
    assert order[4:] == (MARKET_DATE, "pending")
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM daily_opportunity_order_attribution").fetchone() == (1,)
    assert con.execute(
        "SELECT max_hold_sessions,invalidation_kind,invalidation_price,signal_reference_price "
        "FROM daily_opportunity_exit_rules"
    ).fetchone() == (5, "close_below_signal_low", 158.0, 160.0)
    assert con.execute(
        "SELECT COUNT(*) FROM agent_evaluation_execution_links"
    ).fetchone() == (1,)
    con.close()
    con = db.connect(path)
    fill_date = date(2026, 9, 22)
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) VALUES ('FAST',?,?,?,?,?,?)",
        [fill_date, 162, 166, 160, 164, 2_000_000],
    )
    counts = league.fill_pending(con, fill_date)
    lifecycle = daily_opportunity_execution.process_lifecycle(
        con, fill_date, captured_at=NOW + timedelta(days=1)
    )
    assert counts == {"filled": 1, "rejected": 0, "pending": 0}
    assert lifecycle == {"execution_quality_inserted": 1, "exit_orders_created": 0}
    assert con.execute(
        "SELECT fill_date, open_px, fill_px FROM sim_fills"
    ).fetchone()[0:2] == (fill_date, 162.0)
    quality = con.execute(
        "SELECT fill_time_precision,decision_to_tool_ms,tool_latency_ms,tool_to_order_ms,"
        "order_to_fill_sessions,arrival_price,open_price,gap_shortfall_bps,"
        "total_shortfall_bps,cost_bps FROM daily_opportunity_execution_quality"
    ).fetchone()
    assert quality[:5] == ("session_open_date", 0.0, 0.0, 0.0, 1)
    assert quality[5:8] == pytest.approx((160.0, 162.0, 125.0))
    assert quality[8] > quality[7]
    assert quality[9] > 0
    con.close()


def test_agent_position_exits_next_open_on_max_hold(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=True)
    con.close()

    def swing(payload):
        result = _connector(payload)
        result.output["assessments"][0].update(
            decision="swing", action="buy", alert=None, horizon_sessions=2
        )
        return result

    daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response,
        tool_generate=_tool_connector,
    )
    con = db.connect(path)
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    third = date(2026, 9, 24)
    for session, close in ((first, 164), (second, 165), (third, 166)):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('FAST',?,?,?,?,?,?)", [session, close - 1, close + 1, close - 2, close, 2_000_000],
        )
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('SPY',?,?,?,?,?,?)", [session, 120, 121, 119, 120, 2_000_000],
        )
    assert league.fill_pending(con, first)["filled"] == 1
    assert daily_opportunity_execution.process_lifecycle(
        con, first, captured_at=NOW + timedelta(days=1)
    ) == {"execution_quality_inserted": 1, "exit_orders_created": 0}
    assert daily_opportunity_execution.process_lifecycle(
        con, second, captured_at=NOW + timedelta(days=2)
    )["exit_orders_created"] == 1
    assert daily_opportunity_execution.process_lifecycle(
        con, second, captured_at=NOW + timedelta(days=2, minutes=1)
    ) == {"execution_quality_inserted": 0, "exit_orders_created": 0}
    assert con.execute(
        "SELECT reason,signal_date,attempt FROM daily_opportunity_exit_events"
    ).fetchone() == ("maximum_hold_sessions", second, 1)
    assert con.execute(
        "SELECT side,status FROM sim_orders ORDER BY id DESC LIMIT 1"
    ).fetchone() == ("sell", "pending")
    assert league.fill_pending(con, third)["filled"] == 1
    assert daily_opportunity_execution.process_lifecycle(
        con, third, captured_at=NOW + timedelta(days=3)
    )["execution_quality_inserted"] == 1
    assert con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker='FAST'",
        [daily_opportunity_store.PORTFOLIO_ID],
    ).fetchone() == (0.0,)
    assert con.execute(
        "SELECT COUNT(*) FROM daily_opportunity_execution_quality"
    ).fetchone() == (2,)
    con.close()


def test_agent_position_invalidation_is_machine_readable_and_next_open(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=True)
    con.close()

    def swing(payload):
        result = _connector(payload)
        result.output["assessments"][0].update(
            decision="swing", action="buy", alert=None, horizon_sessions=10,
            invalidation="Any prose the model chooses cannot execute directly.",
        )
        return result

    daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response,
        tool_generate=_tool_connector,
    )
    con = db.connect(path)
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    third = date(2026, 9, 24)
    for session, close in ((first, 164), (second, 157), (third, 156)):
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('FAST',?,?,?,?,?,?)", [session, close, close + 1, close - 1, close, 2_000_000],
        )
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('SPY',?,?,?,?,?,?)", [session, 120, 121, 119, 120, 2_000_000],
        )
    league.fill_pending(con, first)
    daily_opportunity_execution.process_lifecycle(
        con, first, captured_at=NOW + timedelta(days=1)
    )
    assert daily_opportunity_execution.process_lifecycle(
        con, second, captured_at=NOW + timedelta(days=2)
    )["exit_orders_created"] == 1
    assert con.execute(
        "SELECT reason,observed_close,signal_date,attempt FROM daily_opportunity_exit_events"
    ).fetchone() == ("close_below_signal_low", 157.0, second, 1)
    assert con.execute("SELECT COUNT(*) FROM sim_fills WHERE side='sell'").fetchone() == (0,)
    league.fill_pending(con, third)
    daily_opportunity_execution.process_lifecycle(
        con, third, captured_at=NOW + timedelta(days=3)
    )
    assert con.execute("SELECT COUNT(*) FROM sim_fills WHERE side='sell'").fetchone() == (1,)
    con.close()


def test_rejected_agent_exit_is_retried_once_no_exit_is_pending(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=True)
    con.close()

    def swing(payload):
        result = _connector(payload)
        result.output["assessments"][0].update(
            decision="swing", action="buy", alert=None, horizon_sessions=1
        )
        return result

    daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response,
        tool_generate=_tool_connector,
    )
    con = db.connect(path)
    first, second = date(2026, 9, 22), date(2026, 9, 23)
    for session in (first, second):
        con.execute(
            "INSERT INTO prices VALUES ('FAST',?,?,?,?,?,?,?,?)",
            [session, 163, 165, 162, 164, 2_000_000, "test", NOW],
        )
        con.execute(
            "INSERT INTO prices VALUES ('SPY',?,?,?,?,?,?,?,?)",
            [session, 120, 121, 119, 120, 2_000_000, "test", NOW],
        )
    league.fill_pending(con, first)
    assert daily_opportunity_execution.process_lifecycle(
        con, first, captured_at=NOW + timedelta(days=1)
    )["exit_orders_created"] == 1
    con.execute(
        "UPDATE sim_orders SET status='rejected',reject_reason='no_bar' WHERE side='sell'"
    )
    assert daily_opportunity_execution.process_lifecycle(
        con, second, captured_at=NOW + timedelta(days=2)
    )["exit_orders_created"] == 1
    assert con.execute(
        "SELECT attempt FROM daily_opportunity_exit_events ORDER BY attempt"
    ).fetchall() == [(1,), (2,)]
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE side='sell' AND status='pending'"
    ).fetchone() == (1,)
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
    assert status["exit_rule_count"] == status["exit_event_count"] == 0
    assert status["execution_quality_count"] == 0
    assert status["schedule"]["nightly"] == "Tue..Sat *-*-* 02:00:00 UTC"
    assert status["algorithm_candidate"]["ticker"] == "FAST"
    assert status["algorithm_agent_veto"] == {
        "ticker": "FAST", "algorithm_action": "buy", "agent_outcome": "veto",
        "execution_authority": "none",
    }


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


def test_trade_tool_rejects_inactive_book_before_model_call(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=False)
    con.close()

    def swing(payload):
        result = _connector(payload)
        result.output["assessments"][0].update(
            decision="swing", action="buy", alert=None
        )
        return result

    daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response
    )
    con = db.connect(path, read_only=True)
    assessment_id = con.execute("SELECT id FROM daily_opportunity_assessments").fetchone()[0]
    con.close()
    with pytest.raises(daily_opportunity_tools.ToolCallError, match="inactive"):
        daily_opportunity_tools.submit(
            assessment_id, database=path, now=NOW,
            generate=lambda _payload: pytest.fail("inactive book must not invoke model"),
            lock_path=tmp_path / "tool.lock",
        )


def test_completed_tool_call_resumes_order_without_second_model_call(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    with db.transaction(con):
        daily_opportunity_store.init_schema(con)
        daily_opportunity_execution.initialize_book(con, MARKET_DATE, active=True)
    con.close()

    def swing(payload):
        result = _connector(payload)
        result.output["assessments"][0].update(
            decision="swing", action="buy", alert=None
        )
        return result

    daily_opportunity_runner.run(
        database=path, now=NOW, generate=swing, fetch_news=_news_response,
        tool_generate=_tool_connector,
    )
    con = db.connect(path)
    assessment_id = con.execute("SELECT id FROM daily_opportunity_assessments").fetchone()[0]
    con.execute("DELETE FROM daily_opportunity_order_attribution")
    con.execute("DELETE FROM sim_orders")
    con.close()
    recovered = daily_opportunity_tools.submit(
        assessment_id, database=path, now=NOW + timedelta(minutes=2),
        generate=lambda _payload: pytest.fail("completed tool must not call model"),
        lock_path=tmp_path / "tool.lock",
    )
    assert recovered["replayed"] is True
    assert recovered["paper_order_id"] is not None
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (1,)
    con.close()
