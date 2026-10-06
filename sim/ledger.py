"""Side-aware cash, position-lot, fee, and replay accounting."""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timezone

import duckdb

from engine.lib.log import get_logger
from engine.lib.util import table_exists

from .costs import FeeBreakdown
from .schema import INITIAL_CASH

MIN_FILL_USD = 1.0
CASH_EVENT_KINDS = frozenset({
    "borrow_fee",
    "margin_interest",
    "short_dividend",
    "buy_in_penalty",
    "expiry",
    "assignment",
    "exercise",
    "cash_settlement",
    "adjustment",
})
log = get_logger("ledger")


def _value(fill, name: str, *aliases: str, default=None):
    if isinstance(fill, Mapping):
        for key in (name, *aliases):
            if key in fill:
                return fill[key]
        return default
    for key in (name, *aliases):
        if hasattr(fill, key):
            return getattr(fill, key)
    return default


def _fee_value(fees, name: str, default=0.0):
    if fees is None:
        return default
    if isinstance(fees, Mapping):
        return fees.get(name, default)
    return getattr(fees, name, default)


def _normalise_fees(fees) -> FeeBreakdown:
    if fees is None:
        return FeeBreakdown("baseline_v1")
    if isinstance(fees, FeeBreakdown):
        return fees
    return FeeBreakdown(
        profile_id=str(_fee_value(fees, "profile_id", _fee_value(
            fees, "cost_profile", "baseline_v1",
        ))),
        commission=float(_fee_value(fees, "commission")),
        exchange_fee=float(_fee_value(fees, "exchange_fee")),
        clearing_fee=float(_fee_value(fees, "clearing_fee")),
        pass_through=float(_fee_value(fees, "pass_through")),
        cat_fee=float(_fee_value(fees, "cat_fee")),
        sec_fee=float(_fee_value(fees, "sec_fee")),
        finra_taf=float(_fee_value(fees, "finra_taf")),
        occ_fee=float(_fee_value(fees, "occ_fee")),
        orf_fee=float(_fee_value(fees, "orf_fee")),
        total_usd=float(_fee_value(fees, "total_usd")),
    )


def _persist_fees(con: duckdb.DuckDBPyConnection, order_id: int,
                  fees: FeeBreakdown) -> None:
    con.execute(
        "INSERT INTO sim_fill_fees "
        "(order_id,cost_profile,commission,exchange_fee,clearing_fee,pass_through,"
        "cat_fee,sec_fee,finra_taf,occ_fee,orf_fee,total_usd) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            order_id,
            fees.profile_id,
            fees.commission,
            fees.exchange_fee,
            fees.clearing_fee,
            fees.pass_through,
            fees.cat_fee,
            fees.sec_fee,
            fees.finra_taf,
            fees.occ_fee,
            fees.orf_fee,
            fees.total_usd,
        ],
    )


def _open_lot(con, fill, instrument_id: str, qty: float, px: float) -> None:
    order_id = _value(fill, "order_id")
    opened = _value(fill, "session_date", "fill_date")
    if order_id is None or opened is None:
        return
    con.execute(
        "INSERT INTO sim_position_lots "
        "(portfolio_id,instrument_id,opened_session,open_order_id,qty,avg_px) "
        "VALUES (?,?,?,?,?,?)",
        [_value(fill, "portfolio_id"), instrument_id, opened, order_id, qty, px],
    )


def _consume_lots(con, portfolio_id: str, instrument_id: str, qty: float,
                  *, closing_short: bool) -> None:
    comparison = "< 0" if closing_short else "> 0"
    remaining = qty
    rows = con.execute(
        "SELECT open_order_id,qty FROM sim_position_lots "
        f"WHERE portfolio_id=? AND instrument_id=? AND qty {comparison} "
        "ORDER BY opened_session,open_order_id",
        [portfolio_id, instrument_id],
    ).fetchall()
    for order_id, stored in rows:
        available = abs(float(stored))
        consumed = min(remaining, available)
        left = available - consumed
        if left <= 1e-12:
            con.execute(
                "DELETE FROM sim_position_lots WHERE portfolio_id=? "
                "AND instrument_id=? AND open_order_id=?",
                [portfolio_id, instrument_id, order_id],
            )
        else:
            con.execute(
                "UPDATE sim_position_lots SET qty=? WHERE portfolio_id=? "
                "AND instrument_id=? AND open_order_id=?",
                [-left if closing_short else left, portfolio_id, instrument_id, order_id],
            )
        remaining -= consumed
        if remaining <= 1e-12:
            break


