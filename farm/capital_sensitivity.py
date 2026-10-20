#!/usr/bin/env python
"""Full-path capital and execution-cost sensitivity replays.

Artifacts are deliberately isolated from canonical backtest/walk-forward
results. Each cell reruns the strategy; no return is scaled after the fact.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.lib import db, resources
from engine.lib.log import get_logger
from engine.lib.settings import DATA_DIR, REPO_ROOT
from farm.backtest import replay
from sim import execution

log = get_logger("capital-sensitivity")

CAPITAL_GRID = (10_000.0, 39_000.0, 100_000.0, 250_000.0, 1_000_000.0,
                10_000_000.0)
PROFILE_GRID = (execution.BASELINE.id, execution.COST_2X.id)
OUT_DIR = DATA_DIR / "reports" / "capital-sensitivity"
SCRATCH_ROOT = REPO_ROOT / "scratch" / "capital-sensitivity"


def capital_slug(value: float) -> str:
    return f"usd-{int(value)}"


def _cell_summary(result: dict) -> dict:
    keys = (
        "initial_cash", "total_return", "cagr", "max_dd", "n_fills",
        "n_rejected", "n_capacity_rejected", "capacity_rejected_notional",
        "p95_participation", "max_participation", "gross_traded_notional",
        "turnover_on_initial_cash", "modeled_price_cost_dollars",
        "modeled_total_cost_dollars", "source_sha256", "source_file_count",
        "config_sha256", "fill_model", "universe_policy",
        "data_quality_class", "data_snapshot", "execution_profile",
    )
    return {key: result.get(key) for key in keys}


def _cohort_signature(cell: dict) -> tuple:
    snapshot = cell.get("data_snapshot") or {}
    snapshot_sha = snapshot.get("sha256") if isinstance(snapshot, dict) else snapshot
    return (
        cell.get("source_sha256"), cell.get("source_file_count"),
        cell.get("config_sha256"), cell.get("fill_model"),
        cell.get("universe_policy"), cell.get("data_quality_class"),
        snapshot_sha,
    )


def capacity_observations(cells: list[dict], profiles: tuple[str, ...]) -> list[dict]:
    """Report bounds only at sampled capitals; never interpolate a ceiling."""
    observations = []
    for profile_id in profiles:
        rows = sorted(
            (c for c in cells if c["profile_id"] == profile_id),
            key=lambda c: c["initial_cash"],
        )
        clean = [c["initial_cash"] for c in rows
                 if not int(c.get("n_capacity_rejected") or 0)]
        rejected = [c["initial_cash"] for c in rows
                    if int(c.get("n_capacity_rejected") or 0)]
        observations.append({
            "profile_id": profile_id,
            "largest_zero_reject_capital": max(clean) if clean else None,
            "first_capacity_reject_capital": min(rejected) if rejected else None,
        })
    return observations


def _aggregate(config_id: str, window: str, cells: list[dict],
               capitals: tuple[float, ...], profiles: tuple[str, ...]) -> dict:
    expected = {(profile_id, float(capital))
                for profile_id in profiles for capital in capitals}
    actual = {(cell.get("profile_id"), float(cell.get("initial_cash")))
              for cell in cells}
    if actual != expected or len(cells) != len(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            "incomplete capital-sensitivity grid: "
            f"expected {len(expected)} unique cells, got {len(cells)}; "
            f"missing={missing}, extra={extra}"
        )

    for cell in cells:
        stamped = cell.get("execution_profile") or {}
        stamped_id = stamped.get("id") if isinstance(stamped, dict) else stamped
        if stamped_id != cell["profile_id"]:
            raise ValueError(
                "execution profile mismatch: requested "
                f"{cell['profile_id']!r}, replay stamped {stamped_id!r}"
            )

    signatures = {_cohort_signature(cell) for cell in cells}
    if len(signatures) != 1:
        raise ValueError(f"mixed capital-sensitivity cohort: {sorted(map(str, signatures))}")
    signature = next(iter(signatures))
    if any(value is None for value in signature):
        raise ValueError(f"unstamped capital-sensitivity cohort: {signature}")
    cohort_keys = (
        "source_sha256", "source_file_count", "config_sha256", "fill_model",
        "universe_policy", "data_quality_class", "data_snapshot_sha256",
    )
    cohort = dict(zip(cohort_keys, signature, strict=True))

    return {
        "kind": "capital_sensitivity",
        "paper_only": True,
        "config_id": config_id,
        "window": window,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capital_grid": list(capitals),
        "execution_profiles": [execution.resolve_profile(p).as_dict()
                               for p in profiles],
        "cohort": cohort,
        "capacity_observations": capacity_observations(cells, profiles),
        "cells": cells,
    }


def _write_aggregate(aggregate: dict, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    resources.write_text_atomic(
        root / "summary.json",
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
    )
    write_markdown(aggregate, root / "README.md")


def write_markdown(aggregate: dict, path: Path) -> None:
    def pct(value) -> str:
        return "·" if value is None else f"{100 * value:.2f}%"

    def money(value) -> str:
        return "·" if value is None else f"${value:,.0f}"

    def number(value) -> str:
        return "·" if value is None else f"{value:.2f}"

    cohort = aggregate["cohort"]
    lines = [
        f"# Capital sensitivity — `{aggregate['config_id']}` / `{aggregate['window']}`",
        "",
        "_Every row is a complete strategy replay. Returns were not rescaled from "
        "another account size. This is paper research, not authorization for live trading._",
        "",
        f"Evidence class: `{cohort['data_quality_class']}` · fill model "
        f"`{cohort['fill_model']}` · source `{cohort['source_sha256']}` · data "
        f"`{cohort['data_snapshot_sha256']}`.",
        "",
        "Capacity observations are bounds at the sampled account sizes, not an "
        "interpolated or guaranteed trading capacity.",
        "",
    ]
    for observation in aggregate["capacity_observations"]:
        largest = observation["largest_zero_reject_capital"]
        first = observation["first_capacity_reject_capital"]
        largest_text = "none" if largest is None else f"${largest:,.0f}"
        first_text = "none in grid" if first is None else f"${first:,.0f}"
        lines.append(
            f"- `{observation['profile_id']}`: Largest tested capital with zero "
            f"capacity rejects: **{largest_text}**; first tested capital with a "
            f"capacity reject: **{first_text}**."
        )
    lines.extend([
        "",
        "| Profile | Start | Return | Max DD | Fills | Total rejects | "
        "Capacity rejects | Rejected notional | p95 participation | "
        "Max participation | Turnover | Market cost $ | Total cost $ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for cell in aggregate["cells"]:
        lines.append(
            f"| `{cell['profile_id']}` | {money(cell['initial_cash'])} | "
            f"{pct(cell.get('total_return'))} | {pct(cell.get('max_dd'))} | "
            f"{cell.get('n_fills', 0)} | {cell.get('n_rejected', 0)} | "
            f"{cell.get('n_capacity_rejected', 0)} | "
            f"{money(cell.get('capacity_rejected_notional'))} | "
            f"{pct(cell.get('p95_participation'))} | "
            f"{pct(cell.get('max_participation'))} | "
            f"{number(cell.get('turnover_on_initial_cash'))}× | "
            f"{money(cell.get('modeled_price_cost_dollars'))} | "
            f"{money(cell.get('modeled_total_cost_dollars'))} |"
        )
    resources.write_text_atomic(path, "\n".join(lines) + "\n")


def run_grid(live_con, config_id: str, window: str, *,
             capitals: tuple[float, ...] = CAPITAL_GRID,
             profiles: tuple[str, ...] = PROFILE_GRID,
             out_dir: Path = OUT_DIR, scratch_root: Path = SCRATCH_ROOT,
             threads: int | None = 4, mem_mb: int | None = 4500,
             verbose: bool = True) -> dict:
    """Run and persist every capital/profile cell outside canonical outputs."""
    cells = []
    root = Path(out_dir) / config_id / window
    for profile_id in profiles:
        execution.resolve_profile(profile_id)
        for capital in capitals:
            capital = float(capital)
            cell_dir = root / "cells" / profile_id / capital_slug(capital)
            result = replay.run_replay(
                live_con, config_id, window,
                scratch_root=Path(scratch_root) / profile_id / capital_slug(capital),
                results_dir=cell_dir, write_result=True, verbose=verbose,
                threads=threads, mem_mb=mem_mb, initial_cash=capital,
                execution_profile=profile_id,
            )
            cell = {"profile_id": profile_id, **_cell_summary(result)}
            cells.append(cell)

    aggregate = _aggregate(config_id, window, cells, capitals, profiles)
    _write_aggregate(aggregate, root)
    log.info(f"[capital-sensitivity] wrote {root}")
    return aggregate


def rebuild_summary(config_id: str, window: str, *,
                    capitals: tuple[float, ...] = CAPITAL_GRID,
                    profiles: tuple[str, ...] = PROFILE_GRID,
                    out_dir: Path = OUT_DIR) -> dict:
    """Validate completed replay cells and regenerate only aggregate artifacts."""
    root = Path(out_dir) / config_id / window
    cells = []
    for profile_id in profiles:
        execution.resolve_profile(profile_id)
        for capital in capitals:
            cell_path = (root / "cells" / profile_id / capital_slug(capital)
                         / f"{config_id}__{window}.json")
            if not cell_path.exists():
                raise FileNotFoundError(
                    f"missing capital-sensitivity cell: {cell_path}")
            result = json.loads(cell_path.read_text())
            cells.append({"profile_id": profile_id, **_cell_summary(result)})
    aggregate = _aggregate(config_id, window, cells, capitals, profiles)
    _write_aggregate(aggregate, root)
    log.info(f"[capital-sensitivity] rebuilt {root} from {len(cells)} cells")
    return aggregate


def run_job(params: dict, con, meta_path=None) -> None:
    config_id = params.get("config_id")
    if not config_id:
        raise ValueError("capital_sensitivity needs params {'config_id': …}")
    run_grid(
        con, config_id, params.get("window", "5y"),
        capitals=tuple(float(v) for v in params.get("capitals", CAPITAL_GRID)),
        profiles=tuple(params.get("execution_profiles", PROFILE_GRID)),
        out_dir=Path(params.get("out_dir") or OUT_DIR),
        scratch_root=Path(params.get("scratch_root") or SCRATCH_ROOT),
        threads=params.get("threads", 4), mem_mb=params.get("mem_mb", 4500),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--config", required=True)
    ap.add_argument("--window", default="5y", choices=list(replay.WINDOW_MONTHS))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--scratch-root", default=str(SCRATCH_ROOT))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--rebuild-summary", action="store_true",
                    help="validate existing cells and rewrite summary files only")
    args = ap.parse_args()
    if args.rebuild_summary:
        rebuild_summary(args.config, args.window, out_dir=Path(args.out_dir))
        return 0
    con = db.connect(args.db, read_only=True)
    try:
        run_grid(con, args.config, args.window, out_dir=Path(args.out_dir),
                 scratch_root=Path(args.scratch_root), threads=args.threads)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
