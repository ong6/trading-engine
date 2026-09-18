"""SQL persistence for append-only shadow agent proposals."""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from .read_model_utils import require_public_positive_integer


class IdentifierSpaceExhausted(RuntimeError):
    """The shadow ledger cannot allocate another public JSON-safe ID."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the server-owned shadow ledger without altering simulator schema."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_proposals (
            id                     BIGINT PRIMARY KEY,
            proposal_id            VARCHAR UNIQUE,
            idempotency_key         VARCHAR UNIQUE,
            proposal_sha256         VARCHAR,
            schema_version          INTEGER,
            mode                    VARCHAR,
            policy_id               VARCHAR,
            policy_registration_sha256 VARCHAR,
            agent_id                VARCHAR,
            model                   VARCHAR,
            model_version           VARCHAR,
            prompt_sha256           VARCHAR,
            toolset_sha256          VARCHAR,
            strategy_id             VARCHAR,
            strategy_config_sha256  VARCHAR,
            agent_boundary_sha256   VARCHAR,
            runtime_source_sha256   VARCHAR,
            data_snapshot_sha256    VARCHAR,
            context_sha256          VARCHAR,
            validated_context_sha256 VARCHAR,
            validated_context       VARCHAR,
            validation_sha256       VARCHAR,
            validation_payload      VARCHAR,
            ticker                  VARCHAR,
            side                    VARCHAR,
            max_notional            DOUBLE,
            stop                    DOUBLE,
            confidence              DOUBLE,
            signal_at               TIMESTAMP,
            expires_at              TIMESTAMP,
            thesis                  VARCHAR,
            invalidation            VARCHAR,
            evidence_ids            VARCHAR,
            normalized_proposal     VARCHAR,
            status                  VARCHAR,
            reasons                 VARCHAR,
            received_at             TIMESTAMP
        )
        """
    )
    con.execute(
        "ALTER TABLE agent_proposals "
        "ADD COLUMN IF NOT EXISTS validated_context VARCHAR"
    )
    con.execute(
        "ALTER TABLE agent_proposals ADD COLUMN IF NOT EXISTS policy_id VARCHAR"
    )
    con.execute(
        "ALTER TABLE agent_proposals "
        "ADD COLUMN IF NOT EXISTS policy_registration_sha256 VARCHAR"
    )
    con.execute(
        "ALTER TABLE agent_proposals ADD COLUMN IF NOT EXISTS validation_sha256 VARCHAR"
    )
    con.execute(
        "ALTER TABLE agent_proposals ADD COLUMN IF NOT EXISTS validation_payload VARCHAR"
    )


def existing(
    con: duckdb.DuckDBPyConnection,
    proposal_id: str,
    idempotency_key: str,
) -> list[tuple]:
    return con.execute(
        "SELECT id, proposal_id, idempotency_key, proposal_sha256, status, "
        "context_sha256, reasons, validated_context_sha256, validation_sha256, "
        "validation_payload, policy_id, policy_registration_sha256 "
        "FROM agent_proposals "
        "WHERE proposal_id = ? OR idempotency_key = ? ORDER BY id",
        [proposal_id, idempotency_key],
    ).fetchall()


def _next_id(con: duckdb.DuckDBPyConnection) -> int:
    maximum = con.execute("SELECT COALESCE(MAX(id), 0) FROM agent_proposals").fetchone()[0]
    try:
        return require_public_positive_integer(maximum + 1)
    except (TypeError, ValueError) as exc:
        raise IdentifierSpaceExhausted from exc


def insert(
    con: duckdb.DuckDBPyConnection,
    proposal: dict,
    *,
    proposal_sha256: str,
    validated_context_sha256: str | None,
    validated_context: dict | None,
    validation_sha256: str | None,
    validation_payload: dict | None,
    status: str,
    reasons: list[str],
    received_at: datetime,
) -> int:
    record_id = _next_id(con)
    con.execute(
        "INSERT INTO agent_proposals ("
        "id, proposal_id, idempotency_key, proposal_sha256, schema_version, mode, "
        "policy_id, policy_registration_sha256, agent_id, model, model_version, "
        "prompt_sha256, toolset_sha256, strategy_id, "
        "strategy_config_sha256, agent_boundary_sha256, runtime_source_sha256, "
        "data_snapshot_sha256, context_sha256, validated_context_sha256, "
        "validated_context, validation_sha256, validation_payload, "
        "ticker, side, max_notional, stop, "
        "confidence, signal_at, expires_at, thesis, invalidation, evidence_ids, "
        "normalized_proposal, status, reasons, received_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            record_id,
            proposal["proposal_id"],
            proposal["idempotency_key"],
            proposal_sha256,
            proposal["schema_version"],
            proposal["mode"],
            proposal["policy_id"],
            proposal["policy_registration_sha256"],
            proposal["agent_id"],
            proposal["model"],
            proposal["model_version"],
            proposal["prompt_sha256"],
            proposal["toolset_sha256"],
            proposal["strategy_id"],
            proposal["strategy_config_sha256"],
            proposal["agent_boundary_sha256"],
            proposal["runtime_source_sha256"],
            proposal["data_snapshot_sha256"],
            proposal["context_sha256"],
            validated_context_sha256,
            (
                None
                if validated_context is None
                else json.dumps(
                    validated_context,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            validation_sha256,
            (
                None
                if validation_payload is None
                else json.dumps(
                    validation_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            proposal["ticker"],
            proposal["side"],
            proposal["max_notional"],
            proposal["stop"],
            proposal["confidence"],
            proposal["signal_at"],
            proposal["expires_at"],
            proposal["thesis"],
            proposal["invalidation"],
            json.dumps(proposal["evidence_ids"], separators=(",", ":")),
            json.dumps(proposal, sort_keys=True, separators=(",", ":"), default=str),
            status,
            json.dumps(reasons, separators=(",", ":")),
            received_at,
        ],
    )
    return record_id
