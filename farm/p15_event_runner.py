"""Rate-limited shadow scoring for P15 news, SEC, and intraday triggers."""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable

import duckdb

from engine import p15_event_sources
from engine.lib import db
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.util import table_exists
from server import agent_evaluation, agent_model_client
from tools import sec_edgar_capture

POLICY_ID = "p15-events-v1"
MAX_DECISIONS_PER_SESSION = 60
CHUNK_SIZE = 10
HORIZONS = (1, 5, 10, 20)
LOCK_PATH = REPO_ROOT / ".p15-events.lock"
NIGHTLY_LOCK = REPO_ROOT / ".nightly.lock"


class EventRunError(ValueError):
    """A P15 event decision or retained run violates its contract."""


def _next_id(con, table: str) -> int:
    if table not in {"p15_event_windows", "p15_event_calls", "p15_event_decisions",
                     "p15_event_labels"}:
        raise EventRunError("event table is invalid")
    return int(con.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}").fetchone()[0])


def _context(con, rows: list[tuple], observed_at: datetime) -> tuple[list[dict], dict]:
    held = {row[0] for row in con.execute(
        "SELECT DISTINCT ticker FROM sim_positions WHERE portfolio_id IN (?,?,?) AND qty>0",
        ["p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto"],
    ).fetchall()} if table_exists(con, "sim_positions") else set()
    items, allowed = [], {}
    for trigger_id, ticker, source, event_type, event_at, available_at, triggered_at, fact_sha in rows:
        if available_at > observed_at.replace(tzinfo=None) or triggered_at > observed_at.replace(
            tzinfo=None
        ):
            raise EventRunError("event trigger exceeds the information cutoff")
        fact = con.execute(
            "SELECT normalized_payload FROM bitemporal_facts WHERE fact_sha256=?", [fact_sha]
        ).fetchone()
        daily = con.execute(
            f"SELECT date,close FROM prices WHERE ticker=? AND date<? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
            "ORDER BY date DESC LIMIT 1",
            [ticker, observed_at.date(), observed_at.replace(tzinfo=None)],
        ).fetchone()
        screen = con.execute(
            "SELECT rs_rank,passes_template FROM screen_results WHERE ticker=? AND run_date<? "
            "ORDER BY run_date DESC LIMIT 1", [ticker, observed_at.date()],
        ).fetchone()
        if fact is None:
            raise EventRunError("event trigger context is unavailable")
        item = {
            "trigger_id": int(trigger_id), "ticker": ticker, "source": source,
            "event_type": event_type, "event_at": event_at.isoformat(),
            "available_at": available_at.isoformat(),
            "triggered_at": triggered_at.isoformat(), "trigger_evidence_id": fact_sha,
            "event": json.loads(fact[0]),
            "context_status": "available" if daily is not None else "unavailable",
            "daily_as_of": None if daily is None else daily[0].isoformat(),
            "prior_close": None if daily is None else float(daily[1]),
            "rs_rank": None if screen is None else screen[0],
            "passes_template": False if screen is None else bool(screen[1]),
            "held": ticker in held, "allowed_evidence_ids": [fact_sha],
        }
        items.append(item)
        allowed[int(trigger_id)] = {fact_sha}
    return items, allowed


def _validate(output: object, rows: list[dict], allowed: dict[int, set[str]]) -> list[dict]:
    if (not isinstance(output, dict) or set(output) != {"schema_version", "assessments"}
            or type(output.get("schema_version")) is not int or output["schema_version"] != 1
            or not isinstance(output["assessments"], list)):
        raise EventRunError("event model output shape is invalid")
    expected = {item["trigger_id"]: item for item in rows}
    result, seen = [], set()
    for item in output["assessments"]:
        fields = {"trigger_id", "ticker", "event_type", "p_outperform_5",
                  "expected_excess_bp_5", "expected_excess_bp_10", "action",
                  "thesis", "invalidation", "evidence_ids"}
        if not isinstance(item, dict) or set(item) != fields:
            raise EventRunError("event assessment shape is invalid")
        trigger_id = item["trigger_id"]
        source = expected.get(trigger_id) if type(trigger_id) is int else None
        if source is None or trigger_id in seen or item["ticker"] != source["ticker"] \
                or item["event_type"] != source["event_type"]:
            raise EventRunError("event assessment identity is invalid")
        numbers = [item[key] for key in (
            "p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10"
        )]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(float(value)) for value in numbers) \
                or not 0 <= float(numbers[0]) <= 1 \
                or any(abs(float(value)) > 10_000 for value in numbers[1:]):
            raise EventRunError("event assessment score is invalid")
        if item["action"] not in {"ignore", "watch", "buy_candidate", "exit"} \
                or (item["action"] == "exit" and not source["held"]):
            raise EventRunError("event assessment action is invalid")
        evidence = item["evidence_ids"]
        if (not isinstance(evidence, list) or not evidence
                or any(not isinstance(value, str) for value in evidence)
                or len(evidence) != len(set(evidence)) or not set(evidence) <= allowed[trigger_id]):
            raise EventRunError("event assessment evidence is invalid")
        if any(not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 1_000
               for key in ("thesis", "invalidation")) or len(item["thesis"].split()) > 60:
            raise EventRunError("event assessment text is invalid")
        seen.add(trigger_id)
        result.append(item)
    if seen != set(expected):
        raise EventRunError("event output does not cover the chunk")
    return result


