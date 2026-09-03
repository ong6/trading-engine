#!/usr/bin/env python
"""M2 paper league — one idempotent day-step over the mock portfolios.

For a given date d the step runs in this fixed order:
  a0. Credit cash dividends going ex on d (portfolio.credit_dividends). Runs
      FIRST so entitlement is the position held at the close of d−1.
  a. Fill pending orders at d's OPEN (fills.py; t+1-open, slippage, guards).
  b. Mark every portfolio to market at d's CLOSE → append sim_equity.
  c. Generate new orders from d's close signals, per each strategy's cadence.
  d. Render data/reports/league.md and league.csv.

Idempotency: if sim_equity already has rows for d the step ABORTS. `--rerun`
deletes d's sim rows first and rebuilds cash/positions from the surviving fills
(portfolio.rebuild_state), so a re-run is exact. `--init` creates the 16
registered portfolios if absent. Reads prices/screen_results read-only; writes
only sim_* / portfolios.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from engine.lib import db
from engine.lib.log import get_logger
from engine.lib.settings import DATA_DIR as DEFAULT_DATA_DIR
from engine.lib.settings import REPO_ROOT  # noqa: F401
from engine.lib.util import table_exists

from . import calendar, fills, portfolio
from .schema import INITIAL_CASH, init_sim_schema
from .strategies import PortfolioView, get_strategy
from .strategies.base import total_return_between
from .strategies.configs import CONFIGS

log = get_logger("league")


# --------------------------------------------------------------------------- #
# setup
# --------------------------------------------------------------------------- #
def resolve_date(con, requested: str | None) -> date:
    if requested:
        return date.fromisoformat(requested)
    row = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if row is None:
        raise SystemExit("[league] prices table is empty")
    return row


def init_portfolios(con, as_of: date) -> int:
    """Create any registered portfolio that doesn't exist yet. Returns #created."""
    created = 0
    for cfg in CONFIGS:
        exists = con.execute(
            "SELECT 1 FROM portfolios WHERE id = ?", [cfg["id"]]
        ).fetchone()
        if exists:
            continue
        con.execute(
            "INSERT INTO portfolios (id, name, strategy, config, created, active, cash)"
            " VALUES (?, ?, ?, ?, ?, TRUE, ?)",
            [cfg["id"], cfg["name"], cfg["strategy"], json.dumps(cfg), as_of,
             INITIAL_CASH],
        )
        created += 1
    return created


def next_order_id(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0]


# --------------------------------------------------------------------------- #
# day-step phases
# --------------------------------------------------------------------------- #
def fill_pending(con, d: date) -> dict:
    """Phase a. Attempt every pending order at d's open. Sells first so freed
    cash funds same-day buys. Returns {'filled','rejected','pending'} counts."""
    # signal_date < d: an order signalled ON d (a discretionary ticket submitted
    # between tonight's collect and league stages carries signal_date = d) fills
    # at the NEXT session's open. Passing it to attempt_fill would trip the
    # look-ahead assert, roll back the whole day-step, and leave a permanent
    # hole in every book's record.
    pend = con.execute(
        "SELECT id, portfolio_id, ticker, side, qty, signal_date FROM sim_orders "
        "WHERE status = 'pending' AND signal_date < ? "
        "ORDER BY CASE side WHEN 'sell' THEN 0 ELSE 1 END, id", [d]
    ).fetchall()
    counts = {"filled": 0, "rejected": 0, "pending": 0}
    for oid, pf_id, tk, side, qty, sig in pend:
        res = fills.attempt_fill(con, tk, side, qty, sig, d)
        if res.status == "filled":
            # apply_fill may clamp (sell close-only / buy cash-bounded) and returns
            # the qty ACTUALLY applied. Record the fill and mark the order with that
            # qty so the fill log and order status reflect what really happened.
            filled_qty = portfolio.apply_fill(
                con, {"portfolio_id": pf_id, "ticker": tk, "side": side,
                      "qty": qty, "fill_px": res.fill_px})
            if filled_qty <= 0:
                reason = ("insufficient_cash" if side == "buy"
                          else "no_position_to_sell")
                con.execute(
                    "UPDATE sim_orders SET status = 'rejected', reject_reason = ? "
                    "WHERE id = ?",
                    [reason, oid],
                )
                counts["rejected"] += 1
                continue
            con.execute(
                "INSERT INTO sim_fills (order_id, portfolio_id, ticker, side, qty,"
                " fill_date, open_px, fill_px, slippage_bps, cost_bps)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [oid, pf_id, tk, side, filled_qty, d, res.open_px, res.fill_px,
                 res.slippage_bps, res.slippage_bps],
            )
            con.execute("UPDATE sim_orders SET status = 'filled' WHERE id = ?", [oid])
            counts["filled"] += 1
        elif res.status == "rejected":
            con.execute(
                "UPDATE sim_orders SET status = 'rejected', reject_reason = ? "
                "WHERE id = ?",
                [res.reject_reason, oid],
            )
            counts["rejected"] += 1
        else:
            counts["pending"] += 1
    return counts


