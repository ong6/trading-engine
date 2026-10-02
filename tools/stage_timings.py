#!/usr/bin/env python3
"""Summarize driver stage runtimes from logs/stage-timings.jsonl."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

from engine.lib.settings import LOGS_DIR


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
