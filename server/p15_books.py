"""Isolated P15 comparator-book contracts and lifecycle."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import duckdb

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from sim import fills, p15_fills, portfolio
from sim.schema import init_sim_schema
from sim.strategies.base import atr_wilder

BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
INITIAL_CASH = 10_000.0
MECHANICS_VERSION = "p15-book-v1"
COMMON_CONFIG = {
    "mechanics_version": MECHANICS_VERSION,
    "initial_cash": INITIAL_CASH,
    "spy_sleeve": "whole_shares",
    "risk_fraction": 0.01,
    "atr_period": 14,
    "atr_multiple": 2.5,
    "max_name_fraction": 0.15,
    "max_positions": 8,
    "max_new_entries": 2,
    "time_exit_sessions": 10,
    "drawdown_halt": -0.20,
    "execution_profile": "baseline_v1",
    "entry_order_type": "limit_on_open",
    "cadence": "daily",
    "simulator_only": True,
}
SELECTION_POLICY = {
    "p15_ai_ranked": "ai_ranked",
    "p15_rule_control": "rule_ranked",
    "p15_hybrid_veto": "rule_ranked_ai_veto",
}


class P15BookError(ValueError):
    """P15 books or their isolated evidence violate the registered contract."""


def _config(portfolio_id: str) -> dict:
    return {**COMMON_CONFIG, "selection_policy": SELECTION_POLICY[portfolio_id]}


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    init_sim_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_contracts (
        portfolio_id VARCHAR PRIMARY KEY, mechanics_version VARCHAR NOT NULL,
        config_sha256 VARCHAR NOT NULL UNIQUE, initialized_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_state (
        portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL,
        entry_halted BOOLEAN NOT NULL, updated_at TIMESTAMP NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_order_intents (
        id BIGINT PRIMARY KEY, decision_id BIGINT, portfolio_id VARCHAR NOT NULL,
        ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE NOT NULL,
        signal_date DATE NOT NULL, order_role VARCHAR NOT NULL, priority INTEGER NOT NULL,
        signal_close DOUBLE NOT NULL, entry_atr DOUBLE, limit_px DOUBLE,
        status VARCHAR NOT NULL, reason VARCHAR, sim_order_id BIGINT UNIQUE,
        created_at TIMESTAMP NOT NULL,
        UNIQUE(decision_id,portfolio_id,order_role),
        UNIQUE(portfolio_id,ticker,side,signal_date,order_role))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_position_rules (
        portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        entry_intent_id BIGINT NOT NULL UNIQUE, entry_order_id BIGINT NOT NULL UNIQUE,
        entry_date DATE NOT NULL, entry_atr DOUBLE NOT NULL, stop_px DOUBLE NOT NULL,
        status VARCHAR NOT NULL, PRIMARY KEY(portfolio_id,ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_limit_attempts (
        intent_id BIGINT NOT NULL, attempt_date DATE NOT NULL, limit_px DOUBLE NOT NULL,
        open_px DOUBLE, counterfactual_fill_px DOUBLE, outcome VARCHAR NOT NULL,
        reject_reason VARCHAR, PRIMARY KEY(intent_id,attempt_date))"""
    )


def initialize_books(
    con: duckdb.DuckDBPyConnection,
    created: date,
    *,
    initialized_at: datetime | None = None,
) -> dict:
    """Create or verify the exact three inactive books without runtime rows."""
    init_schema(con)
    initialized = (initialized_at or datetime.now(timezone.utc)).replace(tzinfo=None)
    for portfolio_id in BOOK_IDS:
        config = _config(portfolio_id)
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
        digest = canonical_sha256(config)
        row = con.execute(
            "SELECT strategy,config,created,active,cash,initial_cash,execution_profile "
            "FROM portfolios WHERE id=?",
            [portfolio_id],
        ).fetchone()
        expected = (
            "agent_only_policy", encoded, created, False, INITIAL_CASH,
            INITIAL_CASH, "baseline_v1",
        )
        if row is None:
            con.execute(
                "INSERT INTO portfolios "
                "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
                "VALUES (?,?,?,?,?,FALSE,?,?,?)",
                [portfolio_id, portfolio_id, "agent_only_policy", encoded, created,
                 INITIAL_CASH, INITIAL_CASH, "baseline_v1"],
            )
            con.execute(
                "INSERT INTO p15_book_contracts VALUES (?,?,?,?)",
                [portfolio_id, MECHANICS_VERSION, digest, initialized],
            )
        elif row != expected:
            raise P15BookError(f"P15 book {portfolio_id} differs from its contract")
        contract = con.execute(
            "SELECT mechanics_version,config_sha256 FROM p15_book_contracts "
            "WHERE portfolio_id=?",
            [portfolio_id],
        ).fetchone()
        if contract != (MECHANICS_VERSION, digest):
            raise P15BookError(f"P15 book {portfolio_id} contract is missing or invalid")
    runtime_counts = {
        table: int(con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN (?,?,?)", list(BOOK_IDS)
        ).fetchone()[0])
        for table in ("sim_orders", "sim_fills", "sim_positions", "sim_equity")
    }
    states = con.execute(
        "SELECT id,active FROM portfolios WHERE id IN (?,?,?) ORDER BY id", list(BOOK_IDS)
    ).fetchall()
    return {"status": "ready", "book_count": len(states), "active_count": sum(row[1] for row in states),
            "runtime_counts": runtime_counts}


