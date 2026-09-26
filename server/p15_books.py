"""Isolated P15 comparator-book contracts and lifecycle."""
from __future__ import annotations

import json
import math
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db
from engine.lib.data_quality import quarantine_reason
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import REPO_ROOT
from engine.lib.util import table_exists
from sim import fills, p15_fills, portfolio
from sim.schema import init_sim_schema

BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
INITIAL_CASH = 10_000.0
MECHANICS_VERSION = "p15-book-v1"
SIM_FILLED_STATUS = "p15_filled"
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
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_windows (
        portfolio_id VARCHAR NOT NULL, market_date DATE NOT NULL,
        equity DOUBLE NOT NULL, cash DOUBLE NOT NULL, n_positions INTEGER NOT NULL,
        carried VARCHAR NOT NULL, completed_at TIMESTAMP NOT NULL,
        PRIMARY KEY(portfolio_id,market_date))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_book_fills (
        intent_id BIGINT PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE,
        portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL,
        qty DOUBLE NOT NULL, fill_date DATE NOT NULL, open_px DOUBLE NOT NULL,
        fill_px DOUBLE NOT NULL, slippage_bps DOUBLE NOT NULL, cost_bps DOUBLE NOT NULL,
        execution_profile VARCHAR NOT NULL, median_dollar_vol DOUBLE, participation DOUBLE,
        impact_bps DOUBLE NOT NULL, fee_bps DOUBLE NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_limit_labels (
        intent_id BIGINT PRIMARY KEY, attempt_date DATE NOT NULL,
        horizon_sessions INTEGER NOT NULL, entry_px DOUBLE NOT NULL,
        exit_date DATE NOT NULL, exit_close DOUBLE NOT NULL,
        net_return DOUBLE NOT NULL, spy_net_return DOUBLE NOT NULL,
        net_excess_return DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL,
        labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE)"""
    )


def initialize_books(
    con: duckdb.DuckDBPyConnection,
    created: date,
    *,
    initialized_at: datetime | None = None,
) -> dict:
    """Create or verify the exact three inactive books without runtime rows."""
    init_schema(con)
    with db.transaction(con):
        return _initialize_books(con, created, initialized_at=initialized_at)


def _initialize_books(
    con: duckdb.DuckDBPyConnection,
    created: date,
    *,
    initialized_at: datetime | None = None,
) -> dict:
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
    for portfolio_id in BOOK_IDS:
        config = _config(portfolio_id)
        row = con.execute(
            "SELECT name,strategy,config,cash,initial_cash,execution_profile "
            "FROM portfolios WHERE id=?",
            [portfolio_id],
        ).fetchone()
        contract = con.execute(
            "SELECT mechanics_version,config_sha256 FROM p15_book_contracts "
            "WHERE portfolio_id=?", [portfolio_id],
        ).fetchone()
        expected_config = json.dumps(config, sort_keys=True, separators=(",", ":"))
        if row != (portfolio_id, "agent_only_policy", expected_config,
                   INITIAL_CASH, INITIAL_CASH, "baseline_v1") or contract != (
            MECHANICS_VERSION, canonical_sha256(config)
        ):
            raise P15BookError("P15 book contract is invalid at activation")
    for table in ("sim_orders", "sim_fills", "sim_positions", "sim_equity"):
        if con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN (?,?,?)", list(BOOK_IDS)
        ).fetchone()[0]:
            raise P15BookError("P15 books already contain runtime state")
    if con.execute("SELECT COUNT(*) FROM p15_order_intents").fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM p15_position_rules"
    ).fetchone()[0] or con.execute("SELECT COUNT(*) FROM p15_limit_attempts").fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM p15_book_state"
    ).fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM p15_book_windows"
    ).fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM p15_book_fills"
    ).fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM p15_limit_labels"
    ).fetchone()[0]:
        raise P15BookError("P15 books already contain owned runtime state")
    checkpoints = con.execute(
        "SELECT p.id,MAX(e.date) FROM portfolios p LEFT JOIN sim_equity e "
        "ON e.portfolio_id=p.id WHERE p.active AND p.id NOT IN (?,?,?) "
        "GROUP BY p.id ORDER BY p.id", list(BOOK_IDS),
    ).fetchall()
    if not checkpoints or any(row[1] is None for row in checkpoints) or {
        row[1] for row in checkpoints
    } != {checkpoint}:
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
        "SELECT decision_id,qty,priority,signal_close,entry_atr,limit_px "
        "FROM p15_order_intents WHERE portfolio_id=? AND ticker=? AND side=? "
        "AND signal_date=? AND order_role=?",
        [portfolio_id, ticker, side, signal_date, role],
    ).fetchone()
    if duplicate is not None:
        if duplicate != (decision_id, qty, priority, signal_close, entry_atr, limit_px):
            raise P15BookError("P15 intent replay differs from retained evidence")
        return False
    con.execute(
        "INSERT INTO p15_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [_next_intent_id(con), decision_id, portfolio_id, ticker, side, qty,
         signal_date, role, priority, signal_close, entry_atr, limit_px,
         "pending", None, None, created_at],
    )
    return True


def _scored_decisions(con: duckdb.DuckDBPyConnection, market_date: date) -> list[dict]:
    if not table_exists(con, "agent_evaluation_traces") or not table_exists(
        con, "agent_evaluation_decisions"
    ):
        return []
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
                    and item.get("decision") == "buy_candidate"
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
    if (peak, halted) != (float(state[0]), bool(state[1])):
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
            adjusted_stop = float(rule[1]) / _split_factor(
                con, ticker, rule[0], market_date
            )
            sessions = int(con.execute(
                "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' "
                "AND date>=? AND date<=? AND volume>0", [rule[0], market_date],
            ).fetchone()[0])
            decision = by_ticker.get(ticker)
            ai_exit = book_id == "p15_ai_ranked" and decision is not None and (
                decision.get("decision") == "exit" or (
                    decision.get("scoring_status") == "available"
                    and float(decision.get("expected_excess_bp_5", 0)) < 0
                )
            )
            reason = ("stop" if float(close[0]) <= adjusted_stop
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
        selected = [] if halted else [item for item in _ranked(book_id, decisions)
                                      if item["ticker"] not in stock_positions
                                      and item["ticker"] not in pending]
        daily_room = COMMON_CONFIG["max_new_entries"] - queued_today
        selected = selected[:max(0, min(daily_room, slots))]
        desired = float(con.execute(
            "SELECT COALESCE(SUM(qty*limit_px),0) FROM p15_order_intents "
            "WHERE portfolio_id=? AND signal_date=? AND order_role='entry' "
            "AND status='pending'", [book_id, market_date],
        ).fetchone()[0])
        for priority, item in enumerate(selected, start=1):
            close = float(item["close"])
            atr = item.get("atr_14")
            if atr is None or atr <= 0 or close <= 0:
                continue
            atr = float(atr)
            limit_px = close * (1 + max(0.015, 0.5 * atr / close))
            qty = min(
                COMMON_CONFIG["risk_fraction"] * equity / (COMMON_CONFIG["atr_multiple"] * atr),
                COMMON_CONFIG["max_name_fraction"] * equity / limit_px,
            )
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


def _split_factor(
    con: duckdb.DuckDBPyConnection, ticker: str, after: date, through: date,
) -> float:
    if not table_exists(con, "split_adjustments"):
        return 1.0
    rows = con.execute(
        "SELECT ratio FROM split_adjustments WHERE ticker=? AND outcome='applied' "
        "AND ex_date>? AND ex_date<=? ORDER BY ex_date", [ticker, after, through],
    ).fetchall()
    return math.prod(float(row[0]) for row in rows)


def _terminal_order(
    con: duckdb.DuckDBPyConnection, intent: tuple, fill_date: date, result,
) -> str:
    (intent_id, portfolio_id, ticker, side, qty, signal_date, role,
     _priority, _signal_close, entry_atr, _limit_px) = intent
    order_id = _next_order_id(con)
    status, reason = result.status, result.reject_reason
    applied = 0.0
    if status == "filled":
        if side == "buy" and ticker != "SPY":
            stock_count = int(con.execute(
                "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id=? "
                "AND ticker!='SPY' AND qty>0", [portfolio_id],
            ).fetchone()[0])
            filled_today = int(con.execute(
                "SELECT COUNT(*) FROM p15_order_intents i JOIN sim_fills f "
                "ON f.order_id=i.sim_order_id WHERE i.portfolio_id=? "
                "AND i.order_role='entry' AND f.fill_date=?", [portfolio_id, fill_date],
            ).fetchone()[0])
            if stock_count >= COMMON_CONFIG["max_positions"]:
                status, reason = "rejected", "position_cap"
            elif filled_today >= COMMON_CONFIG["max_new_entries"]:
                status, reason = "rejected", "daily_entry_cap"
            elif quarantine_reason(con, ticker) is not None:
                status, reason = "rejected", "data_quarantine"
            elif qty * result.fill_px > portfolio.get_cash(con, portfolio_id):
                status, reason = "rejected", "insufficient_cash"
            elif qty * result.fill_px > COMMON_CONFIG["max_name_fraction"] * _signal_equity(
                con, portfolio_id, signal_date
            ) + 1e-9:
                status, reason = "rejected", "name_cap"
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
        [order_id, portfolio_id, ticker, side, qty, signal_date,
         SIM_FILLED_STATUS if status == "filled" else status, reason],
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
        con.execute(
            "INSERT INTO p15_book_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [intent_id, order_id, portfolio_id, ticker, side, applied, fill_date,
             result.open_px, result.fill_px, result.slippage_bps, result.cost_bps,
             result.execution_profile, result.median_dollar_vol, result.participation, result.impact_bps,
             result.fee_bps],
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
    for stored_intent in rows:
        intent = list(stored_intent)
        (intent_id, _book_id, ticker, side, qty, signal_date, role,
         _priority, _signal_close, _entry_atr, limit_px) = intent
        factor = _split_factor(con, ticker, signal_date, fill_date)
        intent[4] = qty = float(qty) * factor
        intent[8] = float(intent[8]) / factor
        if intent[9] is not None:
            intent[9] = float(intent[9]) / factor
        if limit_px is not None:
            intent[10] = limit_px = float(limit_px) / factor
        halted = role == "entry" and bool(con.execute(
            "SELECT entry_halted FROM p15_book_state WHERE portfolio_id=?", [intent[1]]
        ).fetchone()[0])
        result = p15_fills.LimitFillResult(
            status="rejected", reject_reason="drawdown_halt"
        ) if halted else (
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
            expected = (limit_px, result.open_px, result.counterfactual_fill_px,
                        outcome, result.reject_reason)
            prior = con.execute(
                "SELECT limit_px,open_px,counterfactual_fill_px,outcome,reject_reason "
                "FROM p15_limit_attempts WHERE intent_id=? AND attempt_date=?",
                [intent_id, fill_date],
            ).fetchone()
            if prior is not None and prior != expected:
                raise P15BookError("P15 limit-attempt replay differs from retained evidence")
            if prior is None:
                con.execute(
                    "INSERT INTO p15_limit_attempts VALUES (?,?,?,?,?,?,?)",
                    [intent_id, fill_date, *expected],
                )
        if result.status == "pending":
            counts["pending"] += 1
            continue
        counts[_terminal_order(con, tuple(intent), fill_date, result)] += 1
    return counts


def _signal_equity(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, signal_date: date,
) -> float:
    row = con.execute(
        "SELECT equity FROM p15_book_windows WHERE portfolio_id=? AND market_date=? "
        "UNION ALL SELECT equity FROM sim_equity WHERE portfolio_id=? AND date=? "
        "AND NOT EXISTS (SELECT 1 FROM p15_book_windows WHERE portfolio_id=? "
        "AND market_date=?) LIMIT 1",
        [portfolio_id, signal_date, portfolio_id, signal_date, portfolio_id, signal_date],
    ).fetchone()
    if row is None or row[0] is None:
        raise P15BookError("P15 book equity is unavailable")
    return float(row[0])


def _restore_rerun_evidence(con: duckdb.DuckDBPyConnection) -> int:
    rows = con.execute(
        "SELECT r.*,i.signal_date FROM p15_book_fills r "
        "JOIN p15_order_intents i ON i.id=r.intent_id ORDER BY r.order_id"
    ).fetchall()
    restored = 0
    for row in rows:
        (_intent_id, order_id, book_id, ticker, side, qty, fill_date, open_px,
         fill_px, slippage, cost, profile, median_dollar_vol, participation,
         impact, fee, signal_date) = row
        expected_order = (book_id, ticker, side, qty, signal_date, SIM_FILLED_STATUS, None)
        order = con.execute(
            "SELECT portfolio_id,ticker,side,qty,signal_date,status,reject_reason "
            "FROM sim_orders WHERE id=?", [order_id],
        ).fetchone()
        if order is None:
            con.execute(
                "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,?,NULL)",
                [order_id, book_id, ticker, side, qty, signal_date, SIM_FILLED_STATUS],
            )
        elif order != expected_order:
            raise P15BookError("P15 simulator order differs from retained evidence")
        expected_fill = (book_id, ticker, side, qty, fill_date, open_px, fill_px,
                         slippage, cost)
        fill = con.execute(
            "SELECT portfolio_id,ticker,side,qty,fill_date,open_px,fill_px,"
            "slippage_bps,cost_bps FROM sim_fills WHERE order_id=?", [order_id],
        ).fetchone()
        if fill is not None:
            if fill != expected_fill:
                raise P15BookError("P15 simulator fill differs from retained evidence")
            continue
        con.execute(
            "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
            [order_id, *expected_fill],
        )
        con.execute(
            "INSERT INTO sim_fill_costs VALUES (?,?,?,?,?,?,?)",
            [order_id, profile, participation, slippage, impact, fee, cost],
        )
        con.execute(
            "INSERT INTO sim_execution_attempts VALUES (?,?,?,?,?,?,?,?)",
            [order_id, fill_date, profile, qty * open_px, median_dollar_vol, participation,
             "filled", None],
        )
        restored += 1
    if restored:
        _rebuild_p15_state(con)
    con.execute(
        "INSERT OR REPLACE INTO sim_equity "
        "SELECT portfolio_id,market_date,equity,cash,n_positions FROM p15_book_windows"
    )
    return restored


def _rebuild_p15_state(con: duckdb.DuckDBPyConnection) -> None:
    for book_id in BOOK_IDS:
        con.execute("DELETE FROM sim_positions WHERE portfolio_id=?", [book_id])
        con.execute("UPDATE portfolios SET cash=initial_cash WHERE id=?", [book_id])
        dates = {row[0] for row in con.execute(
            "SELECT fill_date FROM sim_fills WHERE portfolio_id=?", [book_id],
        ).fetchall()}
        dates.update(row[0] for row in con.execute(
            "SELECT ex_date FROM sim_dividends WHERE portfolio_id=?", [book_id],
        ).fetchall())
        if table_exists(con, "sim_settlements"):
            dates.update(row[0] for row in con.execute(
                "SELECT effective FROM sim_settlements WHERE portfolio_id=?", [book_id],
            ).fetchall())
        for event_date in sorted(dates):
            dividend = con.execute(
                "SELECT COALESCE(SUM(amount),0) FROM sim_dividends "
                "WHERE portfolio_id=? AND ex_date=?", [book_id, event_date],
            ).fetchone()[0]
            con.execute("UPDATE portfolios SET cash=cash+? WHERE id=?", [dividend, book_id])
            if table_exists(con, "sim_settlements"):
                from sim.settle import apply_settlement_event
                for ticker, kind, qty, price, into, ratio in con.execute(
                    "SELECT ticker,kind,qty,price,into_ticker,ratio FROM sim_settlements "
                    "WHERE portfolio_id=? AND effective=? ORDER BY ticker",
                    [book_id, event_date],
                ).fetchall():
                    apply_settlement_event(
                        con, book_id, ticker, kind, float(qty), float(price), into,
                        None if ratio is None else float(ratio),
                    )
            for ticker, side, qty, fill_px in con.execute(
                "SELECT ticker,side,qty,fill_px FROM sim_fills WHERE portfolio_id=? "
                "AND fill_date=? ORDER BY CASE side WHEN 'sell' THEN 0 ELSE 1 END,order_id",
                [book_id, event_date],
            ).fetchall():
                factor = _split_factor(con, ticker, event_date, date.max)
                adjusted = float(qty) * factor
                applied = portfolio.apply_fill(con, {
                    "portfolio_id": book_id, "ticker": ticker, "side": side,
                    "qty": adjusted, "fill_px": float(fill_px) / factor,
                })
                if not math.isclose(applied, adjusted, rel_tol=1e-12, abs_tol=1e-12):
                    raise P15BookError("P15 fill replay changed applied quantity")


def _mark_exact(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, market_date: date,
    completed_at: datetime,
) -> dict:
    retained = con.execute(
        "SELECT equity,cash,n_positions,carried FROM p15_book_windows "
        "WHERE portfolio_id=? AND market_date=?",
        [portfolio_id, market_date],
    ).fetchone()
    cash = portfolio.get_cash(con, portfolio_id)
    carried, market_value = [], 0.0
    positions = portfolio.get_positions(con, portfolio_id)
    for ticker, position in positions.items():
        close, stale = portfolio.close_on(con, ticker, market_date)
        if close is None:
            carried.append(ticker)
        else:
            market_value += float(position["qty"]) * close
            if stale:
                carried.append(ticker)
    expected = (cash + market_value, cash, len(positions))
    if retained is not None:
        if retained[:3] != expected or json.loads(retained[3]) != sorted(carried):
            raise P15BookError("P15 equity replay differs from retained evidence")
        stored = con.execute(
            "SELECT equity,cash,n_positions FROM sim_equity "
            "WHERE portfolio_id=? AND date=?", [portfolio_id, market_date],
        ).fetchone()
        if stored != expected:
            raise P15BookError("P15 simulator mark differs from retained evidence")
        return {"equity": retained[0], "cash": retained[1], "n_positions": retained[2],
                "carried": carried}
    result = portfolio.mark_to_market(con, portfolio_id, market_date)
    con.execute(
        "INSERT INTO p15_book_windows VALUES (?,?,?,?,?,?,?)",
        [portfolio_id, market_date, result["equity"], result["cash"],
         result["n_positions"], json.dumps(sorted(result["carried"])), completed_at],
    )
    return result


def label_limit_counterfactuals(
    con: duckdb.DuckDBPyConnection, *, labeled_at: datetime,
) -> int:
    """Append h5 outcomes from each missed attempt's actual opening session."""
    from . import agent_evaluation

    latest = con.execute("SELECT MAX(date) FROM prices WHERE ticker='SPY'").fetchone()[0]
    if latest is None:
        return 0
    rows = con.execute(
        "SELECT i.id,i.ticker,a.attempt_date,a.counterfactual_fill_px "
        "FROM p15_order_intents i JOIN p15_limit_attempts a ON a.intent_id=i.id "
        "LEFT JOIN p15_limit_labels l ON l.intent_id=i.id "
        "WHERE a.outcome='limit_not_reached' AND l.intent_id IS NULL ORDER BY i.id"
    ).fetchall()
    inserted = 0
    for intent_id, ticker, attempt_date, entry_px in rows:
        sessions = [row[0] for row in con.execute(
            "SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? AND date<=? "
            "ORDER BY date LIMIT 5", [attempt_date, latest],
        ).fetchall()]
        if len(sessions) < 5:
            continue
        outcome = agent_evaluation._label_outcome(con, ticker, sessions, labeled_at)
        if outcome is None or outcome["entry_date"] != attempt_date:
            continue
        spy_net = outcome["net_return"] - outcome["net_excess_return"]
        net_return = float(outcome["exit_close"]) * 0.999 / float(entry_px) - 1
        identity = {
            "intent_id": int(intent_id), "attempt_date": attempt_date.isoformat(),
            "horizon_sessions": 5, "entry_px": float(entry_px),
            "exit_date": outcome["exit_date"].isoformat(),
            "exit_close": outcome["exit_close"], "net_return": net_return,
            "spy_net_return": spy_net, "net_excess_return": net_return - spy_net,
            "price_prefix_sha256": outcome["price_prefix_sha256"],
        }
        con.execute(
            "INSERT INTO p15_limit_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [*identity.values(), labeled_at, canonical_sha256(identity)],
        )
        inserted += 1
    return inserted


def run_window(
    con: duckdb.DuckDBPyConnection, market_date: date, *, observed_at: datetime,
) -> dict:
    """Process, mark, and queue one completed market session for active P15 books."""
    init_schema(con)
    if activation_state(con) != "active":
        return {"status": "inactive", "filled": 0, "rejected": 0,
                "pending": 0, "restored": 0, "queued": 0,
                "counterfactual_labels": 0}
    with db.transaction(con):
        restored = _restore_rerun_evidence(con)
        processed = process_pending(con, market_date)
        marks = {}
        for book_id in BOOK_IDS:
            marks[book_id] = _mark_exact(con, book_id, market_date, observed_at)
        queued = queue_orders(con, market_date, created_at=observed_at)
        labels = label_limit_counterfactuals(con, labeled_at=observed_at)
    return {"status": "completed", **processed, "restored": restored,
            "queued": queued["created"], "counterfactual_labels": labels,
            "marks": marks}


def dry_run_window(
    database: Path, signal_date: date, fill_date: date, *, observed_at: datetime,
    lock_path: Path = REPO_ROOT / ".nightly.lock",
) -> dict:
    """Exercise an active two-session book window on a verified database copy."""
    from tools.backup_database import _copy_database

    with tempfile.TemporaryDirectory(prefix="trading-engine-p15-book-dry-run-") as directory:
        copied = Path(directory) / "market.duckdb"
        with advisory_file_lock(lock_path):
            _copy_database(database, copied)
        con = db.connect(copied, wait_s=0)
        try:
            init_schema(con)
            state = activation_state(con)
            if state == "absent":
                initialize_books(con, signal_date)
                state = "inactive"
            if state == "inactive":
                activate_books(con, signal_date)
            first = run_window(con, signal_date, observed_at=observed_at)
            second = run_window(con, fill_date, observed_at=observed_at)
            return {"status": "completed", "dry_run": True,
                    "signal_date": signal_date.isoformat(),
                    "fill_date": fill_date.isoformat(), "signal": first, "fill": second}
        finally:
            con.close()