def _identity(result, payload):
    expected = agent_model_client.identity(role="p15_event")
    if (result.model != expected["model"] or result.model_version != expected["model_version"]
            or result.proxy_version != expected["required_proxy_version"]
            or result.proxy_source_sha256 != expected["required_proxy_source_sha256"]
            or result.traecli_runtime != expected["required_traecli_runtime"]
            or result.upstream_model_family != agent_model_client.UPSTREAM_MODEL_FAMILY
            or result.model_catalog_entry_sha256 != expected["model_catalog_entry_sha256"]
            or result.request_sha256 != canonical_sha256(
                agent_model_client.p15_event_request_payload(payload)
            )):
        raise EventRunError("event model identity differs")


def _window(observed_at: datetime) -> tuple[str, date]:
    if type(observed_at) is not datetime or observed_at.utcoffset() is None:
        raise EventRunError("event window timestamp is invalid")
    local = observed_at.astimezone(p15_event_sources.ET)
    valid = local.minute in {5, 20, 35, 50} and (
        10 <= local.hour <= 15 or local.hour == 9 and local.minute in {35, 50}
    )
    if not valid or not p15_event_sources.regular_session_open(observed_at):
        raise EventRunError("event run is outside a registered market window")
    return f"{POLICY_ID}:{local.date().isoformat()}:{local.hour:02}:{local.minute:02}", local.date()


def _replay_window(con, window_id: str) -> dict:
    row = con.execute(
        "SELECT session_date,observed_at,information_cutoff_at,completed_at,status,reason,source_summary,"
        "trigger_count,decision_count,skipped_count,window_sha256 "
        "FROM p15_event_windows WHERE window_id=?", [window_id],
    ).fetchone()
    if row is None or row[4] == "running":
        raise EventRunError("event window is not terminal")
    summary = json.loads(row[6])
    identity = {"window_id": window_id, "session_date": row[0].isoformat(),
                "observed_at": row[1].replace(tzinfo=timezone.utc).isoformat(),
                "information_cutoff_at": row[2].replace(tzinfo=timezone.utc).isoformat(),
                "completed_at": row[3].replace(tzinfo=timezone.utc).isoformat(),
                "status": row[4], "reason": row[5], "source_summary": summary,
                "trigger_count": int(row[7]), "decision_count": int(row[8]),
                "skipped_count": int(row[9])}
    calls = con.execute(
        "SELECT chunk_index,request_payload,request_sha256,response_payload,response_sha256,"
        "status,error,started_at,completed_at,call_sha256 "
        "FROM p15_event_calls WHERE window_id=? ORDER BY chunk_index", [window_id],
    ).fetchall()
    call_trigger_ids = set()
    for chunk_index, request, request_sha, response, response_sha, call_status, error, started, completed, digest in calls:
        request_payload = json.loads(request)
        call_trigger_ids.update(item["trigger_id"] for item in request_payload["events"])
        call_identity = {"window_id": window_id, "chunk_index": int(chunk_index),
                         "request_sha256": request_sha, "response_sha256": response_sha,
                         "status": call_status, "error": error,
                         "started_at": started.replace(tzinfo=timezone.utc).isoformat(),
                         "completed_at": completed.replace(tzinfo=timezone.utc).isoformat()}
        if canonical_sha256(agent_model_client.p15_event_request_payload(
            request_payload
        )) != request_sha or (response is not None and canonical_sha256(
            json.loads(response)
        ) != response_sha) or call_status == "running" or canonical_sha256(
            call_identity
        ) != digest:
            raise EventRunError("event call replay differs")
    decision_rows = con.execute(
        "SELECT trigger_id,ticker,event_type,scoring_status,decision_payload,"
        "decision_sha256,triggered_at,decision_at,latency_ms FROM p15_event_decisions "
        "WHERE window_id=? ORDER BY id", [window_id],
    ).fetchall()
    for trigger_id, ticker, event_type, scoring, raw, digest, triggered, decided, latency in decision_rows:
        item = json.loads(raw)
        expected = {"window_id": window_id, "trigger_id": int(trigger_id),
                    "decision": item,
                    "decision_at": decided.replace(tzinfo=timezone.utc).isoformat(),
                    "triggered_at": triggered.replace(tzinfo=timezone.utc).isoformat(),
                    "latency_ms": latency,
                    "execution_authority": "none"}
        if (item.get("ticker") != ticker or item.get("event_type") != event_type
                or scoring not in {"available", "unavailable"}
                or latency != (decided - triggered).total_seconds() * 1000
                or canonical_sha256(expected) != digest):
            raise EventRunError("event decision replay differs")
    decisions = len(decision_rows)
    selected_ids = set(summary["trigger_ids"][:int(row[7]) - int(row[9])])
    if (canonical_sha256(identity) != row[10] or decisions != int(row[8])
            or not call_trigger_ids <= selected_ids
            or {int(item[0]) for item in decision_rows} != selected_ids):
        raise EventRunError("event window replay differs")
    return {"status": row[4], "decisions": decisions, "skipped": int(row[9]),
            "model_calls": len(calls),
            "unavailable": sum(item[3] == "unavailable" for item in decision_rows),
            "labels": 0, "replayed": True, "execution_authority": "none"}