def activation_state(con: duckdb.DuckDBPyConnection) -> str:
    rows = con.execute(
        "SELECT id,active FROM portfolios WHERE id IN (?,?,?) ORDER BY id", list(BOOK_IDS)
    ).fetchall()
    if len(rows) != len(BOOK_IDS):
        return "absent"
    active = sum(bool(row[1]) for row in rows)
    if active == 0:
        return "inactive"
    if active == len(BOOK_IDS):
        return "active"
    raise P15BookError("P15 books have mixed activation state")


def activate_books(con: duckdb.DuckDBPyConnection, checkpoint: date) -> dict:
    """Atomically activate exact empty books at an already-completed checkpoint."""
    with db.transaction(con):
        return _activate_books(con, checkpoint)


def _activate_books(con: duckdb.DuckDBPyConnection, checkpoint: date) -> dict:
    if activation_state(con) != "inactive":
        raise P15BookError("P15 books are not jointly inactive")
    for table in ("sim_orders", "sim_fills", "sim_positions", "sim_equity"):
        if con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN (?,?,?)", list(BOOK_IDS)
        ).fetchone()[0]:
            raise P15BookError("P15 books already contain runtime state")
    latest = con.execute(
        "SELECT MAX(date) FROM sim_equity WHERE portfolio_id NOT IN (?,?,?)", list(BOOK_IDS)
    ).fetchone()[0]
    if latest is None or checkpoint != latest:
        raise P15BookError("P15 activation checkpoint is not the completed league date")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for portfolio_id in BOOK_IDS:
        con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [portfolio_id])
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,?,?)",
            [portfolio_id, checkpoint, INITIAL_CASH, INITIAL_CASH, 0],
        )
        con.execute(
            "INSERT INTO p15_book_state VALUES (?,?,FALSE,?)",
            [portfolio_id, INITIAL_CASH, now],
        )
    return {"status": "active", "book_count": len(BOOK_IDS),
            "checkpoint": checkpoint.isoformat()}


def _next_intent_id(con: duckdb.DuckDBPyConnection) -> int:
    return int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM p15_order_intents"
    ).fetchone()[0])


def _add_intent(
    con: duckdb.DuckDBPyConnection, *, decision_id: int | None,
    portfolio_id: str, ticker: str, side: str, qty: float, signal_date: date,
    role: str, priority: int, signal_close: float, entry_atr: float | None,
    limit_px: float | None, created_at: datetime,
) -> bool:
    duplicate = con.execute(
        "SELECT 1 FROM p15_order_intents WHERE portfolio_id=? AND ticker=? AND side=? "
        "AND signal_date=? AND order_role=?",
        [portfolio_id, ticker, side, signal_date, role],
    ).fetchone()
    if duplicate is not None:
        return False
    con.execute(
        "INSERT INTO p15_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [_next_intent_id(con), decision_id, portfolio_id, ticker, side, qty,
         signal_date, role, priority, signal_close, entry_atr, limit_px,
         "pending", None, None, created_at],
    )
    return True


def _scored_decisions(con: duckdb.DuckDBPyConnection, market_date: date) -> list[dict]:
    rows = con.execute(
        "SELECT d.id,d.ticker,d.decision_payload FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE t.policy_id='p15-scoring-v1' AND t.market_date=? "
        "AND t.terminal_status='completed' ORDER BY d.ticker",
        [market_date],
    ).fetchall()
    decisions = []
    for decision_id, ticker, raw in rows:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("ticker") != ticker:
            raise P15BookError("P15 decision payload is invalid")
        decisions.append({**payload, "decision_id": int(decision_id)})
    return decisions


