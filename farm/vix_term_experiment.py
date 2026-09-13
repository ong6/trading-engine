#!/usr/bin/env python
"""Run and evaluate charter VIX-TERM-SPY-2026-09-07-v1.

Exactly four isolated walk-forward replays are permitted: one VIX-term candidate
and one exposure-matched static control under baseline and doubled costs. The
public macro history is reconstructed only inside each scratch database.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DATA_DIR, REPO_ROOT
from farm import paired_walkforward as paired
from farm.walkforward import protocol, runner
from sim import execution
from sim.strategies import REGISTRY
from sim.strategies.vix_term_spy_timing import (
    ASSETS,
    CONTANGO_THRESHOLD,
    STATIC_SPY_WEIGHT,
    VixTermSpyTiming,
    VixTermStaticExposure,
)

CHARTER_ID = "VIX-TERM-SPY-2026-09-07-v1"
COMPARISON_PROTOCOL = "vix-term-spy-2026-09-07-v1"
CANDIDATE_ID = "vix_term_spy_timing"
CONTROL_ID = "vix_term_static_8068"
ANCHOR = date(2026, 9, 3)
INITIAL_CASH = 39_000.0
PROFILES = (execution.BASELINE.id, execution.COST_2X.id)
OUT_DIR = DATA_DIR / "reports" / "experiments" / "vix-term-spy-v1"
SCRATCH_ROOT = REPO_ROOT / "scratch" / "vix-term-spy-v1"
DATA_CLASS = "reconstructed_public_eod_macro_history"
RESEARCH_STRATEGIES = {
    CONTROL_ID: VixTermStaticExposure,
    CANDIDATE_ID: VixTermSpyTiming,
}


def _config(config_id: str, profile_id: str) -> dict:
    candidate = config_id == CANDIDATE_ID
    return {
        "id": config_id,
        "name": ("VIX-Term SPY Timing" if candidate
                 else "Static 80.6845% SPY / 19.3155% BIL"),
        "strategy": config_id,
        "cadence": "daily",
        "params": {
            "assets": list(ASSETS),
            "contango_threshold": CONTANGO_THRESHOLD,
            "static_spy_weight": STATIC_SPY_WEIGHT,
        },
        "charter_id": CHARTER_ID,
        "profile_id": profile_id,
        "description": (
            "Hold SPY after VIX/VIX3M closes below 0.95, otherwise BIL."
            if candidate else
            "Hold a fixed exposure-matched SPY/BIL mix on candidate transition dates."
        ),
        "expectation": "Positive net timing excess over the static exposure control.",
        "kill_criterion": "Any failed charter gate closes v1.",
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
        "data_quality_class": DATA_CLASS,
        "created": CHARTER_ID,
        "required_tickers": ASSETS,
        "verify_rebuild_state": True,
        "comparison": {
            "protocol": COMPARISON_PROTOCOL,
            "control_id": CONTROL_ID if config_id == CANDIDATE_ID else None,
            "evidence_role": "chartered_exploratory_reconstructed_history",
        },
    }


def prepare_reconstructed_macro(live_con, scratch_con, start, end, sessions) -> dict:
    """Copy exact-date VIX pairs into scratch with close-time availability."""
    rows = live_con.execute(
        "SELECT v.obs_date, v.value, m.value FROM macro_signals v "
        "JOIN macro_signals m ON m.obs_date = v.obs_date "
        "WHERE v.series = 'vix' AND m.series = 'vix3m' "
        "AND v.obs_date BETWEEN ? AND ? AND v.value > 0 AND m.value > 0 "
        "ORDER BY v.obs_date",
        [start, end],
    ).fetchall()
    by_date = {row[0]: (float(row[1]), float(row[2])) for row in rows}
    missing_macro = sorted(d for d in sessions if d not in by_date)
    priced = {
        row[0]: int(row[1])
        for row in live_con.execute(
            "SELECT date, COUNT(DISTINCT ticker) FROM prices "
            "WHERE date BETWEEN ? AND ? AND ticker IN ('SPY', 'BIL') "
            "AND close > 0 GROUP BY date", [start, end]
        ).fetchall()
    }
    missing_prices = sorted(d for d in sessions if priced.get(d) != len(ASSETS))
    payload = [
        [d.isoformat(), by_date[d][0], by_date[d][1]]
        for d in sorted(by_date)
    ]

    db.init_signals_schema(scratch_con)
    scratch_con.execute("DELETE FROM macro_signals")
    scratch_rows = [
        ("vix", d, vix, d) for d, vix, _vix3m in rows
    ] + [
        ("vix3m", d, vix3m, d) for d, _vix, vix3m in rows
    ]
    scratch_con.executemany(
        "INSERT INTO macro_signals (series, obs_date, value, fetch_as_of) "
        "VALUES (?, ?, ?, ?)", scratch_rows,
    )
    return {
        "class": DATA_CLASS,
        "reconstruction": "fetch_as_of equals obs_date in scratch only",
        "pair_count": len(rows),
        "session_count": len(sessions),
        "missing_macro_sessions": [d.isoformat() for d in missing_macro],
        "missing_price_sessions": [d.isoformat() for d in missing_prices],
        "start": rows[0][0].isoformat() if rows else None,
        "end": rows[-1][0].isoformat() if rows else None,
        "sha256": canonical_sha256(payload),
    }


def run_replays(live_con, *, out_dir: Path = OUT_DIR,
                scratch_root: Path = SCRATCH_ROOT, threads: int = 4) -> None:
    collisions = sorted(RESEARCH_STRATEGIES.keys() & REGISTRY.keys())
    if collisions:
        raise RuntimeError(f"VIX research strategies in production registry: {collisions}")
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
                    scratch_prepare=prepare_reconstructed_macro,
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
        and value.get("pair_count") == value.get("session_count")
        and not value.get("missing_macro_sessions")
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
        pending_policy="none",
    )


def render(report: dict) -> str:
    source = report["profiles"][execution.BASELINE.id]["research_input"] or {}
    return paired.render_experiment(
        report,
        charter_id=CHARTER_ID,
        title="VIX-term SPY timing — historical charter result",
        introduction=(
            "One fixed VIX/VIX3M threshold is compared with a static SPY/BIL control "
            "matched to the signal's predeclared average equity exposure."
        ),
        data_boundary=(
            f"The isolated reconstruction contains {source.get('pair_count', 0):,} "
            f"joined VIX/VIX3M sessions from {source.get('start')} through "
            f"{source.get('end')} (SHA-256 `{source.get('sha256')}`). Production macro "
            "history was not changed."
        ),
        closing=(
            "A failed gate closes v1. A historical pass permits only a separately frozen "
            "shadow-paper comparison; neither outcome authorizes parameter tuning, "
            "automatic promotion, broker connectivity, or live capital."
        ),
        profiles=PROFILES,
    )


def write_report(report: dict, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    json_path = out_dir / "result.json"
    md_path = out_dir / "README.md"
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
    print(f"[vix-term] wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
