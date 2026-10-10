"""Per-account drawdown, daily-loss, and reconciliation halts."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from engine.paper_accounts import AccountRefused, init_schema
from sim.schema import portfolio_account, set_portfolio_account

from .limits import DAILY_LOSS_LIMIT, DRAWDOWN_LIMIT, daily_return, drawdown

HALT_REASONS = frozenset({"halt_drawdown", "halt_daily_loss", "halt_reconciliation"})
FORCED_CLOSE_REASONS = ("buy_in", "margin_call", "retirement")


def next_event_id(con) -> int:
    return int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM account_events").fetchone()[0])


def record_event(con, portfolio_id: str, kind: str, payload: dict,
                 *, now: datetime) -> int:
    event_id = next_event_id(con)
    con.execute(
        "INSERT INTO account_events (id,portfolio_id,kind,payload,created_at) "
        "VALUES (?,?,?,?,?)",
        [event_id, portfolio_id, kind,
         json.dumps(payload, sort_keys=True, separators=(",", ":")), now],
    )
    return event_id


def _state(con, portfolio_id: str, now: datetime):
    row = con.execute(
        "SELECT peak_equity,prior_close_equity,halted_at,halt_reason,resumed_at,"
        "drawdown_anchor_equity "
        "FROM account_state WHERE portfolio_id=?", [portfolio_id]
    ).fetchone()
    if row is not None:
        return row
    initial = con.execute("SELECT initial_cash FROM portfolios WHERE id=?", [portfolio_id]) \
        .fetchone()
    if initial is None:
        raise AccountRefused("unknown account")
    con.execute(
        "INSERT INTO account_state (portfolio_id,peak_equity,prior_close_equity,"
        "drawdown_anchor_equity,updated_at) VALUES (?,?,?,?,?)",
        [portfolio_id, initial[0], initial[0], initial[0], now],
    )
    return float(initial[0]), float(initial[0]), None, None, None, float(initial[0])


def halt_account(con, portfolio_id: str, reason: str, *, now: datetime,
                 detail: dict | None = None) -> bool:
    """Halt once, retain positions, and cancel every queued order."""
    if reason not in HALT_REASONS and reason != "halt_manual":
        raise AccountRefused("invalid halt reason")
    init_schema(con)
    exists = con.execute("SELECT 1 FROM portfolios WHERE id=?", [portfolio_id]).fetchone()
    if exists is None:
        raise AccountRefused("unknown account")
    settings = portfolio_account(con, portfolio_id)
    if settings["engine"] != "account":
        raise AccountRefused("unknown account")
    if settings["status"] == "retired":
        raise AccountRefused("retired")
    if settings["status"] == "halted":
        return False
    _state(con, portfolio_id, now)
    set_portfolio_account(con, portfolio_id, status="halted", updated_at=now)
    con.execute(
        "UPDATE account_state SET halted_at=?,halt_reason=?,updated_at=? WHERE portfolio_id=?",
        [now, reason, now, portfolio_id],
    )
    forced = " OR ".join(
        f"COALESCE(d.state_reason,'') LIKE '{value}%'" for value in FORCED_CLOSE_REASONS
    )
    order_ids = [row[0] for row in con.execute(
        "SELECT o.id FROM sim_orders o LEFT JOIN sim_order_details d ON d.order_id=o.id "
        "WHERE o.portfolio_id=? AND o.status='pending' AND NOT (" + forced + ")",
        [portfolio_id],
    ).fetchall()]
    if order_ids:
        placeholders = ",".join("?" for _ in order_ids)
        con.execute(
            f"UPDATE sim_orders SET status='cancelled',reject_reason=? "
            f"WHERE id IN ({placeholders})", [reason, *order_ids],
        )
        con.execute(
            f"UPDATE sim_order_details SET state='cancelled',state_reason=?,state_at=? "
            f"WHERE order_id IN ({placeholders}) AND state='queued'",
            [reason, now, *order_ids],
        )
    payload = {"reason_code": reason, "cancelled_order_ids": order_ids, **(detail or {})}
    record_event(con, portfolio_id, reason, payload, now=now)
    return True


def _latest_reconciliation(con, portfolio_id: str, session_date: date):
    return con.execute(
        "SELECT session_date,status,detail,created_at FROM account_reconciliations "
        "WHERE portfolio_id=? AND session_date<=? "
        "ORDER BY session_date DESC,created_at DESC LIMIT 1", [portfolio_id, session_date]
    ).fetchone()


def check(con, portfolio_id: str, session_date: date, *,
          now: datetime | None = None) -> str | None:
    """Apply the three halt rules after a persisted account equity mark."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    init_schema(con)
    exists = con.execute("SELECT 1 FROM portfolios WHERE id=?", [portfolio_id]).fetchone()
    if exists is None:
        raise AccountRefused("unknown account")
    settings = portfolio_account(con, portfolio_id)
    if settings["engine"] != "account":
        raise AccountRefused("unknown account")
    if settings["status"] in {"halted", "retired"}:
        return None
    equity_row = con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id=? AND date=?",
        [portfolio_id, session_date],
    ).fetchone()
    if equity_row is None:
        raise AccountRefused("account has no equity mark for halt check")
    equity = float(equity_row[0])
    _state(con, portfolio_id, now)
    initial = float(con.execute('SELECT initial_cash FROM portfolios WHERE id=?', [portfolio_id]).fetchone()[0])
    curve = con.execute('SELECT date,equity FROM sim_equity WHERE portfolio_id=? AND date<=? '
                        'ORDER BY date', [portfolio_id, session_date]).fetchall()
    resume = con.execute("SELECT created_at,payload FROM account_events WHERE portfolio_id=? "
                         "AND kind='resumed' ORDER BY created_at DESC,id DESC LIMIT 1",
                         [portfolio_id]).fetchone()
    resumed_at, anchor_day, anchor = None, None, initial
    if resume:
        resumed_at, raw = resume
        payload = json.loads(raw)
        anchor_day = date.fromisoformat(payload['anchor_session']) if payload.get('anchor_session') else None
        anchor = next((float(value) for day, value in curve if day == anchor_day), initial)
    subsequent = [(day, float(value)) for day, value in curve if anchor_day is None or day > anchor_day]
    peak = max([initial, *[float(value) for _, value in curve]])
    risk_peak = max([anchor, *[value for _, value in subsequent]])
    prior = subsequent[-2][1] if len(subsequent) > 1 else anchor
    con.execute('UPDATE account_state SET drawdown_anchor_equity=? WHERE portfolio_id=?',
                [anchor, portfolio_id])
    latest_reconciliation = _latest_reconciliation(con, portfolio_id, session_date)
    reason, detail = None, {}
    fresh_mismatch = (
        latest_reconciliation is not None
        and latest_reconciliation[1] == "mismatch"
        and (resumed_at is None or latest_reconciliation[3] > resumed_at)
    )
    if fresh_mismatch:
        reason = "halt_reconciliation"
        detail = {"session_date": latest_reconciliation[0].isoformat(),
                  "detail": latest_reconciliation[2]}
    elif equity <= risk_peak * (1.0 + DRAWDOWN_LIMIT):
        reason = "halt_drawdown"
        detail = {"drawdown": drawdown(equity, risk_peak), "equity": equity,
                  "peak_equity": risk_peak}
    elif (daily_return(equity, prior) is not None
          and equity <= float(prior) * (1.0 + DAILY_LOSS_LIMIT)):
        reason = "halt_daily_loss"
        detail = {"daily_return": daily_return(equity, prior), "equity": equity,
                  "prior_close_equity": prior}
    con.execute(
        "UPDATE account_state SET peak_equity=?,prior_close_equity=?,updated_at=? "
        "WHERE portfolio_id=?", [peak, equity, now, portfolio_id]
    )
    if reason is not None:
        halt_account(con, portfolio_id, reason, now=now, detail=detail)
    return reason


def check_all(con, session_date: date, *, now: datetime | None = None) -> dict[str, str]:
    results = {}
    rows = con.execute(
        "SELECT portfolio_id FROM portfolio_accounts_v WHERE pa_engine='account' "
        "AND pa_status='active' ORDER BY portfolio_id"
    ).fetchall()
    for (portfolio_id,) in rows:
        reason = check(con, portfolio_id, session_date, now=now)
        if reason is not None:
            results[portfolio_id] = reason
    return results
