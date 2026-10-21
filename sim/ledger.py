"""Side-aware cash, position-lot, fee, and replay accounting."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone

import duckdb

from engine.lib import db
from engine.lib.log import get_logger
from engine.lib.util import table_exists

from . import money_inputs
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
# Offline replays opt in to reusing exact prefix states (see projection_checkpoints).
_CHECKPOINTS: dict | None = None
_STATE_TABLES = ('sim_positions', 'sim_position_lots', 'sim_day_trades')


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
               closing_short: bool = False, consume: bool = True) -> tuple[MatchedLot, ...]:
    """Consume FIFO lots and return the exact opens matched by a close."""
    comparison = "< 0" if closing_short else "> 0"
    remaining = qty
    matched = []
    if qty <= 1e-12:
        return ()
    for order_id, stored, opened_session, avg_px in con.execute(
        "SELECT l.open_order_id,l.qty,l.opened_session,l.avg_px FROM sim_position_lots l "
        "LEFT JOIN sim_fill_details d ON d.order_id=l.open_order_id "
        f"WHERE l.portfolio_id=? AND l.instrument_id=? AND l.qty {comparison} "
        "ORDER BY l.opened_session,d.fill_ts,l.open_order_id",
        [portfolio_id, instrument_id],
    ).fetchall():
        available = abs(float(stored))
        consumed = min(remaining, available)
        matched.append(MatchedLot(int(order_id), opened_session, consumed, float(avg_px)))
        left = available - consumed
        if consume and left <= 1e-12:
            con.execute(
                "DELETE FROM sim_position_lots WHERE portfolio_id=? "
                "AND instrument_id=? AND open_order_id=?",
                [portfolio_id, instrument_id, order_id],
            )
        elif consume:
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
               persist_fees: bool = True, on_close=None) -> float:
    """Apply a buy/sell/short/cover and return the positive quantity applied.

    ``buy`` and ``sell`` retain the legacy cash-account clamps. ``short`` and
    ``cover`` are explicit sides, so a close can never silently cross through
    zero. Dollar fees are always debited from cash and, when an order id is
    supplied, stored beside the immutable fill for deterministic replay.
    """
    portfolio_id = str(_value(fill, "portfolio_id"))
    instrument_id = str(_value(fill, "instrument_id", "ticker"))
    side = str(_value(fill, "side"))
    try:
        qty = money_inputs.finite_number(_value(fill, "qty", "quantity"), "fill quantity", positive=True)
        px = money_inputs.finite_number(_value(fill, "fill_px", "price"), "fill price", positive=True)
        multiplier = money_inputs.finite_number(_value(fill, "multiplier", default=1.0), "multiplier", positive=True)
        money_inputs.finite_number(qty * px * multiplier, "fill notional", positive=True)
    except ValueError as exc:
        log.warning(f"[ledger] WARN bad_fill: {exc} — fill rejected")
        return 0.0
    if side not in {"buy", "sell", "short", "cover"}:
        raise ValueError(f"unknown fill side {side!r}")
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
    matched = ()
    if fees is not None:
        for name in FeeBreakdown.__dataclass_fields__:
            if name != "profile_id":
                money_inputs.finite_number(_fee_value(fees, name), f"fill fee {name}", nonnegative=True)
    charged = _normalise_fees(fees)
    fee = charged.total_usd
    money_inputs.finite_number(cash, "cash")
    money_inputs.finite_number(current_qty, "position quantity")
    money_inputs.finite_number(current_cost, "position basis", nonnegative=True)
    signed_notional = qty * px * multiplier * (-1 if side in {"buy", "cover"} else 1)
    money_inputs.finite_number(cash + signed_notional - fee, "cash after fill")
    money_inputs.finite_number(abs(current_qty) + qty, "position after fill")
    money_inputs.finite_number(abs(current_qty) * current_cost + qty * px, "position basis value")

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

    if on_close is not None and matched:
        on_close(con, matched, side, qty, px, multiplier, fee)
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


def get_cash_value(con, portfolio_id):
    row = con.execute("SELECT cash FROM portfolios WHERE id=?", [portfolio_id]).fetchone()
    if row is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    return money_inputs.finite_number(row[0], "cash")


def apply_cash_event(con: duckdb.DuckDBPyConnection, event: Mapping) -> int:
    """Append one signed non-fill cash movement and apply it exactly once."""
    portfolio_id = str(event["portfolio_id"])
    event_date = event["event_date"]
    kind = str(event["kind"])
    amount = money_inputs.finite_number(event["amount"], "cash-event amount")
    if kind not in CASH_EVENT_KINDS:
        raise ValueError(f"unknown cash-event kind {kind!r}")
    money_inputs.finite_number(get_cash_value(con, portfolio_id) + amount, "cash after event")
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


@dataclass(frozen=True)
class LedgerEvent:
    stamp: datetime
    phase: int
    sequence: tuple
    kind: str
    row: dict

    @property
    def key(self):
        return self.stamp, self.phase, self.sequence


def _rows(con, sql, params):
    cursor = con.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def events(con, portfolio_ids, *, since=None, through=None) -> list[LedgerEvent]:
    """The shared chronological sequence for replay, recovery and trade results.

    Elapsed debit interest precedes opening cash movements; borrow follows
    opening corporate actions. Execution uses authoritative fill timestamps.
    """
    from engine.accounts.actions import recorded_splits

    from . import bar_sources

    result = []
    for account_id in portfolio_ids:
        account = portfolio_account(con, account_id)['engine'] == 'account'
        splits = (recorded_splits(con, account_id, through) if account else
                  [(ticker, day, ratio) for ticker, rows in _split_factors(con).items()
                   for day, ratio in rows])
        for ticker, day, ratio in splits:
            result.append(LedgerEvent(bar_sources.session_bounds(day)[0], 0,
                (account_id, 1, ticker), 'split', {'portfolio_id': account_id,
                'ticker': ticker, 'ex_date': day, 'ratio': ratio}))
        tables = (
            ('sim_dividends', 'ex_date', 'dividend', 1),
            ('sim_settlements', 'effective', 'settlement', 2),
            ('sim_cash_events', 'event_date', 'cash', 5),
        )
        for table, day_key, kind, phase in tables:
            if not table_exists(con, table):
                continue
            for row in _rows(con, f'SELECT * FROM {table} WHERE portfolio_id=?', [account_id]):
                opened, closed = bar_sources.session_bounds(row[day_key])
                stamp, priority = opened, phase
                if kind == 'cash':
                    financing = row['kind'] in {'borrow_fee', 'margin_interest'}
                    created = row['created_at']
                    stamp = opened if financing else (
                        created if created.date() == row[day_key] else closed)
                    # Interest covers the preceding debit interval; opening
                    # dividends, settlements and borrow charges cannot reduce it.
                    priority = (-1 if row['kind'] == 'margin_interest' else 3) if financing else phase
                    if row['kind'] == 'adjustment' and row['note'] == 'historical dividend entitlement correction':
                        stamp, priority = opened, 1
                sequence = (account_id, 1, str(row.get('ticker', '')), row.get('seq', 0))
                result.append(LedgerEvent(stamp, priority, sequence, kind, row))
        for row in _rows(con,
            'SELECT f.*,d.fill_ts,COALESCE(d.multiplier,1) AS multiplier,'
            'ff.* EXCLUDE(order_id) FROM sim_fills f '
            'LEFT JOIN sim_fill_details d ON d.order_id=f.order_id '
            'LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id '
            'WHERE f.portfolio_id=?', [account_id]):
            if account and row['fill_ts'] is None:
                raise ValueError(f"account-engine fill {row['order_id']} has no authoritative fill_ts")
            stamp = row['fill_ts'] if account else bar_sources.session_bounds(row['fill_date'])[0]
            priority = 0 if account or row['side'] in {'sell', 'cover'} else 1
            result.append(LedgerEvent(stamp, 4, (account_id, priority, row['order_id']), 'fill', row))
    return sorted((event for event in result
                   if (since is None or event.stamp.date() >= since)
                   and (through is None or event.stamp.date() <= through)), key=lambda event: event.key)


def apply_split(con, account_id, ticker, ex, ratio):
    """Change the units of pre-action lots and their signed aggregate position."""
    old_qty = con.execute(
        'SELECT COALESCE(SUM(qty),0) FROM sim_position_lots '
        'WHERE portfolio_id=? AND instrument_id=? AND opened_session<?',
        [account_id, ticker, ex],
    ).fetchone()[0]
    con.execute(
        'UPDATE sim_position_lots SET qty=qty*?,avg_px=avg_px/? '
        'WHERE portfolio_id=? AND instrument_id=? AND opened_session<?',
        [ratio, ratio, account_id, ticker, ex],
    )
    if old_qty:
        con.execute(
            'UPDATE sim_positions SET qty=qty+?,avg_cost=('
            'SELECT SUM(ABS(qty)*avg_px)/SUM(ABS(qty)) FROM sim_position_lots '
            'WHERE portfolio_id=? AND instrument_id=? AND qty<>0) '
            'WHERE portfolio_id=? AND ticker=?',
            [float(old_qty) * (ratio - 1), account_id, ticker, account_id, ticker],
        )


def apply_event(con, event: LedgerEvent, *, on_close=None):
    """Apply one recorded event using the same mutations as normal settlement."""
    row = event.row
    if event.kind == 'operation':
        row['run']()
    elif event.kind == 'fill':
        applied = apply_fill(con, row, row if row.get('cost_profile') else None,
                             persist_fees=False, on_close=on_close)
        if not math.isclose(applied, row['qty'], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"stored fill {row['order_id']} changed quantity during replay")
    elif event.kind == 'split':
        apply_split(con, row['portfolio_id'], row['ticker'], row['ex_date'], row['ratio'])
    elif event.kind == 'settlement':
        from .settle import apply_settlement_event

        apply_settlement_event(con, row['portfolio_id'], row['ticker'], row['kind'],
                               row['qty'], row['price'], row['into_ticker'], row['ratio'],
                               on_close=on_close)
    else:
        amount = money_inputs.finite_number(row['amount'], "cash event amount")
        if event.kind == 'dividend':
            money_inputs.finite_number(row['dps'], "dividend per share", positive=True)
            money_inputs.finite_number(row['qty'], "dividend quantity")
        money_inputs.finite_number(get_cash_value(con, row['portfolio_id']) + amount, "cash after event")
        con.execute('UPDATE portfolios SET cash=cash+? WHERE id=?',
                    [amount, row['portfolio_id']])


def rebuild_state(con, portfolio_ids: Iterable[str] | None = None, *,
                  through: date | None = None, on_close=None) -> None:
    """Rebuild selected accounts from the shared event sequence."""
    ids = (sorted(set(portfolio_ids)) if portfolio_ids is not None else
           [row[0] for row in con.execute('SELECT id FROM portfolios ORDER BY id').fetchall()])
    if not ids:
        return
    sequence = events(con, ids, through=through)
    placeholders = ','.join('?' for _ in ids)
    for table in ('sim_positions', 'sim_position_lots', 'sim_day_trades'):
        con.execute(f'DELETE FROM {table} WHERE portfolio_id IN ({placeholders})', ids)
    con.execute(f'UPDATE portfolios SET cash=COALESCE(initial_cash,?) WHERE id IN ({placeholders})',
                [INITIAL_CASH, *ids])
    for event in sequence:
        apply_event(con, event, on_close=on_close)


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
    if abs(delta) < 1e-10 and existing[0]:
        return False
    apply_cash_event(con, {**event, 'amount': delta})
    return True


def closed_trades(con, account_id: str) -> list[dict]:
    """Project matched lots by running the ledger on an isolated in-memory copy.

    The caller may be a read-only API connection. No result query rewrites the
    real account or maintains its own position/lot arithmetic.
    """
    outcomes = []

    def collect(connection, matched, side, qty, px, multiplier, fee):
        for lot in matched:
            opening = connection.execute(
                'SELECT f.qty*f.fill_px*COALESCE(d.multiplier,1),COALESCE(ff.total_usd,0) '
                'FROM sim_fills f LEFT JOIN sim_fill_details d ON d.order_id=f.order_id '
                'LEFT JOIN sim_fill_fees ff ON ff.order_id=f.order_id WHERE f.order_id=?',
                [lot.open_order_id],
            ).fetchone()
            basis = lot.qty * lot.avg_px * multiplier
            opening_fee = float(opening[1]) * basis / float(opening[0])
            gross = lot.qty * (px - lot.avg_px) * multiplier * (-1 if side == 'cover' else 1)
            net = gross - opening_fee - fee * lot.qty / qty
            outcomes.append({'entry_session': lot.opened_session, 'net_bp': net / basis * 10_000})

    with replay_connection(con, account_id) as target:
        rebuild_state(target, [account_id], on_close=collect)
    return outcomes


def _insert_rows(target, table: str, rows: list, *, bulk: bool) -> None:
    """Insert fetched rows; ``bulk`` binds each value cast to its column type in
    multi-row statements, the same values as one-row-at-a-time ``executemany``."""
    if not rows:
        return
    if not bulk:
        marks = ','.join('?' for _ in rows[0])
        target.executemany(f'INSERT INTO {table} VALUES ({marks})', rows)
        return
    types = [row[0] for row in target.execute(
        'SELECT data_type FROM duckdb_columns() WHERE table_name=? '
        'AND database_name=current_database() ORDER BY column_index', [table]).fetchall()]
    marks = '(' + ','.join(f'?::{kind}' for kind in types) + ')'
    for start in range(0, len(rows), 256):
        chunk = rows[start:start + 256]
        target.execute(f'INSERT INTO {table} VALUES ' + ','.join([marks] * len(chunk)),
                       [value for row in chunk for value in row])


@contextmanager
def replay_connection(con, account_id: str, *, offline: bool = False):
    """Isolate ledger projection from persisted account state and read-only callers.

    ``offline`` (projection checkpoints) leaves the state tables empty, since the
    projection resets them anyway, and copies rows with bulk inserts.
    """
    tables = ('portfolios', 'portfolio_accounts', 'sim_positions', 'sim_position_lots',
              'sim_day_trades', 'sim_fills', 'sim_fill_details', 'sim_fill_fees',
              'sim_dividends', 'sim_settlements', 'sim_cash_events', 'account_events',
              'split_adjustments')
    present = ({row[0] for row in con.execute(
        'SELECT table_name FROM information_schema.tables '
        'WHERE table_name IN (SELECT UNNEST(?::VARCHAR[]))', [list(tables)]).fetchall()}
        if offline else None)
    with db.connect(':memory:') as target:
        for table in tables:
            if not (table in present if offline else table_exists(con, table)):
                continue
            ddl = con.execute('SELECT sql FROM duckdb_tables() WHERE table_name=? '
                              'AND database_name=current_database()', [table]).fetchone()[0]
            target.execute(ddl)
            columns = [row[0] for row in con.execute(f'SELECT * FROM {table} LIMIT 0').description]
            if 'portfolio_id' in columns:
                clause, params = ' WHERE portfolio_id=?', [account_id]
            elif table == 'portfolios':
                clause, params = ' WHERE id=?', [account_id]
            elif 'order_id' in columns:
                clause = ' WHERE order_id IN (SELECT order_id FROM sim_fills WHERE portfolio_id=?)'
                params = [account_id]
            else:
                clause, params = '', []
            if offline and table in _STATE_TABLES:
                continue
            rows = con.execute(f'SELECT * FROM {table}' + clause, params).fetchall()
            _insert_rows(target, table, rows, bulk=offline)
        target.execute(con.execute(
            "SELECT sql FROM duckdb_views() WHERE view_name='portfolio_accounts_v' "
            'AND database_name=current_database()').fetchone()[0])
        yield target


def state(con, account_id: str) -> dict:
    """Canonical persisted cash, aggregate basis and FIFO lot state."""
    return {
        'cash': float(con.execute('SELECT cash FROM portfolios WHERE id=?', [account_id]).fetchone()[0]),
        'positions': {ticker: {'qty': float(qty), 'avg_cost': float(basis)}
                      for ticker, qty, basis in con.execute(
                          'SELECT ticker,qty,avg_cost FROM sim_positions '
                          'WHERE portfolio_id=? AND qty<>0 ORDER BY ticker', [account_id]).fetchall()},
        'lots': [{'instrument_id': ticker, 'opened_session': opened.isoformat(),
                  'open_order_id': order_id, 'qty': float(qty), 'avg_px': float(px)}
                 for ticker, opened, order_id, qty, px in con.execute(
                     'SELECT instrument_id,opened_session,open_order_id,qty,avg_px '
                     'FROM sim_position_lots WHERE portfolio_id=? AND qty<>0 '
                     'ORDER BY instrument_id,opened_session,open_order_id', [account_id]).fetchall()],
    }


def projected_state(con, account_id: str, *, through=None, before_order_id=None) -> dict | None:
    """Read a chronological prefix without maintaining a second accounting implementation."""
    with replay_connection(con, account_id) as target:
        if before_order_id is None:
            rebuild_state(target, [account_id], through=through)
        else:
            sequence = events(target, [account_id], through=through)
            for table in ('sim_positions', 'sim_position_lots', 'sim_day_trades'):
                target.execute(f'DELETE FROM {table}')
            target.execute('UPDATE portfolios SET cash=COALESCE(initial_cash,?)', [INITIAL_CASH])
            for event in sequence:
                if event.kind == 'fill' and event.row['order_id'] == before_order_id:
                    break
                apply_event(target, event)
            else:
                return None
        return state(target, account_id)


def equity_checkpoint(con, account_id: str, day: date, snapshot: dict, *,
                      available_at=None, carried_marks=None) -> dict:
    """Value a ledger snapshot with the account's source-selected observable marks."""
    from . import valuation

    equity = snapshot['cash']
    for ticker, position in snapshot['positions'].items():
        price = (carried_marks or {}).get(ticker)
        if price is None:
            price = valuation.mark(con, account_id, ticker, day, available_at=available_at).price
        equity += position['qty'] * price
    return dict(date=day.isoformat(), cash=snapshot['cash'], equity=equity,
                n_positions=len(snapshot['positions']))


