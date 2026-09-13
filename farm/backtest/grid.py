#!/usr/bin/env python
"""The (book, window) grid — enumerate it, enqueue it, or run it locally.

The grid contains active, historically replayable books over
{6mo, 1y, 3y, 5y, 15y}, plus a data-limited `max` for ETF-only books. Retired
configs and strategies whose point-in-time inputs do not exist are excluded.

Priorities are staggered by window so SHORT windows land first — the queue
drains `ORDER BY priority ASC, created_at ASC`, and a partially-drained grid is
most useful when the cheap rows are the ones already filled in:

    6mo 140 · 1y 145 · 3y 150 · 5y 155 · 15y 160 · max 165

All of those are above the corporate-actions backfill (job 18, priority 130),
which must drain FIRST — dividend crediting and the total-return hurdles that
`dual_momentum` / `sector_momentum` rank on are only complete once it has run.
`--enqueue` refuses to run if a pending `actions` job sits at a priority that
would let a backtest overtake it.
"""
from __future__ import annotations

import argparse
import json

from engine.lib import db
from engine.lib.data_quality import FIXED_ETF_STRATEGIES
from engine.lib.log import get_logger
from engine.lib.settings import REPO_ROOT  # noqa: F401
from farm.backtest.replay import EXCLUDED, excluded_reason
from sim.strategies.configs import CONFIGS

log = get_logger("grid")

# Strategies eligible for `max`; centralized with result evidence labels.
ETF_ONLY = FIXED_ETF_STRATEGIES
PRIORITY = {"6mo": 140, "1y": 145, "3y": 150, "5y": 155, "15y": 160, "max": 165}
MEM_MB = 8000


def grid() -> list[tuple[str, str]]:
    out = []
    for w in ("6mo", "1y", "3y", "5y", "15y", "max"):
        for c in CONFIGS:
            if not c.get("active", True) or excluded_reason(c["id"], c["strategy"]):
                continue
            if w == "max" and c["strategy"] not in ETF_ONLY:
                continue
            out.append((c["id"], w))
    return out


def enqueue(con, only_window: str | None = None, dry_run: bool = False) -> int:
    from engine import queue_runner as qr

    blockers = con.execute(
        "SELECT id, kind, priority FROM jobs WHERE state = 'pending' "
        "AND kind = 'actions' ORDER BY priority").fetchall()
    for jid, kind, prio in blockers:
        worst = min(PRIORITY.values())
        if prio is None or prio >= worst:
            log.error(f"[grid] REFUSING to enqueue: pending {kind} job {jid} has "
                  f"priority {prio}, which does not drain before the grid's "
                  f"lowest backtest priority {worst}.")
            return 1
        log.info(f"[grid] pending {kind} job {jid} (priority {prio}) drains first — ok")

    n = 0
    for cid, w in grid():
        if only_window and w != only_window:
            continue
        params = json.dumps({"config_id": cid, "window": w}, sort_keys=True)
        if dry_run:
            log.info(f"[grid] would enqueue backtest {params} priority={PRIORITY[w]}")
        else:
            qr.cmd_enqueue(con, "backtest", params, PRIORITY[w], MEM_MB)
        n += 1
    log.info(f"[grid] {n} job(s) {'planned' if dry_run else 'enqueued'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="The backtest-farm job grid.")
    ap.add_argument("--db", default=None, help="DuckDB path (default: live store)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--enqueue", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--window", default=None, help="restrict to one window")
    args = ap.parse_args()

    if args.list:
        for cid, w in grid():
            print(f"{cid:<30} {w:<5} priority={PRIORITY[w]}")
        print(f"\n{len(grid())} jobs")
        for cid, why in EXCLUDED.items():
            print(f"EXCLUDED {cid}: {why}")
        for c in CONFIGS:
            if not c.get("active", True):
                print(f"EXCLUDED {c['id']}: retired (active=false)")
        return 0

    con = db.connect(args.db) if args.db else db.connect()
    try:
        db.init_schema(con)
        db.init_queue_schema(con)
        return enqueue(con, args.window, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
