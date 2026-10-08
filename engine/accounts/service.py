"""Transactional application service for engine-owned paper accounts."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from engine import paper_accounts
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.money import alerts, halts
from sim import ledger, nyse
from sim import schema as sim_schema
from sim.order_types import moc_cutoff, moo_cutoff

NEW_YORK = ZoneInfo("America/New_York")
RECONCILIATION_STATUSES = frozenset({"ok", "mismatch"})


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise paper_accounts.AccountRefused("timestamp must include its timezone")
    return now.astimezone(timezone.utc)


def init_schema(con) -> None:
    paper_accounts.init_schema(con)


def create(con, spec: dict, *, now: datetime | None = None) -> dict:
    return paper_accounts.create_account(con, spec, now=_utc(now))


def submit(con, intent: dict, *, received_at: datetime) -> dict:
    return paper_accounts.submit_intent(con, intent, now=_utc(received_at))


def _account(con, account_id: str):
    row = con.execute("SELECT id,active FROM portfolios WHERE id=?", [account_id]).fetchone()
    if row is None:
        raise paper_accounts.AccountRefused("unknown account")
    settings = sim_schema.portfolio_account(con, account_id)
    if settings["engine"] != "account":
        raise paper_accounts.AccountRefused("unknown account")
    return {"id": row[0], "active": bool(row[1]), **settings}


def _cancel_deadline(order_type: str, session_date: date,
                     received_at: datetime | None) -> datetime:
    if order_type in {"moo", "limit_on_open"}:
        return moo_cutoff(session_date).astimezone(timezone.utc)
    if order_type == "moc":
        return moc_cutoff(session_date).astimezone(timezone.utc)
    if received_at is not None and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    if order_type == "market":
        if received_at is None:
            raise paper_accounts.AccountRefused("market order has no receipt timestamp")
        return received_at + timedelta(seconds=60)
    if order_type == "limit":
        if received_at is None:
            raise paper_accounts.AccountRefused("limit order has no receipt timestamp")
        market_open = datetime.combine(session_date, time(9, 30), NEW_YORK).astimezone(
            timezone.utc
        )
        return max(received_at, market_open)
    return datetime.combine(
        nyse.next_session(session_date), time(9, 30), NEW_YORK,
    ).astimezone(timezone.utc)


def cancel(con, account_id: str, order_id: int, *,
           now: datetime | None = None) -> dict:
    now = _utc(now)
    with db.transaction(con):
        init_schema(con)
        _account(con, account_id)
        row = con.execute(
            "SELECT o.status,o.signal_date,d.order_type,d.state,d.received_at FROM sim_orders o "
            "LEFT JOIN sim_order_details d ON d.order_id=o.id "
            "WHERE o.id=? AND o.portfolio_id=?", [order_id, account_id]
        ).fetchone()
        if row is None:
            raise paper_accounts.AccountRefused("unknown account order")
        if row[0] == "cancelled":
            return {"order_id": order_id, "state": "cancelled", "replayed": True}
        if row[0] != "pending" or (row[3] is not None and row[3] != "queued"):
            raise paper_accounts.AccountRefused("order is no longer queued")
        order_type = row[2] or "next_open"
        if now > _cancel_deadline(order_type, row[1], row[4]):
            raise paper_accounts.AccountRefused("order window has opened")
        con.execute(
            "UPDATE sim_orders SET status='cancelled',reject_reason='cancelled_by_client' "
            "WHERE id=?", [order_id]
        )
        con.execute(
            "UPDATE sim_order_details SET state='cancelled',state_reason='cancelled_by_client',"
            "state_at=? WHERE order_id=?", [now, order_id]
        )
        halts.record_event(con, account_id, "cancelled", {"order_id": order_id}, now=now)
    return {"order_id": order_id, "state": "cancelled", "replayed": False}


def halt(con, account_id: str, *, note: str = "", now: datetime | None = None) -> dict:
    now = _utc(now)
    with db.transaction(con):
        changed = halts.halt_account(
            con, account_id, "halt_manual", now=now, detail={"note": str(note)[:4096]},
        )
    return {"account_id": account_id, "status": "halted", "replayed": not changed}


def resume(con, account_id: str, *, resumed_by: str, note: str = "",
           now: datetime | None = None) -> dict:
    now = _utc(now)
    if resumed_by not in {"owner", "monthly-review"}:
        raise paper_accounts.AccountRefused("resumed_by must be owner or monthly-review")
    with db.transaction(con):
        init_schema(con)
        row = _account(con, account_id)
        if row["status"] != "halted":
            raise paper_accounts.AccountRefused("only a halted account can resume")
        equity = con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id=? ORDER BY date DESC LIMIT 1",
            [account_id],
        ).fetchone()
        resume_equity = float(equity[0]) if equity is not None else float(con.execute(
            "SELECT cash FROM portfolios WHERE id=?", [account_id]
        ).fetchone()[0])
        anchor = resume_equity
        accepted = con.execute(
            "SELECT 1 FROM paper_account_intakes WHERE account_id=? LIMIT 1", [account_id]
        ).fetchone() is not None
        con.execute("UPDATE portfolios SET active=? WHERE id=?", [accepted, account_id])
        sim_schema.set_portfolio_account(con, account_id, status="active", updated_at=now)
        con.execute(
            "UPDATE account_state SET resumed_at=?,resumed_by=?,halted_at=NULL,"
            "halt_reason=NULL,drawdown_anchor_equity=?,prior_close_equity=?,updated_at=? "
            "WHERE portfolio_id=?",
            [now, resumed_by, anchor, resume_equity, now, account_id],
        )
        halts.record_event(
            con, account_id, "resumed",
            {"resumed_by": resumed_by, "note": str(note)[:4096]}, now=now,
        )
    return {"account_id": account_id, "status": "active", "resumed_by": resumed_by}


def _retirement_session(now: datetime) -> date:
    return nyse.next_session(now.astimezone(NEW_YORK).date())


def retire(con, account_id: str, *, now: datetime | None = None) -> dict:
    now = _utc(now)
    queued: list[int] = []
    with db.transaction(con):
        init_schema(con)
        row = _account(con, account_id)
        if row["status"] == "retired":
            return {"account_id": account_id, "status": "retired", "queued_order_ids": [],
                    "replayed": True}
        if row["status"] == "retiring":
            queued = [item[0] for item in con.execute(
                "SELECT o.id FROM sim_orders o JOIN sim_order_details d ON d.order_id=o.id "
                "WHERE o.portfolio_id=? AND o.status='pending' "
                "AND d.state_reason LIKE 'retirement%' ORDER BY o.id", [account_id],
            ).fetchall()]
            return {"account_id": account_id, "status": "retiring",
                    "queued_order_ids": queued, "replayed": True}
        session_date = _retirement_session(now)
        opening_ids = [item[0] for item in con.execute(
            "SELECT id FROM sim_orders WHERE portfolio_id=? AND status='pending' "
            "AND side IN ('buy','short') ORDER BY id", [account_id]
        ).fetchall()]
        if opening_ids:
            placeholders = ",".join("?" for _ in opening_ids)
            con.execute(
                f"UPDATE sim_orders SET status='cancelled',reject_reason='retired' "
                f"WHERE id IN ({placeholders})", opening_ids,
            )
            con.execute(
                f"UPDATE sim_order_details SET state='cancelled',state_reason='retired',"
                f"state_at=? WHERE order_id IN ({placeholders}) AND state='queued'",
                [now, *opening_ids],
            )
        positions = con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<>0 ORDER BY ticker",
            [account_id],
        ).fetchall()
        for ticker, quantity in positions:
            order_id = sim_schema.next_order_id(con)
            side = "sell" if quantity > 0 else "cover"
            con.execute(
                "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
                [order_id, account_id, ticker, side, abs(float(quantity)), session_date],
            )
            con.execute(
                "INSERT INTO sim_order_details "
                "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
                "received_at,created_at,state,state_at,source_sha256) "
                "VALUES (?,?,?,?,?,'day',?,?,?,?,?,?)",
                [order_id, ticker, "stock", "moc", side, session_date, now, now, "queued", now,
                 canonical_sha256({"account_id": account_id, "retired_at": now.isoformat(),
                                   "instrument_id": ticker})],
            )
            con.execute(
                "UPDATE sim_order_details SET state_reason='retirement' WHERE order_id=?",
                [order_id],
            )
            queued.append(order_id)
        # Retirement is a lifecycle, not an immediate switch-off.  The account
        # remains collectable/markable until its risk-forced liquidation fills.
        status = "retiring" if positions else "retired"
        con.execute("UPDATE portfolios SET active=? WHERE id=?", [bool(positions), account_id])
        sim_schema.set_portfolio_account(con, account_id, status=status, updated_at=now)
        if not positions:
            con.execute(
                "UPDATE account_state SET retired_at=?,updated_at=? WHERE portfolio_id=?",
                [now, now, account_id],
            )
        halts.record_event(
            con, account_id, "retirement_requested" if positions else "retired",
            {"close_session": session_date.isoformat(), "queued_order_ids": queued,
             "cancelled_opening_order_ids": opening_ids}, now=now,
        )
    return {"account_id": account_id, "status": status, "queued_order_ids": queued,
            "replayed": False}


def finalize_retirement(
    con, account_id: str, *, now: datetime | None = None,
) -> bool:
    """Finalize a requested retirement only after every position is flat."""
    now = _utc(now)
    settings = sim_schema.portfolio_account(con, account_id)
    if settings["status"] != "retiring":
        return False
    held = con.execute(
        "SELECT 1 FROM sim_positions WHERE portfolio_id=? AND abs(qty)>=1e-9 LIMIT 1",
        [account_id],
    ).fetchone()
    if held is not None:
        return False
    con.execute("UPDATE portfolios SET active=FALSE WHERE id=?", [account_id])
    sim_schema.set_portfolio_account(con, account_id, status="retired", updated_at=now)
    con.execute(
        "UPDATE account_state SET retired_at=?,updated_at=? WHERE portfolio_id=?",
        [now, now, account_id],
    )
    halts.record_event(con, account_id, "retired", {"flat": True}, now=now)
    return True


def reconcile(con, account_id: str, reconciliation: dict, *,
              now: datetime | None = None) -> dict:
    now = _utc(now)
    required = {"session_date", "expected_sha256", "observed_sha256", "status", "detail"}
    if not isinstance(reconciliation, dict) or set(reconciliation) != required:
        raise paper_accounts.AccountRefused("invalid reconciliation")
    try:
        session_date = date.fromisoformat(reconciliation["session_date"])
    except (TypeError, ValueError) as exc:
        raise paper_accounts.AccountRefused("invalid reconciliation session") from exc
    for field in ("expected_sha256", "observed_sha256"):
        paper_accounts._identity(reconciliation[field], field, paper_accounts.SHA256)
    if reconciliation["status"] not in RECONCILIATION_STATUSES:
        raise paper_accounts.AccountRefused("invalid reconciliation status")
    detail = str(reconciliation["detail"])[:4096]
    with db.transaction(con):
        init_schema(con)
        _account(con, account_id)
        old = con.execute(
            "SELECT expected_sha256,observed_sha256,status,detail FROM account_reconciliations "
            "WHERE portfolio_id=? AND session_date=?", [account_id, session_date]
        ).fetchone()
        expected = (reconciliation["expected_sha256"], reconciliation["observed_sha256"],
                    reconciliation["status"], detail)
        if old is not None:
            if old != expected:
                raise paper_accounts.AccountRefused(
                    "reconciliation session already bound to different evidence"
                )
            return {"account_id": account_id, "session_date": session_date.isoformat(),
                    "status": old[2], "replayed": True}
        con.execute(
            "INSERT INTO account_reconciliations VALUES (?,?,?,?,?,?,?)",
            [account_id, session_date, *expected, now],
        )
        if reconciliation["status"] == "mismatch":
            halts.halt_account(
                con, account_id, "halt_reconciliation", now=now,
                detail={"session_date": session_date.isoformat(), "detail": detail},
            )
    return {"account_id": account_id, "session_date": session_date.isoformat(),
            "status": reconciliation["status"], "replayed": False}


def replace_watch(con, account_id: str, tickers: list[str], *,
                  now: datetime | None = None) -> dict:
    now = _utc(now)
    if (not isinstance(tickers, list) or len(tickers) > 500
            or any(not isinstance(ticker, str) for ticker in tickers)):
        raise paper_accounts.AccountRefused("watch must contain at most 500 tickers")
    normalized = sorted(set(ticker.upper() for ticker in tickers))
    for ticker in normalized:
        paper_accounts._identity(ticker, "ticker")
    with db.transaction(con):
        init_schema(con)
        _account(con, account_id)
        con.execute("DELETE FROM account_watch WHERE portfolio_id=?", [account_id])
        con.executemany(
            "INSERT INTO account_watch VALUES (?,?,?)",
            [(account_id, ticker, now) for ticker in normalized],
        )
    return {"account_id": account_id, "tickers": normalized}


def account_list(con, *, include_private: bool = False) -> list[dict]:
    init_schema(con)
    visibility = "" if include_private else " AND pa.pa_visibility='public'"
    rows = con.execute(
        "SELECT p.id,pa.pa_status,p.initial_cash,pa.pa_engine,pa.pa_visibility FROM portfolios p "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=p.id "
        f"WHERE pa.pa_engine='account'{visibility} ORDER BY p.id"
    ).fetchall()
    return [{"id": row[0], "status": row[1], "tier": int(row[2]), "engine": row[3],
             "visibility": row[4]} for row in rows]


def _current_state(con, account_id: str) -> dict:
    return {
        "cash": float(con.execute("SELECT cash FROM portfolios WHERE id=?", [account_id])
                      .fetchone()[0]),
        "positions": dict(con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<>0 ORDER BY ticker",
            [account_id],
        ).fetchall()),
    }


def _restore_account_state(con, account_id: str, cash: float, positions, lots, day_trades) -> None:
    con.execute("DELETE FROM sim_positions WHERE portfolio_id=?", [account_id])
    con.execute("DELETE FROM sim_position_lots WHERE portfolio_id=?", [account_id])
    con.execute("DELETE FROM sim_day_trades WHERE portfolio_id=?", [account_id])
    if positions:
        con.executemany("INSERT INTO sim_positions VALUES (?,?,?,?)", positions)
    if lots:
        con.executemany("INSERT INTO sim_position_lots VALUES (?,?,?,?,?,?)", lots)
    if day_trades:
        con.executemany("INSERT INTO sim_day_trades VALUES (?,?,?,?,?)", day_trades)
    con.execute("UPDATE portfolios SET cash=? WHERE id=?", [cash, account_id])


def verify(
    con,
    account_id: str,
    *,
    session_date: date | None = None,
    now: datetime | None = None,
    manage_transaction: bool = True,
) -> dict:
    """Rebuild one account, restore it, and durably halt any mismatch."""
    effective_now = _utc(now)

    def run() -> dict:
        init_schema(con)
        _account(con, account_id)
        observed = _current_state(con, account_id)
        positions = con.execute(
            "SELECT portfolio_id,ticker,qty,avg_cost FROM sim_positions "
            "WHERE portfolio_id=? ORDER BY ticker", [account_id],
        ).fetchall()
        lots = con.execute(
            "SELECT portfolio_id,instrument_id,opened_session,open_order_id,qty,avg_px "
            "FROM sim_position_lots WHERE portfolio_id=? "
            "ORDER BY instrument_id,opened_session,open_order_id", [account_id],
        ).fetchall()
        day_trades = con.execute(
            "SELECT portfolio_id,session_date,instrument_id,open_order_id,close_order_id "
            "FROM sim_day_trades WHERE portfolio_id=? ORDER BY session_date,close_order_id",
            [account_id],
        ).fetchall()
        try:
            ledger.rebuild_state(con, [account_id], through=session_date)
            expected = _current_state(con, account_id)
        finally:
            _restore_account_state(
                con, account_id, observed["cash"], positions, lots, day_trades,
            )
        ok = (abs(expected["cash"] - observed["cash"]) <= 0.005
              and expected["positions"] == observed["positions"])
        result = {
            "account_id": account_id,
            "status": "ok" if ok else "mismatch",
            "expected_sha256": canonical_sha256(expected),
            "observed_sha256": canonical_sha256(observed),
        }
        if ok:
            return result
        effective_session = session_date
        if effective_session is None:
            latest = con.execute(
                "SELECT MAX(date) FROM sim_equity WHERE portfolio_id=?", [account_id]
            ).fetchone()[0]
            effective_session = latest or effective_now.date()
        detail = "engine ledger reconstruction differs from stored cash/positions"
        con.execute(
            "INSERT INTO account_reconciliations VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (portfolio_id,session_date) DO UPDATE SET "
            "expected_sha256=excluded.expected_sha256,"
            "observed_sha256=excluded.observed_sha256,status='mismatch',"
            "detail=excluded.detail,created_at=excluded.created_at",
            [account_id, effective_session, result["expected_sha256"],
             result["observed_sha256"], "mismatch", detail, effective_now],
        )
        halts.halt_account(
            con, account_id, "halt_reconciliation", now=effective_now,
            detail={"session_date": effective_session.isoformat(), "detail": detail},
        )
        return result

    if manage_transaction:
        with db.transaction(con):
            return run()
    return run()


def run_alerts(con, session_date: date, *, now: datetime | None = None) -> list[dict]:
    with db.transaction(con):
        return alerts.concentration(con, session_date, now=_utc(now))