def _recover_window(con, window_id: str, completed: datetime) -> None:
    recovered = 0
    with db.transaction(con):
        for call_id, raw, request_sha, started, chunk_index in con.execute(
            "SELECT id,request_payload,request_sha256,started_at,chunk_index "
            "FROM p15_event_calls "
            "WHERE window_id=? AND status='running' ORDER BY chunk_index", [window_id],
        ).fetchall():
            payload = json.loads(raw)
            for event in payload["events"]:
                item = {"trigger_id": event["trigger_id"], "ticker": event["ticker"],
                        "event_type": event["event_type"], "p_outperform_5": None,
                        "expected_excess_bp_5": None, "expected_excess_bp_10": None,
                        "action": "unavailable", "thesis": None, "invalidation": None,
                        "evidence_ids": [event["trigger_evidence_id"]]}
                decision_id = _next_id(con, "p15_event_decisions")
                trigger_at = con.execute(
                    "SELECT triggered_at FROM p15_event_triggers WHERE id=?",
                    [item["trigger_id"]],
                ).fetchone()[0]
                identity = {"window_id": window_id, "trigger_id": item["trigger_id"],
                            "decision": item, "decision_at": completed.isoformat(),
                            "triggered_at": trigger_at.replace(tzinfo=timezone.utc).isoformat(),
                            "latency_ms": (completed.replace(tzinfo=None)
                                           - trigger_at).total_seconds() * 1000,
                            "execution_authority": "none"}
                con.execute(
                    "INSERT INTO p15_event_decisions VALUES (?,?,?,?,?,'unavailable',?,?,?,?,?)",
                    [decision_id, window_id, item["trigger_id"], item["ticker"],
                     item["event_type"], json.dumps(item, sort_keys=True, separators=(",", ":")),
                     canonical_sha256(identity), trigger_at, completed.replace(tzinfo=None),
                     (completed.replace(tzinfo=None) - trigger_at).total_seconds() * 1000],
                )
                con.execute(
                    "UPDATE p15_event_triggers SET status='unavailable',reason=? WHERE id=?",
                    ["interrupted event model call", item["trigger_id"]],
                )
                recovered += 1
            error = "interrupted event model call"
            call_identity = {"window_id": window_id,
                             "chunk_index": int(chunk_index),
                             "request_sha256": request_sha, "response_sha256": None,
                             "status": "unavailable", "error": error,
                             "started_at": started.replace(tzinfo=timezone.utc).isoformat(),
                             "completed_at": completed.isoformat()}
            con.execute(
                "UPDATE p15_event_calls SET status='unavailable',error=?,completed_at=?,"
                "call_sha256=? "
                "WHERE id=? AND status='running'",
                [error, completed.replace(tzinfo=None), canonical_sha256(call_identity), call_id],
            )
        row = con.execute(
            "SELECT session_date,observed_at,information_cutoff_at,source_summary,"
            "trigger_count,skipped_count "
            "FROM p15_event_windows WHERE window_id=?", [window_id],
        ).fetchone()
        summary = json.loads(row[3])
        decided = {item[0] for item in con.execute(
            "SELECT trigger_id FROM p15_event_decisions WHERE window_id=?", [window_id]
        ).fetchall()}
        for event in summary["selected_contexts"]:
            if event["trigger_id"] in decided:
                continue
            item = {"trigger_id": event["trigger_id"], "ticker": event["ticker"],
                    "event_type": event["event_type"], "p_outperform_5": None,
                    "expected_excess_bp_5": None, "expected_excess_bp_10": None,
                    "action": "unavailable", "thesis": None, "invalidation": None,
                    "evidence_ids": [event["trigger_evidence_id"]]}
            trigger_at = datetime.fromisoformat(event["triggered_at"])
            latency = (completed - trigger_at.replace(tzinfo=timezone.utc)).total_seconds() * 1000
            identity = {"window_id": window_id, "trigger_id": item["trigger_id"],
                        "decision": item, "decision_at": completed.isoformat(),
                        "triggered_at": trigger_at.replace(tzinfo=timezone.utc).isoformat(),
                        "latency_ms": latency, "execution_authority": "none"}
            con.execute(
                "INSERT INTO p15_event_decisions VALUES (?,?,?,?,?,'unavailable',?,?,?,?,?)",
                [_next_id(con, "p15_event_decisions"), window_id, item["trigger_id"],
                 item["ticker"], item["event_type"],
                 json.dumps(item, sort_keys=True, separators=(",", ":")),
                 canonical_sha256(identity), trigger_at.replace(tzinfo=None),
                 completed.replace(tzinfo=None), latency],
            )
            con.execute(
                "UPDATE p15_event_triggers SET status='unavailable',reason=? WHERE id=?",
                ["interrupted event window", item["trigger_id"]],
            )
            recovered += 1
        decisions = int(con.execute(
            "SELECT COUNT(*) FROM p15_event_decisions WHERE window_id=?", [window_id]
        ).fetchone()[0])
        status = "unavailable" if recovered else "completed"
        identity = {"window_id": window_id, "session_date": row[0].isoformat(),
                    "observed_at": row[1].replace(tzinfo=timezone.utc).isoformat(),
                    "information_cutoff_at": row[2].replace(tzinfo=timezone.utc).isoformat(),
                    "completed_at": completed.isoformat(), "status": status,
                    "reason": "interrupted event model call" if recovered else None,
                    "source_summary": summary, "trigger_count": int(row[4]),
                    "decision_count": decisions, "skipped_count": int(row[5])}
        con.execute(
            "UPDATE p15_event_windows SET completed_at=?,status=?,reason=?,decision_count=?,"
            "window_sha256=? WHERE window_id=? AND status='running'",
            [completed.replace(tzinfo=None), status,
             "interrupted event model call" if recovered else None, decisions,
             canonical_sha256(identity), window_id],
        )


