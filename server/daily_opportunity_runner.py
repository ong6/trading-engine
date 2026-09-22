"""Idempotent daily P8 standout assessment through the constrained Trae model."""
from __future__ import annotations

import argparse
import json
import math
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import duckdb

from engine.daily_opportunities import OpportunityError, detect
from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import agent_model_client, daily_opportunity_news, daily_opportunity_store
from .json_utils import loads_object

LOCK_PATH = REPO_ROOT / ".daily-opportunity.lock"
PORTFOLIO_ID = "daily_opportunity_agent_v1"
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
            [PORTFOLIO_ID],
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
    allowed = {}
    market_id = bundle["market"]["evidence_id"]
    for candidate in bundle["candidates"]:
        allowed[candidate["ticker"]] = {
            market_id, candidate["evidence_id"],
            *(item["evidence_id"] for item in by_ticker[candidate["ticker"]]),
        }
    model_input = {
        "schema_version": 1, "task": "assess each deterministic daily opportunity",
        "execution_authority": "none", "market_date": bundle["market_date"],
        "news_status": news["status"], "market": bundle["market"],
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
    return {"status": run["status"], "market_date": loads_object(run["bundle_payload"])["market_date"],
            "assessment_count": count, "news_status": run["news_status"],
            "execution_authority": "none", "replayed": replayed}


def run(*, database: Path = DEFAULT_DB, now: datetime | None = None, generate: Generate | None = None,
        fetch_news: daily_opportunity_news.Fetch = daily_opportunity_news._fetch) -> dict:
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
                return _result(con, existing, replayed=True)
        with _connection(database, read_only=True) as con:
            bundle, held = detect(con, market_date), _held(con)
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
    try:
        response = generate(model_input)
        if response.request_sha256 != request_sha256:
            raise DailyOpportunityError("daily connector request identity is invalid")
        assessments = _validate_output(response.output, bundle, allowed, set(held))
        response_payload = {**asdict(response), "output": response.output}
        with _connection(database) as con, engine_db.transaction(con):
            daily_opportunity_store.complete_run(
                con, run_id, request_sha256=request_sha256, response_id=response.response_id,
                assessments=assessments, response_payload=response_payload, completed_at=observed_at,
            )
        return {"status": "completed", "market_date": market_date.isoformat(),
                "assessment_count": len(assessments), "news_status": news["status"],
                "execution_authority": "none", "replayed": False}
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
    return 0 if result["status"] in {"completed", "failed"} else 1


if __name__ == "__main__":
    sys.exit(main())
