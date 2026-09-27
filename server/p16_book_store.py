"""Versioned, append-only state for the two inert P16 construction books."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from engine.lib.provenance import canonical_sha256
from sim.schema import init_sim_schema

LOGICAL_BOOK_IDS = ("p16_construct_ai", "p16_construct_rule")
INITIAL_CAPITAL = 10_000.0
MECHANICS_VERSION = "p16-construct-v1"


class P16BookError(ValueError):
    """A construction-book state transition differs from its frozen contract."""


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise P16BookError(f"{field} is invalid")
    return value


def _timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise P16BookError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def versioned_book_id(logical_book_id: str, registration_sha256: str) -> str:
    if logical_book_id not in LOGICAL_BOOK_IDS:
        raise P16BookError("unknown P16 construction book")
    return f"{logical_book_id}@sha256:{_digest(registration_sha256, 'registration digest')}"


def init_schema(con) -> None:
    init_sim_schema(con)
    con.execute("""CREATE TABLE IF NOT EXISTS p16_book_contracts (
        book_instance_id VARCHAR PRIMARY KEY, logical_portfolio_id VARCHAR NOT NULL,
        registration_sha256 VARCHAR NOT NULL, portfolio_id VARCHAR NOT NULL UNIQUE,
        mechanics_version VARCHAR NOT NULL, activation_date DATE,
        initial_capital DOUBLE NOT NULL, risk_aversion DOUBLE NOT NULL,
        cost_per_turnover DOUBLE NOT NULL, no_trade_band DOUBLE NOT NULL,
        config_json VARCHAR NOT NULL, contract_sha256 VARCHAR NOT NULL UNIQUE,
        created_at TIMESTAMP NOT NULL,
        UNIQUE(logical_portfolio_id,registration_sha256))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_book_state (
        book_instance_id VARCHAR NOT NULL, market_date DATE NOT NULL,
        peak_equity DOUBLE NOT NULL, entry_halted BOOLEAN NOT NULL,
        equity DOUBLE NOT NULL, cash DOUBLE NOT NULL, spy_mark DOUBLE,
        stock_marks_json VARCHAR NOT NULL, position_state_sha256 VARCHAR NOT NULL,
        previous_state_sha256 VARCHAR, state_sha256 VARCHAR NOT NULL UNIQUE,
        recorded_at TIMESTAMP NOT NULL, PRIMARY KEY(book_instance_id,market_date))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_book_windows (
        book_instance_id VARCHAR NOT NULL, market_date DATE NOT NULL,
        information_cutoff_at TIMESTAMP NOT NULL, risk_sha256 VARCHAR NOT NULL,
        score_sha256 VARCHAR NOT NULL, previous_state_sha256 VARCHAR,
        target_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR,
        started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP,
        window_sha256 VARCHAR NOT NULL UNIQUE,
        PRIMARY KEY(book_instance_id,market_date))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_order_intents (
        intent_id VARCHAR PRIMARY KEY, book_instance_id VARCHAR NOT NULL,
        signal_date DATE NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL,
        order_role VARCHAR NOT NULL, target_weight DOUBLE NOT NULL,
        rounded_qty DOUBLE NOT NULL, source_sha256 VARCHAR NOT NULL,
        limit_px DOUBLE, entry_atr DOUBLE, expected_session DATE NOT NULL,
        status VARCHAR NOT NULL,
        reason VARCHAR, sim_order_id BIGINT UNIQUE, created_at TIMESTAMP NOT NULL,
        intent_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(book_instance_id,signal_date,ticker,side,order_role))""")
    # This mirrors p15_limit_attempts. Horizon-return outcomes live separately below.
    con.execute("""CREATE TABLE IF NOT EXISTS p16_limit_attempts (
        intent_id VARCHAR NOT NULL, attempt_date DATE NOT NULL, limit_px DOUBLE NOT NULL,
        open_px DOUBLE, counterfactual_fill_px DOUBLE, outcome VARCHAR NOT NULL,
        reject_reason VARCHAR, PRIMARY KEY(intent_id,attempt_date))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_limit_labels (
        intent_id VARCHAR PRIMARY KEY, attempt_date DATE NOT NULL,
        horizon_sessions INTEGER NOT NULL, entry_px DOUBLE NOT NULL,
        exit_date DATE NOT NULL, exit_close DOUBLE NOT NULL,
        net_return DOUBLE NOT NULL, spy_net_return DOUBLE NOT NULL,
        net_excess_return DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL,
        labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_book_fills (
        intent_id VARCHAR PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE,
        book_instance_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        side VARCHAR NOT NULL, qty DOUBLE NOT NULL, fill_date DATE NOT NULL,
        open_px DOUBLE NOT NULL, fill_px DOUBLE NOT NULL,
        slippage_bps DOUBLE NOT NULL, cost_bps DOUBLE NOT NULL,
        execution_profile VARCHAR NOT NULL, median_dollar_vol DOUBLE,
        participation DOUBLE, impact_bps DOUBLE NOT NULL, fee_bps DOUBLE NOT NULL,
        source_sha256 VARCHAR NOT NULL, fill_sha256 VARCHAR NOT NULL UNIQUE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_position_rules (
        book_instance_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        entry_intent_id VARCHAR NOT NULL, entry_order_id BIGINT NOT NULL,
        entry_date DATE NOT NULL, entry_atr DOUBLE NOT NULL, stop_px DOUBLE NOT NULL,
        status VARCHAR NOT NULL, exit_intent_id VARCHAR,
        PRIMARY KEY(book_instance_id,ticker,entry_intent_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_construct_targets (
        book_instance_id VARCHAR NOT NULL, signal_date DATE NOT NULL,
        risk_snapshot_sha256 VARCHAR NOT NULL, score_sha256 VARCHAR NOT NULL,
        ic_source_sha256 VARCHAR NOT NULL, risk_aversion DOUBLE NOT NULL,
        cost_per_turnover DOUBLE NOT NULL, solver_status VARCHAR NOT NULL,
        residuals_json VARCHAR NOT NULL, sector_coverage DOUBLE NOT NULL,
        sector_status VARCHAR NOT NULL, continuous_json VARCHAR NOT NULL,
        banded_json VARCHAR, rounded_json VARCHAR, target_sha256 VARCHAR NOT NULL UNIQUE,
        recorded_at TIMESTAMP NOT NULL, PRIMARY KEY(book_instance_id,signal_date))""")


def initialize_contracts(
    con, *, registration_sha256: str, activation_date: date | None,
    risk_aversion: float, cost_per_turnover: float, created_at: datetime,
) -> list[str]:
    """Create or verify inactive, versioned book contracts without runtime evidence."""
    init_schema(con)
    registration = _digest(registration_sha256, "registration digest")
    recorded = _timestamp(created_at, "contract creation time")
    if (not isinstance(risk_aversion, (int, float)) or risk_aversion <= 0
            or not isinstance(cost_per_turnover, (int, float))
            or cost_per_turnover < 0):
        raise P16BookError("construction calibration is invalid")
    instances = []
    for logical in LOGICAL_BOOK_IDS:
        instance = versioned_book_id(logical, registration)
        config = {
            "mechanics_version": MECHANICS_VERSION, "logical_portfolio_id": logical,
            "registration_sha256": registration, "initial_capital": INITIAL_CAPITAL,
            "risk_aversion": float(risk_aversion),
            "cost_per_turnover": float(cost_per_turnover), "no_trade_band": 0.005,
            "execution_profile": "baseline_v1", "entry_order_type": "limit_on_open",
            "atr_period": 14, "atr_multiple": 2.5, "time_exit_sessions": 10,
            "drawdown_halt": -0.20, "ai_preopen_cancel": False,
            "simulator_only": True,
        }
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
        contract_sha = canonical_sha256(config)
        expected = (
            instance, logical, registration, instance, MECHANICS_VERSION,
            activation_date, INITIAL_CAPITAL, float(risk_aversion),
            float(cost_per_turnover), 0.005, encoded, contract_sha,
        )
        prior = con.execute(
            "SELECT book_instance_id,logical_portfolio_id,registration_sha256,portfolio_id,"
            "mechanics_version,activation_date,initial_capital,risk_aversion,"
            "cost_per_turnover,no_trade_band,config_json,contract_sha256 "
            "FROM p16_book_contracts WHERE book_instance_id=?", [instance],
        ).fetchone()
        if prior is not None and prior != expected:
            raise P16BookError("P16 construction contract replay differs")
        if prior is None:
            con.execute(
                "INSERT INTO portfolios "
                "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
                "VALUES (?,?,?,?,?,FALSE,?,?,?)",
                [instance, logical, "agent_only_policy", encoded,
                 activation_date or recorded.date(), INITIAL_CAPITAL,
                 INITIAL_CAPITAL, "baseline_v1"],
            )
            con.execute(
                "INSERT INTO p16_book_contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [*expected, recorded],
            )
        instances.append(instance)
    return instances


def add_intent(
    con, *, book_instance_id: str, signal_date: date, ticker: str, side: str,
    order_role: str, target_weight: float, rounded_qty: float,
    source_sha256: str, limit_px: float | None, expected_session: date,
    created_at: datetime, entry_atr: float | None = None,
) -> tuple[str, bool]:
    """Append one deterministic intent; exact retries are idempotent."""
    if (side not in {"buy", "sell"} or not ticker or not order_role
            or rounded_qty <= 0 or target_weight < 0):
        raise P16BookError("P16 intent fields are invalid")
    source = _digest(source_sha256, "intent source digest")
    created = _timestamp(created_at, "intent creation time")
    if entry_atr is not None and entry_atr <= 0:
        raise P16BookError("P16 entry ATR is invalid")
    logical = {
        "book_instance_id": book_instance_id, "signal_date": signal_date.isoformat(),
        "ticker": ticker, "side": side, "order_role": order_role,
    }
    intent_id = canonical_sha256(logical)
    payload = {
        **logical, "target_weight": float(target_weight),
        "rounded_qty": float(rounded_qty), "source_sha256": source,
        "limit_px": None if limit_px is None else float(limit_px),
        "entry_atr": None if entry_atr is None else float(entry_atr),
        "expected_session": expected_session.isoformat(),
    }
    intent_sha = canonical_sha256(payload)
    prior = con.execute(
        "SELECT target_weight,rounded_qty,source_sha256,limit_px,entry_atr,"
        "expected_session,intent_sha256 "
        "FROM p16_order_intents WHERE intent_id=?", [intent_id],
    ).fetchone()
    expected = (
        float(target_weight), float(rounded_qty), source,
        None if limit_px is None else float(limit_px),
        None if entry_atr is None else float(entry_atr), expected_session, intent_sha,
    )
    if prior is not None:
        if prior != expected:
            raise P16BookError("P16 intent replay differs")
        return intent_id, False
    con.execute(
        "INSERT INTO p16_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [intent_id, book_instance_id, signal_date, ticker, side, order_role,
         float(target_weight), float(rounded_qty), source, limit_px, entry_atr,
         expected_session, "pending", None, None, created, intent_sha],
    )
    return intent_id, True


def record_limit_attempt(
    con, *, intent_id: str, attempt_date: date, limit_px: float,
    open_px: float | None, counterfactual_fill_px: float | None,
    outcome: str, reject_reason: str | None,
) -> bool:
    expected = (float(limit_px), open_px, counterfactual_fill_px, outcome, reject_reason)
    prior = con.execute(
        "SELECT limit_px,open_px,counterfactual_fill_px,outcome,reject_reason "
        "FROM p16_limit_attempts WHERE intent_id=? AND attempt_date=?",
        [intent_id, attempt_date],
    ).fetchone()
    if prior is not None:
        if prior != expected:
            raise P16BookError("P16 limit-attempt replay differs")
        return False
    con.execute(
        "INSERT INTO p16_limit_attempts VALUES (?,?,?,?,?,?,?)",
        [intent_id, attempt_date, *expected],
    )
    return True


def claim_window(
    con, *, book_instance_id: str, market_date: date,
    information_cutoff_at: datetime, risk_sha256: str, score_sha256: str,
    previous_state_sha256: str | None, target_sha256: str, started_at: datetime,
) -> str:
    """Claim an immutable input tuple for one session; exact recovery reuses it."""
    cutoff = _timestamp(information_cutoff_at, "window information cutoff")
    started = _timestamp(started_at, "window start")
    risk = _digest(risk_sha256, "risk digest")
    score = _digest(score_sha256, "score digest")
    target = _digest(target_sha256, "target digest")
    previous = None if previous_state_sha256 is None else _digest(
        previous_state_sha256, "previous state digest",
    )
    body = {
        "book_instance_id": book_instance_id, "market_date": market_date.isoformat(),
        "information_cutoff_at": cutoff.isoformat(), "risk_sha256": risk,
        "score_sha256": score, "previous_state_sha256": previous,
        "target_sha256": target,
    }
    digest = canonical_sha256(body)
    prior = con.execute(
        "SELECT information_cutoff_at,risk_sha256,score_sha256,previous_state_sha256,"
        "target_sha256,status,window_sha256 FROM p16_book_windows "
        "WHERE book_instance_id=? AND market_date=?", [book_instance_id, market_date],
    ).fetchone()
    expected = (cutoff, risk, score, previous, target)
    if prior is not None:
        if prior[:5] != expected or prior[6] != digest:
            raise P16BookError("P16 completed or running window input differs")
        return prior[5]
    con.execute(
        "INSERT INTO p16_book_windows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [book_instance_id, market_date, cutoff, risk, score, previous, target,
         "running", None, started, None, digest],
    )
    return "running"


def complete_window(
    con, *, book_instance_id: str, market_date: date, status: str,
    reason: str | None, completed_at: datetime,
) -> None:
    if status not in {"completed", "failed"}:
        raise P16BookError("P16 terminal window status is invalid")
    completed = _timestamp(completed_at, "window completion")
    prior = con.execute(
        "SELECT status,reason,completed_at FROM p16_book_windows "
        "WHERE book_instance_id=? AND market_date=?", [book_instance_id, market_date],
    ).fetchone()
    if prior is None:
        raise P16BookError("P16 window was not claimed")
    if prior[0] != "running":
        if prior != (status, reason, completed):
            raise P16BookError("P16 terminal window replay differs")
        return
    con.execute(
        "UPDATE p16_book_windows SET status=?,reason=?,completed_at=? "
        "WHERE book_instance_id=? AND market_date=?",
        [status, reason, completed, book_instance_id, market_date],
    )


def append_state(
    con, *, book_instance_id: str, market_date: date, peak_equity: float,
    entry_halted: bool, equity: float, cash: float, spy_mark: float | None,
    stock_marks: dict[str, float | None], position_state_sha256: str,
    previous_state_sha256: str | None, recorded_at: datetime,
) -> str:
    """Append one chained close-state projection; it is never updated in place."""
    position = _digest(position_state_sha256, "position state digest")
    previous = None if previous_state_sha256 is None else _digest(
        previous_state_sha256, "previous state digest",
    )
    recorded = _timestamp(recorded_at, "state recording time")
    marks_json = json.dumps(stock_marks, sort_keys=True, separators=(",", ":"), allow_nan=False)
    body = {
        "book_instance_id": book_instance_id, "market_date": market_date.isoformat(),
        "peak_equity": float(peak_equity), "entry_halted": bool(entry_halted),
        "equity": float(equity), "cash": float(cash), "spy_mark": spy_mark,
        "stock_marks": stock_marks, "position_state_sha256": position,
        "previous_state_sha256": previous,
    }
    state_sha = canonical_sha256(body)
    expected = (
        float(peak_equity), bool(entry_halted), float(equity), float(cash), spy_mark,
        marks_json, position, previous, state_sha,
    )
    prior = con.execute(
        "SELECT peak_equity,entry_halted,equity,cash,spy_mark,stock_marks_json,"
        "position_state_sha256,previous_state_sha256,state_sha256 FROM p16_book_state "
        "WHERE book_instance_id=? AND market_date=?", [book_instance_id, market_date],
    ).fetchone()
    if prior is not None:
        if prior != expected:
            raise P16BookError("P16 state replay differs")
        return state_sha
    latest = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "ORDER BY market_date DESC LIMIT 1", [book_instance_id],
    ).fetchone()
    if (None if latest is None else latest[0]) != previous:
        raise P16BookError("P16 state chain predecessor differs")
    con.execute(
        "INSERT INTO p16_book_state VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [book_instance_id, market_date, peak_equity, entry_halted, equity, cash,
         spy_mark, marks_json, position, previous, state_sha, recorded],
    )
    return state_sha
