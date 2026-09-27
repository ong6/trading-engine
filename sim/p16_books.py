"""Inert simulator lifecycle for versioned P16 construction books."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime

from engine.lib import db
from engine.lib.data_quality import quarantine_reason
from engine.lib.db import REAL_BAR_SQL
from server import p16_book_store
from sim import nyse, p15_fills, p16_book_mechanics


def queue_plan(
    con, *, book_instance_id: str, signal_date: date, plan: dict,
    limit_prices: dict[str, float], source_sha256: str, created_at: datetime,
    entry_gates: dict[str, str] | None = None, transactional: bool = True,
) -> int:
    """Retain a precomputed whole-share plan; this function never activates a book."""
    if plan.get("status") not in {"planned", "rounded_plan_infeasible"}:
        raise p16_book_store.P16BookError("P16 order plan status is invalid")
    created = 0
    gates = entry_gates or {}
    expected_session = nyse.next_session(signal_date)
    with db.transaction(con) if transactional else nullcontext():
        for order in plan.get("orders", []):
            ticker, side = order["ticker"], order["side"]
            limit_px = limit_prices.get(ticker) if side == "buy" and ticker != "SPY" else None
            if side == "buy" and ticker != "SPY" and limit_px is None:
                raise p16_book_store.P16BookError("P16 stock buy lacks its limit")
            if side == "buy" and ticker != "SPY" and gates.get(ticker) != "eligible":
                raise p16_book_store.P16BookError("P16 stock buy lacks entry-gate authority")
            _, inserted = p16_book_store.add_intent(
                con, book_instance_id=book_instance_id, signal_date=signal_date,
                ticker=ticker, side=side, order_role=order["order_role"],
                target_weight=order["target_weight"], rounded_qty=order["qty"],
                source_sha256=source_sha256, limit_px=limit_px,
                expected_session=expected_session, created_at=created_at,
                entry_atr=order.get("entry_atr"),
            )
            created += int(inserted)
    return created


def _pending_rows(con, book_instance_id: str, fill_date: date) -> list[tuple]:
    return con.execute(
        "SELECT intent_id,ticker,side,rounded_qty,signal_date,order_role,limit_px,entry_atr,"
        "expected_session,source_sha256 FROM p16_order_intents "
        "WHERE book_instance_id=? AND status='pending' AND signal_date<? "
        "ORDER BY signal_date,CASE WHEN side='sell' THEN 0 ELSE 1 END,ticker,intent_id",
        [book_instance_id, fill_date],
    ).fetchall()


def label_limit_counterfactuals(
    con, *, book_instance_id: str, labeled_at: datetime,
) -> int:
    """Append mature h5 outcomes for this book's missed limit attempts."""
    from server import agent_evaluation

    cutoff = p16_book_store._timestamp(labeled_at, "limit-label time")
    latest = con.execute(
        f"SELECT MAX(date) FROM prices WHERE ticker='SPY' "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL}", [cutoff],
    ).fetchone()[0]
    if latest is None:
        return 0
    rows = con.execute(
        "SELECT i.intent_id,i.ticker,a.attempt_date,a.counterfactual_fill_px "
        "FROM p16_order_intents i JOIN p16_limit_attempts a "
        "ON a.intent_id=i.intent_id LEFT JOIN p16_limit_labels l "
        "ON l.intent_id=i.intent_id WHERE i.book_instance_id=? "
        "AND a.outcome IN "
        "('limit_not_reached','cancelled_would_fill','cancelled_limit_not_reached') "
        "AND a.counterfactual_fill_px IS NOT NULL AND l.intent_id IS NULL "
        "ORDER BY i.intent_id", [book_instance_id],
    ).fetchall()
    inserted = 0
    for intent_id, ticker, attempt_date, entry_px in rows:
        sessions = [row[0] for row in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? AND date<=? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date LIMIT 5", [attempt_date, latest, cutoff],
        ).fetchall()]
        if len(sessions) < 5:
            continue
        outcome = agent_evaluation._label_outcome_when_ready(
            con, ticker, sessions, labeled_at,
        )
        if outcome is None or outcome["entry_date"] != attempt_date:
            continue
        spy_net = outcome["spy_net_return"]
        net_return = float(outcome["exit_close"]) * 0.999 / float(entry_px) - 1
        inserted += int(p16_book_store.record_limit_label(
            con, intent_id=intent_id, attempt_date=attempt_date,
            horizon_sessions=5, entry_px=float(entry_px),
            exit_date=outcome["exit_date"], exit_close=outcome["exit_close"],
            net_return=net_return, spy_net_return=spy_net,
            net_excess_return=net_return - spy_net,
            price_prefix_sha256=outcome["price_prefix_sha256"], labeled_at=labeled_at,
        ))
    return inserted


