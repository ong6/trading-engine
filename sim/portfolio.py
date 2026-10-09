"""Position / cash accounting and mark-to-market.

sim_positions and portfolios.cash are current state; sim_equity is persisted by
book/date and restatable only through an explicit league rerun.
State can always be reconstructed from fills, fees, dividends, settlements and
cash events (`rebuild_state`) — that replay is how `--rerun` restores exact
cash/positions after deleting a date's rows.
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb

from engine.lib.util import table_exists

from .execution import FILL_MODEL_VERSION as FILL_MODEL_VERSION
from .ledger import MIN_FILL_USD as MIN_FILL_USD
from .ledger import apply_fill as ledger_apply_fill
from .schema import INITIAL_CASH

# --------------------------------------------------------------------------- #
# fill model version — STAMPED INTO EVERY STORED RESULT
# --------------------------------------------------------------------------- #
# Bump this whenever apply_fill's arithmetic changes. Results produced under
# different versions are NOT comparable, and the only way that stays true rather
# than aspirational is for the version to travel with the numbers.
#   v1  (2026-07-18 → 2026-08-20)  buys clamped to floor(cash / px)
#   v2  (2026-08-20 → 2026-09-06) buys clamped to cash / px, MIN_FILL_USD floor
#   v3  (2026-09-06 → )            same, with simultaneous buys pro-rata scaled
#                                    before application (no order-ID/ticker bias)
#   v4  profile-aware market/fee costs, actual-quantity participation audit,
#       per-book capital, explicit quarantine; baseline_v1 remains v3-equivalent
#   v5  side-aware lots, dollar fees and phase-3 cash-event replay; legacy
#       baseline_v1 fill arithmetic remains v4-equivalent (version in execution.py)

# A buy whose affordable notional falls below this is dust, not a position:
# filling it writes a sim_fills row and an avg_cost for an amount that cannot
# move the book, and rejecting it is the honest outcome. v1 had no explicit
# floor — its effective floor was one whole share, which is $1 for a penny
# stock and $47,988 for a reverse-split-mangled leveraged ETF.
# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def get_positions(con: duckdb.DuckDBPyConnection, pf_id: str) -> dict[str, dict]:
    """{ticker: {'qty': float, 'avg_cost': float}} for open positions (qty != 0).

    Filter is `qty != 0` (not `qty > 0`) so any nonzero position — including an
    accidental short — always counts in mark-to-market and the strategy view,
    rather than silently vanishing (belt-and-braces for the apply_fill sell guard).
    """
    rows = con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty != 0",
        [pf_id],
    ).fetchall()
    return {t: {"qty": q, "avg_cost": c} for t, q, c in rows}


def get_cash(con: duckdb.DuckDBPyConnection, pf_id: str) -> float:
    return float(con.execute(
        "SELECT cash FROM portfolios WHERE id = ?", [pf_id]
    ).fetchone()[0])


def get_initial_cash(con: duckdb.DuckDBPyConnection, pf_id: str) -> float:
    """The immutable capital assigned when this portfolio was created."""
    row = con.execute(
        "SELECT initial_cash FROM portfolios WHERE id = ?", [pf_id]
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown portfolio {pf_id!r}")
    return INITIAL_CASH if row[0] is None else float(row[0])


def position_open_since(con: duckdb.DuckDBPyConnection, pf_id: str, ticker: str):
    """The fill_date the current open lot was opened on: the earliest buy after
    the most recent sell (or ever, if never sold). None if no buys. Used for the
    MR time stop.

    ORDER BY … LIMIT 1 instead of MIN/MAX on purpose: DuckDB 1.5.4 has an
    internal error ("Attempted to access index 0 within vector of size 0") when
    a MIN/MAX aggregate WITH a WHERE clause scans rows appended earlier in the
    SAME transaction — exactly what happens here, since the league day-step is
    one transaction and fill_pending appends to sim_fills before strategies run.
    Plain filtered scans and ORDER BY/LIMIT are unaffected. Don't "simplify"
    these back to MIN/MAX while the engine is on 1.5.x.
    """
    row = con.execute(
        "SELECT fill_date FROM sim_fills "
        "WHERE portfolio_id = ? AND ticker = ? AND side = 'sell' "
        "ORDER BY fill_date DESC LIMIT 1",
        [pf_id, ticker],
    ).fetchone()
    last_sell = row[0] if row else None
    if last_sell is None:
        row = con.execute(
            "SELECT fill_date FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy' "
            "ORDER BY fill_date ASC LIMIT 1",
            [pf_id, ticker],
        ).fetchone()
    else:
        row = con.execute(
            "SELECT fill_date FROM sim_fills "
            "WHERE portfolio_id = ? AND ticker = ? AND side = 'buy' AND fill_date > ? "
            "ORDER BY fill_date ASC LIMIT 1",
            [pf_id, ticker, last_sell],
        ).fetchone()
    return row[0] if row else None


def close_on(con: duckdb.DuckDBPyConnection, ticker: str, d: date):
    """(close, is_carried): the close on/last-known before d. Carried if the
    exact date's bar is missing (never fabricated — the last real close stands)."""
    exact = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date = ?", [ticker, d]
    ).fetchone()
    if exact is not None and exact[0] is not None:
        return float(exact[0]), False
    row = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        [ticker, d],
    ).fetchone()
    if row is None or row[0] is None:
        return None, True
    return float(row[0]), True


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
def apply_fill(con: duckdb.DuckDBPyConnection, fill: dict) -> float:
    """Delegate legacy buy/sell accounting to the common side-aware ledger."""
    return ledger_apply_fill(con, fill)