def states_match(expected, observed) -> bool:
    """Compare identities exactly, quantities tightly and dollars within half a cent."""
    if isinstance(expected, dict):
        return (isinstance(observed, dict) and expected.keys() == observed.keys()
                and all(states_match(expected[k], observed[k]) if k not in {'qty'} else
                        math.isclose(expected[k], observed[k], rel_tol=0, abs_tol=1e-9)
                        for k in expected))
    if isinstance(expected, list):
        return (isinstance(observed, list) and len(expected) == len(observed)
                and all(states_match(a, b) for a, b in zip(expected, observed, strict=True)))
    if isinstance(expected, float):
        return isinstance(observed, (float, int)) and abs(expected - observed) <= 0.005
    return expected == observed


@contextmanager
def projection_checkpoints(limit: int = 8):
    """Let `projected_states_at_closes` resume from an exact earlier prefix.

    An offline replay asks for dividend entitlements every session, and each
    request re-applied the whole ledger from inception. Inside this context a
    request restores the state tables saved after the longest previously
    applied event prefix that is identical, row for row, to its own, then
    applies only the remaining events. Same events, same order, same
    arithmetic: the snapshots are unchanged. Live callers never enter it.
    """
    global _CHECKPOINTS
    previous, _CHECKPOINTS = _CHECKPOINTS, {"limit": limit, "accounts": {}}
    try:
        yield
    finally:
        _CHECKPOINTS = previous


