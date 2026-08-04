#!/usr/bin/env python
"""The weekly walk-forward grid — enumerate it or enqueue it.

One job per ACTIVE book in the live `portfolios` table (the same source
`sim/league.py.generate_all` reads), minus the exclusions in `protocol.py`.
Job kind `walkforward`, params `{"config_id": …}` plus any protocol override.

Priorities sit BELOW everything else the farm runs (nightly archive/miner jobs
are 100-130, the historical-backtest grid is 140-165), so a walk-forward can
never delay a nightly stage, and they are staggered by MEASURED per-book cost
so a partially-drained grid is the cheap books already done rather than one
expensive book half-finished:

    170  ETF/sleeve books (spy_benchmark, dual_momentum, sector_momentum)
    172  template family, low_vol, high_52wk
    174  ew_benchmark, turtle_breakout, momo_stopped   (default)
    176  mr_overlay (and its gated twin) — the most expensive book by 3×

Intended cadence: **Sunday**, ahead of the weekly review (execution design §6).
`engine/run_daily.sh` is a weekday-only cron (`30 22 * * 1-5`) and never fires
on a Sunday, so this grid is enqueued by its own cron entry — see BUILDLOG.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import db  # noqa: E402

if __package__:
    from . import protocol
else:  # pragma: no cover
    from farm.walkforward import protocol

from farm.walkforward.runner import active_books  # noqa: E402

MEM_MB = 8000
DEFAULT_PRIORITY = 174
PRIORITY_BY_STRATEGY = {
    "spy_benchmark": 170, "dual_momentum": 170, "sector_momentum": 170,
    "template_top5": 172, "template_top10_banded": 172,
    "low_vol": 172, "high_52wk": 172,
    "ew_benchmark": 174, "turtle_breakout": 174, "momo_stopped": 174,
    "mr_overlay": 176,
}


def plan(live_con, overrides: dict | None = None) -> list[tuple[str, int, str]]:
    """[(config_id, priority, params_json)] for every eligible active book."""
    out = []
    for b in active_books(live_con):
        if b["excluded"]:
            continue
        params = {"config_id": b["id"], **(overrides or {})}
        out.append((b["id"],
                    PRIORITY_BY_STRATEGY.get(b["strategy"], DEFAULT_PRIORITY),
                    json.dumps(params, sort_keys=True)))
    return sorted(out, key=lambda x: (x[1], x[0]))


def enqueue(con, overrides: dict | None = None, dry_run: bool = False) -> int:
    import queue_runner as qr  # engine/queue_runner.py

    rows = plan(con, overrides)
    if not rows:
        print("[wf-grid] no eligible active books — nothing to enqueue")
        return 1
    n = 0
    for cid, prio, params in rows:
        if dry_run:
            print(f"[wf-grid] would enqueue walkforward {params} priority={prio}")
        else:
            qr.cmd_enqueue(con, "walkforward", params, prio, MEM_MB)
        n += 1
    print(f"[wf-grid] {n} job(s) {'planned' if dry_run else 'enqueued'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="The weekly walk-forward grid.")
    ap.add_argument("--db", default=None, help="DuckDB path (default: live store)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--enqueue", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--train-months", type=int, default=None)
    ap.add_argument("--validate-months", type=int, default=None)
    ap.add_argument("--step-months", type=int, default=None)
    ap.add_argument("--folds", type=int, default=None)
    ap.add_argument("--anchor", default=None)
    ap.add_argument("--extra-params", default=None,
                    help="JSON merged into every job's params (shakedown use: "
                         "results_dir / scratch_root redirection)")
    args = ap.parse_args()

    overrides = json.loads(args.extra_params) if args.extra_params else {}
    for key, val in (("train_months", args.train_months),
                     ("validate_months", args.validate_months),
                     ("step_months", args.step_months),
                     ("n_folds", args.folds), ("anchor", args.anchor)):
        if val is not None:
            overrides[key] = val

    if args.list:
        import duckdb
        live = duckdb.connect(args.db or str(db.DEFAULT_DB), read_only=True)
        try:
            for cid, prio, params in plan(live, overrides):
                print(f"{cid:<30} priority={prio}  params={params}")
            print(f"\n{len(plan(live, overrides))} jobs")
            for b in active_books(live):
                if b["excluded"]:
                    print(f"EXCLUDED {b['id']}: {b['excluded']}")
        finally:
            live.close()
        return 0

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)
    try:
        return enqueue(con, overrides, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
