"""W3 filing scope and writer-free shadow scoring orchestration."""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import p16_filing_parser, p16_filing_sources, p16_screen_inputs
from engine.lib import db, resources
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
from engine.lib.util import table_exists
from server import agent_model_client, p16_filing_client, p16_filing_store

POLICY_ID = "p16-filings-v1"
MAX_MODEL_CALLS = 2
ET = ZoneInfo("America/New_York")
MODEL_LOCK = DEFAULT_DB.parent / ".p16-filing-model.lock"
class FilingRunError(ValueError):
    """A W3 input, identity, or persisted state is unusable."""
def _utc(value, *, database_value: bool = False) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise FilingRunError("filing runner timestamp is invalid") from exc
    if parsed.utcoffset() is None and not database_value:
        raise FilingRunError("filing runner timestamp requires a timezone")
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
def readiness(*, environ=None, legacy_sec_enabled: bool) -> dict:
    """Keep W3 inactive until contact and aggregate-dispatch ownership are safe."""
    if p16_filing_sources.configured_user_agent(environ) is None:
        return {"status": "unconfigured", "sec_requests": 0, "model_calls": 0}
    if legacy_sec_enabled:
        return {"status": "shared_dispatch_required", "sec_requests": 0, "model_calls": 0}
    return {"status": "ready", "sec_requests": 0, "model_calls": 0}
def _p15_snapshot(con, cutoff: datetime) -> dict | None:
    if not table_exists(con, "p15_scoring_runs"):
        return None
    row = con.execute(
        "SELECT id,market_date,universe_payload,universe_sha256,completed_at "
        "FROM p15_scoring_runs WHERE status='completed' AND completed_at<=? "
        "ORDER BY completed_at DESC,id DESC LIMIT 1", [cutoff.replace(tzinfo=None)],
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row[2])
    except (TypeError, ValueError) as exc:
        raise FilingRunError("retained P15 universe is invalid") from exc
    bundle_sha = payload.get("bundle_sha256")
    body = {key: value for key, value in payload.items() if key != "bundle_sha256"}
    if row[3] != canonical_sha256(payload) or bundle_sha != canonical_sha256(body):
        raise FilingRunError("retained P15 universe identity differs")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("ticker"), str)
            for item in candidates):
        raise FilingRunError("retained P15 universe is invalid")
    return {"run_id": int(row[0]), "market_date": row[1].isoformat(), "universe_sha256": row[3],
            "completed_at": _utc(row[4], database_value=True).isoformat(),
            "tickers": sorted({item["ticker"] for item in candidates})}