def _ranked(book_id: str, decisions: list[dict]) -> list[dict]:
    eligible = [item for item in decisions if item.get("tradeable") is True
                and item.get("stratum") in {"mover", "trend"}]
    if book_id == "p15_ai_ranked":
        eligible = [item for item in eligible
                    if item.get("scoring_status") == "available"
                    and item.get("action") == "buy_candidate"
                    and float(item.get("p_outperform_5", -math.inf)) >= 0.55
                    and float(item.get("expected_excess_bp_5", -math.inf)) >= 50]
        return sorted(eligible, key=lambda item: (
            -float(item["expected_excess_bp_5"]),
            int(item.get("baseline_rank") or 2**31), item["ticker"],
        ))
    if book_id == "p15_hybrid_veto":
        eligible = [item for item in eligible if not (
            item.get("scoring_status") == "available"
            and float(item.get("expected_excess_bp_5", 0)) < 0
        )]
    return sorted(eligible, key=lambda item: (
        int(item.get("baseline_rank") or 2**31), item["ticker"],
    ))


def _equity_and_halt(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, market_date: date,
    updated_at: datetime,
) -> tuple[float, bool]:
    row = con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id=? AND date=?",
        [portfolio_id, market_date],
    ).fetchone()
    if row is None or not math.isfinite(float(row[0])) or row[0] <= 0:
        raise P15BookError("P15 book equity is unavailable")
    equity = float(row[0])
    state = con.execute(
        "SELECT peak_equity,entry_halted FROM p15_book_state WHERE portfolio_id=?",
        [portfolio_id],
    ).fetchone()
    if state is None:
        raise P15BookError("P15 book state is unavailable")
    peak = max(float(state[0]), equity)
    halted = bool(state[1]) or equity / peak - 1 <= COMMON_CONFIG["drawdown_halt"]
    con.execute(
        "UPDATE p15_book_state SET peak_equity=?,entry_halted=?,updated_at=? "
        "WHERE portfolio_id=?", [peak, halted, updated_at, portfolio_id],
    )
    return equity, halted


