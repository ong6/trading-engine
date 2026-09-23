"""Locked, durable tool-call confirmation for P8 nightly simulator intents."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import (
    agent_evaluation,
    agent_model_client,
    daily_opportunity_execution,
    daily_opportunity_store,
)
from .json_utils import loads_object, loads_strict

LOCK_PATH = REPO_ROOT / ".daily-opportunity-tool.lock"
Generate = Callable[[dict], agent_model_client.ConnectorResult]
FIELDS = {"ticker", "side", "assessment_sha256", "horizon_sessions",
          "thesis", "invalidation", "evidence_ids"}


class ToolCallError(RuntimeError):
    """A P8 paper tool call is invalid, ambiguous, or not safely replayable."""


@contextmanager
def _connection(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    con = engine_db.connect(path, wait_s=0)
    try:
        yield con
    finally:
        con.close()


def _assessment(con: duckdb.DuckDBPyConnection, assessment_id: int) -> dict:
    cursor = con.execute(
        "SELECT a.id, a.run_id, a.ticker, a.action, a.horizon_sessions, a.thesis, "
        "a.invalidation, a.evidence_ids, a.assessment_sha256, r.market_date, r.status "
        "FROM daily_opportunity_assessments a JOIN daily_opportunity_runs r ON r.id = a.run_id "
        "WHERE a.id = ? AND a.decision = 'swing'", [assessment_id]
    )
    row = cursor.fetchone()
    if row is None or cursor.fetchone() is not None or row[10] != "completed":
        raise ToolCallError("swing assessment is unavailable")
    return dict(zip((item[0] for item in cursor.description), row, strict=True))


def _input(item: dict) -> dict:
    return {
        "schema_version": 1, "task": "confirm the exact retained simulator trade intent",
        "execution_authority": "local_simulator_only",
        "assessment": {
            "ticker": item["ticker"], "side": item["action"],
            "assessment_sha256": item["assessment_sha256"],
            "horizon_sessions": item["horizon_sessions"], "thesis": item["thesis"],
            "invalidation": item["invalidation"],
            "evidence_ids": loads_strict(item["evidence_ids"]),
        },
        "tool": agent_model_client.TRADE_TOOL,
    }


def _validate(arguments: object, assessment: dict) -> dict:
    if not isinstance(arguments, dict) or set(arguments) != FIELDS:
        raise ToolCallError("paper trade tool arguments are invalid")
    expected = _input(assessment)["assessment"]
    if arguments != expected:
        raise ToolCallError("paper trade tool call changed the retained assessment")
    return arguments


def submit(
    assessment_id: int, *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate: Generate | None = None, lock_path: Path = LOCK_PATH,
) -> dict:
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generate = generate or agent_model_client.generate_trade_tool
    with advisory_file_lock(lock_path):
        with _connection(database) as con:
            daily_opportunity_store.init_schema(con)
            assessment = _assessment(con, assessment_id)
            active = con.execute(
                "SELECT active FROM portfolios WHERE id = ?",
                [daily_opportunity_store.PORTFOLIO_ID],
            ).fetchone()
            if active is None or active[0] is not True:
                raise ToolCallError("daily opportunity paper book is inactive")
            request_input = _input(assessment)
            request_sha256 = canonical_sha256(
                agent_model_client.trade_tool_request_payload(request_input)
            )
            with engine_db.transaction(con):
                attempt = daily_opportunity_store.start_tool_attempt(
                    con, assessment_id, assessment["run_id"], request_input,
                    request_sha256, observed,
                )
            if attempt["status"] == "completed":
                arguments = _validate(loads_object(attempt["arguments_payload"]), assessment)
                with engine_db.transaction(con):
                    order_id = daily_opportunity_execution.consume_assessment(
                        con, assessment_id, now=observed
                    )
                    agent_evaluation.link_execution(
                        con, assessment_id=assessment_id, tool_attempt_id=attempt["id"],
                        order_id=order_id, linked_at=observed,
                    )
                return {"status": "completed", "assessment_id": assessment_id,
                        "arguments": arguments, "paper_order_id": order_id,
                        "execution_authority": "local_simulator_only", "replayed": True}
            if attempt["status"] != "new":
                raise ToolCallError("paper trade tool attempt is not safely replayable")
        try:
            response = generate(request_input)
            identity = agent_model_client.identity(role="trade_tool")
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
                raise ToolCallError("paper trade tool request identity is invalid")
            if response.output.get("name") != "submit_paper_trade":
                raise ToolCallError("paper trade tool name is invalid")
            arguments = _validate(response.output.get("arguments"), assessment)
            payload = {**asdict(response), "output": response.output}
        except Exception:
            with _connection(database) as con, engine_db.transaction(con):
                daily_opportunity_store.mark_tool_uncertain(con, attempt["id"], observed)
            raise
        with _connection(database) as con:
            with engine_db.transaction(con):
                daily_opportunity_store.complete_tool_attempt(
                    con, attempt["id"], response_id=response.response_id,
                    call_id=response.output["call_id"], arguments=arguments,
                    response=payload, now=observed,
                )
        with _connection(database) as con:
            with engine_db.transaction(con):
                order_id = daily_opportunity_execution.consume_assessment(
                    con, assessment_id, now=observed
                )
                agent_evaluation.link_execution(
                    con, assessment_id=assessment_id, tool_attempt_id=attempt["id"],
                    order_id=order_id, linked_at=observed,
                )
        return {"status": "completed", "assessment_id": assessment_id,
                "arguments": arguments, "paper_order_id": order_id,
                "execution_authority": "local_simulator_only", "replayed": False}