def mtm_all(con, d: date, verbose: bool = True) -> dict:
    """Phase b. Mark every active portfolio to market → append sim_equity.

    Returns {"carried": {pf_id: [ticker, ...]}} — the positions valued at a
    CARRIED close because the name printed no bar on `d`.

    WHY THIS RETURN VALUE EXISTS. `portfolio.mark_to_market` has always computed
    this flag honestly and returned it, and nothing ever read it. On 2026-08-20
    the new price verifier found `EA` and `TALK` — both `active = FALSE` in
    `universe`, both still HELD — being marked forever at their last print (EA's
    was 2026-08-10, ten days stale) by `high_52wk` and `low_vol`. The equity of
    those books therefore contains a number that will never move again, and
    NOTHING said so: not the log, not `league.md`, not `_meta.json`.

    That is the same defect this codebase keeps producing — the honest
    computation happens and then the result goes nowhere — so the flag is now
    surfaced at the only place that can act on it. A carried mark is not an
    error and must not fail the run: a halted name resumes, and a genuinely
    delisted one needs a human decision about the position, not an exception.
    """
    carried: dict[str, list[str]] = {}
    for (pf_id,) in con.execute(
        "SELECT id FROM portfolios WHERE active ORDER BY id"
    ).fetchall():
        res = portfolio.mark_to_market(con, pf_id, d)
        if res.get("carried"):
            carried[pf_id] = sorted(res["carried"])
    if carried and verbose:
        n = sum(len(v) for v in carried.values())
        log.warning(f"[league] WARN {n} position(s) in {len(carried)} book(s) marked "
              f"at a CARRIED close on {d} — the name printed no bar:")
        for pf_id, tks in sorted(carried.items()):
            log.info(f"[league]   {pf_id}: {', '.join(tks)}")
    return {"carried": carried}


def generate_all(con, d: date) -> int:
    """Phase c. Generate new orders per cadence. Returns #orders created.

    Dedup guard: a new order is skipped if a PENDING sim_orders row already
    exists for the same (portfolio_id, ticker, side). Pending orders don't mutate
    sim_positions and can linger up to PENDING_MAX_DAYS on missing bars, and
    mr_overlay re-emits the same exit daily — so without this guard two pendings
    for the same leg could both fill and double-buy (negative cash) or
    double-sell (negative position). Skips are counted and logged.
    """
    n_new = 0
    n_skipped = 0
    for pf_id, strat_name, cfg_json, cash in con.execute(
        "SELECT id, strategy, config, cash FROM portfolios WHERE active ORDER BY id"
    ).fetchall():
        cfg = json.loads(cfg_json)
        cadence = cfg.get("cadence", "daily")
        if not _cadence_fires(con, cadence, d, pf_id):
            continue
        strat = get_strategy(strat_name)
        equity = con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id = ? AND date = ?",
            [pf_id, d],
        ).fetchone()
        equity = equity[0] if equity else cash
        pv = PortfolioView(
            id=pf_id,
            params=cfg.get("params", {}),
            cash=cash,
            positions={t: p["qty"]
                       for t, p in portfolio.get_positions(con, pf_id).items()},
            equity=equity,
        )
        orders = strat.generate_orders(con, pv, d)
        oid = next_order_id(con)
        for o in orders:
            dup = con.execute(
                "SELECT 1 FROM sim_orders WHERE portfolio_id = ? AND ticker = ? "
                "AND side = ? AND status = 'pending' LIMIT 1",
                [o.portfolio_id, o.ticker, o.side],
            ).fetchone()
            if dup:
                n_skipped += 1
                log.info(f"[league] dedup: skip {o.portfolio_id} {o.ticker} {o.side} "
                      f"— a pending order for this leg already exists")
                continue
            con.execute(
                "INSERT INTO sim_orders (id, portfolio_id, ticker, side, qty,"
                " signal_date, status, reject_reason)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
                [oid, o.portfolio_id, o.ticker, o.side, o.qty, o.signal_date],
            )
            oid += 1
            n_new += 1
    if n_skipped:
        log.info(f"[league] dedup: skipped {n_skipped} duplicate pending order(s)")
    return n_new


