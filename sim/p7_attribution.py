"""Read-only P7 validation over generic simulator economic ledgers."""

from __future__ import annotations

import math
from datetime import date

from engine.lib.util import table_exists


class SimulatorAttributionError(ValueError):
    """P7 simulator rows are incomplete or inconsistent."""


def _number(value, field, positive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or (positive and value <= 0)
    ):
        raise SimulatorAttributionError(f"P7 attribution {field} is invalid")
    return float(value)


def _orders(con, books, limit):
    ids, marks = list(books), ",".join("?" for _ in books)
    rows = con.execute(
        f"SELECT id,portfolio_id,ticker,side,qty,signal_date,status "
        f"FROM sim_orders WHERE portfolio_id IN ({marks}) ORDER BY id",
        ids,
    ).fetchall()
    if len(rows) > limit:
        raise SimulatorAttributionError("P7 attribution order count exceeds bound")
    for row in rows:
        if (
            row[2] not in {"SPY", "EFA", "BIL"}
            or row[3] not in {"buy", "sell"}
            or _number(row[4], "order quantity", True) <= 0
            or type(row[5]) is not date
            or row[6] not in {"pending", "filled", "rejected", "cancelled"}
        ):
            raise SimulatorAttributionError("P7 attribution simulator order is invalid")
    return rows


def _fills(con, books, orders):
    by_order, ids = {row[0]: row for row in orders}, list(books)
    marks, omarks = ",".join("?" for _ in ids), ",".join("?" for _ in orders) or "NULL"
    rows = con.execute(
        f"SELECT order_id,portfolio_id,ticker,side,qty,fill_date,fill_px,slippage_bps,cost_bps "
        f"FROM sim_fills WHERE portfolio_id IN ({marks}) OR order_id IN ({omarks}) ORDER BY order_id",
        [*ids, *by_order],
    ).fetchall()
    found = {}
    for row in rows:
        order = by_order.get(row[0])
        if (
            order is None
            or row[0] in found
            or row[1:4] != order[1:4]
            or row[5] <= order[5]
            or not 0 < _number(row[4], "fill quantity") <= order[4]
            or min(
                _number(row[6], "fill price", True),
                _number(row[7], "fill slippage"),
                _number(row[8], "fill cost"),
            )
            < 0
        ):
            raise SimulatorAttributionError("P7 attribution fill is unattributed or cross-book")
        found[row[0]] = row
    if set(found) != {row[0] for row in orders if row[6] == "filled"}:
        raise SimulatorAttributionError("P7 attribution filled orders and fills differ")
    return rows, found


def _costs(con, order_ids, marks, fills):
    rows = con.execute(
        f"SELECT * FROM sim_fill_costs WHERE order_id IN ({marks}) ORDER BY order_id", order_ids
    ).fetchall()
    for row in rows:
        values, fill = [_number(value, "cost component") for value in row[2:]], fills.get(row[0])
        if (
            fill is None
            or row[1] != "baseline_v1"
            or min(values) < 0
            or not math.isclose(values[4], values[1] + values[3], abs_tol=1e-12)
            or not math.isclose(values[4], fill[8], abs_tol=1e-12)
        ):
            raise SimulatorAttributionError("P7 attribution cost ownership is inconsistent")
    if {row[0] for row in rows} != set(fills):
        raise SimulatorAttributionError("P7 attribution fills and cost evidence differ")
    return rows


def _attempts(con, orders, fills, marks):
    ids = [row[0] for row in orders]
    rows = con.execute(
        f"SELECT * FROM sim_execution_attempts WHERE order_id IN ({marks}) ORDER BY order_id,attempt_date",
        ids,
    ).fetchall()
    grouped, by_order = {oid: [] for oid in ids}, {row[0]: row for row in orders}
    for row in rows:
        grouped[row[0]].append(row)
        order = by_order[row[0]]
        if (
            row[2] != "baseline_v1"
            or any(v is not None and _number(v, "attempt metric") < 0 for v in row[3:6])
            or row[6] not in {"pending", "filled", "rejected"}
            or row[1] <= order[5]
            or (row[6] == "rejected") != (isinstance(row[7], str) and bool(row[7].strip()))
        ):
            raise SimulatorAttributionError("P7 attribution execution attempt is invalid")
    for order in orders:
        history = grouped[order[0]]
        if order[6] in {"filled", "rejected"} and (not history or history[-1][6] != order[6]):
            raise SimulatorAttributionError("P7 attribution execution attempts are incomplete")
        if order[6] == "filled" and history[-1][1] != fills[order[0]][5]:
            raise SimulatorAttributionError("P7 attribution execution attempts are incomplete")
        if order[6] == "pending" and history and history[-1][6] != "pending":
            raise SimulatorAttributionError("P7 attribution execution attempts are inconsistent")
        if order[6] == "cancelled" and history and history[-1][6] == "filled":
            raise SimulatorAttributionError("P7 attribution execution attempts are inconsistent")
    return rows


