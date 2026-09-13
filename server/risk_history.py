"""Realized discretionary round trips and circuit-breaker state."""

from __future__ import annotations

from collections import defaultdict, deque

import duckdb

from engine.lib.util import table_exists

from .risk_book import DISC_ID

CB_CONSEC_LOSERS = 3
CB_R_WINDOW_DAYS = 5
CB_R_FLOOR = -5.0
FILL_SCAN_BATCH_SIZE = 256


def _fill_rows(con: duckdb.DuckDBPyConnection):
    """Stream discretionary fills without materializing the complete ledger."""
    if not table_exists(con, "disc_tickets"):
        return
    cursor = con.execute(
        "WITH ticket_risk AS ("
        "SELECT order_id, entry_ref, stop FROM ("
        "SELECT order_id, entry_ref, stop, ROW_NUMBER() OVER ("
        "PARTITION BY order_id ORDER BY id DESC) AS recency "
        "FROM disc_tickets WHERE order_id IS NOT NULL"
        ") WHERE recency = 1"
        ") SELECT f.order_id, f.ticker, f.side, f.qty, f.fill_date, f.fill_px, "
        "t.entry_ref, t.stop FROM sim_fills f "
        "LEFT JOIN ticket_risk t ON t.order_id = f.order_id "
        "WHERE f.portfolio_id = ? ORDER BY f.fill_date, f.order_id",
        [DISC_ID],
    )
    while batch := cursor.fetchmany(FILL_SCAN_BATCH_SIZE):
        yield from batch


def _risk_per_share(entry_ref, stop):
    if entry_ref is None or stop is None or entry_ref <= stop:
        return None
    return entry_ref - stop


def _realized_r(pnl_per_share: float, risk_per_share) -> float:
    if risk_per_share:
        return pnl_per_share / risk_per_share
    return 1.0 if pnl_per_share > 0 else (-1.0 if pnl_per_share < 0 else 0.0)


def _matched_sale(lots: deque[dict], qty, fill_date, fill_price):
    remaining = float(qty)
    exit_price = float(fill_price)
    while remaining > 1e-9 and lots:
        lot = lots[0]
        take = min(remaining, lot["qty"])
        yield {
            "qty": take,
            "entry_px": lot["px"],
            "exit_px": exit_price,
            "exit_date": fill_date,
            "realized_r": _realized_r(exit_price - lot["px"], lot["rps"]),
        }
        lot["qty"] -= take
        remaining -= take
        if lot["qty"] <= 1e-9:
            lots.popleft()


def iter_closed_round_trips(con: duckdb.DuckDBPyConnection):
    """Yield FIFO-matched discretionary round trips in exit order."""
    lots: defaultdict[str, deque[dict]] = defaultdict(deque)
    for _order_id, ticker, side, qty, fill_date, fill_price, entry_ref, stop in _fill_rows(con):
        if side == "buy":
            lots[ticker].append(
                {
                    "qty": float(qty),
                    "px": float(fill_price),
                    "rps": _risk_per_share(entry_ref, stop),
                }
            )
            continue
        for trip in _matched_sale(lots[ticker], qty, fill_date, fill_price):
            yield {"ticker": ticker, **trip}


def closed_round_trips(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Return complete FIFO-matched history for analysis and compatibility."""
    return list(iter_closed_round_trips(con))


def recent_round_trips(
    con: duckdb.DuckDBPyConnection,
    limit: int,
) -> tuple[list[dict], int]:
    """Return newest matched trips and an exact complete-history count."""
    recent = deque(maxlen=limit)
    matching_count = 0
    for trip in iter_closed_round_trips(con):
        recent.append(trip)
        matching_count += 1
    return list(reversed(recent)), matching_count


def _review_marker(con: duckdb.DuckDBPyConnection):
    return (
        con.execute("SELECT MAX(ts) FROM review_markers WHERE kind = 'circuit_breaker'").fetchone()[
            0
        ]
        if table_exists(con, "review_markers")
        else None
    )


def _window_cutoff(con: duckdb.DuckDBPyConnection):
    cutoff_error = None
    try:
        cutoff = con.execute(
            "SELECT MIN(date) FROM (SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT ?)",
            [CB_R_WINDOW_DAYS],
        ).fetchone()[0]
    except duckdb.Error as exc:
        # Preserve the empty-history behavior even when a partial schema lacks
        # prices. A real closed trip still requires the trailing-session gate.
        cutoff = None
        cutoff_error = exc
    return cutoff, cutoff_error


def _breaker_history(con: duckdb.DuckDBPyConnection, marker, cutoff):
    last_three = deque(maxlen=CB_CONSEC_LOSERS)
    realized_r = 0.0
    matching_count = 0
    for trip in iter_closed_round_trips(con):
        if marker is not None and trip["exit_date"] <= marker.date():
            continue
        matching_count += 1
        last_three.append(trip)
        if cutoff is not None and trip["exit_date"] >= cutoff:
            realized_r += trip["realized_r"]
    return last_three, realized_r, matching_count


def _breaker_result(last_three: deque[dict], realized_r: float) -> dict:
    if len(last_three) == CB_CONSEC_LOSERS and all(trip["realized_r"] < 0 for trip in last_three):
        return {
            "status": "fail",
            "detail": f"{CB_CONSEC_LOSERS} consecutive losing round-trips",
        }
    if realized_r <= CB_R_FLOOR:
        return {
            "status": "fail",
            "detail": f"realized {realized_r:.1f}R in trailing "
            f"{CB_R_WINDOW_DAYS}d (≤ {CB_R_FLOOR:.0f}R)",
        }
    return {
        "status": "pass",
        "detail": f"ok — {realized_r:.1f}R in trailing {CB_R_WINDOW_DAYS}d, "
        f"last {len(last_three)} not all losers",
    }


def circuit_breaker(con: duckdb.DuckDBPyConnection) -> dict:
    """Evaluate consecutive-loss and trailing-realized-R breaker rules."""
    cutoff, cutoff_error = _window_cutoff(con)
    last_three, realized_r, matching_count = _breaker_history(con, _review_marker(con), cutoff)
    if matching_count == 0:
        return {"status": "pass", "detail": "no closed discretionary round-trips"}
    if cutoff_error is not None:
        raise cutoff_error
    if cutoff is None:
        raise ValueError("cannot evaluate circuit breaker without a price-session window")
    return _breaker_result(last_three, realized_r)