def _cadence_fires(con, cadence: str, d: date, pf_id: str) -> bool:
    if cadence == "daily":
        return True
    if cadence == "weekly":
        return calendar.is_week_signal(con, d)
    if cadence == "monthly":
        return calendar.is_month_signal(con, d)
    if cadence == "once":
        n = con.execute(
            "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ?", [pf_id]
        ).fetchone()[0]
        return n == 0
    return False


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def regime_label(con, d: date) -> str:
    spy = con.execute(
        "SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "ORDER BY date DESC LIMIT 200", [d]
    ).fetchall()
    if len(spy) < 200:
        return "unknown"
    c = np.array([r[0] for r in spy], dtype=float)
    return "risk-on" if c[0] > c.mean() else "risk-off"


def _max_drawdown(equity: list[float]) -> float:
    peak = -1e18
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, e / peak - 1)
    return mdd


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "·"
    n = v * 100
    sign = "+" if n >= 0 else "−"
    return f"{sign}{abs(n):.2f}%"


def _spy_return(con, inception: date, d: date):
    """SPY TOTAL return since a book's inception — price plus the dividends that
    went ex in the window. The books now receive their own dividends as cash
    (day-step phase a0), so a price-only benchmark would flatter every book by
    SPY's ~1.2%/yr yield. The league column stays labelled "vs SPY"."""
    return total_return_between(con, "SPY", inception, d)


