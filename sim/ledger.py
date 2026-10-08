"""Side-aware cash, position-lot, fee, and replay accounting."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone

import duckdb

from engine.lib.log import get_logger
from engine.lib.util import table_exists

from .costs import FeeBreakdown
from .schema import INITIAL_CASH, portfolio_account

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


@dataclass(frozen=True)
class MatchedLot:
    open_order_id: int
    opened_session: date
    qty: float
    avg_px: float


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


def add_lot(con: duckdb.DuckDBPyConnection, portfolio_id: str, instrument_id: str,
            opened_session: date, open_order_id: int, qty: float, avg_px: float) -> None:
    """Add signed quantity to one open lot, preserving its weighted basis."""
    existing = con.execute(
        "SELECT qty,avg_px FROM sim_position_lots WHERE portfolio_id=? "
        "AND instrument_id=? AND open_order_id=?",
        [portfolio_id, instrument_id, open_order_id],
    ).fetchone()
    if existing is None:
        con.execute(
            "INSERT INTO sim_position_lots "
            "(portfolio_id,instrument_id,opened_session,open_order_id,qty,avg_px) "
            "VALUES (?,?,?,?,?,?)",
            [portfolio_id, instrument_id, opened_session, open_order_id, qty, avg_px],
        )
        return
    old_qty, old_px = float(existing[0]), float(existing[1])
    if old_qty * qty < 0:
        raise ValueError("cannot merge long and short quantities into one lot")
    new_qty = old_qty + qty
    new_px = (
        (abs(old_qty) * old_px + abs(qty) * avg_px) / abs(new_qty)
        if new_qty else 0.0
    )
    con.execute(
        "UPDATE sim_position_lots SET qty=?,avg_px=? WHERE portfolio_id=? "
        "AND instrument_id=? AND open_order_id=?",
        [new_qty, new_px, portfolio_id, instrument_id, open_order_id],
    )


def _open_lot(con, fill, instrument_id: str, qty: float, px: float) -> None:
    order_id = _value(fill, "order_id")
    opened = _value(fill, "session_date", "fill_date")
    if order_id is None or opened is None:
        return
    add_lot(
        con, _value(fill, "portfolio_id"), instrument_id, opened, int(order_id), qty, px,
    )


def match_lots(con: duckdb.DuckDBPyConnection, portfolio_id: str,
               instrument_id: str, qty: float, *,
               closing_short: bool = False) -> tuple[MatchedLot, ...]:
    """Consume FIFO lots and return the exact opens matched by a close."""
    comparison = "< 0" if closing_short else "> 0"
    remaining = qty
    matched = []
    for order_id, stored, opened_session, avg_px in con.execute(
        "SELECT open_order_id,qty,opened_session,avg_px FROM sim_position_lots "
        f"WHERE portfolio_id=? AND instrument_id=? AND qty {comparison} "
        "ORDER BY opened_session,open_order_id",
        [portfolio_id, instrument_id],
    ).fetchall():
        available = abs(float(stored))
        consumed = min(remaining, available)
        matched.append(MatchedLot(int(order_id), opened_session, consumed, float(avg_px)))
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
    return tuple(matched)


def _record_day_trade(con, fill, instrument_id: str,
                      matched: tuple[MatchedLot, ...]) -> None:
    close_order_id = _value(fill, "order_id")
    session = _value(fill, "session_date", "fill_date")
    same_day = next((lot for lot in matched if lot.opened_session == session), None)
    if same_day is None:
        return
    con.execute(
        "INSERT INTO sim_day_trades "
        "(portfolio_id,session_date,instrument_id,open_order_id,close_order_id) "
        "VALUES (?,?,?,?,?)",
        [_value(fill, "portfolio_id"), session, instrument_id,
         same_day.open_order_id, close_order_id],
    )


def assert_lots_match_positions(con: duckdb.DuckDBPyConnection,
                                portfolio_id: str) -> None:
    """Raise when an account's signed open lots differ from current positions."""
    positions = {
        instrument_id: float(qty)
        for instrument_id, qty in con.execute(
            "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND abs(qty)>=1e-9",
            [portfolio_id],
        ).fetchall()
    }
    lots = {
        instrument_id: float(qty)
        for instrument_id, qty in con.execute(
            "SELECT instrument_id,SUM(qty) FROM sim_position_lots "
            "WHERE portfolio_id=? GROUP BY instrument_id HAVING abs(SUM(qty))>=1e-9",
            [portfolio_id],
        ).fetchall()
    }
    if positions.keys() != lots.keys() or any(
        not math.isclose(positions[key], lots[key], rel_tol=1e-12, abs_tol=1e-9)
        for key in positions
    ):
        raise ValueError(f"position lots differ from positions for {portfolio_id!r}")


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
        "SELECT cash FROM portfolios WHERE id=?",
        [portfolio_id],
    ).fetchone()
    if portfolio is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    cash = float(portfolio[0])
    settings = portfolio_account(con, portfolio_id)
    account_type = settings["account_type"]
    order_id = _value(fill, "order_id")
    fill_date = _value(fill, "session_date", "fill_date")
    if settings["engine"] == "account" and (order_id is None or fill_date is None):
        raise ValueError("account-engine fills require order_id and fill date")
    if side == "short" and account_type == "cash_legacy":
        raise ValueError("cash_legacy portfolios cannot short")
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
        matched = match_lots(con, portfolio_id, instrument_id, qty)
        if settings["engine"] == "account":
            _record_day_trade(con, fill, instrument_id, matched)
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
        matched = match_lots(
            con, portfolio_id, instrument_id, qty, closing_short=True
        )
        if settings["engine"] == "account":
            _record_day_trade(con, fill, instrument_id, matched)

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
    if persist_fees and fees is not None and order_id is not None:
        _persist_fees(con, int(order_id), charged)
    if settings["engine"] == "account":
        assert_lots_match_positions(con, portfolio_id)
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


