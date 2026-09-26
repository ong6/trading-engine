"""Canonical append-only traces and delayed labels for forward agent evaluation."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from tools import p15_evidence_validation

from . import agent_model_client

SCHEMA_VERSION = 1
LABEL_SCHEMA_VERSION = 2
LABEL_V2_SCHEMA_VERSION = 1
COMMON_ENTRY_BASIS = "common_entry"
NEXT_SESSION_OPEN_BASIS = "next_session_open"
ROUND_TRIP_COST_BPS = 20.0
HORIZONS = (1, 5, 10, 20)
TRACE_LIMIT = 500
POLICY_EVALUATION_STARTS = {
    "hourly_market_watch_v5": datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
    "four_hour_opportunity_review_v5": datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
}
POLICIES = {
    "nightly_opportunity_tool_v1": "nightly",
    "hourly_market_watch_v5": "hourly",
    "four_hour_opportunity_review_v5": "four_hour",
    "p15-scoring-v1": "nightly",
}
LEGACY_POLICIES = {"hourly_market_watch_v1": "hourly",
                   "four_hour_opportunity_review_v1": "four_hour",
                   "hourly_market_watch_v2": "hourly",
                   "four_hour_opportunity_review_v2": "four_hour"}
LEGACY_POLICIES.update({"hourly_market_watch_v3": "hourly",
                        "four_hour_opportunity_review_v3": "four_hour"})
LEGACY_POLICIES.update({"hourly_market_watch_v4": "hourly",
                        "four_hour_opportunity_review_v4": "four_hour"})
TRACE_REQUIRED_FIELDS = frozenset({
    "window_id", "policy_id", "cadence", "prompt_role", "market_date",
    "observed_at", "completed_at", "information_cutoff_at", "source_kind",
    "source_identifier", "source_refs", "input_payload", "output_payload",
    "request_sha256", "response_id", "model", "model_version",
    "instructions_sha256", "toolset_sha256", "model_catalog_entry_sha256",
    "proxy_source_sha256", "traecli_runtime", "upstream_model_family",
    "upstream_request_id", "latency_ms", "usage", "terminal_status",
    "execution_authority", "decisions",
})


class EvaluationError(ValueError):
    """An evaluation trace or outcome label is invalid or inconsistent."""


def _timestamp(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise EvaluationError("evaluation timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def in_evaluation_cohort(policy_id: str, observed_at: datetime) -> bool:
    start = POLICY_EVALUATION_STARTS.get(policy_id)
    stored = (
        observed_at.replace(tzinfo=timezone.utc)
        if type(observed_at) is datetime and observed_at.utcoffset() is None
        else observed_at
    )
    return start is None or _timestamp(stored) >= _timestamp(start)


def _next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    if table not in {
        "agent_evaluation_traces",
        "agent_evaluation_decisions",
        "agent_evaluation_labels",
        "agent_evaluation_labels_v2",
    }:
        raise EvaluationError("evaluation table is invalid")
    return int(con.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()[0])


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS agent_evaluation_traces (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, window_id VARCHAR NOT NULL UNIQUE,
        policy_id VARCHAR NOT NULL, cadence VARCHAR NOT NULL, prompt_role VARCHAR NOT NULL,
        market_date DATE NOT NULL, observed_at TIMESTAMP NOT NULL, completed_at TIMESTAMP NOT NULL,
        information_cutoff_at TIMESTAMP NOT NULL, source_kind VARCHAR NOT NULL,
        source_identifier VARCHAR NOT NULL, source_refs VARCHAR NOT NULL,
        input_payload VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL,
        output_payload VARCHAR NOT NULL, output_sha256 VARCHAR NOT NULL,
        request_sha256 VARCHAR NOT NULL, response_id VARCHAR NOT NULL,
        model VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
        instructions_sha256 VARCHAR NOT NULL, toolset_sha256 VARCHAR NOT NULL,
        model_catalog_entry_sha256 VARCHAR NOT NULL, proxy_source_sha256 VARCHAR NOT NULL,
        traecli_runtime VARCHAR NOT NULL, upstream_model_family VARCHAR NOT NULL,
        upstream_request_id VARCHAR NOT NULL, latency_ms DOUBLE NOT NULL,
        input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
        terminal_status VARCHAR NOT NULL, execution_authority VARCHAR NOT NULL,
        trace_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS agent_evaluation_decisions (
        id BIGINT PRIMARY KEY, trace_id BIGINT NOT NULL, ticker VARCHAR NOT NULL,
        decision VARCHAR NOT NULL, action VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL,
        confidence DOUBLE NOT NULL, assessment_sha256 VARCHAR NOT NULL,
        source_assessment_id BIGINT, decision_payload VARCHAR NOT NULL,
        decision_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(trace_id, ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS agent_evaluation_labels (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, decision_id BIGINT NOT NULL,
        horizon_sessions INTEGER NOT NULL, entry_date DATE NOT NULL, exit_date DATE NOT NULL,
        entry_open DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL,
        spy_return DOUBLE NOT NULL, excess_return DOUBLE NOT NULL,
        maximum_adverse_excursion DOUBLE NOT NULL, maximum_favorable_excursion DOUBLE NOT NULL,
        price_prefix_sha256 VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL,
        label_sha256 VARCHAR NOT NULL UNIQUE, round_trip_cost_bps DOUBLE NOT NULL DEFAULT 20,
        net_return DOUBLE NOT NULL DEFAULT 0, net_excess_return DOUBLE NOT NULL DEFAULT 0,
        UNIQUE(decision_id, horizon_sessions))"""
    )
    con.execute("ALTER TABLE agent_evaluation_labels ADD COLUMN IF NOT EXISTS "
                "round_trip_cost_bps DOUBLE DEFAULT 20")
    con.execute("ALTER TABLE agent_evaluation_labels ADD COLUMN IF NOT EXISTS net_return DOUBLE DEFAULT 0")
    con.execute("ALTER TABLE agent_evaluation_labels ADD COLUMN IF NOT EXISTS net_excess_return DOUBLE DEFAULT 0")
    con.execute(
        """CREATE TABLE IF NOT EXISTS agent_evaluation_labels_v2 (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, decision_id BIGINT NOT NULL,
        horizon_sessions INTEGER NOT NULL, label_basis VARCHAR NOT NULL,
        entry_date DATE NOT NULL, exit_date DATE NOT NULL,
        entry_open DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL,
        spy_return DOUBLE NOT NULL, excess_return DOUBLE NOT NULL,
        maximum_adverse_excursion DOUBLE NOT NULL, maximum_favorable_excursion DOUBLE NOT NULL,
        price_prefix_sha256 VARCHAR NOT NULL, missing_bar_status VARCHAR NOT NULL,
        labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE,
        round_trip_cost_bps DOUBLE NOT NULL, net_return DOUBLE NOT NULL,
        net_excess_return DOUBLE NOT NULL,
        UNIQUE(decision_id, horizon_sessions, label_basis))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS agent_evaluation_execution_links (
        id BIGINT PRIMARY KEY, decision_id BIGINT NOT NULL UNIQUE, tool_attempt_id BIGINT NOT NULL,
        order_id BIGINT, linked_at TIMESTAMP NOT NULL, link_sha256 VARCHAR NOT NULL UNIQUE)"""
    )


