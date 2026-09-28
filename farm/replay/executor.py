"""In-tree PREOPEN/SCORE execution and deterministic replay labels."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Sequence

from engine.lib.provenance import canonical_sha256
from farm.replay import p15_adapter
from farm.replay.asof import (
    SplitQuarantineError,
    label_price_point,
    label_split_normalized_return,
)
from farm.replay.store import append_exact
from server import agent_evaluation, agent_model_client
from sim import nyse, p15_books

SCORE_CHUNK_SIZE = 10
LABEL_HORIZONS = (1, 5, 10, 20)
CENSORED_PREFIX = "censored:"


def init_executor_schema(con) -> None:
    agent_evaluation.init_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_decisions (
            decision_id VARCHAR PRIMARY KEY,
            source_decision_id BIGINT NOT NULL UNIQUE,
            decision_session DATE NOT NULL,
            ticker VARCHAR NOT NULL,
            security_id VARCHAR NOT NULL,
            expected_excess_bp DOUBLE,
            payload_json VARCHAR NOT NULL)"""
    )


def _held(con) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT ticker FROM sim_positions WHERE portfolio_id IN (?,?,?) AND qty>0",
            list(p15_books.BOOK_IDS),
        ).fetchall()
    }


def _seed(cohort_id: str, policy_id: str, session: date, chunk: int, sample: int) -> int:
    digest = hashlib.sha256(
        f"{cohort_id}:{policy_id}:{session.isoformat()}:{chunk}:{sample}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def prepare_score(
    con,
    *,
    cohort_id: str,
    policy_id: str,
    session: date,
    cutoff: datetime,
    news_rows: Sequence[Mapping],
    fact_rows: Sequence[Mapping],
    sample_count: int,
) -> dict:
    if sample_count < 1:
        raise ValueError("invalid_replay_sample_count")
    bundle = p15_adapter.gate_candidates(
        p15_adapter.universe(
            con, session, held_tickers=_held(con), information_cutoff_at=cutoff
        )
    )
    context, allowed = p15_adapter.build_context(
        bundle, {"status": "historical_backfill", "observations": list(news_rows)},
        cutoff, list(fact_rows),
    )
    context.update(information_cutoff_at=cutoff.isoformat(), news_receipts=[])
    chunks = []
    for chunk_index, start in enumerate(range(0, len(context["candidates"]), SCORE_CHUNK_SIZE)):
        candidates = context["candidates"][start:start + SCORE_CHUNK_SIZE]
        used_orders: set[tuple[str, ...]] = set()
        requests = []
        for sample_index in range(sample_count):
            seed = _seed(cohort_id, policy_id, session, chunk_index, sample_index)
            payload = p15_adapter.request_input(
                bundle, context, candidates, chunk_index=chunk_index,
                sample_index=sample_index, seed=seed, cutoff=cutoff,
                used_orders=used_orders,
            )
            requests.append(payload)
        chunks.append({"candidates": candidates, "requests": requests})
    return {
        "kind": "score", "bundle": bundle, "context": context,
        "allowed": allowed, "chunks": chunks, "sample_count": sample_count,
    }


def execute_score(
    plan: Mapping,
    generate: Callable[[dict], agent_model_client.ConnectorResult],
) -> dict:
    decisions, samples = [], []
    for chunk in plan["chunks"]:
        validated, failure = [], None
        for payload in chunk["requests"]:
            request = agent_model_client.p15_scoring_request_payload(payload)
            try:
                response = generate(payload)
                if response.request_sha256 != canonical_sha256(request):
                    raise ValueError("replay_scoring_request_identity_differs")
                p15_adapter.validate_scoring_identity(response)
                validated.append(
                    p15_adapter.validate_output(
                        response.output, chunk["candidates"], plan["allowed"]
                    )
                )
                samples.append({
                    "status": "completed", "request_sha256": response.request_sha256,
                    "response": asdict(response),
                })
            except (agent_model_client.ConnectorError, TypeError, ValueError) as exc:
                failure = str(exc)
                samples.append({
                    "status": "failed", "request_sha256": canonical_sha256(request),
                    "reason": failure,
                })
                break
        decisions.extend(
            p15_adapter.aggregate(chunk["candidates"], validated)
            if failure is None and len(validated) == plan["sample_count"]
            else p15_adapter.unavailable(chunk["candidates"], failure or "incomplete_sample_set")
        )
    return {
        "status": "completed" if decisions else "not_applicable",
        "kind": "score", "bundle": plan["bundle"], "context": plan["context"],
        "decisions": decisions, "samples": samples,
    }


