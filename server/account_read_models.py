"""Read-only projections for engine-owned paper accounts."""
from __future__ import annotations

from datetime import date

from engine.accounts import results
from engine.lib.util import table_exists
from engine.money.limits import margin_excess
from engine.paper_accounts import AccountRefused, portfolio_account


def visibility(con, account_id: str) -> str:
    row = con.execute("SELECT 1 FROM portfolios WHERE id=?", [account_id]).fetchone()
    if row is None:
        raise AccountRefused("unknown account")
    settings = portfolio_account(con, account_id)
    if settings["engine"] != "account":
        raise AccountRefused("unknown account")
    return settings["visibility"]


def accounts(con, *, include_private: bool = False) -> list[dict]:
    if not table_exists(con, "portfolio_accounts"):
        return []
    clause = "" if include_private else " AND pa.visibility='public'"
    rows = con.execute(
        "SELECT p.id,pa.status,p.initial_cash,pa.engine,pa.visibility FROM portfolios p "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=p.id "
        f"WHERE pa.engine='account'{clause} ORDER BY p.id"
    ).fetchall()
    return [{"id": row[0], "status": row[1], "tier": int(row[2]), "engine": row[3],
             "visibility": row[4]} for row in rows]


def positions(con, account_id: str) -> list[dict]:
    visibility(con, account_id)
    rows = con.execute(
        "SELECT sp.ticker,sp.qty,sp.avg_cost,(SELECT close FROM prices pr "
        "WHERE pr.ticker=sp.ticker ORDER BY date DESC LIMIT 1) AS mark "
        "FROM sim_positions sp WHERE sp.portfolio_id=? AND sp.qty<>0 ORDER BY sp.ticker",
        [account_id],
    ).fetchall()
    return [{"instrument_id": ticker, "quantity": float(quantity), "avg_cost": float(cost),
             "mark": None if mark is None else float(mark),
             "market_value": None if mark is None else float(quantity) * float(mark)}
            for ticker, quantity, cost, mark in rows]


def account(con, account_id: str) -> dict:
    settings = portfolio_account(con, account_id)
    if settings["engine"] != "account":
        raise AccountRefused("unknown account")
    row = con.execute(
        "SELECT p.cash,p.initial_cash,e.date,e.equity FROM portfolios p "
        "LEFT JOIN LATERAL (SELECT date,equity FROM sim_equity WHERE portfolio_id=p.id "
        "ORDER BY date DESC LIMIT 1) e ON TRUE WHERE p.id=?", [account_id]
    ).fetchone()
    if row is None:
        raise AccountRefused("unknown account")
    held = positions(con, account_id)
    long_value = sum(max(item["market_value"] or 0.0, 0.0) for item in held)
    short_value = sum(min(item["market_value"] or 0.0, 0.0) for item in held)
    equity = float(row[3]) if row[3] is not None else float(row[0]) + long_value + short_value
    state = con.execute(
        "SELECT halted_at,halt_reason,resumed_at,resumed_by,pdt_flagged_at,pdt_restricted_until "
        "FROM account_state WHERE portfolio_id=?", [account_id]
    ).fetchone()
    return {
        "id": account_id,
        "status": settings["status"],
        "cash": float(row[0]),
        "equity": equity,
        "equity_date": row[2].isoformat() if row[2] else None,
        "positions_market_value": long_value + short_value,
        "gross_market_value": long_value + abs(short_value),
        "margin_excess": margin_excess(equity, long_value, short_value),
        "pdt": {"flagged_at": state[4].isoformat() if state and state[4] else None,
                "restricted_until": state[5].isoformat() if state and state[5] else None},
        "halt": {"halted_at": state[0].isoformat() if state and state[0] else None,
                 "reason": state[1] if state else None,
                 "resumed_at": state[2].isoformat() if state and state[2] else None,
                 "resumed_by": state[3] if state else None},
        "cost_profile": settings["cost_profile"],
        "account_type": settings["account_type"],
        "day_trade_rule": settings["day_trade_rule"],
        "allow_short": bool(settings["allow_short"]),
    }


def orders(con, account_id: str, *, since: date | None = None) -> list[dict]:
    visibility(con, account_id)
    clause, params = "", [account_id]
    if since is not None:
        clause, params = " AND o.signal_date>=?", [account_id, since]
    rows = con.execute(
        "SELECT o.id,o.ticker,o.side,o.qty,o.signal_date,o.status,o.reject_reason,"
        "d.order_type,d.tif,d.limit_px,d.received_at,d.state,d.state_reason "
        "FROM sim_orders o LEFT JOIN sim_order_details d ON d.order_id=o.id "
        f"WHERE o.portfolio_id=?{clause} ORDER BY o.id", params,
    ).fetchall()
    return [{"order_id": row[0], "instrument_id": row[1], "side": row[2],
             "quantity": float(row[3]), "session_date": row[4].isoformat(),
             "status": row[5], "reject_reason": row[6], "order_type": row[7],
             "time_in_force": row[8], "limit_price": row[9],
             "received_at": row[10].replace(tzinfo=None).isoformat() + "+00:00" if row[10] else None,
             "state": row[11], "state_reason": row[12]} for row in rows]


def fills(con, account_id: str, *, since: date | None = None) -> list[dict]:
    visibility(con, account_id)
    clause, params = "", [account_id]
    if since is not None:
        clause, params = " AND f.fill_date>=?", [account_id, since]
    rows = con.execute(
        "SELECT f.order_id,f.ticker,f.side,f.qty,f.fill_date,f.fill_px,fd.fill_ts,"
        "fd.fill_kind,fd.price_source,fd.late_settled,ff.total_usd "
        "FROM sim_fills f LEFT JOIN sim_fill_details fd ON fd.order_id=f.order_id "
        "LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id "
        f"WHERE f.portfolio_id=?{clause} ORDER BY f.fill_date,f.order_id", params,
    ).fetchall()
    return [{"order_id": row[0], "instrument_id": row[1], "side": row[2],
             "quantity": float(row[3]), "fill_date": row[4].isoformat(),
             "fill_price": float(row[5]), "fill_at": row[6].isoformat() if row[6] else None,
             "fill_kind": row[7], "price_source": row[8], "late_settled": bool(row[9]),
             "fees_usd": float(row[10] or 0.0)} for row in rows]


def cash_events(con, account_id: str, *, since: date | None = None) -> list[dict]:
    visibility(con, account_id)
    clause, params = "", [account_id]
    if since is not None:
        clause, params = " AND event_date>=?", [account_id, since]
    rows = con.execute(
        "SELECT event_date,seq,kind,amount,instrument_id,ref_order_id,note,created_at "
        f"FROM sim_cash_events WHERE portfolio_id=?{clause} ORDER BY event_date,seq", params,
    ).fetchall()
    return [{"date": row[0].isoformat(), "seq": row[1], "kind": row[2],
             "amount": float(row[3]), "instrument_id": row[4], "ref_order_id": row[5],
             "note": row[6], "created_at": row[7].isoformat()} for row in rows]


def equity(con, account_id: str) -> list[dict]:
    return results.build(con, account_id)["equity_curve"]


def result(con, account_id: str) -> dict:
    return results.build(con, account_id)
