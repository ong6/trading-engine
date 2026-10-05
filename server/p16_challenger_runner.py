"""Timer-safe P16 challenger scoring over the exact retained P15 bundle.

The runner never rebuilds P15 inputs.  It validates the retained P15 evidence,
closes DuckDB before each model call, records all eight family members, and
then invokes the registered pre-entry chain before the next NYSE open.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import tempfile
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import median
from typing import Callable
from zoneinfo import ZoneInfo

import duckdb

from engine import p15_event_sources
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.p16_challenger_inputs import (
    ablate,
    blind,
    enrich,
    memory_examples,
    metadata_envelope,
)
from farm import p16_eval_inputs, p16_trials
from server import (
    agent_model_client,
    p15_scoring_store,
    p16_challenger_store,
    p16_model_client,
    p16_preentry,
    p16_registration,
    p16_store,
    p16_trial_store,
)
from sim import nyse
from tools.backup_database import _copy_database

SAMPLE_COUNT = 3
MAX_EXPECTED_EXCESS_BP = 10_000
LOCK_PATH = REPO_ROOT / ".p16-challengers.lock"
NIGHTLY_LOCK = REPO_ROOT / ".nightly.lock"
ET = ZoneInfo("America/New_York")
MODEL_MEMBERS = tuple(
    member for member in p16_registration.MEMBER_IDS if member != "c-ensemble"
)


class ChallengerRunError(ValueError):
    """The exact prospective challenger run cannot be completed honestly."""


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ChallengerRunError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ChallengerRunError(f"{field} is invalid") from exc
    return _aware(parsed, field)


def _next_open(market_date: date) -> datetime:
    return datetime.combine(
        nyse.next_session(market_date), time(9, 30), ET,
    ).astimezone(timezone.utc)


def _close(market_date: date) -> datetime:
    return datetime.combine(
        market_date, p15_event_sources.session_close(market_date), ET,
    ).astimezone(timezone.utc)


def _hash_treatment(original: dict, payload: dict, kind: str, **details) -> dict:
    body = {
        "treatment": kind,
        "original_sha256": canonical_sha256(original),
        "payload_sha256": canonical_sha256(payload),
        "payload": payload,
        **details,
    }
    return {**body, "treatment_sha256": canonical_sha256(body)}


def _trial_specs(registration: dict) -> list[dict]:
    specs = registration.get("trial_registrations")
    if not isinstance(specs, list) or not specs:
        raise ChallengerRunError("P16 trial registrations are absent")
    expected = {
        row["trial_id"] for row in registration["challengers"]["members"]
    } | {
        row["control_trial_id"] for row in registration["challengers"]["members"]
    }
    actual = {row.get("trial_id") for row in specs if isinstance(row, dict)}
    if actual != expected or len(actual) != len(specs):
        raise ChallengerRunError("P16 trial registration coverage differs")
    validated = []
    for row in specs:
        try:
            registered_at = _parse_time(row["registered_at"], "trial registration time")
            trial_id, _payload = p16_trials.registration(
                policy_id=row["policy_id"], policy_version=row["policy_version"],
                plan_id=row["plan_id"], registration_identity=row["registration_identity"],
                evidence_class=row["evidence_class"], trial_kind=row["trial_kind"],
                parent_trial_ids=row["parent_trial_ids"], registered_at=registered_at,
                identity_status=row["identity_status"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChallengerRunError("P16 trial registration differs") from exc
        if trial_id != row.get("trial_id"):
            raise ChallengerRunError("P16 trial registration identity differs")
        validated.append({**row, "registered_at": registered_at})
    return validated


def _model_contracts(registration: dict) -> dict[str, dict]:
    contracts = registration.get("model_contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ChallengerRunError("P16 model contracts are absent")
    result = {}
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ChallengerRunError("P16 model contract is invalid")
        identity = contract.get("model_contract_sha256")
        if identity != canonical_sha256({
                key: value for key, value in contract.items()
                if key != "model_contract_sha256"}):
            raise ChallengerRunError("P16 model contract identity differs")
        if identity in result:
            raise ChallengerRunError("P16 model contract is duplicated")
        result[identity] = contract
    members = registration["challengers"]["members"]
    expected = {row["model_contract_sha256"] for row in members
                if row["policy_id"] != "c-ensemble"}
    if set(result) != expected:
        raise ChallengerRunError("P16 member model contract coverage differs")
    return result


def _ensure_trials(con, registration: dict) -> None:
    p16_challenger_store.init_schema(con)
    p16_trial_store.load_census(con)
    for row in sorted(_trial_specs(registration), key=lambda item: len(item["parent_trial_ids"])):
        actual = p16_trial_store.register(
            con, policy_id=row["policy_id"], policy_version=row["policy_version"],
            plan_id=row["plan_id"], registration_identity=row["registration_identity"],
            evidence_class=row["evidence_class"], trial_kind=row["trial_kind"],
            parent_trial_ids=row["parent_trial_ids"], registered_at=row["registered_at"],
            recorded_at=row["registered_at"], identity_status=row["identity_status"],
        )
        if actual != row["trial_id"]:
            raise ChallengerRunError("P16 retained trial identity differs")


def _json_object(raw: object, field: str) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ChallengerRunError(f"{field} is invalid") from exc
    if not isinstance(value, dict):
        raise ChallengerRunError(f"{field} is invalid")
    return value


def _memory_history(con, cutoff: datetime, champion_identity: str) -> list[dict]:
    rows = con.execute(
        "SELECT d.decision_sha256,t.observed_at,d.decision_payload,l.exit_date,"
        "l.labeled_at,l.net_excess_return FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "JOIN agent_evaluation_labels_v2 l ON l.decision_id=d.id "
        "WHERE t.policy_id='p15-scoring-v1' AND t.terminal_status='completed' "
        "AND l.horizon_sessions=5 AND l.label_basis IN "
        "('next_session_open','missing_entry_last_available_close') "
        "AND l.labeled_at<=? ORDER BY t.market_date,d.ticker,l.id",
        [cutoff.replace(tzinfo=None)],
    ).fetchall()
    result = []
    for decision_id, decision_at, raw, exit_date, labeled_at, outcome in rows:
        payload = _json_object(raw, "P15 memory decision")
        mature_at = datetime.combine(exit_date, time(16), ET).astimezone(timezone.utc)
        result.append({
            "decision_id": decision_id, "policy_sha256": champion_identity,
            "horizon_sessions": 5, "evidence_class": "prospective_forward",
            "decision_at": decision_at.replace(tzinfo=timezone.utc).isoformat(),
            "label_mature_at": mature_at.isoformat(),
            "label_available_at": labeled_at.replace(tzinfo=timezone.utc).isoformat(),
            "standout_score": payload.get("standout_score"),
            "stratum": payload.get("stratum"),
            "sector": payload.get("sector", "unknown"),
            "net_excess_return": outcome, "thesis": payload.get("thesis"),
        })
    return result


def _retained_sample_chunks(sample_rows: list, selected: date, cutoff: datetime) -> list[dict]:
    samples = []
    for chunk_index, sample_index, raw, request_sha, status in sample_rows:
        request = _json_object(raw, "retained P15 request")
        if canonical_sha256(request) != request_sha or status not in {"completed", "failed"}:
            raise ChallengerRunError("retained P15 request identity differs")
        original = _json_object(request.get("input"), "retained P15 request input")
        if (
            original.get("chunk_index") != chunk_index
            or original.get("sample_index") != sample_index
            or original.get("market_date") != selected.isoformat()
            or _parse_time(original.get("information_cutoff_at"), "retained P15 request cutoff")
            != cutoff
        ):
            raise ChallengerRunError("retained P15 request grid differs")
        samples.append(
            {
                "chunk_index": chunk_index,
                "sample_index": sample_index,
                "original": original,
                "p15_request_sha256": request_sha,
            }
        )
    chunks = []
    for chunk_index in sorted({row["chunk_index"] for row in samples}):
        chunk = [row for row in samples if row["chunk_index"] == chunk_index]
        if [row["sample_index"] for row in chunk] != list(range(SAMPLE_COUNT)):
            raise ChallengerRunError("retained P15 sample grid is incomplete")
        sets = [
            {item.get("ticker") for item in row["original"].get("candidates", [])} for row in chunk
        ]
        if not sets[0] or any(item != sets[0] for item in sets[1:]):
            raise ChallengerRunError("retained P15 chunk candidates differ")
        chunks.append({"chunk_index": chunk_index, "tickers": sets[0], "samples": chunk})
    if [row["chunk_index"] for row in chunks] != list(range(len(chunks))):
        raise ChallengerRunError("retained P15 chunk grid differs")
    return chunks


def _source_snapshot(database: Path, market_date: date | None, now: datetime) -> dict:
    con = db.connect(database, read_only=True)
    try:
        selected = market_date
        if selected is None:
            row = con.execute(
                "SELECT MAX(market_date) FROM p15_scoring_runs "
                "WHERE policy_id='p15-scoring-v1' AND status='completed'"
            ).fetchone()
            selected = None if row is None else row[0]
        if selected is None or db.latest_operational_market_date(con) != selected:
            raise ChallengerRunError("latest completed P15 origin is unavailable")
        run = p15_scoring_store.find_run(con, selected)
        if run is None or run["status"] != "completed":
            raise ChallengerRunError("exact completed P15 scoring run is unavailable")
        origin = p16_eval_inputs.load_origin(
            con, market_date=selected, report_cutoff=now,
        )
        if origin["source"]["run_id"] != int(run["id"]):
            raise ChallengerRunError("P15 origin and scoring run differ")
        cutoff = _parse_time(
            origin["scoring_information_cutoff_at"], "P15 scoring cutoff")
        cursor = con.execute(
            "SELECT chunk_index,sample_index,request_payload,request_sha256,status "
            "FROM p15_scoring_samples WHERE run_id=? "
            "ORDER BY chunk_index,sample_index", [int(run["id"])],
        )
        sample_rows = cursor.fetchall()
        chunks = _retained_sample_chunks(sample_rows, selected, cutoff)
        frozen = _json_object(run["universe_payload"], "retained P15 universe")
        candidates = frozen.get("candidates")
        tickers = [row.get("ticker") for row in candidates] if isinstance(candidates, list) else []
        covered = [ticker for chunk in chunks for ticker in chunk["tickers"]]
        if (not tickers or len(tickers) != len(set(tickers))
                or set(covered) != set(tickers) or len(covered) != len(tickers)):
            raise ChallengerRunError("retained P15 request grid does not cover its universe")
        trace_rows = con.execute(
            "SELECT output_payload,output_sha256,trace_sha256 FROM agent_evaluation_traces "
            "WHERE policy_id='p15-scoring-v1' AND market_date=? "
            "AND source_kind='p15_scoring_run' AND source_identifier=? "
            "AND terminal_status='completed'", [selected, str(run["id"])],
        ).fetchall()
        if len(trace_rows) != 1:
            raise ChallengerRunError("retained P15 aggregate is absent or ambiguous")
        output = _json_object(trace_rows[0][0], "retained P15 aggregate")
        champion = output.get("assessments")
        if (canonical_sha256(output) != trace_rows[0][1]
                or trace_rows[0][2] != run["aggregate_trace_sha256"]
                or trace_rows[0][2] != origin["source"]["trace_sha256"]
                or not isinstance(champion, list)
                or {row.get("ticker") for row in champion} != set(tickers)):
            raise ChallengerRunError("retained P15 aggregate identity differs")
        envelope = metadata_envelope(
            con, tickers, selected.isoformat(), information_cutoff_at=cutoff.isoformat(),
        )
        history = _memory_history(con, cutoff, origin["p15_registration_sha256"])
    finally:
        con.close()
    source_identity = {
        "p15_registration_sha256": origin["p15_registration_sha256"],
        "p15_run_id": int(run["id"]), "p15_run_trace_sha256": trace_rows[0][2],
        "p15_bundle_sha256": origin["source"]["bundle_sha256"],
        "p15_universe_sha256": origin["source"]["universe_sha256"],
        "p15_context_sha256": origin["source"]["context_sha256"],
        "metadata_envelope_sha256": envelope["metadata_envelope_sha256"],
    }
    return {
        "market_date": selected, "cutoff": cutoff, "origin": origin,
        "tickers": tickers, "candidates": {row["ticker"]: row for row in candidates},
        "chunks": chunks, "champion": {row["ticker"]: row for row in champion},
        "metadata_envelope": envelope, "memory_history": history,
        "source_identity": source_identity,
    }


def _treatment(member: dict, original: dict, snapshot: dict, now: datetime) -> dict:
    enriched = enrich(
        original, snapshot["metadata_envelope"], decision_at=now.isoformat(),
    )
    policy_id = member["policy_id"]
    if policy_id == "c-blind":
        aliases = {
            "available_at": snapshot["metadata_envelope"]["available_at"],
            "names": {row["ticker"]: row["aliases"]
                      for row in snapshot["metadata_envelope"]["entries"]},
        }
        return blind(enriched, aliases, decision_at=now.isoformat())
    if policy_id == "c-memory":
        memory = memory_examples(
            enriched["candidates"], snapshot["memory_history"],
            champion_policy_sha256=snapshot["origin"]["p15_registration_sha256"],
            decision_at=now.isoformat(),
        )
        payload = copy.deepcopy(enriched)
        payload["memory_examples"] = memory
        return _hash_treatment(
            enriched, payload, "champion_memory", memory_sha256=memory["memory_sha256"],
        )
    if policy_id == "c-price-only":
        return ablate(enriched, "price_only")
    if policy_id == "c-text-only":
        return ablate(enriched, "text_only")
    if policy_id in {
        "c-model-gpt-5.5-max", "c-model-gpt-5.6-terra-max", "c-prompt-v2",
    }:
        return _hash_treatment(enriched, copy.deepcopy(enriched), "same_input")
    raise ChallengerRunError("unknown model-backed P16 challenger")


def _text(value: object, field: str, words: int | None = None) -> str:
    if (not isinstance(value, str) or value != value.strip() or not value
            or len(value) > 1_000 or (words is not None and len(value.split()) > words)):
        raise ChallengerRunError(f"P16 {field} is invalid")
    return value


def _validate_output(output: object, candidates: list[dict], treatment: dict) -> dict[str, dict]:
    if (not isinstance(output, dict) or set(output) != {"schema_version", "assessments"}
            or output.get("schema_version") != 1
            or not isinstance(output["assessments"], list)):
        raise ChallengerRunError("P16 model output shape is invalid")
    expected = {row["ticker"]: row for row in candidates}
    inverse = {value: key for key, value in treatment.get("asset_ids", {}).items()}
    fields = {
        "ticker", "p_outperform_5", "expected_excess_bp_5",
        "expected_excess_bp_10", "action", "thesis", "invalidation", "evidence_ids",
    }
    result = {}
    for item in output["assessments"]:
        if not isinstance(item, dict) or set(item) != fields or item.get("ticker") not in expected:
            raise ChallengerRunError("P16 model assessment shape differs")
        ticker = item["ticker"]
        if ticker in result:
            raise ChallengerRunError("P16 model assessment is duplicated")
        values = [item[field] for field in (
            "p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")]
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in values)
                or not 0 <= values[0] <= 1
                or any(abs(value) > MAX_EXPECTED_EXCESS_BP for value in values[1:])):
            raise ChallengerRunError("P16 model score is invalid")
        candidate = expected[ticker]
        if (item["action"] not in {"ignore", "watch", "buy_candidate", "exit"}
                or (item["action"] == "exit" and not candidate.get("held", False))):
            raise ChallengerRunError("P16 model action is invalid")
        evidence = item["evidence_ids"]
        if (not isinstance(evidence, list) or not evidence
                or len(evidence) != len(set(evidence))
                or any(not isinstance(value, str) or not value for value in evidence)
                or not set(evidence) <= set(candidate.get("allowed_evidence_ids", []))):
            raise ChallengerRunError("P16 model evidence is invalid")
        canonical_ticker = inverse.get(ticker, ticker)
        result[canonical_ticker] = {
            **item, "ticker": canonical_ticker,
            "p_outperform_5": float(values[0]),
            "expected_excess_bp_5": float(values[1]),
            "expected_excess_bp_10": float(values[2]),
            "thesis": _text(item["thesis"], "thesis", words=60),
            "invalidation": _text(item["invalidation"], "invalidation"),
        }
    canonical_expected = {inverse.get(ticker, ticker) for ticker in expected}
    if set(result) != canonical_expected:
        raise ChallengerRunError("P16 model output does not cover its chunk")
    return result


def _aggregate(tickers: list[str], samples: list[dict[str, dict]]) -> list[dict]:
    rows = []
    for ticker in tickers:
        values = [sample[ticker] for sample in samples]
        numeric = {field: float(median(row[field] for row in values)) for field in (
            "p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")}
        counts = Counter(row["action"] for row in values)
        winners = {action for action, count in counts.items() if count == max(counts.values())}
        representative = min(
            (index for index, row in enumerate(values) if row["action"] in winners),
            key=lambda index: (
                abs(values[index]["expected_excess_bp_5"]
                    - numeric["expected_excess_bp_5"]), index),
        )
        rows.append({
            "ticker": ticker, **numeric, "action": values[representative]["action"],
            "thesis": values[representative]["thesis"],
            "invalidation": values[representative]["invalidation"],
            "evidence_ids": sorted({item for row in values for item in row["evidence_ids"]}),
            "scoring_status": "available",
        })
    return rows


def _unavailable(snapshot: dict, tickers: list[str], reason: str) -> list[dict]:
    rows = []
    for ticker in tickers:
        candidate = snapshot["candidates"][ticker]
        evidence = candidate.get("evidence_id")
        if not isinstance(evidence, str) or not evidence:
            allowed = candidate.get("allowed_evidence_ids", [])
            evidence = allowed[0] if allowed else snapshot["source_identity"]["p15_bundle_sha256"]
        rows.append({
            "ticker": ticker, "p_outperform_5": None, "expected_excess_bp_5": None,
            "expected_excess_bp_10": None, "action": "unavailable", "thesis": None,
            "invalidation": None, "evidence_ids": [evidence],
            "scoring_status": "unavailable", "unavailable_reason": reason[:512],
        })
    return rows


def _receipt_for_error(request: dict, exc: Exception) -> dict:
    response = getattr(exc, "response", None)
    return {
        "request": getattr(exc, "request", request),
        "request_sha256": getattr(exc, "request_sha256", canonical_sha256(request)),
        "response": response,
        "response_sha256": (
            getattr(exc, "response_sha256", canonical_sha256(response))
            if response is not None else None),
        "execution_authority": "none",
    }


def _start_member_run(
    database: Path, registration: dict, member: dict, snapshot: dict, now: datetime,
) -> dict:
    con = db.connect(database)
    try:
        with db.transaction(con):
            _ensure_trials(con, registration)
            manifest = [] if member["policy_id"] == "c-ensemble" else [{
                "chunk_index": sample["chunk_index"],
                "sample_index": sample["sample_index"],
                "source_request_sha256": sample["p15_request_sha256"],
                "source_input_sha256": canonical_sha256(enrich(
                    sample["original"], snapshot["metadata_envelope"],
                    decision_at=snapshot["cutoff"].isoformat(),
                )),
                "source_tickers": sorted(chunk["tickers"]),
            } for chunk in snapshot["chunks"] for sample in chunk["samples"]]
            run = p16_challenger_store.start_run(
                con, registration_sha256=registration["registration_sha256"],
                family_id=registration["evaluation"]["family_id"],
                policy_id=member["policy_id"], trial_id=member["trial_id"],
                window_id=f"{member['policy_id']}:{snapshot['market_date'].isoformat()}",
                market_date=snapshot["market_date"], run_mode="prospective",
                information_cutoff_at=snapshot["cutoff"], started_at=now,
                tickers=snapshot["tickers"], source_identity=snapshot["source_identity"],
                treatment_id=member["treatment_id"],
                model_contract_sha256=member["model_contract_sha256"],
                attempt_manifest=manifest,
                dependency_policy_ids=(
                    list(p16_challenger_store.ENSEMBLE_COMPONENT_POLICIES)
                    if member["policy_id"] == "c-ensemble" else []),
            )
            return {**run, "output": p16_challenger_store.output_for_run(
                con, run["record_id"])}
    finally:
        con.close()


def _reuse_challenger_receipt(
    retained: dict, treated: dict, treatment: dict, validated: list, chunk_failures: list
) -> None:
    if retained["data"]["status"] == "available":
        try:
            validated.append(
                _validate_output(
                    retained["data"]["receipt"].get("output"),
                    treated["candidates"],
                    treatment,
                )
            )
        except ChallengerRunError as exc:
            chunk_failures.append(str(exc))
    else:
        chunk_failures.append(retained["data"].get("reason") or "unavailable")


def _prepare_challenger_attempt(
    con, run, chunk, sample, member, snapshot, call_at, contract, instructions
) -> tuple:
    attempt_id = canonical_sha256(
        {
            "run_id": run["record_id"],
            "chunk_index": chunk["chunk_index"],
            "sample_index": sample["sample_index"],
        }
    )
    attempt = p16_challenger_store.get(con, "p16_challenger_attempts", attempt_id)
    was_existing = attempt is not None
    if attempt is None:
        treatment = _treatment(member, sample["original"], snapshot, call_at)
        treated = treatment["payload"]
        request = p16_model_client.request_payload(treated, contract, instructions=instructions)
        attempt = p16_challenger_store.start_attempt(
            con,
            run["record_id"],
            chunk_index=chunk["chunk_index"],
            sample_index=sample["sample_index"],
            request_payload=request,
            treatment=treatment,
            started_at=call_at,
        )
    else:
        treatment = attempt["data"]["treatment"]
        request = attempt["data"]["request"]
        treated = treatment.get("payload")
        if not isinstance(treated, dict):
            raise ChallengerRunError("retained P16 challenger treatment is invalid")
    receipt_id = canonical_sha256({"attempt_id": attempt["record_id"]})
    retained = p16_challenger_store.get(con, "p16_challenger_receipts", receipt_id)
    return attempt, was_existing, treatment, treated, request, retained


def _invoke_challenger(
    generate, treated, treatment, contract, member, instructions, request
) -> tuple:
    model_receipt = None
    try:
        model_receipt = generate(
            treated,
            contract,
            registered_model_contract_sha256=member["model_contract_sha256"],
            instructions=instructions,
        )
        receipt = model_receipt
        if receipt.get("request") != request:
            raise ChallengerRunError("P16 model request identity differs")
        parsed = _validate_output(
            receipt.get("output"),
            treated["candidates"],
            treatment,
        )
        status, reason = "available", None
    except (
        agent_model_client.ConnectorError,
        ChallengerRunError,
        duckdb.Error,
        TypeError,
        ValueError,
    ) as exc:
        reason = str(exc) or exc.__class__.__name__
        receipt = model_receipt or _receipt_for_error(request, exc)
        status, parsed = "unavailable", None
    return receipt, parsed, status, reason


def _run_member(
    database: Path, registration: dict, member: dict, contract: dict,
    snapshot: dict, now: datetime, *, generate: Callable, clock: Callable[[], datetime],
    instructions: str,
) -> tuple[dict, int]:
    run = _start_member_run(database, registration, member, snapshot, now)
    if run.get("output") is not None:
        return run["output"], 0
    calls, aggregates, failures = 0, [], []
    for chunk in snapshot["chunks"]:
        validated, chunk_failures = [], []
        for sample in chunk["samples"]:
            call_at = _aware(clock(), "challenger call time")
            con = db.connect(database)
            try:
                with db.transaction(con):
                    attempt, was_existing, treatment, treated, request, retained = (
                        _prepare_challenger_attempt(
                            con, run, chunk, sample, member, snapshot, call_at, contract, instructions,
                        )
                    )
            finally:
                con.close()
            if retained is not None:
                _reuse_challenger_receipt(retained, treated, treatment, validated, chunk_failures)
                continue
            if was_existing:
                reason = "interrupted before durable challenger response"
                receipt = _receipt_for_error(request, ChallengerRunError(reason))
                status, parsed = "unavailable", None
            elif _aware(clock(), "challenger invocation time") \
                    >= _next_open(snapshot["market_date"]):
                reason = "challenger pre-entry deadline passed"
                receipt = _receipt_for_error(request, ChallengerRunError(reason))
                status, parsed = "unavailable", None
            else:
                calls += 1
                receipt, parsed, status, reason = _invoke_challenger(
                    generate, treated, treatment, contract, member, instructions, request,
                )
            completed = _aware(clock(), "challenger completion time")
            con = db.connect(database)
            try:
                with db.transaction(con):
                    p16_challenger_store.finish_attempt(
                        con, attempt["record_id"], status=status, receipt=receipt,
                        completed_at=completed, reason=reason,
                    )
            finally:
                con.close()
            if parsed is None:
                chunk_failures.append(reason)
            else:
                validated.append(parsed)
        ordered = [ticker for ticker in snapshot["tickers"] if ticker in chunk["tickers"]]
        if len(validated) == SAMPLE_COUNT and not chunk_failures:
            aggregates.extend(_aggregate(ordered, validated))
        else:
            reason = "; ".join(dict.fromkeys(chunk_failures)) or "incomplete sample set"
            aggregates.extend(_unavailable(snapshot, ordered, reason))
            failures.append(reason)
    completed = _aware(clock(), "challenger run completion time")
    con = db.connect(database)
    try:
        with db.transaction(con):
            output = p16_challenger_store.finish_run(
                con, run["record_id"], rows=aggregates, completed_at=completed,
                reason="; ".join(dict.fromkeys(failures)) or None,
            )
    finally:
        con.close()
    return output, calls


def _ensemble_rows(snapshot: dict, components: list[dict]) -> list[dict]:
    sources = [snapshot["champion"], *[
        {row["ticker"]: row for row in output["data"]["rows"]}
        for output in components
    ]]
    rows = []
    for ticker in snapshot["tickers"]:
        values = [source[ticker] for source in sources]
        champion = values[0]
        if any(row.get("scoring_status") != "available" for row in values):
            evidence = champion.get("evidence_ids") or [
                snapshot["candidates"][ticker].get("evidence_id")
                or snapshot["source_identity"]["p15_bundle_sha256"]]
            rows.append({
                "ticker": ticker, "p_outperform_5": None,
                "expected_excess_bp_5": None, "expected_excess_bp_10": None,
                "action": "unavailable", "thesis": None, "invalidation": None,
                "evidence_ids": evidence, "scoring_status": "unavailable",
                "unavailable_reason": "ensemble component unavailable",
            })
            continue
        numeric = {field: sum(float(row[field]) for row in values) / len(values)
                   for field in ("p_outperform_5", "expected_excess_bp_5",
                                 "expected_excess_bp_10")}
        counts = Counter(row["action"] for row in values)
        winners = {action for action, count in counts.items() if count == max(counts.values())}
        representative = min(
            (index for index, row in enumerate(values) if row["action"] in winners),
            key=lambda index: (
                abs(float(values[index]["expected_excess_bp_5"])
                    - numeric["expected_excess_bp_5"]), index),
        )
        rows.append({
            "ticker": ticker, **numeric, "action": values[representative]["action"],
            "thesis": champion["thesis"], "invalidation": champion["invalidation"],
            "evidence_ids": champion["evidence_ids"], "scoring_status": "available",
        })
    return rows


def _run_ensemble(
    database: Path, registration: dict, member: dict, snapshot: dict,
    components: list[dict], now: datetime, clock: Callable[[], datetime],
) -> dict:
    run = _start_member_run(database, registration, member, snapshot, now)
    if run.get("output") is not None:
        dependency_ids = run["output"]["data"].get("dependency_output_ids", [])
        con = db.connect(database, read_only=True)
        try:
            dependency_outputs = [p16_challenger_store.get(
                con, "p16_challenger_outputs", item) for item in dependency_ids]
            dependency_runs = [None if item is None else p16_challenger_store.get(
                con, "p16_challenger_runs", item["key"].get("run_id", ""))
                               for item in dependency_outputs]
        finally:
            con.close()
        retained_policies = sorted(
            item["key"]["policy_id"] for item in dependency_runs if item is not None)
        if (len(dependency_runs) != 2 or any(item is None for item in dependency_runs)
                or retained_policies
                != sorted(p16_challenger_store.ENSEMBLE_COMPONENT_POLICIES)):
            raise ChallengerRunError("retained ensemble dependency set differs")
        return run["output"]
    expected = {"c-model-gpt-5.5-max", "c-model-gpt-5.6-terra-max"}
    policies = set()
    for output in components:
        con = db.connect(database, read_only=True)
        try:
            source = p16_challenger_store.get(
                con, "p16_challenger_runs", output["key"]["run_id"])
        finally:
            con.close()
        policies.add(source["key"]["policy_id"])
    if policies != expected:
        raise ChallengerRunError("ensemble component policy set differs")
    dependencies = sorted(output["record_id"] for output in components)
    con = db.connect(database)
    try:
        with db.transaction(con):
            return p16_challenger_store.finish_run(
                con, run["record_id"], rows=_ensemble_rows(snapshot, components),
                dependency_output_ids=dependencies,
                completed_at=_aware(clock(), "ensemble completion time"),
            )
    finally:
        con.close()


def _existing_preentry(con, registration: dict, market_date: date) -> bool:
    if not p16_trial_store.table_exists(con, "p16_sequential_origin_events"):
        return False
    rows = con.execute(
        "SELECT * FROM p16_sequential_origin_events "
        "WHERE registration_sha256=? AND family_id=? AND market_date=? "
        "AND event_kind='decision' ORDER BY comparison_id",
        [registration["registration_sha256"], registration["evaluation"]["family_id"],
         market_date],
    ).fetchall()
    if not rows:
        return False
    retained = [p16_store._sequential_row(row) for row in rows]
    epoch = date.fromisoformat(registration["evaluation"]["epoch_session"])
    session_index = p16_preentry.session_index(epoch, market_date)
    expected = sorted((
        row["comparison_id"], row["trial_id"], row["control_trial_id"],
        epoch.isoformat(), session_index,
    ) for row in registration["challengers"]["members"])
    actual = sorted((
        row["comparison_id"], row["trial_id"], row["control_trial_id"],
        row["epoch_session"], row["session_index"],
    ) for row in retained)
    if actual != expected:
        raise ChallengerRunError("P16 pre-entry family is partially retained")
    return True


def _run(
    *, database: Path, registration: dict, now: datetime | None = None,
    market_date: date | None = None, generate: Callable = p16_model_client.generate,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    isolated: bool = False,
) -> dict:
    started = _aware(now or clock(), "challenger start time")
    if not isolated and registration.get("status") != "active":
        raise ChallengerRunError("P16 registration is not active")
    contracts = _model_contracts(registration)
    snapshot = _source_snapshot(database, market_date, started)
    if not _close(snapshot["market_date"]) < started < _next_open(snapshot["market_date"]):
        raise ChallengerRunError("P16 challenger run is outside the pre-entry window")
    con = db.connect(database)
    try:
        with db.transaction(con):
            _ensure_trials(con, registration)
            if _existing_preentry(con, registration, snapshot["market_date"]):
                return {
                    "status": "completed", "market_date": snapshot["market_date"].isoformat(),
                    "family_id": registration["evaluation"]["family_id"],
                    "member_count": len(p16_registration.MEMBER_IDS),
                    "model_call_count": 0, "replayed": True,
                    "execution_authority": "none",
                }
    finally:
        con.close()
    members = {row["policy_id"]: row for row in registration["challengers"]["members"]}
    outputs, calls = {}, 0
    instructions = p16_model_client.prompt()
    for policy_id in MODEL_MEMBERS:
        member = members[policy_id]
        output, count = _run_member(
            database, registration, member, contracts[member["model_contract_sha256"]],
            snapshot, started, generate=generate, clock=clock, instructions=instructions,
        )
        outputs[policy_id], calls = output, calls + count
    outputs["c-ensemble"] = _run_ensemble(
        database, registration, members["c-ensemble"], snapshot,
        [outputs["c-model-gpt-5.5-max"], outputs["c-model-gpt-5.6-terra-max"]],
        started, clock,
    )
    recorded = _aware(clock(), "pre-entry record time")
    if recorded >= _next_open(snapshot["market_date"]):
        raise ChallengerRunError("P16 challenger family missed the next-open deadline")
    con = db.connect(database)
    try:
        with db.transaction(con):
            score_ids = []
            evaluation_tickers = [row["ticker"] for row in snapshot["origin"]["decision_rows"]]
            for policy_id in p16_registration.MEMBER_IDS:
                artifact_id, _payload = p16_challenger_store.publish_score_snapshot(
                    con, outputs[policy_id]["record_id"],
                    evaluation_tickers=evaluation_tickers, recorded_at=recorded,
                )
                score_ids.append(artifact_id)
            preentry = p16_preentry.record_preentry(
                con, registration_sha256=registration["registration_sha256"],
                family_id=registration["evaluation"]["family_id"],
                epoch_session=date.fromisoformat(registration["evaluation"]["epoch_session"]),
                members=p16_registration.family_members(registration),
                market_date=snapshot["market_date"],
                score_artifact_sha256s=sorted(score_ids), recorded_at=recorded,
            )
            if _aware(clock(), "pre-entry commit time") \
                    >= _next_open(snapshot["market_date"]):
                raise ChallengerRunError(
                    "P16 challenger family crossed the next-open deadline")
    finally:
        con.close()
    return {
        "status": "completed", "market_date": snapshot["market_date"].isoformat(),
        "family_id": registration["evaluation"]["family_id"],
        "member_count": len(outputs), "model_call_count": calls, "replayed": False,
        "unavailable_counts": {
            policy_id: output["data"]["unavailable_count"]
            for policy_id, output in outputs.items()},
        "preentry_sha256": preentry["preentry_sha256"],
        "execution_authority": "none",
    }


def run(
    *, database: Path = DEFAULT_DB, registration_path: Path = p16_registration.REGISTRATION_PATH,
    now: datetime | None = None, generate: Callable = p16_model_client.generate,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    registration = p16_registration.load(registration_path)
    with advisory_file_lock(LOCK_PATH), advisory_file_lock(NIGHTLY_LOCK):
        return _run(
            database=database, registration=registration, now=now,
            generate=generate, clock=clock,
        )


def dry_run(
    *, database: Path = DEFAULT_DB, registration_path: Path,
    now: datetime | None = None, market_date: date | None = None,
    generate: Callable = p16_model_client.generate,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    copier: Callable[[Path, Path], object] = _copy_database,
) -> dict:
    """Exercise the exact prospective workflow only inside a copied store."""
    registration = p16_registration.load(registration_path)
    with tempfile.TemporaryDirectory(prefix="trading-engine-p16-dry-run-") as directory:
        copied = Path(directory) / "market.duckdb"
        with advisory_file_lock(NIGHTLY_LOCK):
            copier(database, copied)
        result = _run(
            database=copied, registration=registration, now=now, market_date=market_date,
            generate=generate, clock=clock, isolated=True,
        )
        return {**result, "dry_run": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--registration", type=Path, default=p16_registration.REGISTRATION_PATH)
    args = parser.parse_args(argv)
    result = dry_run(registration_path=args.registration) if args.dry_run else run(
        registration_path=args.registration)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
