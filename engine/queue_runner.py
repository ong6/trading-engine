#!/usr/bin/env python
"""§12.7 job-queue runner — one DuckDB `jobs` table, no ad-hoc worker pools.

Every heavy job (backfill, intraday archive, and later backtest sweeps /
walk-forwards) is enqueued as a row and drained here. Jobs run **in-process,
sequentially** for now: sequential trivially satisfies the "≤ 24 of 32 cores"
cap, and the dispatch table (JOB_TYPES) is the seam where a future capped worker
farm and new job types plug in.

Before starting ANY job the runner enforces the §12.7 guards and logs honestly:
  * re-nice self to 19 + ionice class 3 (best-effort);
  * 5-min load > 28 OR free RAM < 8 GiB  -> start nothing, leave pending, exit 0
    (the runner is re-invoked later; jobs are resumable so pausing is safe);
  * a job whose declared memory need > 48 GiB would blow the engine budget
    -> refuse that job with an error (sequential => budget == one job);
  * disk watchdog: store/ > 60 GiB soft -> set _meta.json disk_warning (merge);
    store/ > 80 GiB hard OR root free < 10 GiB -> refuse archive-type jobs
    (EOD collection is the last thing to stop; here we only gate archive jobs).

CLI:
  queue_runner.py --enqueue <type> [--params JSON] [--priority N] [--mem-mb MB]
  queue_runner.py --run       drain pending jobs (respecting the guards)
  queue_runner.py --status    print the jobs table
Common: --db (default store/market.duckdb), --meta (default data/_meta.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402
from lib import resources as rsc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_META = REPO_ROOT / "data" / "_meta.json"
STORE_DIR = REPO_ROOT / "store"

# §12.7 caps
LOAD_5MIN_MAX = 28.0        # 5-min load average ceiling
FREE_RAM_MIN_GB = 8.0       # refuse to start below this much free RAM
ENGINE_RAM_BUDGET_MB = 48000  # combined engine budget; sequential => one job
STORE_SOFT_GB = 60.0        # soft cap -> warn in _meta.json
STORE_HARD_GB = 80.0        # hard cap -> refuse archive jobs
ROOT_FREE_MIN_GB = 10.0     # refuse archive jobs below this root free space


# --------------------------------------------------------------------------- #
# dispatch table — the seam for new job types (backtest sweeps plug in here)
# --------------------------------------------------------------------------- #
def _load_intraday():
    import intraday
    return intraday.run


def _load_fundamentals():
    import fundamentals
    return fundamentals.run


def _load_earnings():
    import earnings
    return earnings.run


def _load_experiment():
    sys.path.insert(0, str(REPO_ROOT / "farm"))
    import experiment
    return experiment.run_job


JOB_TYPES: dict[str, dict] = {
    # type      loader (lazy)        archive?  default declared memory (MB)
    "intraday":     {"loader": _load_intraday,     "archive": True,  "mem_mb": 4000},
    "fundamentals": {"loader": _load_fundamentals, "archive": True,  "mem_mb": 2000},
    "earnings":     {"loader": _load_earnings,     "archive": True,  "mem_mb": 1000},
    "experiment":   {"loader": _load_experiment,   "archive": False, "mem_mb": 2000},
}


# --------------------------------------------------------------------------- #
# jobs table helpers
# --------------------------------------------------------------------------- #
def _next_id(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM jobs").fetchone()[0]


def _set_state(con, jid: int, state: str, *, progress: str | None = None,
               last_error: str | None = None) -> None:
    con.execute(
        "UPDATE jobs SET state = ?, updated_at = ?, "
        "progress = COALESCE(?, progress), last_error = COALESCE(?, last_error) "
        "WHERE id = ?",
        [state, datetime.now(timezone.utc), progress, last_error, jid],
    )


def cmd_enqueue(con, jtype: str, params: str, priority: int, mem_mb: int | None) -> int:
    if jtype not in JOB_TYPES:
        print(f"[queue] WARNING: unknown job type '{jtype}' "
              f"(known: {', '.join(JOB_TYPES)}); enqueuing anyway")
    # validate params JSON early so a bad payload fails at enqueue, not at run
    try:
        json.loads(params)
    except json.JSONDecodeError as exc:
        print(f"[queue] refusing to enqueue: --params is not valid JSON ({exc})")
        return 1

    if mem_mb is None:
        mem_mb = JOB_TYPES.get(jtype, {}).get("mem_mb", 0)

    jid = _next_id(con)
    now = datetime.now(timezone.utc)
    con.execute(
        "INSERT INTO jobs (id, kind, params, state, progress, priority, mem_mb, "
        "last_error, created_at, updated_at) "
        "VALUES (?, ?, ?, 'pending', ?, ?, ?, NULL, ?, ?)",
        [jid, jtype, params, "queued", priority, mem_mb, now, now],
    )
    print(f"[queue] enqueued job {jid}: {jtype} priority={priority} "
          f"mem_mb={mem_mb} params={params}")
    return 0


def cmd_status(con) -> int:
    rows = con.execute(
        "SELECT id, kind, state, priority, mem_mb, progress, last_error, updated_at "
        "FROM jobs ORDER BY id"
    ).fetchall()
    if not rows:
        print("[queue] no jobs")
        return 0
    hdr = f"{'id':>3}  {'kind':<12} {'state':<9} {'prio':>4} {'mem_mb':>7} " \
          f"{'progress':<12} {'updated_at':<26} last_error"
    print(hdr)
    print("-" * len(hdr))
    for jid, kind, state, prio, mem, prog, err, upd in rows:
        print(f"{jid:>3}  {kind or '':<12} {state or '':<9} "
              f"{('' if prio is None else prio):>4} "
              f"{('' if mem is None else mem):>7} {(prog or ''):<12} "
              f"{str(upd or ''):<26} {err or ''}")
    return 0


# --------------------------------------------------------------------------- #
# the drain loop
# --------------------------------------------------------------------------- #
def cmd_run(con, meta_path: str | Path) -> int:
    rsc.apply_niceness()

    pending = con.execute(
        "SELECT id, kind, params, mem_mb FROM jobs WHERE state = 'pending' "
        "ORDER BY priority ASC, created_at ASC"
    ).fetchall()
    if not pending:
        print("[queue] no pending jobs; nothing to do")
        return 0
    print(f"[queue] {len(pending)} pending job(s)")

    for idx, (jid, kind, params_json, mem_mb) in enumerate(pending):
        remaining = len(pending) - idx

        # --- global resource guard: load / RAM (start nothing if tripped) ---
        load5 = rsc.load_5min()
        free_gb = rsc.free_ram_gb()
        if load5 > LOAD_5MIN_MAX or free_gb < FREE_RAM_MIN_GB:
            reason = []
            if load5 > LOAD_5MIN_MAX:
                reason.append(f"5-min load {load5:.1f} > {LOAD_5MIN_MAX:.0f}")
            if free_gb < FREE_RAM_MIN_GB:
                reason.append(f"free RAM {free_gb:.1f} GiB < {FREE_RAM_MIN_GB:.0f}")
            print(f"[queue] resource guard tripped ({'; '.join(reason)}); "
                  f"leaving {remaining} job(s) pending and exiting 0 (resumable)")
            return 0

        # --- per-job memory budget guard (sequential => budget is one job) ---
        declared = mem_mb or 0
        if declared > ENGINE_RAM_BUDGET_MB:
            msg = (f"declared memory {declared} MB > {ENGINE_RAM_BUDGET_MB} MB "
                   f"engine budget")
            print(f"[queue] job {jid} ({kind}) refused: {msg}")
            _set_state(con, jid, "failed", last_error=msg)
            continue

        # --- disk watchdog (always refresh the soft warning) ---
        store_gb = rsc.dir_size_gb(STORE_DIR)
        root_free = rsc.root_free_gb("/")
        rsc.update_disk_warning(meta_path, store_gb, STORE_SOFT_GB)
        is_archive = JOB_TYPES.get(kind, {}).get("archive", False)
        if is_archive and (store_gb > STORE_HARD_GB or root_free < ROOT_FREE_MIN_GB):
            why = (f"store/ {store_gb:.1f} GiB > {STORE_HARD_GB:.0f} hard"
                   if store_gb > STORE_HARD_GB
                   else f"root free {root_free:.1f} GiB < {ROOT_FREE_MIN_GB:.0f}")
            print(f"[queue] disk watchdog: refusing archive job {jid} ({kind}): {why}; "
                  f"leaving it pending")
            continue

        # --- dispatch ---
        spec = JOB_TYPES.get(kind)
        if spec is None:
            msg = f"no dispatch entry for job type '{kind}'"
            print(f"[queue] job {jid} failed: {msg}")
            _set_state(con, jid, "failed", last_error=msg)
            continue

        try:
            params = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError as exc:
            _set_state(con, jid, "failed", last_error=f"bad params JSON: {exc}")
            print(f"[queue] job {jid} failed: bad params JSON ({exc})")
            continue

        print(f"[queue] --- running job {jid}: {kind} "
              f"(load {load5:.1f}, free RAM {free_gb:.1f} GiB, "
              f"store {store_gb:.2f} GiB) ---")
        _set_state(con, jid, "running", progress="started")
        try:
            fn = spec["loader"]()
            fn(params, con, meta_path=meta_path)
            _set_state(con, jid, "done", progress="complete")
            print(f"[queue] job {jid} ({kind}) done")
        except Exception as exc:  # noqa: BLE001 - one job failing must not sink the queue
            _set_state(con, jid, "failed", last_error=str(exc)[:500])
            print(f"[queue] job {jid} ({kind}) FAILED: {exc}")

    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="§12.7 job-queue runner.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--enqueue", metavar="TYPE", help="enqueue a job of this type")
    g.add_argument("--run", action="store_true", help="drain pending jobs (guarded)")
    g.add_argument("--status", action="store_true", help="print the jobs table")
    ap.add_argument("--params", default="{}", help="params JSON for --enqueue")
    ap.add_argument("--priority", type=int, default=100,
                    help="lower runs first (nightly loop < farm); default 100")
    ap.add_argument("--mem-mb", type=int, default=None,
                    help="declared memory need MB (default: per-type)")
    ap.add_argument("--db", default=None, help="DuckDB path (default store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    args = ap.parse_args()

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)

    try:
        if args.enqueue:
            return cmd_enqueue(con, args.enqueue, args.params, args.priority, args.mem_mb)
        if args.status:
            return cmd_status(con)
        return cmd_run(con, args.meta)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
