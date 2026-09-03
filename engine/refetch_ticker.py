#!/usr/bin/env python
"""Replace ONE ticker's price history with the source's current view.

This is the single sanctioned case where `prices` rows are replaced rather than
appended: the stored rows are KNOWN-CORRUPT (a half-adjusted source pull that the
split reconciler then restated the wrong way) and the replacement is the same
source's own current, internally consistent series. Nothing is invented — the
rows come straight from yfinance with the exact parameters `collect.py` uses.

First use: JEM (BUILDLOG 2026-09-02). Yahoo's 2026-07-16 pull was half-adjusted
for the 1:12 reverse split, the reconciler multiplied 58 rows by 12 of which 2
were already right, so 04-17..07-09 sit at 12x Yahoo.

  --ticker T     canonical ticker (universe.ticker); yf_ticker is looked up
  --apply        write (default is a dry-run that prints before/after)
  --force        proceed even if a book holds the name (positions are NOT
                 touched; only prices change — the caller must reconcile)

Refuses a ticker with open sim_positions unless --force, because a re-scaled
history under a live position changes its mark without any corporate-action
record. Writes an audit_log row and flips the ticker's split_adjustments
watermark(s) to `superseded_by_refetch` (rows are kept, never deleted).
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

import duckdb

from engine.lib import db
from engine.lib.log import get_logger

log = get_logger("refetch")

SHOW_DATES = ["2026-04-17", "2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14"]


def fetch_history(yf_ticker: str, canon: str):
    """Max-history pull through collect.py's own download + parse helpers."""
    from engine import collect

    raw = collect._download([yf_ticker], period="max", start=None)
    df, got = collect._extract_long(raw, {yf_ticker: canon})
    return df if got else None


def _show(con, ticker: str, dates: list[str], label: str) -> None:
    n = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM prices WHERE ticker = ?",
                    [ticker]).fetchone()
    log.info(f"  [{label}] {ticker}: {n[0]} rows {n[1]}..{n[2]}")
    for d in dates:
        r = con.execute("SELECT open, close, volume FROM prices WHERE ticker = ? AND date = ?",
                        [ticker, date.fromisoformat(d)]).fetchone()
        if r is None:
            log.info(f"    {d}  (no row)")
        else:
            log.info(f"    {d}  open {r[0]:>12.4f}  close {r[1]:>12.4f}  vol {int(r[2] or 0):>12,}")


def refetch(con: duckdb.DuckDBPyConnection, ticker: str, *, apply: bool, force: bool,
            fetch=fetch_history, show_dates: list[str] | None = None) -> dict:
    show_dates = show_dates if show_dates is not None else SHOW_DATES
    held = con.execute(
        "SELECT COUNT(*) FROM sim_positions WHERE ticker = ? AND qty > 0", [ticker]
    ).fetchone()[0] if db_has(con, "sim_positions") else 0
    if held and not force:
        raise SystemExit(f"[refetch] REFUSED: {held} open position(s) in {ticker}; "
                         f"pass --force to replace its history anyway")

    row = con.execute("SELECT yf_ticker FROM universe WHERE ticker = ?", [ticker]).fetchone()
    yf_ticker = row[0] if row and row[0] else ticker

    _show(con, ticker, show_dates, "before")
    df = fetch(yf_ticker, ticker)
    if df is None or df.empty:
        raise SystemExit(f"[refetch] ABORT: source returned no rows for {ticker} ({yf_ticker})")
    # Continuity check on the replacement: a > 50% one-day move on a zero-volume bar
    # is the signature of the very corruption we are replacing.
    s = df.sort_values("date").reset_index(drop=True)
    bad = []
    for i in range(1, len(s)):
        prev, cur = float(s.close[i - 1]), float(s.close[i])
        if prev > 0 and abs(cur / prev - 1) > 0.5 and not (s.volume[i] or 0):
            bad.append((str(s.date[i]), prev, cur))
    if bad:
        raise SystemExit(f"[refetch] ABORT: replacement series has {len(bad)} suspicious "
                         f"zero-volume jumps: {bad[:5]}")

    old_n = con.execute("SELECT COUNT(*) FROM prices WHERE ticker = ?", [ticker]).fetchone()[0]
    out = {"ticker": ticker, "yf_ticker": yf_ticker, "rows_before": old_n,
           "rows_after": int(len(s)), "applied": apply}
    if not apply:
        log.info(f"[refetch] DRY-RUN: would replace {old_n} rows with {len(s)} fresh rows "
              f"({s.date.min()}..{s.date.max()}); nothing written")
        return out

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM prices WHERE ticker = ?", [ticker])
        n = db.upsert_prices(con, s)
        if db_has(con, "split_adjustments"):
            con.execute("UPDATE split_adjustments SET outcome = 'superseded_by_refetch' "
                        "WHERE ticker = ?", [ticker])
        if db_has(con, "audit_log"):
            con.execute(
                "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
                [datetime.now(timezone.utc), "refetch_ticker", "prices_replaced",
                 json.dumps({**out, "rows_written": n})])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    _show(con, ticker, show_dates, "after")
    log.info(f"[refetch] APPLIED: {ticker} {old_n} -> {n} rows; watermark superseded_by_refetch")
    return out


def db_has(con, table: str) -> bool:
    return con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
                       [table]).fetchone()[0] > 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    con = db.connect(a.db, read_only=not a.apply)
    try:
        refetch(con, a.ticker.upper(), apply=a.apply, force=a.force)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
