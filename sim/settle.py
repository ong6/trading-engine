#!/usr/bin/env python
"""Settle a dead position at OWNER-SUPPLIED terms.

The engine never invents a price (docs/how-it-works.md, rule 1). When a held
name stops trading — acquisition, delisting, bankruptcy — the fill model can
never sell it (no tradeable bar) and `mark_to_market` carries its last close
forever, which `league.md` flags in the stale-marks table. This module is the
only sanctioned way out: the owner looks up the terms, cites them, and the
engine books exactly those terms. Nothing here reads a price for the dead
ticker and nothing here writes to `prices`.

Kinds
  cash       every active book holding `ticker` receives qty × price in cash on
             `effective`; the position goes to 0.
  worthless  cash settlement at price 0 (bankruptcy / cancellation).
  stock      the position converts into `into_ticker` at `ratio` acquirer shares
             per held share (optionally plus `price` cash per share for mixed
             deals). Cost basis carries over: the acquirer lot's avg_cost is the
             dead lot's avg_cost ÷ ratio, so no P&L is realised on the swap.

Ledger
  `sim_settlements` is append-only, one row per (portfolio, ticker, effective).
  `portfolio.rebuild_state` replays settlements as an event kind at `effective`,
  phased between dividends and fills, so a settlement is part of the pure
  function state = f(sim_fills, sim_dividends, sim_settlements) and survives
  `--rerun`. `sim_equity` is never touched: history before `effective` stays as
  it was, and rows between `effective` and the apply date keep the frozen mark
  they were written with (they are point-in-time records of what the league
  believed on that day). The next MTM reflects the settlement.

Safety
  Dry-run by default. `--apply` writes in one transaction through
  engine/lib/db.connect (the project's single-writer path). Refused when the
  ticker has a bar with volume > 0 on/after `effective` (it is still trading),
  when `--source` is missing, when the acquirer has no stored prices, or when
  no active book holds the name.

    python -m sim.settle --db store/market.duckdb --ticker EA --kind cash \\
        --price 209.70 --effective 2026-08-05 --source "<URL>"          # dry run
    ... --apply                                                         # write
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import duckdb

from engine.lib import db
from engine.lib.log import get_logger
from engine.lib.util import table_exists

from . import portfolio

log = get_logger("settle")

KINDS = ("cash", "worthless", "stock")

SETTLEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS sim_settlements (
    portfolio_id VARCHAR,
    ticker       VARCHAR,
    kind         VARCHAR,     -- 'cash' | 'worthless' | 'stock'
    qty          DOUBLE,      -- shares of `ticker` settled (the position at the time)
    price        DOUBLE,      -- cash per share (0 for worthless; cash leg of a stock deal)
    into_ticker  VARCHAR,     -- stock: acquirer ticker, else NULL
    ratio        DOUBLE,      -- stock: acquirer shares per held share, else NULL
    effective    DATE,        -- the date the terms took effect (replay point)
    source       VARCHAR,     -- owner-supplied citation: URL / filing / note
    note         VARCHAR,
    created_at   TIMESTAMP,
    PRIMARY KEY (portfolio_id, ticker, effective)
)
"""


def ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SETTLEMENTS_DDL)


class SettlementRefused(Exception):
    """The terms cannot be booked as given. Message says why."""


@dataclass(frozen=True)
class Terms:
    ticker: str
    kind: str
    effective: date
    source: str
    price: float = 0.0
    into_ticker: str | None = None
    ratio: float | None = None
    note: str | None = None
    portfolios: tuple[str, ...] | None = None   # None → every active book holding it


