"""Pure paired-policy and historical contamination analysis helpers."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from engine.lib.util import table_exists


def mean(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)
def signed_return(row: dict) -> float:
    if row["action"] == "buy":
        return float(row["asset_return"])
    if row["action"] == "sell":
        return -float(row["asset_return"])
    return 0.0
def expected_windows(start: datetime, end: datetime, sessions: list,
                     variants: list[dict]) -> set[str]:
    result = set()
    session_set = set(sessions)
    for item in variants:
        variant_start = start
        if item.get("evaluation_start_at"):
            variant_start = max(
                start,
                datetime.fromisoformat(
                    item["evaluation_start_at"].replace("Z", "+00:00")
                ).astimezone(timezone.utc),
            )
        if item["id"] == "nightly_opportunity_tool_v1":
            for session in sessions:
                hour, minute = map(int, item["scheduled_local_times"][0].split(":"))
                due = datetime.combine(session + timedelta(days=1), time(hour, minute), timezone.utc)
                if variant_start <= due <= end:
                    result.add(f"nightly:{session.isoformat()}")
            continue
        if item.get("cadence") not in {"hourly", "four_hour"}:
            continue
        zone = ZoneInfo(item["timezone"])
        local_day = start.astimezone(zone).date()
        while local_day <= end.astimezone(zone).date():
            if local_day in session_set:
                for raw_time in item["scheduled_local_times"]:
                    hour, minute = map(int, raw_time.split(":"))
                    due = datetime.combine(local_day, time(hour, minute), zone).astimezone(timezone.utc)
                    if variant_start <= due <= end:
                        bucket = due.hour if item["cadence"] == "hourly" else due.hour // 4 * 4
                        result.add(f"{item['id']}:{due.date().isoformat()}T{bucket:02d}")
            local_day += timedelta(days=1)
    return result
def coverage(con: duckdb.DuckDBPyConnection, rows: list[dict], generated_at: datetime,
             registration_path: Path, horizons: tuple[int, ...]) -> dict:
    decisions = con.execute(
        "SELECT d.id,t.market_date,t.cadence,t.observed_at,d.decision "
        "FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id ORDER BY d.id"
    ).fetchall() if table_exists(con, "agent_evaluation_decisions") else []
    prices_ready = table_exists(con, "prices")
    latest = con.execute("SELECT MAX(date) FROM prices WHERE ticker='SPY'").fetchone()[0] if prices_ready else None
    mature_expected = 0
    if latest is not None:
        for _decision_id, market_date, cadence, observed_at, decision in decisions:
            if decision == "unavailable":
                continue
            boundary = market_date if cadence == "nightly" else observed_at.date()
            count = int(con.execute(
                "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' AND date>? AND date<=?",
                [boundary, latest],
            ).fetchone()[0])
            mature_expected += sum(count >= horizon for horizon in horizons)
    available = sum(row[4] != "unavailable" for row in decisions)
    actual, possible = sum(row["horizon"] is not None for row in rows), available * len(horizons)
    try:
        registration = json.loads(registration_path.read_text())
        start = datetime.fromisoformat(
            registration["evaluation_start_at"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        sessions = [row[0] for row in con.execute(
            "SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? AND date<? ORDER BY date",
            [start.date(), generated_at.date()]).fetchall()] if prices_ready else []
        expected = expected_windows(start, generated_at, sessions, registration["variants"])
        missing = sorted(expected - {row["window_id"] for row in rows})
        status = "complete" if not missing else "incomplete"
    except (KeyError, OSError, TypeError, ValueError, duckdb.Error):
        expected, missing, status = set(), [], "invalid"
    return {
        "trace_count": len({row["window_id"] for row in rows}),
        "decision_count": len(decisions), "available_decision_count": available,
        "unavailable_decision_count": len(decisions) - available, "label_count": actual,
        "mature_expected_label_count": mature_expected,
        "missing_mature_label_count": max(0, mature_expected - actual),
        "immature_label_count": max(0, possible - mature_expected),
        "scheduled_window_status": status, "expected_window_count": len(expected),
        "observed_expected_window_count": len(expected) - len(missing),
        "missing_window_count": len(missing), "missing_windows": missing[:100],
        "missing_windows_truncated": len(missing) > 100,
    }
def _pair_groups(rows: list[dict], policy: str) -> tuple[dict, int]:
    grouped = {}
    duplicates = 0
    seen_windows = set()
    for row in rows:
        if row["policy_id"] != policy or row["horizon"] is None:
            continue
        identity = (row["window_id"], row["ticker"], row["horizon"], row["label_basis"])
        if identity in seen_windows:
            duplicates += 1
            continue
        seen_windows.add(identity)
        key = (row["market_date"], row["ticker"], row["horizon"], row["label_basis"])
        grouped.setdefault(key, []).append(row)
    for values in grouped.values():
        values.sort(key=lambda item: item["window_id"])
    return grouped, duplicates


def paired_metrics(
    rows: list[dict],
    policies: tuple | dict,
    *,
    window_scope: str = "first",
) -> list[dict]:
    if window_scope not in {"first", "all"}:
        raise ValueError("pairing window scope is invalid")
    cadences = (
        dict(policies)
        if isinstance(policies, dict)
        else {
            policy: next(
                (row["cadence"] for row in rows if row["policy_id"] == policy),
                "unknown",
            )
            for policy in policies
        }
    )
    by_policy = {policy: _pair_groups(rows, policy) for policy in policies}
    result = []
    for left, right in itertools.combinations(policies, 2):
        left_cadence, right_cadence = cadences[left], cadences[right]
        if "nightly" not in {left_cadence, right_cadence}:
            continue
        left_rows, left_ambiguous = by_policy[left]
        right_rows, right_ambiguous = by_policy[right]
        keys = sorted(set(left_rows) & set(right_rows))
        comparisons = []
        for key in keys:
            left_values, right_values = left_rows[key], right_rows[key]
            if window_scope == "first":
                comparisons.append((left_values[0], right_values[0]))
            elif left_cadence == "nightly":
                comparisons.extend((left_values[0], item) for item in right_values)
            else:
                comparisons.extend((item, right_values[0]) for item in left_values)
        shared = [pair for pair in comparisons
                  if pair[0]["price_prefix_sha256"] == pair[1]["price_prefix_sha256"]]
        deltas = [signed_return(left_row) - signed_return(right_row)
                  for left_row, right_row in shared]
        result.append({
            "left_policy": left, "right_policy": right, "window_scope": window_scope,
            "paired_count": len(shared),
            "left_missing_count": len(set(right_rows) - set(left_rows)),
            "right_missing_count": len(set(left_rows) - set(right_rows)),
            "left_ambiguous_count": left_ambiguous,
            "right_ambiguous_count": right_ambiguous,
            "incompatible_outcome_count": len(comparisons) - len(shared),
            "same_input_count": sum(left_row["input_sha256"] == right_row["input_sha256"]
                                    for left_row, right_row in shared),
            "same_source_set_count": sum(
                left_row["source_refs_sha256"] == right_row["source_refs_sha256"]
                for left_row, right_row in shared
            ),
            "left_wins": sum(value > 0 for value in deltas),
            "ties": sum(value == 0 for value in deltas),
            "right_wins": sum(value < 0 for value in deltas),
            "mean_signed_return_delta": mean(deltas),
        })
    return result
def contamination_diagnostics(paths: tuple[Path, ...]) -> dict:
    probes = {name: "not_run" for name in ("named_vs_blinded", "date_recall",
        "synthetic_perturbation", "prompt_permutation", "post_cutoff_prospective")}
    available = [path for path in paths if path.exists()]
    if not available:
        return {"status": "unavailable", "promotion_authority": "none",
                "probes": probes, "known_contamination": []}
    payloads = [json.loads(path.read_text()) for path in available]
    rows = [row for payload in payloads for row in payload.get("results", [])]
    named = {row["decision_date"]: row for row in rows if row.get("variant") == "price_named"}
    blinded = {row["decision_date"]: row for row in rows if row.get("variant") == "price_blinded"}
    dates = sorted(set(named) & set(blinded))
    probes["named_vs_blinded"] = "complete" if dates else "not_run"
    variants = {row.get("variant") for row in rows}
    probes["date_recall"] = "complete" if "price_date_recall" in variants else "not_run"
    probes["synthetic_perturbation"] = (
        "complete" if "price_synthetic_perturbed" in variants else "not_run"
    )
    probes["prompt_permutation"] = "complete" if "price_permuted" in variants else "not_run"
    probes["post_cutoff_prospective"] = "collecting"
    comparisons = {}
    for variant in ("price_blinded", "price_date_recall", "price_permuted",
                    "price_synthetic_perturbed"):
        other = {row["decision_date"]: row for row in rows if row.get("variant") == variant}
        shared = sorted(set(named) & set(other))
        comparisons[variant] = {
            "paired_dates": len(shared),
            "choice_agreement": mean([float(named[d]["selected_ticker"] ==
                                            other[d]["selected_ticker"]) for d in shared]),
            "direction_agreement": mean([float(named[d]["decision"]["direction"] ==
                                               other[d]["decision"]["direction"]) for d in shared]),
        }
    return {
        "status": "diagnostic_only", "promotion_authority": "none",
        "interpretation": "contaminated_retrospective_diagnostic_only",
        "known_contamination": sorted({item for payload in payloads
                                        for item in payload.get("known_contamination", [])}),
        "artifacts": [path.parent.name for path in available], "probes": probes,
        "variant_comparisons": comparisons,
        "paired_dates": len(dates),
        "choice_agreement": mean([float(named[d]["selected_ticker"]
                                        == blinded[d]["selected_ticker"]) for d in dates]),
        "direction_agreement": mean([float(named[d]["decision"]["direction"]
                                           == blinded[d]["decision"]["direction"]) for d in dates]),
        "mean_confidence_delta": mean([abs(float(named[d]["decision"]["confidence"])
                                               - float(blinded[d]["decision"]["confidence"]))
                                       for d in dates]),
        "mean_forecast_delta_pct": mean([abs(float(named[d]["decision"]["expected_return_pct"])
                                                 - float(blinded[d]["decision"]["expected_return_pct"]))
                                         for d in dates]),
    }
