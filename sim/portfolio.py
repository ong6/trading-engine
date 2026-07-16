"""Position / cash accounting and mark-to-market.

sim_positions and portfolios.cash are current state; sim_equity is append-only.
State can always be reconstructed from sim_fills (`rebuild_state`) — that replay
is how `--rerun` restores exact cash/positions after deleting a date's rows.
"""
from __future__ import annotations

from datetime import date

import duckdb

from .schema import INITIAL_CASH


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def get_positions(con: duckdb.DuckDBPyConnection, pf_id: str) -> dict[str, dict]:
    """{ticker: {'qty': float, 'avg_cost': float}} for open positions (qty != 0)."""
    rows = con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty > 0",
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
    MR time stop."""
    last_sell = con.execute(
        "SELECT MAX(fill_date) FROM sim_fills "
        "WHERE portfolio_id = ? AND ticker = ? AND side = 'sell'",
        [pf_id, ticker],
    ).fetchone()[0]
    if last_sell is None:
        row = con.execute(
            "SELECT MIN(fill_date) FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy'",
            [pf_id, ticker],
        ).fetchone()
    else:
        row = con.execute(
            "SELECT MIN(fill_date) FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy' AND fill_date > ?",
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
def apply_fill(con: duckdb.DuckDBPyConnection, fill: dict) -> None:
    """Apply one fill to sim_positions + portfolios.cash. `fill` carries
    portfolio_id, ticker, side, qty, fill_px."""
    pf_id, tk = fill["portfolio_id"], fill["ticker"]
    qty, px, side = fill["qty"], fill["fill_px"], fill["side"]
    row = con.execute(
        "SELECT qty, avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [pf_id, tk],
    ).fetchone()
    cur_qty, cur_cost = (row[0], row[1]) if row else (0.0, 0.0)

    if side == "buy":
        new_qty = cur_qty + qty
        new_cost = ((cur_qty * cur_cost) + (qty * px)) / new_qty if new_qty else 0.0
        con.execute("UPDATE portfolios SET cash = cash - ? WHERE id = ?",
                    [qty * px, pf_id])
    else:  # sell
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
# reconstruction (used by --rerun)
# --------------------------------------------------------------------------- #
def rebuild_state(con: duckdb.DuckDBPyConnection) -> None:
    """Replay every surviving sim_fill to recompute sim_positions + cash exactly.

    Cash starts at INITIAL_CASH per portfolio; fills are replayed in
    (fill_date, order_id) order. This makes state a pure function of the fill
    log, so deleting a date's fills and rebuilding restores prior state exactly.
    """
    pf_ids = [r[0] for r in con.execute("SELECT id FROM portfolios").fetchall()]
    con.execute("DELETE FROM sim_positions")
    for pf_id in pf_ids:
        con.execute("UPDATE portfolios SET cash = ? WHERE id = ?",
                    [INITIAL_CASH, pf_id])
    fills = con.execute(
        "SELECT portfolio_id, ticker, side, qty, fill_px FROM sim_fills "
        "ORDER BY fill_date, order_id"
    ).fetchall()
    for pf_id, tk, side, qty, px in fills:
        apply_fill(con, {"portfolio_id": pf_id, "ticker": tk, "side": side,
                         "qty": qty, "fill_px": px})
