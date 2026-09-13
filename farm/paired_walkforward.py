"""Shared fail-closed helpers for isolated paired walk-forward experiments."""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.util import pct
from farm.walkforward import monthly, protocol
from sim import execution

GATE_ORDER = (
    "baseline_cumulative_excess_positive",
    "baseline_mean_ci_above_zero",
    "stress_cumulative_excess_positive",
    "drawdown_within_five_points_every_fold",
    "execution_data_and_accounting_clean",
)


def result_path(out_dir: Path, profile_id: str, config_id: str) -> Path:
    return out_dir / profile_id / "results" / f"{config_id}.json"


def load_results(out_dir: Path, profiles: tuple[str, ...],
                 config_ids: tuple[str, ...]) -> dict[str, dict[str, dict]]:
    return {
        profile: {
            config_id: json.loads(result_path(out_dir, profile, config_id).read_text())
            for config_id in config_ids
        }
        for profile in profiles
    }


def signature(result: dict, *, include_research_input: bool = False) -> tuple:
    profile = result.get("execution_profile")
    snapshot = result.get("data_snapshot")
    comparison = result.get("comparison")
    values = (
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
    if include_research_input:
        values += (json.dumps(result.get("research_input"), sort_keys=True),)
    return values


def without_execution_profile(value: tuple) -> tuple:
    """Remove signature field 4 when comparing baseline with stress runs."""
    return value[:4] + value[5:]


def folds(result: dict) -> dict[tuple, dict]:
    return {
        (fold.get("split_date"), fold.get("validate_end")): fold
        for fold in result.get("folds", [])
        if fold.get("status") == "ok"
    }


def complete_folds(result: dict) -> dict[tuple, dict] | None:
    """Return the exact frozen fold set, or ``None`` for malformed geometry."""
    raw_folds = result.get("folds")
    if not isinstance(raw_folds, list) or len(raw_folds) != protocol.N_FOLDS:
        return None
    if any(not isinstance(fold, dict) or fold.get("status") != "ok"
           for fold in raw_folds):
        return None
    mapped = folds(result)
    if len(mapped) != protocol.N_FOLDS:
        return None
    try:
        indices = {int(fold.get("index")) for fold in raw_folds}
    except (TypeError, ValueError):
        return None
    if indices != set(range(1, protocol.N_FOLDS + 1)):
        return None
    return mapped


def paired_months(candidate: dict, control: dict) -> tuple[list[dict], int]:
    candidate_folds, control_folds = folds(candidate), folds(control)
    rows: list[dict] = []
    missing = 0
    for key in sorted(candidate_folds.keys() | control_folds.keys()):
        candidate_fold = candidate_folds.get(key)
        control_fold = control_folds.get(key)
        if candidate_fold is None or control_fold is None:
            missing += 1
            continue
        candidate_months = dict(monthly.monthly_returns(
            candidate_fold["validate_monthly_equity"]
        ))
        control_months = dict(monthly.monthly_returns(
            control_fold["validate_monthly_equity"]
        ))
        missing += len(candidate_months.keys() ^ control_months.keys())
        for month in sorted(candidate_months.keys() & control_months.keys()):
            rows.append({
                "fold": candidate_fold.get("index"),
                "month": month,
                "candidate": candidate_months[month],
                "control": control_months[month],
                "excess": candidate_months[month] - control_months[month],
            })
    return rows, missing


def execution_check(result: dict) -> dict:
    complete = complete_folds(result)
    good_folds = list(complete.values()) if complete is not None else []
    return {
        "all_folds_ok": complete is not None,
        "n_rejected": sum(int(fold.get("n_rejected") or 0) for fold in good_folds),
        "n_pending": sum(int(fold.get("n_pending") or 0) for fold in good_folds),
        "n_capacity_rejected": sum(
            int(fold.get("n_capacity_rejected") or 0) for fold in good_folds
        ),
        "state_rebuild_matches": bool(good_folds) and all(
            fold.get("state_rebuild_matches") is True for fold in good_folds
        ),
    }


def terminal_pending_clean(candidate: dict, control: dict) -> bool:
    """Allow only symmetric intents emitted on a fold's final replay session."""
    candidate_folds = complete_folds(candidate)
    control_folds = complete_folds(control)
    if candidate_folds is None or control_folds is None:
        return False
    if candidate_folds.keys() != control_folds.keys():
        return False
    for key in candidate_folds:
        candidate_fold, control_fold = candidate_folds[key], control_folds[key]
        candidate_pending = candidate_fold.get("pending_orders") or []
        control_pending = control_fold.get("pending_orders") or []
        if int(candidate_fold.get("n_pending") or 0) != len(candidate_pending):
            return False
        if int(control_fold.get("n_pending") or 0) != len(control_pending):
            return False
        if len(candidate_pending) != len(control_pending):
            return False
        for fold, pending in (
            (candidate_fold, candidate_pending), (control_fold, control_pending)
        ):
            if any(order.get("signal_date") != fold.get("last_session")
                   for order in pending):
                return False
    return True


def evaluate_experiment(
    results: dict[str, dict[str, dict]],
    *,
    profiles: tuple[str, ...],
    candidate_id: str,
    control_id: str,
    charter_id: str,
    input_complete: Callable[[dict], bool],
    mean_block: int,
    pending_policy: str,
    seed: int = 20260907,
) -> dict:
    """Evaluate one frozen candidate/control experiment under common gates."""
    if pending_policy not in {"none", "symmetric_terminal"}:
        raise ValueError(f"unknown pending policy: {pending_policy}")
    profile_results: dict[str, dict] = {}
    cross_profile = set()
    for profile_id in profiles:
        candidate = results[profile_id][candidate_id]
        control = results[profile_id][control_id]
        candidate_signature = signature(candidate, include_research_input=True)
        if candidate_signature != signature(control, include_research_input=True):
            raise ValueError(f"{profile_id}: candidate/control research cohort mismatch")
        if (candidate.get("execution_profile") or {}).get("id") != profile_id:
            raise ValueError(f"{profile_id}: candidate profile stamp mismatch")
        cross_profile.add(without_execution_profile(candidate_signature))

        rows, missing_months = paired_months(candidate, control)
        excess = [row["excess"] for row in rows]
        mean_ci = monthly.block_bootstrap_ci(
            excess, stat="mean", mean_block=mean_block, n_boot=10_000, seed=seed
        )
        candidate_growth = math.prod(1.0 + row["candidate"] for row in rows)
        control_growth = math.prod(1.0 + row["control"] for row in rows)
        candidate_folds = folds(candidate)
        control_folds = folds(control)
        drawdowns = []
        for key in sorted(candidate_folds.keys() & control_folds.keys()):
            candidate_dd = (candidate_folds[key].get("validate") or {}).get("max_dd")
            control_dd = (control_folds[key].get("validate") or {}).get("max_dd")
            if candidate_dd is not None and control_dd is not None:
                drawdowns.append(candidate_dd - control_dd)
        row = {
            "n_paired_months": len(rows),
            "n_missing_paired_months": missing_months,
            "mean_monthly_excess": sum(excess) / len(excess) if excess else None,
            "mean_monthly_excess_ci": mean_ci,
            "cumulative_candidate_return": candidate_growth - 1.0,
            "cumulative_control_return": control_growth - 1.0,
            "cumulative_excess": candidate_growth - control_growth,
            "worst_drawdown_difference": min(drawdowns, default=None),
            "candidate_execution": execution_check(candidate),
            "control_execution": execution_check(control),
            "input_complete": input_complete(candidate) and input_complete(control),
            "research_input": candidate.get("research_input"),
            "execution_profile": candidate.get("execution_profile"),
            "drawdown_fold_count": len(drawdowns),
        }
        if pending_policy == "symmetric_terminal":
            row["terminal_pending_clean"] = terminal_pending_clean(candidate, control)
        profile_results[profile_id] = row

    if len(cross_profile) != 1:
        raise ValueError("baseline/stress research cohort mismatch")
    baseline = profile_results[execution.BASELINE.id]
    stress = profile_results[execution.COST_2X.id]
    checks = [
        profile[side]
        for profile in profile_results.values()
        for side in ("candidate_execution", "control_execution")
    ]
    clean = all(
        check["all_folds_ok"] and check["n_rejected"] == 0
        and check["n_capacity_rejected"] == 0 and check["state_rebuild_matches"]
        and (pending_policy != "none" or check["n_pending"] == 0)
        for check in checks
    ) and all(
        profile["input_complete"] and profile["n_missing_paired_months"] == 0
        and (
            pending_policy != "symmetric_terminal"
            or profile["terminal_pending_clean"]
        )
        for profile in profile_results.values()
    )
    gates = {
        "baseline_cumulative_excess_positive": baseline["cumulative_excess"] > 0,
        "baseline_mean_ci_above_zero": bool(
            baseline["mean_monthly_excess_ci"]
            and baseline["mean_monthly_excess_ci"]["lo"] > 0
        ),
        "stress_cumulative_excess_positive": stress["cumulative_excess"] > 0,
        "drawdown_within_five_points_every_fold": (
            baseline["drawdown_fold_count"] == protocol.N_FOLDS
            and baseline["worst_drawdown_difference"] is not None
            and baseline["worst_drawdown_difference"] >= -0.05
        ),
        "execution_data_and_accounting_clean": clean,
    }
    for profile in profile_results.values():
        del profile["drawdown_fold_count"]
    return {
        "charter_id": charter_id,
        "paper_only": True,
        "automatic_action": "none",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profiles": profile_results,
        "gates": gates,
        "decision": "PASS-HISTORICAL" if all(gates.values()) else "REJECT-V1",
    }


def render_experiment(
    report: dict,
    *,
    charter_id: str,
    title: str,
    introduction: str,
    data_boundary: str,
    closing: str,
    profiles: tuple[str, ...],
) -> str:
    """Render the common paired-experiment decision table and supplied context."""
    lines = [
        f"# {title}", "",
        f"_Charter `{charter_id}` · decision **{report['decision']}** · paper only · "
        "no automatic action._", "",
        introduction, "",
        "## Gates", "", "| Gate | Result |", "|---|---|",
    ]
    for name in GATE_ORDER:
        passed = report["gates"][name]
        lines.append(f"| `{name}` | {'PASS' if passed else '**FAIL**'} |")
    lines.extend([
        "", "## Profile results", "",
        "| Profile | Paired months | Candidate | Control | Cumulative excess | Mean excess/mo | 90% CI | Worst DD difference |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for profile_id in profiles:
        row = report["profiles"][profile_id]
        ci = row["mean_monthly_excess_ci"]
        ci_text = "·" if ci is None else f"[{pct(ci['lo'])}, {pct(ci['hi'])}]"
        lines.append(
            f"| `{profile_id}` | {row['n_paired_months']} | "
            f"{pct(row['cumulative_candidate_return'])} | "
            f"{pct(row['cumulative_control_return'])} | "
            f"{pct(row['cumulative_excess'])} | {pct(row['mean_monthly_excess'])} | "
            f"{ci_text} | {pct(row['worst_drawdown_difference'])} |"
        )
    lines.extend(["", "## Data boundary", "", data_boundary, "", closing, ""])
    return "\n".join(lines)