def mandatory_exits(
    con, *, book_instance_id: str, market_date: date, information_cutoff_at: datetime,
    held_tickers: set[str] | None = None,
) -> dict[str, str]:
    """Derive the registered ATR-stop and ten-session exits from retained rules."""
    cutoff = p16_book_store._timestamp(information_cutoff_at, "exit cutoff")
    if held_tickers is None:
        tickers = [row[0] for row in con.execute(
            "SELECT ticker FROM sim_positions WHERE portfolio_id=? "
            "AND ticker!='SPY' AND qty>0 ORDER BY ticker", [book_instance_id],
        ).fetchall()]
    else:
        tickers = sorted(held_tickers)
    exits = {}
    for ticker in tickers:
        rules = con.execute(
            "SELECT entry_date,stop_px FROM p16_position_rules "
            "WHERE book_instance_id=? AND ticker=? AND status='open' ORDER BY entry_date",
            [book_instance_id, ticker],
        ).fetchall()
        if not rules:
            raise p16_book_store.P16BookError("P16 open position rule is absent")
        close = con.execute(
            f"SELECT close FROM prices WHERE ticker=? AND date=? AND fetched_at IS NOT NULL "
            f"AND fetched_at<=? AND {REAL_BAR_SQL}", [ticker, market_date, cutoff],
        ).fetchone()
        stop_due = any(
            close is not None and float(close[0]) <= float(stop_px)
            / p16_book_mechanics.split_factor(con, ticker, entry_date, market_date)
            for entry_date, stop_px in rules
        )
        time_due = any(int(con.execute(
            f"SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' "
            f"AND date>=? AND date<=? AND fetched_at IS NOT NULL AND fetched_at<=? "
            f"AND {REAL_BAR_SQL}", [entry_date, market_date, cutoff],
        ).fetchone()[0]) >= 10 for entry_date, _stop_px in rules)
        if stop_due:
            exits[ticker] = "stop"
        elif time_due:
            exits[ticker] = "time_exit"
    return exits