@dataclass
class BookPlan:
    portfolio_id: str
    qty: float
    avg_cost: float
    cash_before: float
    cash_after: float
    cash_credit: float
    into_qty_before: float = 0.0
    into_qty_after: float = 0.0
    frozen_value: float | None = None       # qty × last carried close (what MTM held)
    equity_rows_after_effective: int = 0    # sim_equity rows still carrying the frozen mark
    pending_order_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingOrderPlan:
    """A stale pending order covered by an already-booked settlement."""

    order_id: int
    portfolio_id: str
    ticker: str
    side: str
    qty: float
    signal_date: date
    settlement_effective: date
    settlement_created_at: datetime


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate(con: duckdb.DuckDBPyConnection, t: Terms) -> None:
    if t.kind not in KINDS:
        raise SettlementRefused(f"unknown kind {t.kind!r}; expected one of {KINDS}")
    if not t.source or not t.source.strip():
        raise SettlementRefused("--source is required: cite where the terms come from "
                                "(deal press release, 8-K/DEFM14A, exchange delisting "
                                "notice, court order). The engine does not infer terms.")
    if t.kind == "worthless" and t.price != 0.0:
        raise SettlementRefused("--kind worthless means price 0; do not pass --price")
    if t.kind == "cash" and not t.price > 0:
        raise SettlementRefused("--kind cash needs --price > 0 (use --kind worthless for 0)")
    if t.price < 0:
        raise SettlementRefused("price cannot be negative")
    if t.kind == "stock":
        if not t.into_ticker or t.ratio is None or not t.ratio > 0:
            raise SettlementRefused("--kind stock needs --into ACQ and --ratio R > 0")
        if t.into_ticker == t.ticker:
            raise SettlementRefused("--into must differ from --ticker")
        n_bars = con.execute(
            "SELECT COUNT(*) FROM prices WHERE ticker = ? AND date >= ? "
            f"AND {db.REAL_BAR_SQL}", [t.into_ticker, t.effective]).fetchone()[0]
        if n_bars == 0:
            raise SettlementRefused(
                f"acquirer {t.into_ticker} has no real bar in prices on/after "
                f"{t.effective}; converting into a name the engine cannot mark "
                "would recreate the problem being fixed")
    else:
        if t.into_ticker or t.ratio is not None:
            raise SettlementRefused("--into/--ratio only apply to --kind stock")

    traded = con.execute(
        "SELECT MAX(date), COUNT(*) FROM prices WHERE ticker = ? AND date >= ? "
        "AND volume > 0", [t.ticker, t.effective]).fetchone()
    if traded and traded[1] > 0:
        raise SettlementRefused(
            f"{t.ticker} traded on/after {t.effective} (last bar with volume > 0: "
            f"{traded[0]}). A name that still prints is not dead; if it is a halt, "
            "wait; if the effective date is wrong, fix it.")


def holders(con: duckdb.DuckDBPyConnection, t: Terms) -> list[tuple[str, float, float]]:
    """[(portfolio_id, qty, avg_cost)] for active books holding `ticker`."""
    rows = con.execute(
        "SELECT p.portfolio_id, p.qty, p.avg_cost FROM sim_positions p "
        "JOIN portfolios pf ON pf.id = p.portfolio_id "
        "WHERE p.ticker = ? AND p.qty > 0 AND pf.active ORDER BY p.portfolio_id",
        [t.ticker]).fetchall()
    if t.portfolios is not None:
        want = set(t.portfolios)
        missing = want - {r[0] for r in rows}
        if missing:
            raise SettlementRefused(
                f"{sorted(missing)} do not hold {t.ticker} (or are inactive)")
        rows = [r for r in rows if r[0] in want]
    if not rows:
        raise SettlementRefused(f"no active book holds {t.ticker}; nothing to settle")
    return [(r[0], float(r[1]), float(r[2])) for r in rows]


# --------------------------------------------------------------------------- #
# core
# --------------------------------------------------------------------------- #
def _plan_book(con, t: Terms, pf_id: str, qty: float, avg_cost: float) -> BookPlan:
    cash = portfolio.get_cash(con, pf_id)
    credit = qty * t.price
    plan = BookPlan(portfolio_id=pf_id, qty=qty, avg_cost=avg_cost,
                    cash_before=cash, cash_after=cash + credit, cash_credit=credit)
    last_close, _ = portfolio.close_on(con, t.ticker, date.max)
    if last_close is not None:
        plan.frozen_value = qty * last_close
    plan.equity_rows_after_effective = con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id = ? AND date >= ?",
        [pf_id, t.effective]).fetchone()[0]
    plan.pending_order_ids = [int(row[0]) for row in con.execute(
        "SELECT id FROM sim_orders WHERE portfolio_id = ? AND ticker = ? "
        "AND status = 'pending' ORDER BY id",
        [pf_id, t.ticker],
    ).fetchall()]
    if t.kind == "stock":
        row = con.execute(
            "SELECT qty FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
            [pf_id, t.into_ticker]).fetchone()
        plan.into_qty_before = float(row[0]) if row else 0.0
        plan.into_qty_after = plan.into_qty_before + qty * t.ratio
    already = 0
    if table_exists(con, "sim_settlements"):
        already = con.execute(
            "SELECT COUNT(*) FROM sim_settlements WHERE portfolio_id = ? AND ticker = ?",
            [pf_id, t.ticker]).fetchone()[0]
    if already:
        plan.warnings.append(f"{pf_id} already has {already} settlement row(s) for "
                             f"{t.ticker}; a position re-opened after a settlement "
                             "is unusual — check the ledger")
    return plan


