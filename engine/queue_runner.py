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
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib import resources as rsc
from engine.lib.settings import REPO_ROOT, STORE_DIR
from engine.lib.settings import META_PATH as DEFAULT_META

# §12.7 caps
# 5-min load ceiling. Kept at 28 after measurement (2026-08-20): a width-8
# parallel batch of replay workers at 4 DuckDB threads each sustains ~2.5-3
# cores per worker (~20-24 load incl. nightly stages), and even a deliberate
# 16-worker burst only pushed the 5-MIN average to ~16 (1-min hit 28.4). The
# guard EXITS the drain rather than waiting, so margin matters: tripping it on
# a Sunday grid parks the remaining jobs until Monday's nightly. Raising it is
# not needed for width 8 and would erode the §12.7 promise that the farm never
# starves the nightly or the interactive API (~24 of 32 cores for the farm).
LOAD_5MIN_MAX = 28.0
FREE_RAM_MIN_GB = 8.0       # refuse to start below this much free RAM
ENGINE_RAM_BUDGET_MB = 48000  # combined engine budget; sequential => one job
STORE_SOFT_GB = 60.0        # soft cap -> warn in _meta.json
STORE_HARD_GB = 80.0        # hard cap -> refuse archive jobs
ROOT_FREE_MIN_GB = 10.0     # refuse archive jobs below this root free space
# Concurrency for `parallel_safe` job kinds ONLY (see JOB_TYPES). Default 1 =
# the historical strictly-sequential drain; nothing changes unless --jobs is
# passed. Capped so a wide fan-out cannot starve the box or blow the RAM
# budget: each walkforward/backtest/sweep worker declares 4.5 GB (measured
# 2026-08-20, see JOB_TYPES).
#
# Width 8 chosen from measurement (2026-08-20, 32-core box, baseline load ~6
# incl. one live sweep worker at ~3.7 cores): a fixed unit of 8 identical
# 1-fold ew_benchmark replays ran at 205 jobs/h with 2 workers x 8 DuckDB
# threads, 355 with 4x4, 505 with 8x2, and 523 with 8x4 — width, not threads,
# is the throughput lever. 16 workers measured 670 jobs/h but drove the 1-min
# load to 28.4 and would put 16 x 3.4 GB = ~54 GB of real peak RSS on a 62 GB
# box for production 10-fold jobs — infeasible. 8 wide keeps sustained load
# ~20-24 with the nightly's own stages on top, under LOAD_5MIN_MAX with margin.
PARALLEL_JOBS_MAX = 8
# Seconds between launching successive workers in a batch. See the stagger
# comment in _run_parallel_batch: the RSS peak is front-loaded into
# build_scratch, so simultaneous starts stack every peak at the same instant.
BATCH_STAGGER_S = 4.0
# How long the drain waits to reacquire the write lock after a parallel batch.
# Must exceed the longest single writer stage a nightly can hold (collect,
# ~4 min) or a batch that ends inside that window sinks the whole drain.
BATCH_REACQUIRE_WAIT_S = 900.0

# Wall-clock ceiling for a single drain (env-tunable). Once elapsed exceeds this
# we STOP starting new jobs and exit 0, leaving them pending for the next drain —
# an in-flight job is never killed. Keeps a slow farm from running into the day.
DRAIN_BUDGET_DEFAULT_S = 4 * 3600  # 4 hours


# --------------------------------------------------------------------------- #
# dispatch table — the seam for new job types (backtest sweeps plug in here)
# --------------------------------------------------------------------------- #
def _load_intraday():
    from engine import intraday
    return intraday.run


def _load_fundamentals():
    from engine import fundamentals
    return fundamentals.run


def _load_earnings():
    from engine import earnings
    return earnings.run


def _load_actions():
    from engine import actions
    return actions.run


def _load_signals():
    from engine import signals
    return signals.run


def _load_experiment():
    from farm import experiment
    return experiment.run_job


def _load_experiment_forward():
    from farm import experiment_runner
    return experiment_runner.run_job


def _load_backtest():
    from farm.backtest import replay
    return replay.run_job


def _load_sweep():
    from farm.sweep import sweep
    return sweep.run_job