def apply_fill(con: duckdb.DuckDBPyConnection, fill, fees=None, *,
               persist_fees: bool = True) -> float:
    """Apply a buy/sell/short/cover and return the positive quantity applied.

    ``buy`` and ``sell`` retain the legacy cash-account clamps. ``short`` and
    ``cover`` are explicit sides, so a close can never silently cross through
    zero. Dollar fees are always debited from cash and, when an order id is
    supplied, stored beside the immutable fill for deterministic replay.
    """
    portfolio_id = str(_value(fill, "portfolio_id"))
    instrument_id = str(_value(fill, "instrument_id", "ticker"))
    side = str(_value(fill, "side"))
    qty = float(_value(fill, "qty", "quantity"))
    px = float(_value(fill, "fill_px", "price"))
    multiplier = float(_value(fill, "multiplier", default=1.0))
    if side not in {"buy", "sell", "short", "cover"}:
        raise ValueError(f"unknown fill side {side!r}")
    if not all(math.isfinite(value) and value > 0 for value in (qty, px, multiplier)):
        log.warning(
            f"[ledger] WARN bad_fill: {portfolio_id} {instrument_id} "
            f"{side} {qty} @ {px!r} — fill rejected"
        )
        return 0.0
    portfolio = con.execute(
        "SELECT cash,COALESCE(account_type,'cash_legacy') FROM portfolios WHERE id=?",
        [portfolio_id],
    ).fetchone()
    if portfolio is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    cash, account_type = float(portfolio[0]), portfolio[1]
    row = con.execute(
        "SELECT qty,avg_cost FROM sim_positions WHERE portfolio_id=? AND ticker=?",
        [portfolio_id, instrument_id],
    ).fetchone()
    current_qty, current_cost = (
        (float(row[0]), float(row[1])) if row else (0.0, 0.0)
    )
    charged = _normalise_fees(fees)
    fee = charged.total_usd
    if not math.isfinite(fee) or fee < 0:
        raise ValueError("fill fees must be finite and non-negative")

    if side == "buy":
        if current_qty < 0:
            raise ValueError("buy cannot close a short position; use cover")
        available = cash - fee if account_type == "cash_legacy" else math.inf
        notional = qty * px * multiplier
        if notional > available:
            affordable = (
                (max(available, 0.0) / (px * multiplier)) * (1.0 - 1e-12)
            )
            if affordable * px * multiplier < MIN_FILL_USD:
                log.warning(
                    f"[ledger] WARN insufficient_cash: {portfolio_id} "
                    f"{instrument_id} buy {qty} @ {px:.4f} — fill rejected"
                )
                return 0.0
            qty = float(affordable)
        new_qty = current_qty + qty
        new_cost = (
            (current_qty * current_cost + qty * px) / new_qty if new_qty else 0.0
        )
        cash_delta = -(qty * px * multiplier) - fee
        _open_lot(con, fill, instrument_id, qty, px)
    elif side == "sell":
        if current_qty <= 0:
            return 0.0
        if qty > current_qty:
            log.warning(
                f"[ledger] WARN sell-clamp: {portfolio_id} {instrument_id} "
                f"sell {qty} > held {current_qty} → {current_qty}"
            )
            qty = current_qty
        new_qty, new_cost = current_qty - qty, current_cost
        cash_delta = qty * px * multiplier - fee
        _consume_lots(con, portfolio_id, instrument_id, qty, closing_short=False)
    elif side == "short":
        if current_qty > 0:
            raise ValueError("short cannot close a long position; use sell")
        short_before = abs(current_qty)
        short_after = short_before + qty
        new_qty = -short_after
        new_cost = (
            (short_before * current_cost + qty * px) / short_after
            if short_after else 0.0
        )
        cash_delta = qty * px * multiplier - fee
        _open_lot(con, fill, instrument_id, -qty, px)
    else:
        if current_qty >= 0:
            return 0.0
        if qty > abs(current_qty):
            log.warning(
                f"[ledger] WARN cover-clamp: {portfolio_id} {instrument_id} "
                f"cover {qty} > short {abs(current_qty)} → {abs(current_qty)}"
            )
            qty = abs(current_qty)
        new_qty, new_cost = current_qty + qty, current_cost
        cash_delta = -(qty * px * multiplier) - fee
        _consume_lots(con, portfolio_id, instrument_id, qty, closing_short=True)

    con.execute("UPDATE portfolios SET cash=cash+? WHERE id=?", [cash_delta, portfolio_id])
    if row:
        con.execute(
            "UPDATE sim_positions SET qty=?,avg_cost=? WHERE portfolio_id=? AND ticker=?",
            [new_qty, new_cost, portfolio_id, instrument_id],
        )
    else:
        con.execute(
            "INSERT INTO sim_positions (portfolio_id,ticker,qty,avg_cost) VALUES (?,?,?,?)",
            [portfolio_id, instrument_id, new_qty, new_cost],
        )
    order_id = _value(fill, "order_id")
    if persist_fees and fees is not None and order_id is not None:
        _persist_fees(con, int(order_id), charged)
    return float(qty)