def apply_settlement_event(con: duckdb.DuckDBPyConnection, pf_id: str, ticker: str,
                           kind: str, qty: float, price: float,
                           into_ticker: str | None, ratio: float | None) -> None:
    """Mutate sim_positions + portfolios.cash for one settlement. Used both by
    `settle(..., apply=True)` and by `portfolio.rebuild_state`'s replay, so the
    live path and the rebuild path are the same arithmetic by construction.

    Replays at the RECORDED qty (the dividend precedent): the settlement is a
    fact about what was booked, not a function of whatever the rebuilt position
    happens to be. If the rebuilt position differs from the recorded qty a WARN
    is printed — that means a fill before `effective` was added or removed
    after the settlement was booked, and a human should look.
    """
    row = con.execute(
        "SELECT qty, avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
        [pf_id, ticker]).fetchone()
    held, avg_cost = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
    if abs(held - qty) > 1e-6:
        log.warning(f"[settle] WARN {pf_id} {ticker}: recorded settlement qty {qty:.6f} "
              f"!= position {held:.6f} at replay — fills before effective changed "
              f"after the settlement was booked; settling the recorded qty")
    if price:
        con.execute("UPDATE portfolios SET cash = cash + ? WHERE id = ?",
                    [qty * price, pf_id])
    if row:
        con.execute("UPDATE sim_positions SET qty = ? WHERE portfolio_id = ? "
                    "AND ticker = ?", [max(held - qty, 0.0), pf_id, ticker])
    if kind == "stock":
        new_shares = qty * ratio
        basis_per_acq = avg_cost / ratio if ratio else 0.0
        acq = con.execute(
            "SELECT qty, avg_cost FROM sim_positions WHERE portfolio_id = ? AND ticker = ?",
            [pf_id, into_ticker]).fetchone()
        if acq:
            cur_q, cur_c = float(acq[0]), float(acq[1])
            new_q = cur_q + new_shares
            new_c = ((cur_q * cur_c) + (new_shares * basis_per_acq)) / new_q if new_q else 0.0
            con.execute("UPDATE sim_positions SET qty = ?, avg_cost = ? "
                        "WHERE portfolio_id = ? AND ticker = ?",
                        [new_q, new_c, pf_id, into_ticker])
        else:
            con.execute("INSERT INTO sim_positions (portfolio_id, ticker, qty, avg_cost) "
                        "VALUES (?, ?, ?, ?)",
                        [pf_id, into_ticker, new_shares, basis_per_acq])


def settle(con: duckdb.DuckDBPyConnection, t: Terms, apply: bool = False,
           now: datetime | None = None) -> list[BookPlan]:
    """Validate, plan per book, and (if `apply`) write. Returns the plans.

    The caller owns the transaction: `settle` issues no BEGIN/COMMIT so it can
    run inside an enclosing one (the CLI wraps it; tests run autocommit). A dry
    run works on a read-only connection (nothing is created).
    """
    validate(con, t)
    plans = [_plan_book(con, t, pf, q, c) for pf, q, c in holders(con, t)]
    if not apply:
        return plans
    ensure_table(con)
    ts = now or datetime.now(timezone.utc).replace(tzinfo=None)
    for p in plans:
        con.execute(
            "INSERT INTO sim_settlements (portfolio_id, ticker, kind, qty, price, "
            "into_ticker, ratio, effective, source, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [p.portfolio_id, t.ticker, t.kind, p.qty, t.price, t.into_ticker,
             t.ratio, t.effective, t.source, t.note, ts])
        apply_settlement_event(con, p.portfolio_id, t.ticker, t.kind, p.qty,
                               t.price, t.into_ticker, t.ratio)
        if p.pending_order_ids:
            reason = f"cancelled by settlement effective {t.effective.isoformat()}"
            con.execute(
                "UPDATE sim_orders SET status = 'cancelled', reject_reason = ? "
                "WHERE portfolio_id = ? AND ticker = ? AND status = 'pending'",
                [reason, p.portfolio_id, t.ticker],
            )
            if table_exists(con, "disc_tickets"):
                con.execute(
                    "UPDATE disc_tickets SET status = 'cancelled' "
                    "WHERE order_id IN (SELECT UNNEST(?::BIGINT[])) "
                    "AND status = 'submitted'",
                    [p.pending_order_ids],
                )
    if table_exists(con, "audit_log"):
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [ts, "sim.settle", "settlement_applied", json.dumps({
                "ticker": t.ticker,
                "kind": t.kind,
                "effective": t.effective.isoformat(),
                "source": t.source,
                "portfolios": [p.portfolio_id for p in plans],
                "cancelled_order_ids": [
                    oid for p in plans for oid in p.pending_order_ids
                ],
            }, sort_keys=True)],
        )
    return plans


