"""Deterministic scoring and contamination diagnostics for canonical agent traces."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.util import table_exists
from farm.agent_evaluation_analysis import (
    contamination_diagnostics,
    coverage,
    paired_metrics,
    signed_return,
)

from .agent_evaluation import HORIZONS, POLICIES

SCHEMA_VERSION = 1
DEFAULT_OUTPUT = REPO_ROOT / "data" / "reports" / "agent-evaluation.json"
DEFAULT_CONTAMINATION = (REPO_ROOT / "data" / "reports" / "experiments"
                         / "agent-2022-replay-v1" / "result.json")
DEFAULT_CONTAMINATION_PROBES = (REPO_ROOT / "data" / "reports" / "experiments"
                                / "agent-2022-contamination-probes-v1" / "result.json")
DEFAULT_REGISTRATION = REPO_ROOT / "server" / "agent-cadence-registration.json"
CALIBRATION_BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))


def _mean(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def _scored_rows(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute(
        "SELECT t.policy_id,t.cadence,t.market_date,t.window_id,t.input_sha256,"
        "t.source_refs,t.latency_ms,t.total_tokens,d.ticker,d.decision,d.action,d.confidence,"
        "l.horizon_sessions,l.net_return,l.net_excess_return,l.maximum_adverse_excursion,"
        "l.maximum_favorable_excursion,l.price_prefix_sha256 "
        "FROM agent_evaluation_traces t JOIN agent_evaluation_decisions d ON d.trace_id=t.id "
        "LEFT JOIN agent_evaluation_labels l ON l.decision_id=d.id "
        "ORDER BY t.policy_id,t.window_id,d.ticker,l.horizon_sessions"
    ).fetchall()
    return [{
        "policy_id": row[0], "cadence": row[1], "market_date": row[2].isoformat(),
        "window_id": row[3], "input_sha256": row[4],
        "source_refs_sha256": canonical_sha256(json.loads(row[5])),
        "latency_ms": float(row[6]), "total_tokens": int(row[7]), "ticker": row[8],
        "decision": row[9], "action": row[10], "confidence": float(row[11]),
        "horizon": None if row[12] is None else int(row[12]),
        "asset_return": row[13], "excess_return": row[14],
        "mae": row[15], "mfe": row[16], "price_prefix_sha256": row[17],
    } for row in rows]


def _horizon_metrics(rows: list[dict]) -> dict:
    actionable = [row for row in rows if row["action"] != "none"]
    correctness = [1.0 if signed_return(row) > 0 else 0.0 for row in actionable]
    confusion = {
        "true_positive": sum(row["action"] == "buy" and correct == 1
                             for row, correct in zip(actionable, correctness, strict=True)),
        "false_positive": sum(row["action"] == "buy" and correct == 0
                              for row, correct in zip(actionable, correctness, strict=True)),
        "true_negative": sum(row["action"] == "sell" and correct == 1
                             for row, correct in zip(actionable, correctness, strict=True)),
        "false_negative": sum(row["action"] == "sell" and correct == 0
                              for row, correct in zip(actionable, correctness, strict=True)),
    }
    return {
        "labeled_action_count": len(actionable),
        "directional_accuracy": _mean(correctness),
        "confusion_matrix": confusion,
        "brier_score": _mean([(row["confidence"] - correct) ** 2
                                for row, correct in zip(actionable, correctness, strict=True)]),
        "mean_signed_return": _mean([signed_return(row) for row in actionable]),
        "mean_excess_return": _mean([float(row["excess_return"]) for row in actionable]),
        "mean_adverse_excursion": _mean([float(row["mae"]) for row in actionable]),
        "mean_favorable_excursion": _mean([float(row["mfe"]) for row in actionable]),
        "agent_vs_long_candidate_delta": _mean(
            [signed_return(row) - float(row["asset_return"]) for row in rows]
        ),
        "agent_vs_cash_delta": _mean([signed_return(row) for row in rows]),
    }


def _policy_metrics(rows: list[dict], trace_rows: list[dict]) -> dict:
    decisions = {
        (row["window_id"], row["ticker"]): row
        for row in rows
        if row["decision"] != "unavailable"
    }
    actionable = [row for row in rows if row["horizon"] is not None and row["action"] != "none"]
    correctness = [1.0 if signed_return(row) > 0 else 0.0 for row in actionable]
    brier = [(row["confidence"] - correct) ** 2
             for row, correct in zip(actionable, correctness, strict=True)]
    calibration = []
    for low, high in CALIBRATION_BINS:
        members = [(row, correct) for row, correct in zip(actionable, correctness, strict=True)
                   if low <= row["confidence"] <= high
                   and (row["confidence"] < high or high == 1.0)]
        calibration.append({
            "lower": low, "upper": high, "count": len(members),
            "mean_confidence": _mean([item[0]["confidence"] for item in members]),
            "observed_accuracy": _mean([item[1] for item in members]),
        })
    return {
        "trace_count": len({row["window_id"] for row in trace_rows}),
        "decision_count": len(decisions),
        "abstention_rate": _mean([1.0 if row["action"] == "none" else 0.0
                                    for row in decisions.values()]),
        "labeled_action_count": len(actionable),
        "directional_accuracy": _mean(correctness), "brier_score": _mean(brier),
        "mean_signed_return": _mean([signed_return(row) for row in actionable]),
        "mean_excess_return": _mean([float(row["excess_return"]) for row in actionable]),
        "mean_adverse_excursion": _mean([float(row["mae"]) for row in actionable]),
        "mean_favorable_excursion": _mean([float(row["mfe"]) for row in actionable]),
        "by_horizon": {str(horizon): _horizon_metrics(
            [row for row in rows if row["horizon"] == horizon]
        ) for horizon in HORIZONS},
        "mean_latency_ms": _mean([row["latency_ms"] for row in trace_rows]),
        "p95_latency_ms": _percentile([row["latency_ms"] for row in trace_rows], 0.95),
        "total_tokens": sum(row["total_tokens"] for row in trace_rows),
        "calibration": calibration,
        "forecast_error": {"status": "unavailable",
                           "reason": "forward policy does not emit a numeric return forecast"},
    }


def _operations(con: duckdb.DuckDBPyConnection) -> dict:
    result = {
        "order_count": 0, "fill_count": 0, "rejection_rate": None,
        "fill_rate": None, "exit_rule_count": 0, "completed_exit_count": 0,
        "exit_rate": None, "turnover_notional": 0.0, "turnover_over_initial_cash": None,
        "maximum_drawdown": None, "alert_open_count": 0, "alert_terminal_count": 0,
        "alert_trigger_rate": None, "alert_precision": None,
        "alert_precision_count": 0,
        "mean_total_shortfall_bps": None,
        "mean_cost_bps": None, "mean_order_to_fill_sessions": None,
        "timestamp_latency_observations": 0,
    }
    if table_exists(con, "daily_opportunity_execution_quality"):
        quality = con.execute(
            "SELECT q.total_shortfall_bps,q.cost_bps,q.order_to_fill_sessions,"
            "q.decision_to_tool_ms,q.tool_latency_ms,q.tool_to_order_ms,f.qty*f.fill_px "
            "FROM daily_opportunity_execution_quality q JOIN sim_fills f USING(order_id) "
            "ORDER BY order_id"
        ).fetchall()
        result.update(
            fill_count=len(quality),
            mean_total_shortfall_bps=_mean([float(row[0]) for row in quality]),
            mean_cost_bps=_mean([float(row[1]) for row in quality]),
            mean_order_to_fill_sessions=_mean([float(row[2]) for row in quality]),
            timestamp_latency_observations=sum(
                all(value is not None for value in row[3:6]) for row in quality
            ), turnover_notional=sum(abs(float(row[6])) for row in quality),
        )
    if table_exists(con, "daily_opportunity_order_attribution"):
        entry_orders = con.execute(
            "SELECT o.status FROM daily_opportunity_order_attribution a "
            "JOIN sim_orders o ON o.id=a.order_id"
        ).fetchall()
    else:
        entry_orders = []
    if table_exists(con, "daily_opportunity_exit_events"):
        exit_orders = con.execute(
            "SELECT o.status FROM daily_opportunity_exit_events e "
            "JOIN sim_orders o ON o.id=e.exit_order_id"
        ).fetchall()
    else:
        exit_orders = []
    statuses = [row[0] for row in (*entry_orders, *exit_orders)]
    result["order_count"] = len(statuses)
    result["fill_rate"] = _mean([float(status == "filled") for status in statuses])
    result["rejection_rate"] = _mean([float(status == "rejected") for status in statuses])
    if table_exists(con, "daily_opportunity_exit_rules"):
        result["exit_rule_count"] = int(con.execute(
            "SELECT COUNT(*) FROM daily_opportunity_exit_rules"
        ).fetchone()[0])
        result["completed_exit_count"] = sum(row[0] == "filled" for row in exit_orders)
        result["exit_rate"] = (None if not result["exit_rule_count"] else
                               result["completed_exit_count"] / result["exit_rule_count"])
    if table_exists(con, "portfolios"):
        row = con.execute(
            "SELECT initial_cash FROM portfolios WHERE id='daily_opportunity_agent_v1'"
        ).fetchone()
        if row and row[0]:
            result["turnover_over_initial_cash"] = result["turnover_notional"] / float(row[0])
    if table_exists(con, "sim_equity"):
        equity = [float(row[0]) for row in con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id='daily_opportunity_agent_v1' "
            "ORDER BY date"
        ).fetchall()]
        peak, drawdown = None, 0.0
        for value in equity:
            peak = value if peak is None else max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
        result["maximum_drawdown"] = None if not equity else drawdown
    if table_exists(con, "daily_opportunity_alert_events"):
        counts = dict(con.execute(
            "SELECT event_type,COUNT(*) FROM daily_opportunity_alert_events GROUP BY event_type"
        ).fetchall())
        triggered, expired = int(counts.get("triggered", 0)), int(counts.get("expired", 0))
        result["alert_open_count"] = int(counts.get("opened", 0)) - triggered - expired
        result["alert_terminal_count"] = triggered + expired
        result["alert_trigger_rate"] = (
            None if not triggered + expired else triggered / (triggered + expired)
        )
        outcomes = con.execute(
            "SELECT a.direction,a.trigger_price,p.close FROM daily_opportunity_alerts a "
            "JOIN daily_opportunity_alert_events e ON e.alert_id=a.id AND e.event_type='triggered' "
            "JOIN prices p ON p.ticker=a.ticker AND p.date=(SELECT MIN(p2.date) FROM prices p2 "
            "WHERE p2.ticker=a.ticker AND p2.date>e.market_date AND p2.close>0)"
        ).fetchall()
        result["alert_precision_count"] = len(outcomes)
        result["alert_precision"] = _mean([float(
            (row[0] == "above" and float(row[2]) > float(row[1]))
            or (row[0] == "below" and float(row[2]) < float(row[1]))
        ) for row in outcomes])
    return result


def build_report(
    con: duckdb.DuckDBPyConnection, *, generated_at: datetime,
    contamination_path: Path | None = None, registration_path: Path = DEFAULT_REGISTRATION,
) -> dict:
    if not table_exists(con, "agent_evaluation_traces"):
        rows = []
    else:
        rows = _scored_rows(con)
    trace_rows = {
        (row["policy_id"], row["window_id"]): row for row in rows
    }.values()
    policies = {}
    for policy in POLICIES:
        policy_rows = [row for row in rows if row["policy_id"] == policy]
        policy_traces = [row for row in trace_rows if row["policy_id"] == policy]
        policies[policy] = _policy_metrics(policy_rows, policy_traces)
    provenance = {
        "receipt_count": 0, "fact_count": 0, "sec_filing_fact_count": 0,
        "sec_current_mapping_fact_count": 0, "pit_import_batch_count": 0,
        "pit_import_row_count": 0, "historical_membership_authority": False,
    }
    if table_exists(con, "source_response_receipts"):
        provenance["receipt_count"] = int(con.execute(
            "SELECT COUNT(*) FROM source_response_receipts"
        ).fetchone()[0])
    if table_exists(con, "bitemporal_facts"):
        fact_counts = con.execute(
            "SELECT COUNT(*),COUNT(*) FILTER (WHERE fact_type LIKE 'sec.filing:%'),"
            "COUNT(*) FILTER (WHERE fact_type='sec.current_ticker_mapping') "
            "FROM bitemporal_facts"
        ).fetchone()
        provenance.update(fact_count=int(fact_counts[0]),
                          sec_filing_fact_count=int(fact_counts[1]),
                          sec_current_mapping_fact_count=int(fact_counts[2]))
    if table_exists(con, "pit_import_batches"):
        provenance["pit_import_batch_count"] = int(con.execute(
            "SELECT COUNT(*) FROM pit_import_batches"
        ).fetchone()[0])
        provenance["pit_import_row_count"] = int(con.execute(
            "SELECT COUNT(*) FROM pit_import_rows"
        ).fetchone()[0])
    cohorts = []
    if rows:
        cohorts = [{"policy_id": row[0], "cadence": row[1], "prompt_role": row[2],
                    "model": row[3], "model_version": row[4],
                    "instructions_sha256": row[5], "trace_count": int(row[6])}
                   for row in con.execute(
                       "SELECT policy_id,cadence,prompt_role,model,model_version,"
                       "instructions_sha256,COUNT(*) FROM agent_evaluation_traces "
                       "GROUP BY ALL ORDER BY policy_id,prompt_role,model,model_version"
                   ).fetchall()]
    legacy = sorted({row["policy_id"] for row in rows if row["policy_id"] not in POLICIES})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "evidence_class": "prospective_forward_only", "promotion_authority": "none",
        "horizons": list(HORIZONS), "policies": policies, "cohorts": cohorts,
        "legacy_policy_ids": legacy,
        "pairs": paired_metrics(rows, POLICIES),
        "data_provenance": provenance,
        "coverage": coverage(con, rows, generated_at, registration_path, HORIZONS),
        "execution": _operations(con),
        "contamination": contamination_diagnostics(tuple(path for path in (
            (contamination_path, DEFAULT_CONTAMINATION_PROBES)
            if contamination_path == DEFAULT_CONTAMINATION else (contamination_path,)
        ) if path is not None)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contamination", type=Path, default=DEFAULT_CONTAMINATION)
    args = parser.parse_args(argv)
    con = db.connect(args.database, read_only=True, wait_s=0)
    try:
        report = build_report(con, generated_at=datetime.now(timezone.utc),
                              contamination_path=args.contamination)
    finally:
        con.close()
    resources.write_text_atomic(args.output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "complete", "output": str(args.output),
                      "trace_count": report["coverage"]["trace_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
