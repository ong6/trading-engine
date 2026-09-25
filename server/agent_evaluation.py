"""Canonical append-only traces and delayed labels for forward agent evaluation."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists

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
