"""Append-only P8 daily opportunity, assessment, and alert storage."""
from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from engine.lib.provenance import canonical_sha256


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
        expires_sessions INTEGER NOT NULL, status VARCHAR NOT NULL, triggered_on DATE,
        terminal_reason VARCHAR, alert_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS daily_opportunity_news_responses (
        run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL,
        requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL,
        content_type VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL,
        receipt_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(run_id, ticker))"""
    )


def next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    allowed = {
        "daily_opportunity_runs",
        "daily_opportunity_assessments",
        "daily_opportunity_alerts",
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
            identity = {
                "assessment_sha256": digest, "ticker": assessment["ticker"],
                "direction": alert["direction"], "trigger_price": alert["price"],
                "created_market_date": assessment["market_date"],
                "expires_sessions": alert["expires_sessions"],
            }
            con.execute(
                "INSERT INTO daily_opportunity_alerts VALUES (?, ?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?)",
                [alert_id, assessment_id, assessment["ticker"], alert["direction"],
                 alert["price"], date.fromisoformat(assessment["market_date"]),
                 alert["expires_sessions"], canonical_sha256(identity)],
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
