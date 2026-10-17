#!/usr/bin/env python3
"""Summarize driver stage runtimes from logs/stage-timings.jsonl."""

from __future__ import annotations

import argparse
import atexit
import fcntl
import json
import math
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from statistics import median

from engine.lib.settings import LOGS_DIR

# Components append small counter deltas to the current stage's temporary file.
# The driver folds these into its existing completed-stage record. Uninstrumented
# stages have null counters; a measured no-op has zero counters.
FLOW_FIELDS = ("input_rows", "output_rows", "input_bytes", "output_bytes",
               "writer_hold_seconds", "lock_wait_seconds")


_FLOW_PENDING = {}
_FLOW_PATH = None
_FLOW_PID = os.getpid()
_FLOW_EVENTS = 0


def _flush_flow() -> None:
    global _FLOW_PENDING, _FLOW_EVENTS
    if not _FLOW_PENDING or _FLOW_PID != os.getpid():
        return
    try:
        with open(_FLOW_PATH, "a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(_FLOW_PENDING, separators=(",", ":")) + "\n")
    except OSError:
        pass  # Observability never changes a producer's exit semantics.
    _FLOW_PENDING = {}
    _FLOW_EVENTS = 0


atexit.register(_flush_flow)


def record_flow(**values) -> None:
    """Accumulate deltas; flush every 32 events and at normal process exit.

    Exceptions and nonzero Python exits flush through atexit. Abruptly killed
    processes may lose the last 31 events; missing measurements remain unknown.
    Buffering avoids an open/flock/JSON write for each writer-lease fragment.
    """
    global _FLOW_PATH, _FLOW_PID, _FLOW_PENDING, _FLOW_EVENTS
    path = os.environ.get("TRADING_ENGINE_STAGE_METRICS")
    if _FLOW_PID != os.getpid():
        _FLOW_PENDING = {}
        _FLOW_EVENTS = 0
        _FLOW_PID = os.getpid()
    if path != _FLOW_PATH:
        _flush_flow()
        _FLOW_PATH = path
    if not path:
        return
    clean = {k: v for k, v in values.items() if k in FLOW_FIELDS and v is not None}
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v < 0 for v in clean.values()):
        raise ValueError("stage counters must be finite and nonnegative")
    for key, value in clean.items():
        _FLOW_PENDING[key] = _FLOW_PENDING.get(key, 0) + value
    _FLOW_EVENTS += 1
    if _FLOW_EVENTS >= 32:
        _flush_flow()


def flow_totals(path: Path) -> dict:
    if str(path) == _FLOW_PATH:
        _flush_flow()
    totals = dict.fromkeys(FLOW_FIELDS)
    try:
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                for key in FLOW_FIELDS:
                    v = row.get(key)
                    if (not isinstance(v, bool) and isinstance(v, (int, float))
                            and math.isfinite(v) and v >= 0):
                        totals[key] = (totals[key] or 0) + v
            except (ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return totals


@contextmanager
def writer_connection(path):
    """Measure a writer lease and retry wait using the existing DB opener.

    The db logger records each five-second retry before sleeping. Count these
    separately from connection setup; hold covers open success through close.
    """
    import logging

    from engine.lib import db
    waits = []
    class RetryCounter(logging.Handler):
        def emit(self, record):
            if "[db] store locked (attempt" in record.getMessage():
                waits.append(db._LOCK_RETRY_S)
    handler = RetryCounter()
    db.log.addHandler(handler)
    try:
        con = db.connect(path)
    finally:
        db.log.removeHandler(handler)
        record_flow(lock_wait_seconds=sum(waits))
    opened = time.perf_counter()
    try:
        yield con
    finally:
        con.close()
        record_flow(writer_hold_seconds=time.perf_counter() - opened)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def load_timings(path: Path) -> list[dict]:
    """Load valid completed-stage records; malformed observability rows are ignored."""
    records = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            item = json.loads(line)
            if (
                isinstance(item, dict)
                and all(isinstance(item.get(key), str) and item[key]
                        for key in ("driver", "run_id", "stage", "ended"))
                and isinstance(item.get("seconds"), (int, float))
                and not isinstance(item.get("seconds"), bool)
                and float(item["seconds"]) >= 0
                and isinstance(item.get("exit"), int)
                and not isinstance(item.get("exit"), bool)
            ):
                records.append(item)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return records


def summarize(records: list[dict], *, runs: int, driver: str | None = None) -> list[dict]:
    if runs <= 0:
        raise ValueError("runs must be positive")
    by_driver: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if driver is None or record["driver"] == driver:
            by_driver[record["driver"]].append(record)
    result = []
    for driver_name, driver_records in sorted(by_driver.items()):
        run_ended: dict[str, str] = {}
        for record in driver_records:
            run_ended[record["run_id"]] = max(
                record["ended"], run_ended.get(record["run_id"], "")
            )
        selected = {
            run_id for run_id, _ended in sorted(
                run_ended.items(), key=lambda item: item[1], reverse=True
            )[:runs]
        }
        by_stage: dict[str, list[dict]] = defaultdict(list)
        for record in driver_records:
            if record["run_id"] in selected:
                by_stage[record["stage"]].append(record)
        for stage, stage_records in sorted(by_stage.items()):
            seconds = [float(item["seconds"]) for item in stage_records]
            result.append({
                "driver": driver_name,
                "stage": stage,
                "runs": len(seconds),
                "median_seconds": median(seconds),
                "p90_seconds": _percentile(seconds, 0.9),
                "failures": sum(item["exit"] != 0 for item in stage_records),
            })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20, help="recent runs per driver")
    parser.add_argument("--driver", help="limit the report to one driver")
    parser.add_argument("--path", type=Path, default=LOGS_DIR / "stage-timings.jsonl")
    args = parser.parse_args(argv)
    try:
        rows = summarize(load_timings(args.path), runs=args.runs, driver=args.driver)
    except ValueError as exc:
        parser.error(str(exc))
    if not rows:
        print("no stage timings")
        return 0
    print(f"{'driver':<28} {'stage':<24} {'runs':>4} {'median_s':>10} {'p90_s':>10} {'fail':>4}")
    for row in rows:
        print(
            f"{row['driver']:<28} {row['stage']:<24} {row['runs']:>4} "
            f"{row['median_seconds']:>10.3f} {row['p90_seconds']:>10.3f} "
            f"{row['failures']:>4}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
