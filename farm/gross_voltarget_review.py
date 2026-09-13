#!/usr/bin/env python
"""Evaluate the frozen gross-volatility grid against its matched static control.

This closes the comparison addendum in ``docs/charters/ew_gross_voltarget.md``.
It consumes existing sweep artifacts only: it does not run a backtest, select a
paper book, modify a ledger, or open recurring research.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine.lib import resources
from engine.lib.settings import DATA_DIR
from farm import stats as fstats

DEFAULT_DYNAMIC_DIR = DATA_DIR / "reports" / "sweeps" / "gross_voltarget" / "results"
DEFAULT_STATIC_DIR = DATA_DIR / "reports" / "sweeps" / "static_exposure" / "results"
DEFAULT_OUT_DIR = DATA_DIR / "reports" / "experiments" / "gross-voltarget-matched-static"

EXPECTED_DYNAMIC_IDS = frozenset(
    f"sweep__gross_voltarget__vol_lookback-{lookback}__vol_target-{target}"
    for lookback in (40, 60, 120)
    for target in (0.1, 0.15, 0.2)
)
EXPECTED_STATIC_IDS = frozenset(
    f"sweep__static_exposure__exposure-{exposure}"
    for exposure in (0.3, 0.4, 0.5, 0.6, 0.8)
)
ID_RE = re.compile(r"vol_lookback-(?P<lookback>\d+)__vol_target-(?P<target>[0-9.]+)$")
COHORT_FIELDS = (
    "fill_model", "initial_cash", "screen_source", "universe_policy",
    "span_start", "span_end", "sessions", "screen_rows", "protocol",
)
NONDETERMINISTIC_BENCHMARK_FIELDS = frozenset({
    "generated_utc", "runtime_s", "scratch_s", "screen_s",
})


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _load_family(root: Path, expected: frozenset[str], strategy: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(root.glob("sweep__*.json")):
        result = _load(path)
        config_id = result.get("config_id")
        if config_id in expected:
            if result.get("strategy") != strategy:
                raise ValueError(f"{config_id}: expected strategy {strategy}")
            rows[config_id] = result
    missing = sorted(expected - rows.keys())
    extra = sorted(rows.keys() - expected)
    if missing or extra:
        raise ValueError(f"{strategy}: grid mismatch; missing={missing}, extra={extra}")
    return rows


def _cohort_signature(result: dict) -> str:
    return json.dumps(
        {field: result.get(field) for field in COHORT_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
    )


def _folds(result: dict) -> dict[int, dict]:
    folds = result.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError(f"{result.get('config_id')}: missing folds")
    out: dict[int, dict] = {}
    for fold in folds:
        if fold.get("status") != "ok":
            raise ValueError(
                f"{result.get('config_id')}: fold {fold.get('index')} is not ok"
            )
        idx = int(fold["index"])
        if idx in out:
            raise ValueError(f"{result.get('config_id')}: duplicate fold {idx}")
        validate = fold.get("validate") or {}
        for field in ("total_return", "vol_ann", "max_dd"):
            value = validate.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{result.get('config_id')}: bad fold {idx} {field}")
        if validate["vol_ann"] <= 0:
            raise ValueError(f"{result.get('config_id')}: nonpositive fold {idx} volatility")
        out[idx] = fold
    return out


def _economic_benchmark(value):
    """Remove run-timing metadata before comparing duplicate controls."""
    if isinstance(value, dict):
        return {
            key: _economic_benchmark(item)
            for key, item in value.items()
            if key not in NONDETERMINISTIC_BENCHMARK_FIELDS
        }
    if isinstance(value, list):
        return [_economic_benchmark(item) for item in value]
    return value


def _linear_slope(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2 or np.ptp(x) <= 1e-12:
        raise ValueError("cannot estimate volatility slope")
    return float(np.polyfit(np.asarray(x), np.asarray(y), 1)[0])


def _slope_ci(x: list[float], y: list[float]) -> dict:
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    rng = np.random.default_rng(fstats.BOOTSTRAP_SEED)
    slopes: list[float] = []
    for _ in range(fstats.BOOTSTRAP_DRAWS):
        idx = rng.integers(0, len(a), len(a))
        if np.ptp(a[idx]) > 1e-12:
            slopes.append(_linear_slope(a[idx].tolist(), b[idx].tolist()))
    if not slopes:
        raise ValueError("all slope bootstrap samples are degenerate")
    alpha = 1.0 - fstats.BOOTSTRAP_CONF
    lo, hi = np.quantile(slopes, [alpha / 2, 1 - alpha / 2])
    return {
        "point": _linear_slope(x, y),
        "lo": float(lo),
        "hi": float(hi),
        "conf": fstats.BOOTSTRAP_CONF,
        "n_boot": fstats.BOOTSTRAP_DRAWS,
        "seed": fstats.BOOTSTRAP_SEED,
        "contains_zero": bool(lo <= 0 <= hi),
    }


def evaluate(dynamic_dir: Path, static_dir: Path) -> dict:
    dynamic = _load_family(dynamic_dir, EXPECTED_DYNAMIC_IDS, "ew_gross_voltarget")
    static = _load_family(static_dir, EXPECTED_STATIC_IDS, "ew_static_exposure")
    dynamic_bench = _load(dynamic_dir / "ew_benchmark.json")
    static_bench = _load(static_dir / "ew_benchmark.json")
    if dynamic_bench.get("config_id") != "ew_benchmark" \
            or static_bench.get("config_id") != "ew_benchmark":
        raise ValueError("missing ew_benchmark control")
    signatures = {
        _cohort_signature(result)
        for result in [dynamic_bench, static_bench, *dynamic.values(), *static.values()]
    }
    if len(signatures) != 1:
        raise ValueError("dynamic/static research cohort mismatch")
    benchmark = _folds(dynamic_bench)
    _folds(static_bench)
    if _economic_benchmark(dynamic_bench) != _economic_benchmark(static_bench):
        raise ValueError("dynamic/static benchmark folds differ")
    expected_folds = set(benchmark)
    if any(set(_folds(result)) != expected_folds for result in [*dynamic.values(), *static.values()]):
        raise ValueError("candidate/control fold coverage mismatch")

    provenance_fields = ("source_sha256", "data_snapshot", "execution_profile")
    provenance_complete = all(
        all(result.get(field) for field in provenance_fields)
        for result in [dynamic_bench, static_bench, *dynamic.values(), *static.values()]
    )
    bench_worst_dd = min(
        fold["validate"]["max_dd"] for fold in benchmark.values()
    )
    static_folds = {key: _folds(result) for key, result in static.items()}
    rows = []
    for config_id, result in sorted(dynamic.items()):
        match = ID_RE.search(config_id)
        if match is None:
            raise ValueError(f"cannot parse {config_id}")
        folds = _folds(result)
        fold_rows = []
        for idx in sorted(expected_folds):
            candidate = folds[idx]["validate"]
            bench = benchmark[idx]["validate"]
            choices = []
            for static_id, by_fold in static_folds.items():
                control = by_fold[idx]["validate"]
                choices.append((abs(control["vol_ann"] - candidate["vol_ann"]),
                                static_id, control))
            _distance, static_id, control = min(choices, key=lambda item: (item[0], item[1]))
            candidate_ratio = candidate["total_return"] / candidate["vol_ann"]
            control_ratio = control["total_return"] / control["vol_ann"]
            fold_rows.append({
                "fold": idx,
                "benchmark_vol_ann": bench["vol_ann"],
                "candidate_vol_ann": candidate["vol_ann"],
                "matched_static_id": static_id,
                "matched_static_vol_ann": control["vol_ann"],
                "timing_excess": candidate["total_return"] - control["total_return"],
                "candidate_return_over_vol": candidate_ratio,
                "static_return_over_vol": control_ratio,
                "risk_adjusted_win": candidate_ratio > control_ratio,
            })
        ew_excess = [
            folds[idx]["validate"]["total_return"]
            - benchmark[idx]["validate"]["total_return"]
            for idx in sorted(expected_folds)
        ]
        timing_excess = [row["timing_excess"] for row in fold_rows]
        benchmark_vol = [row["benchmark_vol_ann"] for row in fold_rows]
        worst_dd = min(fold["validate"]["max_dd"] for fold in folds.values())
        median_ew_excess = float(np.median(ew_excess))
        beat_ew = sum(value > 0 for value in ew_excess) / len(ew_excess)
        risk_adjusted_win_rate = sum(row["risk_adjusted_win"] for row in fold_rows) / len(fold_rows)
        gates = {
            "drawdown_relief_at_least_5pp": worst_dd - bench_worst_dd >= 0.05,
            "median_return_cost_no_more_than_10pp": median_ew_excess >= -0.10,
            "ew_beat_rate_gate": not (median_ew_excess < 0 and beat_ew < 0.30),
            "all_folds_ok": True,
            "matched_static_risk_adjusted_win_rate_at_least_half": (
                risk_adjusted_win_rate >= 0.50
            ),
        }
        timing_mean_ci = fstats.bootstrap_ci(timing_excess, stat="mean")
        timing_median_ci = fstats.bootstrap_ci(timing_excess, stat="median")
        slope_ci = _slope_ci(benchmark_vol, timing_excess)
        rows.append({
            "config_id": config_id,
            "vol_lookback": int(match.group("lookback")),
            "vol_target": float(match.group("target")),
            "n_folds": len(fold_rows),
            "median_excess_vs_ew": median_ew_excess,
            "beat_ew_rate": beat_ew,
            "worst_drawdown": worst_dd,
            "drawdown_relief_vs_ew": worst_dd - bench_worst_dd,
            "matched_static_risk_adjusted_win_rate": risk_adjusted_win_rate,
            "mean_timing_excess": float(np.mean(timing_excess)),
            "median_timing_excess": float(np.median(timing_excess)),
            "mean_timing_excess_ci": timing_mean_ci,
            "median_timing_excess_ci": timing_median_ci,
            "timing_vs_benchmark_vol_slope": slope_ci,
            "kill_gates": gates,
            "survives_kill_gates": all(gates.values()),
            "positive_timing_edge_established": bool(
                timing_mean_ci and timing_mean_ci["lo"] > 0
                and slope_ci["lo"] > 0
            ),
            "folds": fold_rows,
        })
    rows.sort(key=lambda row: (row["vol_target"], row["vol_lookback"]))
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paper_only": True,
        "automatic_action": "none",
        "decision": "INCONCLUSIVE-LEGACY",
        "decision_reason": (
            "Some cells survive permissive kill gates, but no cell establishes positive "
            "timing value and the v2 artifacts lack complete source/data/profile provenance."
        ),
        "candidate_trials": len(dynamic),
        "static_control_cells": len(static),
        "cohort": {field: dynamic_bench.get(field) for field in COHORT_FIELDS},
        "provenance_complete": provenance_complete,
        "surviving_cells": [row["config_id"] for row in rows if row["survives_kill_gates"]],
        "positive_timing_edge_cells": [
            row["config_id"] for row in rows if row["positive_timing_edge_established"]
        ],
        "rows": rows,
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def render(report: dict) -> str:
    lines = [
        "# Gross-volatility targeting — matched-static review",
        "",
        f"_Decision **{report['decision']}** · paper only · no automatic action._",
        "",
        report["decision_reason"],
        "",
        f"This evaluates all {report['candidate_trials']} predeclared dynamic cells against "
        f"the nearest-volatility fold from {report['static_control_cells']} static-exposure "
        "controls. Matching is deterministic and fold-local; no cell is selected for trading.",
        "",
        "| Lookback | Target | Kill gates | RA wins vs static | Mean timing excess | 90% CI | Vol-slope | 90% CI | Timing edge? |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["rows"]:
        mean_ci = row["mean_timing_excess_ci"]
        slope_ci = row["timing_vs_benchmark_vol_slope"]
        lines.append(
            f"| {row['vol_lookback']} | {_pct(row['vol_target'])} | "
            f"{'SURVIVES' if row['survives_kill_gates'] else 'KILLED'} | "
            f"{row['matched_static_risk_adjusted_win_rate'] * 100:.0f}% | "
            f"{_pct(row['mean_timing_excess'])} | "
            f"[{_pct(mean_ci['lo'])}, {_pct(mean_ci['hi'])}] | "
            f"{slope_ci['point']:+.3f} | [{slope_ci['lo']:+.3f}, {slope_ci['hi']:+.3f}] | "
            f"{'YES' if row['positive_timing_edge_established'] else 'no'} |"
        )
    lines.extend([
        "",
        "`RA wins` compares validate return/annualized-volatility with the matched static "
        "control. The slope regresses timing excess on the same fold's EW benchmark "
        f"volatility. Intervals use {fstats.BOOTSTRAP_DRAWS:,} paired fold resamples with "
        f"seed `{fstats.BOOTSTRAP_SEED}`.",
        "",
        "The three 10%-target cells survive the original permissive drawdown/return gates. "
        "That is not proof of edge: every mean timing-excess interval contains zero, no "
        "volatility-slope interval is wholly positive, nine candidate cells were searched, "
        "and the inputs are legacy fill-model-v2 artifacts without complete provenance. "
        "No paper registration, rerun, parameter choice, or live action follows.",
        "",
    ])
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result.json"
    md_path = out_dir / "README.md"
    resources.write_text_atomic(
        json_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    resources.write_text_atomic(md_path, render(report))
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dynamic-dir", type=Path, default=DEFAULT_DYNAMIC_DIR)
    parser.add_argument("--static-dir", type=Path, default=DEFAULT_STATIC_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    report = evaluate(args.dynamic_dir, args.static_dir)
    md_path, json_path = write_report(report, args.out_dir)
    print(f"[gross-voltarget-review] {report['decision']}: wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