def _prefix_digests(sequence) -> list[str]:
    digest, out = hashlib.sha256(), [hashlib.sha256().hexdigest()]
    for event in sequence:
        digest.update(repr((event.key, event.kind, sorted(event.row.items()))).encode())
        out.append(digest.hexdigest())
    return out


def _state_rows(target) -> dict:
    return {
        'cash': target.execute('SELECT cash FROM portfolios').fetchall(),
        **{table: target.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
           for table in _STATE_TABLES},
    }


def _restore_state(target, rows: dict) -> None:
    (cash,), = rows['cash']
    target.execute('UPDATE portfolios SET cash=?', [cash])
    for table in _STATE_TABLES:
        _insert_rows(target, table, rows[table], bulk=True)


def projected_states_at_closes(con, account_id: str, days) -> dict:
    """Project multiple dividend entitlement dates with one chronological replay."""
    days = sorted(set(days))
    if not days:
        return {}
    snapshots = {}
    with replay_connection(con, account_id, offline=_CHECKPOINTS is not None) as target:
        sequence = events(target, [account_id], through=days[-1])
        for table in _STATE_TABLES:
            target.execute(f'DELETE FROM {table}')
        target.execute('UPDATE portfolios SET cash=COALESCE(initial_cash,?)', [INITIAL_CASH])
        position, saved, digests = 0, None, None
        if _CHECKPOINTS is not None:
            initial = target.execute('SELECT * FROM portfolios').fetchall()
            key = (account_id, repr(initial), repr(sorted(portfolio_account(
                target, account_id).items())))
            saved = _CHECKPOINTS['accounts'].setdefault(key, [])
            digests = _prefix_digests(sequence)
            first = sum(1 for event in sequence if event.stamp.date() <= days[0])
            usable = [item for item in saved
                      if item[0] <= first and digests[item[0]] == item[1]]
            if usable:
                position, _, rows = max(usable, key=lambda item: item[0])
                _restore_state(target, rows)
        for day in days:
            while position < len(sequence) and sequence[position].stamp.date() <= day:
                apply_event(target, sequence[position])
                position += 1
            snapshots[day] = state(target, account_id)
            if saved is not None and all(item[:2] != (position, digests[position])
                                         for item in saved):
                saved.append((position, digests[position], _state_rows(target)))
                del saved[:-_CHECKPOINTS['limit']]
    return snapshots