def apply_cash_event(con: duckdb.DuckDBPyConnection, event: Mapping) -> int:
    """Append one signed non-fill cash movement and apply it exactly once."""
    portfolio_id = str(event["portfolio_id"])
    event_date = event["event_date"]
    kind = str(event["kind"])
    amount = float(event["amount"])
    if kind not in CASH_EVENT_KINDS:
        raise ValueError(f"unknown cash-event kind {kind!r}")
    if not math.isfinite(amount):
        raise ValueError("cash-event amount must be finite")
    seq = event.get("seq")
    if seq is None:
        seq = int(con.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM sim_cash_events "
            "WHERE portfolio_id=? AND event_date=?",
            [portfolio_id, event_date],
        ).fetchone()[0])
    created_at = event.get("created_at") or datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO sim_cash_events "
        "(portfolio_id,event_date,seq,kind,amount,instrument_id,ref_order_id,note,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [portfolio_id, event_date, seq, kind, amount, event.get("instrument_id"),
         event.get("ref_order_id"), event.get("note"), created_at],
    )
    con.execute("UPDATE portfolios SET cash=cash+? WHERE id=?", [amount, portfolio_id])
    return int(seq)


def _split_factors(con) -> dict[str, list[tuple[date, float]]]:
    if not table_exists(con, "split_adjustments"):
        return {}
    out: dict[str, list[tuple[date, float]]] = {}
    for ticker, ex_date, ratio in con.execute(
        "SELECT ticker,ex_date,ratio FROM split_adjustments "
        "WHERE outcome='applied' AND ratio IS NOT NULL AND ratio>0"
    ).fetchall():
        out.setdefault(ticker, []).append((ex_date, float(ratio)))
    return out


