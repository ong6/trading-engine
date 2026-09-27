"""Inert simulator lifecycle for versioned P16 construction books."""
from __future__ import annotations

from datetime import date, datetime

from engine.lib import db
from engine.lib.data_quality import quarantine_reason
from server import p16_book_store
from sim import nyse, p15_fills, p16_book_mechanics


def queue_plan(
    con, *, book_instance_id: str, signal_date: date, plan: dict,
    limit_prices: dict[str, float], source_sha256: str, created_at: datetime,
) -> int:
    """Retain a precomputed whole-share plan; this function never activates a book."""
    if plan.get("status") not in {"planned", "rounded_plan_infeasible"}:
        raise p16_book_store.P16BookError("P16 order plan status is invalid")
    created = 0
    expected_session = nyse.next_session(signal_date)
    with db.transaction(con):
        for order in plan.get("orders", []):
            ticker, side = order["ticker"], order["side"]
            limit_px = limit_prices.get(ticker) if side == "buy" and ticker != "SPY" else None
            if side == "buy" and ticker != "SPY" and limit_px is None:
                raise p16_book_store.P16BookError("P16 stock buy lacks its limit")
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
        for row in _pending_rows(con, book_instance_id, market_date):
            (intent_id, ticker, side, quantity, signal_date, role, limit_px, _entry_atr,
             expected_session, source_sha256) = row
            factor = p16_book_mechanics.split_factor(con, ticker, signal_date, market_date)
            quantity = float(quantity) * factor
            adjusted_limit = None if limit_px is None else float(limit_px) / factor
            stale = role == "rebalance" and market_date > expected_session
            quarantined = side == "buy" and ticker != "SPY" \
                and quarantine_reason(con, ticker) is not None
            if stale:
                result = p15_fills.LimitFillResult(
                    status="rejected", reject_reason="stale_signal",
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
            if adjusted_limit is not None:
                outcome = (result.reject_reason if result.reject_reason == "limit_not_reached"
                           else result.status)
                p16_book_store.record_limit_attempt(
                    con, intent_id=intent_id, attempt_date=market_date,
                    limit_px=adjusted_limit, open_px=result.open_px,
                    counterfactual_fill_px=result.counterfactual_fill_px,
                    outcome=outcome, reject_reason=result.reject_reason,
                )
            if result.status == "pending":
                counts["pending"] += 1
                continue
            status = p16_book_mechanics.record_sim_fill(
                con, intent_id=intent_id, fill_date=market_date,
                result=result, source_sha256=source_sha256,
                adjusted_quantity=quantity,
            )
            counts[status] += 1
        mark = p16_book_mechanics.mark_exact(con, book_instance_id, market_date)
        previous = con.execute(
            "SELECT state_sha256,peak_equity,entry_halted FROM p16_book_state "
            "WHERE book_instance_id=? AND market_date<? ORDER BY market_date DESC LIMIT 1",
            [book_instance_id, market_date],
        ).fetchone()
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
    return {"status": "completed", **counts, "state_sha256": state_sha, "mark": mark}
