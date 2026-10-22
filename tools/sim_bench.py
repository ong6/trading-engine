"""Research-loop benchmark: timed workloads with output digests for identity.

Each workload prints one JSON line with its wall seconds and a SHA-256 of its
output with run-dependent fields (timings, code identity, timestamps) removed,
so the same command on two checkouts proves the outputs are identical:

    python -m tools.sim_bench stats
    python -m tools.sim_bench panel --db COPY.duckdb --tickers 3000 [--legacy]
    python -m tools.sim_bench replay --db COPY.duckdb --book ew_benchmark --window 2025-01-02:2025-12-31
    python -m tools.sim_bench walkforward --db COPY.duckdb --book dual_momentum --folds 3
    python -m tools.sim_bench study --tickers 600 --sessions 3800

`--db` must be a copy of the store (never the live file); it is opened
read-only. `replay` and `walkforward` write only under `--scratch`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np

VOLATILE = frozenset({
    "runtime_s", "screen_s", "step_s", "scratch_s", "generated_utc", "git_sha",
    "git_dirty", "source_sha256", "source_file_count", "build_seconds", "wall_seconds",
    "parent_peak_rss_bytes", "worker_peak_rss_bytes", "rss_sum_bytes",
})


def _scrub(value):
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def result_digest(value) -> str:
    """SHA-256 of canonical JSON with run-dependent fields removed."""
    payload = json.dumps(_scrub(value), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


LEDGER_TABLES = ("sim_orders", "sim_fills", "sim_fill_costs", "sim_execution_attempts",
                 "sim_equity", "sim_dividends", "sim_positions", "portfolios")


def ledger_digest(scratch_dir: Path) -> str:
    """SHA-256 of every row of a kept replay scratch store's book tables."""
    from engine.lib import db

    con = db.connect(scratch_dir / "replay.duckdb", read_only=True, wait_s=0)
    try:
        digest = hashlib.sha256()
        for table in LEDGER_TABLES:
            rows = con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
            digest.update(f"{table}:{len(rows)}:{rows!r}".encode())
        return digest.hexdigest()
    finally:
        con.close()


def _timed(fn):
    started = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - started


def bench_stats(args) -> dict:
    from farm.stats import inference
    from farm.study.stats import calendar_statistics
    from farm.walkforward import monthly

    rng = np.random.default_rng(args.seed)
    days = [date(2011, 1, 3) + timedelta(days=index) for index in range(args.sessions)]
    daily = rng.standard_t(4, args.sessions) * 0.01 + 0.0002
    monthly_excess = rng.normal(0.002, 0.03, 120)

    def run():
        return {
            "calendar": calendar_statistics(days, daily, census_n=364),
            "monthly": monthly.evaluate_excess(monthly_excess, n_trials=364),
            "dsr": inference.deflated_sharpe(daily, 364),
            "fold_ci": inference.bootstrap_ci(monthly_excess[:10]),
        }

    output, seconds = _timed(run)
    return {"seconds": seconds, "digest": result_digest(output)}


def bench_panel(args) -> dict:
    from engine.lib import db
    from farm.study.data import DataDeclaration, PriceSource
    from farm.study_columnar import panel_digest, price_source_from_duckdb

    con = db.connect(args.db, read_only=True, wait_s=0)
    try:
        names = [row[0] for row in con.execute(
            "SELECT ticker FROM prices WHERE date BETWEEN ? AND ? GROUP BY ticker "
            "ORDER BY COUNT(*) DESC, ticker LIMIT ?",
            [args.start, args.end, args.tickers]).fetchall()]
    finally:
        con.close()
    declaration = DataDeclaration("sim-bench", "0" * 64, True, "unknown")
    build = PriceSource.from_duckdb if args.legacy else price_source_from_duckdb
    source, seconds = _timed(lambda: build(
        args.db, declaration, start=args.start, end=args.end, tickers=names))
    return {"seconds": seconds, "digest": panel_digest(source), "builder": build.__qualname__,
            "tickers": len(source.tickers), "sessions": len(source.sessions),
            "bars": source.panel.bar_count}


def _store(args):
    from engine.lib import db

    return db.connect(Path(args.db), read_only=True, wait_s=0)


def bench_replay(args) -> dict:
    from farm.backtest import replay

    override = None
    if ":" in args.window:  # an explicit START:END span instead of a named window
        override = tuple(date.fromisoformat(part) for part in args.window.split(":"))
    live = _store(args)
    try:
        output, seconds = _timed(lambda: replay.run_replay(
            live, args.book, args.window, scratch_root=args.scratch, write_result=False,
            verbose=False, threads=args.threads, mem_mb=args.mem_mb, override=override,
            keep_scratch=True))
    finally:
        live.close()
    return {"seconds": seconds, "digest": result_digest(output),
            "tables_digest": ledger_digest(args.scratch / f"{args.book}__{args.window}"),
            "n_fills": output.get("n_fills"), "step_s": output.get("step_s")}


def bench_walkforward(args) -> dict:
    from farm.walkforward import runner

    live = _store(args)
    try:
        output, seconds = _timed(lambda: runner.run_book(
            live, args.book, n_folds=args.folds, scratch_root=args.scratch,
            train_months=args.train_months, validate_months=args.validate_months,
            step_months=args.validate_months,
            results_dir=args.scratch / "results", write_result=False, verbose=False,
            threads=args.threads, mem_mb=args.mem_mb, keep_scratch=True))
    finally:
        live.close()
    kept = sorted(args.scratch.glob(f"wf__{args.book}__p*"))
    return {"seconds": seconds, "digest": result_digest(output),
            "last_fold_tables_digest": ledger_digest(kept[-1]) if kept else None,
            "folds": len(output.get("folds", []))}


def bench_study(args) -> dict:
    from farm.study import bench

    output = bench.run_benchmark(ticker_count=args.tickers, session_count=args.sessions,
                                 workers=1, folds=args.folds)
    return {"seconds": output["build_seconds"] + output["wall_seconds"],
            "build_seconds": output["build_seconds"], "simulate_seconds": output["wall_seconds"],
            "digest": output["result_sha256"]}


WORKLOADS = {"stats": bench_stats, "panel": bench_panel, "replay": bench_replay,
             "walkforward": bench_walkforward, "study": bench_study}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workload", choices=sorted(WORKLOADS))
    parser.add_argument("--db", type=Path, help="store COPY, opened read-only")
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--book", default="ew_benchmark")
    parser.add_argument("--window", default="3y")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--train-months", type=int, default=24)
    parser.add_argument("--validate-months", type=int, default=12)
    parser.add_argument("--tickers", type=int, default=3000)
    parser.add_argument("--sessions", type=int, default=3800)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2012, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 25))
    parser.add_argument("--legacy", action="store_true", help="panel: per-bar builder")
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--mem-mb", type=int, default=4000)
    args = parser.parse_args(argv)
    if args.workload in {"panel", "replay", "walkforward"} and args.db is None:
        parser.error(f"{args.workload} needs --db (a store copy)")
    with tempfile.TemporaryDirectory(prefix="sim-bench-") as scratch:
        args.scratch = args.scratch or Path(scratch)
        result = WORKLOADS[args.workload](args)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    print(json.dumps({"workload": args.workload, "peak_rss_mb": peak, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
