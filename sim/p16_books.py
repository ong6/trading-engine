"""Inert simulator lifecycle for versioned P16 construction books."""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from engine.lib import db
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.p16_order_planner import plan_mandatory_exit_orders
from server import p16_book_store
from sim import fills, nyse, p15_fills, p16_book_mechanics

_NEW_YORK = ZoneInfo("America/New_York")


def _session_open_utc(market_date: date) -> datetime:
    return datetime.combine(
        market_date, time(9, 30), tzinfo=_NEW_YORK,
    ).astimezone(timezone.utc).replace(tzinfo=None)


def _latest_opened_session(observed_at: datetime) -> date:
    observed = p16_book_store._timestamp(observed_at, "window observation time")
    local = observed.replace(tzinfo=timezone.utc).astimezone(_NEW_YORK)
    current = local.date()
    if not nyse.is_session(current) or local.time() < time(9, 30):
        current -= timedelta(days=1)
        while not nyse.is_session(current):
            current -= timedelta(days=1)
    return current


def _elapsed_sessions(signal_date: date, through: date) -> int:
    count, current = 0, signal_date
    while current < through:
        current = nyse.next_session(current)
        if current <= through:
            count += 1
    return count


def _quarantine_reason_at_open(con, ticker: str, market_date: date) -> str | None:
    """Return quarantine authority known at the modeled open, never retry time."""
    if not table_exists(con, "price_quarantine"):
        return None
    cutoff = _session_open_utc(market_date)
    if table_exists(con, "audit_log"):
        latest = None
        for _ts, action, encoded in con.execute(
            "SELECT ts,action,payload FROM audit_log WHERE actor='price_quarantine' "
            "AND ts<=? ORDER BY ts,CASE action WHEN 'activate' THEN 0 ELSE 1 END",
            [cutoff],
        ).fetchall():
            try:
                payload = json.loads(encoded)
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("ticker") == ticker.upper() and action in {"activate", "resolve"}:
                latest = (action, payload)
        if latest is not None:
            return latest[1].get("reason") if latest[0] == "activate" else None
    row = con.execute(
        "SELECT reason FROM price_quarantine WHERE ticker=? AND confirmed_at<=? "
        "AND (resolved_at IS NULL OR resolved_at>?)",
        [ticker.upper(), cutoff, cutoff],
    ).fetchone()
    return None if row is None else str(row[0])


def _attempt_at_expected_open(
    con, *, ticker: str, side: str, quantity: float, signal_date: date,
    expected_session: date, limit_px: float | None, observed_at: datetime,
):
    observed = p16_book_store._timestamp(observed_at, "window observation time")
    if observed < _session_open_utc(expected_session):
        return p15_fills.LimitFillResult(status="pending")
    available = con.execute(
        f"SELECT 1 FROM prices WHERE ticker=? AND date=? AND fetched_at IS NOT NULL "
        f"AND fetched_at<=? AND {REAL_BAR_SQL}",
        [ticker, expected_session, observed],
    ).fetchone() is not None
    if not available:
        status = "rejected" if _elapsed_sessions(
            signal_date, _latest_opened_session(observed_at),
        ) >= fills.PENDING_MAX_DAYS else "pending"
        return p15_fills.LimitFillResult(
            status=status, reject_reason="no_bar" if status == "rejected" else None,
        )
    if limit_px is not None:
        return p16_book_mechanics.attempt_limit_on_open(
            con, ticker, side, quantity, signal_date, expected_session,
            limit_px, "baseline_v1",
        )
    return p16_book_mechanics.attempt_fill(
        con, ticker, side, quantity, signal_date, expected_session, "baseline_v1",
    )


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