def mark_to_market(con: duckdb.DuckDBPyConnection, pf_id: str, d: date) -> dict:
    """Value a portfolio at d's close and persist its sim_equity row.

    equity = cash + Σ qty*close; a missing close carries the last known close
    (flagged in the returned dict). Idempotent per (portfolio, date) via the PK
    — callers guard against re-running a date at the league level.
    """
    cash = get_cash(con, pf_id)
    positions = get_positions(con, pf_id)
    mkt = 0.0
    carried = []
    for tk, p in positions.items():
        close, is_carried = close_on(con, tk, d)
        if close is None:
            carried.append(tk)  # no price at all — contributes 0, flagged
            continue
        if is_carried:
            carried.append(tk)
        mkt += p["qty"] * close
    equity = cash + mkt
    n_pos = len(positions)
    con.execute(
        "INSERT OR REPLACE INTO sim_equity "
        "(portfolio_id, date, equity, cash, n_positions) VALUES (?, ?, ?, ?, ?)",
        [pf_id, d, equity, cash, n_pos],
    )
    return {"equity": equity, "cash": cash, "n_positions": n_pos, "carried": carried}


# --------------------------------------------------------------------------- #
# corporate actions
# --------------------------------------------------------------------------- #
DIVIDEND_LOOKBACK_DAYS = 10  # how far back phase a0 looks for late-arriving rows


def credit_dividends(con: duckdb.DuckDBPyConnection, d: date,
                     lookback_days: int = DIVIDEND_LOOKBACK_DAYS, *,
                     portfolio_id: str | None = None) -> dict:
    """Phase a0 of the league day-step: pay every cash dividend with an ex-date in
    (d − lookback_days, d] that has not been credited yet.

    Why a window and not `ex_date = d`: the corporate-actions collector runs in
    the same nightly, and yfinance publishes a dividend the session AFTER its
    ex-date (actions_fetch_log: WBS ex 2026-08-10 appeared 08-11; JNJ ex 08-25
    appeared 08-26). An exact-date match therefore never saw a row in time, and
    from 2026-07-17 to 2026-09-01 not one dividend was credited to any book
    while `vs SPY` was computed against SPY's TOTAL return. The window catches a
    row whenever it lands; the (portfolio, ticker, ex_date) primary key on
    sim_dividends keeps every credit exactly-once.

    Entitlement is the signed position at the close of ex_date − 1, projected
    through the shared chronological ledger for both first runs and retries. Cash += qty × dps, one append-only
    sim_dividends row per credit, stamped with the TRUE ex_date so rebuild_state
    replays it at the right point in the cash trajectory. A short position has
    negative entitlement and therefore records and applies a dividend debit.

    Returns {'credited': n_rows, 'amount': total_cash}. A store without a
    corporate_actions table (an old copy) credits nothing rather than failing.
    """
    out = {"credited": 0, "amount": 0.0}
    if not table_exists(con, "corporate_actions"):
        return out
    since = d - timedelta(days=lookback_days)
    divs = con.execute(
        "SELECT ticker, ex_date, value FROM corporate_actions "
        "WHERE kind = 'dividend' AND ex_date > ? AND ex_date <= ? "
        "AND value IS NOT NULL AND value > 0 ORDER BY ex_date, ticker",
        [since, d],
    ).fetchall()
    if not divs:
        return out
    already = set(con.execute(
        "SELECT portfolio_id, ticker, ex_date FROM sim_dividends "
        "WHERE ex_date > ? AND ex_date <= ?", [since, d]
    ).fetchall())

    clause = "pa.pa_engine<>'account'" if portfolio_id is None else "p.id=?"
    params = [] if portfolio_id is None else [portfolio_id]
    for (pf_id,) in con.execute(
        "SELECT p.id FROM portfolios p JOIN portfolio_accounts_v pa ON pa.portfolio_id=p.id "
        f"WHERE p.active AND {clause} ORDER BY p.id", params,
    ).fetchall():
        from .ledger import projected_states_at_closes

        tickers = {row[0] for row in con.execute(
            'SELECT ticker FROM sim_fills WHERE portfolio_id=? UNION '
            'SELECT into_ticker FROM sim_settlements WHERE portfolio_id=?',
            [pf_id, pf_id]).fetchall()}
        eligible = [(tk, ex, value) for tk, ex, value in divs
                    if tk in tickers and (pf_id, tk, ex) not in already]
        prefixes = projected_states_at_closes(
            con, pf_id, {ex - timedelta(days=1) for _, ex, _ in eligible})
        for tk, ex, value in eligible:
            qty = prefixes[ex - timedelta(days=1)]['positions'].get(tk, {}).get('qty', 0.0)
            if abs(qty) < 1e-9:
                continue
            dps = float(value)
            amount = qty * dps
            con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                        [amount, pf_id])
            con.execute(
                "INSERT INTO sim_dividends "
                "(portfolio_id, ticker, ex_date, qty, dps, amount) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [pf_id, tk, ex, qty, dps, amount],
            )
            out["credited"] += 1
            out["amount"] += amount
    return out


# --------------------------------------------------------------------------- #
# reconstruction (used by --rerun)
# --------------------------------------------------------------------------- #
def rebuild_state(
    con: duckdb.DuckDBPyConnection, portfolio_ids: list[str] | tuple[str, ...] | None = None,
) -> None:
    """Delegate all phase-ordered reconstruction to the common ledger."""
    from .ledger import rebuild_state as ledger_rebuild_state

    ledger_rebuild_state(con, portfolio_ids=portfolio_ids)