def _load_walkforward():
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
    # mem_mb 8000 -> 4500 (2026-08-20): measured, not guessed. A live 10-fold
    # sweep worker's lifetime peak RSS (VmHWM) after 4.5 h of a full grid was
    # 3,409 MB; a 2-fold walkforward replay peaked at 2,308 MB (1s sampling —
    # the peak is the build_scratch parquet export, first ~15 s). 4500 MB =
    # measured worst case +32% headroom. The old 8000 was a 5.3x over-
    # declaration of steady-state and throttled batches to 48000//8000 = 6.
    "backtest":     {"loader": _load_backtest,     "archive": False, "mem_mb": 4500,
                     "parallel_safe": True},
    # §12.3 weekly walk-forward re-validation: one job per ACTIVE league book,
    # every fold replayed on a scratch copy. archive=False for the same reason
    # as `backtest` — it writes scratch/ (deleted per job) and data/reports/,
    # never store/. Feeds the Sunday review loop (execution design §6).
    # mem_mb 4500: same measurement as `backtest` above (2026-08-20).
    "walkforward":  {"loader": _load_walkforward,  "archive": False, "mem_mb": 4500,
                     "parallel_safe": True},
    # Parameter sweep over an existing strategy class (farm/sweep/sweep.py). Same
    # profile as walkforward -- read-only on the store, writes only scratch/ and
    # data/reports/sweeps/ -- so it batches the same way. One job = one GRID, and
    # the grid runs its candidates in-process, so the batch width multiplies with
    # the candidate count: keep sweep jobs to a couple per drain.
    # mem_mb 4500: measured on THIS kind — the live meanrev sweep worker's
    # VmHWM was 3,409 MB four+ hours into a 10-fold grid (2026-08-20).
    "sweep":        {"loader": _load_sweep,        "archive": False, "mem_mb": 4500,
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
    rsc.apply_niceness()
    con = db.connect(db_path or db.DEFAULT_DB, read_only=True)
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
    for i, (jid, kind) in enumerate(batch):
        # STAGGER THE STARTS. A worker's RSS peak is not spread over its life —
        # it lands in the first ~15 s, during `build_scratch`'s parquet export
        # (measured 2026-08-20: 3,409 MB peak on a 10-fold sweep worker, ~1.2-1.5
        # GB steady-state after). Launching a batch simultaneously therefore
        # ALIGNS every worker's peak, which is the worst case rather than an
        # unlucky one: 8 x 3.4 GB = 26.6 GB arriving at once leaves roughly
        # 1.9 GB above the FREE_RAM_MIN_GB floor, and tripping that floor parks
        # the rest of the drain until the next run.
        #
        # A few seconds between launches decorrelates the peaks almost entirely
        # and costs nothing: these jobs run for minutes to hours.
        if i:
            time.sleep(BATCH_STAGGER_S)
        cmd = [sys.executable, "-m", "engine.queue_runner",
               "--run-one", str(jid), "--meta", str(meta_path)]
        if db_path:
            cmd += ["--db", str(db_path)]
        procs.append((jid, kind, subprocess.Popen(cmd, cwd=str(REPO_ROOT))))

    results = {}
    for jid, kind, pr in procs:
        rc = pr.wait()
        results[jid] = rc
        print(f"[queue] job {jid} ({kind}) {'done' if rc == 0 else f'FAILED rc={rc}'}")

    # Reacquiring the writer can collide with a nightly that started while the
    # batch ran (collect holds it for ~4 min), and losing the race would crash
    # the drain and bounce every batched job back to 'pending'. Wait 15 min.
    new_con = (db.connect(db_path, wait_s=BATCH_REACQUIRE_WAIT_S) if db_path
               else db.connect(wait_s=BATCH_REACQUIRE_WAIT_S))
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
_DRAIN_LOCK_FD: int | None = None


def acquire_drain_lock() -> bool:
    """Take the exclusive drain lock, or return False if another drain holds it.

    MUST be called BEFORE opening the DuckDB write connection. Order matters:
    a second drain that connects first would sit through db.connect's retry
    window and then die non-zero, which in the nightly's farm subshell reads as
    a farm failure. Declining early and cleanly is the correct outcome — the
    queue is already being worked, and the jobs stay pending for the next drain.

    The fd is deliberately leaked for the process lifetime: the lock must
    outlive this function and be released by process exit.
    """
    global _DRAIN_LOCK_FD
    fd = os.open(str(REPO_ROOT / ".queue-drain.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _DRAIN_LOCK_FD = fd
    return True


def cmd_run(con, meta_path: str | Path, *, db_path=None, jobs: int = 1) -> int:
    # Line-buffer the drain's own stdout. Redirected to a log it is otherwise
    # block-buffered, so a batch's children (separate processes, own buffers)
    # write through while the parent's "--- parallel batch [...] ---" line sits
    # unflushed for minutes — a tailed log then shows work with no record of
    # what started it.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001 - observability only, never fatal
        pass
    rsc.apply_niceness()

    # --- ONE DRAIN AT A TIME, enforced independently of the DuckDB writer ----
    # The orphan sweep below reclaims every 'running' row on the grounds that no
    # other drain can be alive. Until 2026-08-20 that was guaranteed by holding
    # the DuckDB write connection, since DuckDB permits exactly one writer.
    #
    # BATCHING BROKE THAT INVARIANT. `_run_parallel_batch` RELEASES the writer
    # for the batch's whole duration — which, now that the nightly drains with
    # --jobs 4, is most of a drain's life. A second drain starting in that
    # window (the 22:30 nightly landing while a weekend sweep is still going)
    # would acquire the writer, see the first drain's live children as orphans,
    # reclaim them to 'pending' and RE-RUN THEM: two processes writing the same
    # data/reports/sweeps/<grid>/results/*.json, after which the first drain's
    # reacquire stamps them 'done'. Verified reachable on 2026-08-20 with jobs
    # 209/210 'running', a live child, and the writer free.
    #
    # The per-script flocks (.sweeps.lock, .walkforward.lock) do not help: they
    # guard their own script, not the drain. So the drain takes its own lock and
    # holds it for its ENTIRE life, batches included, restoring the invariant
    # the orphan sweep depends on. A second drain exits 0 leaving jobs pending,
    # which is the correct non-fatal outcome — the nightly must never fail
    # because the farm is busy.
    # main() takes the lock BEFORE opening the write connection (see
    # acquire_drain_lock); reaching here without it is a programming error.
    if _DRAIN_LOCK_FD is None:
        raise RuntimeError("cmd_run called without the drain lock — call "
                           "acquire_drain_lock() first")
    return _drain(con, meta_path, db_path=db_path, jobs=jobs)


def _drain(con, meta_path: str | Path, *, db_path=None, jobs: int = 1) -> int:
    """The drain proper. Called ONLY by cmd_run, which holds the drain lock —
    the precondition the orphan sweep below relies on."""
    # Reclaim jobs a killed drain left in 'running'. Safe ONLY because the drain
    # lock above proves no other drain is alive; the DuckDB writer no longer
    # proves it, since batches release it.
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

    # --- concurrency for `parallel_safe` kinds, IN PRIORITY ORDER -----------
    # An earlier version drained every parallel_safe job in a pre-pass before
    # the sequential loop. That inverted the queue's own priorities: a weekend
    # sweep at priority 150 would overtake the nightly's own intraday/signals/
    # earnings jobs at 100-110 and delay them by hours. Batches are therefore
    # formed only from jobs that are ALREADY ADJACENT in priority order, so
    # parallelism can reorder nothing — it only widens a run.
    jobs = max(1, min(int(jobs), PARALLEL_JOBS_MAX))
    if jobs > 1:
        print(f"[queue] parallel width {jobs} for parallel_safe kinds "
              f"(store-writing kinds stay strictly sequential)")

    idx = 0
    while idx < len(pending):
        jid, kind, params_json, mem_mb = pending[idx]
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

        # --- batch a RUN of consecutive parallel_safe jobs ---------------
        # Children open their own READ-ONLY connections, so the parent must let
        # go of the write lock for the batch. That is also why this matters
        # operationally: a sweep run in-process pins the single writer for its
        # whole life, and the API/UI answer 503 for as long as it lasts.
        if jobs > 1 and JOB_TYPES.get(kind, {}).get("parallel_safe"):
            run = []
            j = idx
            while j < len(pending) and JOB_TYPES.get(
                    pending[j][1], {}).get("parallel_safe"):
                run.append(pending[j])
                j += 1
            widest = max((r[3] or 0) for r in run) or 1
            per_batch = max(1, min(jobs, ENGINE_RAM_BUDGET_MB // widest))
            batch = [(r[0], r[1]) for r in run[:per_batch]]
            if per_batch < jobs:
                print(f"[queue] parallel width {jobs} -> {per_batch} "
                      f"(RAM budget {ENGINE_RAM_BUDGET_MB} MB / {widest} MB "
                      f"per worker)")
            print(f"[queue] --- parallel batch {[b for b, _ in batch]} "
                  f"({', '.join(sorted({k for _, k in batch}))}, load {load5:.1f}, "
                  f"free RAM {free_gb:.1f} GiB) ---")
            _res, con = _run_parallel_batch(batch, db_path, meta_path, con)
            idx += len(batch)
            continue

        # Everything below runs the job IN-PROCESS on the write connection.
        # Advance the cursor here so the body's `continue`s (refused / skipped
        # / failed job) cannot spin.
        idx += 1

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

    if args.run and not acquire_drain_lock():
        print("[queue] another drain holds the drain lock — leaving all jobs "
              "pending and exiting 0 (the queue is already being worked)")
        return 0

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
