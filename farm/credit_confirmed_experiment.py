#!/usr/bin/env python
"""Run frozen charter CREDIT-CONFIRMED-SPY-2026-09-18-v1."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DATA_DIR, REPO_ROOT
from engine.lib.util import pct
from farm.walkforward import monthly, protocol, runner
from sim import calendar, execution
from sim.strategies import REGISTRY
from sim.strategies.base import PortfolioView, Strategy, total_return
from sim.strategies.research_spy_bil import transition_orders

CHARTER_ID = "CREDIT-CONFIRMED-SPY-2026-09-18-v1"
COMPARISON_PROTOCOL = "credit-confirmed-spy-2026-09-18-v1"
CANDIDATE_ID = "credit_confirmed_spy_v1"
CONTROL_ID = "credit_confirmed_static_control_v1"
ANCHOR = date(2026, 9, 17)
INITIAL_CASH = 39_000.0
ASSETS = ("BIL", "HYG", "LQD", "SPY")
EQUITY_LOOKBACK = 252
CREDIT_LOOKBACK = 63
MINIMUM_EFFECT = 0.001
BOOTSTRAP_SEED = 20260918
EXPERIMENT_FOLDS = 18
SCENARIOS = {
    "baseline_v1": (execution.BASELINE.id, 0),
    "cost_2x_v1": (execution.COST_2X.id, 0),
    "delay_1_session_v1": (execution.BASELINE.id, 1),
}
OUT_DIR = DATA_DIR / "reports" / "experiments" / "credit-confirmed-spy-v1"
SCRATCH_ROOT = REPO_ROOT / "scratch" / "credit-confirmed-spy-v1"
CONTROL_TABLE = "credit_confirmed_fold_controls"
ACTION_COVERAGE_TABLE = "credit_confirmed_action_coverage"
DATA_CLASS = "fixed_etf_total_return_history"


def _decision_date(con, as_of: date, delay_sessions: int) -> date | None:
    if delay_sessions == 0:
        return as_of if calendar.is_month_signal(con, as_of) else None
    prior = con.execute(
        "SELECT MAX(date) FROM prices WHERE ticker = 'SPY' AND date < ?", [as_of]
    ).fetchone()[0]
    return prior if prior is not None and calendar.is_month_signal(con, prior) else None


def _signal(con, as_of: date) -> tuple[bool, dict]:
    values = {
        "spy_252": total_return(con, "SPY", as_of, EQUITY_LOOKBACK),
        "bil_252": total_return(con, "BIL", as_of, EQUITY_LOOKBACK),
        "hyg_63": total_return(con, "HYG", as_of, CREDIT_LOOKBACK),
        "lqd_63": total_return(con, "LQD", as_of, CREDIT_LOOKBACK),
    }
    return_complete = all(
        value is not None and math.isfinite(value) for value in values.values()
    )
    coverage = con.execute(
        f"SELECT ticker, fetched_on FROM {ACTION_COVERAGE_TABLE} ORDER BY ticker"
    ).fetchall()
    coverage_payload = [
        {"ticker": ticker, "fetched_on": fetched_on.isoformat()}
        for ticker, fetched_on in coverage
    ]
    action_coverage_complete = (
        {ticker for ticker, _fetched_on in coverage} == set(ASSETS)
        and all(fetched_on >= as_of for _ticker, fetched_on in coverage)
    )
    complete = return_complete and action_coverage_complete
    risk_on = bool(
        complete
        and values["spy_252"] > values["bil_252"]
        and values["hyg_63"] > values["lqd_63"]
    )
    return risk_on, {
        "date": as_of.isoformat(),
        "complete": complete,
        "return_complete": return_complete,
        "action_coverage_complete": action_coverage_complete,
        "action_coverage": coverage_payload,
        **values,
    }


def _orders(con, pf: PortfolioView, as_of: date, risk_weight: float):
    if not 0 <= risk_weight <= 1:
        raise ValueError("credit-confirmed risk weight is invalid")
    return transition_orders(
        con,
        pf,
        as_of,
        risk_on=risk_weight == 1.0,
        changed=True,
        static_spy_weight=risk_weight,
    )


class CreditConfirmedSpy(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        signal_date = _decision_date(
            con, as_of, int(pf.params.get("delay_sessions", 0))
        )
        if signal_date is None:
            return []
        risk_on, _facts = _signal(con, signal_date)
        return _orders(con, pf, as_of, float(risk_on))


class CreditConfirmedStaticControl(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of: date):
        if _decision_date(con, as_of, int(pf.params.get("delay_sessions", 0))) is None:
            return []
        created = con.execute(
            "SELECT created FROM portfolios WHERE id = ?", [pf.id]
        ).fetchone()
        row = None if created is None else con.execute(
            f"SELECT spy_weight FROM {CONTROL_TABLE} WHERE fold_start = ?",
            [created[0]],
        ).fetchone()
        if row is None:
            raise ValueError("credit-confirmed fold control is unavailable")
        return _orders(con, pf, as_of, float(row[0]))


RESEARCH_STRATEGIES = {
    CANDIDATE_ID: CreditConfirmedSpy,
    CONTROL_ID: CreditConfirmedStaticControl,
}


def _config(config_id: str, scenario: str) -> dict:
    candidate = config_id == CANDIDATE_ID
    profile, delay = SCENARIOS[scenario]
    return {
        "id": config_id,
        "name": "Credit-Confirmed SPY" if candidate else "Fold-Matched Static SPY/BIL",
        "strategy": config_id,
        "cadence": "daily",
        "params": {
            "assets": list(ASSETS),
            "equity_lookback": EQUITY_LOOKBACK,
            "credit_lookback": CREDIT_LOOKBACK,
            "delay_sessions": delay,
        },
        "charter_id": CHARTER_ID,
        "scenario": scenario,
        "profile_id": profile,
        "description": (
            "Monthly SPY/BIL trend requiring HYG/LQD credit confirmation."
            if candidate
            else "Monthly SPY/BIL mix matched to candidate mean fold exposure."
        ),
        "expectation": "Positive net timing excess over the fold-matched control.",
        "kill_criterion": "Any failed charter gate closes v1.",
    }


def _book(config_id: str, scenario: str) -> dict:
    config = _config(config_id, scenario)
    return {
        "id": config_id,
        "name": config["name"],
        "strategy": config_id,
        "config": config,
        "config_json": json.dumps(config, sort_keys=True),
        "excluded": None,
        "initial_cash": INITIAL_CASH,
        "execution_profile": SCENARIOS[scenario][0],
        "data_quality_class": DATA_CLASS,
        "created": CHARTER_ID,
        "required_tickers": ASSETS,
        "verify_rebuild_state": True,
        "comparison": {
            "protocol": COMPARISON_PROTOCOL,
            "control_id": CONTROL_ID if config_id == CANDIDATE_ID else None,
            "evidence_role": "chartered_exposure_matched_historical_comparison",
        },
    }


def prepare_inputs(live_con, scratch_con, start, end, sessions) -> dict:
    """Freeze exact signal facts and fold-specific diagnostic control weights."""
    floor = runner.data_floor(live_con, CANDIDATE_ID, ASSETS)
    coverage = live_con.execute(
        "SELECT ticker, MAX(fetched_on) FROM actions_fetch_log "
        "WHERE ticker IN ('BIL', 'HYG', 'LQD', 'SPY') AND status = 'ok' "
        "GROUP BY ticker ORDER BY ticker"
    ).fetchall()
    scratch_con.execute(
        f"CREATE TABLE {ACTION_COVERAGE_TABLE} "
        "(ticker VARCHAR PRIMARY KEY, fetched_on DATE)"
    )
    scratch_con.executemany(
        f"INSERT INTO {ACTION_COVERAGE_TABLE} VALUES (?, ?)", coverage
    )
    signals = {
        session: _signal(scratch_con, session)
        for session in sessions
        if calendar.is_month_signal(scratch_con, session)
    }
    scratch_con.execute(
        f"CREATE TABLE {CONTROL_TABLE} "
        "(fold_start DATE PRIMARY KEY, spy_weight DOUBLE)"
    )
    controls = []
    for fold in protocol.make_folds(ANCHOR, n_folds=EXPERIMENT_FOLDS):
        if fold.split_date <= floor:
            continue
        fold_start = max(fold.train_start, floor)
        start_session = next((item for item in sessions if item >= fold_start), None)
        validation = [
            risk_on
            for session, (risk_on, _facts) in signals.items()
            if fold.split_date <= session <= fold.validate_end
        ]
        if start_session is None or not validation:
            continue
        weight = sum(validation) / len(validation)
        controls.append([start_session, weight, len(validation)])
        scratch_con.execute(
            f"INSERT INTO {CONTROL_TABLE} VALUES (?, ?)", [start_session, weight]
        )
    facts = [details for _session, (_risk, details) in sorted(signals.items())]
    control_payload = [
        [row[0].isoformat(), row[1], row[2]] for row in controls
    ]
    return {
        "class": DATA_CLASS,
        "assets": list(ASSETS),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "session_count": len(sessions),
        "sessions_sha256": canonical_sha256(
            [session.isoformat() for session in sessions]
        ),
        "signal_count": len(facts),
        "complete_signal_count": sum(item["complete"] for item in facts),
        "incomplete_signal_dates": [
            item["date"] for item in facts if not item["complete"]
        ],
        "fold_controls": [
            {
                "fold_start": row[0].isoformat(),
                "spy_weight": row[1],
                "signal_count": row[2],
            }
            for row in controls
        ],
        "signal_facts_sha256": canonical_sha256(facts),
        "signal_facts": facts,
        "sha256": canonical_sha256(
            {"facts": facts, "controls": control_payload}
        ),
    }


def run_replays(
    live_con,
    *,
    out_dir: Path = OUT_DIR,
    scratch_root: Path = SCRATCH_ROOT,
    threads: int = 4,
) -> None:
    collisions = sorted(RESEARCH_STRATEGIES.keys() & REGISTRY.keys())
    if collisions:
        raise RuntimeError(
            f"credit-confirmed research strategies in registry: {collisions}"
        )
    REGISTRY.update(RESEARCH_STRATEGIES)
    try:
        for scenario, (profile, _delay) in SCENARIOS.items():
            for config_id in (CONTROL_ID, CANDIDATE_ID):
                runner.run_book(
                    live_con,
                    config_id,
                    book=_book(config_id, scenario),
                    anchor=ANCHOR,
                    n_folds=EXPERIMENT_FOLDS,
                    scratch_root=scratch_root / scenario,
                    results_dir=out_dir / scenario / "results",
                    initial_cash=INITIAL_CASH,
                    execution_profile=profile,
                    scratch_prepare=prepare_inputs,
                    threads=threads,
                )
    finally:
        for strategy_id, strategy_type in RESEARCH_STRATEGIES.items():
            if REGISTRY.get(strategy_id) is strategy_type:
                del REGISTRY[strategy_id]


def load_results(out_dir: Path = OUT_DIR) -> dict[str, dict[str, dict]]:
    return {
        scenario: {
            config_id: json.loads(
                (
                    out_dir
                    / scenario
                    / "results"
                    / f"{config_id}.json"
                ).read_text()
            )
            for config_id in (CONTROL_ID, CANDIDATE_ID)
        }
        for scenario in SCENARIOS
    }


def _folds(result: dict) -> dict[tuple, dict]:
    return {
        (fold["split_date"], fold["validate_end"]): fold
        for fold in result.get("folds", [])
        if fold.get("status") == "ok"
    }


def _scenario(candidate: dict, control: dict) -> dict:
    candidate_profile = candidate.get("execution_profile")
    control_profile = control.get("execution_profile")
    if (
        candidate.get("source_sha256") != control.get("source_sha256")
        or candidate.get("data_snapshot") != control.get("data_snapshot")
        or candidate.get("research_input") != control.get("research_input")
        or candidate.get("protocol") != control.get("protocol")
        or candidate.get("fill_model") != control.get("fill_model")
        or candidate_profile != control_profile
        or candidate.get("initial_cash") != control.get("initial_cash")
        or candidate.get("sessions") != control.get("sessions")
        or candidate.get("span_start") != control.get("span_start")
        or candidate.get("span_end") != control.get("span_end")
        or candidate.get("universe_policy") != control.get("universe_policy")
        or (candidate.get("config") or {}).get("scenario")
        != (control.get("config") or {}).get("scenario")
        or (candidate.get("config") or {}).get("params")
        != (control.get("config") or {}).get("params")
    ):
        raise ValueError("candidate/control research cohort mismatch")
    candidate_folds, control_folds = _folds(candidate), _folds(control)
    if candidate_folds.keys() != control_folds.keys():
        raise ValueError("candidate/control fold identity mismatch")
    rows = []
    drawdown_differences = []
    for key in sorted(candidate_folds.keys() & control_folds.keys()):
        left, right = candidate_folds[key], control_folds[key]
        left_months = dict(monthly.monthly_returns(left["validate_monthly_equity"]))
        right_months = dict(monthly.monthly_returns(right["validate_monthly_equity"]))
        if left_months.keys() != right_months.keys():
            raise ValueError("candidate/control monthly evidence mismatch")
        rows.extend(
            (left_months[month], right_months[month])
            for month in sorted(left_months)
        )
        drawdown_differences.append(
            left["validate"]["max_dd"] - right["validate"]["max_dd"]
        )
    excess = [left - right for left, right in rows]
    all_folds = [
        fold
        for result in (candidate, control)
        for fold in result.get("folds", [])
    ]
    clean = (
        len(candidate_folds) == len(control_folds) == EXPERIMENT_FOLDS
        and all(fold.get("status") == "ok" for fold in all_folds)
        and all(int(fold.get("n_rejected") or 0) == 0 for fold in all_folds)
        and all(int(fold.get("n_pending") or 0) == 0 for fold in all_folds)
        and all(
            int(fold.get("n_capacity_rejected") or 0) == 0
            for fold in all_folds
        )
        and all(
            fold.get("state_rebuild_matches") is True for fold in all_folds
        )
        and not (candidate.get("research_input") or {}).get("incomplete_signal_dates")
    )
    candidate_growth = math.prod(1 + left for left, _right in rows)
    control_growth = math.prod(1 + right for _left, right in rows)
    return {
        "paired_months": len(rows),
        "candidate_return": candidate_growth - 1,
        "control_return": control_growth - 1,
        "cumulative_excess": candidate_growth - control_growth,
        "mean_monthly_excess": sum(excess) / len(excess) if excess else None,
        "mean_monthly_excess_ci": monthly.block_bootstrap_ci(
            excess,
            stat="mean",
            mean_block=4,
            n_boot=10_000,
            seed=BOOTSTRAP_SEED,
        ),
        "worst_drawdown_difference": min(drawdown_differences, default=None),
        "clean": clean,
        "source_sha256": candidate.get("source_sha256"),
        "data_snapshot_sha256": (candidate.get("data_snapshot") or {}).get("sha256"),
        "research_input": candidate.get("research_input"),
        "execution_profile": candidate_profile,
        "initial_cash": candidate.get("initial_cash"),
        "protocol": candidate.get("protocol"),
    }


def evaluate(results: dict[str, dict[str, dict]]) -> dict:
    scenarios = {
        name: _scenario(values[CANDIDATE_ID], values[CONTROL_ID])
        for name, values in results.items()
    }
    identities = {
        (
            row["source_sha256"],
            row["data_snapshot_sha256"],
            (row["research_input"] or {}).get("sha256"),
        )
        for row in scenarios.values()
    }
    if len(identities) != 1:
        raise ValueError("scenario research cohort mismatch")
    baseline = scenarios["baseline_v1"]
    gates = {
        "baseline_cumulative_excess_positive": baseline["cumulative_excess"] > 0,
        "baseline_minimum_effect_met": (
            baseline["mean_monthly_excess"] is not None
            and baseline["mean_monthly_excess"] >= MINIMUM_EFFECT
        ),
        "baseline_mean_ci_above_zero": bool(
            baseline["mean_monthly_excess_ci"]
            and baseline["mean_monthly_excess_ci"]["lo"] > 0
        ),
        "cost_stress_excess_positive": (
            scenarios["cost_2x_v1"]["cumulative_excess"] > 0
        ),
        "delay_stress_excess_positive": (
            scenarios["delay_1_session_v1"]["cumulative_excess"] > 0
        ),
        "drawdown_within_five_points_every_fold": (
            baseline["worst_drawdown_difference"] is not None
            and baseline["worst_drawdown_difference"] >= -0.05
        ),
        "execution_data_and_accounting_clean": all(
            row["clean"] for row in scenarios.values()
        ),
    }
    return {
        "charter_id": CHARTER_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paper_only": True,
        "automatic_action": "none",
        "scenarios": scenarios,
        "gates": gates,
        "decision": "PASS-HISTORICAL" if all(gates.values()) else "REJECT-V1",
    }


def render(report: dict) -> str:
    lines = [
        "# Credit-confirmed equity trend — historical result",
        "",
        f"Charter {CHARTER_ID} · decision {report['decision']} · "
        "paper only · no automatic action.",
        "",
        "One frozen candidate is compared with its per-fold exposure-matched "
        "SPY/BIL control. No grid or alternate parameter was run.",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines.extend(
        f"| {name} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in report["gates"].items()
    )
    lines.extend(
        [
            "",
            "## Scenarios",
            "",
            "| Scenario | Months | Candidate | Control | Excess | Mean excess/mo | 90% CI |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, row in report["scenarios"].items():
        ci = row["mean_monthly_excess_ci"]
        ci_text = "·" if ci is None else f"[{pct(ci['lo'])}, {pct(ci['hi'])}]"
        lines.append(
            f"| {name} | {row['paired_months']} | "
            f"{pct(row['candidate_return'])} | {pct(row['control_return'])} | "
            f"{pct(row['cumulative_excess'])} | "
            f"{pct(row['mean_monthly_excess'])} | {ci_text} |"
        )
    lines.extend(
        [
            "",
            "A failed gate closes v1 without tuning. A pass permits only a "
            "separately frozen prospective paper comparison.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    md_path, json_path = out_dir / "README.md", out_dir / "result.json"
    resources.write_text_atomic(
        json_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
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
            run_replays(
                live,
                out_dir=args.out_dir,
                scratch_root=args.scratch_root,
                threads=args.threads,
            )
        finally:
            live.close()
    md_path, json_path = write_report(
        evaluate(load_results(args.out_dir)), args.out_dir
    )
    print(f"[credit-confirmed] wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
