import json
import os
from datetime import date

import pytest

from farm.study.benchmark import Benchmark
from farm.study.costs import CostSelection
from farm.study.data import Bar, MarketData, PriceSource
from farm.study.report import CrossCheckTrade, build_report, write_report
from farm.study.run import BLAS_ENV_VARS, run_jobs


def _evaluate(job):
    return {"score": (job.seed % 10_000) / 10_000, "parameter": job.parameters["x"]}


def test_serial_and_process_pool_results_are_byte_identical():
    variants = {"zeta": {"x": 2}, "alpha": {"x": 1}}
    serial = run_jobs(variants, [2, 1], _evaluate, master_seed=17, max_workers=1)
    parallel = run_jobs(variants, [2, 1], _evaluate, master_seed=17, max_workers=2)
    assert serial.json_bytes == parallel.json_bytes
    assert [(row["variant"], row["fold"]) for row in serial.results] == [
        ("alpha", 1), ("alpha", 2), ("zeta", 1), ("zeta", 2)]
    assert all(os.environ[name] == "1" for name in BLAS_ENV_VARS)
    assert serial.worker_count == 1 and parallel.worker_count == 2


def _bar(ticker, day, open_px, close):
    return Bar(ticker, day, open_px, max(open_px, close), min(open_px, close), close,
               10_000_000)


def test_report_has_fixed_sections_caveats_and_biased_secondary_cross_check(tmp_path):
    d0, d1, d2 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
    primary = PriceSource.declared(source="primary", survivor_status="current_listings_only",
        bars=[_bar("AAA", d0, 100, 100), _bar("AAA", d1, 100, 102),
              _bar("AAA", d2, 100, 104)])
    secondary = PriceSource.declared(source="independent", survivor_status="unknown",
        bars=[_bar("AAA", d0, 101, 100), _bar("AAA", d1, 101, 102)])
    data = MarketData(primary, secondary)
    trades = [CrossCheckTrade("AAA", "long", d0, "open", d1, "close"),
              CrossCheckTrade("AAA", "long", d1, "open", d2, "close")]
    report = build_report(
        identity="a" * 64, data=data,
        costs=CostSelection("baseline_v1", ("ibkr_fixed_v1",)),
        benchmark=Benchmark("ticker", "AAA"),
        variants=[{"variant": "trend", "net_return": 0.02, "benchmark_return": 0.01,
                   "excess_return": 0.01, "absolute_net_positive": True,
                   "trades": 2, "one_sided_t": 2.1}],
        folds=[{"fold": 1, "mean": 0.01, "one_sided_t": 2.0}],
        cross_check_trades=trades, hard_max_date=d2, open_as_indication=True,
        runtime_seconds=0.5, worker_count=2, job_count=4,
        serial_parallel_identical=True, cpu_count=8)
    check = report["independent_price_cross_check"]
    assert check["trade_day_coverage"] == pytest.approx(0.5)
    assert check["uncovered_trades"] == 1
    assert check["per_trade"][1]["secondary_result"] is None
    assert check["fill_field_distributions"]["open"]["mean"] == pytest.approx(100 / 101 - 1)
    assert check["per_trade"][0]["secondary_result"] == pytest.approx(102 / 101 - 1)
    assert report["recency_folds"] == report["folds"]
    assert (report["job_count"], report["cpu_count"],
            report["serial_parallel_identical"]) == (4, 8, True)
    markdown_path, json_path = write_report(tmp_path / "report", report)
    text = markdown_path.read_text()
    for section in ("Data declaration", "Costs", "Benchmark",
                    "Independent-price cross-check", "Variants", "Folds", "Caveats",
                    "Plain-English results"):
        assert f"## {section}" in text
    assert "SURVIVOR-BIASED SOURCE" in text
    assert "open_as_indication" in text
    assert json.loads(json_path.read_text()) == report


@pytest.mark.parametrize("side,expected", [("long", -1.0), ("short", 1.0)])
def test_cross_check_preserves_terminal_zero_outcomes(side, expected):
    from farm.study.report import price_cross_check

    first, second = date(2024, 1, 2), date(2024, 1, 3)
    bars = [_bar("AAA", first, 100, 100), _bar("AAA", second, 1, 0)]
    data = MarketData(PriceSource.declared(source="primary", bars=bars),
                      PriceSource.declared(source="independent", bars=bars))
    result = price_cross_check(data, [CrossCheckTrade(
        "AAA", side, first, "open", second, "close")], hard_max_date=second)
    assert result["covered_trades"] == 1
    assert result["per_trade"][0]["primary_result"] == expected
    assert result["per_trade"][0]["secondary_result"] == expected
    # A zero secondary denominator has no price ratio, but still covers the trade.
    assert result["fill_field_distributions"]["close"]["n"] == 0
    assert result["secondary_trade_result"]["mean"] == expected


@pytest.mark.parametrize("source", ["primary", "secondary"])
@pytest.mark.parametrize("field,value", [("open", 0), ("close", -1),
                                         ("close", float("inf"))])
def test_cross_check_rejects_invalid_entry_and_exit_prices(source, field, value):
    from farm.study.data import DataDeclaration
    from farm.study.report import price_cross_check

    day = date(2024, 1, 2)
    bars = [_bar("AAA", day, 100, 110)]
    invalid = [Bar("AAA", day, value if field == "open" else 100, 110, 0,
                   value if field == "close" else 110, 100)]
    primary = PriceSource(DataDeclaration("primary", "a" * 64, True, "point_in_time"),
                          invalid if source == "primary" else bars)
    secondary = PriceSource(DataDeclaration("independent", "b" * 64, True, "point_in_time"),
                            invalid if source == "secondary" else bars)
    with pytest.raises(ValueError, match="cross-check entry prices"):
        price_cross_check(MarketData(primary, secondary), [CrossCheckTrade(
            "AAA", "long", day, "open", day, "close")], hard_max_date=day)
