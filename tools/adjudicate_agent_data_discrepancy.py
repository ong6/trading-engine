#!/usr/bin/env python3
"""Record or inspect non-authorizing operator data-discrepancy decisions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, TextIO

import duckdb

from engine.lib import db as engine_db
from engine.lib.settings import DEFAULT_DB
from server import agent_data_discrepancy_adjudication
from server.json_utils import loads_object

REQUEST_SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 327_680
_REQUEST_FIELDS = {
    "schema_version",
    "decision_id",
    "disposition",
    "operator_id",
    "justification",
    "review_packet",
}


class DataDiscrepancyAdjudicationCliError(ValueError):
    """The requested adjudication operation is invalid."""


def _request(source: BinaryIO) -> dict:
    payload = source.read(MAX_REQUEST_BYTES + 1)
    if len(payload) > MAX_REQUEST_BYTES:
        raise DataDiscrepancyAdjudicationCliError(
            "adjudication request exceeds the input limit"
        )
    if not payload:
        raise DataDiscrepancyAdjudicationCliError(
            "adjudication request stdin is empty"
        )
    try:
        request = loads_object(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise DataDiscrepancyAdjudicationCliError(
            "adjudication request stdin is invalid"
        ) from exc
    if (
        set(request) != _REQUEST_FIELDS
        or type(request["schema_version"]) is not int
        or request["schema_version"] != REQUEST_SCHEMA_VERSION
        or not isinstance(request["review_packet"], dict)
    ):
        raise DataDiscrepancyAdjudicationCliError(
            "adjudication request shape is invalid"
        )
    return request


def record_database(
    database: Path,
    request: dict,
    *,
    decided_at: datetime,
) -> dict:
    """Record through the repository connection factory and close reliably."""
    con = engine_db.connect(database, read_only=False, wait_s=0)
    try:
        return agent_data_discrepancy_adjudication.record_decision(
            con,
            request["review_packet"],
            decision_id=request["decision_id"],
            disposition=request["disposition"],
            operator_id=request["operator_id"],
            justification=request["justification"],
            decided_at=decided_at,
        )
    finally:
        con.close()


def status_database(database: Path) -> dict:
    """Inspect the verified ledger through a read-only connection."""
    con = engine_db.connect(database, read_only=True, wait_s=0)
    try:
        return agent_data_discrepancy_adjudication.status(con)
    finally:
        con.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status",
        help="verify the ledger and print aggregate status without justifications",
    )
    commands.add_parser(
        "record",
        help="revalidate and record one strict JSON request from stdin",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    decided_at = datetime.now(timezone.utc) if now is None else now
    try:
        if args.command == "status":
            result = status_database(args.db)
        else:
            source = sys.stdin.buffer if stdin is None else stdin
            result = record_database(
                args.db,
                _request(source),
                decided_at=decided_at,
            )
    except (
        DataDiscrepancyAdjudicationCliError,
        agent_data_discrepancy_adjudication.DataDiscrepancyAdjudicationError,
        duckdb.Error,
        OSError,
    ) as exc:
        print(f"data discrepancy adjudication unavailable: {exc}", file=errors)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