def deferred_mandatory_exits(
    con, *, book_instance_id: str, held_tickers: set[str], signal_date: date,
    information_cutoff_at: datetime,
) -> dict[str, str]:
    """Carry a recovery-detected exit until its entry lot closes, as visible at the cutoff."""
    cutoff = p16_book_store._timestamp(information_cutoff_at, "deferred exit cutoff")
    rows = con.execute(
        "SELECT rounded_json FROM p16_construct_targets WHERE book_instance_id=? "
        "AND solver_status='input_unavailable' AND signal_date<=? AND recorded_at<=? "
        "ORDER BY signal_date",
        [book_instance_id, signal_date, cutoff],
    ).fetchall()
    deferred = {}
    for (encoded,) in rows:
        payload = json.loads(encoded)
        for ticker, item in payload.get("deferred_mandatory_exits", {}).items():
            if ticker not in held_tickers or not isinstance(item, dict):
                continue
            entry_ids = item.get("entry_intent_ids")
            if not isinstance(entry_ids, list) or not entry_ids:
                continue
            open_count = con.execute(
                "SELECT COUNT(*) FROM p16_position_rules r WHERE r.book_instance_id=? "
                "AND r.ticker=? AND r.entry_date<=? AND r.entry_intent_id IN ("
                + ",".join("?" for _value in entry_ids) + ") AND NOT EXISTS ("
                "SELECT 1 FROM p16_book_fills f WHERE f.intent_id=r.exit_intent_id "
                "AND f.fill_date<=?)",
                [book_instance_id, ticker, signal_date, *entry_ids, signal_date],
            ).fetchone()[0]
            if open_count == len(entry_ids):
                deferred[ticker] = item["reason"]
    return deferred


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
        window = con.execute(
            "SELECT status,previous_state_sha256,target_sha256,reason "
            "FROM p16_book_windows "
            "WHERE book_instance_id=? AND market_date=?",
            [book_instance_id, market_date],
        ).fetchone()
        if window is None:
            raise p16_book_store.P16BookError("P16 book window was not claimed")
        if window[0] == "completed":
            return {
                "status": "already_complete", "filled": 0, "rejected": 0,
                "pending": 0, "counterfactual_labels": 0,
            }
        if window[0] != "running":
            raise p16_book_store.P16BookError("P16 book window is not runnable")
        latest_date = con.execute(
            "SELECT MAX(market_date) FROM p16_book_state WHERE book_instance_id=?",
            [book_instance_id],
        ).fetchone()[0]
        if latest_date is not None and market_date > nyse.next_session(latest_date):
            raise p16_book_store.P16BookError("P16 book window skipped a market session")
        if latest_date is not None and market_date <= latest_date:
            raise p16_book_store.P16BookError("P16 book window moved backward")
        previous = con.execute(
            "SELECT state_sha256,peak_equity,entry_halted,position_state_sha256 "
            "FROM p16_book_state "
            "WHERE book_instance_id=? AND market_date<? ORDER BY market_date DESC LIMIT 1",
            [book_instance_id, market_date],
        ).fetchone()
        actual_previous = None if previous is None else previous[0]
        if window[1] != actual_previous:
            raise p16_book_store.P16BookError(
                "P16 window previous state differs",
            )
        current_position = p16_book_mechanics.current_position_state(con, book_instance_id)
        if previous is None:
            initial_cash = con.execute(
                "SELECT initial_cash FROM portfolios WHERE id=?", [book_instance_id],
            ).fetchone()[0]
            expected_position = canonical_sha256({
                "cash": float(initial_cash), "positions": {},
            })
        else:
            expected_position = previous[3]
        if current_position["position_state_sha256"] != expected_position:
            raise p16_book_store.P16BookError("P16 mutable position state differs")
        pending_rows = _pending_rows(con, book_instance_id, market_date)
        authority_rows = con.execute(
            "SELECT source_sha256,status FROM p16_order_intents "
            "WHERE book_instance_id=? AND expected_session=?",
            [book_instance_id, market_date],
        ).fetchall()
        if any(source != window[2] or status != "pending"
               for source, status in authority_rows):
            raise p16_book_store.P16BookError("P16 window intent authority differs")
        outcomes = []
        for row in pending_rows:
            (intent_id, ticker, side, quantity, signal_date, role, limit_px, entry_atr,
             expected_session, source_sha256) = row
            if expected_session != market_date:
                raise p16_book_store.P16BookError(
                    "P16 intent expected session differs from its window",
                )
            factor = p16_book_mechanics.split_factor(con, ticker, signal_date, market_date)
            quantity = float(quantity) * factor
            adjusted_limit = None if limit_px is None else float(limit_px) / factor
            adjusted_entry_atr = None if entry_atr is None else float(entry_atr) / factor
            stale = role == "rebalance" and market_date > expected_session
            halted = (side == "buy" and ticker != "SPY" and role == "rebalance"
                      and bool(previous and previous[2]))
            quarantined = side == "buy" and ticker != "SPY" \
                and _quarantine_reason_at_open(con, ticker, market_date) is not None
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
            else:
                result = _attempt_at_expected_open(
                    con, ticker=ticker, side=side, quantity=quantity,
                    signal_date=signal_date, expected_session=expected_session,
                    limit_px=adjusted_limit, observed_at=observed_at,
                )
            outcomes.append((row, quantity, adjusted_limit, adjusted_entry_atr, result))
        pending = sum(result.status == "pending" for *_rest, result in outcomes)
        if pending:
            return {
                "status": "pending", "filled": 0, "rejected": 0,
                "pending": pending, "counterfactual_labels": 0,
            }
        for row, quantity, adjusted_limit, adjusted_entry_atr, result in outcomes:
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
                adjusted_quantity=quantity, adjusted_entry_atr=adjusted_entry_atr,
            )
            counts[status] += 1
        mark = p16_book_mechanics.mark_exact(con, book_instance_id, market_date)
        initial_capital = con.execute(
            "SELECT initial_cash FROM portfolios WHERE id=?", [book_instance_id],
        ).fetchone()[0]
        peak = max(mark["equity"], float(initial_capital) if previous is None else previous[1])
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
        p16_book_store.complete_window(
            con, book_instance_id=book_instance_id, market_date=market_date,
            status="completed",
            reason="ordered_recovery" if window[3] == "ordered_recovery" else None,
            completed_at=observed_at,
        )
    return {"status": "completed", **counts, "counterfactual_labels": labels,
            "state_sha256": state_sha, "mark": mark}