def _positions(rows, books, balance):
    exposure = {book: 0.0 for book in books}
    for book, ticker, qty, cost in rows:
        if (
            ticker not in {"SPY", "EFA", "BIL"}
            or _number(qty, "position quantity", True) <= 0
            or _number(cost, "position cost", True) <= 0
        ):
            raise SimulatorAttributionError("P7 attribution position ownership is inconsistent")
        exposure[book] += qty * cost
    if any(value > balance + 1e-6 for value in exposure.values()):
        raise SimulatorAttributionError("P7 attribution gross exposure exceeds opening capital")


def _equity_paths(equity, books, balance, activation, as_of):
    paths = {book: [] for book in books}
    for row in equity:
        if row[1] > as_of:
            raise SimulatorAttributionError("P7 attribution contains future equity preseed")
        if (
            row[1] < activation
            or min(_number(row[2], "equity"), _number(row[3], "equity cash")) < 0
            or type(row[4]) is not int
            or row[4] < 0
        ):
            raise SimulatorAttributionError("P7 attribution equity is invalid")
        paths[row[0]].append(row)
    if len({tuple(row[1] for row in path) for path in paths.values()}) > 1:
        raise SimulatorAttributionError("P7 attribution equity dates differ across arms")
    opening = (activation, balance, balance, 0)
    if equity and any(not path or path[0][1:] != opening for path in paths.values()):
        raise SimulatorAttributionError("P7 attribution opening equity is unequal or invalid")
    return paths


def _state(con, books, balance, activation, as_of, active):
    ids, marks = list(books), ",".join("?" for _ in books)
    positions = con.execute(
        f"SELECT portfolio_id,ticker,qty,avg_cost FROM sim_positions WHERE portfolio_id IN ({marks})",
        ids,
    ).fetchall()
    equity = con.execute(
        f"SELECT portfolio_id,date,equity,cash,n_positions FROM sim_equity WHERE portfolio_id IN ({marks}) ORDER BY portfolio_id,date",
        ids,
    ).fetchall()
    if not active:
        cash = con.execute(f"SELECT cash FROM portfolios WHERE id IN ({marks})", ids).fetchall()
        if positions or equity:
            raise SimulatorAttributionError("P7 inactive books contain runtime evidence")
        if any(_number(row[0], "unstarted book cash") != balance for row in cash):
            raise SimulatorAttributionError("P7 attribution unstarted book balances are unequal")
        return [], []
    _positions(positions, books, balance)
    paths = _equity_paths(equity, books, balance, activation, as_of)
    if not equity:
        raise SimulatorAttributionError("P7 active books require complete aligned equity")
    for book, path in paths.items():
        if path:
            cash = con.execute("SELECT cash FROM portfolios WHERE id=?", [book]).fetchone()[0]
            if not math.isclose(cash, path[-1][3], abs_tol=1e-6) or path[-1][4] != sum(
                p[0] == book for p in positions
            ):
                raise SimulatorAttributionError(
                    "P7 attribution current cash or position count differs"
                )
    return equity, positions


def _economics(con, books):
    ids, marks = list(books), ",".join("?" for _ in books)
    dividends = con.execute(
        f"SELECT COUNT(*) FROM sim_dividends WHERE portfolio_id IN ({marks})", ids
    ).fetchone()[0]
    settlements = (
        con.execute(
            f"SELECT COUNT(*) FROM sim_settlements WHERE portfolio_id IN ({marks})", ids
        ).fetchone()[0]
        if table_exists(con, "sim_settlements")
        else 0
    )
    if dividends or settlements:
        raise SimulatorAttributionError(
            f"P7 unsupported economic rows: dividends={dividends}, settlements={settlements}"
        )
    return dividends, settlements


def verify(con, books, *, balance, activation, as_of, active, max_orders):
    """Validate simulator-owned P7 rows and return immutable order rows/counts."""
    dividends, settlements = _economics(con, books)
    orders = _orders(con, books, max_orders)
    if not active and orders:
        raise SimulatorAttributionError("P7 inactive books contain runtime evidence")
    fills, by_fill = _fills(con, books, orders)
    marks = ",".join("?" for _ in orders) or "NULL"
    costs = _costs(con, [row[0] for row in orders], marks, by_fill)
    attempts = _attempts(con, orders, by_fill, marks)
    equity, positions = _state(con, books, balance, activation, as_of, active)
    return {
        "orders": orders,
        "fills": len(fills),
        "costs": len(costs),
        "attempts": len(attempts),
        "equity": len(equity),
        "dividends": dividends,
        "settlements": settlements,
    }
