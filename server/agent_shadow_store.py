"""Append-only persistence for lock-protected shadow decision attempts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import NamedTuple

import duckdb

from .read_model_utils import require_public_positive_integer

TERMINAL_EVENT_TYPES = frozenset(
    {
        "no_action",
        "malformed_output",
        "transport_failure",
        "proposal_result",
        "proposal_failure",
        "uncertain",
        "cadence_no_action",
        "hybrid_no_veto_candidate",
        "hybrid_allow",
        "hybrid_veto",
        "hybrid_fallback_allow",
    }
)


class ShadowAttempt(NamedTuple):
    id: int
    decision_window: str
    mode: str
    agent_id: str
    strategy_id: str
    ticker: str
    market_date: object
    context_sha256: str | None
    context_payload: str | None
    model_input: str | None
    model_request: str | None
    request_sha256: str | None
    started_at: datetime
    policy_id: str | None
    policy_registration_sha256: str | None


class IdentifierSpaceExhausted(RuntimeError):
    """The shadow-attempt ledger cannot allocate another public JSON-safe ID."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create immutable attempts and append-only attempt events."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_shadow_attempts (
            id                     BIGINT PRIMARY KEY,
            decision_window        VARCHAR UNIQUE,
            schema_version         INTEGER,
            mode                   VARCHAR,
            policy_id              VARCHAR,
            policy_registration_sha256 VARCHAR,
            agent_id               VARCHAR,
            strategy_id            VARCHAR,
            ticker                 VARCHAR,
            market_date            DATE,
            context_sha256         VARCHAR,
            context_payload        VARCHAR,
            model_input            VARCHAR,
            model_request          VARCHAR,
            request_sha256         VARCHAR,
            model                   VARCHAR,
            model_version           VARCHAR,
            prompt_sha256           VARCHAR,
            toolset_sha256          VARCHAR,
            required_proxy_version VARCHAR,
            execution_authority    VARCHAR,
            started_at             TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_shadow_events (
            id          BIGINT PRIMARY KEY,
            attempt_id  BIGINT,
            event_type  VARCHAR,
            payload     VARCHAR,
            occurred_at TIMESTAMP
        )
        """
    )
    con.execute(
        "ALTER TABLE agent_shadow_attempts ADD COLUMN IF NOT EXISTS policy_id VARCHAR"
    )
    con.execute(
        "ALTER TABLE agent_shadow_attempts "
        "ADD COLUMN IF NOT EXISTS policy_registration_sha256 VARCHAR"
    )


def _next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    if table not in {"agent_shadow_attempts", "agent_shadow_events"}:
        raise ValueError("invalid shadow ledger table")
    maximum = con.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
    try:
        return require_public_positive_integer(maximum + 1)
    except (TypeError, ValueError) as exc:
        raise IdentifierSpaceExhausted from exc


def find_window(
    con: duckdb.DuckDBPyConnection,
    decision_window: str,
) -> ShadowAttempt | None:
    row = con.execute(
        "SELECT id, decision_window, mode, agent_id, strategy_id, ticker, "
        "market_date, context_sha256, context_payload, model_input, "
        "model_request, request_sha256, started_at, policy_id, "
        "policy_registration_sha256 "
        "FROM agent_shadow_attempts WHERE decision_window = ?",
        [decision_window],
    ).fetchone()
    return None if row is None else ShadowAttempt(*row)


def unfinished_attempts(
    con: duckdb.DuckDBPyConnection,
    *,
    mode: str,
    strategy_id: str,
    ticker: str,
    policy_id: str,
) -> list[ShadowAttempt]:
    """Return at most two unfinished matching attempts to detect ambiguity."""
    terminal_placeholders = ",".join("?" for _ in TERMINAL_EVENT_TYPES)
    rows = con.execute(
        "SELECT a.id, a.decision_window, a.mode, a.agent_id, a.strategy_id, "
        "a.ticker, a.market_date, a.context_sha256, a.context_payload, "
        "a.model_input, a.model_request, a.request_sha256, a.started_at, "
        "a.policy_id, a.policy_registration_sha256 "
        "FROM agent_shadow_attempts a "
        "WHERE a.mode = ? AND a.strategy_id = ? AND a.ticker = ? "
        "AND (a.policy_id = ? OR a.policy_id IS NULL) "
        "AND NOT EXISTS ("
        "SELECT 1 FROM agent_shadow_events e WHERE e.attempt_id = a.id "
        f"AND e.event_type IN ({terminal_placeholders})"
        ") ORDER BY a.id LIMIT 2",
        [mode, strategy_id, ticker, policy_id, *sorted(TERMINAL_EVENT_TYPES)],
    ).fetchall()
    return [ShadowAttempt(*row) for row in rows]


def insert_attempt(
    con: duckdb.DuckDBPyConnection,
    *,
    decision_window: str,
    mode: str,
    policy_id: str,
    policy_registration_sha256: str,
    agent_id: str,
    strategy_id: str,
    ticker: str,
    market_date,
    context: dict,
    model_input: dict,
    model_request: dict,
    request_sha256: str,
    model_identity: dict,
    started_at: datetime,
) -> int:
    attempt_id = _next_id(con, "agent_shadow_attempts")
    con.execute(
        "INSERT INTO agent_shadow_attempts ("
        "id, decision_window, schema_version, mode, agent_id, strategy_id, "
        "ticker, market_date, context_sha256, context_payload, model_input, "
        "model_request, request_sha256, model, model_version, prompt_sha256, "
        "toolset_sha256, required_proxy_version, execution_authority, started_at, "
        "policy_id, policy_registration_sha256"
        ") VALUES (?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', ?, ?, ?)",
        [
            attempt_id,
            decision_window,
            mode,
            agent_id,
            strategy_id,
            ticker,
            market_date,
            context["context_sha256"],
            json.dumps(context, sort_keys=True, separators=(",", ":")),
            json.dumps(model_input, sort_keys=True, separators=(",", ":")),
            json.dumps(model_request, sort_keys=True, separators=(",", ":")),
            request_sha256,
            model_identity["model"],
            model_identity["model_version"],
            model_identity["instructions_sha256"],
            model_identity["toolset_sha256"],
            model_identity["required_proxy_version"],
            started_at,
            policy_id,
            policy_registration_sha256,
        ],
    )
    append_event(
        con,
        attempt_id,
        "started",
        {
            "request_sha256": request_sha256,
            "execution_authority": "none",
        },
        occurred_at=started_at,
    )
    return attempt_id


def insert_cadence_no_action(
    con: duckdb.DuckDBPyConnection,
    *,
    decision_window: str,
    mode: str,
    policy_id: str,
    policy_registration_sha256: str,
    agent_id: str,
    strategy_id: str,
    ticker: str,
    market_date,
    started_at: datetime,
) -> int:
    """Record a deterministic non-signal date without constructing a model request."""
    attempt_id = _next_id(con, "agent_shadow_attempts")
    con.execute(
        "INSERT INTO agent_shadow_attempts ("
        "id, decision_window, schema_version, mode, policy_id, "
        "policy_registration_sha256, agent_id, strategy_id, ticker, market_date, "
        "execution_authority, started_at"
        ") VALUES (?, ?, 2, ?, ?, ?, ?, ?, ?, ?, 'none', ?)",
        [
            attempt_id,
            decision_window,
            mode,
            policy_id,
            policy_registration_sha256,
            agent_id,
            strategy_id,
            ticker,
            market_date,
            started_at,
        ],
    )
    result = {
        "schema_version": 2,
        "attempt_id": attempt_id,
        "decision_window": decision_window,
        "status": "cadence_no_action",
        "reason": "market date is not a registered strategy signal date",
        "proposal_result": None,
        "execution_authority": "none",
        "replayed": False,
    }
    append_event(
        con,
        attempt_id,
        "cadence_no_action",
        {
            "cadence": "monthly",
            "market_date": market_date.isoformat(),
            "model_requested": False,
            "result": result,
        },
        occurred_at=started_at,
    )
    return attempt_id


def insert_deterministic_attempt(
    con: duckdb.DuckDBPyConnection,
    *,
    decision_window: str,
    mode: str,
    policy_id: str,
    policy_registration_sha256: str,
    agent_id: str,
    strategy_id: str,
    ticker: str,
    market_date,
    context: dict,
    model_identity: dict,
    event_type: str,
    event_payload: dict,
    started_at: datetime,
) -> int:
    """Record a context-derived terminal outcome that requires no model call."""
    if event_type not in {"hybrid_no_veto_candidate"}:
        raise ValueError("invalid deterministic shadow event")
    attempt_id = _next_id(con, "agent_shadow_attempts")
    event_payload = {
        **event_payload,
        "result": {
            **event_payload["result"],
            "attempt_id": attempt_id,
        },
    }
    con.execute(
        "INSERT INTO agent_shadow_attempts ("
        "id, decision_window, schema_version, mode, policy_id, "
        "policy_registration_sha256, agent_id, strategy_id, ticker, market_date, "
        "context_sha256, context_payload, model, model_version, prompt_sha256, "
        "toolset_sha256, required_proxy_version, execution_authority, started_at"
        ") VALUES (?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', ?)",
        [
            attempt_id,
            decision_window,
            mode,
            policy_id,
            policy_registration_sha256,
            agent_id,
            strategy_id,
            ticker,
            market_date,
            context["context_sha256"],
            json.dumps(context, sort_keys=True, separators=(",", ":")),
            model_identity["model"],
            model_identity["model_version"],
            model_identity["instructions_sha256"],
            model_identity["toolset_sha256"],
            model_identity["required_proxy_version"],
            started_at,
        ],
    )
    append_event(
        con,
        attempt_id,
        event_type,
        event_payload,
        occurred_at=started_at,
    )
    return attempt_id


def append_event(
    con: duckdb.DuckDBPyConnection,
    attempt_id: int,
    event_type: str,
    payload: dict,
    *,
    occurred_at: datetime,
) -> int:
    event_id = _next_id(con, "agent_shadow_events")
    con.execute(
        "INSERT INTO agent_shadow_events "
        "(id, attempt_id, event_type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        [
            event_id,
            attempt_id,
            event_type,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            occurred_at,
        ],
    )
    return event_id


def events(con: duckdb.DuckDBPyConnection, attempt_id: int) -> list[tuple]:
    return con.execute(
        "SELECT id, event_type, payload, occurred_at FROM agent_shadow_events "
        "WHERE attempt_id = ? ORDER BY id",
        [attempt_id],
    ).fetchall()
