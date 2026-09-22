"""Bounded public status for the P8 daily opportunity pipeline."""
from __future__ import annotations

import duckdb

from engine.lib.util import table_exists

from .daily_opportunity_store import PORTFOLIO_ID
from .json_utils import loads_strict

ASSESSMENT_LIMIT = 20


def status(con: duckdb.DuckDBPyConnection) -> dict:
    required = ("daily_opportunity_runs", "daily_opportunity_assessments",
                "daily_opportunity_alerts", "daily_opportunity_alert_events")
    if any(not table_exists(con, table) for table in required):
        return {
            "status": "not_initialized", "latest_market_date": None,
            "latest_run_status": None, "news_status": None, "assessment_count": 0,
            "open_alert_count": 0, "triggered_alert_count": 0,
            "expired_alert_count": 0, "paper_order_count": 0,
            "book_active": False, "execution_authority": "local_simulator_only",
            "broker_route": "absent", "assessments": [],
        }
    run = con.execute(
        "SELECT id, market_date, status, news_status, reason, completed_at "
        "FROM daily_opportunity_runs ORDER BY market_date DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return {
            "status": "waiting", "latest_market_date": None, "latest_run_status": None,
            "news_status": None, "assessment_count": 0, "open_alert_count": 0,
            "triggered_alert_count": 0, "expired_alert_count": 0,
            "paper_order_count": 0, "book_active": False,
            "execution_authority": "local_simulator_only", "broker_route": "absent",
            "assessments": [],
        }
    run_id, market_date, run_status, news_status, reason, completed_at = run
    rows = con.execute(
        "SELECT ticker, decision, action, horizon_sessions, confidence, thesis, invalidation, "
        "evidence_ids, created_at FROM daily_opportunity_assessments WHERE run_id = ? "
        "ORDER BY id LIMIT ?", [run_id, ASSESSMENT_LIMIT]
    ).fetchall()
    counts = dict(con.execute(
        "SELECT e.event_type, COUNT(*) FROM daily_opportunity_alert_events e "
        "WHERE e.event_type IN ('triggered','expired') GROUP BY e.event_type"
    ).fetchall())
    open_count = int(con.execute(
        "SELECT COUNT(*) FROM daily_opportunity_alerts a WHERE NOT EXISTS ("
        "SELECT 1 FROM daily_opportunity_alert_events e WHERE e.alert_id = a.id "
        "AND e.event_type IN ('triggered','expired'))"
    ).fetchone()[0])
    book = con.execute("SELECT active FROM portfolios WHERE id = ?", [PORTFOLIO_ID]).fetchone()
    order_count = int(con.execute(
        "SELECT COUNT(*) FROM daily_opportunity_order_attribution"
    ).fetchone()[0]) if table_exists(con, "daily_opportunity_order_attribution") else 0
    return {
        "status": "ok" if run_status == "completed" else "issues",
        "latest_market_date": market_date, "latest_run_status": run_status,
        "latest_completed_at": completed_at, "reason": reason, "news_status": news_status,
        "assessment_count": len(rows), "open_alert_count": open_count,
        "triggered_alert_count": int(counts.get("triggered", 0)),
        "expired_alert_count": int(counts.get("expired", 0)),
        "paper_order_count": order_count, "book_active": bool(book and book[0]),
        "execution_authority": "local_simulator_only", "broker_route": "absent",
        "assessments": [
            {"ticker": row[0], "decision": row[1], "action": row[2],
             "horizon_sessions": row[3], "confidence": row[4], "thesis": row[5],
             "invalidation": row[6], "evidence_ids": loads_strict(row[7]),
             "created_at": row[8]} for row in rows
        ],
    }
