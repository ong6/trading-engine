"""Read-only, immutable P15 inputs for P16 evaluation research."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import duckdb

from engine import p15_evaluation
from engine.lib.provenance import canonical_sha256
from server import agent_evaluation

POLICY_ID = "p15-scoring-v1"
TERMINAL_H5_BASES = {"next_session_open", "missing_entry_last_available_close"}


class EvaluationInputError(ValueError):
    """The retained P15 origin is absent, ambiguous, or inconsistent."""


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvaluationInputError("report cutoff must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationInputError(f"{field} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationInputError(f"{field} is invalid")
    return result


def _rank(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvaluationInputError("baseline rank is invalid")
    return value


def _one_trace(con: duckdb.DuckDBPyConnection, market_date: date) -> dict:
    cursor = con.execute(
        "SELECT id,market_date,information_cutoff_at,completed_at,source_kind,source_identifier,"
        "source_refs,input_payload,input_sha256,output_sha256,request_sha256,terminal_status,"
        "trace_sha256 FROM agent_evaluation_traces "
        "WHERE policy_id=? AND market_date=? ORDER BY id", [POLICY_ID, market_date],
    )
    columns, values = [item[0] for item in cursor.description], cursor.fetchall()
    if len(values) != 1:
        raise EvaluationInputError("P15 scoring origin is absent or ambiguous")
    return dict(zip(columns, values[0], strict=True))


def _frozen_candidates(trace: dict) -> tuple[list[dict], str, str]:
    try:
        universe = json.loads(trace["input_payload"])["universe"]
        candidates = universe["candidates"]
        universe_sha = universe["bundle_sha256"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise EvaluationInputError("P15 frozen universe is invalid") from exc
    if not isinstance(candidates, list) or not candidates:
        raise EvaluationInputError("P15 frozen universe is empty")
    body = {key: value for key, value in universe.items() if key != "bundle_sha256"}
    if canonical_sha256(body) != universe_sha:
        raise EvaluationInputError("P15 frozen universe identity differs")
    tickers = [item.get("ticker") for item in candidates if isinstance(item, dict)]
    if len(tickers) != len(candidates) or any(not item for item in tickers) \
            or len(set(tickers)) != len(tickers):
        raise EvaluationInputError("P15 frozen candidate set is invalid")
    return candidates, universe_sha, canonical_sha256(universe)


def _decisions(con: duckdb.DuckDBPyConnection, trace_id: int) -> dict[str, dict]:
    rows = con.execute(
        "SELECT id,ticker,decision,assessment_sha256,decision_payload,decision_sha256 "
        "FROM agent_evaluation_decisions WHERE trace_id=? ORDER BY ticker", [trace_id],
    ).fetchall()
    result = {row[1]: {"id": int(row[0]), "decision": row[2],
                       "assessment_sha256": row[3], "payload": json.loads(row[4]),
                       "decision_sha256": row[5]}
              for row in rows}
    if len(result) != len(rows):
        raise EvaluationInputError("P15 decision set contains duplicate tickers")
    return result


def _labels(
    con: duckdb.DuckDBPyConnection, decision_ids: list[int], cutoff: datetime,
) -> dict[int, dict]:
    if not decision_ids:
        return {}
    placeholders = ",".join("?" for _ in decision_ids)
    rows = con.execute(
        "SELECT decision_id,label_basis,entry_date,exit_date,missing_bar_status,labeled_at,"
        "label_sha256,price_prefix_sha256,round_trip_cost_bps,net_excess_return "
        "FROM agent_evaluation_labels_v2 WHERE horizon_sessions=5 "
        f"AND decision_id IN ({placeholders}) AND labeled_at<=? ORDER BY decision_id,id",
        [*decision_ids, cutoff],
    ).fetchall()
    result: dict[int, dict] = {}
    for row in rows:
        decision_id, basis = int(row[0]), row[1]
        if basis not in TERMINAL_H5_BASES:
            continue
        if decision_id in result:
            raise EvaluationInputError("P15 decision has duplicate terminal h5 labels")
        result[decision_id] = {
            "label_basis": basis, "entry_date": _iso(row[2]), "exit_date": _iso(row[3]),
            "missing_bar_status": row[4], "labeled_at": _iso(row[5]),
            "label_sha256": row[6], "price_prefix_sha256": row[7],
            "round_trip_cost_bps": _finite(row[8], "round-trip cost"),
            "net_excess_return": _finite(row[9], "h5 net excess return"),
            "fallback_label": basis == "missing_entry_last_available_close"
            or row[4] != "complete",
        }
        if result[decision_id]["round_trip_cost_bps"] != 20.0:
            raise EvaluationInputError("P15 h5 label cost basis differs")
    return result


def load_origin(
    con: duckdb.DuckDBPyConnection, *, market_date: date, report_cutoff: datetime,
) -> dict:
    """Project one validated scoring origin without writing to the source database."""
    cutoff = _utc_naive(report_cutoff)
    agent_evaluation.validate_p15_evidence(con, generated_at=report_cutoff)
    trace = _one_trace(con, market_date)
    if (trace["source_kind"] != "p15_scoring_run" or trace["terminal_status"] != "completed"
            or trace["information_cutoff_at"] > cutoff or trace["completed_at"] > cutoff):
        raise EvaluationInputError("P15 scoring trace is unavailable at report cutoff")
    candidates, bundle_sha, universe_sha = _frozen_candidates(trace)
    decisions = _decisions(con, int(trace["id"]))
    if set(decisions) != {item["ticker"] for item in candidates}:
        raise EvaluationInputError("P15 decision set differs from frozen candidates")
    run = con.execute(
        "SELECT universe_sha256,context_sha256,aggregate_trace_sha256,"
        "information_cutoff_at,completed_at FROM p15_scoring_runs "
        "WHERE id=? AND policy_id=? AND market_date=? AND status='completed'",
        [int(trace["source_identifier"]), POLICY_ID, market_date],
    ).fetchone()
    if (run is None or run[0] != universe_sha or run[2] != trace["trace_sha256"]
            or run[3] != trace["information_cutoff_at"] or run[4] != trace["completed_at"]
            or run[3] > cutoff or run[4] > cutoff):
        raise EvaluationInputError("P15 scoring run identity differs")
    ranks = []
    for candidate in candidates:
        decision = decisions[candidate["ticker"]]
        payload = decision["payload"]
        if any(payload.get(field) != value for field, value in candidate.items()):
            raise EvaluationInputError("P15 retained candidate fields differ")
        rank = _rank(payload["baseline_rank"])
        score = _finite(payload["baseline_score"], "baseline score")
        if score != len(candidates) + 1 - rank:
            raise EvaluationInputError("baseline score is not equivalent to negative rank")
        ranks.append(rank)
    if sorted(ranks) != list(range(1, len(candidates) + 1)):
        raise EvaluationInputError("baseline score is not equivalent to negative rank")
    labels = _labels(con, [item["id"] for item in decisions.values()], cutoff)
    rows, unresolved, held_only = [], [], 0
    for candidate in candidates:
        ticker, stratum = candidate["ticker"], candidate.get("stratum")
        if stratum == "held_only":
            held_only += 1
            continue
        if stratum not in {"mover", "trend"}:
            raise EvaluationInputError("P15 candidate stratum is invalid")
        decision = decisions[ticker]
        label = labels.get(decision["id"])
        if label is None:
            unresolved.append(ticker)
            continue
        payload = decision["payload"]
        available = payload.get("scoring_status") == "available"
        if payload.get("scoring_status") not in {"available", "unavailable"}:
            raise EvaluationInputError("P15 scoring status is invalid")
        champion = payload.get("expected_excess_bp_5")
        if available:
            champion = _finite(champion, "champion score")
            if decision["decision"] == "unavailable":
                raise EvaluationInputError("available P15 score has unavailable decision")
        elif champion is not None or decision["decision"] != "unavailable":
            raise EvaluationInputError("unavailable P15 score is populated")
        rows.append({
            "ticker": ticker, "stratum": stratum,
            "champion_score": champion, "champion_score_available": available,
            "rule_score": -_rank(payload["baseline_rank"]),
            "baseline_rank": payload["baseline_rank"], "baseline_score": payload["baseline_score"],
            "candidate_evidence_id": candidate.get("evidence_id"),
            "decision": decision["decision"],
            "assessment_sha256": decision["assessment_sha256"],
            "decision_sha256": decision["decision_sha256"],
            **label,
        })
    body = {
        "schema_version": 1, "policy_id": POLICY_ID,
        "status": "pending" if unresolved else "available",
        "market_date": market_date.isoformat(),
        "report_cutoff": report_cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scoring_information_cutoff_at": _iso(trace["information_cutoff_at"]),
        "source": {"run_id": int(trace["source_identifier"]),
                   "bundle_sha256": bundle_sha, "universe_sha256": universe_sha,
                   "context_sha256": run[1],
                   "source_refs_sha256": canonical_sha256(json.loads(trace["source_refs"])),
                   "request_sha256": trace["request_sha256"],
                   "input_sha256": trace["input_sha256"],
                   "output_sha256": trace["output_sha256"], "trace_sha256": trace["trace_sha256"]},
        "p15_registration_sha256": p15_evaluation.registration_sha256(),
        "scoring_completed_at": _iso(trace["completed_at"]),
        "frozen_candidate_count": len(candidates), "held_only_excluded_count": held_only,
        "evaluation_candidate_count": len(candidates) - held_only,
        "terminal_h5_count": len(rows), "unresolved_h5_tickers": unresolved, "rows": rows,
    }
    return {**body, "input_snapshot_sha256": canonical_sha256(body)}