def frozen_scope(
    con, *, market_date: date, scan_started_at: datetime, map_sha256: str,
    aliases: dict[str, str] | None = None,
) -> dict:
    """Freeze latest cutoff-bounded P15/template names into CIK/security scope."""
    cutoff = _utc(scan_started_at)
    p15 = _p15_snapshot(con, cutoff)
    screen = p16_screen_inputs.screen_as_known(
        con, market_date, information_cutoff_at=cutoff,
    )
    tickers = set(() if p15 is None else p15["tickers"])
    if screen["status"] == "available":
        tickers.update(row["ticker"] for row in screen["rows"] if row.get("passes_template"))
    if not tickers:
        return {"status": "universe_unavailable", "universe": {}, "p15": p15,
                "screen": screen}
    if not isinstance(map_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", map_sha256) is None:
        raise FilingRunError("filing security map identity is invalid")
    receipt = con.execute(
        "SELECT endpoint,received_at,content_type,response_body,response_size_bytes "
        "FROM source_response_receipts WHERE source='sec-edgar' AND dataset='ticker_map' "
        "AND response_sha256=? AND http_status=200 AND received_at<=? "
        "ORDER BY received_at DESC LIMIT 1", [map_sha256, cutoff.replace(tzinfo=None)],
    ).fetchone()
    if receipt is None:
        raise FilingRunError("retained filing security map is unavailable")
    body = bytes(receipt[3])
    if hashlib.sha256(body).hexdigest() != map_sha256:
        raise FilingRunError("retained filing security map identity differs")
    received = _utc(receipt[1], database_value=True)
    map_snapshot = p16_filing_sources.parse_ticker_map(p16_filing_sources.SecResponse(
        200, receipt[2], {}, body, received, received, receipt[0], int(receipt[4]), True))
    if p16_filing_sources.ticker_map_status(map_snapshot, at=cutoff) != "ready":
        return {"status": "map_stale", "universe": {}, "p15": p15, "screen": screen}
    aliases = aliases or {}
    if not isinstance(aliases, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                            for key, value in aliases.items()):
        raise FilingRunError("cutoff-bounded filing security master is unavailable")
    canonical_tickers = {aliases.get(ticker, ticker) for values in
                         map_snapshot["cik_tickers"].values() for ticker in values}
    try:
        liquidity = p16_screen_inputs.security_liquidity_as_known(
            con, canonical_tickers, market_date=market_date, information_cutoff_at=cutoff)
    except ValueError as exc:
        raise FilingRunError(str(exc)) from exc
    if not set(aliases.values()) <= set(liquidity):
        raise FilingRunError("cutoff-bounded filing security master is unavailable")
    security_rows = [{"cik": cik, "ticker": ticker, "security_id": aliases.get(ticker, ticker),
                      "snapshot_id": map_sha256, "available_at": map_snapshot["received_at"]}
                     for cik, values in map_snapshot["cik_tickers"].items()
                     for ticker in values if aliases.get(ticker, ticker) in liquidity]
    ciks = sorted(map_snapshot["cik_tickers"])
    universe = {}
    for cik in ciks:
        mapped = p16_filing_parser.map_cik_scope(
            cik, rows=security_rows, snapshot_id=map_sha256, universe=tickers,
            cutoff_at=cutoff, aliases=aliases,
        )
        if mapped["status"] != "mapped":
            continue
        selected = mapped["securities"]
        if any(item["security_id"] not in liquidity for item in selected):
            raise FilingRunError("primary security liquidity is unavailable")
        volumes = {item["security_id"]: liquidity[item["security_id"]]["median_dollar_volume_60d"]
                   for item in selected}
        liquidity_lineage = {item["security_id"]: liquidity[item["security_id"]]["price_rows_sha256"]
                             for item in selected}
        primary = min(volumes, key=lambda security_id: (-volumes[security_id], security_id))
        entered_at = cutoff
        if table_exists(con, "p16_filing_scans"):
            prior = con.execute(
                    "SELECT universe_json FROM p16_filing_scans WHERE policy_id=? AND started_at<=? "
                    "ORDER BY started_at DESC LIMIT 1",
                    [POLICY_ID, cutoff.replace(tzinfo=None)]).fetchone()
            prior_scope = None if prior is None else json.loads(prior[0]).get(cik)
            if prior_scope:
                entered_at = _utc(prior_scope["entered_at"])
        universe[cik] = {
            "entered_at": entered_at.isoformat(),
            "securities": sorted(volumes),
            "security_tickers": {item["security_id"]: item["ticker"] for item in selected},
            "primary_security_id": primary,
            "selection_sha256": canonical_sha256({"map_sha256": map_sha256, "market_date": market_date.isoformat(),
                                                   "cutoff_at": cutoff.isoformat(), "aliases": aliases, "liquidity": liquidity_lineage}),
        }
    return {"status": "ready" if universe else "map_unavailable", "universe": universe,
            "map_sha256": map_sha256, "p15": p15, "screen": screen,
            "scope_sha256": canonical_sha256({"universe": universe, "map_sha256": map_sha256,
                                               "p15": p15, "screen": screen})}
def _work(con, work_id: str) -> dict:
    cursor = con.execute(
        "SELECT work_id,policy_id,accession,security_id,session_date,input_json,status "
        "FROM p16_filing_work_events WHERE work_id=? ORDER BY sequence DESC LIMIT 1", [work_id],
    )
    row = cursor.fetchone()
    if row is None:
        raise FilingRunError("filing score work is unavailable")
    return dict(zip((item[0] for item in cursor.description), row, strict=True))
def build_input(con, work: dict, *, cutoff_at: datetime) -> dict:
    """Build one exact filing/security request from immutable retained state."""
    work_input = json.loads(work["input_json"])
    try:
        row = p16_filing_store.verified_score_bundle(
            con, bundle_sha256=work_input.get("bundle_sha256"),
            policy_id=work["policy_id"], accession=work["accession"],
        )
    except ValueError as exc:
        raise FilingRunError(str(exc)) from exc
    normalized, scope = row["normalized"], row["universe"][row["cik"]]
    ticker = scope["security_tickers"].get(work["security_id"])
    spans = normalized.get("spans")
    if not ticker or not isinstance(spans, list) or not spans:
        raise FilingRunError("filing model evidence is unavailable")
    published, available, ingested = (_utc(row[key], database_value=True).isoformat()
                                      for key in ("accepted_at", "available_at", "ingested_at"))
    evidence = [{**{key: span[key] for key in (
        "evidence_id", "text", "source_sha256", "filename", "parser_version",
        "normalized_sha256", "start", "end")}, "published_at": published,
        "available_at": available, "ingested_at": ingested} for span in spans]
    items = set(normalized.get("items", ()))
    allowed_kinds = [p16_filing_parser.EVENTS[item] for item in p16_filing_parser.PRECEDENCE
                     if item in items]
    cutoff = _utc(cutoff_at).isoformat()
    payload = {
        "schema_version": 1, "policy_id": POLICY_ID, "call_id": work["work_id"],
        "model_identity": p16_filing_client.identity(), "accession": work["accession"],
        "cik": row["cik"], "issuer_id": f"sec-cik:{row['cik']}",
        "security_id": work["security_id"], "ticker": ticker,
        "information_cutoff_at": cutoff, "current_decision_time": cutoff,
        "expected_entry_rule": p16_filing_client.ENTRY_RULE,
        "source_bundle_sha256": work_input["bundle_sha256"], "evidence": evidence,
        "allowed_evidence_ids": [item["evidence_id"] for item in evidence],
        "allowed_event_kinds": allowed_kinds,
        "text_completeness": {"status": "truncated" if normalized.get("truncated")
                              else "primary_only" if row["status"] == "primary_only" else "full",
                              "exhibit_status": row["exhibit_status"]},
        "previous_guidance": normalized.get("previous_guidance"),
        "consensus": normalized.get("consensus"),
        "comparable_consensus": bool(normalized.get("comparable_consensus")),
        "company_consensus_statement": bool(normalized.get("company_consensus_statement")),
        "company_consensus_evidence_ids": normalized.get("company_consensus_evidence_ids", []),
        "company_consensus_context": normalized.get("company_consensus_context"),
        "held": work["security_id"] in normalized.get("held_security_ids", []),
        "tradeable": False, "reason": "shadow_only",
        "underlying_p15_gates": normalized.get("underlying_p15_gates", []),
        "prior_market_context": normalized.get("prior_market_context", {}),
    }
    return p16_filing_client.validate_input(payload)
def _validate_identity(result, request: dict) -> None:
    if not isinstance(result, p16_filing_client.FilingConnectorResult):
        raise FilingRunError("filing model result is invalid")
    expected = p16_filing_client.identity()
    observed = {"model": result.model, "model_version": result.model_version,
                "upstream_model_family": result.upstream_model_family,
                "model_catalog_entry_sha256": result.model_catalog_entry_sha256,
                "proxy_version": result.proxy_version, "proxy_source_sha256": result.proxy_source_sha256,
                "traecli_runtime": result.traecli_runtime}
    required = {"model": expected["model"], "model_version": expected["model_version"],
                "upstream_model_family": expected["upstream_model_family"],
                "model_catalog_entry_sha256": expected["model_catalog_entry_sha256"],
                "proxy_version": expected["required_proxy_version"],
                "proxy_source_sha256": expected["required_proxy_source_sha256"],
                "traecli_runtime": expected["required_traecli_runtime"]}
    if observed != required or result.request_sha256 != canonical_sha256(request):
        raise FilingRunError("filing model identity differs")
def _retryable(exc: Exception) -> bool:
    reason = str(exc).casefold()
    return "proxy is unavailable" in reason or "deadline exceeded" in reason
def _response_payload(result) -> dict:
    return asdict(result)
def _error_payload(error: agent_model_client.ConnectorError) -> dict | None:
    payload = {"error": str(error), "response_id": getattr(error, "response_id", None),
               "request_sha256": getattr(error, "request_sha256", None), "response_sha256": getattr(error, "response_sha256", None),
               "usage": getattr(error, "usage", None),
               "raw_response_sha256": getattr(error, "raw_response_sha256", None)}
    return payload if any(value is not None for key, value in payload.items() if key != "error") else None
def _append_work(con, work, *, status: str, at: datetime, reason: str) -> str:
    return p16_filing_store.append_work_event(
        con, policy_id=work["policy_id"], work_kind="score", accession=work["accession"],
        security_id=work["security_id"], session_date=work["session_date"], status=status,
        event_at=at, not_before=at, input_payload=json.loads(work["input_json"]), reason=reason,
    )
def _recover_started(con, *, now: datetime, session_date: date) -> list[str]:
    cursor = con.execute(
        "SELECT work_id FROM p16_filing_work_events WHERE work_kind='score' "
        "QUALIFY sequence=MAX(sequence) OVER (PARTITION BY work_id) AND status='started'",
    )
    unavailable = []
    for work_id, in cursor.fetchall():
        work = _work(con, work_id)
        attempt = con.execute(
            "SELECT attempt_sha256,attempt_number FROM p16_filing_score_attempts "
            "WHERE work_id=? ORDER BY attempt_number DESC LIMIT 1", [work_id]).fetchone()
        if work["session_date"] != session_date:
            if attempt is not None:
                p16_filing_store.record_decision(con, attempt_sha256=attempt[0],
                    status="unavailable", decided_at=now, response_payload=None,
                    reason="transport:orphaned_prior_session")
            else:
                with db.transaction(con):
                    _append_work(con, work, status="unavailable", at=now,
                                 reason="preflight:orphaned_prior_session")
            unavailable.append(work_id)
        elif attempt is not None and attempt[1] == 1:
            with db.transaction(con):
                _append_work(con, work, status="retry", at=now, reason="transport_lost")
        elif attempt is not None:
            p16_filing_store.record_decision(
                con, attempt_sha256=attempt[0], status="unavailable", decided_at=now,
                response_payload=None, reason="transport:orphaned_call")
            unavailable.append(work_id)
        else:
            with db.transaction(con):
                _append_work(
                    con, work, status="unavailable", at=now, reason="preflight:orphaned_claim",
                )
            unavailable.append(work_id)
    return unavailable
def _score_pending_locked(database, *, now, session_date, generate, clock) -> dict:
    con = db.connect(database)
    prepared = []
    try:
        unavailable = _recover_started(con, now=now, session_date=session_date)
        with db.transaction(con):
            capacity = p16_filing_store.claim_score_capacity(
                con, session_date=session_date, now=now, batch_size=MAX_MODEL_CALLS,
                in_transaction=True)
            unavailable.extend(capacity["capacity_unavailable"])
            for work_id in capacity["claimed"]:
                work = _work(con, work_id)
                try:
                    prior = con.execute(
                        "SELECT request_json FROM p16_filing_score_attempts WHERE work_id=? "
                        "ORDER BY attempt_number LIMIT 1", [work_id],
                    ).fetchone()
                    if prior:
                        request = json.loads(prior[0])
                        payload = json.loads(request["input"])
                        if p16_filing_client.request_payload(payload) != request:
                            raise FilingRunError("filing retry request differs")
                    else:
                        payload = build_input(con, work, cutoff_at=now)
                        request = p16_filing_client.request_payload(payload)
                    attempt = p16_filing_store.record_score_attempt(
                        con, work_id=work_id, started_at=now, request_payload=request,
                        runtime_identity=p16_filing_client.identity())
                    prepared.append((work, payload, request, attempt))
                except (FilingRunError, agent_model_client.ConnectorError, KeyError, ValueError) as exc:
                    _append_work(
                        con, work, status="unavailable", at=now, reason=f"preflight:{exc}",
                    )
                    unavailable.append(work_id)
    finally:
        con.close()
    def invoke(item):
        try:
            result, error = generate(item[1]), None
        except (agent_model_client.ConnectorError, OSError, TimeoutError) as exc:
            result, error = None, exc
        return item, result, error, _utc(clock())
    with ThreadPoolExecutor(max_workers=MAX_MODEL_CALLS) as executor:
        outcomes = list(executor.map(invoke, prepared))
    con = db.connect(database)
    completed, retried = [], []
    try:
        for (work, payload, request, attempt), result, error, completed_at in outcomes:
            try:
                if error is not None:
                    raise error
                _validate_identity(result, request)
                output = p16_filing_client.validate_output(result.output, payload)
                response = {**_response_payload(result), "output": output}
                p16_filing_store.record_decision(
                    con, attempt_sha256=attempt, status="scored", decided_at=completed_at,
                    response_payload=response)
                completed.append(work["work_id"])
            except (agent_model_client.ModelOutputError, FilingRunError) as exc:
                response = (_response_payload(result) if result is not None
                            else _error_payload(exc) if isinstance(
                                exc, agent_model_client.ModelOutputError) else None)
                p16_filing_store.record_decision(
                    con, attempt_sha256=attempt, status="unavailable",
                    decided_at=completed_at, response_payload=response,
                    reason=f"invalid:{exc}")
                unavailable.append(work["work_id"])
            except (agent_model_client.ConnectorError, OSError, TimeoutError) as exc:
                retry_count = int(con.execute(
                    "SELECT COUNT(*) FROM p16_filing_work_events "
                    "WHERE work_id=? AND status='retry'", [work["work_id"]],
                ).fetchone()[0])
                if _retryable(exc) and retry_count == 0:
                    with db.transaction(con):
                        _append_work(
                            con, work, status="retry", at=completed_at, reason="transport_lost",
                        )
                    retried.append(work["work_id"])
                else:
                    p16_filing_store.record_decision(
                        con, attempt_sha256=attempt, status="unavailable",
                        decided_at=completed_at, response_payload=_error_payload(exc),
                        reason=f"transport:{exc}")
                    unavailable.append(work["work_id"])
    finally:
        con.close()
    return {"status": "completed", "claimed": len(prepared), "scored": len(completed),
            "retried": len(retried), "unavailable": len(unavailable), "model_calls": len(prepared)}
def score_pending(
    database: Path = DEFAULT_DB, *, observed_at: datetime | None = None,
    session_date: date | None = None, environ=None, legacy_sec_enabled: bool = True,
    generate=p16_filing_client.generate_json, clock=lambda: datetime.now(timezone.utc),
) -> dict:
    """Serialize W3 calls globally, release DuckDB during inference, and append outcomes."""
    ready = readiness(environ=environ, legacy_sec_enabled=legacy_sec_enabled)
    if ready["status"] != "ready":
        return ready
    now = _utc(observed_at or clock())
    exchange_date = session_date or now.astimezone(ET).date()
    database = Path(database)
    with resources.advisory_file_lock(MODEL_LOCK):
        return _score_pending_locked(
            database, now=now, session_date=exchange_date, generate=generate, clock=clock)