def _terminalize_stale_triggers(
    con: duckdb.DuckDBPyConnection, session_date: date, completed: datetime,
) -> int:
    total = 0
    for (stale_date,) in con.execute(
        "SELECT DISTINCT session_date FROM p15_event_triggers "
        "WHERE status='pending' AND session_date<? ORDER BY session_date", [session_date],
    ).fetchall():
        rows = con.execute(
            "SELECT id,ticker,event_type,triggered_at,fact_sha256 FROM p15_event_triggers "
            "WHERE status='pending' AND session_date=? ORDER BY available_at,id", [stale_date],
        ).fetchall()
        used = int(con.execute(
            "SELECT COUNT(*) FROM p15_event_decisions d JOIN p15_event_triggers t "
            "ON t.id=d.trigger_id WHERE t.session_date=?", [stale_date],
        ).fetchone()[0])
        selected = rows[:max(0, MAX_DECISIONS_PER_SESSION - used)]
        skipped = rows[len(selected):]
        window_id = f"{POLICY_ID}:{stale_date.isoformat()}:stale-recovery"
        contexts = [{"trigger_id": row[0], "ticker": row[1],
                     "event_type": row[2], "triggered_at": row[3].isoformat(),
                     "trigger_evidence_id": row[4],
                     "context_status": "unavailable"} for row in selected]
        summary = {"source_summary": {"status": "interrupted_before_window"},
                   "trigger_ids": [row[0] for row in rows], "selected_contexts": contexts}
        for trigger_id, ticker, event_type, triggered, fact_sha in selected:
            item = {"trigger_id": trigger_id, "ticker": ticker, "event_type": event_type,
                    "p_outperform_5": None, "expected_excess_bp_5": None,
                    "expected_excess_bp_10": None, "action": "unavailable",
                    "thesis": None, "invalidation": None, "evidence_ids": [fact_sha]}
            latency = (completed.replace(tzinfo=None) - triggered).total_seconds() * 1000
            identity = {"window_id": window_id, "trigger_id": trigger_id,
                        "decision": item, "decision_at": completed.isoformat(),
                        "triggered_at": triggered.replace(tzinfo=timezone.utc).isoformat(),
                        "latency_ms": latency, "execution_authority": "none"}
            con.execute(
                "INSERT INTO p15_event_decisions VALUES (?,?,?,?,?,'unavailable',?,?,?,?,?)",
                [_next_id(con, "p15_event_decisions"), window_id, trigger_id, ticker,
                 event_type, json.dumps(item, sort_keys=True, separators=(",", ":")),
                 canonical_sha256(identity), triggered, completed.replace(tzinfo=None), latency],
            )
            con.execute(
                "UPDATE p15_event_triggers SET status='unavailable',reason=? WHERE id=?",
                ["event window did not start", trigger_id],
            )
        for trigger_id, *_rest in skipped:
            con.execute(
                "UPDATE p15_event_triggers SET status='skipped_rate_limit',reason=? WHERE id=?",
                ["60 decision session limit reached", trigger_id],
            )
        identity = {"window_id": window_id, "session_date": stale_date.isoformat(),
                    "observed_at": completed.isoformat(),
                    "information_cutoff_at": completed.isoformat(),
                    "completed_at": completed.isoformat(), "status": "unavailable",
                    "reason": "event window did not start", "source_summary": summary,
                    "trigger_count": len(rows), "decision_count": len(selected),
                    "skipped_count": len(skipped)}
        con.execute(
            "INSERT INTO p15_event_windows VALUES (?,?,?,?,?,?,'unavailable',?,?,?,?,?,?)",
            [_next_id(con, "p15_event_windows"), window_id, stale_date,
             completed.replace(tzinfo=None), completed.replace(tzinfo=None),
             completed.replace(tzinfo=None), "event window did not start",
             json.dumps(summary, sort_keys=True, separators=(",", ":")),
             len(rows), len(selected), len(skipped), canonical_sha256(identity)],
        )
        total += len(selected)
    return total


