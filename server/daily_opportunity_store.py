"""Append-only P8 daily opportunity, assessment, and alert storage."""
from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from engine.lib.provenance import canonical_sha256

PORTFOLIO_ID = "daily_opportunity_agent_v1"
MAX_OPEN_ALERTS = 10
ALERT_EVALUATION_LIMIT = 10


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_runs (
        id BIGINT PRIMARY KEY, market_date DATE UNIQUE, bundle_payload VARCHAR NOT NULL,
        bundle_sha256 VARCHAR NOT NULL UNIQUE, news_status VARCHAR NOT NULL,
        model_request_sha256 VARCHAR, model_response_id VARCHAR, model_response_payload VARCHAR,
        status VARCHAR NOT NULL,
        reason VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_assessments (
        id BIGINT PRIMARY KEY, run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL,
        decision VARCHAR NOT NULL, action VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL,
        confidence DOUBLE NOT NULL, thesis VARCHAR NOT NULL, invalidation VARCHAR NOT NULL,
        evidence_ids VARCHAR NOT NULL, assessment_payload VARCHAR NOT NULL,
        assessment_sha256 VARCHAR NOT NULL UNIQUE, created_at TIMESTAMP NOT NULL,
        UNIQUE(run_id, ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_alerts (
        id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, ticker VARCHAR NOT NULL,
        direction VARCHAR NOT NULL, trigger_price DOUBLE NOT NULL, created_market_date DATE NOT NULL,
        expires_sessions INTEGER NOT NULL, alert_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_alert_events (
        id BIGINT PRIMARY KEY, alert_id BIGINT NOT NULL, event_type VARCHAR NOT NULL,
        market_date DATE NOT NULL, detail VARCHAR NOT NULL, event_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(alert_id, event_type))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_news_responses (
        run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL,
        requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL,
        content_type VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL,
        receipt_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(run_id, ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_order_attribution (
        order_id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, run_id BIGINT NOT NULL,
        portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL,
        quantity DOUBLE NOT NULL, signal_date DATE NOT NULL, assessment_sha256 VARCHAR NOT NULL,
        attribution_sha256 VARCHAR NOT NULL UNIQUE, recorded_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_tool_attempts (
        id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, run_id BIGINT NOT NULL,
        idempotency_key VARCHAR NOT NULL UNIQUE, request_payload VARCHAR NOT NULL,
        request_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, response_id VARCHAR,
        call_id VARCHAR, arguments_payload VARCHAR, response_payload VARCHAR,
        started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP)"""
    )


def next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    allowed = {
        "daily_opportunity_runs",
        "daily_opportunity_assessments",
        "daily_opportunity_alerts",
        "daily_opportunity_alert_events",
        "daily_opportunity_tool_attempts",
    }
    if table not in allowed:
        raise ValueError("invalid daily opportunity table")
    return int(con.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()[0])


def find_run(con: duckdb.DuckDBPyConnection, market_date: date) -> dict | None:
    cursor = con.execute(
        "SELECT id, bundle_payload, bundle_sha256, news_status, model_request_sha256, "
        "model_response_id, model_response_payload, status, reason, started_at, completed_at "
        "FROM daily_opportunity_runs WHERE market_date = ?", [market_date]
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip((item[0] for item in cursor.description), row, strict=True))


def insert_run(
    con: duckdb.DuckDBPyConnection, bundle: dict, *, news_status: str, started_at: datetime,
    news_receipts: list[dict] | None = None,
) -> int:
    run_id = next_id(con, "daily_opportunity_runs")
    con.execute(
        "INSERT INTO daily_opportunity_runs VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, 'in_progress', "
        "NULL, ?, NULL)",
        [run_id, date.fromisoformat(bundle["market_date"]), json.dumps(bundle, sort_keys=True, separators=(",", ":")), bundle["bundle_sha256"], news_status, started_at],
    )
    for receipt in news_receipts or []:
        con.execute(
            "INSERT INTO daily_opportunity_news_responses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [run_id, receipt["ticker"], receipt["endpoint"], receipt["requested_at"],
             receipt["received_at"], receipt["http_status"], receipt["content_type"],
             receipt["response_sha256"], receipt["response_body"], receipt["receipt_sha256"]],
        )
    return run_id


def complete_run(
    con: duckdb.DuckDBPyConnection, run_id: int, *, request_sha256: str, response_id: str,
    assessments: list[dict], response_payload: dict, completed_at: datetime
) -> None:
    assessment_id = next_id(con, "daily_opportunity_assessments")
    alert_id = next_id(con, "daily_opportunity_alerts")
    for assessment in assessments:
        payload = json.dumps(assessment, sort_keys=True, separators=(",", ":"))
        digest = canonical_sha256(assessment)
        con.execute(
            "INSERT INTO daily_opportunity_assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [assessment_id, run_id, assessment["ticker"], assessment["decision"],
             assessment["action"], assessment["horizon_sessions"], assessment["confidence"],
             assessment["thesis"], assessment["invalidation"],
             json.dumps(assessment["evidence_ids"], separators=(",", ":")), payload, digest, completed_at],
        )
        alert = assessment["alert"]
        if alert is not None:
            open_count = con.execute(
                "SELECT COUNT(*) FROM daily_opportunity_alerts a WHERE NOT EXISTS ("
                "SELECT 1 FROM daily_opportunity_alert_events e WHERE e.alert_id = a.id "
                "AND e.event_type IN ('triggered','expired'))"
            ).fetchone()[0]
            open_alert = con.execute(
                "SELECT 1 FROM daily_opportunity_alerts a WHERE a.ticker = ? AND NOT EXISTS ("
                "SELECT 1 FROM daily_opportunity_alert_events e WHERE e.alert_id = a.id "
                "AND e.event_type IN ('triggered','expired')) LIMIT 1",
                [assessment["ticker"]],
            ).fetchone()
            if open_alert is not None or open_count >= MAX_OPEN_ALERTS:
                assessment_id += 1
                continue
            identity = {
                "assessment_sha256": digest, "ticker": assessment["ticker"],
                "direction": alert["direction"], "trigger_price": alert["price"],
                "created_market_date": assessment["market_date"],
                "expires_sessions": alert["expires_sessions"],
            }
            con.execute(
                "INSERT INTO daily_opportunity_alerts (id, assessment_id, ticker, direction, "
                "trigger_price, created_market_date, expires_sessions, alert_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [alert_id, assessment_id, assessment["ticker"], alert["direction"],
                 alert["price"], date.fromisoformat(assessment["market_date"]),
                 alert["expires_sessions"], canonical_sha256(identity)],
            )
            event = {"alert_sha256": canonical_sha256(identity), "event_type": "opened",
                     "market_date": assessment["market_date"], "detail": "model_watch"}
            con.execute(
                "INSERT INTO daily_opportunity_alert_events VALUES (?, ?, 'opened', ?, 'model_watch', ?)",
                [next_id(con, "daily_opportunity_alert_events"), alert_id,
                 date.fromisoformat(assessment["market_date"]), canonical_sha256(event)],
            )
            alert_id += 1
        assessment_id += 1
    con.execute(
        "UPDATE daily_opportunity_runs SET model_request_sha256 = ?, model_response_id = ?, "
        "model_response_payload = ?, "
        "status = 'completed', completed_at = ? WHERE id = ? AND status = 'in_progress'",
        [request_sha256, response_id, json.dumps(response_payload, sort_keys=True, separators=(",", ":")), completed_at, run_id],
    )


def fail_run(con: duckdb.DuckDBPyConnection, run_id: int, reason: str, now: datetime) -> None:
    con.execute(
        "UPDATE daily_opportunity_runs SET status = 'failed', reason = ?, completed_at = ? "
        "WHERE id = ? AND status = 'in_progress'", [reason[:512], now, run_id]
    )


def evaluate_alerts(con: duckdb.DuckDBPyConnection, market_date: date) -> list[dict]:
    """Append terminal events for alerts crossed or expired on a later real session."""
    rows = con.execute(
        "SELECT a.id, a.ticker, a.direction, a.trigger_price, a.created_market_date, "
        "a.expires_sessions, a.alert_sha256 FROM daily_opportunity_alerts a "
        "WHERE NOT EXISTS (SELECT 1 FROM daily_opportunity_alert_events e "
        "WHERE e.alert_id = a.id AND e.event_type IN ('triggered','expired')) "
        "ORDER BY a.id LIMIT ?",
        [ALERT_EVALUATION_LIMIT],
    ).fetchall()
    triggered = []
    for alert_id, ticker, direction, price, created, expires, alert_sha256 in rows:
        if market_date <= created:
            continue
        elapsed = int(con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker = 'SPY' "
            "AND date > ? AND date <= ? AND volume > 0", [created, market_date]
        ).fetchone()[0])
        bar = con.execute(
            "SELECT high, low FROM prices WHERE ticker = ? AND date = ? AND volume > 0",
            [ticker, market_date],
        ).fetchone()
        crossed = bar is not None and (
            (direction == "above" and bar[0] is not None and float(bar[0]) >= price)
            or (direction == "below" and bar[1] is not None and float(bar[1]) <= price)
        )
        event_type = "triggered" if crossed and elapsed <= expires else ("expired" if elapsed > expires else None)
        if event_type is None:
            continue
        detail = "price_crossed" if event_type == "triggered" else "session_expiry"
        event = {"alert_sha256": alert_sha256, "event_type": event_type,
                 "market_date": market_date.isoformat(), "detail": detail}
        con.execute(
            "INSERT INTO daily_opportunity_alert_events VALUES (?, ?, ?, ?, ?, ?)",
            [next_id(con, "daily_opportunity_alert_events"), alert_id, event_type, market_date,
             detail, canonical_sha256(event)],
        )
        if event_type == "triggered":
            triggered.append({"alert_id": alert_id, "ticker": ticker,
                              "alert_sha256": alert_sha256, "direction": direction,
                              "trigger_price": float(price)})
    return triggered


def start_tool_attempt(
    con: duckdb.DuckDBPyConnection, assessment_id: int, run_id: int,
    request: dict, request_sha256: str, now: datetime,
) -> dict:
    existing = con.execute(
        "SELECT id, status, arguments_payload FROM daily_opportunity_tool_attempts "
        "WHERE assessment_id = ?", [assessment_id]
    ).fetchone()
    if existing is not None:
        return {"id": existing[0], "status": existing[1], "arguments_payload": existing[2]}
    attempt_id = next_id(con, "daily_opportunity_tool_attempts")
    key = f"p8-trade:{canonical_sha256({'assessment_id': assessment_id, 'run_id': run_id})}"
    con.execute(
        "INSERT INTO daily_opportunity_tool_attempts VALUES (?, ?, ?, ?, ?, ?, 'in_progress', "
        "NULL, NULL, NULL, NULL, ?, NULL)",
        [attempt_id, assessment_id, run_id, key,
         json.dumps(request, sort_keys=True, separators=(",", ":")), request_sha256, now],
    )
    return {"id": attempt_id, "status": "new", "arguments_payload": None}


def complete_tool_attempt(
    con: duckdb.DuckDBPyConnection, attempt_id: int, *, response_id: str, call_id: str,
    arguments: dict, response: dict, now: datetime,
) -> None:
    changed = con.execute(
        "UPDATE daily_opportunity_tool_attempts SET status = 'completed', response_id = ?, "
        "call_id = ?, arguments_payload = ?, response_payload = ?, completed_at = ? "
        "WHERE id = ? AND status = 'in_progress' RETURNING id",
        [response_id, call_id, json.dumps(arguments, sort_keys=True, separators=(",", ":")),
         json.dumps(response, sort_keys=True, separators=(",", ":")), now, attempt_id],
    ).fetchone()
    if changed is None:
        raise ValueError("daily opportunity tool attempt is not open")


def mark_tool_uncertain(con: duckdb.DuckDBPyConnection, attempt_id: int, now: datetime) -> None:
    con.execute(
        "UPDATE daily_opportunity_tool_attempts SET status = 'uncertain', completed_at = ? "
        "WHERE id = ? AND status = 'in_progress'", [now, attempt_id]
    )