def settled_pending_orders(con: duckdb.DuckDBPyConnection,
                           ticker: str | None = None) -> list[PendingOrderPlan]:
    """Return pending orders that predate a matching booked settlement.

    The creation-date bound is deliberate. A settlement may be followed by an
    unusual but legitimate re-opening of the symbol; this repair must not use
    an old event to cancel later intent. Orders already present on the day the
    day before the settlement was booked are the narrowly provable lifecycle
    omission. Same-day intent is left alone because old orders have no creation
    timestamp with which to establish event ordering.
    """
    if not table_exists(con, "sim_settlements"):
        return []
    params: list[str] = []
    ticker_clause = ""
    if ticker is not None:
        ticker_clause = " AND o.ticker = ?"
        params.append(ticker.upper())
    rows = con.execute(
        "SELECT o.id, o.portfolio_id, o.ticker, o.side, o.qty, o.signal_date, "
        "s.effective, s.created_at FROM sim_orders o "
        "JOIN sim_settlements s ON s.portfolio_id = o.portfolio_id "
        "AND s.ticker = o.ticker "
        "WHERE o.status = 'pending' "
        "AND o.signal_date < CAST(s.created_at AS DATE)" + ticker_clause + " "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY o.id ORDER BY s.created_at DESC) = 1 "
        "ORDER BY o.id",
        params,
    ).fetchall()
    return [PendingOrderPlan(int(oid), pf, tk, side, float(qty), signal_date,
                             effective, created_at)
            for oid, pf, tk, side, qty, signal_date, effective, created_at in rows]


def reconcile_settled_pending_orders(
        con: duckdb.DuckDBPyConnection, *, apply: bool = False,
        ticker: str | None = None, now: datetime | None = None,
) -> list[PendingOrderPlan]:
    """Dry-run or cancel provably stale orders missed by older settlement code."""
    plans = settled_pending_orders(con, ticker)
    if not apply or not plans:
        return plans
    ts = now or datetime.now(timezone.utc).replace(tzinfo=None)
    for p in plans:
        reason = ("cancelled by booked settlement effective "
                  f"{p.settlement_effective.isoformat()}")
        con.execute(
            "UPDATE sim_orders SET status = 'cancelled', reject_reason = ? "
            "WHERE id = ? AND status = 'pending'",
            [reason, p.order_id],
        )
    if table_exists(con, "disc_tickets"):
        con.execute(
            "UPDATE disc_tickets SET status = 'cancelled' "
            "WHERE order_id IN (SELECT UNNEST(?::BIGINT[])) "
            "AND status = 'submitted'",
            [[p.order_id for p in plans]],
        )
    if table_exists(con, "audit_log"):
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [ts, "sim.settle", "settlement_pending_orders_reconciled", json.dumps({
                "ticker": ticker.upper() if ticker else None,
                "order_ids": [p.order_id for p in plans],
                "count": len(plans),
            }, sort_keys=True)],
        )
    return plans


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _render(t: Terms, plans: list[BookPlan], applied: bool) -> str:
    head = f"{t.ticker} {t.kind}"
    if t.kind == "stock":
        head += f" → {t.ratio:g} {t.into_ticker}/sh"
        if t.price:
            head += f" + ${t.price:,.4f}/sh cash"
    elif t.kind == "cash":
        head += f" @ ${t.price:,.4f}/sh"
    lines = [f"[settle] {'APPLIED' if applied else 'DRY RUN'}: {head}, effective "
             f"{t.effective}, {len(plans)} book(s)",
             f"[settle] source: {t.source}"]
    if t.note:
        lines.append(f"[settle] note: {t.note}")
    lines.append("")
    hdr = "| Book | Qty | Avg cost | Frozen value | Cash before | Cash after | Δ cash |"
    sep = "|---|---|---|---|---|---|---|"
    if t.kind == "stock":
        hdr = hdr[:-1] + f" {t.into_ticker} before | {t.into_ticker} after |"
        sep += "---|---|"
    lines += [hdr, sep]
    for p in plans:
        fv = "·" if p.frozen_value is None else f"${p.frozen_value:,.2f}"
        row = (f"| {p.portfolio_id} | {p.qty:,.6f} | ${p.avg_cost:,.4f} | {fv} | "
               f"${p.cash_before:,.2f} | ${p.cash_after:,.2f} | {p.cash_credit:+,.2f} |")
        if t.kind == "stock":
            row += f" {p.into_qty_before:,.6f} | {p.into_qty_after:,.6f} |"
        lines.append(row)
        if p.pending_order_ids:
            verb = "cancelled" if applied else "would cancel"
            ids = ", ".join(str(oid) for oid in p.pending_order_ids)
            lines.append(f"  - pending order(s) {ids}: {verb} with the settlement")
    lines.append("")
    n_eq = sum(p.equity_rows_after_effective for p in plans)
    if n_eq:
        lines.append(f"[settle] note: {n_eq} sim_equity row(s) dated >= {t.effective} keep "
                     "the frozen mark they were written with; equity is not restated. "
                     "The next MTM reflects the settlement.")
    for p in plans:
        for w in p.warnings:
            lines.append(f"[settle] WARN {w}")
    if not applied:
        lines.append("[settle] nothing written. Re-run with --apply to book it.")
    return "\n".join(lines)