def _validate_trace_observation(trace: dict) -> dict:
    usage = trace.get("usage")
    if not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}:
        raise EvaluationError("evaluation usage is invalid")
    if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise EvaluationError("evaluation usage is inconsistent")
    latency = trace.get("latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
        raise EvaluationError("evaluation latency is invalid")
    observed = _timestamp(trace["observed_at"])
    completed = _timestamp(trace["completed_at"])
    cutoff = _timestamp(trace["information_cutoff_at"])
    if observed > cutoff or cutoff > completed:
        raise EvaluationError("evaluation event and availability times are inconsistent")
    return usage


def _validate_trace(trace: dict) -> None:
    if set(trace) != TRACE_REQUIRED_FIELDS:
        raise EvaluationError("evaluation trace shape is invalid")
    policy_id = trace.get("policy_id")
    if policy_id not in POLICIES | LEGACY_POLICIES or trace.get("cadence") != (
            POLICIES | LEGACY_POLICIES)[policy_id]:
        raise EvaluationError("evaluation policy or cadence is invalid")
    if type(trace.get("market_date")) is not date:
        raise EvaluationError("evaluation market date is invalid")
    if not isinstance(trace.get("decisions"), list) or not trace["decisions"]:
        raise EvaluationError("evaluation decisions are empty")
    usage = _validate_trace_observation(trace)
    if not isinstance(trace.get("source_refs"), list) or not trace["source_refs"]:
        raise EvaluationError("evaluation source references are empty")
    for field in (
        "window_id", "prompt_role", "source_kind", "source_identifier",
        "request_sha256", "response_id", "model", "model_version",
        "instructions_sha256", "toolset_sha256", "model_catalog_entry_sha256",
        "proxy_source_sha256", "traecli_runtime", "upstream_model_family",
        "upstream_request_id", "terminal_status", "execution_authority",
    ):
        value = trace[field]
        if not isinstance(value, str) or not value or len(value) > 256 or not value.isprintable():
            raise EvaluationError(f"evaluation {field} is invalid")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in usage.values()):
        raise EvaluationError("evaluation usage is invalid")


def record_trace(con: duckdb.DuckDBPyConnection, trace: dict) -> dict:
    """Insert one immutable trace and its candidate decisions, or verify exact replay."""
    _validate_trace(trace)
    window_id = trace["window_id"]
    input_payload, output_payload, source_refs = (
        _json(trace["input_payload"]), _json(trace["output_payload"]), _json(trace["source_refs"])
    )
    input_sha, output_sha = canonical_sha256(trace["input_payload"]), canonical_sha256(trace["output_payload"])
    identity = {
        "schema_version": SCHEMA_VERSION, "window_id": window_id,
        "policy_id": trace["policy_id"], "cadence": trace["cadence"],
        "prompt_role": trace["prompt_role"], "market_date": trace["market_date"].isoformat(),
        "observed_at": _timestamp(trace["observed_at"]).isoformat(),
        "completed_at": _timestamp(trace["completed_at"]).isoformat(),
        "information_cutoff_at": _timestamp(trace["information_cutoff_at"]).isoformat(),
        "source_kind": trace["source_kind"], "source_identifier": trace["source_identifier"],
        "source_refs_sha256": canonical_sha256(trace["source_refs"]),
        "input_sha256": input_sha, "output_sha256": output_sha,
        "request_sha256": trace["request_sha256"], "response_id": trace["response_id"],
        "model": trace["model"], "model_version": trace["model_version"],
        "instructions_sha256": trace["instructions_sha256"],
        "toolset_sha256": trace["toolset_sha256"],
        "model_catalog_entry_sha256": trace["model_catalog_entry_sha256"],
        "proxy_source_sha256": trace["proxy_source_sha256"],
        "traecli_runtime": trace["traecli_runtime"],
        "upstream_model_family": trace["upstream_model_family"],
        "upstream_request_id": trace["upstream_request_id"],
        "latency_ms": float(trace["latency_ms"]), "usage": trace["usage"],
        "terminal_status": trace["terminal_status"],
        "execution_authority": trace["execution_authority"],
    }
    trace_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT id, trace_sha256 FROM agent_evaluation_traces WHERE window_id = ?", [window_id]
    ).fetchone()
    if existing is not None:
        if existing[1] != trace_sha:
            raise EvaluationError("evaluation window replay differs from retained trace")
        return {"trace_id": int(existing[0]), "trace_sha256": trace_sha, "replayed": True}
    trace_id = _next_id(con, "agent_evaluation_traces")
    observed, completed, cutoff = map(
        _timestamp, (trace["observed_at"], trace["completed_at"], trace["information_cutoff_at"])
    )
    values = [
        trace_id, SCHEMA_VERSION, window_id, trace["policy_id"], trace["cadence"],
        trace["prompt_role"], trace["market_date"], observed, completed, cutoff,
        trace["source_kind"], trace["source_identifier"], source_refs, input_payload,
        input_sha, output_payload, output_sha, trace["request_sha256"], trace["response_id"],
        trace["model"], trace["model_version"], trace["instructions_sha256"],
        trace["toolset_sha256"], trace["model_catalog_entry_sha256"],
        trace["proxy_source_sha256"], trace["traecli_runtime"],
        trace["upstream_model_family"], trace["upstream_request_id"], float(trace["latency_ms"]),
        trace["usage"]["input_tokens"], trace["usage"]["output_tokens"],
        trace["usage"]["total_tokens"], trace["terminal_status"],
        trace["execution_authority"], trace_sha,
    ]
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (" + ",".join("?" for _ in values) + ")",
        values,
    )
    decision_id = _next_id(con, "agent_evaluation_decisions")
    seen = set()
    allowed_decisions = {"ignore", "watch", "hold", "swing", "unavailable"}
    if trace["policy_id"] == "p15-scoring-v1":
        allowed_decisions |= {"buy_candidate", "exit"}
    for item in trace["decisions"]:
        ticker = item.get("ticker")
        if not isinstance(ticker, str) or not ticker or ticker in seen:
            raise EvaluationError("evaluation decision ticker is invalid or duplicated")
        seen.add(ticker)
        if (item.get("decision") not in allowed_decisions
                or item.get("action") not in {"none", "buy", "sell"}
                or isinstance(item.get("horizon_sessions"), bool)
                or not isinstance(item.get("horizon_sessions"), int)
                or not 1 <= item["horizon_sessions"] <= 20
                or isinstance(item.get("confidence"), bool)
                or not isinstance(item.get("confidence"), (int, float))
                or not math.isfinite(item["confidence"])
                or not 0 <= item["confidence"] <= 1):
            raise EvaluationError("evaluation decision values are invalid")
        payload = _json(item)
        assessment_sha = item.get("assessment_sha256") or canonical_sha256(item)
        decision_identity = {"trace_sha256": trace_sha, "ticker": ticker,
                             "assessment_sha256": assessment_sha}
        con.execute(
            "INSERT INTO agent_evaluation_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [decision_id, trace_id, ticker, item["decision"], item["action"],
             item["horizon_sessions"], float(item["confidence"]), assessment_sha,
             item.get("source_assessment_id"), payload, canonical_sha256(decision_identity)],
        )
        decision_id += 1
    return {"trace_id": trace_id, "trace_sha256": trace_sha, "replayed": False}


