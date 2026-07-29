"""Position / cash accounting and mark-to-market.

sim_positions and portfolios.cash are current state; sim_equity is append-only.
State can always be reconstructed from sim_fills (`rebuild_state`) — that replay
is how `--rerun` restores exact cash/positions after deleting a date's rows.
"""
from __future__ import annotations

import math
from datetime import date

import duckdb

from .schema import INITIAL_CASH


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def get_positions(con: duckdb.DuckDBPyConnection, pf_id: str) -> dict[str, dict]:
    """{ticker: {'qty': float, 'avg_cost': float}} for open positions (qty != 0).

    Filter is `qty != 0` (not `qty > 0`) so any nonzero position — including an
    accidental short — always counts in mark-to-market and the strategy view,
    rather than silently vanishing (belt-and-braces for the apply_fill sell guard).
    """
    rows = con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty != 0",
        [pf_id],
    ).fetchall()
    return {t: {"qty": q, "avg_cost": c} for t, q, c in rows}


def get_cash(con: duckdb.DuckDBPyConnection, pf_id: str) -> float:
    return float(con.execute(
        "SELECT cash FROM portfolios WHERE id = ?", [pf_id]
    ).fetchone()[0])


def position_open_since(con: duckdb.DuckDBPyConnection, pf_id: str, ticker: str):
    """The fill_date the current open lot was opened on: the earliest buy after
    the most recent sell (or ever, if never sold). None if no buys. Used for the
    MR time stop.

    ORDER BY … LIMIT 1 instead of MIN/MAX on purpose: DuckDB 1.5.4 has an
    internal error ("Attempted to access index 0 within vector of size 0") when
    a MIN/MAX aggregate WITH a WHERE clause scans rows appended earlier in the
    SAME transaction — exactly what happens here, since the league day-step is
    one transaction and fill_pending appends to sim_fills before strategies run.
    Plain filtered scans and ORDER BY/LIMIT are unaffected. Don't "simplify"
    these back to MIN/MAX while the engine is on 1.5.x.
    """
    row = con.execute(
        "SELECT fill_date FROM sim_fills "
        "WHERE portfolio_id = ? AND ticker = ? AND side = 'sell' "
        "ORDER BY fill_date DESC LIMIT 1",
        [pf_id, ticker],
    ).fetchone()
    last_sell = row[0] if row else None
    if last_sell is None:
        row = con.execute(
            "SELECT fill_date FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy' "
            "ORDER BY fill_date ASC LIMIT 1",
            [pf_id, ticker],
        ).fetchone()
    else:
        row = con.execute(
            "SELECT fill_date FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy' AND fill_date > ? "
            "ORDER BY fill_date ASC LIMIT 1",
            [pf_id, ticker, last_sell],
        ).fetchone()
    return row[0] if row else None


