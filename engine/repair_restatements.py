#!/usr/bin/env python
"""Revert FALSE split restatements made by the reconciler (2026-09-02 incident).

Background: `actions._adjudicate` used to accept any one-session close ratio
within ±20% (log) of the split ratio anywhere in a 25-session window as "the
break". For a 3:2 split that band is an ordinary −20%…−44% day, and three
earnings crashes were taken for scale breaks: every stored bar before them was
divided by 1.5 (volume ×1.5) and the split watermarked `applied`:

    BH    ex 2018-05-01  break 2018-04-27  9,612 rows
    ORCL  ex 1999-03-01  break 1999-03-12  3,286 rows  (real split already adjusted by Yahoo)
    NEM   ex 1987-10-09  break 1987-10-16  1,918 rows

This script inverts exactly that arithmetic for a given (ticker, break_date,
ratio): open/high/low/close × ratio and volume ÷ ratio for `date < break_date`,
flips the `split_adjustments` watermark to `reverted_false_break` (the row is
kept, so the nightly reconcile never re-adjudicates the split — and even if it
did, the fixed adjudicator would not re-apply it), and appends an `audit_log`
row. Nothing is deleted. If the ticker has sim_fills, the books are rebuilt
from fills so no position keeps a stale ×ratio (none of the three names has
ever been held).

Usage (dry-run is the default and opens the store read-only):

    .venv/bin/python -m engine.repair_restatements --db <copy>              # dry-run, defaults
    .venv/bin/python -m engine.repair_restatements --db <copy> --apply --yahoo
    .venv/bin/python -m engine.repair_restatements --apply --yahoo          # live store

`--target TICKER:BREAK_DATE:RATIO` (repeatable) overrides the three defaults.
`--yahoo` pulls each name's current yfinance history and reports
median(store/yahoo close) over 30 sessions before and after the break — a
correct series reads ~1.0 on both sides; the false restatement read ~1/ratio
before. --apply opens the store through the project's writer path
(`engine/lib/db.connect`, single-writer lock discipline). Never run it while
the nightly or a queue job is active.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.log import get_logger
from engine.lib.settings import REPO_ROOT  # noqa: F401

log = get_logger("repair")

REVERTED = "reverted_false_break"
ACTOR = "actions.repair_restatements"
DEFAULT_TARGETS = ["BH:2018-04-27:1.5", "ORCL:1999-03-12:1.5", "NEM:1987-10-16:1.5"]


def parse_target(s: str) -> tuple[str, date, float]:
    tk, brk, ratio = s.split(":")
    return tk.strip().upper(), date.fromisoformat(brk), float(ratio)


def _bars(con, tk: str, around: date, before: int = 2, after: int = 2) -> list[tuple]:
    pre = con.execute(
        "SELECT date, open, close, volume FROM prices WHERE ticker = ? AND date < ? "
        "ORDER BY date DESC LIMIT ?", [tk, around, before]).fetchall()
    post = con.execute(
        "SELECT date, open, close, volume FROM prices WHERE ticker = ? AND date >= ? "
        "ORDER BY date LIMIT ?", [tk, around, after]).fetchall()
    return list(reversed(pre)) + post


def show(con, label: str, tk: str, brk: date, ex: date) -> None:
    n, first = con.execute(
        "SELECT COUNT(*), MIN(date) FROM prices WHERE ticker = ? AND date < ?",
        [tk, brk]).fetchone()
    log.info(f"  [{label}] {tk}: {n} rows before break {brk} (from {first})")
    for tag, d in (("break", brk), ("ex", ex)):
        rows = _bars(con, tk, d)
        for dt, o, c, v in rows:
            mark = "<-- " + tag if dt == d else ""
            log.info(f"    {dt}  open {o:>12.4f}  close {c:>12.4f}  vol {v:>12,d}  {mark}")
        if tag == "break" and len(rows) >= 3:
            prev = [r for r in rows if r[0] < d][-1]
            cur = [r for r in rows if r[0] >= d][0]
            log.info(f"    one-session close ratio prev/cur at break = {prev[2] / cur[2]:.4f} "
                  f"(move {cur[2] / prev[2] - 1:+.1%})")


def revert(con, tk: str, brk: date, ratio: float, apply: bool) -> bool:
    row = con.execute(
        "SELECT ex_date, ratio, outcome, rows_restated, observed FROM split_adjustments "
        "WHERE ticker = ? AND break_date = ?", [tk, brk]).fetchone()
    if row is None:
        log.warning(f"SKIP {tk}: no split_adjustments row with break_date {brk}")
        return False
    ex, w_ratio, outcome, n_rest, observed = row
    if outcome != "applied":
        log.warning(f"SKIP {tk} ex={ex}: watermark outcome is '{outcome}', not 'applied' "
              f"(already reverted?)")
        return False
    if abs(float(w_ratio) - ratio) > 1e-9:
        log.warning(f"SKIP {tk} ex={ex}: watermark ratio {w_ratio} != requested {ratio}")
        return False
    n = con.execute("SELECT COUNT(*) FROM prices WHERE ticker = ? AND date < ?",
                    [tk, brk]).fetchone()[0]
    log.info(f"== {tk} split {ratio:g}:1 ex={ex} break={brk} watermark rows_restated={n_rest} "
          f"observed={observed} -> {n} rows to multiply back by {ratio:g}")
    show(con, "before", tk, brk, ex)
    if not apply:
        log.info("  dry-run: no changes written")
        return True

    n_fills = con.execute("SELECT COUNT(*) FROM sim_fills WHERE ticker = ?", [tk]).fetchone()[0]
    n_pos = con.execute("SELECT COUNT(*) FROM sim_positions WHERE ticker = ? AND qty != 0",
                        [tk]).fetchone()[0]
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "UPDATE prices SET open = open * ?, high = high * ?, low = low * ?, "
            "close = close * ?, volume = CAST(ROUND(volume / ?) AS BIGINT) "
            "WHERE ticker = ? AND date < ?",
            [ratio, ratio, ratio, ratio, ratio, tk, brk])
        con.execute(
            "UPDATE split_adjustments SET outcome = ?, applied_at = ? "
            "WHERE ticker = ? AND ex_date = ?",
            [REVERTED, datetime.now(timezone.utc), tk, ex])
        if n_fills:
            # The watermark is no longer 'applied', so rebuild_state stops scaling
            # this name's pre-ex fills — recompute the books from the ledger.
            from sim import portfolio
            portfolio.rebuild_state(con)
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [datetime.now(timezone.utc), ACTOR, "split_restatement_reverted",
             json.dumps({"ticker": tk, "ex_date": ex, "ratio": ratio, "break_date": brk,
                         "rows_reverted": n, "original_rows_restated": n_rest,
                         "original_observed": observed, "reason": "false break: "
                         "ordinary price move inside the old ±20% tolerance; series was "
                         "already on Yahoo's adjusted scale (audit 2026-09-02)",
                         "sim_fills_for_ticker": n_fills, "open_positions_for_ticker": n_pos,
                         "books_rebuilt": bool(n_fills)}, default=str)])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    show(con, "after", tk, brk, ex)
    log.info(f"  watermark -> {REVERTED}; audit_log row appended"
          + ("; sim books rebuilt from fills" if n_fills else "; no fills for this name"))
    return True


def yahoo_check(con, targets: list[tuple[str, date, float]]) -> None:
    import pandas as pd
    import yfinance as yf

    ymap = dict(con.execute(
        "SELECT ticker, COALESCE(yf_ticker, ticker) FROM universe WHERE ticker IN "
        f"({','.join(['?'] * len(targets))})", [t[0] for t in targets]).fetchall())
    syms = sorted({ymap.get(tk, tk) for tk, _b, _r in targets})
    raw = yf.download(syms, period="max", auto_adjust=False, group_by="ticker",
                      threads=True, progress=False)
    log.info("\n== Yahoo cross-check: median(store close / yahoo close), 30 sessions each side of the break")
    for tk, brk, ratio in targets:
        yft = ymap.get(tk, tk)
        y = raw[yft]["Close"].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw["Close"].dropna()
        y.index = pd.to_datetime(y.index).date
        s = dict(con.execute("SELECT date, close FROM prices WHERE ticker = ? ORDER BY date",
                             [tk]).fetchall())
        common = [d for d in y.index if d in s and y[d] > 0]
        bef = [s[d] / y[d] for d in sorted(d for d in common if d < brk)[-30:]]
        aft = [s[d] / y[d] for d in sorted(d for d in common if d >= brk)[:30]]
        allr = [s[d] / y[d] for d in common]
        off = sum(1 for r in allr if abs(r - 1) > 0.01)
        mb = statistics.median(bef) if bef else float("nan")
        ma = statistics.median(aft) if aft else float("nan")
        verdict = "OK — one scale, matches Yahoo" if abs(mb - 1) < 0.02 and abs(ma - 1) < 0.02 else (
            "STILL DIVIDED (store = yahoo/ratio before break)" if abs(mb * ratio - 1) < 0.02 else "DIFFERS")
        log.info(f"  {tk:5} before {mb:.4f} (n={len(bef)})  after {ma:.4f} (n={len(aft)})  "
              f"rows >1% off Yahoo: {off}/{len(allr)}  -> {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None, help="DuckDB path (default store/market.duckdb)")
    ap.add_argument("--target", action="append", default=None,
                    help="TICKER:BREAK_DATE:RATIO (repeatable); default = the three 2026-09-02 names")
    ap.add_argument("--apply", action="store_true", help="write (default is a read-only dry-run)")
    ap.add_argument("--yahoo", action="store_true", help="cross-check against current yfinance history")
    args = ap.parse_args()
    targets = [parse_target(t) for t in (args.target or DEFAULT_TARGETS)]
    path = Path(args.db) if args.db else db.DEFAULT_DB

    if args.apply:
        con = db.connect(path)            # project writer path: lock retry discipline
        log.info(f"[repair] APPLY on {path}")
    else:
        con = db.connect(path, read_only=True)
        log.info(f"[repair] DRY-RUN (read-only) on {path}")
    try:
        for tk, brk, ratio in targets:
            revert(con, tk, brk, ratio, args.apply)
        if args.yahoo:
            yahoo_check(con, targets)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
