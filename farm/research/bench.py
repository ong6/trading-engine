"""Acceptance benchmark for persistent research panel reuse."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import resource
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from farm.study import bench as panel_bench
from farm.study.costs import CostSelection
from farm.study.data import DerivedInput, MarketData
from farm.study.examples.spy_trend import run_example
from farm.study.synthetic import generate_market

from .cache import ResearchCache
from .canonical import canonical_bytes

SCAN_PANEL_DIGEST = "70bddbc92931bd627c9eb79dd3ed827633806aea8c04bcc0f759ff2700a637b8"
REGISTERED_COLD_SECONDS = 133.41


def _rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _fixed_report(data: MarketData, output: Path) -> bytes:
    with patch("farm.study.examples.spy_trend.time.perf_counter", side_effect=(0.0, 1.0)):
        run_example(
            data,
            output,
            costs=CostSelection("ibkr_tiered_auction_v1", ("baseline_v1",)),
            census_n=3,
        )
    return (output / "report.json").read_bytes()


def synthetic_benchmark(cache_root: str | Path, output_root: str | Path) -> dict:
    """Repeat the scan's seed-71, 1,900-session synthetic example."""
    cache, output = ResearchCache(cache_root), Path(output_root)
    started = time.perf_counter()
    market = generate_market(seed=71, session_count=1_900)
    uncached_seconds = time.perf_counter() - started
    identities = {
        "primary": {
            "benchmark": "scan-synthetic-v1",
            "seed": 71,
            "sessions": 1_900,
            "source": market.data.primary.declaration.snapshot_sha256,
        },
        "secondary": {
            "benchmark": "scan-synthetic-v1",
            "seed": 71,
            "sessions": 1_900,
            "source": market.data.secondary.declaration.snapshot_sha256,
        },
    }
    cold_started = time.perf_counter()
    cold_primary = cache.panel(identities["primary"], lambda source=market.data.primary: source)
    cold_secondary = cache.panel(
        identities["secondary"], lambda source=market.data.secondary: source
    )
    cold_seconds = time.perf_counter() - cold_started
    output.mkdir(parents=True, exist_ok=True)
    reports = {
        "uncached": _fixed_report(
            MarketData(market.data.primary, market.data.secondary), output / "uncached"
        ),
        "cold": _fixed_report(
            MarketData(cold_primary.source, cold_secondary.source), output / "cold"
        ),
    }
    primary_bars = len(market.data.primary.bars)
    secondary_bars = len(market.data.secondary.bars)
    del market, cold_primary, cold_secondary
    gc.collect()
    warm_started = time.perf_counter()
    warm_primary = cache.panel(
        identities["primary"], lambda: (_ for _ in ()).throw(AssertionError("cache miss"))
    )
    warm_secondary = cache.panel(
        identities["secondary"], lambda: (_ for _ in ()).throw(AssertionError("cache miss"))
    )
    warm_seconds = time.perf_counter() - warm_started
    reports["warm"] = _fixed_report(
        MarketData(warm_primary.source, warm_secondary.source), output / "warm"
    )
    report_hashes = {name: hashlib.sha256(value).hexdigest() for name, value in reports.items()}
    if len(set(reports.values())) != 1:
        raise AssertionError("cached and uncached synthetic reports differ")
    return {
        "benchmark": "scan-synthetic-seed71-1900",
        "primary_bars": primary_bars,
        "secondary_bars": secondary_bars,
        "uncached_build_seconds": uncached_seconds,
        "cold_publish_load_seconds": cold_seconds,
        "warm_verified_load_seconds": warm_seconds,
        "warm_speedup_fraction": 1 - warm_seconds / uncached_seconds,
        "warm_bytes_read": warm_primary.object.bytes_read + warm_secondary.object.bytes_read,
        "report_sha256": report_hashes["warm"],
        "reports_byte_identical": len(set(report_hashes.values())) == 1,
        "peak_rss_bytes": _rss_bytes(),
    }


def _write_candidates(path: Path, data: MarketData) -> dict:
    selected = next(item for item in data.derived_inputs if item.name == "candidates")
    rows = [{
        "session": row["session"].isoformat(),
        "available_at": row["available_at"].isoformat(),
        "event": list(row["event"]),
        "portfolio": list(row["portfolio"]),
    } for row in selected.records]
    (path / "candidates.json").write_bytes(canonical_bytes(rows, newline=True))
    return {"format": "study-benchmark-candidates-v1", "rows": len(rows)}


def _load_candidates(obj) -> DerivedInput:
    rows = [{
        "session": date.fromisoformat(row["session"]),
        "available_at": datetime.fromisoformat(row["available_at"]),
        "event": tuple(row["event"]),
        "portfolio": tuple(row["portfolio"]),
    } for row in obj.read_json("candidates.json")]
    return DerivedInput(
        "candidates", rows, declaration={"rule": "deterministic pre-session candidates"}
    )


