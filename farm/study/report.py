"""Fixed, atomic Markdown and JSON reports for shared study runs."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from engine.lib.resources import write_text_atomic

from .benchmark import Benchmark
from .costs import CostSelection, resolve
from .data import DataDeclaration, MarketData
from .protocol import RunIdentity
from .universe import SURVIVOR_WARNING


@dataclass(frozen=True)
class CrossCheckTrade:
    ticker: str
    side: str
    entry_session: date
    entry_field: str
    exit_session: date
    exit_field: str

    def __post_init__(self) -> None:
        if not self.ticker or self.side not in {"long", "short"}:
            raise ValueError("cross-check trade needs a ticker and long/short side")
        if self.exit_session < self.entry_session:
            raise ValueError("cross-check exit cannot precede entry")


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p5": None, "p95": None,
                "share_beyond_0_5pct": None}
    array = np.asarray(values, dtype=float)
    return {"n": len(array), "mean": float(array.mean()),
            "median": float(np.median(array)), "p5": float(np.percentile(array, 5)),
            "p95": float(np.percentile(array, 95)),
            "share_beyond_0_5pct": float(np.mean(np.abs(array) > 0.005))}


def price_cross_check(data: MarketData, trades: Iterable[CrossCheckTrade], *,
                      hard_max_date: date) -> dict:
    observations = tuple(trades)
    fields = sorted({field for trade in observations
                     for field in (trade.entry_field, trade.exit_field)})
    ratios = {field: [] for field in fields}
    rows, covered_days = [], set()
    by_day: dict[date, list[bool]] = {}
    for trade in observations:
        entry = data.fill_prices(trade.ticker, trade.entry_session, trade.entry_field,
                                 hard_max_date=hard_max_date)
        exit_ = data.fill_prices(trade.ticker, trade.exit_session, trade.exit_field,
                                 hard_max_date=hard_max_date)
        pairs = ((trade.entry_field, entry), (trade.exit_field, exit_))
        for field, pair in pairs:
            if pair.secondary is not None:
                if pair.secondary <= 0:
                    raise ValueError("secondary cross-check prices must be positive")
                ratios[field].append(pair.primary / pair.secondary - 1)
        covered = entry.secondary is not None and exit_.secondary is not None
        by_day.setdefault(trade.entry_session, []).append(covered)
        direction = 1 if trade.side == "long" else -1
        primary_result = direction * (exit_.primary / entry.primary - 1)
        secondary_result = None
        if covered:
            secondary_result = direction * (exit_.secondary / entry.secondary - 1)
        rows.append({"ticker": trade.ticker, "entry_session": trade.entry_session.isoformat(),
                     "exit_session": trade.exit_session.isoformat(), "side": trade.side,
                     "primary_result": primary_result,
                     "secondary_result": secondary_result, "covered": covered})
    covered_days = {day for day, coverage in by_day.items() if all(coverage)}
    trade_days = len(by_day)
    covered = sum(row["covered"] for row in rows)
    secondary_values = [row["secondary_result"] for row in rows if row["covered"]]
    return {
        "status": "available" if data.secondary is not None else "unavailable",
        "trade_days": trade_days, "covered_trade_days": len(covered_days),
        "trade_day_coverage": len(covered_days) / trade_days if trade_days else None,
        "trades": len(rows), "covered_trades": covered,
        "uncovered_trades": len(rows) - covered,
        "fill_field_distributions": {field: _distribution(ratios[field]) for field in fields},
        "secondary_trade_result": _distribution(secondary_values),
        "per_trade": rows,
    }


def _declaration(value: DataDeclaration) -> dict:
    return {"source": value.source, "snapshot_sha256": value.snapshot_sha256,
            "point_in_time": value.point_in_time, "survivor_status": value.survivor_status,
            "timezone": value.timezone, "session_open": value.session_open,
            "session_close": value.session_close,
            "daily_bar_lag_seconds": value.daily_bar_lag.total_seconds()}


def _variant_line(row: Mapping) -> str:
    sign = "positive" if row["absolute_net_positive"] else "not positive"
    return (f"{row['variant']}: net return {row['net_return']:.2%}, excess return "
            f"{row['excess_return']:.2%}, and absolute net return was {sign}.")


def build_report(*, identity: RunIdentity | str, data: MarketData, costs: CostSelection,
                 benchmark: Benchmark, variants: Iterable[Mapping], folds: Iterable[Mapping],
                 cross_check_trades: Iterable[CrossCheckTrade] = (),
                 hard_max_date: date, holdout: Mapping | None = None,
                 open_as_indication: bool = False, runtime_seconds: float,
                 worker_count: int, delisting_fallback_count: int = 0) -> dict:
    variant_rows = [dict(row) for row in variants]
    required = {"variant", "net_return", "benchmark_return", "excess_return",
                "absolute_net_positive", "trades", "one_sided_t"}
    if not variant_rows or any(not required <= row.keys() for row in variant_rows):
        raise ValueError("every report variant needs the fixed result fields")
    if not math.isfinite(runtime_seconds) or runtime_seconds < 0 or worker_count < 1:
        raise ValueError("runtime and worker count must be valid")
    selected = [resolve(name) for name in (costs.primary, *costs.sensitivities)]
    caveats = []
    if open_as_indication:
        caveats.append("open_as_indication: official opens stand in for pre-market indications.")
    if data.primary.declaration.survivor_status != "point_in_time":
        caveats.append(SURVIVOR_WARNING)
    caveats.extend(f"Unverified cost profile: {profile.id}."
                   for profile in selected if not profile.verified_against_fills)
    caveats.extend(f"Fewer than 100 trades: {row['variant']} ({row['trades']})."
                   for row in variant_rows if row["trades"] < 100)
    return {
        "schema_version": 1,
        "run_identity": identity.sha256 if isinstance(identity, RunIdentity) else identity,
        "runtime_seconds": runtime_seconds, "worker_count": worker_count,
        "delisting_fallback_count": delisting_fallback_count,
        "data": {"primary": _declaration(data.primary.declaration),
                 "secondary": (_declaration(data.secondary.declaration)
                               if data.secondary is not None else None)},
        "costs": {"primary": costs.primary, "sensitivities": list(costs.sensitivities),
                  "profiles": [{"id": profile.id, "sha256": profile.sha256,
                                "verified_against_fills": profile.verified_against_fills}
                               for profile in selected]},
        "benchmark": asdict(benchmark),
        "independent_price_cross_check": price_cross_check(
            data, cross_check_trades, hard_max_date=hard_max_date),
        "variants": variant_rows, "folds": [dict(row) for row in folds],
        "holdout": dict(holdout) if holdout is not None else None,
        "caveats": caveats,
        "variant_interpretations": [_variant_line(row) for row in variant_rows],
    }


def _fmt(value: object) -> str:
    if value is None:
        return "·"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def markdown(report: Mapping) -> str:
    primary, secondary = report["data"]["primary"], report["data"]["secondary"]
    lines = ["# Study report", "", f"Run identity: `{report['run_identity']}`  ",
             f"Runtime: {_fmt(report['runtime_seconds'])} seconds with "
             f"{report['worker_count']} worker(s).", "", "## Data declaration", "",
             f"Primary: `{primary['source']}`; point-in-time: {_fmt(primary['point_in_time'])}; "
             f"survivor status: `{primary['survivor_status']}`; snapshot "
             f"`{primary['snapshot_sha256']}`.",
             (f"Secondary: `{secondary['source']}`; snapshot "
              f"`{secondary['snapshot_sha256']}`." if secondary else "Secondary: not supplied."),
             "", "## Costs", "", f"Primary: `{report['costs']['primary']}`.  ",
             "Sensitivities: " + ", ".join(
                 f"`{value}`" for value in report["costs"]["sensitivities"]) + ".", "",
             "## Benchmark", "", f"Kind: `{report['benchmark']['kind']}`; mode: "
             f"`{report['benchmark']['mode']}`; ticker: "
             f"`{report['benchmark'].get('ticker') or 'none'}`.", "",
             "## Independent-price cross-check", ""]
    check = report["independent_price_cross_check"]
    lines.append(f"Trade-day coverage: {check['covered_trade_days']}/{check['trade_days']} "
                 f"({_fmt(check['trade_day_coverage'])}); uncovered trades: "
                 f"{check['uncovered_trades']}.")
    lines += ["", "| Fill field | N | Mean | Median | P5 | P95 | Share beyond 0.5% |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for field, row in check["fill_field_distributions"].items():
        lines.append(f"| `{field}` | {row['n']} | {_fmt(row['mean'])} | "
                     f"{_fmt(row['median'])} | {_fmt(row['p5'])} | {_fmt(row['p95'])} | "
                     f"{_fmt(row['share_beyond_0_5pct'])} |")
    lines += ["", "Secondary-price per-trade results use only trades with both independent "
              "entry and exit prices; uncovered trades remain missing.", "", "## Variants", "",
              "| Variant | Net | Benchmark | Excess | Absolute net > 0 | Trades | One-sided t |",
              "|---|---:|---:|---:|:---:|---:|---:|"]
    for row in report["variants"]:
        lines.append(f"| {row['variant']} | {_fmt(row['net_return'])} | "
                     f"{_fmt(row['benchmark_return'])} | {_fmt(row['excess_return'])} | "
                     f"{_fmt(row['absolute_net_positive'])} | {row['trades']} | "
                     f"{_fmt(row['one_sided_t'])} |")
    lines += ["", "## Folds", "", "```json",
              json.dumps(report["folds"], indent=2, sort_keys=True, allow_nan=False), "```"]
    if report["holdout"] is not None:
        lines += ["", "## Holdout", "", "```json",
                  json.dumps(report["holdout"], indent=2, sort_keys=True, allow_nan=False), "```"]
    lines += ["", "## Caveats", ""]
    lines.extend(f"- {item}" for item in report["caveats"] or ["None."])
    lines += ["", "## Plain-English results", ""]
    lines.extend(report["variant_interpretations"])
    return "\n".join(lines) + "\n"


def write_report(output_dir: str | Path, report: Mapping) -> tuple[Path, Path]:
    target = Path(output_dir)
    json_path, markdown_path = target / "report.json", target / "report.md"
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    write_text_atomic(json_path, encoded)
    write_text_atomic(markdown_path, markdown(report))
    return markdown_path, json_path