def event_identity(event: LedgerEvent) -> str:
    """The complete primary key, including account and effective date."""
    row = event.row
    keys = {'fill': ('portfolio_id', 'fill_date', 'order_id'),
            'cash': ('portfolio_id', 'event_date', 'seq'),
            'split': ('portfolio_id', 'ticker', 'ex_date'),
            'dividend': ('portfolio_id', 'ticker', 'ex_date'),
            'settlement': ('portfolio_id', 'ticker', 'effective')}
    return json.dumps([event.kind, *[row[key] for key in keys[event.kind]]],
                      separators=(',', ':'), default=str)


def checkpoints(con, account_id: str) -> dict:
    """Source marks retained with each atomic accounting cache publication."""
    if not table_exists(con, 'account_events'):
        return {}
    return {date.fromisoformat(item['date']): item for (raw,) in con.execute(
        "SELECT payload FROM account_events WHERE portfolio_id=? "
        "AND kind='equity_checkpoint' ORDER BY id", [account_id],
    ).fetchall() for item in [json.loads(raw)]}


def record_checkpoint(con, account_id: str, day: date, marks: dict, now) -> None:
    from engine.money.halts import record_event

    payload = dict(date=day.isoformat(), marks=marks)
    record_event(con, account_id, 'equity_checkpoint', payload, now=now)