def _insert_label(
    con, decision_id: int, horizon: int, basis: str, entry_at: datetime,
    outcome: dict, entry_px: float, spy_return: float, labeled_at: datetime,
) -> bool:
    existing = con.execute(
        "SELECT label_basis,entry_at,exit_date,entry_px,exit_close,asset_return,spy_return,net_return,"
        "net_excess_return,missing_bar_status,price_prefix_sha256,label_sha256 "
        "FROM p15_event_labels WHERE decision_id=? AND horizon_sessions=? AND label_basis=?",
        [decision_id, horizon, basis],
    ).fetchone()
    if existing is not None:
        stored = {"decision_id": decision_id, "horizon_sessions": horizon,
                  "label_basis": existing[0], "entry_at": existing[1].isoformat(),
                  "exit_date": existing[2].isoformat(), "entry_px": existing[3],
                  "exit_close": existing[4], "asset_return": existing[5],
                  "spy_return": existing[6], "net_return": existing[7],
                  "net_excess_return": existing[8], "missing_bar_status": existing[9],
                  "price_prefix_sha256": existing[10]}
        if canonical_sha256(stored) != existing[11]:
            raise EventRunError("event label replay differs")
        return False
    asset_return = float(outcome["exit_close"]) / entry_px - 1
    net_return = float(outcome["exit_close"]) * 0.999 / (entry_px * 1.001) - 1
    spy_net = (1 + spy_return) * 0.999 / 1.001 - 1
    identity = {"decision_id": decision_id, "horizon_sessions": horizon,
                "label_basis": basis, "entry_at": entry_at.isoformat(),
                "exit_date": outcome["exit_date"].isoformat(), "entry_px": entry_px,
                "exit_close": outcome["exit_close"], "asset_return": asset_return,
                "spy_return": spy_return, "net_return": net_return,
                "net_excess_return": net_return - spy_net,
                "missing_bar_status": outcome["missing_bar_status"],
                "price_prefix_sha256": outcome["price_prefix_sha256"]}
    con.execute(
        "INSERT INTO p15_event_labels VALUES (" + ",".join("?" for _ in range(16)) + ")",
        [_next_id(con, "p15_event_labels"), *identity.values(),
         labeled_at.replace(tzinfo=None), canonical_sha256(identity)],
    )
    return True


def _missing_next_bar(con, ticker: str, decision_at: datetime, labeled_at: datetime):
    last = con.execute(
        f"SELECT date,close FROM prices WHERE ticker=? AND date<? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 1",
        [ticker, decision_at.date(), labeled_at.replace(tzinfo=None)],
    ).fetchone()
    if last is None or last[1] in (None, 0):
        return None
    entry_at = datetime.combine(
        last[0], p15_event_sources.session_close(last[0]), p15_event_sources.ET
    ).astimezone(timezone.utc).replace(tzinfo=None)
    price = float(last[1])
    outcome = {
        "exit_date": last[0], "exit_close": price, "spy_return": 0.0,
        "missing_bar_status": "missing_next_bar_last_available_close",
        "price_prefix_sha256": canonical_sha256({
            "requested_basis": "next_bar", "decision_at": decision_at.isoformat(),
            "asset_rows": [(last[0].isoformat(), price)],
        }),
    }
    return entry_at, price, outcome