def queue_orders(
    con: duckdb.DuckDBPyConnection, market_date: date, *, created_at: datetime
) -> dict:
    """Turn one retained score window into book-local intents, never generic pending orders."""
    init_schema(con)
    if activation_state(con) != "active":
        return {"status": "inactive", "created": 0}
    decisions = _scored_decisions(con, market_date)
    if not decisions:
        raise P15BookError("completed P15 scoring decisions are unavailable")
    by_ticker = {item["ticker"]: item for item in decisions}
    created = 0
    for book_id in BOOK_IDS:
        equity, halted = _equity_and_halt(con, book_id, market_date, created_at)
        positions = portfolio.get_positions(con, book_id)
        stock_positions = {ticker: value for ticker, value in positions.items()
                           if ticker != "SPY" and value["qty"] > 0}
        exiting = set()
        for ticker, position in sorted(stock_positions.items()):
            rule = con.execute(
                "SELECT entry_date,stop_px FROM p15_position_rules "
                "WHERE portfolio_id=? AND ticker=? AND status='open'",
                [book_id, ticker],
            ).fetchone()
            if rule is None:
                raise P15BookError("P15 open position has no deterministic rule")
            close = con.execute(
                "SELECT close FROM prices WHERE ticker=? AND date=?", [ticker, market_date]
            ).fetchone()
            if close is None or close[0] is None:
                continue
            sessions = int(con.execute(
                "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' "
                "AND date>=? AND date<=? AND volume>0", [rule[0], market_date],
            ).fetchone()[0])
            decision = by_ticker.get(ticker)
            ai_exit = book_id == "p15_ai_ranked" and decision is not None and (
                decision.get("action") == "exit" or (
                    decision.get("scoring_status") == "available"
                    and float(decision.get("expected_excess_bp_5", 0)) < 0
                )
            )
            reason = ("stop" if close is not None and float(close[0]) <= float(rule[1])
                      else "time_exit" if sessions >= COMMON_CONFIG["time_exit_sessions"]
                      else "ai_exit" if ai_exit else None)
            if reason and _add_intent(
                con, decision_id=None if decision is None else decision["decision_id"],
                portfolio_id=book_id, ticker=ticker, side="sell",
                qty=float(position["qty"]), signal_date=market_date, role=reason,
                priority=0, signal_close=float(close[0]), entry_atr=None,
                limit_px=None, created_at=created_at,
            ):
                created += 1
                exiting.add(ticker)
        if halted:
            continue
        pending = {row[0] for row in con.execute(
            "SELECT ticker FROM p15_order_intents WHERE portfolio_id=? AND side='buy' "
            "AND status='pending' AND ticker!='SPY'", [book_id],
        ).fetchall()}
        queued_today = int(con.execute(
            "SELECT COUNT(*) FROM p15_order_intents WHERE portfolio_id=? "
            "AND signal_date=? AND order_role='entry'",
            [book_id, market_date],
        ).fetchone()[0])
        slots = (COMMON_CONFIG["max_positions"] - len(set(stock_positions) - exiting)
                 - len(pending))
        selected = [item for item in _ranked(book_id, decisions)
                    if item["ticker"] not in stock_positions and item["ticker"] not in pending]
        daily_room = COMMON_CONFIG["max_new_entries"] - queued_today
        selected = selected[:max(0, min(daily_room, slots))]
        desired = 0.0
        for priority, item in enumerate(selected, start=1):
            close = float(item["close"])
            atr = atr_wilder(con, item["ticker"], market_date, COMMON_CONFIG["atr_period"])
            if atr is None or atr <= 0 or close <= 0:
                continue
            qty = min(
                COMMON_CONFIG["risk_fraction"] * equity / (COMMON_CONFIG["atr_multiple"] * atr),
                COMMON_CONFIG["max_name_fraction"] * equity / close,
            )
            limit_px = close * (1 + max(0.015, 0.5 * atr / close))
            if qty > 0 and _add_intent(
                con, decision_id=item["decision_id"], portfolio_id=book_id,
                ticker=item["ticker"], side="buy", qty=qty, signal_date=market_date,
                role="entry", priority=priority, signal_close=close,
                entry_atr=atr, limit_px=limit_px, created_at=created_at,
            ):
                created += 1
                desired += qty * limit_px
        cash = portfolio.get_cash(con, book_id)
        spy = positions.get("SPY", {}).get("qty", 0.0)
        spy_close = con.execute(
            "SELECT close FROM prices WHERE ticker='SPY' AND date=?", [market_date]
        ).fetchone()
        if spy_close is None or spy_close[0] is None or spy_close[0] <= 0:
            raise P15BookError("SPY sleeve price is unavailable")
        if desired > cash and spy > 0:
            qty = min(float(spy), math.ceil((desired - cash) / float(spy_close[0])))
            created += _add_intent(
                con, decision_id=None, portfolio_id=book_id, ticker="SPY", side="sell",
                qty=qty, signal_date=market_date, role="spy_fund", priority=-1,
                signal_close=float(spy_close[0]), entry_atr=None, limit_px=None,
                created_at=created_at,
            )
        elif cash > desired:
            qty = math.floor((cash - desired) / float(spy_close[0]))
            if qty > 0:
                created += _add_intent(
                    con, decision_id=None, portfolio_id=book_id, ticker="SPY", side="buy",
                    qty=float(qty), signal_date=market_date, role="spy_reinvest", priority=99,
                    signal_close=float(spy_close[0]), entry_atr=None, limit_px=None,
                    created_at=created_at,
                )
    return {"status": "queued", "created": created}


def _next_order_id(con: duckdb.DuckDBPyConnection) -> int:
    return int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM sim_orders").fetchone()[0])


