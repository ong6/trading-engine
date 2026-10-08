"""Reg T margin, financing and per-account day-trading rules."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import duckdb

from engine.accounts import account_portfolios, portfolio_account
from engine.lib.util import table_exists

from . import bar_sources, costs, ledger, nyse, portfolio
from .schema import next_order_id

PDT_MIN_EQUITY = 25_000.0
PDT_MAX_DAY_TRADES = 3
PDT_WINDOW_SESSIONS = 5
PDT_RESTRICTION_DAYS = 90
DAY_TRADE_RULES = frozenset({"pdt_25k_legacy", "intraday_margin_2026"})


@dataclass(frozen=True)
class MarginState:
    equity: float
    long_market_value: float
    short_market_value: float
    initial_requirement: float
    maintenance_requirement: float
    initial_excess: float
    maintenance_excess: float


@dataclass(frozen=True)
class PDTResult:
    allowed: bool
    reason: str | None
    creates_day_trade: bool
    trailing_day_trades: int
    rule: str


def day_trade_rule(con: duckdb.DuckDBPyConnection, portfolio_id: str) -> str:
    """Read R10 from the account spec; legacy is the compatibility default."""
    value = portfolio_account(con, portfolio_id)["day_trade_rule"]
    if value not in DAY_TRADE_RULES:
        raise ValueError(f"unknown day_trade_rule {value!r}")
    return value


def _marks(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    day: date,
    *,
    price_source: str,
    as_of: datetime | None,
    available_at: datetime | None,
) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for ticker, qty in con.execute(
        "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<>0",
        [portfolio_id],
    ).fetchall():
        close = _mark_at(
            con, ticker, day, price_source=price_source,
            as_of=as_of, available_at=available_at,
        )
        if close is not None:
            out[ticker] = (float(qty), close)
    return out


def _mark_at(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    day: date,
    *,
    price_source: str,
    as_of: datetime | None,
    available_at: datetime | None,
) -> float | None:
    if as_of is None:
        return bar_sources.latest_close(
            con, ticker, day, source=price_source, available_at=available_at,
        )
    stamp = (
        as_of if as_of.utcoffset() is None
        else as_of.astimezone(timezone.utc).replace(tzinfo=None)
    )
    opened, closed = bar_sources.session_bounds(day)
    if stamp >= closed:
        return bar_sources.latest_close(
            con, ticker, day, source=price_source, available_at=available_at,
        )
    if stamp > opened:
        minute_source = (
            "massive_minute" if price_source == "massive_daily"
            else "intraday_prices"
        )
        bars = bar_sources.minute_bars(
            con, ticker, day, source=minute_source, available_at=available_at,
        )
        eligible = [
            bar.close for bar in bars
            if bar.ts + timedelta(minutes=1) <= stamp
        ]
        if eligible:
            return eligible[-1]
    return bar_sources.latest_close(
        con, ticker, day, source=price_source, available_at=available_at,
        strictly_before=True,
    )


def margin_state(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    day: date,
    *,
    projected: tuple[str, str, float, float] | None = None,
    fees: float = 0.0,
    price_source: str = "prices",
    as_of: datetime | None = None,
    available_at: datetime | None = None,
) -> MarginState:
    """Return current or post-fill Reg T initial and maintenance excess."""
    cash = portfolio.get_cash(con, portfolio_id) - fees
    marks = _marks(
        con, portfolio_id, day, price_source=price_source,
        as_of=as_of, available_at=available_at,
    )
    if projected is not None:
        ticker, side, qty, price = projected
        current = marks.get(ticker, (0.0, price))[0]
        if side == "buy":
            if current < 0:
                raise ValueError("buy cannot close a short; use cover")
            cash -= qty * price
            marks[ticker] = (current + qty, price)
        elif side == "sell":
            qty = min(qty, max(current, 0.0))
            cash += qty * price
            marks[ticker] = (current - qty, price)
        elif side == "short":
            if current > 0:
                raise ValueError("short cannot close a long; use sell")
            cash += qty * price
            marks[ticker] = (current - qty, price)
        elif side == "cover":
            qty = min(qty, abs(min(current, 0.0)))
            cash -= qty * price
            marks[ticker] = (current + qty, price)
        else:
            raise ValueError(f"unknown side {side!r}")
    long_value = sum(qty * price for qty, price in marks.values() if qty > 0)
    short_value = sum(abs(qty) * price for qty, price in marks.values() if qty < 0)
    short_share_floor = sum(abs(qty) * 5 for qty, _price in marks.values() if qty < 0)
    equity = cash + long_value - short_value
    initial = 0.5 * long_value + 0.5 * short_value
    maintenance = 0.25 * long_value + max(0.30 * short_value, short_share_floor)
    return MarginState(
        equity, long_value, short_value, initial, maintenance,
        equity - initial, equity - maintenance,
    )


def initial_margin_allows(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    day: date,
    *,
    fees: float = 0.0,
    price_source: str = "prices",
    as_of: datetime | None = None,
    available_at: datetime | None = None,
) -> bool:
    state = margin_state(
        con, portfolio_id, day,
        projected=(ticker, side, qty, price), fees=fees,
        price_source=price_source, as_of=as_of, available_at=available_at,
    )
    return state.initial_excess >= -1e-9


def _window_start(day: date, count: int) -> date:
    sessions: list[date] = []
    cursor = day
    while len(sessions) < count:
        if nyse.is_session(cursor):
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    return min(sessions)


def _prior_close_equity(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, day: date,
) -> float:
    row = con.execute(
        "SELECT equity FROM sim_equity WHERE portfolio_id=? AND date<? "
        "ORDER BY date DESC LIMIT 1",
        [portfolio_id, day],
    ).fetchone()
    if row is not None:
        return float(row[0])
    row = con.execute(
        "SELECT COALESCE(initial_cash,cash) FROM portfolios WHERE id=?", [portfolio_id]
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    return float(row[0])


def would_create_day_trade(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    instrument_id: str,
    side: str,
    qty: float,
    session_date: date,
) -> bool:
    return matched_day_trade_open(
        con, portfolio_id, instrument_id, side, qty, session_date,
    ) is not None


def matched_day_trade_open(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    instrument_id: str,
    side: str,
    qty: float,
    session_date: date,
) -> int | None:
    """Return a same-session opening lot matched first for PDT purposes."""
    if side not in {"sell", "cover"}:
        return None
    sign = ">0" if side == "sell" else "<0"
    rows = con.execute(
        "SELECT l.open_order_id,GREATEST(ABS(l.qty)-COALESCE(("
        "SELECT SUM(f.qty) FROM sim_day_trades d JOIN sim_fills f "
        "ON f.order_id=d.close_order_id WHERE d.portfolio_id=l.portfolio_id "
        "AND d.open_order_id=l.open_order_id),0),0) FROM sim_position_lots l "
        f"WHERE portfolio_id=? AND instrument_id=? AND opened_session=? AND qty{sign} "
        "ORDER BY open_order_id",
        [portfolio_id, instrument_id, session_date],
    ).fetchall()
    for order_id, available in rows:
        if min(qty, float(available)) > 1e-12:
            return int(order_id)
    return None


def trailing_day_trades(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, day: date,
) -> int:
    start = _window_start(day, PDT_WINDOW_SESSIONS)
    return int(con.execute(
        "SELECT COUNT(*) FROM sim_day_trades WHERE portfolio_id=? "
        "AND session_date>=? AND session_date<=?",
        [portfolio_id, start, day],
    ).fetchone()[0])


def _restricted_until(
    con: duckdb.DuckDBPyConnection, portfolio_id: str,
) -> date | None:
    if not table_exists(con, "account_state"):
        return None
    columns = {
        row[0] for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='account_state'"
        ).fetchall()
    }
    if "pdt_restricted_until" not in columns:
        return None
    row = con.execute(
        "SELECT pdt_restricted_until FROM account_state WHERE portfolio_id=?",
        [portfolio_id],
    ).fetchone()
    return row[0] if row else None


def _flag_pdt(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, day: date,
) -> None:
    if not table_exists(con, "account_state"):
        return
    restricted = day + timedelta(days=PDT_RESTRICTION_DAYS)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "UPDATE account_state SET pdt_flagged_at=COALESCE(pdt_flagged_at,?),"
        "pdt_restricted_until=GREATEST(COALESCE(pdt_restricted_until,?),?),updated_at=? "
        "WHERE portfolio_id=?",
        [now, restricted, restricted, now, portfolio_id],
    )


def pdt_check(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    instrument_id: str,
    side: str,
    qty: float,
    session_date: date,
    *,
    price: float | None = None,
    price_source: str | None = None,
    as_of: datetime | None = None,
    available_at: datetime | None = None,
) -> PDTResult:
    """Apply the selected R10 rule before an account fill."""
    rule = day_trade_rule(con, portfolio_id)
    creates = would_create_day_trade(
        con, portfolio_id, instrument_id, side, qty, session_date,
    )
    count = trailing_day_trades(con, portfolio_id, session_date)
    settings = portfolio_account(con, portfolio_id)
    if settings["account_type"] != "margin":
        return PDTResult(True, None, creates, count, rule)
    if rule == "intraday_margin_2026":
        if price is not None and side in {"buy", "short"} and not initial_margin_allows(
            con, portfolio_id, instrument_id, side, qty, price, session_date,
            price_source=price_source or settings["price_source"],
            as_of=as_of, available_at=available_at,
        ):
            return PDTResult(False, "reg_t_initial", creates, count, rule)
        return PDTResult(True, None, creates, count, rule)
    prior_equity = _prior_close_equity(con, portfolio_id, session_date)
    restricted = _restricted_until(con, portfolio_id)
    if (
        restricted is not None
        and session_date <= restricted
        and prior_equity < PDT_MIN_EQUITY
        and side in {"buy", "short"}
    ):
        return PDTResult(False, "pdt_restricted", creates, count, rule)
    if creates and prior_equity < PDT_MIN_EQUITY and count >= PDT_MAX_DAY_TRADES:
        _flag_pdt(con, portfolio_id, session_date)
        return PDTResult(False, "pdt_limit", True, count, rule)
    return PDTResult(True, None, creates, count, rule)


def record_day_trade(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    instrument_id: str,
    close_order_id: int,
    side: str,
    session_date: date,
    *,
    open_order_id: int | None = None,
) -> bool:
    """Record a filled close against its earliest same-session opening lot."""
    if side not in {"sell", "cover"}:
        return False
    if open_order_id is None:
        sign = ">0" if side == "sell" else "<0"
        row = con.execute(
            "SELECT open_order_id FROM sim_position_lots "
            f"WHERE portfolio_id=? AND instrument_id=? AND opened_session=? AND qty{sign} "
            "ORDER BY open_order_id LIMIT 1",
            [portfolio_id, instrument_id, session_date],
        ).fetchone()
        open_order_id = None if row is None else int(row[0])
    if open_order_id is None:
        opening_side = "buy" if side == "sell" else "short"
        row = con.execute(
            "SELECT order_id FROM sim_fills WHERE portfolio_id=? AND ticker=? "
            "AND fill_date=? AND side=? ORDER BY order_id LIMIT 1",
            [portfolio_id, instrument_id, session_date, opening_side],
        ).fetchone()
        open_order_id = None if row is None else int(row[0])
    if open_order_id is None:
        return False
    con.execute(
        "INSERT OR IGNORE INTO sim_day_trades VALUES (?,?,?,?,?)",
        [portfolio_id, session_date, instrument_id, open_order_id, close_order_id],
    )
    return True


def accrue_interest(
    con: duckdb.DuckDBPyConnection,
    day: date,
    *,
    days: int | None = None,
    portfolio_id: str | None = None,
) -> dict:
    """Debit effective-dated margin interest once per account and date."""
    count = 0
    charged = 0.0
    settings_rows = [
        settings for settings in account_portfolios(con, active_only=False)
        if settings["status"] in {"active", "halted"}
        and (portfolio_id is None or settings["portfolio_id"] == portfolio_id)
    ]
    for settings in settings_rows:
        portfolio_id = settings["portfolio_id"]
        cash = portfolio.get_cash(con, portfolio_id)
        if cash >= 0:
            continue
        exists = con.execute(
            "SELECT 1 FROM sim_cash_events WHERE portfolio_id=? AND event_date=? "
            "AND kind='margin_interest'",
            [portfolio_id, day],
        ).fetchone()
        if exists:
            continue
        if days is None:
            last = con.execute(
                "SELECT MAX(event_date) FROM sim_cash_events WHERE portfolio_id=? "
                "AND kind='margin_interest' AND event_date<?", [portfolio_id, day],
            ).fetchone()[0]
            start = last
            if start is None:
                start = day - timedelta(days=1)
                while not nyse.is_session(start):
                    start -= timedelta(days=1)
            accrual_dates = [
                start + timedelta(days=offset)
                for offset in range(1, (day - start).days + 1)
            ]
        else:
            if days < 0:
                raise ValueError("days must be non-negative")
            accrual_dates = [
                day - timedelta(days=offset) for offset in reversed(range(days))
            ]
        fee = sum(
            costs.margin_interest(
                abs(float(cash)), 1, session_date=accrual_date,
                profile=settings["cost_profile"],
            )
            for accrual_date in accrual_dates
        )
        ledger.apply_cash_event(con, {
            "portfolio_id": portfolio_id,
            "event_date": day,
            "kind": "margin_interest",
            "amount": -fee,
            "note": f"{len(accrual_dates)} calendar day(s)",
        })
        count += 1
        charged += fee
    return {"events": count, "charged": charged}


def queue_margin_reductions(
    con: duckdb.DuckDBPyConnection, portfolio_id: str, day: date,
) -> list[int]:
    """Queue proportional next-open sell/covers after a maintenance breach."""
    settings = portfolio_account(con, portfolio_id)
    state = margin_state(
        con, portfolio_id, day, price_source=settings["price_source"],
    )
    if state.maintenance_excess >= 0 or state.maintenance_requirement <= 0:
        return []
    if table_exists(con, "account_events"):
        payload = json.dumps({
            "session_date": day.isoformat(),
            "equity": state.equity,
            "maintenance_requirement": state.maintenance_requirement,
            "maintenance_excess": state.maintenance_excess,
        }, sort_keys=True, separators=(",", ":"))
        prior = con.execute(
            "SELECT 1 FROM account_events WHERE portfolio_id=? AND kind='margin_call' "
            "AND payload=?",
            [portfolio_id, payload],
        ).fetchone()
        if prior is None:
            event_id = int(con.execute(
                "SELECT COALESCE(MAX(id),0)+1 FROM account_events"
            ).fetchone()[0])
            con.execute(
                "INSERT INTO account_events (id,portfolio_id,kind,payload,created_at) "
                "VALUES (?,?, 'margin_call', ?, ?)",
                [event_id, portfolio_id, payload,
                 datetime.now(timezone.utc).replace(tzinfo=None)],
            )
    ratio = min(1.0, -state.maintenance_excess / state.maintenance_requirement)
    queued: list[int] = []
    _opened, close_utc = bar_sources.session_bounds(day)
    now = close_utc
    for ticker, qty in con.execute(
        "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<>0 ORDER BY ticker",
        [portfolio_id],
    ).fetchall():
        side = "sell" if qty > 0 else "cover"
        amount = abs(float(qty)) * ratio
        if amount <= 1e-12:
            continue
        duplicate = con.execute(
            "SELECT 1 FROM sim_orders o JOIN sim_order_details d ON d.order_id=o.id "
            "WHERE o.portfolio_id=? AND o.ticker=? AND o.status='pending' "
            "AND d.state_reason LIKE 'margin_call%'",
            [portfolio_id, ticker],
        ).fetchone()
        if duplicate:
            continue
        order_id = next_order_id(con)
        con.execute(
            "INSERT INTO sim_orders VALUES (?,?,?,?,?,?,'pending',NULL)",
            [order_id, portfolio_id, ticker, side, amount, day],
        )
        con.execute(
            "INSERT INTO sim_order_details "
            "(order_id,instrument_id,instrument_kind,order_type,side,tif,session_date,"
            "received_at,state,state_reason,state_at) "
            "VALUES (?,?,?,'next_open',?,'day',?,?,'queued','margin_call',?)",
            [order_id, ticker, "stock", side, day, now, now],
        )
        queued.append(order_id)
    return queued


def check_maintenance(
    con: duckdb.DuckDBPyConnection, day: date, *, portfolio_id: str | None = None,
) -> dict[str, list[int]]:
    """Queue reductions for every processing margin account below maintenance."""
    out: dict[str, list[int]] = {}
    for settings in account_portfolios(con, active_only=False):
        if settings["status"] not in {"active", "halted", "retiring"}:
            continue
        if portfolio_id is not None and settings["portfolio_id"] != portfolio_id:
            continue
        if settings["account_type"] != "margin":
            continue
        portfolio_id = settings["portfolio_id"]
        queued = queue_margin_reductions(con, portfolio_id, day)
        if queued:
            out[portfolio_id] = queued
    return out
