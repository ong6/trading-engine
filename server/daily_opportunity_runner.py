"""Idempotent daily P8 standout assessment through the constrained Trae model."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import duckdb

from engine.daily_opportunities import OpportunityError, detect
from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import agent_evaluation, agent_model_client, daily_opportunity_news, daily_opportunity_store
from .json_utils import loads_object

LOCK_PATH = REPO_ROOT / ".daily-opportunity.lock"
MAX_TEXT = 1000
DECISIONS = {"ignore", "watch", "hold", "swing"}
ACTIONS = {"none", "buy", "sell"}
Generate = Callable[[dict], agent_model_client.ConnectorResult]


class DailyOpportunityError(RuntimeError):
    """A daily opportunity run could not complete safely."""


@contextmanager
def _connection(path: Path, *, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    con = engine_db.connect(path, read_only=read_only, wait_s=0)
    try:
        yield con
    finally:
        con.close()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > MAX_TEXT:
        raise DailyOpportunityError(f"assessment {field} is invalid")
    return value


def _held(con: duckdb.DuckDBPyConnection) -> list[str]:
    try:
        return [row[0] for row in con.execute(
            "SELECT ticker FROM sim_positions WHERE portfolio_id = ? AND qty > 0 ORDER BY ticker",
            [daily_opportunity_store.PORTFOLIO_ID],
        ).fetchall()]
    except duckdb.Error:
        return []


def _validate_output(output: object, bundle: dict, allowed: dict[str, set[str]], held: set[str]) -> list[dict]:
    if (
        not isinstance(output, dict)
        or set(output) != {"schema_version", "assessments"}
        or output["schema_version"] != 1
        or not isinstance(output["assessments"], list)
    ):
        raise DailyOpportunityError("daily model output shape is invalid")
    expected = [item["ticker"] for item in bundle["candidates"]]
    if len(output["assessments"]) != len(expected):
        raise DailyOpportunityError("daily model output does not assess every candidate")
    normalized = []
    for raw in output["assessments"]:
        fields = {"ticker", "decision", "action", "horizon_sessions", "confidence",
                  "thesis", "invalidation", "evidence_ids", "alert"}
        if not isinstance(raw, dict) or set(raw) != fields or raw.get("ticker") not in expected:
            raise DailyOpportunityError("daily assessment shape is invalid")
        ticker, decision, action = raw["ticker"], raw["decision"], raw["action"]
        horizon, confidence = raw["horizon_sessions"], raw["confidence"]
        evidence_ids = raw["evidence_ids"]
        if (decision not in DECISIONS or action not in ACTIONS
                or isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 20
                or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence)) or not 0 <= confidence <= 1
                or not isinstance(evidence_ids, list) or not evidence_ids
                or any(not isinstance(value, str) for value in evidence_ids)
                or not set(evidence_ids) <= allowed[ticker]):
            raise DailyOpportunityError("daily assessment values are invalid")
        if decision in {"ignore", "watch", "hold"} and action != "none":
            raise DailyOpportunityError("non-swing assessment cannot act")
        if decision == "swing" and action not in {"buy", "sell"}:
            raise DailyOpportunityError("swing assessment needs an action")
        if (decision == "hold" or action == "sell") and ticker not in held:
            raise DailyOpportunityError("assessment refers to an unheld position")
        if ticker in held and not (
            decision == "hold" or (decision == "swing" and action == "sell")
        ):
            raise DailyOpportunityError("held position requires hold or swing-sell assessment")
        alert = raw["alert"]
        candidate = next(item for item in bundle["candidates"] if item["ticker"] == ticker)
        if decision == "watch":
            if not isinstance(alert, dict) or set(alert) != {"direction", "price", "expires_sessions"}:
                raise DailyOpportunityError("watch assessment alert is invalid")
            price, expires = alert["price"], alert["expires_sessions"]
            bounds = candidate["alert_bounds"]
            if (alert["direction"] not in {"above", "below"}
                    or isinstance(price, bool) or not isinstance(price, (int, float))
                    or not math.isfinite(float(price)) or not bounds["minimum"] <= price <= bounds["maximum"]
                    or isinstance(expires, bool) or not isinstance(expires, int) or not 1 <= expires <= 10):
                raise DailyOpportunityError("watch assessment alert is outside bounds")
        elif alert is not None:
            raise DailyOpportunityError("only watch assessments may create alerts")
        normalized.append({**raw, "confidence": float(confidence), "market_date": bundle["market_date"]})
    if sorted(item["ticker"] for item in normalized) != sorted(expected):
        raise DailyOpportunityError("daily model output contains duplicate candidates")
    return normalized


def _model_input(bundle: dict, news: dict, held: list[str]) -> tuple[dict, dict[str, set[str]]]:
    by_ticker = {item["ticker"]: [] for item in bundle["candidates"]}
    for item in news["observations"]:
        if item["ticker"] in by_ticker:
            by_ticker[item["ticker"]].append(item)
    market_headlines = [
        item for item in news["observations"] if item["ticker"] == "SPY"
    ]
    market_news_ids = {item["evidence_id"] for item in market_headlines}
    allowed = {}
    market_id = bundle["market"]["evidence_id"]
    for candidate in bundle["candidates"]:
        allowed[candidate["ticker"]] = {
            market_id, candidate["evidence_id"], *market_news_ids,
            *(item["evidence_id"] for item in by_ticker[candidate["ticker"]]),
        }
    model_input = {
        "schema_version": 1, "task": "assess each deterministic daily opportunity",
        "execution_authority": "none", "market_date": bundle["market_date"],
        "news_status": news["status"], "market": bundle["market"],
        "market_headlines": market_headlines,
        "held_positions": held,
        "candidates": [{**item, "headlines": by_ticker[item["ticker"]]} for item in bundle["candidates"]],
        "allowed_evidence_ids": sorted(set().union(*allowed.values()) if allowed else set()),
        "output_contract": {
            "decisions": sorted(DECISIONS), "actions": sorted(ACTIONS),
            "horizon_sessions": [1, 20], "alert_expiry_sessions": [1, 10],
        },
    }
    return model_input, allowed


def _result(con: duckdb.DuckDBPyConnection, run: dict, *, replayed: bool) -> dict:
    count = con.execute(
        "SELECT COUNT(*) FROM daily_opportunity_assessments WHERE run_id = ?", [run["id"]]
    ).fetchone()[0]
    orders = con.execute(
        "SELECT COUNT(*) FROM daily_opportunity_order_attribution WHERE run_id = ?",
        [run["id"]],
    ).fetchone()[0]
    return {"status": run["status"], "market_date": loads_object(run["bundle_payload"])["market_date"],
            "assessment_count": count, "news_status": run["news_status"],
            "paper_order_count": orders, "execution_authority": "local_simulator_only",
            "replayed": replayed}


def _index_evaluation(database: Path, run_id: int, now: datetime) -> None:
    """Best-effort derived index; the authoritative decision remains committed on failure."""
    try:
        with _connection(database) as con, engine_db.transaction(con):
            agent_evaluation.init_schema(con)
            agent_evaluation.record_trace(con, agent_evaluation.daily_trace(con, run_id))
            agent_evaluation.label_mature(con, labeled_at=now)
    except (agent_evaluation.EvaluationError, duckdb.Error):
        pass


def _submit_nightly_tools(
    database: Path, run_id: int, observed_at: datetime, tool_generate=None
) -> list[int]:
    """Confirm each eligible swing through the sole P9 execution-bearing tool role."""
    with _connection(database) as con:
        book = con.execute(
            "SELECT active FROM portfolios WHERE id = ?",
            [daily_opportunity_store.PORTFOLIO_ID],
        ).fetchone()
        if book is None or book[0] is not True:
            return []
        ids = [row[0] for row in con.execute(
            "SELECT id FROM daily_opportunity_assessments WHERE run_id = ? "
            "AND decision = 'swing' ORDER BY id", [run_id],
        ).fetchall()]
    from . import daily_opportunity_tools

    orders = []
    market_date = None
    with _connection(database) as con:
        market_date = con.execute(
            "SELECT market_date FROM daily_opportunity_runs WHERE id = ?", [run_id]
        ).fetchone()[0]
    if observed_at.date() != market_date + timedelta(days=1) or observed_at.hour >= 12:
        return []
    for assessment_id in ids:
        result = daily_opportunity_tools.submit(
            assessment_id, database=database, now=observed_at, generate=tool_generate
        )
        if result["paper_order_id"] is not None:
            orders.append(result["paper_order_id"])
    return orders


def run(*, database: Path = DEFAULT_DB, now: datetime | None = None, generate: Generate | None = None,
        fetch_news: daily_opportunity_news.Fetch = daily_opportunity_news._fetch,
        tool_generate=None) -> dict:
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generate = generate or agent_model_client.generate_opportunity_json
    with advisory_file_lock(LOCK_PATH):
        with _connection(database) as con:
            daily_opportunity_store.init_schema(con)
            market_date = engine_db.latest_operational_market_date(con)
            if market_date is None:
                raise DailyOpportunityError("no breadth-qualified market date")
            existing = daily_opportunity_store.find_run(con, market_date)
            if existing is not None:
                result = _result(con, existing, replayed=True)
                run_id = existing["id"]
                completed = existing["status"] == "completed"
            else:
                result = None
                completed = False
            if result is not None:
                break_out = True
            else:
                break_out = False
            with engine_db.transaction(con):
                triggered = [] if break_out else daily_opportunity_store.evaluate_alerts(con, market_date)
        if break_out:
            if completed:
                _index_evaluation(database, run_id, observed_at)
                result["paper_order_ids"] = _submit_nightly_tools(
                    database, run_id, observed_at, tool_generate
                )
                result["paper_order_count"] = len(result["paper_order_ids"])
            return result
        with _connection(database, read_only=True) as con:
            held = _held(con)
            bundle = detect(
                con, market_date,
                required_tickers={item["ticker"] for item in triggered} | set(held),
            )
        trigger_by_ticker = {item["ticker"]: item for item in triggered}
        for candidate in bundle["candidates"]:
            candidate["triggered_alert"] = trigger_by_ticker.get(candidate["ticker"])
        news = daily_opportunity_news.capture(
            ["SPY", *(item["ticker"] for item in bundle["candidates"])],
            now=observed_at, fetch=fetch_news,
        )
        for item in bundle["candidates"]:
            item["headline_evidence_ids"] = [
                row["evidence_id"] for row in news["observations"] if row["ticker"] == item["ticker"]
            ]
        bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
        with _connection(database) as con:
            daily_opportunity_store.init_schema(con)
            existing = daily_opportunity_store.find_run(con, market_date)
            if existing is not None:
                return _result(con, existing, replayed=True)
            with engine_db.transaction(con):
                run_id = daily_opportunity_store.insert_run(
                    con, bundle, news_status=news["status"], started_at=observed_at,
                    news_receipts=news["receipts"],
                )
    model_input, allowed = _model_input(bundle, news, held)
    request_sha256 = canonical_sha256(agent_model_client.opportunity_request_payload(model_input))
    information_cutoff_at = datetime.now(timezone.utc)
    generation_started = time.monotonic()
    try:
        response = generate(model_input)
        latency_ms = (time.monotonic() - generation_started) * 1000
        completed_at = datetime.now(timezone.utc)
        identity = agent_model_client.identity(role="opportunity")
        if (
            response.request_sha256 != request_sha256
            or response.model != identity["model"]
            or response.model_version != identity["model_version"]
            or response.proxy_version != identity["required_proxy_version"]
            or response.proxy_source_sha256 != identity["required_proxy_source_sha256"]
            or response.traecli_runtime != identity["required_traecli_runtime"]
            or response.upstream_model_family != agent_model_client.UPSTREAM_MODEL_FAMILY
            or response.model_catalog_entry_sha256 != identity["model_catalog_entry_sha256"]
        ):
            raise DailyOpportunityError("daily connector identity is invalid")
        assessments = _validate_output(response.output, bundle, allowed, set(held))
        response_payload = {**asdict(response), "output": response.output}
        with _connection(database) as con, engine_db.transaction(con):
            daily_opportunity_store.complete_run(
                con, run_id, request_sha256=request_sha256, response_id=response.response_id,
                assessments=assessments, response_payload=response_payload, model_input=model_input,
                information_cutoff_at=information_cutoff_at, latency_ms=latency_ms,
                completed_at=completed_at,
            )
        _index_evaluation(database, run_id, completed_at)
        order_ids = _submit_nightly_tools(database, run_id, observed_at, tool_generate)
        return {"status": "completed", "market_date": market_date.isoformat(),
                "assessment_count": len(assessments), "news_status": news["status"],
                "paper_order_count": len(order_ids), "paper_order_ids": order_ids,
                "execution_authority": "local_simulator_only",
                "replayed": False}
    except (agent_model_client.ConnectorError, DailyOpportunityError) as exc:
        with _connection(database) as con, engine_db.transaction(con):
            daily_opportunity_store.fail_run(con, run_id, str(exc), observed_at)
        return {"status": "failed", "market_date": market_date.isoformat(),
                "reason": str(exc), "execution_authority": "none", "replayed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        result = run(database=args.database)
    except (DailyOpportunityError, OpportunityError, duckdb.Error, OSError) as exc:
        result = {"status": "failed", "reason": str(exc), "execution_authority": "none"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
