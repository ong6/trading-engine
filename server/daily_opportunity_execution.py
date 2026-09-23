"""Deterministic simulator-only consumption of P8 swing assessments."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb

from engine.lib.data_quality import quarantine_reason
from engine.lib.provenance import canonical_sha256
from sim.execution import DEFAULT_PROFILE_ID
from sim.strategies.base import Order

from . import daily_opportunity_store
from .daily_opportunity_store import PORTFOLIO_ID
from .json_utils import loads_object

INITIAL_CASH = 10_000.0
POSITION_FRACTION = 0.10
MAX_POSITIONS = 3
MIN_CONFIDENCE = 0.65
SUBMISSION_CUTOFF_UTC_HOUR = 12
EXIT_REASONS = ("maximum_hold_sessions", "close_below_signal_low")
BOOK_CONFIG = {
    "schema_version": 1, "policy_id": "daily-opportunity-v1",
    "strategy": "agent_only_policy", "cadence": "daily",
    "initial_cash": INITIAL_CASH, "position_fraction": POSITION_FRACTION,
    "max_positions": MAX_POSITIONS, "minimum_confidence": MIN_CONFIDENCE,
    "execution_profile": DEFAULT_PROFILE_ID, "simulator_only": True,
}


class ExecutionError(RuntimeError):
    """P8 paper execution state is absent or inconsistent."""


def initialize_book(con: duckdb.DuckDBPyConnection, start: date, *, active: bool) -> dict:
    encoded = json.dumps(BOOK_CONFIG, sort_keys=True, separators=(",", ":"))
    row = con.execute(
        "SELECT config, created, active, cash, initial_cash, execution_profile "
        "FROM portfolios WHERE id = ?", [PORTFOLIO_ID]
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO portfolios VALUES (?, 'Daily Opportunity Agent', 'agent_only_policy', "
            "?, ?, ?, ?, ?, ?)",
            [PORTFOLIO_ID, encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, ?, 0)",
            [PORTFOLIO_ID, start, INITIAL_CASH, INITIAL_CASH],
        )
        row = (encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID)
    expected = (encoded, start, active, INITIAL_CASH, INITIAL_CASH, DEFAULT_PROFILE_ID)
    if row != expected:
        raise ExecutionError("daily opportunity book differs from its frozen contract")
    return {"portfolio_id": PORTFOLIO_ID, "active": active, "book_sha256": canonical_sha256(BOOK_CONFIG)}


def activate_book(con: duckdb.DuckDBPyConnection, start: date) -> dict:
    """Activate only an exact empty P8 book at its registered start boundary."""
    initialize_book(con, start, active=False)
    counts = {}
    for table in ("sim_orders", "sim_fills", "sim_positions"):
        counts[table] = int(con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id = ?", [PORTFOLIO_ID]
        ).fetchone()[0])
    equity = con.execute(
        "SELECT date, equity, cash, n_positions FROM sim_equity WHERE portfolio_id = ?",
        [PORTFOLIO_ID],
    ).fetchall()
    if any(counts.values()) or equity != [(start, INITIAL_CASH, INITIAL_CASH, 0)]:
        raise ExecutionError("daily opportunity book is not empty at activation")
    con.execute("UPDATE portfolios SET active = TRUE WHERE id = ? AND active = FALSE", [PORTFOLIO_ID])
    return {"portfolio_id": PORTFOLIO_ID, "active": True,
            "activation_market_date": start.isoformat(), "execution_authority": "local_simulator_only"}


def _candidate(bundle: dict, ticker: str) -> dict:
    matches = [item for item in bundle["candidates"] if item["ticker"] == ticker]
    if len(matches) != 1:
        raise ExecutionError("assessment candidate is unavailable")
    return matches[0]


def _eligible_buy(con: duckdb.DuckDBPyConnection, candidate: dict, confidence: float, market_date: date) -> bool:
    earnings = candidate["earnings"].get("next_date")
    earnings_near = earnings is not None and 0 <= (date.fromisoformat(earnings) - market_date).days <= 5
    held = con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? AND qty > 0", [PORTFOLIO_ID]
    ).fetchone()[0]
    duplicate = con.execute(
        "SELECT 1 FROM sim_orders WHERE portfolio_id = ? AND ticker = ? AND status = 'pending'",
        [PORTFOLIO_ID, candidate["ticker"]],
    ).fetchone()
    return (confidence >= MIN_CONFIDENCE and candidate["passes_template"] is True
            and not earnings_near and held < MAX_POSITIONS and duplicate is None
            and quarantine_reason(con, candidate["ticker"]) is None)


def consume_assessment(
    con: duckdb.DuckDBPyConnection, assessment_id: int, *, now: datetime
) -> int | None:
    run = con.execute(
        "SELECT r.id, r.market_date, r.bundle_payload, r.status, a.ticker, a.action, "
        "a.confidence, a.assessment_sha256 FROM daily_opportunity_assessments a "
        "JOIN daily_opportunity_runs r ON r.id = a.run_id "
        "WHERE a.id = ? AND a.decision = 'swing'", [assessment_id],
    ).fetchone()
    if run is None or run[3] != "completed":
        raise ExecutionError("daily opportunity swing assessment is not complete")
    book = con.execute(
        "SELECT active, config, cash FROM portfolios WHERE id = ?", [PORTFOLIO_ID]
    ).fetchone()
    if book is None or book[0] is not True or loads_object(book[1]) != BOOK_CONFIG:
        return None
    run_id, market_date, bundle, _status, ticker, side, confidence, assessment_sha256 = (
        run[0], run[1], loads_object(run[2]), *run[3:]
    )
    observed = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    observed = observed.astimezone(timezone.utc)
    if observed.date() > market_date and observed.hour >= SUBMISSION_CUTOFF_UTC_HOUR:
        raise ExecutionError("paper intent missed the pre-open submission cutoff")
    prior = con.execute(
        "SELECT order_id FROM daily_opportunity_order_attribution WHERE assessment_id = ?",
        [assessment_id],
    ).fetchone()
    if prior is not None:
        return int(prior[0])
    candidate = _candidate(bundle, ticker)
    if side == "buy":
        if bundle["market"]["regime"] != "risk_on" or not _eligible_buy(
            con, candidate, float(confidence), market_date
        ):
            return None
        quantity = min(float(book[2]) * POSITION_FRACTION, INITIAL_CASH * POSITION_FRACTION) / candidate["close"]
    elif side == "sell":
        position = con.execute(
            "SELECT qty FROM sim_positions WHERE portfolio_id = ? AND ticker = ? AND qty > 0",
            [PORTFOLIO_ID, ticker],
        ).fetchone()
        if position is None:
            return None
        pending_exit = con.execute(
            "SELECT 1 FROM sim_orders WHERE portfolio_id=? AND ticker=? "
            "AND side='sell' AND status='pending'", [PORTFOLIO_ID, ticker],
        ).fetchone()
        if pending_exit is not None:
            return None
        quantity = float(position[0])
    else:
        return None
    order_id = int(con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0])
    con.execute(
        "INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
        [order_id, PORTFOLIO_ID, ticker, side, quantity, market_date],
    )
    attribution = {
        "order_id": order_id, "assessment_id": assessment_id, "run_id": run_id,
        "portfolio_id": PORTFOLIO_ID, "ticker": ticker, "side": side,
        "quantity": quantity, "signal_date": market_date.isoformat(),
        "assessment_sha256": assessment_sha256, "recorded_at": now.isoformat(),
    }
    con.execute(
        "INSERT INTO daily_opportunity_order_attribution VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [order_id, assessment_id, run_id, PORTFOLIO_ID, ticker, side, quantity, market_date,
         assessment_sha256, canonical_sha256(attribution), now],
    )
    if side == "buy":
        assessment = con.execute(
            "SELECT horizon_sessions FROM daily_opportunity_assessments WHERE id=?",
            [assessment_id],
        ).fetchone()
        signal_low = con.execute(
            "SELECT low FROM prices WHERE ticker=? AND date=? AND low>0",
            [ticker, market_date],
        ).fetchone()
        if assessment is None or signal_low is None:
            raise ExecutionError("deterministic exit inputs are unavailable")
        rule = {
            "entry_order_id": order_id, "assessment_id": assessment_id,
            "ticker": ticker, "max_hold_sessions": int(assessment[0]),
            "invalidation_kind": "close_below_signal_low",
            "invalidation_price": float(signal_low[0]),
            "signal_reference_price": float(candidate["close"]),
        }
        rule_sha256 = canonical_sha256(rule)
        existing_rule = con.execute(
            "SELECT entry_order_id,ticker,max_hold_sessions,invalidation_kind,"
            "invalidation_price,signal_reference_price FROM daily_opportunity_exit_rules "
            "WHERE assessment_id=?", [assessment_id],
        ).fetchone()
        expected_rule = (order_id, ticker, rule["max_hold_sessions"],
                         rule["invalidation_kind"], rule["invalidation_price"],
                         rule["signal_reference_price"])
        if existing_rule is not None and existing_rule != expected_rule:
            raise ExecutionError("deterministic exit rule differs from recovery")
        if existing_rule is None:
            con.execute(
                "INSERT INTO daily_opportunity_exit_rules VALUES (?,?,?,?,?,?,?,?,?)",
                [order_id, assessment_id, ticker, rule["max_hold_sessions"],
                 rule["invalidation_kind"], rule["invalidation_price"],
                 rule["signal_reference_price"], now, rule_sha256],
            )
    return order_id


def capture_execution_quality(con: duckdb.DuckDBPyConnection, *, captured_at: datetime) -> int:
    """Append execution latency/shortfall for newly filled attributed orders."""
    rows = con.execute(
        "SELECT a.order_id,a.assessment_id,a.ticker,a.side,a.recorded_at,r.completed_at,"
        "t.started_at,t.completed_at,a.signal_date,f.fill_date,f.open_px,f.fill_px,f.cost_bps,"
        "CAST(json_extract(r.bundle_payload, '$.candidates') AS VARCHAR),f.portfolio_id "
        "FROM daily_opportunity_order_attribution a "
        "JOIN daily_opportunity_runs r ON r.id=a.run_id "
        "LEFT JOIN daily_opportunity_tool_attempts t ON t.assessment_id=a.assessment_id "
        "JOIN sim_fills f ON f.order_id=a.order_id "
        "LEFT JOIN daily_opportunity_execution_quality q ON q.order_id=a.order_id "
        "WHERE q.order_id IS NULL ORDER BY a.order_id"
    ).fetchall()
    inserted = 0
    for (order_id, assessment_id, ticker, side, recorded_at, decision_at, tool_started,
         tool_completed, signal_date, fill_date, open_px, fill_px, cost_bps, raw_candidates,
         portfolio_id) in rows:
        candidates = json.loads(raw_candidates)
        arrival = next(float(item["close"]) for item in candidates if item["ticker"] == ticker)
        direction = 1.0 if side == "buy" else -1.0
        gap_bps = direction * (float(open_px) / arrival - 1.0) * 10_000
        total_bps = direction * (float(fill_px) / arrival - 1.0) * 10_000
        session_count = int(con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker=? AND date>? AND date<=?",
            [ticker, signal_date, fill_date],
        ).fetchone()[0])
        def elapsed(start, end):
            if start is None or end is None or end < start:
                return None
            return (end - start).total_seconds() * 1000
        position = con.execute(
            "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker=?",
            [portfolio_id, ticker],
        ).fetchone()
        cash = con.execute("SELECT cash FROM portfolios WHERE id=?", [portfolio_id]).fetchone()
        equity = con.execute(
            "SELECT date,equity FROM sim_equity WHERE portfolio_id=? AND date>=? "
            "ORDER BY date LIMIT 1", [portfolio_id, fill_date],
        ).fetchone()
        identity = {
            "order_id": int(order_id), "assessment_id": int(assessment_id), "side": side,
            "decision_at": None if decision_at is None else decision_at.isoformat(),
            "tool_started_at": None if tool_started is None else tool_started.isoformat(),
            "tool_completed_at": None if tool_completed is None else tool_completed.isoformat(),
            "order_recorded_at": recorded_at.isoformat(), "fill_date": fill_date.isoformat(),
            "fill_time_precision": "session_open_date",
            "decision_to_tool_ms": elapsed(decision_at, tool_started),
            "tool_latency_ms": elapsed(tool_started, tool_completed),
            "tool_to_order_ms": elapsed(tool_completed, recorded_at),
            "order_to_fill_sessions": session_count, "arrival_price": arrival,
            "open_price": float(open_px), "fill_price": float(fill_px),
            "gap_shortfall_bps": gap_bps, "total_shortfall_bps": total_bps,
            "cost_bps": float(cost_bps), "captured_at": captured_at.isoformat(),
            "post_fill_position_qty": 0.0 if position is None else float(position[0]),
            "post_fill_cash": float(cash[0]),
            "post_fill_equity": None if equity is None else float(equity[1]),
            "equity_as_of": None if equity is None else equity[0].isoformat(),
        }
        con.execute(
            "INSERT INTO daily_opportunity_execution_quality "
            "(order_id,assessment_id,side,decision_at,tool_started_at,tool_completed_at,"
            "order_recorded_at,fill_date,fill_time_precision,decision_to_tool_ms,"
            "tool_latency_ms,tool_to_order_ms,order_to_fill_sessions,arrival_price,open_price,"
            "fill_price,gap_shortfall_bps,total_shortfall_bps,cost_bps,captured_at,"
            "post_fill_position_qty,post_fill_cash,post_fill_equity,equity_as_of,quality_sha256) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [order_id, assessment_id, side, decision_at, tool_started, tool_completed, recorded_at,
             fill_date, "session_open_date", identity["decision_to_tool_ms"],
             identity["tool_latency_ms"], identity["tool_to_order_ms"], session_count, arrival,
             open_px, fill_px, gap_bps, total_bps, cost_bps, captured_at,
             identity["post_fill_position_qty"], identity["post_fill_cash"],
             identity["post_fill_equity"], equity[0] if equity else None,
             canonical_sha256(identity)],
        )
        inserted += 1
    exit_rows = con.execute(
        "SELECT e.exit_order_id,r.assessment_id,e.signal_date,e.observed_close,e.created_at,"
        "f.fill_date,f.open_px,f.fill_px,f.cost_bps,o.ticker,f.portfolio_id "
        "FROM daily_opportunity_exit_events e JOIN daily_opportunity_exit_rules r "
        "ON r.rule_sha256=e.rule_sha256 JOIN sim_orders o ON o.id=e.exit_order_id "
        "JOIN sim_fills f ON f.order_id=e.exit_order_id "
        "LEFT JOIN daily_opportunity_execution_quality q ON q.order_id=e.exit_order_id "
        "WHERE q.order_id IS NULL ORDER BY e.exit_order_id"
    ).fetchall()
    for (order_id, assessment_id, signal_date, arrival, decision_at, fill_date, open_px, fill_px,
         cost_bps, ticker, portfolio_id) in exit_rows:
        gap_bps = -(float(open_px) / float(arrival) - 1.0) * 10_000
        total_bps = -(float(fill_px) / float(arrival) - 1.0) * 10_000
        session_count = int(con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker=? AND date>? AND date<=?",
            [ticker, signal_date, fill_date],
        ).fetchone()[0])
        position = con.execute(
            "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker=?",
            [portfolio_id, ticker],
        ).fetchone()
        cash = con.execute("SELECT cash FROM portfolios WHERE id=?", [portfolio_id]).fetchone()
        equity = con.execute(
            "SELECT date,equity FROM sim_equity WHERE portfolio_id=? AND date>=? "
            "ORDER BY date LIMIT 1", [portfolio_id, fill_date],
        ).fetchone()
        identity = {
            "order_id": int(order_id), "assessment_id": int(assessment_id), "side": "sell",
            "decision_at": decision_at.isoformat(), "tool_started_at": None,
            "tool_completed_at": None, "order_recorded_at": decision_at.isoformat(),
            "fill_date": fill_date.isoformat(),
            "fill_time_precision": "session_open_date", "decision_to_tool_ms": None,
            "tool_latency_ms": None, "tool_to_order_ms": None,
            "order_to_fill_sessions": session_count, "arrival_price": float(arrival),
            "open_price": float(open_px), "fill_price": float(fill_px),
            "gap_shortfall_bps": gap_bps, "total_shortfall_bps": total_bps,
            "cost_bps": float(cost_bps), "captured_at": captured_at.isoformat(),
            "post_fill_position_qty": 0.0 if position is None else float(position[0]),
            "post_fill_cash": float(cash[0]),
            "post_fill_equity": None if equity is None else float(equity[1]),
            "equity_as_of": None if equity is None else equity[0].isoformat(),
        }
        con.execute(
            "INSERT INTO daily_opportunity_execution_quality "
            "(order_id,assessment_id,side,decision_at,tool_started_at,tool_completed_at,"
            "order_recorded_at,fill_date,fill_time_precision,decision_to_tool_ms,"
            "tool_latency_ms,tool_to_order_ms,order_to_fill_sessions,arrival_price,open_price,"
            "fill_price,gap_shortfall_bps,total_shortfall_bps,cost_bps,captured_at,"
            "post_fill_position_qty,post_fill_cash,post_fill_equity,equity_as_of,quality_sha256) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [order_id, assessment_id, "sell", decision_at, None, None, decision_at, fill_date,
             "session_open_date", None, None, None, session_count, arrival, open_px, fill_px,
             gap_bps, total_bps, cost_bps, captured_at, identity["post_fill_position_qty"],
             identity["post_fill_cash"], identity["post_fill_equity"],
             equity[0] if equity else None, canonical_sha256(identity)],
        )
        inserted += 1
    return inserted


def process_lifecycle(
    con: duckdb.DuckDBPyConnection, market_date: date, *, captured_at: datetime
) -> dict:
    """Capture fills and queue deterministic exit orders after a league step."""
    from sim import portfolio

    quality = capture_execution_quality(con, captured_at=captured_at)
    positions = portfolio.get_positions(con, PORTFOLIO_ID)
    exit_orders = 0
    for ticker, position in sorted(positions.items()):
        if float(position["qty"]) <= 0:
            continue
        row = con.execute(
            "SELECT r.rule_sha256,r.max_hold_sessions,r.invalidation_price,f.fill_date,p.close "
            "FROM daily_opportunity_exit_rules r JOIN sim_fills f "
            "ON f.order_id=r.entry_order_id JOIN prices p ON p.ticker=r.ticker AND p.date=? "
            "WHERE r.ticker=? AND f.side='buy' "
            "ORDER BY f.fill_date DESC LIMIT 1", [market_date, ticker],
        ).fetchone()
        if row is None:
            continue
        rule_sha, horizon, threshold, fill_date, close = row
        sessions = int(con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' "
            "AND date>=? AND date<=? AND volume>0", [fill_date, market_date],
        ).fetchone()[0])
        reason = EXIT_REASONS[1] if float(close) <= float(threshold) else (
            EXIT_REASONS[0] if sessions >= int(horizon) else None
        )
        if reason is None:
            continue
        pending = con.execute(
            "SELECT 1 FROM sim_orders WHERE portfolio_id=? AND ticker=? "
            "AND side='sell' AND status='pending'", [PORTFOLIO_ID, ticker],
        ).fetchone()
        if pending is not None:
            continue
        last_attempt = con.execute(
            "SELECT e.attempt,o.status FROM daily_opportunity_exit_events e "
            "LEFT JOIN sim_orders o ON o.id=e.exit_order_id WHERE e.rule_sha256=? "
            "ORDER BY e.attempt DESC LIMIT 1", [rule_sha],
        ).fetchone()
        if last_attempt is not None and last_attempt[1] in {"pending", "filled"}:
            continue
        attempt = 1 if last_attempt is None else int(last_attempt[0]) + 1
        order_id = int(con.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM sim_orders"
        ).fetchone()[0])
        order = Order(PORTFOLIO_ID, ticker, "sell", float(position["qty"]), market_date)
        con.execute(
            "INSERT INTO sim_orders VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
            [order_id, order.portfolio_id, order.ticker, order.side, order.qty, order.signal_date],
        )
        identity = {
            "rule_sha256": rule_sha, "signal_date": market_date.isoformat(),
            "reason": reason, "observed_close": float(close), "exit_order_id": order_id,
            "attempt": attempt, "created_at": captured_at.isoformat(),
        }
        con.execute(
            "INSERT INTO daily_opportunity_exit_events VALUES (?,?,?,?,?,?,?,?,?)",
            [daily_opportunity_store.next_id(con, "daily_opportunity_exit_events"), rule_sha,
             attempt, market_date, reason, close, order_id, captured_at, canonical_sha256(identity)],
        )
        exit_orders += 1
    return {"execution_quality_inserted": quality, "exit_orders_created": exit_orders}