def _benchmark_digest(data: MarketData, universe, folds: int) -> dict:
    panel_bench._CONTEXT = panel_bench._Context(
        data, universe, panel_bench._windows(data.primary.sessions, folds)
    )
    try:
        evaluated = [panel_bench._evaluate(index) for index in range(folds)]
    finally:
        panel_bench._CONTEXT = None
    payloads, _ = zip(*evaluated, strict=True)
    encoded = (json.dumps(
        payloads, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n").encode()
    return {
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "event_trades": sum(len(row["event"]["trades"]) for row in payloads),
        "portfolio_days": sum(len(row["portfolio"]["days"]) for row in payloads),
    }


def panel_benchmark(
    cache_root: str | Path,
    *,
    ticker_count: int = 300,
    session_count: int = 500,
    folds: int = 4,
) -> dict:
    """Build once, persist, verify-load, and replay the scan's shared-panel workload."""
    cache = ResearchCache(cache_root)
    started = time.perf_counter()
    data, universe = panel_bench.build_market(
        ticker_count=ticker_count, session_count=session_count
    )
    uncached_seconds = time.perf_counter() - started
    panel_identity = {
        "benchmark": "study-panel-v1",
        "ticker_count": ticker_count,
        "session_count": session_count,
        "source": data.primary.declaration.snapshot_sha256,
    }
    cold_started = time.perf_counter()
    cold = cache.panel(panel_identity, lambda source=data.primary: source)
    cold_seconds = time.perf_counter() - cold_started
    universe_identity = {**panel_identity, "kind": "point-in-time-universe"}
    cached_universe = cache.universe(
        universe_identity, cold.source, lambda value=universe: value,
    )
    candidate_identity = {**panel_identity, "kind": "candidate-features"}
    candidates = cache.build(
        "feature", candidate_identity,
        lambda path, market_data=data: _write_candidates(path, market_data),
    )
    baseline = _benchmark_digest(data, universe, folds)
    bar_count = len(data.primary.bars)
    del data, universe
    gc.collect()
    cold_result = _benchmark_digest(
        MarketData(cold.source, derived_inputs=(_load_candidates(candidates),)),
        cached_universe.universe,
        folds,
    )
    del cold, cached_universe
    gc.collect()
    warm_started = time.perf_counter()
    warm = cache.panel(
        panel_identity, lambda: (_ for _ in ()).throw(AssertionError("cache miss"))
    )
    warm_seconds = time.perf_counter() - warm_started
    warm_universe = cache.universe(
        universe_identity, warm.source,
        lambda: (_ for _ in ()).throw(AssertionError("cache miss")),
    )
    warm_candidates = cache.get("feature", candidate_identity)
    assert warm_candidates is not None
    warm_result = _benchmark_digest(
        MarketData(warm.source, derived_inputs=(_load_candidates(warm_candidates),)),
        warm_universe.universe,
        folds,
    )
    if len({baseline["result_sha256"], cold_result["result_sha256"],
            warm_result["result_sha256"]}) != 1:
        raise AssertionError("cached and uncached panel results differ")
    result = {
        "benchmark": f"shared-panel-{ticker_count}x{session_count}",
        "ticker_count": ticker_count,
        "session_count": session_count,
        "bar_count": bar_count,
        "folds": folds,
        "uncached_build_seconds": uncached_seconds,
        "cold_publish_load_seconds": cold_seconds,
        "warm_verified_load_seconds": warm_seconds,
        "warm_speedup_fraction": 1 - warm_seconds / uncached_seconds,
        "warm_speedup_vs_registered_133_41_fraction": 1 - warm_seconds / REGISTERED_COLD_SECONDS,
        "warm_bytes_read": warm.object.bytes_read,
        "result_sha256": warm_result["result_sha256"],
        "results_byte_identical": True,
        "event_trades": warm_result["event_trades"],
        "portfolio_days": warm_result["portfolio_days"],
        "peak_rss_bytes": _rss_bytes(),
    }
    if ticker_count == 300 and session_count == 500 and folds == 4 \
            and result["result_sha256"] != SCAN_PANEL_DIGEST:
        raise AssertionError("scan benchmark digest differs")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--mode", choices=("synthetic", "panel"), required=True)
    parser.add_argument("--tickers", type=int, default=300)
    parser.add_argument("--sessions", type=int, default=500)
    parser.add_argument("--folds", type=int, default=4)
    args = parser.parse_args(argv)
    if args.mode == "synthetic":
        if args.output_root is None:
            parser.error("--output-root is required for synthetic mode")
        result = synthetic_benchmark(args.cache_root, args.output_root)
    else:
        result = panel_benchmark(
            args.cache_root,
            ticker_count=args.tickers,
            session_count=args.sessions,
            folds=args.folds,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
