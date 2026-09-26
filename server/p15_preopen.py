"""P15 cancel-only pre-open reassessment and post-open evidence capture."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import duckdb

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.util import table_exists
from sim import nyse, p15_books, p15_fills

from . import agent_model_client, daily_opportunity_news

POLICY_ID = "p15-preopen-v1"
BOOK_IDS = ("p15_ai_ranked", "p15_hybrid_veto")
LOCK_PATH = REPO_ROOT / ".p15-preopen.lock"
NIGHTLY_LOCK = REPO_ROOT / ".nightly.lock"
ET = ZoneInfo("America/New_York")
START = time(9, 5)
DEADLINE = time(9, 25)


class PreopenError(ValueError):
    """P15 pre-open input or retained evidence violates its contract."""


class _LateCommit(RuntimeError):
    def __init__(self, observed_at: datetime):
        self.observed_at = observed_at


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_preopen_runs (
        id BIGINT PRIMARY KEY, policy_id VARCHAR NOT NULL, session_date DATE NOT NULL,
        status VARCHAR NOT NULL, reason VARCHAR, input_payload VARCHAR NOT NULL,
        input_sha256 VARCHAR NOT NULL UNIQUE, response_payload VARCHAR,
        response_sha256 VARCHAR, started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP, run_sha256 VARCHAR UNIQUE,
        UNIQUE(policy_id,session_date))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_preopen_decisions (
        id BIGINT PRIMARY KEY, run_id BIGINT NOT NULL, intent_id BIGINT NOT NULL,
        portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        decision VARCHAR NOT NULL, reason VARCHAR NOT NULL,
        evidence_ids VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL UNIQUE,
        applied_at TIMESTAMP NOT NULL, UNIQUE(run_id,intent_id))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_preopen_news_responses (
        run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL,
        requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL,
        http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL,
        response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL,
        receipt_sha256 VARCHAR NOT NULL, PRIMARY KEY(run_id,ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_execution_quality (
        intent_id BIGINT PRIMARY KEY, sim_order_id BIGINT UNIQUE,
        decision_id BIGINT, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        side VARCHAR NOT NULL, order_role VARCHAR NOT NULL, decision_at TIMESTAMP,
        order_at TIMESTAMP NOT NULL, attempt_date DATE NOT NULL, status VARCHAR NOT NULL,
        decision_to_order_ms DOUBLE, order_to_attempt_sessions INTEGER NOT NULL,
        arrival_price DOUBLE NOT NULL, open_px DOUBLE, fill_px DOUBLE,
        gap_shortfall_bps DOUBLE, total_shortfall_bps DOUBLE, cost_bps DOUBLE,
        captured_at TIMESTAMP NOT NULL, quality_sha256 VARCHAR NOT NULL UNIQUE)"""
    )


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise PreopenError("pre-open timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _pending(con: duckdb.DuckDBPyConnection, session_date: date) -> list[dict]:
    if not table_exists(con, "agent_evaluation_decisions") or not table_exists(
        con, "agent_evaluation_traces"
    ):
        return []
    rows = con.execute(
        "SELECT i.id,i.portfolio_id,i.ticker,i.signal_date,i.limit_px,i.created_at,"
        "d.decision_payload,t.completed_at FROM p15_order_intents i "
        "JOIN agent_evaluation_decisions d ON d.id=i.decision_id "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE i.order_role='entry' AND i.status='pending' "
        "AND i.signal_date<? AND i.portfolio_id IN (?,?,?) ORDER BY i.id",
        [session_date, *p15_books.BOOK_IDS],
    ).fetchall()
    return [{
        "intent_id": int(row[0]), "portfolio_id": row[1], "ticker": row[2],
        "signal_date": row[3], "limit_px": float(row[4]), "created_at": row[5],
        "assessment": json.loads(row[6]), "decision_at": row[7],
    } for row in rows]


def _facts(con, ticker: str, decision_at: datetime, cutoff: datetime) -> list[dict]:
    if not table_exists(con, "bitemporal_facts"):
        return []
    rows = con.execute(
        "SELECT fact_type,event_at,available_at,source,normalized_payload,fact_sha256 "
        "FROM bitemporal_facts WHERE security_id=? AND available_at>? "
        "AND available_at<=? AND ingested_at<=? AND fact_type NOT LIKE 'intraday.%' "
        "AND fact_type NOT LIKE 'market.%' AND source!='tradingview_unofficial' "
        "QUALIFY revision=MAX(revision) OVER (PARTITION BY entity_id,fact_type,event_at) "
        "ORDER BY available_at,fact_sha256 LIMIT 20",
        [ticker, decision_at, cutoff.replace(tzinfo=None), cutoff.replace(tzinfo=None)],
    ).fetchall()
    return [{
        "fact_type": row[0], "event_at": row[1].isoformat(),
        "available_at": row[2].isoformat(), "source": row[3],
        "payload": json.loads(row[4]), "evidence_id": row[5],
    } for row in rows]


def _validate(output: object, allowed: dict[int, set[str]]) -> list[dict]:
    if not isinstance(output, dict) or set(output) != {"schema_version", "decisions"} \
            or type(output.get("schema_version")) is not int \
            or output["schema_version"] != 1 or not isinstance(output["decisions"], list):
        raise PreopenError("pre-open output shape is invalid")
    decisions, seen = [], set()
    for item in output["decisions"]:
        if not isinstance(item, dict) or set(item) != {
            "intent_id", "decision", "reason", "evidence_ids"
        }:
            raise PreopenError("pre-open decision shape is invalid")
        intent_id, evidence = item["intent_id"], item["evidence_ids"]
        if type(intent_id) is not int or intent_id not in allowed or intent_id in seen \
                or item["decision"] not in {"keep", "cancel"}:
            raise PreopenError("pre-open decision identity is invalid")
        if not isinstance(item["reason"], str) or not item["reason"].strip() or len(item["reason"]) > 500:
            raise PreopenError("pre-open reason is invalid")
        if not isinstance(evidence, list) or not evidence \
                or any(not isinstance(value, str) for value in evidence) \
                or len(evidence) != len(set(evidence)) \
                or not set(evidence) <= allowed[intent_id]:
            raise PreopenError("pre-open evidence is invalid")
        seen.add(intent_id)
        decisions.append(item)
    if seen != set(allowed):
        raise PreopenError("pre-open output does not cover every intent")
    return decisions


def _validate_identity(result: agent_model_client.ConnectorResult, payload: dict) -> None:
    identity = agent_model_client.identity(role="p15_preopen")
    if (result.model != identity["model"]
            or result.model_version != identity["model_version"]
            or result.proxy_version != identity["required_proxy_version"]
            or result.proxy_source_sha256 != identity["required_proxy_source_sha256"]
            or result.traecli_runtime != identity["required_traecli_runtime"]
            or result.upstream_model_family != agent_model_client.UPSTREAM_MODEL_FAMILY
            or result.model_catalog_entry_sha256 != identity["model_catalog_entry_sha256"]
            or result.request_sha256 != canonical_sha256(
                agent_model_client.p15_preopen_request_payload(payload)
            )):
        raise PreopenError("pre-open model identity differs")


def _start_run(
    con, *, session_date: date, payload: dict, receipts: list[dict], started: datetime,
) -> int:
    run_id = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM p15_preopen_runs").fetchone()[0])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    con.execute(
        "INSERT INTO p15_preopen_runs VALUES "
        "(?,?,?,'running',NULL,?,?,NULL,NULL,?,NULL,NULL)",
        [run_id, POLICY_ID, session_date, encoded, canonical_sha256(payload),
         started.replace(tzinfo=None)],
    )
    for receipt in receipts:
        con.execute(
            "INSERT INTO p15_preopen_news_responses VALUES (?,?,?,?,?,?,?,?,?,?)",
            [run_id, receipt["ticker"], receipt["endpoint"], receipt["requested_at"],
             receipt["received_at"], receipt["http_status"], receipt["content_type"],
             receipt["response_sha256"], receipt["response_body"], receipt["receipt_sha256"]],
        )
    return run_id


