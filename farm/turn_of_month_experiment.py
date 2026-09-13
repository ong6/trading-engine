#!/usr/bin/env python
"""Run and evaluate charter TURN-OF-MONTH-SPY-2026-09-07-v1.

Exactly four isolated walk-forward replays are permitted: one calendar-timing
candidate and one exposure-matched static control under baseline and doubled
costs. Nothing here registers a paper portfolio or opens a parameter grid.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DATA_DIR, REPO_ROOT
from farm import paired_walkforward as paired
from farm.walkforward import protocol, runner
from sim import execution
from sim.strategies import REGISTRY
from sim.strategies.turn_of_month_spy import (
    ASSETS,
    STATIC_SPY_WEIGHT,
    TurnOfMonthSpy,
    TurnOfMonthStaticExposure,
    is_turn_session,
)

CHARTER_ID = "TURN-OF-MONTH-SPY-2026-09-07-v1"
COMPARISON_PROTOCOL = "turn-of-month-spy-2026-09-07-v1"
CANDIDATE_ID = "turn_of_month_spy"
CONTROL_ID = "turn_of_month_static_1911"
ANCHOR = date(2026, 9, 4)
INITIAL_CASH = 39_000.0
PROFILES = (execution.BASELINE.id, execution.COST_2X.id)
OUT_DIR = DATA_DIR / "reports" / "experiments" / "turn-of-month-spy-v1"
SCRATCH_ROOT = REPO_ROOT / "scratch" / "turn-of-month-spy-v1"
DATA_CLASS = "fixed_etf_history"
RESEARCH_STRATEGIES = {
    CONTROL_ID: TurnOfMonthStaticExposure,
    CANDIDATE_ID: TurnOfMonthSpy,
}


def _config(config_id: str, profile_id: str) -> dict:
    candidate = config_id == CANDIDATE_ID
    return {
        "id": config_id,
        "name": ("Turn-of-Month SPY" if candidate
                 else "Static 19.1123% SPY / 80.8877% BIL"),
        "strategy": config_id,
        "cadence": "daily",
        "params": {
            "assets": list(ASSETS),
            "turn_window": "last NYSE session plus first three NYSE sessions",
            "static_spy_weight": STATIC_SPY_WEIGHT,
        },
        "charter_id": CHARTER_ID,
        "profile_id": profile_id,
        "description": (
            "Hold SPY over the four-session turn-of-month window, otherwise BIL."
            if candidate else
            "Hold a fixed exposure-matched SPY/BIL mix on candidate transition dates."
        ),
        "expectation": "Positive net calendar-timing excess over static exposure.",
        "kill_criterion": "Any failed charter gate closes v1.",
    }


def _book(config_id: str, profile_id: str) -> dict:
    config = _config(config_id, profile_id)
    return {
        "id": config_id,
        "name": config["name"],
        "strategy": config["strategy"],
        "config": config,
        "config_json": json.dumps(config, sort_keys=True),
        "excluded": None,
        "initial_cash": INITIAL_CASH,
        "execution_profile": profile_id,
        "data_quality_class": DATA_CLASS,
        "created": CHARTER_ID,
        "required_tickers": ASSETS,
        "verify_rebuild_state": True,
        "comparison": {
            "protocol": COMPARISON_PROTOCOL,
            "control_id": CONTROL_ID if config_id == CANDIDATE_ID else None,
            "evidence_role": "chartered_exploratory_historical_comparison",
        },
    }


def capture_price_input(live_con, _scratch_con, start, end, sessions) -> dict:
    """Fingerprint exact SPY/BIL bars and verify the frozen calendar exposure."""
    rows = live_con.execute(
        "SELECT ticker, date, open, high, low, close, volume, source "
        "FROM prices WHERE ticker IN ('SPY', 'BIL') AND date BETWEEN ? AND ? "
        "ORDER BY date, ticker", [start, end]
    ).fetchall()
    valid_dates: dict[date, set[str]] = {}
    payload = []
    for ticker, bar_date, open_px, high, low, close, volume, source in rows:
        payload.append([
            ticker, bar_date.isoformat(), open_px, high, low, close, volume, source,
        ])
        if open_px is not None and close is not None and open_px > 0 and close > 0:
            valid_dates.setdefault(bar_date, set()).add(ticker)
    missing = [
        d.isoformat() for d in sessions
        if valid_dates.get(d, set()) != set(ASSETS)
    ]
    turn_count = sum(is_turn_session(d) for d in sessions)
    return {
        "class": DATA_CLASS,
        "assets": list(ASSETS),
        "session_count": len(sessions),
        "turn_session_count": turn_count,
        "derived_spy_weight": turn_count / len(sessions) if sessions else None,
        "frozen_spy_weight": STATIC_SPY_WEIGHT,
        "missing_price_sessions": missing,
        "start": sessions[0].isoformat() if sessions else None,
        "end": sessions[-1].isoformat() if sessions else None,
        "sha256": canonical_sha256(payload),
    }


def run_replays(live_con, *, out_dir: Path = OUT_DIR,
                scratch_root: Path = SCRATCH_ROOT, threads: int = 4) -> None:
    collisions = sorted(RESEARCH_STRATEGIES.keys() & REGISTRY.keys())
    if collisions:
        raise RuntimeError(f"turn-of-month research strategies in registry: {collisions}")
    REGISTRY.update(RESEARCH_STRATEGIES)
    try:
        for profile_id in PROFILES:
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
                    results_dir=out_dir / profile_id / "results",
                    initial_cash=INITIAL_CASH,
                    execution_profile=profile_id,
                    scratch_prepare=capture_price_input,
                    threads=threads,
                )
    finally:
        for strategy_id, strategy_type in RESEARCH_STRATEGIES.items():
            if REGISTRY.get(strategy_id) is strategy_type:
                del REGISTRY[strategy_id]


def load_results(out_dir: Path = OUT_DIR) -> dict[str, dict[str, dict]]:
    return paired.load_results(out_dir, PROFILES, (CONTROL_ID, CANDIDATE_ID))


def _input_complete(result: dict) -> bool:
    value = result.get("research_input") or {}
    return bool(
        value.get("class") == DATA_CLASS
        and value.get("session_count") == 3019
        and value.get("turn_session_count") == 577
        and math.isclose(
            float(value.get("derived_spy_weight", -1)), STATIC_SPY_WEIGHT,
            rel_tol=0, abs_tol=1e-15,
        )
        and math.isclose(
            float(value.get("frozen_spy_weight", -1)), STATIC_SPY_WEIGHT,
            rel_tol=0, abs_tol=1e-15,
        )
        and not value.get("missing_price_sessions")
        and value.get("sha256")
    )


def evaluate(results: dict[str, dict[str, dict]]) -> dict:
    return paired.evaluate_experiment(
        results,
        profiles=PROFILES,
        candidate_id=CANDIDATE_ID,
        control_id=CONTROL_ID,
        charter_id=CHARTER_ID,
        input_complete=_input_complete,
        mean_block=4,
        pending_policy="symmetric_terminal",
    )


def render(report: dict) -> str:
    source = report["profiles"][execution.BASELINE.id]["research_input"] or {}
    return paired.render_experiment(
        report,
        charter_id=CHARTER_ID,
        title="Turn-of-month SPY — historical charter result",
        introduction=(
            "One frozen four-session calendar rule is compared with a static SPY/BIL "
            "control matched to its predeclared calendar exposure."
        ),
        data_boundary=(
            f"The input contains {source.get('session_count', 0):,} complete SPY/BIL "
            f"sessions from {source.get('start')} through {source.get('end')}; "
            f"{source.get('turn_session_count', 0):,} are in-window. Exact bar "
            f"fingerprint: `{source.get('sha256')}`."
        ),
        closing=(
            "A failed gate closes v1. A historical pass permits only a separately frozen "
            "shadow-paper comparison; neither outcome authorizes calendar tuning, "
            "automatic promotion, broker connectivity, or live capital."
        ),
        profiles=PROFILES,
    )


def write_report(report: dict, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    md_path, json_path = out_dir / "README.md", out_dir / "result.json"
    resources.write_text_atomic(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    resources.write_text_atomic(md_path, render(report))
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--report-only", action="store_true")
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--scratch-root", type=Path, default=SCRATCH_ROOT)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.run:
        live = db.connect(args.db, read_only=True)
        try:
            run_replays(live, out_dir=args.out_dir, scratch_root=args.scratch_root,
                        threads=args.threads)
        finally:
            live.close()
    md_path, json_path = write_report(evaluate(load_results(args.out_dir)), args.out_dir)
    print(f"[turn-of-month] wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
