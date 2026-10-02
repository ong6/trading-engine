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
from ..costs import CostSelection
from ..data import DataDeclaration, MarketData, PriceSource
from ..protocol import run_identity
from ..report import build_report, write_report
from ..simulate import simulate_portfolio
from ..spec import FillPoint, PortfolioStrategy
from ..stats import calendar_statistics
from ..universe import ListingInterval, Universe

CAPITAL = 100_000.0


def trend_weights(view, session: date) -> dict[str, float]:
    history = view.history("SPY", ("close",), limit=200)
    closes = [row["close"] for row in history if row["close"] is not None]
    return {"SPY": 1.0 if len(closes) == 200 and closes[-1] > float(np.mean(closes)) else 0.0}


SPY_200_DAY_TREND = PortfolioStrategy(
    "spy_200_day_trend", "at_close", trend_weights, "daily", FillPoint.next_open(),
    {"window_sessions": 200, "invested_weight": 1.0}, CAPITAL,
    close_as_indication=True)


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
    universe = Universe(data.primary, (ListingInterval("SPY", sessions[0]),))
    ledger = simulate_portfolio(
        SPY_200_DAY_TREND, data, universe, sessions, costs, Benchmark("ticker", "SPY"))
    daily_dates = list(ledger.sessions)
    net = ledger.returns
    benchmark_array = np.asarray([row.benchmark_return for row in ledger.days])
    exposure = [row.gross_exposure for row in ledger.days]
    total_costs = {profile: sum(row.costs_by_profile[profile] for row in ledger.days)
                   for profile in (costs.primary, *costs.sensitivities)}
    trade_count = sum(row.turnover > 0 for row in ledger.days)
    costs.require_harsher(total_costs)
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
        folds=_year_rows(daily_dates, net), hard_max_date=sessions[-1], ledger=ledger,
        close_as_indication=True, runtime_seconds=time.perf_counter() - started,
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
