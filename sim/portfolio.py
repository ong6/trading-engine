"""Position / cash accounting and mark-to-market.

sim_positions and portfolios.cash are current state; sim_equity is persisted by
book/date and restatable only through an explicit league rerun.
State can always be reconstructed from sim_fills (`rebuild_state`) — that replay
is how `--rerun` restores exact cash/positions after deleting a date's rows.
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb

from engine.lib.log import get_logger
from engine.lib.util import table_exists

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
FILL_MODEL_VERSION = "v4"

# A buy whose affordable notional falls below this is dust, not a position:
# filling it writes a sim_fills row and an avg_cost for an amount that cannot
# move the book, and rejecting it is the honest outcome. v1 had no explicit
# floor — its effective floor was one whole share, which is $1 for a penny
# stock and $47,988 for a reverse-split-mangled leveraged ETF.
MIN_FILL_USD = 1.0

log = get_logger("apply_fill")


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
    """Apply one fill to sim_positions + portfolios.cash. `fill` carries
    portfolio_id, ticker, side, qty, fill_px.

    Returns the qty ACTUALLY applied, which may be less than the requested qty:

    - Sells are close-only: if the requested qty exceeds the held qty it is
      clamped to the held qty (never go negative) and a WARN is printed.
    - Buys are cash-bounded: if the notional exceeds available cash the qty is
      reduced to cash / fill_px so cash never goes negative (no phantom leverage
      from a signal-day → next-open gap-up). If the affordable notional is below
      MIN_FILL_USD the fill is rejected (returns 0.0, nothing written) and a
      WARN is printed — that residual is dust, not a position.

      **fillmodel v2 (2026-08-20): the clamp is FRACTIONAL.** v1 used
      `floor(cash / px)`, which was the one place in the engine that rounded to
      whole shares. Every sizing path is fractional (`base.py`,
      `turtle_breakout.py`, `pead_ear.py`) and the live books hold fractional
      quantities (`DLLL qty 102.384263`); `trading-execution-design.md` §2
      specifies fills, slippage and the liquidity guard and says NOTHING about
      lot size. The `floor()` was a 2026-07-18 negative-cash safety fix
      (BUILDLOG:284) and whole-share trading was its incidental side effect.

      Why it mattered: `collect.py` fetches `auto_adjust=False`, which still
      SPLIT-adjusts OHLC, so a name with heavy cumulative REVERSE splits has its
      old prices multiplied without limit — `TNXP` reaches $19.2bn in 2012,
      `DRIP` $83,000, and 32 tickers exceed $100,000. A $39,000 book facing a
      $31.7M adjusted price computed `floor(0.0012) = 0`, rejected the order and
      stranded the whole allocation. Measured across the fold replays: 2,634
      rejects, of which 436 (16.6%) were leveraged/inverse ETFs carrying 90.8%
      of ALL stranded cash, and 50 rejects stranded >10% of a book.

      The prices are not wrong — back-adjustment preserves returns, which is
      what a backtest consumes, and dollar-volume stays split-invariant so the
      liquidity filter is sound. Exactly one rule keyed on absolute price per
      share, and this was it.

    A return of 0.0 means nothing was applied — the caller must not record a
    sim_fills row and should mark the order rejected. Callers that record a
    sim_fills row MUST use the returned qty so the fill log and order status
    reflect what actually happened.
    """
    pf_id, tk = fill["portfolio_id"], fill["ticker"]
    qty, px, side = fill["qty"], fill["fill_px"], fill["side"]
    row = con.execute(
        "SELECT qty, avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [pf_id, tk],
    ).fetchone()
    cur_qty, cur_cost = (row[0], row[1]) if row else (0.0, 0.0)

    if px is None or not px > 0:
        # A non-positive fill price is never a trade: a buy at 0 would book free
        # shares (and skip the cash clamp), a sell at 0 would erase a position for
        # nothing. fills.attempt_fill already refuses such bars; this is the
        # last line of defence for any other caller.
        log.warning(f"[apply_fill] WARN bad_price: {pf_id} {tk} {side} {qty} @ {px!r} "
              f"— fill rejected")
        return 0.0

    if side == "buy":
        cash = get_cash(con, pf_id)
        if qty * px > cash:
            # Shave a floating-point epsilon so `qty * px` can never round up
            # past `cash` and drive the balance negative — the invariant the
            # v1 floor() was protecting, kept without the whole-share side
            # effect.
            affordable = (cash / px) * (1.0 - 1e-12) if cash > 0 else 0.0
            if affordable * px < MIN_FILL_USD:
                log.warning(f"[apply_fill] WARN insufficient_cash: {pf_id} {tk} buy "
                      f"{qty} @ {px:.4f} (notional ${qty * px:,.2f} > cash "
                      f"${cash:,.2f}; affordable ${affordable * px:,.2f} < "
                      f"${MIN_FILL_USD:g} dust floor) — fill rejected")
                return 0.0
            log.warning(f"[apply_fill] WARN cash-clamp: {pf_id} {tk} buy {qty} → "
                  f"{affordable:.6f} @ {px:.4f} (cash ${cash:,.2f})")
            qty = float(affordable)
        new_qty = cur_qty + qty
        new_cost = ((cur_qty * cur_cost) + (qty * px)) / new_qty if new_qty else 0.0
        con.execute("UPDATE portfolios SET cash = cash - ? WHERE id = ?",
                    [qty * px, pf_id])
    else:  # sell — close-only, never go short
        if qty > cur_qty:
            log.warning(f"[apply_fill] WARN sell-clamp: {pf_id} {tk} sell {qty} > held "
                  f"{cur_qty} → {cur_qty} (close-only)")
            qty = cur_qty
        if qty <= 0:
            return 0.0
        new_qty = cur_qty - qty
        new_cost = cur_cost  # realized P&L falls out of cash; avg_cost unchanged
        con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                    [qty * px, pf_id])

    if row:
        con.execute(
            "UPDATE sim_positions SET qty = ?, avg_cost = ? "
            "WHERE portfolio_id = ? AND ticker = ?",
            [new_qty, new_cost, pf_id, tk],
        )
    else:
        con.execute(
            "INSERT INTO sim_positions (portfolio_id, ticker, qty, avg_cost) "
            "VALUES (?, ?, ?, ?)",
            [pf_id, tk, new_qty, new_cost],
        )
    return float(qty)


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


def _position_as_of(con: duckdb.DuckDBPyConnection, pf_id: str, tk: str,
                    as_of: date, splits: dict[str, list[tuple[date, float]]]) -> float:
    """Shares of `tk` held by `pf_id` at the close of the session BEFORE `as_of`,
    reconstructed from sim_fills (fill_date < as_of), on the current post-split
    scale — the same replay rule rebuild_state uses."""
    rows = con.execute(
        "SELECT side, qty, fill_date FROM sim_fills "
        "WHERE portfolio_id = ? AND ticker = ? AND fill_date < ?",
        [pf_id, tk, as_of],
    ).fetchall()
    qty = 0.0
    for side, q, fd in rows:
        factor = 1.0
        for ex, ratio in splits.get(tk, ()):
            if fd < ex:
                factor *= ratio
        qty += float(q) * factor if side == "buy" else -float(q) * factor
    return max(qty, 0.0)


def credit_dividends(con: duckdb.DuckDBPyConnection, d: date,
                     lookback_days: int = DIVIDEND_LOOKBACK_DAYS) -> dict:
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

    Entitlement is the position at the close of ex_date − 1. For ex_date == d
    that is the current sim_positions state (this runs BEFORE the day's fills);
    for an earlier ex_date it is reconstructed from sim_fills so a name bought
    after the ex-date is not paid. Cash += qty × dps, one append-only
    sim_dividends row per credit, stamped with the TRUE ex_date so rebuild_state
    replays it at the right point in the cash trajectory.

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
    splits = _split_factors(con)

    for (pf_id,) in con.execute(
        "SELECT id FROM portfolios WHERE active ORDER BY id"
    ).fetchall():
        held_now = {
            tk: float(q) for tk, q in con.execute(
                "SELECT ticker, qty FROM sim_positions "
                "WHERE portfolio_id = ? AND qty > 0", [pf_id]
            ).fetchall()
        }
        # Any name the book has EVER filled is a candidate for a late credit.
        ever = {r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM sim_fills WHERE portfolio_id = ?", [pf_id]
        ).fetchall()} | set(held_now)
        for tk, ex, value in divs:
            if tk not in ever or (pf_id, tk, ex) in already:
                continue
            if ex == d:
                qty = held_now.get(tk, 0.0)
            else:
                qty = _position_as_of(con, pf_id, tk, ex, splits)
            if qty <= 0:
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


def _split_factors(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[date, float]]]:
    """{ticker: [(ex_date, ratio), …]} for splits the reconciler actually APPLIED.

    A fill that happened BEFORE a split's ex-date was executed at pre-split
    prices, so replaying it verbatim would rebuild a pre-split share count. The
    boundary here is the ex_date (economics), deliberately NOT the storage
    break_date the price restatement used (see engine/actions.py).
    """
    if not table_exists(con, "split_adjustments"):
        return {}
    out: dict[str, list[tuple[date, float]]] = {}
    for tk, ex, ratio in con.execute(
        "SELECT ticker, ex_date, ratio FROM split_adjustments "
        "WHERE outcome = 'applied' AND ratio IS NOT NULL AND ratio > 0"
    ).fetchall():
        out.setdefault(tk, []).append((ex, float(ratio)))
    return out


# --------------------------------------------------------------------------- #
# reconstruction (used by --rerun)
# --------------------------------------------------------------------------- #
def rebuild_state(con: duckdb.DuckDBPyConnection) -> None:
    """Replay every surviving sim_fill + sim_dividend to recompute sim_positions
    and cash exactly.

    Cash starts at INITIAL_CASH per portfolio; events are replayed in date order
    with dividends BEFORE fills within a date — the SAME order the live day-step
    applies them (phase a0 then phase a), so the cash-bounded buy clamp in
    apply_fill sees an identical cash trajectory and never re-clamps a stored
    fill. Fills within a date keep the live (sells-before-buys, order_id) order.
    This makes state a pure function of (sim_fills, sim_dividends).

    Splits: a fill recorded before an APPLIED split's ex-date is replayed with
    qty × ratio and fill_px ÷ ratio. Notional (and therefore the cash trajectory)
    is unchanged, while the rebuilt share count and avg_cost land on the current,
    post-split scale — without this, any --rerun after a split would silently
    revert the reconciler's position adjustment. Dividends are replayed at their
    RECORDED amount: the cash was received at the share count of the day, and a
    later split does not retroactively change what was paid.

    Settlements (sim_settlements, owner-supplied terms for a name that stopped
    trading — see sim/settle.py) are replayed at `effective`, phased AFTER that
    date's dividends and BEFORE its fills, at their RECORDED qty/price. Why an
    event and not a synthetic fill: a settlement is not a trade (no bar, no
    slippage, no order) and must never look like one in sim_fills; and it must
    survive `--rerun`, which deletes a date's fills/dividends but never the
    owner's settlement rows. Phase order: dividends first because a final
    dividend can go ex on the same day the shares are cancelled; fills after
    because by `effective` the fill model can no longer produce one anyway.
    """
    pf_ids = con.execute(
        "SELECT id, COALESCE(initial_cash, ?) FROM portfolios", [INITIAL_CASH]
    ).fetchall()
    con.execute("DELETE FROM sim_positions")
    for pf_id, initial_cash in pf_ids:
        con.execute("UPDATE portfolios SET cash = ? WHERE id = ?",
                    [initial_cash, pf_id])

    splits = _split_factors(con)

    # (date, phase, seq, kind, payload) — phase 0 = dividends, 1 = settlements,
    # 2 = fills.
    events: list[tuple] = []
    if table_exists(con, "sim_dividends"):
        for i, (pf_id, tk, ex, amount) in enumerate(con.execute(
            "SELECT portfolio_id, ticker, ex_date, amount FROM sim_dividends "
            "ORDER BY ex_date, portfolio_id, ticker"
        ).fetchall()):
            events.append((ex, 0, i, "div", (pf_id, tk, float(amount))))
    for i, (pf_id, tk, side, qty, px, fd, _oid) in enumerate(con.execute(
        "SELECT portfolio_id, ticker, side, qty, fill_px, fill_date, order_id "
        "FROM sim_fills "
        "ORDER BY fill_date, CASE side WHEN 'sell' THEN 0 ELSE 1 END, order_id"
    ).fetchall()):
        events.append((fd, 2, i, "fill", (pf_id, tk, side, qty, px, fd)))
    if table_exists(con, "sim_settlements"):
        for i, row in enumerate(con.execute(
            "SELECT portfolio_id, ticker, kind, qty, price, into_ticker, ratio, "
            "effective FROM sim_settlements ORDER BY effective, portfolio_id, ticker"
        ).fetchall()):
            events.append((row[7], 1, i, "settle", row[:7]))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    for _d, _phase, _seq, kind, payload in events:
        if kind == "div":
            pf_id, _tk, amount = payload
            con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                        [amount, pf_id])
            continue
        if kind == "settle":
            from .settle import apply_settlement_event  # local: settle imports us
            pf_id, tk, skind, qty, price, into, ratio = payload
            apply_settlement_event(con, pf_id, tk, skind, float(qty), float(price),
                                   into, None if ratio is None else float(ratio))
            continue
        pf_id, tk, side, qty, px, fd = payload
        factor = 1.0
        for ex, ratio in splits.get(tk, ()):
            if fd < ex:
                factor *= ratio
        apply_fill(con, {"portfolio_id": pf_id, "ticker": tk, "side": side,
                         "qty": qty * factor, "fill_px": px / factor})