def _terminal_order(
    con: duckdb.DuckDBPyConnection, intent: tuple, fill_date: date, result,
) -> str:
    (intent_id, portfolio_id, ticker, side, qty, signal_date, role,
     _priority, _signal_close, entry_atr, _limit_px) = intent
    order_id = _next_order_id(con)
    status, reason = result.status, result.reject_reason
    applied = 0.0
    if status == "filled":
        if side == "buy" and ticker != "SPY" and qty * result.fill_px > portfolio.get_cash(
            con, portfolio_id
        ):
            status, reason = "rejected", "insufficient_cash"
        else:
            if side == "buy" and ticker == "SPY":
                qty = float(math.floor(portfolio.get_cash(con, portfolio_id) / result.fill_px))
                if qty > 0:
                    result = fills.attempt_fill(
                        con, ticker, side, qty, signal_date, fill_date, "baseline_v1"
                    )
                if qty <= 0 or result.status != "filled":
                    status, reason = "rejected", "insufficient_cash"
            if status == "filled":
                applied = portfolio.apply_fill(con, {
                    "portfolio_id": portfolio_id, "ticker": ticker,
                    "side": side, "qty": qty, "fill_px": result.fill_px,
                })
                if applied <= 0:
                    status, reason = "rejected", (
                        "insufficient_cash" if side == "buy" else "no_position_to_sell"
                    )
    con.execute(
        "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,?,?)",
        [order_id, portfolio_id, ticker, side, qty, signal_date, status, reason],
    )
    raw_notional = None if result.open_px is None else qty * float(result.open_px)
    con.execute(
        "INSERT INTO sim_execution_attempts "
        "(order_id,attempt_date,execution_profile,raw_notional,median_dollar_vol,"
        "participation,outcome,reject_reason) VALUES (?,?,?,?,?,?,?,?)",
        [order_id, fill_date, result.execution_profile or "baseline_v1", raw_notional,
         result.median_dollar_vol, result.participation, status, reason],
    )
    if status == "filled":
        con.execute(
            "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
            [order_id, portfolio_id, ticker, side, applied, fill_date, result.open_px,
             result.fill_px, result.slippage_bps, result.cost_bps],
        )
        con.execute(
            "INSERT INTO sim_fill_costs VALUES (?,?,?,?,?,?,?)",
            [order_id, result.execution_profile, result.participation,
             result.slippage_bps, result.impact_bps, result.fee_bps, result.cost_bps],
        )
        if role == "entry":
            stop = float(result.fill_px) - COMMON_CONFIG["atr_multiple"] * float(entry_atr)
            existing = con.execute(
                "SELECT status FROM p15_position_rules WHERE portfolio_id=? AND ticker=?",
                [portfolio_id, ticker],
            ).fetchone()
            if existing is not None and existing[0] != "closed":
                raise P15BookError("P15 entry would replace an open position rule")
            con.execute(
                "DELETE FROM p15_position_rules WHERE portfolio_id=? AND ticker=?",
                [portfolio_id, ticker],
            )
            con.execute(
                "INSERT INTO p15_position_rules VALUES (?,?,?,?,?,?,?,?)",
                [portfolio_id, ticker, intent_id, order_id, fill_date,
                 entry_atr, stop, "open"],
            )
        elif side == "sell" and ticker != "SPY":
            con.execute(
                "UPDATE p15_position_rules SET status='closed' "
                "WHERE portfolio_id=? AND ticker=?", [portfolio_id, ticker],
            )
    con.execute(
        "UPDATE p15_order_intents SET status=?,reason=?,sim_order_id=? WHERE id=?",
        [status, reason, order_id, intent_id],
    )
    return status


def process_pending(con: duckdb.DuckDBPyConnection, fill_date: date) -> dict:
    """Execute only P15-owned intents; generic league orders are never selected."""
    init_schema(con)
    if activation_state(con) != "active":
        return {"filled": 0, "rejected": 0, "pending": 0}
    rows = con.execute(
        "SELECT id,portfolio_id,ticker,side,qty,signal_date,order_role,priority,"
        "signal_close,entry_atr,limit_px FROM p15_order_intents "
        "WHERE status='pending' AND signal_date<? AND portfolio_id IN (?,?,?) "
        "ORDER BY signal_date,"
        "CASE WHEN side='sell' THEN 0 WHEN order_role='entry' THEN 1 ELSE 2 END,priority,id",
        [fill_date, *BOOK_IDS],
    ).fetchall()
    counts = {"filled": 0, "rejected": 0, "pending": 0}
    for intent in rows:
        (intent_id, _book_id, ticker, side, qty, signal_date, role,
         _priority, _signal_close, _entry_atr, limit_px) = intent
        result = (
            p15_fills.attempt_limit_on_open(
                con, ticker, side, qty, signal_date, fill_date, limit_px, "baseline_v1"
            )
            if role == "entry" else
            fills.attempt_fill(
                con, ticker, side, qty, signal_date, fill_date, "baseline_v1"
            )
        )
        if role == "entry":
            outcome = (result.reject_reason if result.reject_reason == "limit_not_reached"
                       else result.status)
            con.execute(
                "INSERT OR REPLACE INTO p15_limit_attempts VALUES (?,?,?,?,?,?,?)",
                [intent_id, fill_date, limit_px, result.open_px,
                 result.counterfactual_fill_px, outcome, result.reject_reason],
            )
        if result.status == "pending":
            counts["pending"] += 1
            continue
        counts[_terminal_order(con, intent, fill_date, result)] += 1
    return counts


def run_window(
    con: duckdb.DuckDBPyConnection, market_date: date, *, observed_at: datetime,
) -> dict:
    """Process, mark, and queue one completed market session for active P15 books."""
    init_schema(con)
    if activation_state(con) != "active":
        return {"status": "inactive", "filled": 0, "rejected": 0,
                "pending": 0, "queued": 0}
    with db.transaction(con):
        processed = process_pending(con, market_date)
        marks = {}
        for book_id in BOOK_IDS:
            marks[book_id] = portfolio.mark_to_market(con, book_id, market_date)
        queued = queue_orders(con, market_date, created_at=observed_at)
    return {"status": "completed", **processed, "queued": queued["created"],
            "marks": marks}