def daily_trace(
    con: duckdb.DuckDBPyConnection,
    run_id: int,
) -> dict:
    """Reconstruct one completed P8 run from its authoritative retained rows."""
    row = con.execute(
        "SELECT market_date, bundle_payload, model_input_payload, information_cutoff_at, "
        "model_latency_ms, model_request_sha256, model_response_id, model_response_payload, "
        "status, started_at, completed_at FROM daily_opportunity_runs "
        "WHERE id = ?", [run_id]
    ).fetchone()
    if row is None or row[8] != "completed" or any(row[index] is None for index in (2, 3, 4, 5, 6, 7, 10)):
        raise EvaluationError("completed daily opportunity run is unavailable")
    (market_date, raw_bundle, raw_input, cutoff, latency_ms, request_sha, response_id,
     raw_response, status, started, completed) = row
    bundle, model_input, identity = map(json.loads, (raw_bundle, raw_input, raw_response))
    decisions = []
    for item in con.execute(
        "SELECT id, assessment_payload, assessment_sha256 FROM daily_opportunity_assessments "
        "WHERE run_id = ? ORDER BY id", [run_id]
    ).fetchall():
        decision = json.loads(item[1])
        decisions.append({**decision, "source_assessment_id": int(item[0]),
                          "assessment_sha256": item[2]})
    source_refs = [
        {"kind": "daily_opportunity_bundle", "sha256": bundle["bundle_sha256"]},
        *[{"kind": "news_receipt", "ticker": ticker, "sha256": receipt}
          for ticker, receipt in con.execute(
              "SELECT ticker, receipt_sha256 FROM daily_opportunity_news_responses "
              "WHERE run_id = ? ORDER BY ticker", [run_id]
          ).fetchall()],
    ]
    return {
        "window_id": f"nightly:{market_date.isoformat()}",
        "policy_id": "nightly_opportunity_tool_v1", "cadence": "nightly",
        "prompt_role": "eod_swing_decision", "market_date": market_date,
        "observed_at": started.replace(tzinfo=timezone.utc),
        "completed_at": completed.replace(tzinfo=timezone.utc),
        "information_cutoff_at": cutoff.replace(tzinfo=timezone.utc),
        "source_kind": "daily_opportunity_run", "source_identifier": str(run_id),
        "source_refs": source_refs, "input_payload": model_input,
        "output_payload": identity["output"], "request_sha256": request_sha,
        "response_id": response_id, "model": identity["model"],
        "model_version": identity["model_version"],
        "instructions_sha256": agent_model_client.identity(role="opportunity")[
            "instructions_sha256"
        ],
        "toolset_sha256": agent_model_client.identity(role="opportunity")[
            "toolset_sha256"
        ],
        "model_catalog_entry_sha256": identity["model_catalog_entry_sha256"],
        "proxy_source_sha256": identity["proxy_source_sha256"],
        "traecli_runtime": identity["traecli_runtime"],
        "upstream_model_family": identity["upstream_model_family"],
        "upstream_request_id": identity["upstream_request_id"],
        "latency_ms": latency_ms, "usage": identity["usage"],
        "terminal_status": status, "execution_authority": "local_simulator_only",
        "decisions": decisions,
    }


def artifact_trace(artifact: dict, *, source_identifier: str, latency_ms: float) -> dict:
    """Translate one retained hourly/four-hour artifact into the canonical trace contract."""
    model_input = artifact["model_input"]
    response = artifact["model_response"]
    decisions = [
        {**item, "assessment_sha256": canonical_sha256(item)}
        for item in artifact["assessments"]
    ]
    source_refs = [
        {"kind": "artifact", "sha256": artifact["observation_sha256"]},
        *[{"kind": "intraday_receipt", "ticker": item["ticker"],
           "sha256": item["receipt_sha256"]} for item in artifact["quotes"]
          if item.get("receipt_sha256")],
        *[{"kind": "intraday_failure_receipt", "ticker": item["ticker"],
           "sha256": item["receipt_sha256"]} for item in artifact.get("quote_failures", [])
          if item.get("receipt_sha256")],
        *[{"kind": "realtime_cross_check_receipt", "ticker": item["ticker"],
           "source_id": item["source_id"], "sha256": item["receipt_sha256"],
           "execution_authority": "none"}
          for item in artifact.get("realtime_cross_checks", [])
          if item.get("receipt_sha256")],
        *[{"kind": "news_receipt", "ticker": item["ticker"],
           "sha256": item["receipt_sha256"]} for item in artifact["news_receipts"]],
    ]
    observed = datetime.fromisoformat(artifact["observed_at"])
    completed = datetime.fromisoformat(artifact["completed_at"])
    cutoff = datetime.fromisoformat(artifact["information_cutoff_at"])
    return {
        "window_id": f"{artifact['variant_id']}:{artifact['window']}",
        "policy_id": artifact["variant_id"], "cadence": artifact["cadence"],
        "prompt_role": artifact["prompt_role"],
        "market_date": date.fromisoformat(artifact["market_date"]),
        "observed_at": observed, "completed_at": completed,
        "information_cutoff_at": cutoff, "source_kind": "jsonl_artifact",
        "source_identifier": source_identifier, "source_refs": source_refs,
        "input_payload": model_input, "output_payload": response["output"],
        "request_sha256": response["request_sha256"], "response_id": response["response_id"],
        "model": response["model"], "model_version": response["model_version"],
        "instructions_sha256": response["instructions_sha256"],
        "toolset_sha256": response["toolset_sha256"],
        "model_catalog_entry_sha256": response["model_catalog_entry_sha256"],
        "proxy_source_sha256": response["proxy_source_sha256"],
        "traecli_runtime": response["traecli_runtime"],
        "upstream_model_family": response["upstream_model_family"],
        "upstream_request_id": response["upstream_request_id"],
        "latency_ms": latency_ms, "usage": response["usage"],
        "terminal_status": "completed", "execution_authority": "none",
        "decisions": decisions,
    }


def replay_artifact_trace(artifact: dict, *, source_identifier: str) -> dict:
    """Index a complete P11 artifact; reject legacy artifacts rather than guessing identity."""
    required = {"model_input", "model_response", "completed_at",
                "information_cutoff_at", "latency_ms"}
    if not required <= set(artifact):
        raise EvaluationError("agent artifact predates the canonical trace contract")
    return artifact_trace(
        artifact, source_identifier=source_identifier,
        latency_ms=float(artifact["latency_ms"]),
    )