def close_on(con: duckdb.DuckDBPyConnection, ticker: str, d: date):
    """(close, is_carried): the close on/last-known before d. Carried if the
    exact date's bar is missing (never fabricated — the last real close stands)."""
    exact = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date = ?", [ticker, d]
    ).fetchone()
    if exact is not None and exact[0] is not None:
        return float(exact[0]), False
    row = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        [ticker, d],
    ).fetchone()
    if row is None or row[0] is None:
        return None, True
    return float(row[0]), True


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
def apply_fill(con: duckdb.DuckDBPyConnection, fill: dict) -> float:
    """Apply one fill to sim_positions + portfolios.cash. `fill` carries
    portfolio_id, ticker, side, qty, fill_px.

    Returns the qty ACTUALLY applied, which may be less than the requested qty:

    - Sells are close-only: if the requested qty exceeds the held qty it is
      clamped to the held qty (never go negative) and a WARN is printed.
    - Buys are cash-bounded: if the notional exceeds available cash the qty is
      reduced to floor(cash / fill_px) so cash never goes negative (no phantom
      leverage from a signal-day → next-open gap-up). If that floors to 0 the
      fill is rejected (returns 0.0, nothing written) and a WARN is printed.

    A return of 0.0 means nothing was applied — the caller must not record a
    sim_fills row and should mark the order rejected. Callers that record a
    sim_fills row MUST use the returned qty so the fill log and order status
    reflect what actually happened.
    """
    pf_id, tk = fill["portfolio_id"], fill["ticker"]
    qty, px, side = fill["qty"], fill["fill_px"], fill["side"]
    row = con.execute(
        "SELECT qty, avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [pf_id, tk],
    ).fetchone()
    cur_qty, cur_cost = (row[0], row[1]) if row else (0.0, 0.0)

    if side == "buy":
        cash = get_cash(con, pf_id)
        if px > 0 and qty * px > cash:
            affordable = math.floor(cash / px) if cash > 0 else 0
            if affordable <= 0:
                print(f"[apply_fill] WARN insufficient_cash: {pf_id} {tk} buy "
                      f"{qty} @ {px:.4f} (notional ${qty * px:,.2f} > cash "
                      f"${cash:,.2f}) — fill rejected")
                return 0.0
            print(f"[apply_fill] WARN cash-clamp: {pf_id} {tk} buy {qty} → "
                  f"{affordable} @ {px:.4f} (cash ${cash:,.2f})")
            qty = float(affordable)
        new_qty = cur_qty + qty
        new_cost = ((cur_qty * cur_cost) + (qty * px)) / new_qty if new_qty else 0.0
        con.execute("UPDATE portfolios SET cash = cash - ? WHERE id = ?",
                    [qty * px, pf_id])
    else:  # sell — close-only, never go short
        if qty > cur_qty:
            print(f"[apply_fill] WARN sell-clamp: {pf_id} {tk} sell {qty} > held "
                  f"{cur_qty} → {cur_qty} (close-only)")
            qty = cur_qty
        if qty <= 0:
            return 0.0
        new_qty = cur_qty - qty
        new_cost = cur_cost  # realized P&L falls out of cash; avg_cost unchanged
        con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                    [qty * px, pf_id])

    if row:
        con.execute(
            "UPDATE sim_positions SET qty = ?, avg_cost = ? "
            "WHERE portfolio_id = ? AND ticker = ?",
            [new_qty, new_cost, pf_id, tk],
        )
    else:
        con.execute(
            "INSERT INTO sim_positions (portfolio_id, ticker, qty, avg_cost) "
            "VALUES (?, ?, ?, ?)",
            [pf_id, tk, new_qty, new_cost],
        )
    return float(qty)


def mark_to_market(con: duckdb.DuckDBPyConnection, pf_id: str, d: date) -> dict:
    """Value a portfolio at d's close and append a sim_equity row.

    equity = cash + Σ qty*close; a missing close carries the last known close
    (flagged in the returned dict). Idempotent per (portfolio, date) via the PK
    — callers guard against re-running a date at the league level.
    """
    cash = get_cash(con, pf_id)
    positions = get_positions(con, pf_id)
    mkt = 0.0
    carried = []
    for tk, p in positions.items():
        close, is_carried = close_on(con, tk, d)
        if close is None:
            carried.append(tk)  # no price at all — contributes 0, flagged
            continue
        if is_carried:
            carried.append(tk)
        mkt += p["qty"] * close
    equity = cash + mkt
    n_pos = len(positions)
    con.execute(
        "INSERT OR REPLACE INTO sim_equity "
        "(portfolio_id, date, equity, cash, n_positions) VALUES (?, ?, ?, ?, ?)",
        [pf_id, d, equity, cash, n_pos],
    )
    return {"equity": equity, "cash": cash, "n_positions": n_pos, "carried": carried}


# --------------------------------------------------------------------------- #
# corporate actions
# --------------------------------------------------------------------------- #
def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] > 0


def credit_dividends(con: duckdb.DuckDBPyConnection, d: date) -> dict:
    """Phase a0 of the league day-step: pay every cash dividend going ex on `d`.

    Entitlement is the position held at the close of d−1 — which is exactly the
    current sim_positions state, because this runs BEFORE the day's fills. For
    each active portfolio and each held name with a `corporate_actions` dividend
    row on `d`: cash += qty × dps, and one append-only sim_dividends row.

    Returns {'credited': n_rows, 'amount': total_cash}. A store without a
    corporate_actions table (an old copy) credits nothing rather than failing.
    """
    out = {"credited": 0, "amount": 0.0}
    if not _has_table(con, "corporate_actions"):
        return out
    divs = con.execute(
        "SELECT ticker, value FROM corporate_actions "
        "WHERE kind = 'dividend' AND ex_date = ?", [d]
    ).fetchall()
    if not divs:
        return out
    dps_by_ticker = {tk: float(v) for tk, v in divs if v is not None and v > 0}
    if not dps_by_ticker:
        return out

    for (pf_id,) in con.execute(
        "SELECT id FROM portfolios WHERE active ORDER BY id"
    ).fetchall():
        for tk, qty in con.execute(
            "SELECT ticker, qty FROM sim_positions "
            "WHERE portfolio_id = ? AND qty > 0 ORDER BY ticker", [pf_id]
        ).fetchall():
            dps = dps_by_ticker.get(tk)
            if dps is None:
                continue
            amount = float(qty) * dps
            con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                        [amount, pf_id])
            con.execute(
                "INSERT OR REPLACE INTO sim_dividends "
                "(portfolio_id, ticker, ex_date, qty, dps, amount) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [pf_id, tk, d, float(qty), dps, amount],
            )
            out["credited"] += 1
            out["amount"] += amount
    return out


