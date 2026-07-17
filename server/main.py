"""M3 FastAPI backend — local mock-trading dashboard + gated discretionary tickets.

Binds 127.0.0.1 only, no auth (mock system). GET endpoints open the DB read-only
per request; write endpoints open read-write and map a contended write lock to
HTTP 503 (the nightly league run holds it). This server never fills orders or
steps the league — a submitted ticket becomes a *pending* sim_orders row that the
existing nightly step fills at the next open.

Run from repo root:  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "engine"))

from lib import db as engine_db  # noqa: E402
from sim.league import (  # noqa: E402
    _max_drawdown, _spy_return, regime_label,
)
from sim.schema import INITIAL_CASH, init_sim_schema  # noqa: E402

from . import risk  # noqa: E402
from .db import DBBusyError, db_path, read_con, write_con  # noqa: E402

app = FastAPI(title="trading-engine M3 backend", version="0.1.0")

DISC_ID = risk.DISC_ID


@app.exception_handler(DBBusyError)
async def _busy_handler(request, exc):  # noqa: ANN001
    return JSONResponse(
        status_code=503,
        content={"detail": "database busy (nightly run?) — retry later"},
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _rows(cur: duckdb.DuckDBPyConnection) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(con, action: str, payload: dict) -> None:
    con.execute(
        "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
        [_now(), "user", action, json.dumps(payload, default=str)],
    )


def _latest_prices_date(con) -> date | None:
    return con.execute("SELECT MAX(date) FROM prices").fetchone()[0]


def _table_exists(con, name: str) -> bool:
    """disc_tickets et al. only appear after the first write — reads must tolerate
    their absence rather than 500."""
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone() is not None


# --------------------------------------------------------------------------- #
# health / meta
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    readable = False
    try:
        con = read_con()
        try:
            con.execute("SELECT 1")
            readable = True
        finally:
            con.close()
    except DBBusyError:
        readable = False
    return {"ok": True, "db_path": str(db_path()), "db_readable": readable}


@app.get("/meta")
def meta():
    meta_path = REPO_ROOT / "data" / "_meta.json"
    meta_json = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    con = read_con()
    try:
        latest = _latest_prices_date(con)
    finally:
        con.close()
    freshness = None if latest is None else (date.today() - latest).days
    return {"meta": meta_json, "latest_prices_date": latest,
            "freshness_days": freshness}


# --------------------------------------------------------------------------- #
# screen
# --------------------------------------------------------------------------- #
def _screen_payload(con, run_date: date) -> dict:
    hdr = con.execute(
        "SELECT COUNT(*) AS n_total, "
        "SUM(CASE WHEN passes_template THEN 1 ELSE 0 END) AS n_passing, "
        "SUM(CASE WHEN new_today THEN 1 ELSE 0 END) AS n_new_today "
        "FROM screen_results WHERE run_date = ?",
        [run_date],
    ).fetchone()
    results = _rows(con.execute(
        "SELECT * FROM screen_results WHERE run_date = ? AND passes_template "
        "ORDER BY rs_rank DESC, ticker",
        [run_date],
    ))
    return {
        "run_date": run_date,
        "n_total": hdr[0], "n_passing": hdr[1], "n_new_today": hdr[2],
        "results": results,
    }


@app.get("/screen/latest")
def screen_latest():
    con = read_con()
    try:
        rd = con.execute("SELECT MAX(run_date) FROM screen_results").fetchone()[0]
        if rd is None:
            raise HTTPException(404, "no screen_results")
        return _screen_payload(con, rd)
    finally:
        con.close()


@app.get("/screen/{run_date}")
def screen_by_date(run_date: str):
    con = read_con()
    try:
        rd = date.fromisoformat(run_date)
        exists = con.execute(
            "SELECT 1 FROM screen_results WHERE run_date = ? LIMIT 1", [rd]
        ).fetchone()
        if not exists:
            raise HTTPException(404, f"no screen for {run_date}")
        return _screen_payload(con, rd)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# league
# --------------------------------------------------------------------------- #
@app.get("/league")
def league():
    con = read_con()
    try:
        d = _latest_prices_date(con)
        rows = []
        if _table_exists(con, "portfolios"):
            for pf_id, name, created in con.execute(
                "SELECT id, name, created FROM portfolios WHERE active ORDER BY id"
            ).fetchall():
                eq = con.execute(
                    "SELECT date, equity FROM sim_equity WHERE portfolio_id = ? "
                    "ORDER BY date", [pf_id],
                ).fetchall()
                if not eq:
                    continue
                series = [e for _, e in eq]
                equity = series[-1]
                total_ret = equity / INITIAL_CASH - 1
                spy_ret = _spy_return(con, created, d)
                vs_spy = None if spy_ret is None else total_ret - spy_ret
                mdd = _max_drawdown(series)
                last5 = series[-1] / series[-6] - 1 if len(series) >= 6 else None
                n_open = con.execute(
                    "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? "
                    "AND qty > 0", [pf_id]).fetchone()[0]
                n_fills = con.execute(
                    "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
                    [pf_id]).fetchone()[0]
                rows.append({
                    "id": pf_id, "name": name, "inception": created,
                    "equity": equity, "total_ret": total_ret, "vs_spy": vs_spy,
                    "mdd": mdd, "n_open": n_open, "n_fills": n_fills,
                    "last5": last5,
                })
        rows.sort(key=lambda r: r["total_ret"], reverse=True)
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return {"as_of": d, "regime": regime_label(con, d),
                "reference_notional": INITIAL_CASH, "rows": rows}
    finally:
        con.close()


@app.get("/league/{portfolio_id}/equity")
def league_equity(portfolio_id: str):
    con = read_con()
    try:
        if not _table_exists(con, "sim_equity"):
            return {"portfolio_id": portfolio_id, "equity": []}
        rows = _rows(con.execute(
            "SELECT portfolio_id, date, equity, cash, n_positions FROM sim_equity "
            "WHERE portfolio_id = ? ORDER BY date", [portfolio_id]))
        if not rows:
            raise HTTPException(404, f"no equity for {portfolio_id}")
        return {"portfolio_id": portfolio_id, "equity": rows}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# candidates
# --------------------------------------------------------------------------- #
@app.get("/candidates/{ticker}")
def candidate(ticker: str):
    ticker = ticker.upper()
    con = read_con()
    try:
        bars = _rows(con.execute(
            "SELECT date, open, high, low, close, volume FROM (   "
            "  SELECT date, open, high, low, close, volume FROM prices "
            "  WHERE ticker = ? ORDER BY date DESC LIMIT 250"
            ") ORDER BY date", [ticker]))
        if not bars:
            raise HTTPException(404, f"no price bars for {ticker}")
        screen = _rows(con.execute(
            "SELECT * FROM screen_results WHERE ticker = ? "
            "ORDER BY run_date DESC LIMIT 1", [ticker]))
        screen_row = screen[0] if screen else None
        latest_close = bars[-1]["close"]
        return {"ticker": ticker, "n_bars": len(bars), "bars": bars,
                "latest_close": latest_close, "screen": screen_row}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# positions
# --------------------------------------------------------------------------- #
@app.get("/positions")
def positions(portfolio: str | None = Query(None)):
    con = read_con()
    try:
        if not _table_exists(con, "sim_positions"):
            return {"portfolio": portfolio, "positions": []}
        if portfolio:
            q = ("SELECT portfolio_id, ticker, qty, avg_cost FROM sim_positions "
                 "WHERE portfolio_id = ? AND qty > 0 ORDER BY ticker")
            raw = con.execute(q, [portfolio]).fetchall()
        else:
            q = ("SELECT portfolio_id, ticker, qty, avg_cost FROM sim_positions "
                 "WHERE qty > 0 ORDER BY portfolio_id, ticker")
            raw = con.execute(q).fetchall()
        out = []
        for pf_id, tk, qty, avg in raw:
            close = risk._latest_close(con, tk)
            rec = {"portfolio_id": pf_id, "ticker": tk, "qty": qty,
                   "avg_cost": avg, "close": close}
            if close is not None:
                rec["market_value"] = qty * close
                rec["unrealized_pnl"] = qty * (close - avg)
                rec["unrealized_pnl_pct"] = (close - avg) / avg if avg else None
            if pf_id == DISC_ID:
                stop = risk.latest_stop_for(con, tk)
                rec["stop"] = stop
                if stop is not None and close is not None:
                    rec["dist_to_stop_pct"] = (close - stop) / close
                    rps = avg - stop
                    rec["unrealized_r"] = ((close - avg) / rps) if rps else None
            out.append(rec)
        return {"portfolio": portfolio, "positions": out}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# orders
# --------------------------------------------------------------------------- #
@app.get("/orders")
def orders(status: str | None = Query(None)):
    con = read_con()
    try:
        if not _table_exists(con, "sim_orders"):
            return {"status": status, "orders": []}
        has_t = _table_exists(con, "disc_tickets")
        sel = ("o.*, t.id AS ticket_id, t.playbook, t.stop, t.target "
               "FROM sim_orders o LEFT JOIN disc_tickets t ON t.order_id = o.id"
               ) if has_t else "o.* FROM sim_orders o"
        if status:
            cur = con.execute(
                f"SELECT {sel} WHERE o.status = ? ORDER BY o.id DESC", [status])
        else:
            cur = con.execute(f"SELECT {sel} ORDER BY o.id DESC LIMIT 500")
        return {"status": status, "orders": _rows(cur)}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# journal
# --------------------------------------------------------------------------- #
@app.get("/journal")
def journal():
    con = read_con()
    try:
        tickets = _rows(con.execute(
            "SELECT * FROM disc_tickets ORDER BY created_at DESC, id DESC"
        )) if _table_exists(con, "disc_tickets") else []
        for t in tickets:
            if t.get("gates"):
                try:
                    t["gates"] = json.loads(t["gates"])
                except Exception:
                    pass
            if t.get("order_id") is not None:
                t["fills"] = _rows(con.execute(
                    "SELECT ticker, side, qty, fill_date, fill_px FROM sim_fills "
                    "WHERE order_id = ? ORDER BY fill_date", [t["order_id"]]))
            else:
                t["fills"] = []
        round_trips = risk.closed_round_trips(con)
        league_events = _rows(con.execute(
            "SELECT order_id, portfolio_id, ticker, side, qty, fill_date, fill_px "
            "FROM sim_fills ORDER BY fill_date DESC, order_id DESC LIMIT 100"
        )) if _table_exists(con, "sim_fills") else []
        return {"discretionary": {"tickets": tickets, "round_trips": round_trips},
                "league_events": league_events}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# tickets (write)
# --------------------------------------------------------------------------- #
def _ensure_disc_portfolio(con, as_of: date) -> None:
    exists = con.execute(
        "SELECT 1 FROM portfolios WHERE id = ?", [DISC_ID]).fetchone()
    if not exists:
        con.execute(
            "INSERT INTO portfolios (id, name, strategy, config, created, active, "
            "cash) VALUES (?, ?, ?, ?, ?, TRUE, ?)",
            [DISC_ID, "Discretionary (paper)", "discretionary",
             json.dumps({"kind": "discretionary"}), as_of, INITIAL_CASH],
        )


@app.post("/tickets")
def create_ticket(body: dict = Body(...)):
    ticker = (body.get("ticker") or "").upper().strip()
    side = (body.get("side") or "buy").lower().strip()
    if not ticker:
        raise HTTPException(400, "ticker required")

    con = write_con()
    try:
        init_sim_schema(con)  # ensure disc_tickets/audit_log/review_markers exist
        as_of = _latest_prices_date(con)
        if as_of is None:
            raise HTTPException(503, "no price data")
        _ensure_disc_portfolio(con, as_of)

        ticket = {
            "ticker": ticker, "side": side,
            "qty": float(body.get("qty") or 0),
            "entry_ref": body.get("entry_ref"),
            "stop": body.get("stop"),
            "target": body.get("target"),
            "playbook": body.get("playbook"),
            "emotion": body.get("emotion"),
            "notes": body.get("notes"),
            "acknowledge_earnings": bool(body.get("acknowledge_earnings")),
            "override_regime": bool(body.get("override_regime")),
            "override_reason": body.get("override_reason"),
        }

        # v1: shorts unsupported. A 'sell' is valid only to close an open position.
        if side == "sell":
            pos = con.execute(
                "SELECT qty FROM sim_positions WHERE portfolio_id = ? AND ticker = ? "
                "AND qty > 0", [DISC_ID, ticker]).fetchone()
            if not pos or pos[0] < ticket["qty"]:
                _audit(con, "ticket_reject_short", ticket)
                raise HTTPException(
                    400, "shorts unsupported v1; sell only closes an open position")
            gates = [{"name": "closing_order", "status": "pass",
                      "detail": "sell closes existing long position"}]
            allowed, reasons = True, []
        else:
            gates = risk.evaluate_gates(con, ticket)
            allowed, reasons = risk.is_allowed(gates, ticket)

        tid = con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM disc_tickets").fetchone()[0]
        order_id = None
        status = "rejected"

        if allowed:
            order_id = con.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0]
            con.execute(
                "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty, "
                "signal_date, status, reject_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
                [order_id, DISC_ID, ticker, side, ticket["qty"], as_of])
            status = "submitted"

        con.execute(
            "INSERT INTO disc_tickets (id, ticker, side, qty, entry_ref, stop, "
            "target, playbook, emotion, notes, gates, status, order_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tid, ticker, side, ticket["qty"], ticket["entry_ref"], ticket["stop"],
             ticket["target"], ticket["playbook"], ticket["emotion"],
             ticket["notes"], json.dumps(gates, default=str), status, order_id,
             _now()])

        _audit(con, "ticket_submit", {"ticket_id": tid, "status": status,
                                      "order_id": order_id, "allowed": allowed,
                                      "ticket": ticket})
        return {"ticket_id": tid, "allowed": allowed, "status": status,
                "order_id": order_id, "signal_date": as_of, "gates": gates,
                "reasons": reasons}
    finally:
        con.close()


@app.post("/tickets/{ticket_id}/cancel")
def cancel_ticket(ticket_id: int):
    con = write_con()
    try:
        row = con.execute(
            "SELECT status, order_id FROM disc_tickets WHERE id = ?",
            [ticket_id]).fetchone()
        if row is None:
            raise HTTPException(404, f"no ticket {ticket_id}")
        t_status, order_id = row
        if order_id is None:
            raise HTTPException(409, f"ticket {ticket_id} has no order (was rejected)")
        o = con.execute(
            "SELECT status FROM sim_orders WHERE id = ?", [order_id]).fetchone()
        if o is None or o[0] != "pending":
            raise HTTPException(
                409, f"order {order_id} not pending (status "
                     f"{o[0] if o else 'missing'}) — cannot cancel")
        con.execute("UPDATE sim_orders SET status = 'cancelled', "
                    "reject_reason = 'cancelled by user' WHERE id = ?", [order_id])
        con.execute("UPDATE disc_tickets SET status = 'cancelled' WHERE id = ?",
                    [ticket_id])
        _audit(con, "ticket_cancel", {"ticket_id": ticket_id, "order_id": order_id})
        return {"ticket_id": ticket_id, "order_id": order_id, "status": "cancelled"}
    finally:
        con.close()


@app.post("/review-done")
def review_done():
    con = write_con()
    try:
        init_sim_schema(con)
        ts = _now()
        con.execute("INSERT INTO review_markers (ts, kind) VALUES (?, ?)",
                    [ts, "circuit_breaker"])
        _audit(con, "review_done", {"kind": "circuit_breaker", "ts": str(ts)})
        return {"ok": True, "kind": "circuit_breaker", "ts": ts,
                "detail": "circuit breaker cleared"}
    finally:
        con.close()
