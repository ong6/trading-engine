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
import os
import sys
import time
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
# Concurrency for `parallel_safe` job kinds ONLY (see JOB_TYPES). Default 1 =
# the historical strictly-sequential drain; nothing changes unless --jobs is
# passed. Capped so a wide fan-out cannot starve the box or blow the RAM
# budget: each walkforward/backtest worker declares 8 GB.
PARALLEL_JOBS_MAX = 8

# Wall-clock ceiling for a single drain (env-tunable). Once elapsed exceeds this
# we STOP starting new jobs and exit 0, leaving them pending for the next drain —
# an in-flight job is never killed. Keeps a slow farm from running into the day.
DRAIN_BUDGET_DEFAULT_S = 4 * 3600  # 4 hours


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


def _load_actions():
    import actions
    return actions.run


def _load_signals():
    import signals
    return signals.run


def _load_experiment():
    sys.path.insert(0, str(REPO_ROOT / "farm"))
    import experiment
    return experiment.run_job


def _load_experiment_forward():
    sys.path.insert(0, str(REPO_ROOT / "farm"))
    import experiment_runner
    return experiment_runner.run_job


def _load_backtest():
    sys.path.insert(0, str(REPO_ROOT))
    from farm.backtest import replay
    return replay.run_job


def _load_walkforward():
    sys.path.insert(0, str(REPO_ROOT))
    from farm.walkforward import runner
    return runner.run_job