def _split_factors(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[date, float]]]:
    """{ticker: [(ex_date, ratio), …]} for splits the reconciler actually APPLIED.

    A fill that happened BEFORE a split's ex-date was executed at pre-split
    prices, so replaying it verbatim would rebuild a pre-split share count. The
    boundary here is the ex_date (economics), deliberately NOT the storage
    break_date the price restatement used (see engine/actions.py).
    """
    if not _has_table(con, "split_adjustments"):
        return {}
    out: dict[str, list[tuple[date, float]]] = {}
    for tk, ex, ratio in con.execute(
        "SELECT ticker, ex_date, ratio FROM split_adjustments "
        "WHERE outcome = 'applied' AND ratio IS NOT NULL AND ratio > 0"
    ).fetchall():
        out.setdefault(tk, []).append((ex, float(ratio)))
    return out


# --------------------------------------------------------------------------- #
# reconstruction (used by --rerun)
# --------------------------------------------------------------------------- #
def rebuild_state(con: duckdb.DuckDBPyConnection) -> None:
    """Replay every surviving sim_fill + sim_dividend to recompute sim_positions
    and cash exactly.

    Cash starts at INITIAL_CASH per portfolio; events are replayed in date order
    with dividends BEFORE fills within a date — the SAME order the live day-step
    applies them (phase a0 then phase a), so the cash-bounded buy clamp in
    apply_fill sees an identical cash trajectory and never re-clamps a stored
    fill. Fills within a date keep the live (sells-before-buys, order_id) order.
    This makes state a pure function of (sim_fills, sim_dividends).

    Splits: a fill recorded before an APPLIED split's ex-date is replayed with
    qty × ratio and fill_px ÷ ratio. Notional (and therefore the cash trajectory)
    is unchanged, while the rebuilt share count and avg_cost land on the current,
    post-split scale — without this, any --rerun after a split would silently
    revert the reconciler's position adjustment. Dividends are replayed at their
    RECORDED amount: the cash was received at the share count of the day, and a
    later split does not retroactively change what was paid.
    """
    pf_ids = [r[0] for r in con.execute("SELECT id FROM portfolios").fetchall()]
    con.execute("DELETE FROM sim_positions")
    for pf_id in pf_ids:
        con.execute("UPDATE portfolios SET cash = ? WHERE id = ?",
                    [INITIAL_CASH, pf_id])

    splits = _split_factors(con)

    # (date, phase, seq, kind, payload) — phase 0 = dividends, 1 = fills.
    events: list[tuple] = []
    if _has_table(con, "sim_dividends"):
        for i, (pf_id, tk, ex, amount) in enumerate(con.execute(
            "SELECT portfolio_id, ticker, ex_date, amount FROM sim_dividends "
            "ORDER BY ex_date, portfolio_id, ticker"
        ).fetchall()):
            events.append((ex, 0, i, "div", (pf_id, tk, float(amount))))
    for i, (pf_id, tk, side, qty, px, fd, oid) in enumerate(con.execute(
        "SELECT portfolio_id, ticker, side, qty, fill_px, fill_date, order_id "
        "FROM sim_fills "
        "ORDER BY fill_date, CASE side WHEN 'sell' THEN 0 ELSE 1 END, order_id"
    ).fetchall()):
        events.append((fd, 1, i, "fill", (pf_id, tk, side, qty, px, fd)))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    for _d, _phase, _seq, kind, payload in events:
        if kind == "div":
            pf_id, _tk, amount = payload
            con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                        [amount, pf_id])
            continue
        pf_id, tk, side, qty, px, fd = payload
        factor = 1.0
        for ex, ratio in splits.get(tk, ()):
            if fd < ex:
                factor *= ratio
        apply_fill(con, {"portfolio_id": pf_id, "ticker": tk, "side": side,
                         "qty": qty * factor, "fill_px": px / factor})