def label_mature(con: duckdb.DuckDBPyConnection, *, labeled_at: datetime) -> int:
    """Append next-bar and next-session labels without changing prior outcomes."""
    latest = con.execute("SELECT MAX(date) FROM prices WHERE ticker='SPY'").fetchone()[0]
    if latest is None:
        return 0
    inserted = 0
    rows = con.execute(
        "SELECT id,ticker,decision_at FROM p15_event_decisions "
        "ORDER BY id"
    ).fetchall()
    for decision_id, ticker, decision_at in rows:
        decision_utc = decision_at.replace(tzinfo=timezone.utc)
        decision_day = decision_utc.astimezone(p15_event_sources.ET).date()
        decision_session_end = datetime.combine(
            decision_day, p15_event_sources.session_close(decision_day),
            p15_event_sources.ET,
        ).astimezone(timezone.utc).replace(tzinfo=None)
        sessions = [row[0] for row in con.execute(
            "SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? AND date<=? "
            "ORDER BY date LIMIT 20", [decision_at.date(), latest],
        ).fetchall()]
        intraday = None
        if table_exists(con, "bitemporal_facts"):
            intraday = con.execute(
                "WITH known AS (SELECT security_id,event_at,normalized_payload,fact_sha256 "
                "FROM bitemporal_facts WHERE fact_type='intraday.ohlcv.5m' "
                "AND event_at>? AND event_at<? "
                "AND available_at<=? AND ingested_at<=? "
                "QUALIFY revision=MAX(revision) OVER "
                "(PARTITION BY entity_id,fact_type,event_at)) "
                "SELECT a.event_at,a.normalized_payload,a.fact_sha256,"
                "s.normalized_payload,s.fact_sha256 FROM known a JOIN known s "
                "ON s.security_id='SPY' AND s.event_at=a.event_at "
                "WHERE a.security_id=? ORDER BY a.event_at LIMIT 1",
                [decision_at, decision_session_end, labeled_at.replace(tzinfo=None),
                 labeled_at.replace(tzinfo=None), ticker],
            ).fetchone()
        same_day_sessions = [row[0] for row in con.execute(
            "SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? AND date<=? "
            "ORDER BY date LIMIT 20", [decision_at.date(), latest],
        ).fetchall()]
        labeled_local = labeled_at.astimezone(p15_event_sources.ET)
        session_closed = (labeled_local.date() > decision_day or (
            labeled_local.date() == decision_day
            and labeled_local.timetz().replace(tzinfo=None)
            >= p15_event_sources.session_close(decision_day)
        ))
        missing_next_bar = None if intraday is not None or not session_closed else _missing_next_bar(
            con, ticker, decision_at, labeled_at
        )
        for horizon in HORIZONS:
            if len(sessions) >= horizon:
                outcome = agent_evaluation._label_outcome(
                    con, ticker, sessions[:horizon], labeled_at
                )
                if outcome is not None:
                    entry_at = datetime.combine(
                        outcome["entry_date"], time(9, 30), p15_event_sources.ET
                    ).astimezone(timezone.utc).replace(tzinfo=None)
                    inserted += _insert_label(
                        con, int(decision_id), horizon, "next_session_open", entry_at,
                        outcome, float(outcome["entry_open"]),
                        float(outcome["spy_return"]), labeled_at,
                    )
            if intraday is not None and len(same_day_sessions) >= horizon:
                outcome = agent_evaluation._label_outcome(
                    con, ticker, same_day_sessions[:horizon], labeled_at
                )
                if outcome is not None and outcome["exit_date"] >= intraday[0].date():
                    entry_at, asset_raw, asset_sha, spy_raw, spy_sha = intraday
                    asset, spy = json.loads(asset_raw), json.loads(spy_raw)
                    spy_exit = con.execute(
                        f"SELECT close FROM prices WHERE ticker='SPY' AND date=? "
                        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL}",
                        [outcome["exit_date"], labeled_at.replace(tzinfo=None)],
                    ).fetchone()[0]
                    outcome = {**outcome, "price_prefix_sha256": canonical_sha256({
                        "daily": outcome["price_prefix_sha256"],
                        "entry_facts": [asset_sha, spy_sha],
                    })}
                    inserted += _insert_label(
                        con, int(decision_id), horizon, "next_bar", entry_at,
                        outcome, float(asset["open"]),
                        float(spy_exit) / float(spy["open"]) - 1, labeled_at,
                    )
            elif missing_next_bar is not None and len(same_day_sessions) >= horizon:
                entry_at, entry_px, outcome = missing_next_bar
                inserted += _insert_label(
                    con, int(decision_id), horizon, "next_bar", entry_at,
                    outcome, entry_px, 0.0, labeled_at,
                )
    return inserted


