"""Bounded public status for the P8 daily opportunity pipeline."""
from __future__ import annotations

import duckdb

from engine.gap_volume_candidate import select
from engine.lib.util import table_exists

from . import agent_evaluation
from .daily_opportunity_store import PORTFOLIO_ID
from .json_utils import loads_object, loads_strict

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
        "SELECT id, market_date, status, news_status, reason, completed_at, "
        "model_response_id, model_response_payload "
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
    run_id, market_date, run_status, news_status, reason, completed_at, response_id, raw_response = run
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
    positions = int(con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? AND qty > 0", [PORTFOLIO_ID]
    ).fetchone()[0])
    pending = int(con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? AND status = 'pending'",
        [PORTFOLIO_ID],
    ).fetchone()[0])
    response = {} if raw_response is None else loads_object(raw_response)
    bundle = loads_object(con.execute(
        "SELECT bundle_payload FROM daily_opportunity_runs WHERE id = ?", [run_id]
    ).fetchone()[0])
    algorithm_candidate = select(bundle)
    veto_observation = None
    if algorithm_candidate is not None:
        matching = next(
            (item for item in rows if item[0] == algorithm_candidate["ticker"]), None
        )
        if matching is not None:
            veto_observation = {
                "ticker": matching[0],
                "algorithm_action": "buy",
                "agent_outcome": (
                    "allow" if matching[1] == "swing" and matching[2] == "buy" else "veto"
                ),
                "execution_authority": "none",
            }
    return {
        "status": "ok" if run_status == "completed" else "issues",
        "latest_market_date": market_date, "latest_run_status": run_status,
        "latest_completed_at": completed_at, "reason": reason, "news_status": news_status,
        "assessment_count": len(rows), "open_alert_count": open_count,
        "triggered_alert_count": int(counts.get("triggered", 0)),
        "expired_alert_count": int(counts.get("expired", 0)),
        "paper_order_count": order_count, "book_active": bool(book and book[0]),
        "position_count": positions, "pending_order_count": pending,
        "model": response.get("model"), "model_version": response.get("model_version"),
        "model_response_id": response_id, "usage": response.get("usage"),
        "algorithm_candidate": algorithm_candidate,
        "algorithm_agent_veto": veto_observation,
        "evaluation": agent_evaluation.status(con),
        "schedule": {
            "nightly": "Tue..Sat *-*-* 02:00:00 UTC",
            "hourly": "Mon..Fri *-*-* 09..16:15:00 America/New_York",
            "four_hour": ["09:30", "13:30 America/New_York"],
            "persistent_nightly": True,
        },
        "execution_authority": "local_simulator_only", "broker_route": "absent",
        "assessments": [
            {"ticker": row[0], "decision": row[1], "action": row[2],
             "horizon_sessions": row[3], "confidence": row[4], "thesis": row[5],
             "invalidation": row[6], "evidence_ids": loads_strict(row[7]),
             "created_at": row[8]} for row in rows
        ],
    }
