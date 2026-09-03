#!/usr/bin/env python
"""Execution-timing drag — what does trading at next-open (vs the signal close) cost?

Read-only over the live store. For every sim fill, the drag is the signed move from the
signal-day close to what we actually did:

    overnight bp = side_sign * (open_px  / signal_close - 1) * 1e4   # the delay alone
    all-in    bp = side_sign * (fill_px  / signal_close - 1) * 1e4   # delay + slippage

cost > 0 is adverse (buys that opened higher, sells that opened lower). This quantifies the
"we trade after hours, are we missing moves?" question from the bot's own record instead of
assuming an answer. Run manually or from the weekly review:

    .venv/bin/python -m farm.execution_drag            # print + write the report
    .venv/bin/python -m farm.execution_drag --no-write # print only

Interpretation guard: at small n this is noise-dominated (per-fill stdev is ~15-20x the
mean). Do not act on it before the t-stat clears ~2, and read it per book — mean-reversion
entries systematically BENEFIT from the overnight delay (buying continued weakness), so a
single all-book mean hides opposite-signed effects.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date

from engine.lib import db
from engine.lib.settings import DATA_DIR, REPO_ROOT  # noqa: F401

DB_PATH = db.DEFAULT_DB
REPORT = DATA_DIR / "reports" / "execution-drag.md"

QUERY = """
    SELECT f.portfolio_id, f.side, f.fill_date, o.signal_date, f.open_px, f.fill_px,
           (SELECT close FROM prices p
             WHERE p.ticker = f.ticker AND p.date = o.signal_date) AS sig_close
    FROM sim_fills f JOIN sim_orders o ON o.id = f.order_id
    ORDER BY f.fill_date
"""


def stats(xs: list[float]) -> dict:
    n = len(xs)
    mean = statistics.mean(xs)
    sd = statistics.stdev(xs) if n > 1 else 0.0
    t = mean / (sd / n**0.5) if n > 1 and sd > 0 else 0.0
    return {"n": n, "mean": mean, "sd": sd, "t": t}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--no-write", action="store_true", help="print only, skip the report file")
    args = ap.parse_args()

    con = db.connect(args.db, read_only=True)
    overnight: list[float] = []
    allin: list[float] = []
    per_book: dict[str, list[float]] = {}
    skipped = 0
    for pf, side, _fd, _sd, open_px, fill_px, sig_close in con.execute(QUERY).fetchall():
        if sig_close is None:
            skipped += 1  # signal-day bar missing — never invent a price
            continue
        sgn = 1 if side == "buy" else -1
        overnight.append(sgn * (open_px / sig_close - 1) * 1e4)
        allin.append(sgn * (fill_px / sig_close - 1) * 1e4)
        per_book.setdefault(pf, []).append(overnight[-1])
    con.close()

    if len(overnight) < 2:
        print("[execution-drag] fewer than 2 usable fills — nothing to report")
        return 0

    ov = stats(overnight)
    ai = stats(allin)
    adverse = sum(1 for d in overnight if d > 0)

    lines = [
        f"# Execution-timing drag — as of {date.today().isoformat()}",
        "",
        "Signed cost (bp, >0 = adverse) of filling at next-open vs the signal-day close,",
        "over every sim fill on record. See farm/execution_drag.py for method and the",
        "interpretation guard (noise-dominated at small n; read per book).",
        "",
        f"- Fills: **{ov['n']}**" + (f" ({skipped} skipped, no signal-day bar)" if skipped else ""),
        f"- Overnight move alone: mean **{ov['mean']:+.1f} bp** · stdev {ov['sd']:.0f} bp · t = {ov['t']:.2f}",
        f"- All-in (incl. slippage): mean **{ai['mean']:+.1f} bp**",
        f"- Adverse overnight moves: {adverse}/{ov['n']}",
        "",
        "| Book | mean overnight bp | n | t |",
        "|---|---|---|---|",
    ]
    for pf in sorted(per_book):
        s = stats(per_book[pf]) if len(per_book[pf]) > 1 else {
            "n": 1, "mean": per_book[pf][0], "t": 0.0}
        lines.append(f"| {pf} | {s['mean']:+.1f} | {s['n']} | {s['t']:.2f} |")
    lines += [
        "",
        "_Decision rule (pre-committed 2026-07-29): consider close-execution (MOC-style)",
        "A/B variants only for a book whose drag is adverse with t > 2 at n ≥ 100 own",
        "fills. Mean-reversion books are expected to keep a favorable sign — leave them._",
        "",
    ]
    text = "\n".join(lines)
    print(text)
    if not args.no_write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text)
        print(f"[execution-drag] wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
