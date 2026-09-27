"""P16-only parity adapter for P15 fill, cost, split, and accounting mechanics."""
from __future__ import annotations

import math
from datetime import date

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from server.p16_book_store import P16BookError
from sim import fills, p15_fills, portfolio

SIM_FILLED_STATUS = "p16_filled"

attempt_limit_on_open = p15_fills.attempt_limit_on_open
attempt_fill = fills.attempt_fill
apply_fill = portfolio.apply_fill


def next_sim_order_id(con) -> int:
    return int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM sim_orders").fetchone()[0])


def split_factor(con, ticker: str, after: date, through: date) -> float:
    if not table_exists(con, "split_adjustments"):
        return 1.0
    rows = con.execute(
        "SELECT ratio FROM split_adjustments WHERE ticker=? AND outcome='applied' "
        "AND ex_date>? AND ex_date<=? ORDER BY ex_date", [ticker, after, through],
    ).fetchall()
    return math.prod(float(row[0]) for row in rows)


def record_sim_fill(
    con, *, intent_id: str, fill_date: date, result, source_sha256: str,
    adjusted_quantity: float | None = None,
) -> str:
    """Commit one terminal outcome through every P15-equivalent simulator ledger."""
    intent = con.execute(
        "SELECT book_instance_id,ticker,side,rounded_qty,signal_date,order_role,entry_atr,"
        "status,reason,sim_order_id FROM p16_order_intents WHERE intent_id=?", [intent_id],
    ).fetchone()
    if intent is None:
        raise P16BookError("P16 terminal intent is absent")
    (book, ticker, side, stored_quantity, signal_date, role, entry_atr,
     stored_status, reason, order_id) = intent
    quantity = float(stored_quantity if adjusted_quantity is None else adjusted_quantity)
    if not math.isfinite(quantity) or quantity <= 0:
        raise P16BookError("P16 adjusted terminal quantity is invalid")
    if stored_status != "pending":
        if order_id is None:
            raise P16BookError("P16 terminal intent lacks its simulator order")
        return stored_status
    order_id = next_sim_order_id(con)
    status, reason = result.status, result.reject_reason
    applied = 0.0
    if status == "filled":
        existing_quantity = con.execute(
            "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker=?",
            [book, ticker],
        ).fetchone()
        if (side == "buy" and ticker != "SPY"
                and (existing_quantity is None or existing_quantity[0] <= 0)
                and entry_atr is None):
            raise P16BookError("P16 new stock entry lacks its ATR rule")
        applied = apply_fill(con, {
            "portfolio_id": book, "ticker": ticker, "side": side,
            "qty": float(quantity), "fill_px": result.fill_px,
        })
        if applied <= 0:
            status = "rejected"
            reason = "insufficient_cash" if side == "buy" else "no_position_to_sell"
    con.execute(
        "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,?,?)",
        [order_id, book, ticker, side, float(quantity), signal_date,
         SIM_FILLED_STATUS if status == "filled" else status, reason],
    )
    raw_notional = None if result.open_px is None else float(quantity) * float(result.open_px)
    profile = result.execution_profile or "baseline_v1"
    con.execute(
        "INSERT INTO sim_execution_attempts "
        "(order_id,attempt_date,execution_profile,raw_notional,median_dollar_vol,"
        "participation,outcome,reject_reason) VALUES (?,?,?,?,?,?,?,?)",
        [order_id, fill_date, profile, raw_notional, result.median_dollar_vol,
         result.participation, status, reason],
    )
    if status == "filled":
        con.execute(
            "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
            [order_id, book, ticker, side, applied, fill_date, result.open_px,
             result.fill_px, result.slippage_bps, result.cost_bps],
        )
        con.execute(
            "INSERT INTO sim_fill_costs VALUES (?,?,?,?,?,?,?)",
            [order_id, profile, result.participation, result.slippage_bps,
             result.impact_bps, result.fee_bps, result.cost_bps],
        )
        fill_body = {
            "intent_id": intent_id, "order_id": order_id, "book_instance_id": book,
            "ticker": ticker, "side": side, "qty": applied,
            "fill_date": fill_date.isoformat(), "open_px": result.open_px,
            "fill_px": result.fill_px, "slippage_bps": result.slippage_bps,
            "cost_bps": result.cost_bps, "execution_profile": profile,
            "median_dollar_vol": result.median_dollar_vol,
            "participation": result.participation, "impact_bps": result.impact_bps,
            "fee_bps": result.fee_bps, "source_sha256": source_sha256,
        }
        fill_sha = canonical_sha256(fill_body)
        con.execute(
            "INSERT INTO p16_book_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [*fill_body.values(), fill_sha],
        )
        if side == "buy" and ticker != "SPY" and entry_atr is not None:
            con.execute(
                "INSERT INTO p16_position_rules VALUES (?,?,?,?,?,?,?,?,NULL)",
                [book, ticker, intent_id, order_id, fill_date, float(entry_atr),
                 float(result.fill_px) - 2.5 * float(entry_atr), "open"],
            )
        elif side == "sell" and ticker != "SPY":
            remaining = con.execute(
                "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker=?",
                [book, ticker],
            ).fetchone()
            if remaining is None or remaining[0] <= 1e-12:
                con.execute(
                    "UPDATE p16_position_rules SET status='closed',exit_intent_id=? "
                    "WHERE book_instance_id=? AND ticker=? AND status='open'",
                    [intent_id, book, ticker],
                )
    con.execute(
        "UPDATE p16_order_intents SET status=?,reason=?,sim_order_id=? WHERE intent_id=?",
        [status, reason, order_id, intent_id],
    )
    return status


def mark_exact(con, book_instance_id: str, market_date: date) -> dict:
    """Append or verify the exact close projection without carrying a fabricated price."""
    cash = portfolio.get_cash(con, book_instance_id)
    positions = portfolio.get_positions(con, book_instance_id)
    market_value, carried, marks = 0.0, [], {}
    for ticker, position in sorted(positions.items()):
        close, stale = portfolio.close_on(con, ticker, market_date)
        marks[ticker] = close
        if close is None:
            carried.append(ticker)
            continue
        market_value += float(position["qty"]) * close
        if stale:
            carried.append(ticker)
    expected = (cash + market_value, cash, len(positions))
    retained = con.execute(
        "SELECT equity,cash,n_positions FROM sim_equity WHERE portfolio_id=? AND date=?",
        [book_instance_id, market_date],
    ).fetchone()
    if retained is not None:
        if retained != expected:
            raise P16BookError("P16 simulator mark replay differs")
    else:
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,?,?)",
            [book_instance_id, market_date, *expected],
        )
    return {
        "equity": expected[0], "cash": cash, "n_positions": len(positions),
        "carried": carried, "marks": marks,
        "position_state_sha256": canonical_sha256({
            "cash": cash,
            "positions": {ticker: positions[ticker] for ticker in sorted(positions)},
        }),
    }