def _label_outcome(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    sessions: list[date],
    labeled_at: datetime,
) -> dict | None:
    entry_date, exit_date = sessions[0], sessions[-1]
    asset = con.execute(
        f"SELECT date,open,high,low,close FROM prices WHERE ticker=? "
        f"AND date>=? AND date<=? AND fetched_at IS NOT NULL AND fetched_at<=? "
        f"AND {REAL_BAR_SQL} ORDER BY date",
        [ticker, entry_date, exit_date, labeled_at],
    ).fetchall()
    spy = con.execute(
        f"SELECT date,open,high,low,close FROM prices WHERE ticker='SPY' "
        f"AND date>=? AND date<=? AND fetched_at IS NOT NULL AND fetched_at<=? "
        f"AND {REAL_BAR_SQL} ORDER BY date",
        [entry_date, exit_date, labeled_at],
    ).fetchall()
    if len(spy) != len(sessions):
        return None
    if not asset or asset[0][0] != entry_date or asset[0][1] in (None, 0):
        last = con.execute(
            f"SELECT date,close FROM prices WHERE ticker=? AND date<? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date DESC LIMIT 1",
            [ticker, entry_date, labeled_at],
        ).fetchone()
        if last is None or last[1] in (None, 0):
            return None
        previous_date, previous_close = last[0], float(last[1])
        return {
            "entry_date": previous_date, "exit_date": previous_date,
            "entry_open": previous_close, "exit_close": previous_close,
            "asset_return": 0.0, "spy_return": 0.0, "excess_return": 0.0,
            "maximum_adverse_excursion": 0.0, "maximum_favorable_excursion": 0.0,
            "price_prefix_sha256": canonical_sha256({
                "expected_sessions": [item.isoformat() for item in sessions],
                "asset_rows": [(previous_date.isoformat(), previous_close)],
            }),
            "missing_bar_status": "missing_entry_last_available_close",
            "label_basis_override": "missing_entry_last_available_close",
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "net_return": 0.999 / 1.001 - 1,
            "net_excess_return": 0.0,
        }
    asset_dates = [item[0] for item in asset]
    missing_bar_status = (
        "complete" if asset_dates == sessions else "last_available_close"
    )
    exit_date = asset[-1][0]
    spy_by_date = {item[0]: item for item in spy}
    if exit_date not in spy_by_date:
        return None
    entry, exit_close = float(asset[0][1]), float(asset[-1][4])
    asset_return = exit_close / entry - 1
    spy_return = float(spy_by_date[exit_date][4]) / float(spy[0][1]) - 1
    net_return = exit_close * 0.999 / (entry * 1.001) - 1
    spy_net = (
        float(spy_by_date[exit_date][4]) * 0.999 / (float(spy[0][1]) * 1.001) - 1
    )
    lows = [float(item[3]) / entry - 1 for item in asset if item[3] is not None]
    highs = [float(item[2]) / entry - 1 for item in asset if item[2] is not None]
    prefix = {
        "expected_sessions": [item.isoformat() for item in sessions],
        "asset_rows": [(item[0].isoformat(), *item[1:]) for item in asset],
    }
    return {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_open": entry,
        "exit_close": exit_close,
        "asset_return": asset_return,
        "spy_return": spy_return,
        "excess_return": asset_return - spy_return,
        "maximum_adverse_excursion": min(lows),
        "maximum_favorable_excursion": max(highs),
        "price_prefix_sha256": canonical_sha256(prefix),
        "missing_bar_status": missing_bar_status,
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "net_return": net_return,
        "net_excess_return": net_return - spy_net,
    }


def _insert_v2_label(
    con: duckdb.DuckDBPyConnection,
    decision_id: int,
    horizon: int,
    outcome: dict,
    labeled_at: datetime,
    label_basis: str = COMMON_ENTRY_BASIS,
) -> bool:
    stored_basis = outcome.get("label_basis_override", label_basis)
    terminal_bases = [label_basis]
    if label_basis in {COMMON_ENTRY_BASIS, NEXT_SESSION_OPEN_BASIS}:
        terminal_bases.append("missing_entry_last_available_close")
    if con.execute(
        "SELECT 1 FROM agent_evaluation_labels_v2 "
        f"WHERE decision_id=? AND horizon_sessions=? AND label_basis IN "
        f"({','.join('?' for _ in terminal_bases)})",
        [decision_id, horizon, *terminal_bases],
    ).fetchone():
        return False
    body = {
        "schema_version": LABEL_V2_SCHEMA_VERSION,
        "decision_id": decision_id,
        "horizon_sessions": horizon,
        "label_basis": stored_basis,
        **{
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in outcome.items()
            if key != "label_basis_override"
        },
        "missing_bar_status": outcome["missing_bar_status"],
    }
    con.execute(
        "INSERT INTO agent_evaluation_labels_v2 VALUES ("
        + ",".join("?" for _ in range(21))
        + ")",
        [
            _next_id(con, "agent_evaluation_labels_v2"),
            LABEL_V2_SCHEMA_VERSION,
            decision_id,
            horizon,
            stored_basis,
            outcome["entry_date"],
            outcome["exit_date"],
            outcome["entry_open"],
            outcome["exit_close"],
            outcome["asset_return"],
            outcome["spy_return"],
            outcome["excess_return"],
            outcome["maximum_adverse_excursion"],
            outcome["maximum_favorable_excursion"],
            outcome["price_prefix_sha256"],
            outcome["missing_bar_status"],
            _timestamp(labeled_at),
            canonical_sha256(body),
            outcome["round_trip_cost_bps"],
            outcome["net_return"],
            outcome["net_excess_return"],
        ],
    )
    return True


def _label_common_entries(
    con: duckdb.DuckDBPyConnection,
    *,
    latest: date,
    labeled_at: datetime,
) -> int:
    intraday = [policy for policy, cadence in POLICIES.items() if cadence != "nightly"]
    rows = con.execute(
        "SELECT nd.id,id.id,nd.ticker,nt.market_date,it.observed_at,it.policy_id "
        "FROM agent_evaluation_decisions nd "
        "JOIN agent_evaluation_traces nt ON nt.id=nd.trace_id "
        "JOIN agent_evaluation_decisions id ON id.ticker=nd.ticker "
        "JOIN agent_evaluation_traces it ON it.id=id.trace_id AND it.market_date=nt.market_date "
        "WHERE nt.policy_id='nightly_opportunity_tool_v1' "
        "AND it.policy_id IN (?,?) AND nd.decision<>'unavailable' "
        "AND id.decision<>'unavailable' ORDER BY nt.market_date,nd.ticker,it.window_id",
        intraday,
    ).fetchall()
    inserted = 0
    for nightly_id, intraday_id, ticker, market_date, observed_at, policy_id in rows:
        if not in_evaluation_cohort(policy_id, observed_at):
            continue
        boundary = max(market_date, observed_at.date())
        sessions = [item[0] for item in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? AND date<=? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date LIMIT 20",
            [boundary, latest, labeled_at],
        ).fetchall()]
        for horizon in HORIZONS:
            if len(sessions) < horizon:
                continue
            outcome = _label_outcome(con, ticker, sessions[:horizon], labeled_at)
            if outcome is None:
                continue
            for decision_id in (int(nightly_id), int(intraday_id)):
                inserted += _insert_v2_label(
                    con, decision_id, horizon, outcome, labeled_at
                )
    return inserted