def _finish_run(
    con, *, run_id: int, status: str, reason: str | None, response: dict | None,
    decisions: list[dict], completed: datetime,
) -> dict:
    response_text = None if response is None else json.dumps(
        response, sort_keys=True, separators=(",", ":")
    )
    row = con.execute(
        "SELECT session_date,input_sha256,started_at FROM p15_preopen_runs WHERE id=?",
        [run_id],
    ).fetchone()
    response_sha = None if response is None else canonical_sha256(response)
    run_identity = {
        "run_id": run_id, "policy_id": POLICY_ID, "session_date": row[0].isoformat(),
        "status": status, "reason": reason, "input_sha256": row[1],
        "response_sha256": response_sha, "started_at": row[2].isoformat(),
        "completed_at": completed.replace(tzinfo=None).isoformat(),
    }
    changed = con.execute(
        "UPDATE p15_preopen_runs SET status=?,reason=?,response_payload=?,response_sha256=?,"
        "completed_at=?,run_sha256=? WHERE id=? AND status='running' RETURNING id",
        [status, reason, response_text, response_sha, completed.replace(tzinfo=None),
         canonical_sha256(run_identity), run_id],
    ).fetchone()
    if changed is None:
        raise PreopenError("pre-open run is not pending completion")
    decision_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM p15_preopen_decisions"
    ).fetchone()[0])
    for item in decisions:
        identity = {"run_id": run_id, **item, "applied_at": completed.isoformat()}
        con.execute(
            "INSERT INTO p15_preopen_decisions VALUES (?,?,?,?,?,?,?,?,?,?)",
            [decision_id, run_id, item["intent_id"], item["portfolio_id"], item["ticker"],
             item["decision"], item["reason"], json.dumps(item["evidence_ids"]),
             canonical_sha256(identity), completed.replace(tzinfo=None)],
        )
        if item["decision"] == "cancel":
            changed = con.execute(
                "UPDATE p15_order_intents SET status='cancelled',reason='preopen_cancel' "
                "WHERE id=? AND status='pending' RETURNING id", [item["intent_id"]],
            ).fetchone()
            if changed is None:
                raise PreopenError("pre-open cancel target is no longer pending")
        decision_id += 1
    return {"status": status, "run_id": run_id, "replayed": False,
            "decision_count": len(decisions),
            "cancelled": sum(item["decision"] == "cancel" for item in decisions)}


