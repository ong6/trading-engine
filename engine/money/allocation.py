"""Portfolio-wide exposure allocation for independently funded accounts."""
from __future__ import annotations

from datetime import date

from engine.lib.util import table_exists

TOTAL_GROSS_CAP_FRACTION = 1.0


class AllocationRefused(ValueError):
    """A new opening order would breach the account-engine aggregate cap."""


def total_gross_cap(con, *, include_account: str | None = None) -> float:
    """Return 1x independently funded capital for active account portfolios."""
    clause, params = "", []
    if include_account is not None:
        clause, params = " OR p.id=?", [include_account]
    row = con.execute(
        "SELECT COALESCE(SUM(p.initial_cash),0) FROM portfolios p "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=p.id "
        f"WHERE pa.pa_engine='account' AND (pa.pa_status='active'{clause})",
        params,
    ).fetchone()
    return float(row[0]) * TOTAL_GROSS_CAP_FRACTION


def _mark(con, ticker: str, as_of: date) -> float:
    row = con.execute(
        "SELECT close FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
        [ticker, as_of],
    ).fetchone()
    if row is None or row[0] is None:
        raise AllocationRefused(f"total_exposure_cap: no mark for {ticker}")
    return float(row[0])


def total_gross_exposure(con, as_of: date) -> float:
    positions = con.execute(
        "SELECT sp.ticker,sp.qty FROM sim_positions sp "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=sp.portfolio_id "
        "WHERE pa.pa_engine='account' AND pa.pa_status IN ('active','halted')"
    ).fetchall()
    gross = sum(abs(float(qty) * _mark(con, ticker, as_of)) for ticker, qty in positions)
    pending = con.execute(
        "SELECT o.ticker,o.qty FROM sim_orders o "
        "JOIN portfolio_accounts_v pa ON pa.portfolio_id=o.portfolio_id "
        "WHERE pa.pa_engine='account' AND o.status='pending' "
        "AND o.side IN ('buy','short')"
    ).fetchall()
    gross += sum(abs(float(qty) * _mark(con, ticker, as_of)) for ticker, qty in pending)
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
    return sum(abs(float(qty) * _mark(con, ticker, as_of)) for ticker, qty in rows)
