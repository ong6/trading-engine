"""Transactional application service for engine-owned paper accounts."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine import paper_accounts
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.money import alerts, halts
from sim import ledger, nyse
from sim import schema as sim_schema

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


def _window_start(order_type: str, session_date: date) -> datetime:
    if order_type in {"moo", "limit_on_open"}:
        at = time(9, 30)
    elif order_type == "moc":
        at = time(16, 0)
    elif order_type in {"market", "limit"}:
        at = time(16, 0)
    else:
        at = time(9, 30)
        session_date = nyse.next_session(session_date)
    return datetime.combine(session_date, at, NEW_YORK).astimezone(timezone.utc)


def cancel(con, account_id: str, order_id: int, *,
           now: datetime | None = None) -> dict:
    now = _utc(now)
    with db.transaction(con):
        init_schema(con)
        _account(con, account_id)
        row = con.execute(
            "SELECT o.status,o.signal_date,d.order_type,d.state FROM sim_orders o "
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
        if now >= _window_start(order_type, row[1]):
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
        con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [account_id])
        sim_schema.set_portfolio_account(con, account_id, status="active", updated_at=now)
        con.execute(
            "UPDATE account_state SET resumed_at=?,resumed_by=?,halted_at=NULL,"
            "halt_reason=NULL,updated_at=? WHERE portfolio_id=?",
            [now, resumed_by, now, account_id],
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
        session_date = _retirement_session(now)
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
            queued.append(order_id)
        con.execute("UPDATE portfolios SET active=FALSE WHERE id=?", [account_id])
        sim_schema.set_portfolio_account(con, account_id, status="retired", updated_at=now)
        con.execute(
            "UPDATE account_state SET retired_at=?,updated_at=? WHERE portfolio_id=?",
            [now, now, account_id],
        )
        halts.record_event(
            con, account_id, "retired",
            {"close_session": session_date.isoformat(), "queued_order_ids": queued}, now=now,
        )
    return {"account_id": account_id, "status": "retired", "queued_order_ids": queued,
            "replayed": False}


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


def verify(con, account_id: str) -> dict:
    """Compare current cash/positions with a read-only ledger reconstruction."""
    init_schema(con)
    _account(con, account_id)
    observed = _current_state(con, account_id)
    with db.transaction(con, commit=False):
        ledger.rebuild_state(con)
        expected = _current_state(con, account_id)
    ok = canonical_sha256(expected) == canonical_sha256(observed)
    return {"account_id": account_id, "status": "ok" if ok else "mismatch",
            "expected_sha256": canonical_sha256(expected),
            "observed_sha256": canonical_sha256(observed)}


def run_alerts(con, session_date: date, *, now: datetime | None = None) -> list[dict]:
    with db.transaction(con):
        return alerts.concentration(con, session_date, now=_utc(now))