def _replay_run(con, run_id: int, status: str) -> dict:
    raw = con.execute(
        "SELECT input_payload,input_sha256,response_payload,response_sha256,"
        "session_date,reason,started_at,completed_at,run_sha256 "
        "FROM p15_preopen_runs WHERE id=?", [run_id],
    ).fetchone()
    payload = json.loads(raw[0])
    if canonical_sha256(payload) != raw[1] or (
        raw[2] is not None and canonical_sha256(json.loads(raw[2])) != raw[3]
    ):
        raise PreopenError("pre-open retained run differs from its identity")
    if raw[7] is None or raw[7] < raw[6]:
        raise PreopenError("pre-open retained timing is invalid")
    run_identity = {
        "run_id": run_id, "policy_id": POLICY_ID, "session_date": raw[4].isoformat(),
        "status": status, "reason": raw[5], "input_sha256": raw[1],
        "response_sha256": raw[3], "started_at": raw[6].isoformat(),
        "completed_at": raw[7].isoformat(),
    }
    if canonical_sha256(run_identity) != raw[8]:
        raise PreopenError("pre-open retained run identity is invalid")
    receipt_ids = set()
    for receipt in con.execute(
        "SELECT ticker,endpoint,requested_at,received_at,http_status,content_type,"
        "response_sha256,response_body,receipt_sha256 FROM p15_preopen_news_responses "
        "WHERE run_id=? ORDER BY ticker", [run_id],
    ).fetchall():
        body_sha = hashlib.sha256(bytes(receipt[7])).hexdigest()
        receipt_identity = {
            "ticker": receipt[0], "endpoint": receipt[1],
            "requested_at": receipt[2].replace(tzinfo=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "received_at": receipt[3].replace(tzinfo=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "http_status": receipt[4], "content_type": receipt[5],
            "response_sha256": body_sha,
        }
        if body_sha != receipt[6] or canonical_sha256(receipt_identity) != receipt[8]:
            raise PreopenError("pre-open retained news receipt is invalid")
        receipt_ids.add(receipt[8])
    if receipt_ids != set(payload["receipt_sha256s"]):
        raise PreopenError("pre-open retained news receipt set is incomplete")
    rows = con.execute(
        "SELECT portfolio_id,ticker,intent_id,decision,reason,evidence_ids,"
        "decision_sha256,applied_at "
        "FROM p15_preopen_decisions WHERE run_id=? ORDER BY id", [run_id],
    ).fetchall()
    for book_id, ticker, intent_id, decision, reason, evidence, digest, applied_at in rows:
        identity = {"run_id": run_id, "intent_id": intent_id,
                    "decision": decision, "reason": reason,
                    "evidence_ids": json.loads(evidence),
                    "portfolio_id": book_id, "ticker": ticker,
                    "applied_at": applied_at.replace(tzinfo=timezone.utc).isoformat()}
        if applied_at != raw[7] or canonical_sha256(identity) != digest:
            raise PreopenError("pre-open retained decision differs from its identity")
    expected_intents = {item["intent_id"] for item in [
        *payload["intents"], *payload["control_noops"],
    ]}
    if {int(row[2]) for row in rows} != expected_intents:
        raise PreopenError("pre-open retained decision set is incomplete")
    return {"status": status, "run_id": run_id, "replayed": True,
            "decision_count": len(rows),
            "cancelled": sum(row[3] == "cancel" for row in rows)}


def run(
    con: duckdb.DuckDBPyConnection, *, session_date: date, now: datetime,
    generate: Callable[[dict], agent_model_client.ConnectorResult]
    = agent_model_client.generate_p15_preopen_json,
    fetch_news=daily_opportunity_news._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    """Run one bounded pre-open decision; failures and lateness retain every intent."""
    started = _utc(now)
    local = started.astimezone(ET)
    if local.date() != session_date or local.timetz().replace(tzinfo=None) < START:
        raise PreopenError("pre-open run is outside its session window")
    init_schema(con)
    if p15_books.activation_state(con) != "active":
        return {"status": "inactive", "decision_count": 0, "cancelled": 0}
    existing = con.execute(
        "SELECT id,status FROM p15_preopen_runs WHERE policy_id=? AND session_date=?",
        [POLICY_ID, session_date],
    ).fetchone()
    if existing is not None:
        if existing[1] != "running":
            return _replay_run(con, int(existing[0]), existing[1])
        retained = con.execute(
            "SELECT input_payload,input_sha256 FROM p15_preopen_runs WHERE id=?",
            [existing[0]],
        ).fetchone()
        payload = json.loads(retained[0])
        if canonical_sha256(payload) != retained[1]:
            raise PreopenError("pre-open retained input is invalid")
        original = [*payload["intents"], *payload["control_noops"]]
        decisions = [{"intent_id": item["intent_id"],
                      "portfolio_id": item["portfolio_id"], "ticker": item["ticker"],
                      "decision": "keep", "reason": "interrupted_preopen_run",
                      "evidence_ids": []} for item in original]
        with db.transaction(con):
            return _finish_run(
                con, run_id=int(existing[0]), status="unavailable",
                reason="interrupted pre-open run", response=None,
                decisions=decisions, completed=started,
            )
    pending = _pending(con, session_date)
    if not pending:
        payload = {"schema_version": 1, "policy_id": POLICY_ID,
                   "session_date": session_date.isoformat(), "cutoff_at": started.isoformat(),
                   "execution_authority": "cancel_only", "intents": [],
                   "control_noops": [], "receipt_sha256s": []}
        with db.transaction(con):
            run_id = _start_run(
                con, session_date=session_date, payload=payload,
                receipts=[], started=started,
            )
            return _finish_run(
                con, run_id=run_id, status="no_pending_orders",
                reason="no pending P15 entries", response=None,
                decisions=[], completed=started,
            )
    model_intents = [item for item in pending if item["portfolio_id"] in BOOK_IDS]
    news = daily_opportunity_news.capture(
        [item["ticker"] for item in model_intents], now=started, fetch=fetch_news,
    ) if model_intents and local.timetz().replace(tzinfo=None) < DEADLINE else {
        "status": "not_called", "receipts": [], "observations": [], "failures": [],
    }
    receipt_times = [
        datetime.fromisoformat(item["received_at"].replace("Z", "+00:00"))
        for item in news["receipts"]
    ]
    capture_finished = _utc(clock())
    cutoff = max([started, capture_finished, *receipt_times])
    intent_payloads, allowed = [], {}
    for item in model_intents:
        decision_at = item["decision_at"].replace(tzinfo=timezone.utc)
        headlines = [entry for entry in news["observations"]
                     if entry["ticker"] == item["ticker"]
                     and decision_at < datetime.fromisoformat(
                         entry["retrieved_at"].replace("Z", "+00:00")
                     ) <= cutoff
                     and datetime.fromisoformat(
                         entry["published_at"].replace("Z", "+00:00")
                     ) <= cutoff]
        facts = _facts(con, item["ticker"], item["decision_at"], cutoff)
        ids = set(item["assessment"].get("evidence_ids", []))
        ids.update(entry["evidence_id"] for entry in [*headlines, *facts])
        allowed[item["intent_id"]] = ids
        intent_payloads.append({
            "intent_id": item["intent_id"], "portfolio_id": item["portfolio_id"],
            "ticker": item["ticker"], "limit_px": item["limit_px"],
            "nightly_assessment": item["assessment"], "new_headlines": headlines,
            "new_event_facts": facts, "allowed_evidence_ids": sorted(ids),
        })
    control_noops = [{"intent_id": item["intent_id"],
                      "portfolio_id": item["portfolio_id"], "ticker": item["ticker"]}
                     for item in pending if item["portfolio_id"] == "p15_rule_control"]
    payload = {"schema_version": 1, "policy_id": POLICY_ID,
               "session_date": session_date.isoformat(), "cutoff_at": cutoff.isoformat(),
               "execution_authority": "cancel_only", "intents": intent_payloads,
               "control_noops": control_noops,
               "receipt_sha256s": sorted(item["receipt_sha256"] for item in news["receipts"])}
    with db.transaction(con):
        run_id = _start_run(
            con, session_date=session_date, payload=payload,
            receipts=news["receipts"], started=started,
        )
    response, status, reason, model_decisions = None, "completed", None, []
    completed = started
    if cutoff.astimezone(ET).timetz().replace(tzinfo=None) >= DEADLINE:
        status, reason = "late", "pre-open deadline reached"
    elif model_intents:
        try:
            generated = generate(payload)
            _validate_identity(generated, payload)
            response = asdict(generated)
            completed = _utc(clock())
            if completed < cutoff:
                status, reason = "unavailable", "pre-open clock moved backwards"
            elif completed.astimezone(ET).timetz().replace(tzinfo=None) >= DEADLINE:
                status, reason = "late", "pre-open response missed deadline"
            else:
                model_decisions = _validate(response["output"], allowed)
        except (agent_model_client.ConnectorError, PreopenError, TypeError, ValueError) as exc:
            status, reason = "unavailable", str(exc)[:500]
            completed = _utc(clock())
    elif status == "late":
        completed = _utc(clock())
    if status != "completed":
        model_decisions = [{"intent_id": item["intent_id"], "decision": "keep",
                            "reason": reason, "evidence_ids": sorted(allowed[item["intent_id"]])}
                           for item in model_intents]
    by_id = {item["intent_id"]: item for item in pending}
    decisions = [{**item, "portfolio_id": by_id[item["intent_id"]]["portfolio_id"],
                  "ticker": by_id[item["intent_id"]]["ticker"]}
                 for item in model_decisions]
    decisions.extend({**item, "decision": "keep",
                      "reason": "rule_control_noop", "evidence_ids": []}
                     for item in control_noops)
    try:
        with db.transaction(con):
            final_time = _utc(clock())
            if final_time < completed:
                status, reason = "unavailable", "pre-open clock moved backwards"
            elif status == "completed" and final_time.astimezone(ET).timetz().replace(
                tzinfo=None
            ) >= DEADLINE:
                status, reason = "late", "pre-open commit missed deadline"
            if status != "completed":
                decisions = [{**item, "decision": "keep", "reason": reason}
                             if item["portfolio_id"] in BOOK_IDS else item
                             for item in decisions]
            result = _finish_run(
                con, run_id=run_id, status=status, reason=reason, response=response,
                decisions=decisions, completed=final_time,
            )
            post_apply = _utc(clock())
            if result["cancelled"] and post_apply.astimezone(ET).timetz().replace(
                tzinfo=None
            ) >= DEADLINE:
                raise _LateCommit(post_apply)
        return result
    except _LateCommit as exc:
        keep = [{**item, "decision": "keep", "reason": "pre-open commit missed deadline"}
                if item["portfolio_id"] in BOOK_IDS else item for item in decisions]
        with db.transaction(con):
            return _finish_run(
                con, run_id=run_id, status="late",
                reason="pre-open commit missed deadline", response=response,
                decisions=keep, completed=exc.observed_at,
            )


def run_database(database: Path = DEFAULT_DB, *, now: datetime | None = None, **kwargs) -> dict:
    observed = _utc(now or datetime.now(timezone.utc))
    with advisory_file_lock(LOCK_PATH), advisory_file_lock(NIGHTLY_LOCK):
        con = db.connect(database, wait_s=0)
        try:
            p15_books.init_schema(con)
            init_schema(con)
            return run(con, session_date=observed.astimezone(ET).date(), now=observed, **kwargs)
        finally:
            con.close()


def capture_after_open(
    con: duckdb.DuckDBPyConnection, fill_date: date, *, captured_at: datetime,
) -> dict:
    """Record cancelled hypotheticals and terminal order execution quality."""
    init_schema(con)
    cancelled = con.execute(
        "SELECT id,portfolio_id,ticker,qty,signal_date,limit_px FROM p15_order_intents i "
        "WHERE status='cancelled' AND order_role='entry' AND signal_date<? "
        "AND NOT EXISTS (SELECT 1 FROM p15_limit_attempts done "
        "WHERE done.intent_id=i.id AND done.outcome!='pending') "
        "ORDER BY id", [fill_date],
    ).fetchall()
    attempts = 0
    for intent_id, _book_id, ticker, qty, signal_date, limit_px in cancelled:
        attempt_date = nyse.next_session(signal_date)
        while attempt_date <= fill_date:
            prior = con.execute(
                "SELECT outcome FROM p15_limit_attempts WHERE intent_id=? AND attempt_date=?",
                [intent_id, attempt_date],
            ).fetchone()
            if prior is not None:
                if prior[0] != "pending":
                    break
                attempt_date = nyse.next_session(attempt_date)
                continue
            factor = p15_books._split_factor(con, ticker, signal_date, attempt_date)
            result = p15_fills.attempt_limit_on_open(
                con, ticker, "buy", float(qty) * factor, signal_date, attempt_date,
                float(limit_px) / factor, "baseline_v1",
            )
            if result.status == "filled":
                outcome, counterfactual = "cancelled_would_fill", result.fill_px
            elif result.reject_reason == "limit_not_reached":
                outcome = "cancelled_limit_not_reached"
                counterfactual = result.counterfactual_fill_px
            else:
                outcome, counterfactual = result.status, result.counterfactual_fill_px
            con.execute(
                "INSERT INTO p15_limit_attempts VALUES (?,?,?,?,?,?,?)",
                [intent_id, attempt_date, float(limit_px) / factor, result.open_px,
                 counterfactual, outcome, result.reject_reason],
            )
            attempts += 1
            if outcome != "pending":
                break
            attempt_date = nyse.next_session(attempt_date)
    labels = p15_books.label_limit_counterfactuals(con, labeled_at=captured_at)
    quality = capture_execution_quality(con, captured_at=captured_at)
    return {"cancelled_attempts": attempts, "counterfactual_labels": labels,
            "execution_quality": quality}


def capture_execution_quality(
    con: duckdb.DuckDBPyConnection, *, captured_at: datetime,
) -> int:
    rows = con.execute(
        "SELECT i.id,i.sim_order_id,i.decision_id,i.portfolio_id,i.ticker,i.side,"
        "i.order_role,t.completed_at,i.created_at,i.signal_date,i.signal_close,i.status,"
        "COALESCE(f.fill_date,a.attempt_date,la.attempt_date),"
        "COALESCE(f.open_px,la.open_px),"
        "CASE WHEN i.status='cancelled' THEN la.counterfactual_fill_px ELSE f.fill_px END,"
        "f.cost_bps FROM p15_order_intents i LEFT JOIN sim_orders o ON o.id=i.sim_order_id "
        "LEFT JOIN sim_fills f ON f.order_id=o.id "
        "LEFT JOIN sim_execution_attempts a ON a.order_id=o.id "
        "LEFT JOIN (SELECT * FROM p15_limit_attempts QUALIFY ROW_NUMBER() OVER "
        "(PARTITION BY intent_id ORDER BY CASE WHEN outcome='pending' THEN 1 ELSE 0 END,"
        "attempt_date DESC)=1) la ON la.intent_id=i.id "
        "LEFT JOIN agent_evaluation_decisions d ON d.id=i.decision_id "
        "LEFT JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE i.status IN ('filled','rejected','cancelled') "
        "AND (i.status!='cancelled' OR la.outcome!='pending') ORDER BY i.id"
    ).fetchall()
    inserted = 0
    for row in rows:
        (intent_id, order_id, decision_id, book_id, ticker, side, role, decision_at,
         order_at, signal_date, arrival, status, attempt_date, open_px, fill_px, cost) = row
        if attempt_date is None:
            raise PreopenError("terminal P15 order has no execution attempt")
        direction = 1.0 if side == "buy" else -1.0
        arrival = float(arrival) / p15_books._split_factor(
            con, ticker, signal_date, attempt_date
        )
        gap = None if open_px is None else direction * (float(open_px) / arrival - 1) * 1e4
        total = None if fill_px is None else direction * (float(fill_px) / arrival - 1) * 1e4
        sessions = int(con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE ticker='SPY' "
            "AND date>? AND date<=? AND volume>0", [signal_date, attempt_date],
        ).fetchone()[0])
        effective_decision_at = decision_at or order_at
        if order_at < effective_decision_at:
            raise PreopenError("P15 decision-to-order time is negative")
        latency = (order_at - effective_decision_at).total_seconds() * 1000
        if status == "cancelled" and cost is None and open_px and fill_px:
            cost = (float(fill_px) / float(open_px) - 1) * 1e4
        identity = {
            "intent_id": int(intent_id),
            "sim_order_id": None if order_id is None else int(order_id),
            "decision_id": None if decision_id is None else int(decision_id),
            "portfolio_id": book_id, "ticker": ticker, "side": side,
            "order_role": role, "decision_at": effective_decision_at.isoformat(),
            "order_at": order_at.isoformat(), "attempt_date": attempt_date.isoformat(),
            "status": status,
            "decision_to_order_ms": latency, "order_to_attempt_sessions": sessions,
            "arrival_price": float(arrival), "open_px": open_px, "fill_px": fill_px,
            "gap_shortfall_bps": gap, "total_shortfall_bps": total, "cost_bps": cost,
            "captured_at": captured_at.replace(tzinfo=None).isoformat(),
        }
        digest = canonical_sha256(identity)
        existing = con.execute(
            "SELECT sim_order_id,decision_id,portfolio_id,ticker,side,order_role,decision_at,"
            "order_at,attempt_date,status,decision_to_order_ms,order_to_attempt_sessions,"
            "arrival_price,open_px,fill_px,gap_shortfall_bps,total_shortfall_bps,cost_bps,"
            "captured_at,quality_sha256 FROM p15_execution_quality WHERE intent_id=?", [intent_id]
        ).fetchone()
        if existing is not None:
            stored = dict(zip(tuple(identity)[1:], existing[:-1], strict=True))
            for key in ("decision_at", "order_at", "attempt_date", "captured_at"):
                if stored[key] is not None:
                    stored[key] = stored[key].isoformat()
            stored = {"intent_id": int(intent_id), **stored}
            expected = {**identity, "captured_at": stored["captured_at"]}
            if canonical_sha256(stored) != existing[-1] or existing[-1] != canonical_sha256(expected):
                raise PreopenError("P15 execution-quality replay differs")
            continue
        con.execute(
            "INSERT INTO p15_execution_quality VALUES (" + ",".join("?" for _ in range(21)) + ")",
            [*identity.values(), digest],
        )
        inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run", action="store_true", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_database(args.database), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