def write_reports(con, d: date, data_dir: Path) -> Path:
    rows = []
    for pf_id, name, created in con.execute(
        "SELECT id, name, created FROM portfolios WHERE active ORDER BY id"
    ).fetchall():
        eq = con.execute(
            "SELECT date, equity FROM sim_equity WHERE portfolio_id = ? ORDER BY date",
            [pf_id],
        ).fetchall()
        if not eq:
            continue
        series = [e for _, e in eq]
        equity = series[-1]
        total_ret = equity / INITIAL_CASH - 1
        spy_ret = _spy_return(con, created, d)
        vs_spy = None if spy_ret is None else total_ret - spy_ret
        mdd = _max_drawdown(series)
        last5 = series[-1] / series[-6] - 1 if len(series) >= 6 else None
        n_open = con.execute(
            "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? AND qty > 0",
            [pf_id]).fetchone()[0]
        n_fills = con.execute(
            "SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
            [pf_id]).fetchone()[0]
        rows.append({
            "id": pf_id, "name": name, "inception": created, "equity": equity,
            "total_ret": total_ret, "vs_spy": vs_spy, "mdd": mdd,
            "n_open": n_open, "n_fills": n_fills, "last5": last5,
        })
    rows.sort(key=lambda r: r["total_ret"], reverse=True)

    lines = [
        f"# Paper League — {d.isoformat()}",
        "",
        "| # | Portfolio | Inception | Equity | Total ret | vs SPY | Max DD | "
        "Open | Fills | Last 5d |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['name']} | {r['inception']} | "
            f"${r['equity']:,.0f} | {_fmt_pct(r['total_ret'])} | "
            f"{_fmt_pct(r['vs_spy'])} | {_fmt_pct(r['mdd'])} | "
            f"{r['n_open']} | {r['n_fills']} | {_fmt_pct(r['last5'])} |"
        )
    lines += [
        "",
        f"_Regime: **{regime_label(con, d)}** · reference notional "
        f"${INITIAL_CASH:,.0f}/book · as of {d.isoformat()}._",
        "",
    ]

    # --- stale marks, on the dashboard rather than only in a log line -------
    # A held name that stopped printing is carried at its last close forever, so
    # the book's equity above contains a number that will never move again. That
    # belongs where the equity is READ, not only in a WARN nobody tails: the
    # 2026-08-20 verifier found EA (last print 2026-08-10) and TALK held by
    # `high_52wk` and `low_vol` with nothing anywhere saying so.
    # Keyed on the last bar that actually TRADED, not the last bar that exists.
    # yfinance keeps emitting a dead quote as a bar after a name stops trading:
    # EA's last real session was 2026-08-04 (volume 48,713,698 — a ~10x spike,
    # the acquisition-close signature) at $209.699997, followed by FOUR bars at
    # that identical price with volume 0, and then nothing. A detector keyed on
    # MAX(date) reported EA as 7 sessions stale when the truth was 11: the
    # phantom bars made a dead position look fresher than it was, and
    # `mark_to_market` saw a bar and did not flag a carried price at all.
    stale = con.execute(
        """
        SELECT p.portfolio_id, p.ticker, p.qty,
               MAX(pr.date) FILTER (WHERE pr.volume > 0) AS last_traded
        FROM sim_positions p
        JOIN prices pr ON pr.ticker = p.ticker
        WHERE p.qty > 0
        GROUP BY p.portfolio_id, p.ticker, p.qty
        HAVING MAX(pr.date) FILTER (WHERE pr.volume > 0) < ?
        ORDER BY last_traded, p.portfolio_id, p.ticker
        """, [d]).fetchall()
    if stale:
        lines += [
            f"## ⚠ Stale marks — {len(stale)} position(s) carried at an old close",
            "",
            "These names have not TRADED since the date shown, so they are "
            "valued at a close that cannot change until they trade again. "
            "**Sessions stale counts from the last bar with real volume, not "
            "the last bar on file** — yfinance keeps emitting a dead quote as a "
            "zero-volume bar after a name stops trading, which makes a dead "
            "position look fresher than it is. A halt resolves itself; a "
            "delisting or acquisition needs the position settled by hand. "
            "**The equity above includes these marks.**",
            "",
            "| Book | Ticker | Qty | Last traded | Sessions stale | Frozen value | % of equity |",
            "|---|---|---|---|---|---|---|",
        ]
        eq_by_book = {r["id"]: r["equity"] for r in rows}
        for pf_id, tk, qty, last_bar in stale:
            # Sessions counted off SPY's calendar, not off `prices` for the dead
            # name itself — which by definition has none.
            n_sess = con.execute(
                "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker = 'SPY' "
                "AND date > ? AND date <= ?", [last_bar, d]).fetchone()[0]
            px = con.execute(
                "SELECT close FROM prices WHERE ticker = ? AND date = ?",
                [tk, last_bar]).fetchone()
            val = qty * float(px[0]) if px else None
            eq = eq_by_book.get(pf_id)
            pct = (val / eq * 100) if (val is not None and eq) else None
            lines.append(
                f"| {pf_id} | {tk} | {qty:,.4f} | {last_bar} | {n_sess} | "
                f"{'·' if val is None else f'${val:,.2f}'} | "
                f"{'·' if pct is None else f'{pct:.2f}%'} |")
        lines.append("")

    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / "league.md"
    md_path.write_text("\n".join(lines))

    # full sim_equity export
    csv_df = con.execute(
        "SELECT portfolio_id, date, equity FROM sim_equity ORDER BY portfolio_id, date"
    ).fetch_df()
    csv_df.to_csv(reports_dir / "league.csv", index=False)
    return md_path


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def rerun_cleanup(con, d: date) -> None:
    """Delete date d's sim rows, then rebuild cash/positions from surviving fills.

    - sim_equity[d], sim_fills[fill_date=d] and sim_dividends[ex_date=d] are
      deleted (the day's dividend credits are re-paid by the re-run's phase a0).
    - Orders created on d (signal_date=d) are deleted.
    - Orders that filled on d now have no surviving fill → reset to pending so
      the re-run re-attempts them.
    - Rejected orders are left as-is: a reject is a deterministic outcome of the
      same data, so re-attempting d would reproduce it identically (documented).
    - State is rebuilt by replaying every surviving fill (exact).
    """
    con.execute("DELETE FROM sim_equity WHERE date = ?", [d])
    con.execute("DELETE FROM sim_fills WHERE fill_date = ?", [d])
    con.execute("DELETE FROM sim_dividends WHERE ex_date = ?", [d])
    # Orders the day-step CREATED are regenerated by the re-run; orders a
    # discretionary ticket created are not (the ticket is the owner's record and
    # points at the order by id) — deleting them left disc_tickets.order_id
    # dangling and the ticket 'submitted' forever.
    if table_exists(con, "disc_tickets"):
        con.execute(
            "DELETE FROM sim_orders WHERE signal_date = ? AND id NOT IN "
            "(SELECT order_id FROM disc_tickets WHERE order_id IS NOT NULL)", [d])
    else:
        con.execute("DELETE FROM sim_orders WHERE signal_date = ?", [d])
    con.execute(
        "UPDATE sim_orders SET status = 'pending', reject_reason = NULL "
        "WHERE status = 'filled' AND id NOT IN (SELECT order_id FROM sim_fills)"
    )
    portfolio.rebuild_state(con)