def rebuild_state(
    con: duckdb.DuckDBPyConnection,
    portfolio_ids: Iterable[str] | None = None,
    *,
    through: date | None = None,
) -> None:
    """Replay ledger state, optionally for only the named portfolios.

    Selective replay is what lets a legacy-book rerun repair those books without
    rewriting account-engine cash, positions, lots, or day-trade state.
    """
    selected = None if portfolio_ids is None else tuple(sorted(set(portfolio_ids)))
    if selected == ():
        return
    clause = ""
    params: list[object] = []
    if selected is not None:
        clause = f" WHERE id IN ({','.join('?' for _ in selected)})"
        params.extend(selected)
    portfolios = con.execute(
        "SELECT id,COALESCE(initial_cash,?) FROM portfolios" + clause,
        [INITIAL_CASH, *params],
    ).fetchall()
    if not portfolios:
        return
    target_ids = [row[0] for row in portfolios]
    placeholders = ",".join("?" for _ in target_ids)
    for table in ("sim_positions", "sim_position_lots", "sim_day_trades"):
        con.execute(
            f"DELETE FROM {table} WHERE portfolio_id IN ({placeholders})", target_ids,
        )
    for portfolio_id, initial_cash in portfolios:
        con.execute(
            "UPDATE portfolios SET cash=? WHERE id=?", [initial_cash, portfolio_id]
        )

    events: list[tuple] = []
    if table_exists(con, "sim_dividends"):
        for seq, row in enumerate(con.execute(
            "SELECT portfolio_id,ticker,ex_date,amount FROM sim_dividends "
            f"WHERE portfolio_id IN ({placeholders}) "
            "ORDER BY ex_date,portfolio_id,ticker",
            target_ids,
        ).fetchall()):
            events.append((row[2], 0, seq, "dividend", row))
    if table_exists(con, "sim_settlements"):
        for seq, row in enumerate(con.execute(
            "SELECT portfolio_id,ticker,kind,qty,price,into_ticker,ratio,effective "
            f"FROM sim_settlements WHERE portfolio_id IN ({placeholders}) "
            "ORDER BY effective,portfolio_id,ticker",
            target_ids,
        ).fetchall()):
            events.append((row[7], 1, seq, "settlement", row))

    fee_columns = (
        "ff.cost_profile,ff.commission,ff.exchange_fee,ff.clearing_fee,"
        "ff.pass_through,ff.cat_fee,ff.sec_fee,ff.finra_taf,ff.occ_fee,"
        "ff.orf_fee,ff.total_usd"
    )
    fills = con.execute(
        "SELECT f.order_id,f.portfolio_id,f.ticker,f.side,f.qty,f.fill_px,f.fill_date,"
        "COALESCE(fd.multiplier,1),pa.pa_engine,fd.fill_ts," + fee_columns
        + " FROM sim_fills f "
        "LEFT JOIN sim_fill_details fd ON fd.order_id=f.order_id "
        "LEFT JOIN portfolio_accounts_v pa USING (portfolio_id) "
        "LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id "
        f"WHERE f.portfolio_id IN ({placeholders}) "
        "ORDER BY f.fill_date,f.portfolio_id,f.order_id",
        target_ids,
    ).fetchall()
    for row in fills:
        order_id, portfolio_id, _ticker, side, *_tail = row
        engine, fill_ts = row[8:10]
        if engine == "account":
            if fill_ts is None:
                raise ValueError(
                    f"account-engine fill {order_id} has no authoritative fill_ts"
                )
            replay_order = (portfolio_id, 1, fill_ts, order_id)
        else:
            side_priority = 0 if side in {"sell", "cover"} else 1
            replay_order = (portfolio_id, 0, side_priority, order_id)
        events.append((row[6], 2, replay_order, "fill", row))
    if table_exists(con, "sim_cash_events"):
        for row in con.execute(
            "SELECT portfolio_id,event_date,seq,amount,kind FROM sim_cash_events "
            f"WHERE portfolio_id IN ({placeholders}) "
            "ORDER BY event_date,portfolio_id,seq",
            target_ids,
        ).fetchall():
            phase = 1.5 if row[4] in {"borrow_fee", "margin_interest"} else 3
            events.append((row[1], phase, row[2], "cash", row))
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    splits = _split_factors(con)
    from engine.accounts.actions import recorded_splits

    account_splits = {}
    for portfolio_id in target_ids:
        if portfolio_account(con, portfolio_id)['engine'] == 'account':
            account_splits[portfolio_id] = recorded_splits(con, portfolio_id, through)

    for _event_date, _phase, _seq, kind, row in events:
        if through is not None and _event_date > through:
            continue
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
        factors = (
            [(ex, ratio) for name, ex, ratio in account_splits[portfolio_id] if name == ticker]
            if portfolio_id in account_splits else splits.get(ticker, ())
        )
        for ex_date, ratio in factors:
            if fill_date < ex_date:
                factor *= ratio
        fee_row = row[10:]
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