def _queue_recovery_window(
    con, *, book_instance_id: str, signal_date: date, observed_at: datetime,
) -> date | None:
    """Claim a mandatory-only modeled session after an earlier window delayed the book."""
    market_date = nyse.next_session(signal_date)
    if not table_exists(con, "p15_price_fetch_batches"):
        return None
    cutoff_row = con.execute(
        "SELECT MIN(attempted_at) FROM p15_price_fetch_batches "
        "WHERE market_date=? AND source='yfinance' AND failed_count=0 "
        "AND requested_count=present_count+missing_count",
        [signal_date],
    ).fetchone()
    modeled_cutoff = None if cutoff_row is None else cutoff_row[0]
    observed = p16_book_store._timestamp(observed_at, "recovery observation time")
    if modeled_cutoff is None or modeled_cutoff > observed:
        return None
    current = p16_book_mechanics.current_position_state(con, book_instance_id)
    held = {
        ticker for ticker, position in current["positions"].items()
        if ticker != "SPY" and float(position["qty"]) > 0
    }
    if held:
        placeholders = ",".join("?" for _ticker in held)
        available = con.execute(
            f"SELECT COUNT(DISTINCT ticker) FROM prices WHERE ticker IN ({placeholders}) "
            f"AND date=? AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL}",
            [*sorted(held), signal_date, modeled_cutoff],
        ).fetchone()[0]
        if available != len(held):
            return None
    cutoff = modeled_cutoff.replace(tzinfo=timezone.utc)
    exits = mandatory_exits(
        con, book_instance_id=book_instance_id, market_date=signal_date,
        information_cutoff_at=cutoff, held_tickers=held,
    )
    quantities = {
        ticker: float(position["qty"])
        for ticker, position in current["positions"].items()
        if float(position["qty"]) > 0
    }
    plan = plan_mandatory_exit_orders(quantities, exits)
    previous = con.execute(
        "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
        "AND market_date=?", [book_instance_id, signal_date],
    ).fetchone()
    contract = con.execute(
        "SELECT risk_aversion,cost_per_turnover FROM p16_book_contracts "
        "WHERE book_instance_id=?", [book_instance_id],
    ).fetchone()
    if previous is None or contract is None:
        raise p16_book_store.P16BookError("P16 recovery predecessor is unavailable")
    recovery_sha = canonical_sha256({
        "kind": "ordered_mandatory_recovery", "book_instance_id": book_instance_id,
        "signal_date": signal_date.isoformat(), "market_date": market_date.isoformat(),
        "previous_state_sha256": previous[0], "mandatory_exits": exits,
    })
    with db.transaction(con):
        target_sha = p16_book_store.record_target(
            con, book_instance_id=book_instance_id, signal_date=signal_date,
            risk_snapshot_sha256=recovery_sha, score_sha256=recovery_sha,
            ic_source_sha256=recovery_sha, risk_aversion=float(contract[0]),
            cost_per_turnover=float(contract[1]), solver_result={
                "status": "input_unavailable", "reason": "ordered_recovery",
                "sector_coverage": None, "sector_status": None,
            }, continuous_weights=None, banded_weights=None, rounded_plan=plan,
            recorded_at=observed_at,
        )
        p16_book_store.claim_recovery_window(
            con, book_instance_id=book_instance_id, signal_date=signal_date,
            information_cutoff_at=cutoff, risk_sha256=recovery_sha,
            score_sha256=recovery_sha, previous_state_sha256=previous[0],
            target_sha256=target_sha, recovered_at=observed_at,
        )
        queue_plan(
            con, book_instance_id=book_instance_id, signal_date=signal_date,
            plan=plan, limit_prices={}, source_sha256=target_sha,
            created_at=cutoff, transactional=False,
        )
    return market_date


def process_through(
    con, *, book_instance_id: str, market_date: date, observed_at: datetime,
) -> dict:
    """Process every missing exchange session in order through ``market_date``."""
    latest = con.execute(
        "SELECT MAX(market_date) FROM p16_book_state WHERE book_instance_id=?",
        [book_instance_id],
    ).fetchone()[0]
    if latest is not None and market_date < latest:
        raise p16_book_store.P16BookError("P16 book window moved backward")
    results = []
    processed_sessions = []
    observed = p16_book_store._timestamp(observed_at, "recovery observation time")
    while True:
        latest = con.execute(
            "SELECT MAX(market_date) FROM p16_book_state WHERE book_instance_id=?",
            [book_instance_id],
        ).fetchone()[0]
        running = con.execute(
            "SELECT MIN(market_date) FROM p16_book_windows WHERE book_instance_id=? "
            "AND status='running' AND market_date<=?", [book_instance_id, market_date],
        ).fetchone()[0]
        if (latest is not None and latest < market_date
                and (running is None or running > nyse.next_session(latest))):
            if observed < _session_open_utc(nyse.next_session(latest)):
                break
            running = _queue_recovery_window(
                con, book_instance_id=book_instance_id, signal_date=latest,
                observed_at=observed_at,
            )
            if running is None:
                break
        elif running is None:
            break
        result = process_window(
            con, book_instance_id=book_instance_id, market_date=running,
            observed_at=observed_at,
        )
        results.append(result)
        processed_sessions.append(running)
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
