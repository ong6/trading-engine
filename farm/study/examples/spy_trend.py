"""Textbook SPY 200-session trend rule against gross SPY buy-and-hold."""
from __future__ import annotations

import argparse
import hashlib
import math
import time
from datetime import date
from pathlib import Path

import numpy as np

from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from ..benchmark import Benchmark, compare
from ..costs import CostSelection, calculate
from ..data import DataDeclaration, MarketData, PriceSource
from ..protocol import run_identity
from ..report import CrossCheckTrade, build_report, write_report
from ..spec import FillPoint, PortfolioStrategy
from ..stats import calendar_statistics

CAPITAL = 100_000.0


def trend_weights(view, session: date) -> dict[str, float]:
    history = view.history("SPY", ("close",), limit=200)
    closes = [row["close"] for row in history if row["close"] is not None]
    return {"SPY": 1.0 if len(closes) == 200 and closes[-1] > float(np.mean(closes)) else 0.0}


SPY_200_DAY_TREND = PortfolioStrategy(
    "spy_200_day_trend", "at_close", trend_weights, "daily", FillPoint.next_open(),
    {"window_sessions": 200, "invested_weight": 1.0})


def _year_rows(dates: list[date], returns: np.ndarray) -> list[dict]:
    rows = []
    for year in sorted({day.year for day in dates}):
        values = returns[[day.year == year for day in dates]]
        if not len(values):
            continue
        mean = float(values.mean())
        se = float(values.std(ddof=1) / math.sqrt(len(values))) if len(values) > 1 else None
        rows.append({"fold": year, "n": len(values), "mean": mean,
                     "one_sided_t": mean / se if se and se > 0 else None,
                     "positive": bool(mean > 0)})
    return rows


def run_example(data: MarketData, output_dir: str | Path, *, costs: CostSelection,
                census_n: int = 1) -> dict:
    started = time.perf_counter()
    sessions = [day for day in data.primary.sessions if data.primary.get("SPY", day) is not None]
    if len(sessions) < 202:
        raise ValueError("SPY trend example needs at least 202 sessions")
    daily_dates, net_returns, benchmark, exposure = [], [], [], []
    total_costs = {name: 0.0 for name in (costs.primary, *costs.sensitivities)}
    cross_checks, previous_target, trade_count = [], 0.0, 0
    for index in range(199, len(sessions) - 2):
        decision, entry_day, exit_day = sessions[index:index + 3]
        view = data.view(decision, SPY_200_DAY_TREND.decision_time, sessions[-1])
        target = SPY_200_DAY_TREND.target_weights(view, decision)["SPY"]
        entry = data.primary.get("SPY", entry_day)
        exit_ = data.primary.get("SPY", exit_day)
        if entry is None or exit_ is None or not entry.open or not exit_.open:
            raise ValueError("SPY example never invents a missing opening fill")
        raw = target * (exit_.open / entry.open - 1)
        benchmark.append(exit_.open / entry.open - 1)
        turnover = abs(target - previous_target)
        primary_cost = 0.0
        if turnover:
            trade_count += 1
            side = "buy" if target > previous_target else "sell"
            mdv60 = float(np.median([
                bar.close * bar.volume for bar in data.primary.bars
                if bar.ticker == "SPY" and bar.session < entry_day and bar.close and bar.volume][-60:]))
            for profile in total_costs:
                amount = calculate(
                    profile, side=side, notional=CAPITAL * turnover,
                    fill_price=entry.open, mdv60=mdv60).total
                total_costs[profile] += amount
                if profile == costs.primary:
                    primary_cost = amount
        net_returns.append(raw - primary_cost / CAPITAL)
        daily_dates.append(exit_day)
        exposure.append(target * CAPITAL)
        if target:
            cross_checks.append(CrossCheckTrade(
                "SPY", "long", entry_day, "open", exit_day, "open"))
        previous_target = target
    costs.require_harsher(total_costs)
    net = np.asarray(net_returns)
    benchmark_array = np.asarray(benchmark)
    comparison = compare(net, benchmark_array, Benchmark("ticker", "SPY"))
    stats = calendar_statistics(
        daily_dates, net, census_n=census_n, gross_exposure=exposure,
        traded_notional=trade_count * CAPITAL, capital=CAPITAL, bootstrap_draws=200)
    identity = run_identity(
        SPY_200_DAY_TREND, costs, data.primary.declaration.snapshot_sha256,
        secondary_data_snapshot_sha256=(data.secondary.declaration.snapshot_sha256
                                        if data.secondary else None))
    report = build_report(
        identity=identity, data=data, costs=costs, benchmark=Benchmark("ticker", "SPY"),
        variants=[{"variant": SPY_200_DAY_TREND.name,
                   "net_return": comparison.strategy_net_return,
                   "benchmark_return": comparison.benchmark_return,
                   "excess_return": comparison.excess_return,
                   "absolute_net_positive": comparison.absolute_net_positive,
                   "trades": trade_count, "one_sided_t": stats["one_sided_t"]}],
        folds=_year_rows(daily_dates, net), cross_check_trades=cross_checks,
        hard_max_date=sessions[-1], runtime_seconds=time.perf_counter() - started,
        worker_count=1, job_count=len(daily_dates), serial_parallel_identical=None)
    write_report(output_dir, report)
    return report


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_cli_paths(database: Path, output_dir: Path) -> None:
    if database.resolve() == DEFAULT_DB.resolve():
        raise ValueError("the live default store is forbidden; use tools.backup_database create")
    tracked_data = (REPO_ROOT / "data").resolve()
    if output_dir.resolve().is_relative_to(tracked_data):
        raise ValueError("example output must be outside tracked data/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--primary-cost", required=True)
    parser.add_argument("--sensitivity-cost", action="append", required=True)
    parser.add_argument("--census-n", type=int, required=True)
    args = parser.parse_args(argv)
    _validate_cli_paths(args.database, args.output_dir)
    if not args.database.is_file():
        parser.error("--database must name a store copy")
    declaration = DataDeclaration(
        "explicit-read-only-store-copy", _sha256_file(args.database), True, "unknown")
    source = PriceSource.from_duckdb(args.database, declaration, tickers=("SPY",))
    run_example(MarketData(source), args.output_dir,
                costs=CostSelection(args.primary_cost, tuple(args.sensitivity_cost)),
                census_n=args.census_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