def post_accrual(con, event: Mapping, *, replay: bool = False) -> bool:
    """Append a financing correction while retaining every previous cash event."""
    existing = con.execute(
        'SELECT COUNT(*),COALESCE(SUM(amount),0) FROM sim_cash_events '
        'WHERE portfolio_id=? AND event_date=? AND kind=? '
        'AND instrument_id IS NOT DISTINCT FROM ?',
        [event['portfolio_id'], event['event_date'], event['kind'], event.get('instrument_id')],
    ).fetchone()
    if existing[0] and not replay:
        return False
    if replay:
        con.execute('UPDATE portfolios SET cash=cash+? WHERE id=?',
                    [existing[1], event['portfolio_id']])
    delta = float(event['amount']) - float(existing[1])
    if abs(delta) < 1e-10:
        return False
    apply_cash_event(con, {**event, 'amount': delta})
    return True


def replay_session_fills(con, portfolio_id: str, day: date) -> list[dict]:
    """Stored executions for merging with newly available fills in timestamp order."""
    cursor = con.execute(
        'SELECT f.*,d.fill_ts,ff.* EXCLUDE(order_id) FROM sim_fills f '
        'JOIN sim_fill_details d ON d.order_id=f.order_id '
        'LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id '
        'WHERE f.portfolio_id=? AND f.fill_date=? ORDER BY d.fill_ts,f.order_id',
        [portfolio_id, day],
    )
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def apply_stored_fill(con, row: dict) -> None:
    """Replay an immutable execution without writing its fill or fee rows again."""
    qty = apply_fill(con, row, row if row.get('cost_profile') else None, persist_fees=False)
    if not math.isclose(qty, row['qty'], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"stored fill {row['order_id']} changed quantity during replay")
