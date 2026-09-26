"""P15 nightly candidate scoring with retained independent samples."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from datetime import time as datetime_time
from pathlib import Path
from statistics import median
from typing import Callable

import duckdb

from engine.daily_opportunities import p15_universe
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.util import table_exists
from sim import nyse
from tools.backup_database import _copy_database

from . import (
    agent_evaluation,
    agent_model_client,
    daily_opportunity_news,
    p15_books,
)
from . import (
    p15_scoring_store as store,
)

POLICY_ID = "p15-scoring-v1"
CHUNK_SIZE = 10
SAMPLE_COUNT = 3
MAX_EXPECTED_EXCESS_BP = 10_000.0
AGGREGATION_RULE = "numeric_median_majority_action_representative_text_v1"
P15_BOOKS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
LOCK_PATH = REPO_ROOT / ".p15-scoring.lock"
NIGHTLY_LOCK = REPO_ROOT / ".nightly.lock"
DEADLINE_UTC = datetime_time(12, 0, tzinfo=timezone.utc)


class ScoringError(RuntimeError):
    """A P15 scoring run cannot safely produce evidence."""


def _held(con: duckdb.DuckDBPyConnection) -> set[str]:
    placeholders = ",".join("?" for _ in P15_BOOKS)
    try:
        return {row[0] for row in con.execute(
            f"SELECT DISTINCT ticker FROM sim_positions WHERE portfolio_id IN ({placeholders}) "
            "AND qty>0 ORDER BY ticker",
            list(P15_BOOKS),
        ).fetchall()}
    except duckdb.Error:
        return set()


def _sessions_until(market_date: date, event_date: date, limit: int = 5) -> int:
    count, current = 0, market_date
    while current < event_date and count <= limit:
        current = nyse.next_session(current)
        count += 1
    return count if current == event_date else limit + 1


def _gate_candidates(bundle: dict) -> dict:
    risk_on = bundle["market"]["regime"] == "risk_on"
    candidates = []
    for original in bundle["candidates"]:
        candidate = {key: value for key, value in original.items() if key != "evidence_id"}
        if candidate["reason"] != "eligible":
            pass
        else:
            earnings = candidate["earnings"]
            if not risk_on:
                candidate.update(tradeable=False, reason="risk_off")
            elif earnings["status"] == "unavailable":
                candidate.update(tradeable=False, reason="earnings_unavailable")
            elif (
                earnings["status"] == "available"
                and _sessions_until(
                    date.fromisoformat(bundle["market_date"]),
                    date.fromisoformat(earnings["next_date"]),
                ) <= 5
            ):
                candidate.update(tradeable=False, reason="earnings_within_5_sessions")
        candidates.append({**candidate, "evidence_id": canonical_sha256(candidate)})
    body = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    body["candidates"] = candidates
    return {**body, "bundle_sha256": canonical_sha256(body)}


def _context(
    bundle: dict, news: dict, cutoff: datetime
) -> tuple[dict, dict[str, set[str]]]:
    observations = [
        item for item in news["observations"]
        if datetime.fromisoformat(item["retrieved_at"]).astimezone(timezone.utc) <= cutoff
    ]
    market_news = [item for item in observations if item["ticker"] == "SPY"]
    allowed = {}
    candidates = []
    for candidate in bundle["candidates"]:
        headlines = [
            item for item in observations if item["ticker"] == candidate["ticker"]
        ]
        ids = {
            bundle["market"]["evidence_id"], candidate["evidence_id"],
            *(item["evidence_id"] for item in market_news),
            *(item["evidence_id"] for item in headlines),
        }
        allowed[candidate["ticker"]] = ids
        candidates.append({**candidate, "headlines": headlines,
                           "allowed_evidence_ids": sorted(ids)})
    return {
        "news_status": news["status"], "market_headlines": market_news,
        "event_facts": [], "tradingview_quotes": [], "candidates": candidates,
    }, allowed


def _seed(market_date: str, chunk_index: int, sample_index: int) -> int:
    digest = hashlib.sha256(
        f"{POLICY_ID}:{market_date}:{chunk_index}:{sample_index}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _request_input(
    bundle: dict,
    context: dict,
    candidates: list[dict],
    *,
    chunk_index: int,
    sample_index: int,
    seed: int,
    cutoff: datetime,
    used_orders: set[tuple[str, ...]],
) -> dict:
    order = [dict(item) for item in candidates]
    random.Random(seed).shuffle(order)
    for _rotation in range(max(0, len(order) - 1)):
        identity = tuple(item["ticker"] for item in order)
        if identity not in used_orders:
            break
        order = [*order[1:], order[0]]
    used_orders.add(tuple(item["ticker"] for item in order))
    return {
        "schema_version": 1, "policy_id": POLICY_ID,
        "market_date": bundle["market_date"], "information_cutoff_at": cutoff.isoformat(),
        "chunk_index": chunk_index, "sample_index": sample_index,
        "permutation_seed": seed, "market": bundle["market"],
        "market_headlines": context["market_headlines"],
        "event_facts": context["event_facts"],
        "tradingview_quotes": context["tradingview_quotes"], "candidates": order,
    }


def _text(value: object, *, words: int | None = None) -> str:
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > 1_000:
        raise ScoringError("P15 scoring text is invalid")
    if words is not None and len(value.split()) > words:
        raise ScoringError("P15 scoring thesis is too long")
    return value


def _validate_output(
    output: object, candidates: list[dict], allowed: dict[str, set[str]]
) -> dict[str, dict]:
    if (
        not isinstance(output, dict) or set(output) != {"schema_version", "assessments"}
        or output.get("schema_version") != 1 or not isinstance(output["assessments"], list)
    ):
        raise ScoringError("P15 scoring output shape is invalid")
    expected = {item["ticker"]: item for item in candidates}
    result = {}
    fields = {"ticker", "p_outperform_5", "expected_excess_bp_5",
              "expected_excess_bp_10", "action", "thesis", "invalidation", "evidence_ids"}
    for item in output["assessments"]:
        if not isinstance(item, dict) or set(item) != fields or item.get("ticker") not in expected:
            raise ScoringError("P15 scoring assessment shape is invalid")
        ticker = item["ticker"]
        if ticker in result:
            raise ScoringError("P15 scoring assessment is duplicated")
        values = [item[name] for name in (
            "p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ScoringError("P15 scoring numeric value is invalid")
        if not 0 <= values[0] <= 1 or any(
            abs(value) > MAX_EXPECTED_EXCESS_BP for value in values[1:]
        ):
            raise ScoringError("P15 scoring numeric value is outside bounds")
        action = item["action"]
        if action not in {"ignore", "watch", "buy_candidate", "exit"}:
            raise ScoringError("P15 scoring action is invalid")
        if action == "exit" and not expected[ticker]["held"]:
            raise ScoringError("P15 scoring exit refers to an unheld candidate")
        evidence_ids = item["evidence_ids"]
        if (
            not isinstance(evidence_ids, list) or not evidence_ids
            or len(set(evidence_ids)) != len(evidence_ids)
            or any(not isinstance(value, str) for value in evidence_ids)
            or not set(evidence_ids) <= allowed[ticker]
        ):
            raise ScoringError("P15 scoring evidence is invalid")
        result[ticker] = {
            **item, "p_outperform_5": float(values[0]),
            "expected_excess_bp_5": float(values[1]),
            "expected_excess_bp_10": float(values[2]),
            "thesis": _text(item["thesis"], words=60),
            "invalidation": _text(item["invalidation"]),
        }
    if set(result) != set(expected):
        raise ScoringError("P15 scoring output does not cover the chunk")
    return result


def _validate_identity(result: agent_model_client.ConnectorResult) -> None:
    identity = agent_model_client.identity(role="p15_scoring")
    if (
        result.model != identity["model"]
        or result.model_version != identity["model_version"]
        or result.proxy_version != identity["required_proxy_version"]
        or result.proxy_source_sha256 != identity["required_proxy_source_sha256"]
        or result.traecli_runtime != identity["required_traecli_runtime"]
        or result.upstream_model_family != agent_model_client.UPSTREAM_MODEL_FAMILY
        or result.model_catalog_entry_sha256 != identity["model_catalog_entry_sha256"]
    ):
        raise ScoringError("P15 scoring model identity differs")


def _aggregate(candidates: list[dict], samples: list[dict[str, dict]]) -> list[dict]:
    output = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        rows = [sample[ticker] for sample in samples]
        numeric = {
            field: float(median(row[field] for row in rows))
            for field in ("p_outperform_5", "expected_excess_bp_5", "expected_excess_bp_10")
        }
        counts = Counter(row["action"] for row in rows)
        max_votes = max(counts.values())
        winning_actions = {action for action, count in counts.items() if count == max_votes}
        representative_index = min(
            (index for index, row in enumerate(rows) if row["action"] in winning_actions),
            key=lambda index: (abs(rows[index]["expected_excess_bp_5"]
                                   - numeric["expected_excess_bp_5"]), index),
        )
        representative = rows[representative_index]
        output.append({
            **candidate, **numeric, "action": representative["action"],
            "thesis": representative["thesis"],
            "invalidation": representative["invalidation"],
            "evidence_ids": sorted({value for row in rows for value in row["evidence_ids"]}),
            "representative_sample_index": representative_index,
            "aggregation_rule": AGGREGATION_RULE,
            "sample_support": [{
                "sample_index": index, "action": row["action"],
                "p_outperform_5": row["p_outperform_5"],
                "expected_excess_bp_5": row["expected_excess_bp_5"],
                "expected_excess_bp_10": row["expected_excess_bp_10"],
                "evidence_ids": row["evidence_ids"],
            } for index, row in enumerate(rows)],
            "scoring_status": "available",
        })
    return output


def _unavailable(candidates: list[dict], reason: str) -> list[dict]:
    return [{**candidate, "p_outperform_5": None, "expected_excess_bp_5": None,
             "expected_excess_bp_10": None, "action": "unavailable", "thesis": None,
             "invalidation": None, "evidence_ids": [candidate["evidence_id"]],
             "representative_sample_index": None, "scoring_status": "unavailable",
             "aggregation_rule": AGGREGATION_RULE, "sample_support": [],
             "unavailable_reason": reason[:512]} for candidate in candidates]


def _trace(
    run_id: int, bundle: dict, context: dict, decisions: list[dict],
    samples: list[dict], started_at: datetime, completed_at: datetime,
) -> dict:
    identity = agent_model_client.identity(role="p15_scoring")
    sample_ids = [{key: item.get(key) for key in (
        "chunk_index", "sample_index", "request_sha256", "response_id",
        "upstream_request_id", "status")} for item in samples]
    digest = canonical_sha256(sample_ids)
    usage = {field: sum(int(item.get(field) or 0) for item in samples)
             for field in ("input_tokens", "output_tokens", "total_tokens")}
    return {
        "window_id": f"{POLICY_ID}:{bundle['market_date']}", "policy_id": POLICY_ID,
        "cadence": "nightly", "prompt_role": POLICY_ID,
        "market_date": date.fromisoformat(bundle["market_date"]),
        "observed_at": started_at, "completed_at": completed_at,
        "information_cutoff_at": datetime.fromisoformat(context["information_cutoff_at"]),
        "source_kind": "p15_scoring_run", "source_identifier": str(run_id),
        "source_refs": [{"kind": "p15_universe", "sha256": bundle["bundle_sha256"]},
                        *[{"kind": "news_receipt", "ticker": item["ticker"],
                           "sha256": item["receipt_sha256"]}
                          for item in context["news_receipts"]]],
        "input_payload": {"universe": bundle, "context": context},
        "output_payload": {"schema_version": 1, "assessments": decisions},
        "request_sha256": canonical_sha256([item["request_sha256"] for item in samples]),
        "response_id": f"aggregate-{digest[:32]}", "model": identity["model"],
        "model_version": identity["model_version"],
        "instructions_sha256": identity["instructions_sha256"],
        "toolset_sha256": identity["toolset_sha256"],
        "model_catalog_entry_sha256": identity["model_catalog_entry_sha256"],
        "proxy_source_sha256": identity["required_proxy_source_sha256"],
        "traecli_runtime": identity["required_traecli_runtime"],
        "upstream_model_family": agent_model_client.UPSTREAM_MODEL_FAMILY,
        "upstream_request_id": f"aggregate-{digest[:32]}",
        "latency_ms": max(0.0, (completed_at - started_at).total_seconds() * 1000),
        "usage": usage, "terminal_status": "completed",
        "execution_authority": "local_simulator_only",
        "decisions": [{
            **item,
            "decision": item["action"],
            "action": {"buy_candidate": "buy", "exit": "sell"}.get(item["action"], "none"),
            "horizon_sessions": 5,
            "confidence": item["p_outperform_5"] or 0.0,
        } for item in decisions],
    }


def _stored_samples(con: duckdb.DuckDBPyConnection, run_id: int) -> list[dict]:
    cursor = con.execute(
        "SELECT * FROM p15_scoring_samples WHERE run_id=? ORDER BY chunk_index,sample_index",
        [run_id],
    )
    return [dict(zip((item[0] for item in cursor.description), row, strict=True))
            for row in cursor.fetchall()]


def _run(
    *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate: Callable[[dict], agent_model_client.ConnectorResult]
    = agent_model_client.generate_p15_scoring_json,
    fetch_news=daily_opportunity_news._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    started = (now or clock()).astimezone(timezone.utc)
    deadline = datetime.combine(started.date(), DEADLINE_UTC)
    if started >= deadline:
        raise ScoringError("P15 scoring cannot start at or after 12:00 UTC")
    con = db.connect(database, read_only=True, wait_s=0)
    try:
        market_date = db.latest_operational_market_date(con)
        if market_date is None:
            raise ScoringError("P15 scoring market date is unavailable")
        existing = (
            store.find_run(con, market_date)
            if table_exists(con, "p15_scoring_runs") else None
        )
        if existing is None:
            bundle = p15_universe(
                con, market_date, held_tickers=_held(con),
                information_cutoff_at=started,
            )
    finally:
        con.close()
    if existing is not None:
        if existing["status"] == "completed":
            return {"status": "completed", "market_date": market_date.isoformat(),
                    "replayed": True, "model_call_count": 0}
        if existing["status"] == "failed":
            return {"status": "failed", "market_date": market_date.isoformat(),
                    "reason": existing["reason"], "replayed": True,
                    "model_call_count": 0}
        if existing["status"] != "running":
            raise ScoringError("P15 scoring run status is invalid")
        bundle = json.loads(existing["universe_payload"])
        context = json.loads(existing["context_payload"])
        cutoff = existing["information_cutoff_at"].replace(tzinfo=timezone.utc)
        allowed = {
            item["ticker"]: set(item["allowed_evidence_ids"])
            for item in context["candidates"]
        }
        run_id = int(existing["id"])
    else:
        bundle = _gate_candidates({**bundle, "snapshot_at": started.isoformat()})
        news = daily_opportunity_news.capture(
            ["SPY", *(item["ticker"] for item in bundle["candidates"])],
            now=started, fetch=fetch_news,
        )
        cutoff = now or clock()
        context, allowed = _context(bundle, news, cutoff.astimezone(timezone.utc))
        context.update(
            information_cutoff_at=cutoff.astimezone(timezone.utc).isoformat(),
            news_receipts=[{
                "ticker": item["ticker"], "receipt_sha256": item["receipt_sha256"],
                "requested_at": (
                    item["requested_at"] if isinstance(item["requested_at"], str)
                    else item["requested_at"].isoformat()
                ),
                "received_at": (
                    item["received_at"] if isinstance(item["received_at"], str)
                    else item["received_at"].isoformat()
                ),
            } for item in news["receipts"]],
        )
        con = db.connect(database, wait_s=0)
        try:
            with db.transaction(con):
                store.init_schema(con)
                agent_evaluation.init_schema(con)
                created = store.create_run(
                    con, market_date=market_date, universe=bundle, context=context,
                    information_cutoff_at=cutoff, started_at=started,
                    news_receipts=news["receipts"],
                )
            run_id = created["run_id"]
        finally:
            con.close()
    chunks = [context["candidates"][index:index + CHUNK_SIZE]
              for index in range(0, len(context["candidates"]), CHUNK_SIZE)]
    aggregates, calls, deadline_exceeded = [], 0, False
    for chunk_index, chunk in enumerate(chunks):
        validated, failure = [], None
        used_orders: set[tuple[str, ...]] = set()
        for sample_index in range(SAMPLE_COUNT):
            if clock().astimezone(timezone.utc) >= deadline:
                deadline_exceeded = True
                failure = "P15 scoring exceeded the 12:00 UTC deadline"
                break
            seed = _seed(bundle["market_date"], chunk_index, sample_index)
            payload = _request_input(
                bundle, context, chunk, chunk_index=chunk_index,
                sample_index=sample_index, seed=seed, cutoff=cutoff,
                used_orders=used_orders,
            )
            request = agent_model_client.p15_scoring_request_payload(payload)
            order = [item["ticker"] for item in payload["candidates"]]
            con = db.connect(database, wait_s=0)
            result = None
            try:
                with db.transaction(con):
                    started_sample = store.start_sample(
                        con, run_id=run_id, chunk_index=chunk_index,
                        sample_index=sample_index, permutation_seed=seed,
                        ticker_order=order, request_payload=request, started_at=clock(),
                    )
                if started_sample["replayed"]:
                    row = con.execute(
                        "SELECT response_payload FROM p15_scoring_samples WHERE id=?",
                        [started_sample["sample_id"]],
                    ).fetchone()
                    if started_sample["status"] == "completed" and row and row[0]:
                        retained = json.loads(row[0])
                        validated.append(_validate_output(retained["output"], chunk, allowed))
                    elif started_sample["status"] == "started":
                        with db.transaction(con):
                            store.fail_sample(
                                con, started_sample["sample_id"],
                                reason="interrupted before durable response",
                                completed_at=clock(),
                            )
                        failure = "interrupted before durable response"
                    else:
                        failure = f"sample replay is terminal: {started_sample['status']}"
                    continue
            finally:
                con.close()
            try:
                result = generate(payload)
                calls += 1
                sample_completed = clock().astimezone(timezone.utc)
                if sample_completed >= deadline:
                    raise ScoringError("P15 scoring exceeded the 12:00 UTC deadline")
                if result.request_sha256 != canonical_sha256(request):
                    raise ScoringError("P15 scoring request identity differs")
                _validate_identity(result)
                parsed = _validate_output(result.output, chunk, allowed)
                con = db.connect(database, wait_s=0)
                try:
                    with db.transaction(con):
                        store.complete_sample(
                            con, started_sample["sample_id"], response=asdict(result),
                            completed_at=sample_completed,
                        )
                finally:
                    con.close()
                validated.append(parsed)
            except (agent_model_client.ConnectorError, ScoringError, TypeError, ValueError) as exc:
                failure = str(exc)
                deadline_exceeded = "12:00 UTC deadline" in failure
                retained = None if result is None else asdict(result)
                metadata = {
                    key: getattr(exc, key, None)
                    for key in ("response_id", "request_sha256", "response_sha256", "usage")
                }
                con = db.connect(database, wait_s=0)
                try:
                    with db.transaction(con):
                        store.fail_sample(
                            con, started_sample["sample_id"], reason=failure,
                            completed_at=clock(), response=retained, metadata=metadata,
                        )
                finally:
                    con.close()
                if deadline_exceeded:
                    break
        aggregates.extend(
            _aggregate(chunk, validated)
            if failure is None and len(validated) == SAMPLE_COUNT
            else _unavailable(chunk, failure or "incomplete sample set")
        )
        if deadline_exceeded:
            break
    if deadline_exceeded:
        con = db.connect(database, wait_s=0)
        try:
            with db.transaction(con):
                store.fail_run(
                    con, run_id, reason="P15 scoring exceeded the 12:00 UTC deadline",
                    completed_at=clock(),
                )
        finally:
            con.close()
        return {"status": "failed", "market_date": bundle["market_date"],
                "reason": "deadline_exceeded", "model_call_count": calls,
                "replayed": False}
    completed = clock().astimezone(timezone.utc)
    if completed >= deadline:
        con = db.connect(database, wait_s=0)
        try:
            with db.transaction(con):
                store.fail_run(
                    con, run_id, reason="P15 scoring exceeded the 12:00 UTC deadline",
                    completed_at=completed,
                )
        finally:
            con.close()
        return {"status": "failed", "market_date": bundle["market_date"],
                "reason": "deadline_exceeded", "model_call_count": calls,
                "replayed": False}
    con = db.connect(database, wait_s=0)
    try:
        with db.transaction(con):
            samples = _stored_samples(con, run_id)
            trace = _trace(run_id, bundle, context, aggregates, samples, started, completed)
            result = agent_evaluation.record_trace(con, trace)
            store.complete_run(
                con, run_id, trace_sha256=result["trace_sha256"], completed_at=completed
            )
    finally:
        con.close()
    return {"status": "completed", "market_date": bundle["market_date"],
            "candidate_count": len(aggregates), "model_call_count": calls,
            "unavailable_count": sum(item["scoring_status"] == "unavailable"
                                     for item in aggregates), "replayed": False}


def run(
    *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate: Callable[[dict], agent_model_client.ConnectorResult]
    = agent_model_client.generate_p15_scoring_json,
    fetch_news=daily_opportunity_news._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    with advisory_file_lock(LOCK_PATH), advisory_file_lock(NIGHTLY_LOCK):
        result = _run(
            database=database, now=now, generate=generate,
            fetch_news=fetch_news, clock=clock,
        )
        if "market_date" in result:
            con = db.connect(database, wait_s=0)
            try:
                result = {**result, "books": p15_books.run_window(
                    con, date.fromisoformat(result["market_date"]), observed_at=clock()
                )}
            finally:
                con.close()
        return result


def dry_run(
    *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate: Callable[[dict], agent_model_client.ConnectorResult]
    = agent_model_client.generate_p15_scoring_json,
    fetch_news=daily_opportunity_news._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    copier: Callable[[Path, Path], object] = _copy_database,
) -> dict:
    """Run the exact mutating flow against an isolated DuckDB snapshot."""
    requested = (now or clock()).astimezone(timezone.utc)
    if requested >= datetime.combine(requested.date(), DEADLINE_UTC):
        raise ScoringError("P15 scoring cannot start at or after 12:00 UTC")
    with tempfile.TemporaryDirectory(prefix="trading-engine-p15-dry-run-") as directory:
        copied = Path(directory) / "market.duckdb"
        with advisory_file_lock(NIGHTLY_LOCK):
            copier(database, copied)
        con = db.connect(copied, wait_s=0)
        try:
            p15_books.init_schema(con)
            state = p15_books.activation_state(con)
            if state != "active":
                checkpoint = con.execute(
                    "SELECT MAX(e.date) FROM sim_equity e JOIN portfolios p "
                    "ON p.id=e.portfolio_id WHERE p.active AND p.id NOT IN (?,?,?)",
                    list(p15_books.BOOK_IDS),
                ).fetchone()[0]
                if checkpoint is None:
                    raise ScoringError("P15 dry-run activation checkpoint is unavailable")
                if state == "absent":
                    p15_books.initialize_books(con, checkpoint)
                p15_books.activate_books(con, checkpoint)
        finally:
            con.close()
        result = run(
            database=copied, now=now, generate=generate,
            fetch_news=fetch_news, clock=clock,
        )
        return {**result, "dry_run": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = (
        dry_run(database=args.database)
        if args.dry_run else run(database=args.database)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