def score_pending(
    con: duckdb.DuckDBPyConnection, *, session_date: date, observed_at: datetime,
    source_summary: dict, information_cutoff_at: datetime | None = None,
    generate: Callable[[dict], agent_model_client.ConnectorResult]
    = agent_model_client.generate_p15_event_json,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    p15_event_sources.init_schema(con)
    window_id, resolved_session = _window(observed_at)
    observed_at = observed_at.astimezone(timezone.utc)
    cutoff = (information_cutoff_at or observed_at).astimezone(timezone.utc)
    if cutoff < observed_at:
        raise EventRunError("event information cutoff precedes its window")
    if session_date != resolved_session:
        raise EventRunError("event session date differs from its window")
    labels = label_mature(con, labeled_at=cutoff)
    for (stale_window,) in con.execute(
        "SELECT window_id FROM p15_event_windows WHERE status='running' ORDER BY observed_at"
    ).fetchall():
        _recover_window(con, stale_window, cutoff)
    with db.transaction(con):
        _terminalize_stale_triggers(con, session_date, cutoff)
    existing = con.execute(
        "SELECT status,decision_count,skipped_count FROM p15_event_windows WHERE window_id=?",
        [window_id],
    ).fetchone()
    if existing is not None:
        if existing[0] == "running":
            _recover_window(con, window_id, cutoff)
        result = _replay_window(con, window_id)
        return {**result, "labels": labels}
    used = int(con.execute(
        "SELECT COUNT(*) FROM p15_event_decisions d JOIN p15_event_triggers t "
        "ON t.id=d.trigger_id WHERE t.session_date=?", [session_date],
    ).fetchone()[0])
    available = max(0, MAX_DECISIONS_PER_SESSION - used)
    rows = con.execute(
        "SELECT id,ticker,source,event_type,event_at,available_at,triggered_at,fact_sha256 "
        "FROM p15_event_triggers WHERE session_date=? AND status='pending' "
        "AND available_at<=? AND triggered_at<=? ORDER BY available_at,id",
        [session_date, cutoff.replace(tzinfo=None), cutoff.replace(tzinfo=None)],
    ).fetchall()
    selected, skipped = rows[:available], rows[available:]
    contexts, allowed = _context(con, selected, cutoff)
    summary = {"source_summary": source_summary,
               "trigger_ids": [int(row[0]) for row in rows],
               "selected_contexts": contexts}
    with db.transaction(con):
        for row in skipped:
            con.execute(
                "UPDATE p15_event_triggers SET status='skipped_rate_limit',reason=? WHERE id=?",
                ["60 decision session limit reached", row[0]],
            )
        con.execute(
            "INSERT INTO p15_event_windows VALUES "
            "(?,?,?,?,?,NULL,'running',NULL,?,?,0,?,NULL)",
            [_next_id(con, "p15_event_windows"), window_id, session_date,
             observed_at.replace(tzinfo=None), cutoff.replace(tzinfo=None),
             json.dumps(summary, sort_keys=True, separators=(",", ":")),
             len(rows), len(skipped)],
        )
    decisions, call_count = [], 0
    unavailable_contexts = [item for item in contexts if item["context_status"] == "unavailable"]
    with db.transaction(con):
        for event in unavailable_contexts:
            item = {"trigger_id": event["trigger_id"], "ticker": event["ticker"],
                    "event_type": event["event_type"], "p_outperform_5": None,
                    "expected_excess_bp_5": None, "expected_excess_bp_10": None,
                    "action": "unavailable", "thesis": None, "invalidation": None,
                    "evidence_ids": [event["trigger_evidence_id"]]}
            latency = (cutoff - datetime.fromisoformat(
                event["triggered_at"]
            ).replace(tzinfo=timezone.utc)).total_seconds() * 1000
            if latency < 0:
                raise EventRunError("event decision latency is negative")
            identity = {"window_id": window_id, "trigger_id": item["trigger_id"],
                        "decision": item, "decision_at": cutoff.isoformat(),
                        "triggered_at": event["triggered_at"],
                        "latency_ms": latency,
                        "execution_authority": "none"}
            con.execute(
                "INSERT INTO p15_event_decisions VALUES (?,?,?,?,?,'unavailable',?,?,?,?,?)",
                [_next_id(con, "p15_event_decisions"), window_id, item["trigger_id"],
                 item["ticker"], item["event_type"],
                 json.dumps(item, sort_keys=True, separators=(",", ":")),
                 canonical_sha256(identity), datetime.fromisoformat(event["triggered_at"]),
                 cutoff.replace(tzinfo=None), identity["latency_ms"]],
            )
            con.execute(
                "UPDATE p15_event_triggers SET status='unavailable',reason=? WHERE id=?",
                ["daily context unavailable", item["trigger_id"]],
            )
            decisions.append(item)
    model_contexts = [item for item in contexts if item["context_status"] == "available"]
    for chunk_index in range(0, len(model_contexts), CHUNK_SIZE):
        chunk = model_contexts[chunk_index:chunk_index + CHUNK_SIZE]
        payload = {"schema_version": 1, "policy_id": POLICY_ID,
                   "window_id": window_id, "observed_at": observed_at.isoformat(),
                   "information_cutoff_at": cutoff.isoformat(),
                   "execution_authority": "none", "events": chunk}
        started = clock().astimezone(timezone.utc)
        call_id = _next_id(con, "p15_event_calls")
        request_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        request_sha = canonical_sha256(agent_model_client.p15_event_request_payload(payload))
        con.execute(
            "INSERT INTO p15_event_calls VALUES "
            "(?,?,?,?,?,NULL,NULL,'running',NULL,?,NULL,NULL)",
            [call_id, window_id, chunk_index // CHUNK_SIZE, request_text,
             request_sha, started.replace(tzinfo=None)],
        )
        response, error = None, None
        try:
            generated = generate(payload)
            _identity(generated, payload)
            response = asdict(generated)
            parsed = _validate(response["output"], chunk, allowed)
        except (agent_model_client.ConnectorError, EventRunError, TypeError, ValueError) as exc:
            error = str(exc)[:500]
            parsed = [{"trigger_id": item["trigger_id"], "ticker": item["ticker"],
                       "event_type": item["event_type"], "p_outperform_5": None,
                       "expected_excess_bp_5": None, "expected_excess_bp_10": None,
                       "action": "unavailable", "thesis": None, "invalidation": None,
                       "evidence_ids": [item["trigger_evidence_id"]]} for item in chunk]
        completed = clock().astimezone(timezone.utc)
        response_text = None if response is None else json.dumps(
            response, sort_keys=True, separators=(",", ":")
        )
        call_status = "completed" if error is None else "unavailable"
        call_identity = {"window_id": window_id, "chunk_index": chunk_index // CHUNK_SIZE,
                         "request_sha256": request_sha,
                         "response_sha256": None if response is None else canonical_sha256(response),
                         "status": call_status, "error": error,
                         "started_at": started.isoformat(), "completed_at": completed.isoformat()}
        with db.transaction(con):
            con.execute(
                "UPDATE p15_event_calls SET response_payload=?,response_sha256=?,status=?,"
                "error=?,completed_at=?,call_sha256=? WHERE id=? AND status='running'",
                [response_text, call_identity["response_sha256"], call_status, error,
                 completed.replace(tzinfo=None), canonical_sha256(call_identity), call_id],
            )
            for item in parsed:
                trigger = next(row for row in selected if row[0] == item["trigger_id"])
                decision_id = _next_id(con, "p15_event_decisions")
                latency = (completed.replace(tzinfo=None) - trigger[6]).total_seconds() * 1000
                if latency < 0:
                    raise EventRunError("event decision latency is negative")
                identity = {"window_id": window_id, "trigger_id": item["trigger_id"],
                            "decision": item, "decision_at": completed.isoformat(),
                            "triggered_at": trigger[6].replace(tzinfo=timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "execution_authority": "none"}
                con.execute(
                    "INSERT INTO p15_event_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [decision_id, window_id, item["trigger_id"], item["ticker"],
                     item["event_type"], "available" if error is None else "unavailable",
                     json.dumps(item, sort_keys=True, separators=(",", ":")),
                     canonical_sha256(identity), trigger[6], completed.replace(tzinfo=None), latency],
                )
                con.execute(
                    "UPDATE p15_event_triggers SET status=?,reason=? WHERE id=?",
                    ["scored" if error is None else "unavailable", error, item["trigger_id"]],
                )
                decisions.append(item)
        call_count += 1
    completed = clock().astimezone(timezone.utc)
    identity = {"window_id": window_id, "session_date": session_date.isoformat(),
                "observed_at": observed_at.isoformat(),
                "information_cutoff_at": cutoff.isoformat(),
                "completed_at": completed.isoformat(),
                "status": "completed", "reason": None, "source_summary": summary,
                "trigger_count": len(rows), "decision_count": len(decisions),
                "skipped_count": len(skipped)}
    con.execute(
        "UPDATE p15_event_windows SET completed_at=?,status='completed',"
        "decision_count=?,window_sha256=? WHERE window_id=? AND status='running'",
        [completed.replace(tzinfo=None), len(decisions), canonical_sha256(identity), window_id],
    )
    return {"status": "completed", "decisions": len(decisions),
            "skipped": len(skipped), "model_calls": call_count,
            "unavailable": sum(item["action"] == "unavailable" for item in decisions),
            "labels": labels, "replayed": False, "execution_authority": "none"}


def run_database(
    database: Path = DEFAULT_DB, *, observed_at: datetime | None = None,
    rss_path: Path = p15_event_sources.RSS_PATH, generate=agent_model_client.generate_p15_event_json,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        _window_id, session_date = _window(observed)
    except EventRunError:
        return {"status": "outside_session", "execution_authority": "none"}
    with advisory_file_lock(LOCK_PATH), advisory_file_lock(NIGHTLY_LOCK):
        con = db.connect(database, wait_s=0)
        try:
            p15_event_sources.init_schema(con)
            p15_event_sources.initialize_event_evidence(con, now=observed)
            checkpointed = con.execute(
                "SELECT 1 FROM p15_rss_checkpoints WHERE source_id=?",
                [p15_event_sources.RSS_SOURCE],
            ).fetchone()
            rss = (p15_event_sources.ingest_rss(con, rss_path, now=observed)
                   if rss_path.exists() and checkpointed else
                   p15_event_sources.initialize_rss_checkpoint(con, rss_path, now=observed)
                   if rss_path.exists() else {"status": "unavailable"})
            names = list(p15_event_sources._universe_names(con)[0])
            local = observed.astimezone(p15_event_sources.ET)
            sec_names = _sec_names(names, session_date, local.hour, local.minute)
            sec = ({"status": "unconfigured"} if not os.environ.get(
                "TRADING_ENGINE_SEC_USER_AGENT"
            ) else sec_edgar_capture.capture(con, sec_names))
            intraday = p15_event_sources.scan_intraday(con, observed_at=observed)
            cutoff = clock().astimezone(timezone.utc)
            triggers = p15_event_sources.create_text_triggers(
                con, session_date, triggered_at=cutoff
            )
            return score_pending(
                con, session_date=session_date, observed_at=observed,
                information_cutoff_at=cutoff,
                source_summary={"rss": rss, "sec": sec, "intraday": intraday,
                                "text_triggers": triggers}, generate=generate, clock=clock,
            )
        finally:
            con.close()


def _sec_names(names: list[str], session_date: date, hour: int, minute: int) -> list[str]:
    if not names:
        return []
    slot = (hour * 60 + minute) // 15
    offset = (session_date.toordinal() + slot * 5) % len(names)
    return (names[offset:] + names[:offset])[:5]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run", action="store_true", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_database(args.database), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