def step(con, d: date, data_dir: Path, rerun: bool, verbose: bool = True,
         skip_if_done: bool = False) -> int:
    existing = con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE date = ?", [d]
    ).fetchone()[0]
    if existing and rerun:
        later = con.execute(
            "SELECT COUNT(DISTINCT date) FROM sim_equity WHERE date > ?", [d]
        ).fetchone()[0]
        if later:
            # Re-running d after d+1.. have been stepped would replay d's fills
            # (regenerating d's orders) while d+1's fills of the ORIGINAL orders
            # survive — a double-count that rebuild_state cannot detect. A
            # historical re-run must roll back from the latest date down to d.
            log.error(f"[league] ABORT: --rerun {d} refused — {later} later session(s) "
                  f"already stepped. Re-run from the latest date backwards.")
            return 1
    if existing:
        if not rerun:
            if skip_if_done:
                # Benign no-op: the date is already stepped (e.g. a weekend/holiday
                # nightly where MAX(date) hasn't advanced, or a re-run). The report
                # already reflects this date. Exit 0 so the nightly never trips.
                if verbose:
                    log.info(f"[league] {d} already stepped ({existing} equity rows); "
                          f"--skip-if-done → no-op, exit 0")
                return 0
            if verbose:
                log.error(f"[league] ABORT: sim_equity already has {existing} rows for "
                      f"{d} — the step is idempotent. Pass --rerun to redo this date.")
            return 1
    # The whole per-day step is ONE DuckDB transaction so the day is all-or-
    # nothing. Without it, a mid-run death (e.g. after fills + partial equity
    # writes) leaves fills applied but that day's orders never generated and some
    # portfolios missing equity rows — and because "day done" is inferred from ANY
    # sim_equity[d] row existing, --skip-if-done would then no-op forever. Wrapping
    # fill_pending + mtm_all + generate_all (and the --rerun cleanup) in one
    # BEGIN…COMMIT makes a crash roll back everything, so a rerun redoes the whole
    # day exactly once. This also fixes the per-order double-fill window: the
    # INSERT sim_fills + apply_fill + UPDATE status trio is now atomic, so a crash
    # between them rolls back rather than double-filling on rerun.
    # (db.connect returns a fresh autocommit connection with no enclosing
    # transaction, so this BEGIN never nests.)
    con.execute("BEGIN TRANSACTION")
    try:
        if existing:  # reached only on --rerun (non-rerun already returned above)
            rerun_cleanup(con, d)
            if verbose:
                log.info(f"[league] --rerun: cleared {d} sim rows, rebuilt state")
        dv = portfolio.credit_dividends(con, d)
        fc = fill_pending(con, d)
        # verbose is threaded through so a walk-forward replay (thousands of
        # sessions, verbose=False) does not print a carried-mark line per day,
        # while the nightly — the one run a human reads — always does.
        mm = mtm_all(con, d, verbose=verbose)
        nn = generate_all(con, d)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    md_path = write_reports(con, d, data_dir)
    if verbose:
        div_note = (f" divs={dv['credited']}/${dv['amount']:,.2f}"
                    if dv["credited"] else "")
        n_carried = sum(len(v) for v in mm["carried"].values())
        carry_note = f" carried_marks={n_carried}" if n_carried else ""
        log.info(f"[league] {d}: fills={fc['filled']} rejected={fc['rejected']} "
              f"still_pending={fc['pending']} new_orders={nn}{div_note}"
              f"{carry_note} → {md_path}")
    return 0


def run(db_path: str, data_dir: Path, requested_date: str | None,
        do_init: bool, rerun: bool, skip_if_done: bool = False) -> int:
    con = db.connect(db_path)
    db.init_schema(con)
    db.init_actions_schema(con)   # dividends are read by phase a0 / total_return
    init_sim_schema(con)
    d = resolve_date(con, requested_date)

    if do_init:
        n = init_portfolios(con, d)
        log.info(f"[league] init: created {n} portfolios (as of {d})")

    have = con.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0]
    if not have:
        log.info("[league] no portfolios — run with --init first")
        con.close()
        return 1

    rc = step(con, d, data_dir, rerun, skip_if_done=skip_if_done)
    con.close()
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="M2 paper-league day-step.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="output dir")
    ap.add_argument("--date", default=None, help="step date YYYY-MM-DD (default: latest bar)")
    ap.add_argument("--init", action="store_true", help="create the 17 portfolios if absent")
    ap.add_argument("--rerun", action="store_true", help="redo an already-run date")
    ap.add_argument("--skip-if-done", action="store_true",
                    help="exit 0 (not 1) if the date is already stepped — for the "
                         "unattended nightly, where a weekend/holiday run re-sees the "
                         "same MAX(date). Real errors still fail loudly.")
    args = ap.parse_args()
    return run(args.db, Path(args.data_dir), args.date, args.init, args.rerun,
               skip_if_done=args.skip_if_done)


if __name__ == "__main__":
    raise SystemExit(main())