def _render_reconciliation(plans: list[PendingOrderPlan], applied: bool) -> str:
    state = "APPLIED" if applied else "DRY RUN"
    lines = [f"[settle] {state}: {len(plans)} settled pending order(s)"]
    for p in plans:
        lines.append(
            f"- order {p.order_id}: {p.portfolio_id} {p.side} {p.qty:.6f} "
            f"{p.ticker}, signalled {p.signal_date}, settlement effective "
            f"{p.settlement_effective}"
        )
    if not applied:
        lines.append("[settle] nothing written. Re-run with --apply to cancel them.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Settle a dead position at owner-supplied terms (dry-run by default).")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--ticker")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--price", type=float, default=None,
                    help="cash per share (cash: required; stock: optional cash leg)")
    ap.add_argument("--into", default=None, help="stock: acquirer ticker")
    ap.add_argument("--ratio", type=float, default=None,
                    help="stock: acquirer shares per held share")
    ap.add_argument("--effective", help="YYYY-MM-DD the terms took effect")
    ap.add_argument("--source",
                    help="citation for the terms (URL, filing, exchange notice)")
    ap.add_argument("--note", default=None)
    ap.add_argument("--portfolio", default="all",
                    help="'all' (default) or a comma-separated list of book ids")
    ap.add_argument("--apply", action="store_true", help="write (default is dry-run)")
    ap.add_argument(
        "--reconcile-pending", action="store_true",
        help="cancel pending orders covered by settlements booked before this fix",
    )
    args = ap.parse_args(argv)

    if args.reconcile_pending:
        con = db.connect(args.db, read_only=not args.apply)
        try:
            if not args.apply:
                plans = reconcile_settled_pending_orders(
                    con, apply=False, ticker=args.ticker)
                print(_render_reconciliation(plans, applied=False))
                return 0
            with db.transaction(con):
                plans = reconcile_settled_pending_orders(
                    con, apply=True, ticker=args.ticker)
            print(_render_reconciliation(plans, applied=True))
            return 0
        finally:
            con.close()

    missing = [name for name, value in (
        ("--ticker", args.ticker), ("--kind", args.kind),
        ("--effective", args.effective), ("--source", args.source),
    ) if not value]
    if missing:
        ap.error(f"the following arguments are required: {', '.join(missing)}")

    price = 0.0 if args.price is None else args.price
    pfs = None if args.portfolio == "all" else tuple(
        s.strip() for s in args.portfolio.split(",") if s.strip())
    t = Terms(ticker=args.ticker.upper(), kind=args.kind,
              effective=date.fromisoformat(args.effective), source=args.source,
              price=price, into_ticker=args.into.upper() if args.into else None,
              ratio=args.ratio, note=args.note, portfolios=pfs)

    # Dry run never opens the store for writing; --apply goes through the
    # project's single-writer path with its lock retry.
    con = db.connect(args.db, read_only=not args.apply)
    try:
        if not args.apply:
            print(_render(t, settle(con, t, apply=False), applied=False))
            return 0
        with db.transaction(con):
            plans = settle(con, t, apply=True)
        print(_render(t, plans, applied=True))
        return 0
    except SettlementRefused as e:
        log.error(f"[settle] REFUSED: {e}")
        return 2
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
