#!/usr/bin/env python
"""One-off: credit dividends the league missed before 2026-09-02.

Phase a0 matched `ex_date = d` and yfinance publishes a dividend the session
after its ex-date, so from inception (2026-07-17) to 2026-09-01 not one dividend
reached a book (sim_dividends had 0 rows; 26 entitled events). This runs the
fixed catch-up (`portfolio.credit_dividends`) once with a window that reaches
back to inception. Each credit lands at its TRUE ex-date with the position as of
ex_date - 1 reconstructed from sim_fills, so rebuild_state stays exact.

  --apply   write (default: run inside a transaction and ROLL BACK, printing
            what would be credited)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "engine"))

from lib import db  # noqa: E402
from sim import portfolio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(REPO_ROOT / "store" / "market.duckdb"))
    ap.add_argument("--as-of", default=None, help="step date (default MAX(sim_equity.date))")
    ap.add_argument("--lookback-days", type=int, default=60)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = db.connect(a.db)
    d = (date.fromisoformat(a.as_of) if a.as_of
         else con.execute("SELECT MAX(date) FROM sim_equity").fetchone()[0])
    before = con.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM sim_dividends").fetchone()
    print(f"[backfill-div] as_of={d} lookback={a.lookback_days}d  "
          f"sim_dividends before: {before[0]} rows / ${before[1]:,.2f}")
    con.execute("BEGIN TRANSACTION")
    try:
        out = portfolio.credit_dividends(con, d, lookback_days=a.lookback_days)
        rows = con.execute(
            "SELECT portfolio_id, ticker, ex_date, qty, dps, amount FROM sim_dividends "
            "ORDER BY ex_date, portfolio_id, ticker").fetchall()
        for pf, tk, ex, q, dps, amt in rows:
            print(f"    {ex}  {pf:<28} {tk:<6} {q:12.4f} x {dps:.4f} = ${amt:9.2f}")
        print(f"[backfill-div] {'APPLY' if a.apply else 'DRY-RUN'}: credited "
              f"{out['credited']} rows / ${out['amount']:,.2f}")
        if a.apply:
            con.execute("COMMIT")
            print("[backfill-div] committed")
        else:
            con.execute("ROLLBACK")
            print("[backfill-div] rolled back — nothing written")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
