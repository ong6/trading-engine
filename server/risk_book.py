"""Read-only discretionary-book valuation and open-risk accounting."""

from __future__ import annotations

from datetime import date

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.util import table_exists
from sim.schema import INITIAL_CASH

from .market_read_models import latest_prices_date

DISC_ID = "discretionary"
RISK_PCT = 0.01


def latest_real_quote(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    as_of: date | None = None,
) -> tuple[date, float] | None:
    date_clause = "" if as_of is None else "AND date <= ? "
    params = [ticker] if as_of is None else [ticker, as_of]
    row = con.execute(
        f"SELECT date, close FROM prices WHERE ticker = ? {date_clause}AND {REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 1",
        params,
    ).fetchone()
    return None if row is None or row[1] is None else (row[0], float(row[1]))


def latest_close(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    as_of: date | None = None,
) -> float | None:
    quote = latest_real_quote(con, ticker, as_of=as_of)
    return None if quote is None else quote[1]


def latest_stop_for(con: duckdb.DuckDBPyConnection, ticker: str) -> float | None:
    """Stop from the most recent submitted/filled disc ticket for this ticker."""
    if not table_exists(con, "disc_tickets"):
        return None
    row = con.execute(
        "SELECT stop FROM disc_tickets WHERE ticker = ? AND stop IS NOT NULL "
        "AND status IN ('submitted', 'filled') ORDER BY created_at DESC, id DESC "
        "LIMIT 1",
        [ticker],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def _quote_cte(as_of: date | None) -> str:
    if as_of is None:
        return "quotes AS (SELECT NULL::VARCHAR AS ticker, NULL::DOUBLE AS close WHERE FALSE)"
    return (
        "quotes AS ("
        "SELECT ticker, close FROM ("
        "SELECT px.ticker, px.close, ROW_NUMBER() OVER ("
        "PARTITION BY px.ticker ORDER BY px.date DESC) AS recency "
        "FROM prices px JOIN held h ON h.ticker = px.ticker "
        f"WHERE px.date <= ? AND {REAL_BAR_SQL}"
        ") WHERE recency = 1"
        ")"
    )


def _stop_cte(con: duckdb.DuckDBPyConnection) -> str:
    if not table_exists(con, "disc_tickets"):
        return "stops AS (SELECT NULL::VARCHAR AS ticker, NULL::DOUBLE AS stop WHERE FALSE)"
    return (
        "stops AS ("
        "SELECT ticker, stop FROM ("
        "SELECT t.ticker, t.stop, ROW_NUMBER() OVER ("
        "PARTITION BY t.ticker ORDER BY t.created_at DESC, t.id DESC) AS recency "
        "FROM disc_tickets t JOIN held h ON h.ticker = t.ticker "
        "WHERE t.stop IS NOT NULL AND t.status IN ('submitted', 'filled')"
        ") WHERE recency = 1"
        ")"
    )


def _disc_positions(
    con: duckdb.DuckDBPyConnection,
    as_of: date | None,
) -> list[tuple]:
    """Load held positions, current marks, and stops with a fixed query count."""
    params = [DISC_ID] if as_of is None else [DISC_ID, as_of]
    return con.execute(
        "WITH held AS ("
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty > 0"
        f"), {_quote_cte(as_of)}, {_stop_cte(con)} "
        "SELECT h.ticker, h.qty, h.avg_cost, s.stop, q.close FROM held h "
        "LEFT JOIN stops s ON s.ticker = h.ticker "
        "LEFT JOIN quotes q ON q.ticker = h.ticker "
        "ORDER BY h.ticker",
        params,
    ).fetchall()


def _active_disc_book(con: duckdb.DuckDBPyConnection) -> tuple[float, float] | None:
    portfolio_cols = {r[1] for r in con.execute("PRAGMA table_info('portfolios')").fetchall()}
    initial_expr = "COALESCE(initial_cash, ?)" if "initial_cash" in portfolio_cols else "?"
    row = con.execute(
        f"SELECT cash, {initial_expr} FROM portfolios WHERE id = ? AND active",
        [INITIAL_CASH, DISC_ID],
    ).fetchone()
    return None if row is None else (float(row[0]), float(row[1]))


def _marked_positions(rows: list[tuple]) -> tuple[list[dict], float]:
    positions = []
    market_value = 0.0
    for ticker, qty, avg_cost, stop, close in rows:
        if close is not None:
            market_value += qty * close
        positions.append(
            {
                "ticker": ticker,
                "qty": float(qty),
                "avg_cost": float(avg_cost),
                "stop": None if stop is None else float(stop),
                "close": None if close is None else float(close),
            }
        )
    return positions, market_value


def disc_state(con: duckdb.DuckDBPyConnection, *, as_of: date | None = None) -> dict:
    """Return current discretionary cash, equity, and marked positions."""
    if as_of is None:
        as_of = latest_prices_date(con)
    book = _active_disc_book(con)
    if book is None:
        return {
            "exists": False,
            "cash": INITIAL_CASH,
            "equity": INITIAL_CASH,
            "positions": [],
        }
    cash, initial_cash = book
    positions, market_value = _marked_positions(_disc_positions(con, as_of))
    return {
        "exists": True,
        "cash": cash,
        "initial_cash": initial_cash,
        "equity": cash + market_value,
        "positions": positions,
    }


def pending_disc_risk(con: duckdb.DuckDBPyConnection) -> float:
    """Return risk committed by accepted, unfilled discretionary buy orders."""
    if not table_exists(con, "sim_orders") or not table_exists(con, "disc_tickets"):
        return 0.0
    rows = con.execute(
        "SELECT o.qty, t.entry_ref, t.stop FROM sim_orders o "
        "JOIN disc_tickets t ON t.order_id = o.id "
        "WHERE o.portfolio_id = ? AND o.status = 'pending' AND o.side = 'buy'",
        [DISC_ID],
    ).fetchall()
    total = 0.0
    for qty, entry, stop in rows:
        if qty is None or entry is None or stop is None:
            continue
        total += max(0.0, float(qty) * (float(entry) - float(stop)))
    return total


def open_disc_risk(con: duckdb.DuckDBPyConnection, state: dict) -> float:
    """Return marked position risk plus accepted, unfilled order risk."""
    one_r = RISK_PCT * state["equity"]
    total = 0.0
    for position in state["positions"]:
        if position["stop"] is not None:
            total += max(
                0.0,
                position["qty"] * (position["avg_cost"] - position["stop"]),
            )
        else:
            total += one_r
    return total + pending_disc_risk(con)