JOB_TYPES: dict[str, dict] = {
    # type      loader (lazy)        archive?  default declared memory (MB)
    "intraday":     {"loader": _load_intraday,     "archive": True,  "mem_mb": 4000},
    "fundamentals": {"loader": _load_fundamentals, "archive": True,  "mem_mb": 2000},
    "earnings":     {"loader": _load_earnings,     "archive": True,  "mem_mb": 1000},
    "actions":      {"loader": _load_actions,      "archive": True,  "mem_mb": 1000},
    # Macro/regime signal collector. archive=False: `macro_signals` is a few tens
    # of thousands of small rows a year, nothing the disk watchdog needs to gate.
    # The nightly (incremental) pass is a handful of small HTTP fetches plus one
    # session of breadth SQL; a --mode backfill job is the heavy one and is run
    # by hand, not by cron.
    "signals":      {"loader": _load_signals,      "archive": False, "mem_mb": 500},
    "experiment":   {"loader": _load_experiment,   "archive": False, "mem_mb": 2000},
    # Forward (out-of-sample) experiment record. Milliseconds of work, so the
    # nightly runs it inline after the league (see run_daily.sh) rather than
    # queueing it; this entry exists so a missed night can be replayed through
    # the normal job path.
    "experiment_forward": {"loader": _load_experiment_forward,
                           "archive": False, "mem_mb": 500},
    # §12.3 historical-backtest farm: one (book, window) replay per job on a
    # scratch copy of the store. archive=False — a backtest writes only into
    # scratch/ (deleted per job) and data/reports/, never into store/, so the
    # disk watchdog's archive gate does not apply to it; the guard that matters
    # is the load/RAM one, which applies to every job.
    "backtest":     {"loader": _load_backtest,     "archive": False, "mem_mb": 8000,
                     "parallel_safe": True},
    # §12.3 weekly walk-forward re-validation: one job per ACTIVE league book,
    # every fold replayed on a scratch copy. archive=False for the same reason
    # as `backtest` — it writes scratch/ (deleted per job) and data/reports/,
    # never store/. Feeds the Sunday review loop (execution design §6).
    "walkforward":  {"loader": _load_walkforward,  "archive": False, "mem_mb": 8000,
                     "parallel_safe": True},
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
        # An unknown type would only become a dead 'failed' row at drain — refuse it.
        print(f"[queue] ERROR: unknown job type '{jtype}' "
              f"(known: {', '.join(JOB_TYPES)}); refusing to enqueue")
        return 1
    # validate params JSON early so a bad payload fails at enqueue, not at run
    try:
        json.loads(params)
    except json.JSONDecodeError as exc:
        print(f"[queue] refusing to enqueue: --params is not valid JSON ({exc})")
        return 1

    # Dedup: if an identical (kind, params) job is already pending, don't stack a
    # duplicate. When the resource guard leaves jobs pending, back-to-back nightly
    # re-enqueues otherwise pile up N identical rows that all drain later (N
    # redundant yfinance pulls).
    dup = con.execute(
        "SELECT id FROM jobs WHERE kind = ? AND params = ? AND state = 'pending' "
        "ORDER BY id LIMIT 1",
        [jtype, params],
    ).fetchone()
    if dup is not None:
        print(f"[queue] job {dup[0]} ({jtype}) already pending with same params; "
              f"skipping duplicate enqueue")
        return 0

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
# parallel execution of `parallel_safe` job kinds
# --------------------------------------------------------------------------- #
# WHY SUBPROCESSES AND NOT THREADS. DuckDB is single-writer and a connection is
# not shareable across workers, so a parallel batch cannot borrow the drain's
# write connection. Each child opens its OWN READ-ONLY connection, which is why
# only kinds that never write `store/` may be marked `parallel_safe`: they work
# inside their own scratch/ store and emit JSON/markdown reports. A kind that
# writes the store (intraday, signals, earnings, fundamentals, actions) must
# stay sequential and is simply never batched.
#
# The parent RELEASES its write connection for the duration of the batch --
# otherwise the children could not open the file at all (DuckDB permits many
# readers OR one writer, never both) -- then reopens it to record outcomes.
# Children never touch the `jobs` table; the parent owns all state transitions,
# so a killed child is reclaimed by the usual orphan sweep on the next drain.

def cmd_run_one(jid: int, db_path: str | None, meta_path: str | Path) -> int:
    """Child entry: execute ONE job against a read-only connection.

    Exit code is the whole protocol -- 0 done, non-zero failed. State is the
    parent's business, deliberately: a child that dies mid-job leaves the row
    'running' and the next drain's orphan sweep returns it to 'pending'.
    """
    import duckdb
    rsc.apply_niceness()
    path = str(db_path or db.DEFAULT_DB)
    con = duckdb.connect(path, read_only=True)
    try:
        row = con.execute("SELECT kind, params FROM jobs WHERE id = ?", [jid]).fetchone()
        if row is None:
            print(f"[queue:{jid}] no such job")
            return 2
        kind, params_json = row
        spec = JOB_TYPES.get(kind)
        if spec is None:
            print(f"[queue:{jid}] no dispatch entry for '{kind}'")
            return 2
        if not spec.get("parallel_safe"):
            print(f"[queue:{jid}] '{kind}' is not parallel_safe - refusing")
            return 2
        params = json.loads(params_json) if params_json else {}
        spec["loader"]()(params, con, meta_path=meta_path)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[queue:{jid}] FAILED: {exc}")
        return 1
    finally:
        con.close()


def _run_parallel_batch(batch, db_path, meta_path, con) -> tuple[dict, object]:
    """Run `batch` [(jid, kind)] concurrently. Returns (results, new_con).

    Closes `con` for the duration (children need the file) and returns a fresh
    write connection, so the caller MUST rebind its connection to the second
    element.
    """
    import subprocess

    for jid, _k in batch:
        _set_state(con, jid, "running", progress="started (parallel)")
    con.close()

    procs = []
    for jid, kind in batch:
        cmd = [sys.executable, str(Path(__file__).resolve()),
               "--run-one", str(jid), "--meta", str(meta_path)]
        if db_path:
            cmd += ["--db", str(db_path)]
        procs.append((jid, kind, subprocess.Popen(cmd)))

    results = {}
    for jid, kind, pr in procs:
        rc = pr.wait()
        results[jid] = rc
        print(f"[queue] job {jid} ({kind}) {'done' if rc == 0 else f'FAILED rc={rc}'}")

    new_con = db.connect(db_path) if db_path else db.connect()
    for jid, rc in results.items():
        if rc == 0:
            _set_state(new_con, jid, "done", progress="complete")
        else:
            _set_state(new_con, jid, "failed",
                       last_error=f"parallel worker exited {rc}")
    return results, new_con


# --------------------------------------------------------------------------- #
# the drain loop
# --------------------------------------------------------------------------- #
def cmd_run(con, meta_path: str | Path, *, db_path=None, jobs: int = 1) -> int:
    rsc.apply_niceness()

    # Reclaim jobs a killed drain left in 'running'. Safe: DuckDB has a single
    # write lock, so holding this write connection proves no other drain is
    # alive — any 'running' row here is an orphan. Jobs are resumable by design.
    for (sid,) in con.execute("SELECT id FROM jobs WHERE state = 'running'").fetchall():
        _set_state(con, sid, "pending", progress="reclaimed")
        print(f"[queue] reclaimed stale running job {sid} -> pending (prior drain died)")

    pending = con.execute(
        "SELECT id, kind, params, mem_mb FROM jobs WHERE state = 'pending' "
        "ORDER BY priority ASC, created_at ASC"
    ).fetchall()
    if not pending:
        print("[queue] no pending jobs; nothing to do")
        return 0
    print(f"[queue] {len(pending)} pending job(s)")

    budget_s = float(os.environ.get("TRADING_ENGINE_DRAIN_BUDGET_S",
                                    DRAIN_BUDGET_DEFAULT_S))
    drain_start = time.monotonic()

    # --- parallel pre-pass over `parallel_safe` kinds -----------------------
    # Runs BEFORE the sequential loop rather than inside it: the store-writing
    # kinds must keep the single writer to themselves, and interleaving a batch
    # with them would mean closing/reopening the write connection repeatedly.
    # Batches are sized by the SAME RAM budget the sequential path uses, so a
    # fan-out can never declare more memory than one sequential job was allowed.
    jobs = max(1, min(int(jobs), PARALLEL_JOBS_MAX))
    if jobs > 1:
        par = [(jid, kind, mem_mb or 0) for jid, kind, _pj, mem_mb in pending
               if JOB_TYPES.get(kind, {}).get("parallel_safe")]
        if par:
            per_batch = max(1, min(jobs, ENGINE_RAM_BUDGET_MB // max(
                1, max(m for _j, _k, m in par))))
            if per_batch < jobs:
                print(f"[queue] parallel width {jobs} -> {per_batch} "
                      f"(RAM budget {ENGINE_RAM_BUDGET_MB} MB / "
                      f"{max(m for _j, _k, m in par)} MB per worker)")
            print(f"[queue] {len(par)} parallel-safe job(s), width {per_batch}")
            for i in range(0, len(par), per_batch):
                if time.monotonic() - drain_start > budget_s:
                    print("[queue] drain budget exhausted - leaving the rest pending")
                    return 0
                load5, free_gb = rsc.load_5min(), rsc.free_ram_gb()
                if load5 > LOAD_5MIN_MAX or free_gb < FREE_RAM_MIN_GB:
                    print(f"[queue] resource guard tripped (load {load5:.1f}, "
                          f"free RAM {free_gb:.1f} GiB) - leaving the rest pending")
                    return 0
                batch = [(j, k) for j, k, _m in par[i:i + per_batch]]
                print(f"[queue] --- parallel batch {[j for j, _ in batch]} "
                      f"(load {load5:.1f}, free RAM {free_gb:.1f} GiB) ---")
                _res, con = _run_parallel_batch(batch, db_path, meta_path, con)
            # states changed underneath us; re-read what is still pending
            pending = con.execute(
                "SELECT id, kind, params, mem_mb FROM jobs WHERE state = 'pending' "
                "ORDER BY priority ASC, created_at ASC").fetchall()
            if not pending:
                print("[queue] all jobs drained")
                return 0

    for idx, (jid, kind, params_json, mem_mb) in enumerate(pending):
        remaining = len(pending) - idx

        # --- wall-clock budget: stop STARTING new jobs once the window is up ---
        elapsed = time.monotonic() - drain_start
        if elapsed > budget_s:
            print(f"[queue] drain budget exhausted after {elapsed / 3600:.1f}h — "
                  f"leaving {remaining} pending job(s) for next drain")
            return 0

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
    g.add_argument("--run-one", type=int, metavar="JOB_ID",
                   help="internal: execute ONE parallel_safe job read-only "
                        "(spawned by --run --jobs N; not for manual use)")
    ap.add_argument("--params", default="{}", help="params JSON for --enqueue")
    ap.add_argument("--priority", type=int, default=100,
                    help="lower runs first (nightly loop < farm); default 100")
    ap.add_argument("--mem-mb", type=int, default=None,
                    help="declared memory need MB (default: per-type)")
    ap.add_argument("--db", default=None, help="DuckDB path (default store/market.duckdb)")
    ap.add_argument("--meta", default=str(DEFAULT_META), help="_meta.json path")
    ap.add_argument("--jobs", type=int, default=1,
                    help=f"max concurrent parallel_safe jobs (1 = sequential, "
                         f"max {PARALLEL_JOBS_MAX}); store-writing kinds always "
                         f"run one at a time")
    args = ap.parse_args()

    # Child mode opens its own READ-ONLY connection inside cmd_run_one; taking
    # the write lock here would deadlock it against its own parent.
    if args.run_one is not None:
        return cmd_run_one(args.run_one, args.db, args.meta)

    con = db.connect(args.db) if args.db else db.connect()
    db.init_schema(con)
    db.init_queue_schema(con)

    try:
        if args.enqueue:
            return cmd_enqueue(con, args.enqueue, args.params, args.priority, args.mem_mb)
        if args.status:
            return cmd_status(con)
        return cmd_run(con, args.meta, db_path=args.db, jobs=args.jobs)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