def _label_p15_entries(
    con: duckdb.DuckDBPyConnection,
    *,
    latest: date,
    labeled_at: datetime,
) -> int:
    rows = con.execute(
        "SELECT d.id,d.ticker,t.market_date FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE t.policy_id='p15-scoring-v1' ORDER BY d.id"
    ).fetchall()
    inserted = 0
    for decision_id, ticker, market_date in rows:
        sessions = [item[0] for item in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? AND date<=? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date LIMIT 20",
            [market_date, latest, labeled_at],
        ).fetchall()]
        for horizon in HORIZONS:
            if len(sessions) < horizon:
                continue
            outcome = _label_outcome(con, ticker, sessions[:horizon], labeled_at)
            if outcome is None:
                continue
            inserted += _insert_v2_label(
                con, int(decision_id), horizon, outcome, labeled_at,
                label_basis=NEXT_SESSION_OPEN_BASIS,
            )
    return inserted


def label_mature(con: duckdb.DuckDBPyConnection, *, labeled_at: datetime) -> dict:
    """Append every newly mature price label; never expose or rewrite immature horizons."""
    init_schema(con)
    inserted = 0
    latest = con.execute("SELECT MAX(date) FROM prices WHERE ticker = 'SPY'").fetchone()[0]
    if latest is None:
        return {"inserted": 0, "latest_market_date": None}
    rows = con.execute(
        "SELECT d.id,d.ticker,t.market_date,t.cadence,t.observed_at,d.decision,t.policy_id "
        "FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id = d.trace_id ORDER BY d.id"
    ).fetchall()
    for decision_id, ticker, market_date, cadence, observed_at, decision, policy_id in rows:
        if (
            decision == "unavailable"
            or policy_id == "p15-scoring-v1"
            or not in_evaluation_cohort(policy_id, observed_at)
        ):
            continue
        label_after = market_date if cadence == "nightly" else observed_at.date()
        sessions = [item[0] for item in con.execute(
            "SELECT DISTINCT date FROM prices WHERE ticker = 'SPY' AND date > ? "
            "AND date <= ? ORDER BY date LIMIT 20", [label_after, latest]
        ).fetchall()]
        for horizon in HORIZONS:
            if len(sessions) < horizon:
                continue
            if con.execute(
                "SELECT 1 FROM agent_evaluation_labels WHERE decision_id=? AND horizon_sessions=?",
                [decision_id, horizon],
            ).fetchone():
                continue
            entry_date, exit_date = sessions[0], sessions[horizon - 1]
            asset = con.execute(
                "SELECT date, open, high, low, close FROM prices WHERE ticker=? "
                "AND date>=? AND date<=? ORDER BY date", [ticker, entry_date, exit_date]
            ).fetchall()
            spy = con.execute(
                "SELECT date, open, high, low, close FROM prices WHERE ticker='SPY' "
                "AND date>=? AND date<=? ORDER BY date", [entry_date, exit_date]
            ).fetchall()
            if len(asset) != horizon or len(spy) != horizon or asset[0][1] in (None, 0):
                continue
            entry, exit_close = float(asset[0][1]), float(asset[-1][4])
            asset_return = exit_close / entry - 1
            spy_return = float(spy[-1][4]) / float(spy[0][1]) - 1
            net_return = exit_close * 0.999 / (entry * 1.001) - 1
            spy_net = float(spy[-1][4]) * 0.999 / (float(spy[0][1]) * 1.001) - 1
            lows = [float(item[3]) / entry - 1 for item in asset if item[3] is not None]
            highs = [float(item[2]) / entry - 1 for item in asset if item[2] is not None]
            prefix = [(item[0].isoformat(), *item[1:]) for item in asset]
            body = {
                "schema_version": LABEL_SCHEMA_VERSION, "decision_id": int(decision_id),
                "horizon_sessions": horizon, "entry_date": entry_date.isoformat(),
                "exit_date": exit_date.isoformat(), "entry_open": entry,
                "exit_close": exit_close, "asset_return": asset_return,
                "spy_return": spy_return, "excess_return": asset_return - spy_return,
                "maximum_adverse_excursion": min(lows),
                "maximum_favorable_excursion": max(highs),
                "round_trip_cost_bps": ROUND_TRIP_COST_BPS, "net_return": net_return,
                "net_excess_return": net_return - spy_net,
                "price_prefix_sha256": canonical_sha256(prefix),
            }
            con.execute(
                "INSERT INTO agent_evaluation_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [_next_id(con, "agent_evaluation_labels"), LABEL_SCHEMA_VERSION,
                 decision_id, horizon, entry_date, exit_date, entry, exit_close,
                 asset_return, spy_return, asset_return - spy_return, min(lows), max(highs),
                 body["price_prefix_sha256"], _timestamp(labeled_at), canonical_sha256(body),
                 ROUND_TRIP_COST_BPS, net_return, net_return - spy_net],
            )
            inserted += 1
    v2_latest = con.execute(
        f"SELECT MAX(date) FROM prices WHERE ticker='SPY' AND fetched_at IS NOT NULL "
        f"AND fetched_at<=? AND {REAL_BAR_SQL}",
        [_timestamp(labeled_at)],
    ).fetchone()[0]
    v2_inserted = 0
    if v2_latest is not None:
        v2_inserted = _label_common_entries(
            con, latest=v2_latest, labeled_at=labeled_at
        )
        v2_inserted += _label_p15_entries(
            con, latest=v2_latest, labeled_at=labeled_at
        )
    return {
        "inserted": inserted,
        "v2_inserted": v2_inserted,
        "latest_market_date": latest.isoformat(),
    }


def link_execution(
    con: duckdb.DuckDBPyConnection, *, assessment_id: int, tool_attempt_id: int,
    order_id: int | None, linked_at: datetime,
) -> dict:
    """Append one immutable trace-to-tool/order link, or verify exact replay."""
    row = con.execute(
        "SELECT d.id, t.trace_sha256, d.decision_sha256 FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id WHERE d.source_assessment_id=?",
        [assessment_id],
    ).fetchone()
    if row is None:
        raise EvaluationError("evaluation decision for tool attempt is unavailable")
    decision_id, trace_sha, decision_sha = row
    body = {"decision_sha256": decision_sha, "trace_sha256": trace_sha,
            "tool_attempt_id": tool_attempt_id, "order_id": order_id}
    digest = canonical_sha256(body)
    existing = con.execute(
        "SELECT tool_attempt_id,order_id,link_sha256 FROM agent_evaluation_execution_links "
        "WHERE decision_id=?", [decision_id]
    ).fetchone()
    if existing is not None:
        if existing != (tool_attempt_id, order_id, digest):
            raise EvaluationError("evaluation execution link differs from replay")
        return {"decision_id": int(decision_id), "replayed": True}
    next_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM agent_evaluation_execution_links"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO agent_evaluation_execution_links VALUES (?,?,?,?,?,?)",
        [next_id, decision_id, tool_attempt_id, order_id, _timestamp(linked_at), digest],
    )
    return {"decision_id": int(decision_id), "replayed": False}