def rebuild_state(con: duckdb.DuckDBPyConnection) -> None:
    """Replay dividends → settlements → fills with fees → cash events by date."""
    portfolios = con.execute(
        "SELECT id,COALESCE(initial_cash,?) FROM portfolios", [INITIAL_CASH]
    ).fetchall()
    con.execute("DELETE FROM sim_positions")
    con.execute("DELETE FROM sim_position_lots")
    for portfolio_id, initial_cash in portfolios:
        con.execute(
            "UPDATE portfolios SET cash=? WHERE id=?", [initial_cash, portfolio_id]
        )

    events: list[tuple] = []
    if table_exists(con, "sim_dividends"):
        for seq, row in enumerate(con.execute(
            "SELECT portfolio_id,ticker,ex_date,amount FROM sim_dividends "
            "ORDER BY ex_date,portfolio_id,ticker"
        ).fetchall()):
            events.append((row[2], 0, seq, "dividend", row))
    if table_exists(con, "sim_settlements"):
        for seq, row in enumerate(con.execute(
            "SELECT portfolio_id,ticker,kind,qty,price,into_ticker,ratio,effective "
            "FROM sim_settlements ORDER BY effective,portfolio_id,ticker"
        ).fetchall()):
            events.append((row[7], 1, seq, "settlement", row))

    fee_columns = (
        "ff.cost_profile,ff.commission,ff.exchange_fee,ff.clearing_fee,"
        "ff.pass_through,ff.cat_fee,ff.sec_fee,ff.finra_taf,ff.occ_fee,"
        "ff.orf_fee,ff.total_usd"
    )
    fills = con.execute(
        "SELECT f.order_id,f.portfolio_id,f.ticker,f.side,f.qty,f.fill_px,f.fill_date,"
        "COALESCE(fd.multiplier,1)," + fee_columns + " FROM sim_fills f "
        "LEFT JOIN sim_fill_details fd ON fd.order_id=f.order_id "
        "LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id "
        "ORDER BY f.fill_date,CASE f.side WHEN 'sell' THEN 0 WHEN 'cover' THEN 0 ELSE 1 END,"
        "f.order_id"
    ).fetchall()
    for seq, row in enumerate(fills):
        events.append((row[6], 2, seq, "fill", row))
    if table_exists(con, "sim_cash_events"):
        for row in con.execute(
            "SELECT portfolio_id,event_date,seq,amount FROM sim_cash_events "
            "ORDER BY event_date,portfolio_id,seq"
        ).fetchall():
            events.append((row[1], 3, row[2], "cash", row))
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    splits = _split_factors(con)

    for _event_date, _phase, _seq, kind, row in events:
        if kind == "dividend":
            con.execute("UPDATE portfolios SET cash=cash+? WHERE id=?", [row[3], row[0]])
            continue
        if kind == "settlement":
            from .settle import apply_settlement_event

            apply_settlement_event(
                con, row[0], row[1], row[2], float(row[3]), float(row[4]), row[5],
                None if row[6] is None else float(row[6]),
            )
            continue
        if kind == "cash":
            con.execute("UPDATE portfolios SET cash=cash+? WHERE id=?", [row[3], row[0]])
            continue
        order_id, portfolio_id, ticker, side, qty, px, fill_date, multiplier = row[:8]
        factor = 1.0
        for ex_date, ratio in splits.get(ticker, ()):
            if fill_date < ex_date:
                factor *= ratio
        fee_row = row[8:]
        fees = None if fee_row[0] is None else FeeBreakdown(
            profile_id=fee_row[0],
            commission=float(fee_row[1] or 0),
            exchange_fee=float(fee_row[2] or 0),
            clearing_fee=float(fee_row[3] or 0),
            pass_through=float(fee_row[4] or 0),
            cat_fee=float(fee_row[5] or 0),
            sec_fee=float(fee_row[6] or 0),
            finra_taf=float(fee_row[7] or 0),
            occ_fee=float(fee_row[8] or 0),
            orf_fee=float(fee_row[9] or 0),
            total_usd=float(fee_row[10] or 0),
        )
        adjusted = float(qty) * factor
        applied = apply_fill(
            con,
            {
                "order_id": order_id,
                "portfolio_id": portfolio_id,
                "instrument_id": ticker,
                "side": side,
                "qty": adjusted,
                "fill_px": float(px) / factor,
                "fill_date": fill_date,
                "multiplier": float(multiplier),
            },
            fees,
            persist_fees=False,
        )
        if not math.isclose(applied, adjusted, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"stored fill {order_id} changed quantity during replay")
