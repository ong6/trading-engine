"""Append-only, one-way operational halt state for the inert broker boundary.

Missing state is halted. This module can append and verify halt evidence, but
it deliberately has no enable, clear, lease, submission, adapter, or network
operation.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
from engine.lib.util import table_exists

from .broker_contract import BrokerStateError, require_identifier

CONTROL_SCHEMA_VERSION = 1
MAX_REASON_CHARS = 512


@dataclass(frozen=True, slots=True)
class RiskControlStatus:
    schema_version: int
    account_id: str
    halted: bool
    reason: str
    event_count: int
    latest_event_sha256: str | None
    execution_authority: str = "none"


def _timestamp(value: datetime) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise ValueError("risk-control timestamp must be UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _reason(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_REASON_CHARS
        or not value.isprintable()
    ):
        raise ValueError("risk-control reason is invalid")
    return value


def _event_body(
    *,
    halt_key: str,
    account_id: str,
    event_sequence: int,
    reason: str,
    occurred_at: str,
    prior_event_sha256: str | None,
) -> dict:
    return {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "halt_key": halt_key,
        "account_id": account_id,
        "event_sequence": event_sequence,
        "event_type": "halt",
        "reason": reason,
        "occurred_at": occurred_at,
        "prior_event_sha256": prior_event_sha256,
        "execution_authority": "none",
    }


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the append-only halt ledger without changing its halted state."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_risk_control_events (
            halt_key           VARCHAR PRIMARY KEY,
            account_id         VARCHAR NOT NULL,
            event_sequence     INTEGER NOT NULL,
            event_type         VARCHAR NOT NULL,
            reason             VARCHAR NOT NULL,
            occurred_at        VARCHAR NOT NULL,
            prior_event_sha256 VARCHAR,
            event_sha256       VARCHAR NOT NULL,
            UNIQUE (account_id, event_sequence)
        )
        """
    )


def _verified_events(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> list[tuple]:
    if not table_exists(con, "broker_risk_control_events"):
        return []
    rows = con.execute(
        "SELECT halt_key, account_id, event_sequence, event_type, reason, "
        "occurred_at, prior_event_sha256, event_sha256 "
        "FROM broker_risk_control_events WHERE account_id = ? "
        "ORDER BY event_sequence",
        [account_id],
    ).fetchall()
    prior = None
    prior_occurred_at = None
    for expected_sequence, row in enumerate(rows, 1):
        (
            halt_key,
            stored_account,
            sequence,
            event_type,
            reason,
            occurred_at,
            prior_sha256,
            event_sha256,
        ) = row
        try:
            require_identifier(halt_key, "halt key")
            require_identifier(stored_account, "account identifier")
            _reason(reason)
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            canonical_time = _timestamp(parsed)
        except (TypeError, ValueError) as exc:
            raise BrokerStateError("stored risk-control event is invalid") from exc
        body = _event_body(
            halt_key=halt_key,
            account_id=stored_account,
            event_sequence=sequence,
            reason=reason,
            occurred_at=canonical_time,
            prior_event_sha256=prior_sha256,
        )
        if (
            stored_account != account_id
            or sequence != expected_sequence
            or event_type != "halt"
            or canonical_time != occurred_at
            or (prior_occurred_at is not None and parsed < prior_occurred_at)
            or prior_sha256 != prior
            or canonical_sha256(body) != event_sha256
        ):
            raise BrokerStateError("stored risk-control event is invalid")
        prior = event_sha256
        prior_occurred_at = parsed
    return rows


def status(
    con: duckdb.DuckDBPyConnection,
    account_id: str,
) -> RiskControlStatus:
    """Return verified state; missing or empty state is always halted."""
    require_identifier(account_id, "account identifier")
    events = _verified_events(con, account_id)
    if not events:
        return RiskControlStatus(
            schema_version=CONTROL_SCHEMA_VERSION,
            account_id=account_id,
            halted=True,
            reason="default_halted_no_control_event",
            event_count=0,
            latest_event_sha256=None,
        )
    latest = events[-1]
    return RiskControlStatus(
        schema_version=CONTROL_SCHEMA_VERSION,
        account_id=account_id,
        halted=True,
        reason=latest[4],
        event_count=len(events),
        latest_event_sha256=latest[7],
    )


def record_halt(
    con: duckdb.DuckDBPyConnection,
    *,
    halt_key: str,
    account_id: str,
    reason: str,
    now: datetime | None = None,
) -> RiskControlStatus:
    """Append one halt event; exact key replay is idempotent."""
    require_identifier(halt_key, "halt key")
    require_identifier(account_id, "account identifier")
    reason = _reason(reason)
    occurred_at = _timestamp(now or datetime.now(timezone.utc))
    init_schema(con)
    with engine_db.transaction(con):
        events = _verified_events(con, account_id)
        existing = con.execute(
            "SELECT account_id, event_sequence, event_type, reason, occurred_at, "
            "prior_event_sha256, event_sha256 "
            "FROM broker_risk_control_events WHERE halt_key = ?",
            [halt_key],
        ).fetchone()
        if existing is not None:
            if existing[0] != account_id or existing[2] != "halt" or existing[3] != reason:
                raise BrokerStateError("stored risk-control halt conflicts with key")
            return status(con, account_id)
        if events:
            latest_at = datetime.fromisoformat(events[-1][5].replace("Z", "+00:00"))
            if datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) < latest_at:
                raise ValueError("risk-control timestamp precedes the latest event")
        sequence = len(events) + 1
        prior = None if not events else events[-1][7]
        body = _event_body(
            halt_key=halt_key,
            account_id=account_id,
            event_sequence=sequence,
            reason=reason,
            occurred_at=occurred_at,
            prior_event_sha256=prior,
        )
        event_sha256 = canonical_sha256(body)
        con.execute(
            "INSERT INTO broker_risk_control_events VALUES "
            "(?, ?, ?, 'halt', ?, ?, ?, ?)",
            [
                halt_key,
                account_id,
                sequence,
                reason,
                occurred_at,
                prior,
                event_sha256,
            ],
        )
    return status(con, account_id)


def halt_event_sha256(
    con: duckdb.DuckDBPyConnection,
    *,
    halt_key: str,
    account_id: str,
) -> str:
    """Return the verified hash of one exact halt event."""
    require_identifier(halt_key, "halt key")
    require_identifier(account_id, "account identifier")
    events = _verified_events(con, account_id)
    matching = [row for row in events if row[0] == halt_key]
    if len(matching) != 1 or matching[0][1] != account_id:
        raise BrokerStateError("risk-control halt event is unavailable")
    return matching[0][7]


def main(argv: list[str] | None = None) -> int:
    """Inspect or append halt state through an operator-only local CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("status")
    inspect.add_argument("--account", required=True)
    halt = commands.add_parser("halt")
    halt.add_argument("--account", required=True)
    halt.add_argument("--halt-key", required=True)
    halt.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    try:
        con = engine_db.connect(args.db, read_only=args.command == "status")
        try:
            result = (
                status(con, args.account)
                if args.command == "status"
                else record_halt(
                    con,
                    halt_key=args.halt_key,
                    account_id=args.account,
                    reason=args.reason,
                )
            )
        finally:
            con.close()
    except (duckdb.Error, OSError, ValueError, BrokerStateError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(exc).strip() or type(exc).__name__,
                    "execution_authority": "none",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