def prepare_preopen(
    con,
    *,
    session: date,
    cutoff: datetime,
    news_rows: Sequence[Mapping],
    fact_rows: Sequence[Mapping],
) -> dict:
    pending = p15_adapter.preopen_pending(con, session)
    observations, facts = p15_adapter.visible_p15_inputs(news_rows, fact_rows, cutoff=cutoff)
    model_intents, allowed = [], {}
    for item in pending:
        if item["portfolio_id"] not in p15_adapter.PREOPEN_MODEL_BOOKS:
            continue
        decision_at = item["decision_at"].replace(tzinfo=timezone.utc)
        headlines = [
            row for row in observations
            if row.get("ticker") == item["ticker"]
            and decision_at < datetime.fromisoformat(
                str(row["retrieved_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc) <= cutoff
        ]
        event_facts = [
            row for row in facts
            if row.get("ticker") in {"SPY", item["ticker"]}
            and decision_at < datetime.fromisoformat(
                str(row["available_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc) <= cutoff
        ]
        evidence = set(item["assessment"].get("evidence_ids", ()))
        evidence.update(row["evidence_id"] for row in [*headlines, *event_facts])
        allowed[item["intent_id"]] = evidence
        model_intents.append({
            "intent_id": item["intent_id"], "portfolio_id": item["portfolio_id"],
            "ticker": item["ticker"], "limit_px": item["limit_px"],
            "nightly_assessment": item["assessment"], "new_headlines": headlines,
            "new_event_facts": event_facts, "allowed_evidence_ids": sorted(evidence),
        })
    controls = [
        {"intent_id": row["intent_id"], "portfolio_id": row["portfolio_id"],
         "ticker": row["ticker"]}
        for row in pending if row["portfolio_id"] == "p15_rule_control"
    ]
    return {
        "kind": "preopen", "payload": {
            "schema_version": 1, "policy_id": "p15-preopen-v1",
            "session_date": session.isoformat(), "cutoff_at": cutoff.isoformat(),
            "execution_authority": "cancel_only", "intents": model_intents,
            "control_noops": controls, "receipt_sha256s": [],
        },
        "allowed": allowed,
    }


def execute_preopen(
    plan: Mapping,
    generate: Callable[[dict], agent_model_client.ConnectorResult],
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    payload, allowed = plan["payload"], plan["allowed"]
    decisions, status = [], "completed"
    if payload["intents"]:
        started = monotonic()
        try:
            response = generate(payload)
            p15_adapter.validate_preopen_identity(response, payload)
            response_row = asdict(response)
            if monotonic() - started >= 20 * 60:
                status = "late"
                decisions = [
                    {"intent_id": row["intent_id"], "decision": "keep",
                     "reason": "pre-open response missed deadline",
                     "evidence_ids": sorted(allowed[row["intent_id"]])}
                    for row in payload["intents"]
                ]
            else:
                decisions = p15_adapter.validate_preopen_output(response.output, allowed)
        except (agent_model_client.ConnectorError, TypeError, ValueError) as exc:
            status = "unavailable"
            decisions = [
                {"intent_id": row["intent_id"], "decision": "keep", "reason": str(exc),
                 "evidence_ids": sorted(allowed[row["intent_id"]])}
                for row in payload["intents"]
            ]
            response_row = None
    else:
        response_row = None
    decisions.extend(
        {**row, "decision": "keep", "reason": "rule_control_noop", "evidence_ids": []}
        for row in payload["control_noops"]
    )
    by_id = {
        row["intent_id"]: row for row in [*payload["intents"], *payload["control_noops"]]
    }
    return {
        "status": status if decisions else "not_applicable", "kind": "preopen",
        "payload": payload, "response": response_row,
        "decisions": [
            {**row, "portfolio_id": by_id[row["intent_id"]]["portfolio_id"],
             "ticker": by_id[row["intent_id"]]["ticker"]}
            for row in decisions
        ],
    }


def _aggregate_identity(samples: Sequence[Mapping]) -> tuple[dict, dict]:
    completed = [row["response"] for row in samples if row["status"] == "completed"]
    identity = agent_model_client.identity(role="p15_scoring")
    source = completed[0] if completed else {
        "model": identity["model"], "model_version": identity["model_version"],
        "proxy_source_sha256": identity["required_proxy_source_sha256"],
        "traecli_runtime": identity["required_traecli_runtime"],
        "upstream_model_family": agent_model_client.UPSTREAM_MODEL_FAMILY,
        "model_catalog_entry_sha256": identity["model_catalog_entry_sha256"],
    }
    usage = {
        key: sum(int(row.get("usage", {}).get(key, 0)) for row in completed)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    return source, usage


def apply_score(
    con,
    result: Mapping,
    *,
    cohort_id: str,
    policy_id: str,
    session: date,
    logical_at: datetime,
    security_ids: Mapping[str, str],
) -> int:
    if not result["decisions"]:
        return 0
    init_executor_schema(con)
    source, usage = _aggregate_identity(result["samples"])
    requests = [row["request_sha256"] for row in result["samples"]]
    aggregate_id = canonical_sha256(result["samples"])
    identity = agent_model_client.identity(role="p15_scoring")
    completed_at = logical_at + timedelta(microseconds=1)
    trace = {
        "window_id": f"replay:{cohort_id}:{policy_id}:{session.isoformat()}",
        "policy_id": "p15-scoring-v1", "cadence": "nightly",
        "prompt_role": policy_id, "market_date": session,
        "observed_at": logical_at, "completed_at": completed_at,
        "information_cutoff_at": logical_at, "source_kind": "p16_replay_score",
        "source_identifier": f"{cohort_id}:{policy_id}",
        "source_refs": [{"kind": "replay_bundle", "sha256": result["bundle"]["bundle_sha256"]}],
        "input_payload": {"universe": result["bundle"], "context": result["context"]},
        "output_payload": {"schema_version": 1, "assessments": result["decisions"]},
        "request_sha256": canonical_sha256(requests),
        "response_id": f"replay-{aggregate_id[:32]}",
        "model": source["model"], "model_version": source["model_version"],
        "instructions_sha256": identity["instructions_sha256"],
        "toolset_sha256": identity["toolset_sha256"],
        "model_catalog_entry_sha256": source["model_catalog_entry_sha256"],
        "proxy_source_sha256": source["proxy_source_sha256"],
        "traecli_runtime": source["traecli_runtime"],
        "upstream_model_family": source["upstream_model_family"],
        "upstream_request_id": f"replay-{aggregate_id[:32]}",
        "latency_ms": 0.0, "usage": usage, "terminal_status": "completed",
        "execution_authority": "historical_research_only",
        "decisions": [
            {**row, "decision": row["action"],
             "action": {"buy_candidate": "buy", "exit": "sell"}.get(row["action"], "none"),
             "horizon_sessions": 5, "confidence": row["p_outperform_5"] or 0.0}
            for row in result["decisions"]
        ],
    }
    recorded = agent_evaluation.record_trace(con, trace)
    rows = con.execute(
        "SELECT id,ticker,decision_payload FROM agent_evaluation_decisions "
        "WHERE trace_id=? ORDER BY ticker", [recorded["trace_id"]],
    ).fetchall()
    for decision_id, ticker, payload in rows:
        decoded = json.loads(payload)
        replay_id = f"{cohort_id}:{policy_id}:{decision_id}"
        stored = (
            replay_id, int(decision_id), session, ticker, security_ids.get(ticker, ticker),
            decoded.get("expected_excess_bp_5"), payload,
        )
        prior = con.execute(
            "SELECT * FROM replay_decisions WHERE decision_id=?", [replay_id]
        ).fetchone()
        if prior is None:
            con.execute("INSERT INTO replay_decisions VALUES (?,?,?,?,?,?,?)", stored)
        elif prior != stored:
            raise ValueError("replay_decision_conflict")
    return len(rows)


def apply_preopen(con, result: Mapping, *, session: date, logical_at: datetime) -> int:
    payload = {
        "input": result["payload"], "response": result["response"],
        "decisions": result["decisions"],
    }
    append_exact(
        con, record_type="replay_preopen", record_key=session.isoformat(),
        payload=payload, recorded_at=logical_at,
    )
    cancelled = 0
    for row in result["decisions"]:
        if row["decision"] != "cancel":
            continue
        changed = con.execute(
            "UPDATE p15_order_intents SET status='cancelled',reason='preopen_cancel' "
            "WHERE id=? AND status='pending' RETURNING id", [row["intent_id"]],
        ).fetchone()
        if changed is None:
            raise ValueError("replay_preopen_cancel_target_changed")
        cancelled += 1
    return cancelled


def _horizon_session(signal_session: date, horizon: int) -> date:
    current = nyse.next_session(signal_session)
    for _ in range(1, horizon):
        current = nyse.next_session(current)
    return current


def produce_labels(
    con,
    *,
    session: date,
    visible_at: datetime,
    reconstructed_bars: Sequence[Mapping],
    actions: Sequence[Mapping],
    knowledge_policy: str,
) -> int:
    """Append labels visible at this close; unlabelable ones are recorded as censored."""
    init_executor_schema(con)
    bars = {
        (str(row.get("security_id")), row.get("session") if isinstance(row.get("session"), date)
         else date.fromisoformat(str(row.get("session")))): row
        for row in reconstructed_bars
    }
    ticker_security = {
        str(row.get("ticker")): str(row.get("security_id")) for row in reconstructed_bars
    }
    spy_id = ticker_security.get("SPY")
    if spy_id is None:
        return 0
    inserted = 0
    decisions = con.execute(
        "SELECT decision_id,decision_session,security_id,expected_excess_bp "
        "FROM replay_decisions ORDER BY decision_session,decision_id"
    ).fetchall()
    for decision_id, decision_session, security_id, expected in decisions:
        entry_session = nyse.next_session(decision_session)
        for horizon in LABEL_HORIZONS:
            if _horizon_session(decision_session, horizon) != session:
                continue
            if con.execute(
                "SELECT 1 FROM replay_labels WHERE decision_id=? AND horizon=?",
                [decision_id, f"h{horizon}"],
            ).fetchone() is not None:
                continue
            asset_entry, asset_exit = bars.get((security_id, entry_session)), bars.get(
                (security_id, session)
            )
            spy_entry, spy_exit = bars.get((spy_id, entry_session)), bars.get((spy_id, session))
            status, excess = "terminal", None
            if None in (asset_entry, asset_exit):
                status = CENSORED_PREFIX + "missing_asset_bar"
            elif None in (spy_entry, spy_exit):
                status = CENSORED_PREFIX + "missing_spy_bar"
            else:
                entry_at = _phase_time(entry_session, "open")
                exit_at = _phase_time(session, "close")
                try:
                    asset_return = label_split_normalized_return(
                        security_id=security_id,
                        entry_point=label_price_point(asset_entry, "open"),
                        exit_point=label_price_point(asset_exit, "close"), entry_at=entry_at,
                        exit_at=exit_at, visible_at=visible_at, actions=actions,
                        knowledge_policy=knowledge_policy,
                    )
                    spy_return = label_split_normalized_return(
                        security_id=spy_id, entry_point=label_price_point(spy_entry, "open"),
                        exit_point=label_price_point(spy_exit, "close"), entry_at=entry_at,
                        exit_at=exit_at, visible_at=visible_at, actions=actions,
                        knowledge_policy=knowledge_policy,
                    )
                    excess = (asset_return - spy_return) * 10_000
                except SplitQuarantineError as exc:
                    status = CENSORED_PREFIX + str(exc).split(":", 1)[0]
            con.execute(
                "INSERT INTO replay_labels VALUES (?,?,?,?,?,?,?)",
                [decision_id, decision_session, f"h{horizon}",
                 visible_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                 status, expected, excess],
            )
            inserted += 1
    return inserted


def censored_label_counts(con) -> dict[str, int]:
    """Count censored labels by reason for the report's exclusion table."""
    rows = con.execute(
        "SELECT status,count(*) FROM replay_labels WHERE starts_with(status,?) "
        "GROUP BY status ORDER BY status", [CENSORED_PREFIX],
    ).fetchall()
    return {status[len(CENSORED_PREFIX):]: int(count) for status, count in rows}


def _phase_time(session: date, field: str) -> datetime:
    from farm.replay.runner import session_phases

    return session_phases(session)[field]
