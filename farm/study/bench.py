"""Deterministic realistic-scale benchmark for the shared study simulator."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import multiprocessing
import pstats
import resource
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time

import numpy as np

from .benchmark import Benchmark
from .costs import CostSelection
from .data import Bar, DataDeclaration, DerivedInput, Dividend, MarketData, PriceSource
from .simulate import simulate_events, simulate_portfolio
from .spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from .universe import ListingInterval, Universe

DEFAULT_TICKERS = 3_000
DEFAULT_SESSIONS = 3_800
DEFAULT_FOLDS = 16
BENCH_COSTS = CostSelection("ibkr_tiered_auction_v1", ("ibkr_fixed_v1",))
_CONTEXT: "_Context | None" = None


def _sessions(count: int) -> tuple[date, ...]:
    result, current = [], date(2008, 1, 2)
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _declaration(tickers: int, sessions: int) -> DataDeclaration:
    payload = json.dumps(
        {"generator": 1, "tickers": tickers, "sessions": sessions},
        sort_keys=True,
        separators=(",", ":"),
    )
    return DataDeclaration(
        "study-performance-benchmark",
        hashlib.sha256(payload.encode()).hexdigest(),
        True,
        "point_in_time",
    )


def _bars(names: tuple[str, ...], days: tuple[date, ...], ends: np.ndarray):
    prices = np.full(len(names), 40.0, dtype=np.float64)
    for day_index, session in enumerate(days):
        for ticker_index, ticker in enumerate(names):
            if day_index > ends[ticker_index] or (ticker_index * 17 + day_index) % 997 == 0:
                continue
            gap = ((ticker_index * 31 + day_index * 17) % 401 - 200) * 0.00001
            intraday = ((ticker_index * 13 + day_index * 29) % 301 - 150) * 0.000012
            if (ticker_index * 7 + day_index) % 61 == 0:
                gap -= 0.018
                intraday += 0.004
            open_px = max(0.01, prices[ticker_index] * (1 + gap))
            close = max(0.01, open_px * (1 + intraday))
            volume = (2_000_000 + (ticker_index % 100) * 900_000) / close
            yield Bar(
                ticker,
                session,
                open_px,
                max(open_px, close) * 1.001,
                min(open_px, close) * 0.999,
                close,
                volume,
                volume * 0.08,
            )
            prices[ticker_index] = close


def build_market(
    *, ticker_count: int = DEFAULT_TICKERS, session_count: int = DEFAULT_SESSIONS
) -> tuple[MarketData, Universe]:
    """Build a reproducible panel with gaps, delistings, dividends, and candidate sets."""
    if ticker_count < 32 or session_count < 40:
        raise ValueError("benchmark needs at least 32 tickers and 40 sessions")
    names, days = tuple(f"T{index:04d}" for index in range(ticker_count)), _sessions(session_count)
    ends = np.full(ticker_count, session_count - 1, dtype=np.int64)
    if session_count > 80:
        for index in range(0, ticker_count, 97):
            ends[index] = 40 + (index * 37) % (session_count - 40)
    ex_indexes = tuple(
        index
        for index in (session_count // 4, session_count // 2, 3 * session_count // 4)
        if index > 5
    )
    dividends = (
        Dividend(
            ticker,
            days[index],
            0.05 + (ticker_index % 5) * 0.01,
            datetime.combine(days[index - 5], clock_time(16), timezone.utc),
        )
        for ticker_index, ticker in enumerate(names)
        for index in ex_indexes
        if index <= ends[ticker_index]
    )
    source = PriceSource(
        _declaration(ticker_count, session_count), _bars(names, days, ends), dividends
    )
    listings = tuple(
        ListingInterval(ticker, days[0], None if end == session_count - 1 else days[int(end)])
        for ticker, end in zip(names, ends, strict=True)
    )
    candidates = []
    for index, session in enumerate(days):
        event = tuple(names[(index * 17 + offset * 997) % ticker_count] for offset in range(3))
        portfolio = tuple(names[(index * 11 + offset * 131) % ticker_count] for offset in range(8))
        candidates.append(
            {
                "session": session,
                "available_at": datetime.combine(session, clock_time(8), timezone.utc),
                "event": event,
                "portfolio": portfolio,
            }
        )
    inputs = (
        DerivedInput(
            "candidates", candidates, declaration={"rule": "deterministic pre-session candidates"}
        ),
    )
    return MarketData(source, derived_inputs=inputs), Universe(source, listings)


def _condition(view, position) -> bool:
    try:
        close = view.value(position.ticker, "close")
    except KeyError:
        return False
    return bool(close is not None and close >= position.entry_price * 1.002)


def _orders(view, session: date) -> list[Order]:
    exit_rule = ExitRule.first_condition(_condition, 5)
    return [
        Order(ticker, "long", FillPoint.open_auction(), exit_rule, 10_000)
        for ticker in view.derived("candidates", "event")
    ]


def _weights(view, session: date) -> dict[str, float]:
    scores = []
    for ticker in view.derived("candidates", "portfolio"):
        rows = view.history(ticker, ("close",), limit=20)
        if len(rows) == 20 and rows[0]["close"] and rows[-1]["close"]:
            scores.append((rows[-1]["close"] / rows[0]["close"] - 1, ticker))
    scores.sort(reverse=True)
    return {ticker: 1 / 3 for _, ticker in scores[:3]}


@dataclass(frozen=True)
class _Context:
    data: MarketData
    universe: Universe
    windows: tuple[tuple[date, ...], ...]


def _evaluate(index: int) -> tuple[dict, int]:
    if _CONTEXT is None:
        raise RuntimeError("benchmark worker has no inherited context")
    days = _CONTEXT.windows[index]
    event = simulate_events(
        EventStrategy(
            "benchmark-event",
            "pre_open",
            _orders,
            32,
            10_000,
            max_new_per_session=3,
            close_as_indication=True,
        ),
        _CONTEXT.data,
        _CONTEXT.universe,
        days,
        BENCH_COSTS,
        Benchmark("cash"),
    )
    portfolio = simulate_portfolio(
        PortfolioStrategy(
            "benchmark-weekly", "at_close", _weights, "weekly", FillPoint.next_open()
        ),
        _CONTEXT.data,
        _CONTEXT.universe,
        days,
        BENCH_COSTS,
        Benchmark("cash"),
    )
    payload = {"fold": index, "event": event.as_dict(), "portfolio": portfolio.as_dict()}
    return payload, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _windows(days: tuple[date, ...], folds: int) -> tuple[tuple[date, ...], ...]:
    return tuple(
        tuple(part.tolist()) for part in np.array_split(np.asarray(days, dtype=object), folds)
    )


def run_benchmark(
    *,
    ticker_count: int = DEFAULT_TICKERS,
    session_count: int = DEFAULT_SESSIONS,
    workers: int = 1,
    folds: int = DEFAULT_FOLDS,
    profile: str | None = None,
) -> dict:
    """Run the same folded workload serially or through fork-shared workers."""
    global _CONTEXT
    started = time.perf_counter()
    data, universe = build_market(ticker_count=ticker_count, session_count=session_count)
    built = time.perf_counter()
    _CONTEXT = _Context(data, universe, _windows(data.primary.sessions, folds))
    profiler = cProfile.Profile() if profile else None
    if profiler:
        profiler.enable()
    if workers == 1:
        evaluated = [_evaluate(index) for index in range(folds)]
    else:
        if workers != 16:
            raise ValueError("parallel benchmark is registered at 16 workers")
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("fork")
        ) as pool:
            evaluated = list(pool.map(_evaluate, range(folds)))
    if profiler:
        profiler.disable()
        profiler.dump_stats(profile)
    finished = time.perf_counter()
    payloads, worker_rss = zip(*evaluated, strict=True)
    result_bytes = (
        json.dumps(payloads, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    result = {
        "ticker_count": ticker_count,
        "session_count": session_count,
        "bar_count": len(data.primary.bars),
        "folds": folds,
        "workers": workers,
        "build_seconds": built - started,
        "wall_seconds": finished - built,
        "event_trades": sum(len(row["event"]["trades"]) for row in payloads),
        "portfolio_days": sum(len(row["portfolio"]["days"]) for row in payloads),
        "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "worker_peak_rss_bytes": list(worker_rss),
        "rss_sum_bytes": (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 + sum(worker_rss)
        ),
    }
    _CONTEXT = None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", type=int, default=DEFAULT_TICKERS)
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--workers", type=int, choices=(1, 16), default=1)
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--profile")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    result = run_benchmark(
        ticker_count=args.tickers,
        session_count=args.sessions,
        workers=args.workers,
        folds=args.folds,
        profile=args.profile,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    if args.profile:
        stream = io.StringIO()
        pstats.Stats(args.profile, stream=stream).sort_stats("cumulative").print_stats(args.top)
        print(stream.getvalue())


if __name__ == "__main__":
    main()