def process_window(
    con, *, book_instance_id: str, market_date: date, observed_at: datetime,
) -> dict:
    """Process terminal attempts and append the close state in one transaction."""
    p16_book_store.init_schema(con)
    active = con.execute(
        "SELECT active FROM portfolios WHERE id=?", [book_instance_id],
    ).fetchone()
    if active is None or not active[0]:
        return {"status": "inactive", "filled": 0, "rejected": 0, "pending": 0}
    counts = {"filled": 0, "rejected": 0, "pending": 0}
    with db.transaction(con):
        latest_date = con.execute(
            "SELECT MAX(market_date) FROM p16_book_state WHERE book_instance_id=?",
            [book_instance_id],
        ).fetchone()[0]
        if latest_date is not None and market_date > nyse.next_session(latest_date):
            raise p16_book_store.P16BookError("P16 book window skipped a market session")
        if latest_date is not None and market_date < latest_date:
            raise p16_book_store.P16BookError("P16 book window moved backward")
        previous = con.execute(
            "SELECT state_sha256,peak_equity,entry_halted FROM p16_book_state "
            "WHERE book_instance_id=? AND market_date<? ORDER BY market_date DESC LIMIT 1",
            [book_instance_id, market_date],
        ).fetchone()
        outcomes = []
        for row in _pending_rows(con, book_instance_id, market_date):
            (intent_id, ticker, side, quantity, signal_date, role, limit_px, _entry_atr,
             expected_session, source_sha256) = row
            factor = p16_book_mechanics.split_factor(con, ticker, signal_date, market_date)
            quantity = float(quantity) * factor
            adjusted_limit = None if limit_px is None else float(limit_px) / factor
            stale = role == "rebalance" and market_date > expected_session
            halted = (side == "buy" and ticker != "SPY" and role == "rebalance"
                      and bool(previous and previous[2]))
            quarantined = side == "buy" and ticker != "SPY" \
                and quarantine_reason(con, ticker) is not None
            if stale:
                result = p15_fills.LimitFillResult(
                    status="rejected", reject_reason="stale_signal",
                )
            elif halted:
                result = p15_fills.LimitFillResult(
                    status="rejected", reject_reason="drawdown_halt",
                )
            elif quarantined:
                result = p15_fills.LimitFillResult(
                    status="rejected", reject_reason="data_quarantine",
                )
            elif adjusted_limit is not None:
                result = p16_book_mechanics.attempt_limit_on_open(
                    con, ticker, side, quantity, signal_date, market_date,
                    adjusted_limit, "baseline_v1",
                )
            else:
                result = p16_book_mechanics.attempt_fill(
                    con, ticker, side, quantity, signal_date, market_date, "baseline_v1",
                )
            outcomes.append((row, quantity, adjusted_limit, result))
        pending = sum(result.status == "pending" for *_rest, result in outcomes)
        if pending:
            return {
                "status": "pending", "filled": 0, "rejected": 0,
                "pending": pending, "counterfactual_labels": 0,
            }
        for row, quantity, adjusted_limit, result in outcomes:
            (intent_id, _ticker, _side, _original_quantity, _signal_date, _role,
             _limit_px, _entry_atr, _expected_session, source_sha256) = row
            if adjusted_limit is not None:
                outcome = (result.reject_reason if result.reject_reason == "limit_not_reached"
                           else result.status)
                p16_book_store.record_limit_attempt(
                    con, intent_id=intent_id, attempt_date=market_date,
                    limit_px=adjusted_limit, open_px=result.open_px,
                    counterfactual_fill_px=result.counterfactual_fill_px,
                    outcome=outcome, reject_reason=result.reject_reason,
                )
            status = p16_book_mechanics.record_sim_fill(
                con, intent_id=intent_id, fill_date=market_date,
                result=result, source_sha256=source_sha256,
                adjusted_quantity=quantity,
            )
            counts[status] += 1
        mark = p16_book_mechanics.mark_exact(con, book_instance_id, market_date)
        peak = max(mark["equity"], mark["equity"] if previous is None else previous[1])
        halted = bool(previous and previous[2]) or mark["equity"] / peak - 1 <= -0.20
        state_sha = p16_book_store.append_state(
            con, book_instance_id=book_instance_id, market_date=market_date,
            peak_equity=peak, entry_halted=halted, equity=mark["equity"],
            cash=mark["cash"], spy_mark=mark["marks"].get("SPY"),
            stock_marks={key: value for key, value in mark["marks"].items() if key != "SPY"},
            position_state_sha256=mark["position_state_sha256"],
            previous_state_sha256=None if previous is None else previous[0],
            recorded_at=observed_at,
        )
        labels = label_limit_counterfactuals(
            con, book_instance_id=book_instance_id, labeled_at=observed_at,
        )
        window = con.execute(
            "SELECT status FROM p16_book_windows WHERE book_instance_id=? "
            "AND market_date=?", [book_instance_id, market_date],
        ).fetchone()
        if window is not None:
            p16_book_store.complete_window(
                con, book_instance_id=book_instance_id, market_date=market_date,
                status="completed", reason=None, completed_at=observed_at,
            )
    return {"status": "completed", **counts, "counterfactual_labels": labels,
            "state_sha256": state_sha, "mark": mark}


def process_through(
    con, *, book_instance_id: str, market_date: date, observed_at: datetime,
) -> dict:
    """Process every missing exchange session in order through ``market_date``."""
    latest = con.execute(
        "SELECT MAX(market_date) FROM p16_book_state WHERE book_instance_id=?",
        [book_instance_id],
    ).fetchone()[0]
    running = con.execute(
        "SELECT MIN(market_date) FROM p16_book_windows WHERE book_instance_id=? "
        "AND status='running' AND market_date<=?", [book_instance_id, market_date],
    ).fetchone()[0]
    if latest is not None and market_date < latest:
        raise p16_book_store.P16BookError("P16 book window moved backward")
    if latest is None:
        cursor = running or market_date
    elif latest == market_date:
        cursor = market_date
    else:
        cursor = nyse.next_session(latest)
        if running is not None and running < cursor:
            cursor = running
    sessions = []
    while cursor <= market_date:
        sessions.append(cursor)
        cursor = nyse.next_session(cursor)
    results = []
    processed_sessions = []
    for session in sessions:
        result = process_window(
            con, book_instance_id=book_instance_id, market_date=session,
            observed_at=observed_at,
        )
        results.append(result)
        processed_sessions.append(session)
        if result["status"] == "pending":
            break
    return {
        "status": ("already_complete" if not results else "pending"
                   if results[-1]["status"] == "pending" else "completed"),
        "sessions": [session.isoformat() for session in processed_sessions],
        "filled": sum(row["filled"] for row in results),
        "rejected": sum(row["rejected"] for row in results),
        "counterfactual_labels": sum(
            row.get("counterfactual_labels", 0) for row in results
        ),
    }
