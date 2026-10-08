"""Portfolio-wide exposure allocation for independently funded accounts."""
from __future__ import annotations

from datetime import date

from engine.lib.util import table_exists
from engine.paper_accounts import AccountRefused
from sim import bar_sources

TOTAL_GROSS_CAP_FRACTION = 1.0


class AllocationRefused(AccountRefused):
    """A new opening order would breach the account-engine aggregate cap."""


def total_gross_cap(con, *, include_account: str | None = None) -> float:
    """Return 1x independently funded capital for active account portfolios."""
    clause, params = "", []
    if include_account is not None:
        clause, params = " OR p.id=?", [include_account]
    row = con.execute(
        "SELECT COALESCE(SUM(p.initial_cash),0) FROM portfolios p "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=p.id "
        f"WHERE pa.pa_engine='account' "
        f"AND (pa.pa_status IN ('active','halted','retiring'){clause})",
        params,
    ).fetchone()
    return float(row[0]) * TOTAL_GROSS_CAP_FRACTION


def _mark(con, ticker: str, as_of: date, price_source: str) -> float | None:
    relation, column = (
        ("free_daily_bars", "c") if price_source == "massive_daily" else ("prices", "close")
    )
    if not table_exists(con, relation):
        return None
    row = con.execute(
        f"SELECT {column} FROM {relation} WHERE ticker=? AND date<=? "
        "ORDER BY date DESC LIMIT 1", [ticker, as_of],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def total_gross_exposure(con, as_of: date) -> float:
    positions = con.execute(
        "SELECT sp.ticker,sp.qty,pa.pa_price_source FROM sim_positions sp "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=sp.portfolio_id "
        "WHERE pa.pa_engine='account' AND pa.pa_status IN ('active','halted','retiring')"
    ).fetchall()
    gross = sum(
        abs(float(qty) * mark)
        for ticker, qty, source in positions
        if (mark := _mark(con, ticker, as_of, source)) is not None
    )
    pending = con.execute(
        "SELECT o.ticker,o.qty,pa.pa_price_source FROM sim_orders o "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=o.portfolio_id "
        "WHERE pa.pa_engine='account' AND o.status='pending' "
        "AND o.side IN ('buy','short')"
    ).fetchall()
    gross += sum(
        abs(float(qty) * mark)
        for ticker, qty, source in pending
        if (mark := _mark(con, ticker, as_of, source)) is not None
    )
    return gross


def require_total_capacity(con, account_id: str, requested_notional: float,
                           as_of: date) -> None:
    if requested_notional <= 0:
        raise AllocationRefused("total_exposure_cap: requested notional must be positive")
    if total_gross_exposure(con, as_of) + requested_notional > total_gross_cap(
        con, include_account=account_id,
    ):
        raise AllocationRefused("total_exposure_cap")


def account_gross(con, account_id: str, as_of: date) -> float:
    if not table_exists(con, "sim_positions"):
        return 0.0
    rows = con.execute(
        "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=?", [account_id]
    ).fetchall()
    source = con.execute(
        "SELECT pa_price_source FROM portfolio_accounts_v WHERE portfolio_id=?", [account_id]
    ).fetchone()
    return sum(
        abs(float(qty) * mark)
        for ticker, qty in rows
        if (mark := _mark(con, ticker, as_of, source[0])) is not None
    )


def require_execution_capacity(
    con,
    account_id: str,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    as_of: date,
    *,
    available_at=None,
) -> None:
    """Recheck the aggregate cap from positions at execution-time prices.

    Pending-order reservations are intentionally absent: the order being executed
    was already reserved at intake, and counting it again is the reviewed defect.
    Previously completed fills are present in ``sim_positions`` and therefore do
    contribute in chronological settlement order.
    """
    gross = 0.0
    target_qty = 0.0
    rows = con.execute(
        "SELECT sp.portfolio_id,sp.ticker,sp.qty,pa.pa_price_source "
        "FROM sim_positions sp JOIN portfolio_accounts_v pa "
        "ON pa.portfolio_id=sp.portfolio_id "
        "WHERE pa.pa_engine='account' "
        "AND pa.pa_status IN ('active','halted','retiring') AND sp.qty<>0"
    ).fetchall()
    for portfolio_id, instrument_id, held, source in rows:
        held = float(held)
        if portfolio_id == account_id and instrument_id == ticker:
            mark = price
            target_qty = held
        else:
            mark = bar_sources.latest_close(
                con, instrument_id, as_of, source=source, available_at=available_at,
            )
            if mark is None:
                raise AllocationRefused("total_exposure_mark_unavailable")
        gross += abs(held * mark)
    if side == "buy":
        projected = target_qty + quantity
    elif side == "short":
        projected = target_qty - quantity
    else:
        return
    gross += abs(projected * price) - abs(target_qty * price)
    if gross > total_gross_cap(con, include_account=account_id) + 1e-9:
        raise AllocationRefused("total_exposure_cap")