def _complete_schema(con: duckdb.DuckDBPyConnection, names: tuple[str, ...], label: str) -> bool:
    present = [table_exists(con, name) for name in names]
    if any(present) and not all(present):
        raise EvaluationError(f"P15 {label} schema is incomplete")
    return all(present)


def validate_p15_evidence(
    con: duckdb.DuckDBPyConnection, generated_at: datetime | None = None,
) -> None:
    """Fail closed if stored P15 scoring or label identities no longer replay."""
    generated_at = generated_at or datetime.now(timezone.utc)
    p15_evidence_validation.enforce_bounds(con, EvaluationError)
    scoring_schema = _complete_schema(con, (
        "agent_evaluation_traces", "agent_evaluation_decisions", "agent_evaluation_labels_v2"
    ), "scoring")
    preopen_schema = _complete_schema(con, (
        "p15_preopen_runs", "p15_preopen_decisions", "p15_preopen_news_responses",
        "p15_execution_quality"
    ), "pre-open")
    book_schema = _complete_schema(con, (
        "p15_book_contracts", "p15_book_state", "p15_order_intents", "p15_position_rules",
        "p15_limit_attempts", "p15_book_windows", "p15_book_fills", "p15_limit_labels"
    ), "book")
    event_schema = _complete_schema(con, (
        "p15_event_source_state", "p15_event_triggers", "p15_event_windows",
        "p15_event_calls", "p15_event_decisions", "p15_event_labels"
    ), "event")
    if not scoring_schema:
        if preopen_schema or book_schema or event_schema:
            raise EvaluationError("P15 scoring schema is missing")
        return
    if preopen_schema and not book_schema:
        raise EvaluationError("P15 pre-open book schema is missing")
    p15_evidence_validation.validate_links(con, EvaluationError)
    p15_evidence_validation.validate_common_labels(
        con, generated_at, EvaluationError, _label_outcome
    )
    cursor = con.execute(
        "SELECT * FROM agent_evaluation_traces WHERE policy_id='p15-scoring-v1' ORDER BY id"
    )
    columns = [item[0] for item in cursor.description]
    for values in cursor.fetchall():
        row = dict(zip(columns, values, strict=True))
        source_refs, input_payload, output_payload = map(
            json.loads, (row["source_refs"], row["input_payload"], row["output_payload"])
        )
        bundle, context = input_payload["universe"], input_payload["context"]
        bundle_sha = bundle["bundle_sha256"]
        expected_refs = [{"kind": "p15_universe", "sha256": bundle_sha}, *[
            {"kind": "news_receipt", "ticker": item["ticker"],
             "sha256": item["receipt_sha256"]} for item in context["news_receipts"]
        ]]
        identity = {key: row[key] for key in (
            "schema_version", "window_id", "policy_id", "cadence", "prompt_role",
            "source_kind", "source_identifier", "request_sha256", "response_id", "model",
            "model_version", "instructions_sha256", "toolset_sha256",
            "model_catalog_entry_sha256", "proxy_source_sha256", "traecli_runtime",
            "upstream_model_family", "upstream_request_id", "latency_ms", "terminal_status",
            "execution_authority",
        )}
        identity.update(
            market_date=row["market_date"].isoformat(),
            observed_at=row["observed_at"].isoformat(),
            completed_at=row["completed_at"].isoformat(),
            information_cutoff_at=row["information_cutoff_at"].isoformat(),
            source_refs_sha256=canonical_sha256(source_refs),
            input_sha256=row["input_sha256"], output_sha256=row["output_sha256"],
            usage={"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
                   "total_tokens": row["total_tokens"]},
        )
        if (source_refs != expected_refs or canonical_sha256({
                key: value for key, value in bundle.items() if key != "bundle_sha256"
                }) != bundle_sha or canonical_sha256(input_payload) != row["input_sha256"]
                or canonical_sha256(output_payload) != row["output_sha256"]
                or canonical_sha256(identity) != row["trace_sha256"]):
            raise EvaluationError("P15 trace evidence differs")
        if not all(table_exists(con, table) for table in (
            "p15_scoring_runs", "p15_scoring_samples", "p15_scoring_news_responses"
        )):
            raise EvaluationError("P15 scoring source ledger is missing")
        run = con.execute(
            "SELECT id,universe_payload,universe_sha256,context_payload,context_sha256,status,"
            "information_cutoff_at,completed_at,aggregate_trace_sha256 FROM p15_scoring_runs "
            "WHERE market_date=?", [row["market_date"]]
        ).fetchone()
        if (run is None or row["source_kind"] != "p15_scoring_run"
                or row["source_identifier"] != str(run[0])
                or run[5] != "completed" or run[8] != row["trace_sha256"]
                or json.loads(run[1]) != bundle or json.loads(run[3]) != context
                or canonical_sha256(bundle) != run[2] or canonical_sha256(context) != run[4]
                or run[6] != row["information_cutoff_at"] or run[7] != row["completed_at"]):
            raise EvaluationError("P15 scoring run evidence differs")
        samples = con.execute(
            "SELECT chunk_index,sample_index,permutation_seed,ticker_order,request_payload,"
            "request_sha256,status,response_id,response_payload,response_sha256,model,model_version,"
            "proxy_version,proxy_source_sha256,traecli_runtime,upstream_model_family,"
            "upstream_request_id,model_catalog_entry_sha256,input_tokens,output_tokens,total_tokens,"
            "started_at,completed_at FROM p15_scoring_samples WHERE run_id=? "
            "ORDER BY chunk_index,sample_index", [run[0]]
        ).fetchall()
        expected_sample_count = math.ceil(len(context["candidates"]) / 10) * 3
        expected_grid = {(chunk, sample) for chunk in range(math.ceil(
            len(context["candidates"]) / 10)) for sample in range(3)}
        if len(samples) != expected_sample_count or {(item[0], item[1]) for item in samples} \
                != expected_grid:
            raise EvaluationError("P15 scoring sample set is incomplete")
        sample_ids, usage = [], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        model_identity = agent_model_client.identity(role="p15_scoring")
        for sample_row in samples:
            (chunk, sample, seed, ticker_order, request, request_sha, status, response_id,
             response, response_sha, model, model_version, proxy_version, proxy_sha, runtime,
             upstream_family, upstream_id, catalog_sha, input_tokens, output_tokens, total_tokens,
             sample_started, sample_completed) = sample_row
            request_payload = json.loads(request)
            request_input = json.loads(request_payload["input"])
            expected_chunk = {item["ticker"]: item for item in context["candidates"][
                chunk * 10:(chunk + 1) * 10
            ]}
            expected_seed = int.from_bytes(hashlib.sha256(
                f"p15-scoring-v1:{row['market_date'].isoformat()}:{chunk}:{sample}".encode()
            ).digest()[:8], "big") & ((1 << 63) - 1)
            if (request_input["chunk_index"] != chunk or request_input["sample_index"] != sample
                    or request_input["permutation_seed"] != seed or seed != expected_seed
                    or json.loads(ticker_order) != [item["ticker"]
                                                    for item in request_input["candidates"]]
                    or {item["ticker"] for item in request_input["candidates"]}
                    != set(expected_chunk)
                    or any(item != expected_chunk[item["ticker"]]
                           for item in request_input["candidates"])
                    or agent_model_client.p15_scoring_request_payload(request_input)
                    != request_payload
                    or canonical_sha256(request_payload) != request_sha
                    or status not in {"completed", "failed"}
                    or sample_completed is None or sample_completed < sample_started
                    or (status == "completed" and (response is None or response_sha is None))
                    or (response is not None and canonical_sha256(json.loads(response))
                        != response_sha)):
                raise EvaluationError("P15 scoring sample evidence differs")
            if status == "completed" and (model != model_identity["model"]
                    or model_version != model_identity["model_version"]
                    or proxy_version != model_identity["required_proxy_version"]
                    or proxy_sha != model_identity["required_proxy_source_sha256"]
                    or runtime != model_identity["required_traecli_runtime"]
                    or upstream_family != agent_model_client.UPSTREAM_MODEL_FAMILY
                    or catalog_sha != model_identity["model_catalog_entry_sha256"]):
                raise EvaluationError("P15 scoring sample model identity differs")
            if response is not None:
                retained = json.loads(response)
                if any(retained.get(key) != value for key, value in {
                    "response_id": response_id, "model": model, "model_version": model_version,
                    "proxy_version": proxy_version, "proxy_source_sha256": proxy_sha,
                    "traecli_runtime": runtime, "upstream_model_family": upstream_family,
                    "upstream_request_id": upstream_id,
                    "model_catalog_entry_sha256": catalog_sha,
                    "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                              "total_tokens": total_tokens},
                }.items()):
                    raise EvaluationError("P15 scoring sample response differs")
            sample_ids.append({"chunk_index": chunk, "sample_index": sample,
                               "request_sha256": request_sha, "response_id": response_id,
                               "upstream_request_id": upstream_id, "status": status})
            for key, value in zip(usage, (input_tokens, output_tokens, total_tokens), strict=True):
                usage[key] += int(value or 0)
        digest = canonical_sha256(sample_ids)
        if (row["request_sha256"] != canonical_sha256([item["request_sha256"]
                                                        for item in sample_ids])
                or row["response_id"] != f"aggregate-{digest[:32]}"
                or row["upstream_request_id"] != f"aggregate-{digest[:32]}"
                or usage != {key: row[key] for key in usage}):
            raise EvaluationError("P15 scoring aggregate identity differs")
        receipts = con.execute(
            "SELECT ticker,endpoint,requested_at,received_at,http_status,content_type,"
            "response_sha256,response_body,receipt_sha256 FROM p15_scoring_news_responses "
            "WHERE run_id=? ORDER BY ticker", [run[0]]
        ).fetchall()
        for receipt in receipts:
            receipt_identity = {"ticker": receipt[0], "endpoint": receipt[1],
                                "requested_at": receipt[2].replace(
                                    tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                                "received_at": receipt[3].replace(
                                    tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                                "http_status": receipt[4], "content_type": receipt[5],
                                "response_sha256": hashlib.sha256(bytes(receipt[7])).hexdigest()}
            if receipt_identity["response_sha256"] != receipt[6] \
                    or canonical_sha256(receipt_identity) != receipt[8]:
                raise EvaluationError("P15 scoring news evidence differs")
        if {receipt[8] for receipt in receipts} != {item["receipt_sha256"]
                                                    for item in context["news_receipts"]}:
            raise EvaluationError("P15 scoring news receipt set is incomplete")
        decisions = con.execute(
            "SELECT ticker,assessment_sha256,decision_payload,decision_sha256 "
            "FROM agent_evaluation_decisions WHERE trace_id=? ORDER BY ticker", [row["id"]]
        ).fetchall()
        expected = {item["ticker"]: item for item in output_payload["assessments"]}
        if len(expected) != len(output_payload["assessments"]) or set(expected) != {
                item[0] for item in decisions}:
            raise EvaluationError("P15 trace decision set differs")
        for ticker, assessment_sha, raw, decision_sha in decisions:
            payload = json.loads(raw)
            assessment = payload.get("assessment_sha256") or canonical_sha256(payload)
            expected_item = expected[ticker]
            if (assessment != assessment_sha
                    or any(payload.get(key if key != "action" else "decision") != value
                           for key, value in expected_item.items())
                    or canonical_sha256({"trace_sha256": row["trace_sha256"],
                                         "ticker": ticker,
                                         "assessment_sha256": assessment_sha}) != decision_sha):
                raise EvaluationError("P15 decision evidence differs")
    labels = con.execute(
        "SELECT l.*,d.ticker AS source_ticker,t.market_date AS source_market_date "
        "FROM agent_evaluation_labels_v2 l JOIN agent_evaluation_decisions d "
        "ON d.id=l.decision_id JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE t.policy_id='p15-scoring-v1' ORDER BY l.id"
    )
    columns = [item[0] for item in labels.description]
    for values in labels.fetchall():
        row = dict(zip(columns, values, strict=True))
        body = {key: row[key] for key in (
            "schema_version", "decision_id", "horizon_sessions", "label_basis", "entry_open",
            "exit_close", "asset_return", "spy_return", "excess_return",
            "maximum_adverse_excursion", "maximum_favorable_excursion", "price_prefix_sha256",
            "missing_bar_status", "round_trip_cost_bps", "net_return", "net_excess_return",
        )}
        body.update(entry_date=row["entry_date"].isoformat(),
                    exit_date=row["exit_date"].isoformat())
        if canonical_sha256(body) != row["label_sha256"]:
            raise EvaluationError("P15 label evidence differs")
        sessions = [item[0] for item in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date LIMIT ?", [row["source_market_date"], row["labeled_at"],
                                      row["horizon_sessions"]]
        ).fetchall()]
        if len(sessions) != row["horizon_sessions"]:
            raise EvaluationError("P15 label maturity evidence differs")
        outcome = _label_outcome(
            con, row["source_ticker"], sessions,
            row["labeled_at"].replace(tzinfo=timezone.utc),
        )
        expected_basis = None if outcome is None else outcome.get(
            "label_basis_override", "next_session_open"
        )
        expected_body = None if outcome is None else {
            "schema_version": row["schema_version"], "decision_id": row["decision_id"],
            "horizon_sessions": row["horizon_sessions"], "label_basis": expected_basis,
            **{key: value.isoformat() if isinstance(value, date) else value
               for key, value in outcome.items() if key != "label_basis_override"},
            "missing_bar_status": outcome["missing_bar_status"],
        }
        if expected_body is None or canonical_sha256(expected_body) != row["label_sha256"]:
            raise EvaluationError("P15 label source evidence differs")
    if preopen_schema:
        p15_evidence_validation.validate_preopen(con, generated_at, EvaluationError)
    if book_schema:
        from sim import p15_books
        rows = con.execute(
            "SELECT c.portfolio_id,c.mechanics_version,c.config_sha256,p.config "
            "FROM p15_book_contracts c JOIN portfolios p ON p.id=c.portfolio_id ORDER BY 1"
        ).fetchall()
        if {row[0] for row in rows} != set(p15_books.BOOK_IDS):
            raise EvaluationError("P15 book evidence differs")
        for portfolio_id, version, digest, raw in rows:
            config = p15_books._config(portfolio_id)
            if (version != p15_books.MECHANICS_VERSION or digest != canonical_sha256(config)
                    or json.loads(raw) != config):
                raise EvaluationError("P15 book evidence differs")
        mismatch = con.execute(
            "SELECT COUNT(*) FROM p15_book_fills f LEFT JOIN sim_fills s ON s.order_id=f.order_id "
            "WHERE s.order_id IS NULL OR (f.portfolio_id,f.ticker,f.side,f.qty,f.fill_date,"
            "f.open_px,f.fill_px,f.slippage_bps,f.cost_bps) IS DISTINCT FROM "
            "(s.portfolio_id,s.ticker,s.side,s.qty,s.fill_date,s.open_px,s.fill_px,"
            "s.slippage_bps,s.cost_bps)"
        ).fetchone()[0]
        mismatch += con.execute(
            "SELECT COUNT(*) FROM p15_book_windows w LEFT JOIN sim_equity e "
            "ON e.portfolio_id=w.portfolio_id AND e.date=w.market_date "
            "WHERE e.portfolio_id IS NULL OR (w.equity,w.cash,w.n_positions) "
            "IS DISTINCT FROM (e.equity,e.cash,e.n_positions)"
        ).fetchone()[0]
        mismatch += con.execute(
            "SELECT COUNT(*) FROM p15_order_intents i LEFT JOIN sim_orders o ON o.id=i.sim_order_id "
            "WHERE i.sim_order_id IS NOT NULL AND (o.id IS NULL OR "
            "(i.portfolio_id,i.ticker,i.side,i.qty,i.signal_date,i.status) IS DISTINCT FROM "
            "(o.portfolio_id,o.ticker,o.side,o.qty,o.signal_date,o.status))"
        ).fetchone()[0]
        if mismatch:
            raise EvaluationError("P15 book runtime evidence differs")
        p15_evidence_validation.validate_book_links(con, EvaluationError)
        for values in con.execute(
            "SELECT l.intent_id,l.attempt_date,l.horizon_sessions,l.entry_px,l.exit_date,"
            "l.exit_close,l.net_return,l.spy_net_return,l.net_excess_return,"
            "l.price_prefix_sha256,l.labeled_at,l.label_sha256,i.ticker "
            "FROM p15_limit_labels l JOIN p15_order_intents i ON i.id=l.intent_id ORDER BY l.intent_id"
        ).fetchall():
            identity = {"intent_id": int(values[0]), "attempt_date": values[1].isoformat(),
                        "horizon_sessions": int(values[2]), "entry_px": values[3],
                        "exit_date": values[4].isoformat(), "exit_close": values[5],
                        "net_return": values[6], "spy_net_return": values[7],
                        "net_excess_return": values[8], "price_prefix_sha256": values[9]}
            sessions = [row[0] for row in con.execute(
                f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? "
                f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
                "ORDER BY date LIMIT 5", [values[1], values[10]]
            ).fetchall()]
            outcome = _label_outcome(
                con, values[12], sessions, values[10].replace(tzinfo=timezone.utc)
            ) if len(sessions) == 5 else None
            expected = None if outcome is None else {
                "intent_id": int(values[0]), "attempt_date": values[1].isoformat(),
                "horizon_sessions": 5, "entry_px": values[3],
                "exit_date": outcome["exit_date"].isoformat(),
                "exit_close": outcome["exit_close"],
                "net_return": float(outcome["exit_close"]) * 0.999 / values[3] - 1,
                "spy_net_return": outcome["net_return"] - outcome["net_excess_return"],
                "net_excess_return": (float(outcome["exit_close"]) * 0.999 / values[3] - 1)
                - (outcome["net_return"] - outcome["net_excess_return"]),
                "price_prefix_sha256": outcome["price_prefix_sha256"],
            }
            if (canonical_sha256(identity) != values[11] or expected is None
                    or canonical_sha256(expected) != values[11]):
                raise EvaluationError("P15 limit label evidence differs")
    if event_schema:
        p15_evidence_validation.validate_events(con, EvaluationError, _label_outcome)


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Bounded coverage and maturity summary, never raw prompts or responses."""
    if any(not table_exists(con, table) for table in (
        "agent_evaluation_traces", "agent_evaluation_decisions",
        "agent_evaluation_labels", "agent_evaluation_execution_links",
    )):
        return {"schema_version": 1, "status": "not_initialized",
                "trace_count": 0, "decision_count": 0, "label_count": 0,
                "execution_link_count": 0,
                "horizons": list(HORIZONS), "policies": [],
                "performance_claim": "none"}
    policies = []
    for policy_id, cadence, traces, decisions, labels in con.execute(
        "SELECT t.policy_id, t.cadence, COUNT(DISTINCT t.id), COUNT(DISTINCT d.id), "
        "COUNT(DISTINCT l.id) FROM agent_evaluation_traces t "
        "LEFT JOIN agent_evaluation_decisions d ON d.trace_id=t.id "
        "LEFT JOIN agent_evaluation_labels l ON l.decision_id=d.id "
        "GROUP BY t.policy_id,t.cadence ORDER BY t.policy_id"
    ).fetchall():
        policies.append({"policy_id": policy_id, "cadence": cadence,
                         "trace_count": int(traces), "decision_count": int(decisions),
                         "label_count": int(labels)})
    totals = con.execute(
        "SELECT (SELECT COUNT(*) FROM agent_evaluation_traces), "
        "(SELECT COUNT(*) FROM agent_evaluation_decisions), "
        "(SELECT COUNT(*) FROM agent_evaluation_labels), "
        "(SELECT COUNT(*) FROM agent_evaluation_execution_links)"
    ).fetchone()
    return {"schema_version": 1, "status": "capturing" if totals[0] else "waiting",
            "trace_count": int(totals[0]), "decision_count": int(totals[1]),
            "label_count": int(totals[2]), "execution_link_count": int(totals[3]),
            "horizons": list(HORIZONS),
            "policies": policies, "performance_claim": "none"}
