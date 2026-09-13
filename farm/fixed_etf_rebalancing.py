#!/usr/bin/env python
"""Run and evaluate charter FIXED-ETF-REBAL-2026-09-07-v1.

Exactly four isolated walk-forward replays are permitted: one candidate and
one same-basket buy-and-hold control under baseline and doubled costs. Nothing
in this module registers a paper portfolio, opens a grid, or promotes a rule.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db, resources
from engine.lib.settings import DATA_DIR, REPO_ROOT
from engine.lib.util import pct
from farm.walkforward import monthly, protocol, runner
from sim import execution
from sim.strategies import REGISTRY
from sim.strategies.fixed_etf_rebalancing import (
    ASSETS,
    FixedEtfBuyHold,
    FixedEtfRebalanced,
)

CHARTER_ID = "FIXED-ETF-REBAL-2026-09-07-v1"
COMPARISON_PROTOCOL = "fixed-etf-rebal-2026-09-07-v1"
CANDIDATE_ID = "fixed_etf_rebalanced"
CONTROL_ID = "fixed_etf_buy_hold"
ANCHOR = date(2026, 9, 4)
INITIAL_CASH = 39_000.0
PROFILES = (execution.BASELINE.id, execution.COST_2X.id)
OUT_DIR = DATA_DIR / "reports" / "experiments" / "fixed-etf-rebalancing-v1"
SCRATCH_ROOT = REPO_ROOT / "scratch" / "fixed-etf-rebalancing-v1"
RESEARCH_STRATEGIES = {
    CONTROL_ID: FixedEtfBuyHold,
    CANDIDATE_ID: FixedEtfRebalanced,
}


def _config(config_id: str, profile_id: str) -> dict:
    is_candidate = config_id == CANDIDATE_ID
    strategy = "fixed_etf_rebalanced" if is_candidate else "fixed_etf_buy_hold"
    name = "Quarterly Equal-Weight SPY/IEF/GLD" if is_candidate else \
        "Buy-and-Hold Equal-Weight SPY/IEF/GLD"
    return {
        "id": config_id,
        "name": name,
        "strategy": strategy,
        "cadence": "daily",
        "params": {"assets": list(ASSETS)},
        "charter_id": CHARTER_ID,
        "profile_id": profile_id,
        "description": (
            "Equal-weight SPY/IEF/GLD at inception and calendar-quarter ends."
            if is_candidate else
            "Equal-weight SPY/IEF/GLD at inception with no later rebalance."
        ),
        "expectation": "Positive net rebalancing premium versus the identical basket.",
        "kill_criterion": "Any failed gate in the versioned charter closes v1.",
    }


def _book(config_id: str, profile_id: str) -> dict:
    cfg = _config(config_id, profile_id)
    return {
        "id": config_id,
        "name": cfg["name"],
        "strategy": cfg["strategy"],
        "config": cfg,
        "config_json": json.dumps(cfg, sort_keys=True),
        "excluded": None,
        "initial_cash": INITIAL_CASH,
        "execution_profile": profile_id,
        "data_quality_class": "fixed_etf_history",
        "created": CHARTER_ID,
        "expected_assets": ASSETS,
        "quarter_end_signals": config_id == CANDIDATE_ID,
        "verify_rebuild_state": True,
        "comparison": {
            "protocol": COMPARISON_PROTOCOL,
            "control_id": CONTROL_ID if config_id == CANDIDATE_ID else None,
            "evidence_role": "chartered_exploratory_historical_comparison",
        },
    }


def _result_path(out_dir: Path, profile_id: str, config_id: str) -> Path:
    return out_dir / profile_id / "results" / f"{config_id}.json"


def run_replays(live_con, *, out_dir: Path = OUT_DIR,
                scratch_root: Path = SCRATCH_ROOT, threads: int = 4) -> None:
    collisions = sorted(RESEARCH_STRATEGIES.keys() & REGISTRY.keys())
    if collisions:
        raise RuntimeError(
            "fixed-ETF research strategies unexpectedly exist in the production "
            f"registry: {', '.join(collisions)}"
        )
    # The league resolves strategies through its production registry. Install
    # these charter-only classes for this isolated process and always remove
    # them afterward; importing this module never makes either strategy eligible
    # for a live paper portfolio.
    REGISTRY.update(RESEARCH_STRATEGIES)
    try:
        for profile_id in PROFILES:
            results_dir = out_dir / profile_id / "results"
            for config_id in (CONTROL_ID, CANDIDATE_ID):
                runner.run_book(
                    live_con,
                    config_id,
                    book=_book(config_id, profile_id),
                    anchor=ANCHOR,
                    train_months=protocol.TRAIN_MONTHS,
                    validate_months=protocol.VALIDATE_MONTHS,
                    step_months=protocol.STEP_MONTHS,
                    n_folds=protocol.N_FOLDS,
                    scratch_root=scratch_root,
                    results_dir=results_dir,
                    initial_cash=INITIAL_CASH,
                    execution_profile=profile_id,
                    threads=threads,
                )
    finally:
        for strategy_id, strategy_type in RESEARCH_STRATEGIES.items():
            if REGISTRY.get(strategy_id) is strategy_type:
                del REGISTRY[strategy_id]


def load_results(out_dir: Path = OUT_DIR) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for profile_id in PROFILES:
        out[profile_id] = {}
        for config_id in (CONTROL_ID, CANDIDATE_ID):
            path = _result_path(out_dir, profile_id, config_id)
            if not path.exists():
                raise FileNotFoundError(path)
            out[profile_id][config_id] = json.loads(path.read_text())
    return out


def _signature(result: dict) -> tuple:
    profile = result.get("execution_profile")
    snapshot = result.get("data_snapshot")
    comparison = result.get("comparison")
    return (
        result.get("source_sha256"),
        result.get("source_file_count"),
        result.get("fill_model"),
        result.get("initial_cash"),
        json.dumps(profile, sort_keys=True) if isinstance(profile, dict) else None,
        snapshot.get("sha256") if isinstance(snapshot, dict) else None,
        result.get("data_quality_class"),
        json.dumps(result.get("protocol"), sort_keys=True),
        comparison.get("protocol") if isinstance(comparison, dict) else None,
    )


def _folds(result: dict) -> dict[tuple, dict]:
    return {
        (fold.get("split_date"), fold.get("validate_end")): fold
        for fold in result.get("folds", [])
        if fold.get("status") == "ok"
    }


def _paired_months(candidate: dict, control: dict) -> tuple[list[dict], int]:
    candidate_folds, control_folds = _folds(candidate), _folds(control)
    rows: list[dict] = []
    missing = 0
    for key in sorted(candidate_folds.keys() | control_folds.keys()):
        c_fold, b_fold = candidate_folds.get(key), control_folds.get(key)
        if c_fold is None or b_fold is None:
            missing += 1
            continue
        c_months = dict(monthly.monthly_returns(c_fold["validate_monthly_equity"]))
        b_months = dict(monthly.monthly_returns(b_fold["validate_monthly_equity"]))
        missing += len(c_months.keys() ^ b_months.keys())
        for month in sorted(c_months.keys() & b_months.keys()):
            rows.append({
                "fold": c_fold.get("index"),
                "month": month,
                "candidate": c_months[month],
                "control": b_months[month],
                "excess": c_months[month] - b_months[month],
            })
    return rows, missing


def _execution_check(result: dict) -> dict:
    folds = [f for f in result.get("folds", []) if f.get("status") == "ok"]
    return {
        "all_folds_ok": len(folds) == protocol.N_FOLDS,
        "n_rejected": sum(int(f.get("n_rejected") or 0) for f in folds),
        "n_pending": sum(int(f.get("n_pending") or 0) for f in folds),
        "n_capacity_rejected": sum(int(f.get("n_capacity_rejected") or 0) for f in folds),
        "missing_initial_assets": sum(
            len(f.get("initial_entry_missing_assets") or []) for f in folds
        ),
        "missing_required_signal_prices": sum(
            len(f.get("missing_required_signal_prices") or []) for f in folds
        ),
        "state_rebuild_matches": bool(folds) and all(
            f.get("state_rebuild_matches") is True for f in folds
        ),
    }


def evaluate(results: dict[str, dict[str, dict]]) -> dict:
    profiles: dict[str, dict] = {}
    cross_profile_signatures = set()
    for profile_id in PROFILES:
        candidate = results[profile_id][CANDIDATE_ID]
        control = results[profile_id][CONTROL_ID]
        if _signature(candidate) != _signature(control):
            raise ValueError(f"{profile_id}: candidate/control research cohort mismatch")
        stamped_id = (candidate.get("execution_profile") or {}).get("id")
        if stamped_id != profile_id:
            raise ValueError(f"{profile_id}: candidate stamped {stamped_id!r}")
        signature = _signature(candidate)
        cross_profile_signatures.add((
            signature[0], signature[1], signature[2], signature[3],
            signature[5], signature[6], signature[7], signature[8],
        ))
        rows, missing_months = _paired_months(candidate, control)
        excess = [row["excess"] for row in rows]
        mean_ci = monthly.block_bootstrap_ci(
            excess, stat="mean", mean_block=4, n_boot=10_000, seed=20260907
        )
        candidate_growth = math.prod(1.0 + row["candidate"] for row in rows)
        control_growth = math.prod(1.0 + row["control"] for row in rows)
        candidate_folds, control_folds = _folds(candidate), _folds(control)
        drawdowns = []
        for key in sorted(candidate_folds.keys() & control_folds.keys()):
            cdd = candidate_folds[key]["validate"].get("max_dd")
            bdd = control_folds[key]["validate"].get("max_dd")
            if cdd is not None and bdd is not None:
                drawdowns.append({
                    "fold": candidate_folds[key].get("index"),
                    "candidate": cdd,
                    "control": bdd,
                    "difference": cdd - bdd,
                })
        profiles[profile_id] = {
            "n_paired_months": len(rows),
            "n_missing_paired_months": missing_months,
            "mean_monthly_excess": sum(excess) / len(excess) if excess else None,
            "mean_monthly_excess_ci": mean_ci,
            "cumulative_candidate_return": candidate_growth - 1.0,
            "cumulative_control_return": control_growth - 1.0,
            "cumulative_excess": candidate_growth - control_growth,
            "drawdown_pairs": drawdowns,
            "worst_drawdown_difference": min(
                (row["difference"] for row in drawdowns), default=None
            ),
            "candidate_execution": _execution_check(candidate),
            "control_execution": _execution_check(control),
            "source_sha256": candidate.get("source_sha256"),
            "data_snapshot_sha256": (candidate.get("data_snapshot") or {}).get("sha256"),
            "execution_profile": candidate.get("execution_profile"),
        }

    if len(cross_profile_signatures) != 1:
        raise ValueError("baseline/stress research cohort mismatch")

    baseline = profiles[execution.BASELINE.id]
    stress = profiles[execution.COST_2X.id]
    execution_checks = [
        profile[side]
        for profile in profiles.values()
        for side in ("candidate_execution", "control_execution")
    ]
    gates = {
        "baseline_cumulative_excess_positive": baseline["cumulative_excess"] > 0,
        "baseline_mean_ci_above_zero": bool(
            baseline["mean_monthly_excess_ci"]
            and baseline["mean_monthly_excess_ci"]["lo"] > 0
        ),
        "stress_cumulative_excess_positive": stress["cumulative_excess"] > 0,
        "drawdown_within_five_points_every_fold": bool(baseline["drawdown_pairs"])
        and baseline["worst_drawdown_difference"] >= -0.05,
        "execution_and_accounting_clean": all(
            check["all_folds_ok"]
            and check["n_rejected"] == 0
            and check["n_pending"] == 0
            and check["n_capacity_rejected"] == 0
            and check["missing_initial_assets"] == 0
            and check["missing_required_signal_prices"] == 0
            and check["state_rebuild_matches"]
            for check in execution_checks
        ) and all(profile["n_missing_paired_months"] == 0 for profile in profiles.values()),
    }
    return {
        "charter_id": CHARTER_ID,
        "paper_only": True,
        "automatic_action": "none",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profiles": profiles,
        "gates": gates,
        "decision": "PASS-HISTORICAL" if all(gates.values()) else "REJECT-V1",
    }


def render(report: dict) -> str:
    lines = [
        "# Fixed-ETF rebalancing premium — historical charter result",
        "",
        f"_Charter `{CHARTER_ID}` · decision **{report['decision']}** · paper only · "
        "no automatic action._",
        "",
        "This is one pre-registered candidate/control comparison, not a parameter sweep. "
        "A historical pass would permit only a new shadow-paper registration.",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    for name, passed in report["gates"].items():
        lines.append(f"| `{name}` | {'PASS' if passed else '**FAIL**'} |")
    lines.extend(["", "## Profile results", "",
                  "| Profile | Paired months | Candidate | Control | Cumulative excess | Mean excess/mo | 90% CI | Worst DD difference |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for profile_id in PROFILES:
        row = report["profiles"][profile_id]
        ci = row["mean_monthly_excess_ci"]
        ci_text = "·" if ci is None else f"[{pct(ci['lo'])}, {pct(ci['hi'])}]"
        lines.append(
            f"| `{profile_id}` | {row['n_paired_months']} | "
            f"{pct(row['cumulative_candidate_return'])} | "
            f"{pct(row['cumulative_control_return'])} | "
            f"{pct(row['cumulative_excess'])} | "
            f"{pct(row['mean_monthly_excess'])} | {ci_text} | "
            f"{pct(row['worst_drawdown_difference'])} |"
        )
    lines.extend([
        "",
        "A failure closes charter v1. It does not authorize asset substitution, cadence "
        "changes, threshold tuning, a new parameter grid, paper activation, or live capital.",
        "",
    ])
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result.json"
    md_path = out_dir / "README.md"
    resources.write_text_atomic(
        json_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    resources.write_text_atomic(md_path, render(report))
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", action="store_true", help="run all four frozen replays")
    parser.add_argument("--report-only", action="store_true", help="evaluate existing results")
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--scratch-root", default=str(SCRATCH_ROOT))
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.run == args.report_only:
        parser.error("choose exactly one of --run or --report-only")
    out_dir = Path(args.out_dir)
    if args.run:
        live = db.connect(args.db, read_only=True)
        try:
            run_replays(
                live, out_dir=out_dir, scratch_root=Path(args.scratch_root),
                threads=args.threads,
            )
        finally:
            live.close()
    for path in write_report(evaluate(load_results(out_dir)), out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
