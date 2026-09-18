#!/usr/bin/env python3
"""Build or revalidate one non-authorizing source/cache discrepancy packet."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO, TextIO

import duckdb

from engine.lib import db as engine_db
from engine.lib.settings import DEFAULT_DB
from server import agent_data_discrepancy_review
from server.json_utils import loads_object

MAX_PACKET_BYTES = 262_144


class DataDiscrepancyCliError(ValueError):
    """The requested discrepancy review operation is invalid."""


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a canonical ISO date") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must be a canonical ISO date")
    return parsed


def _packet(source: BinaryIO) -> dict:
    payload = source.read(MAX_PACKET_BYTES + 1)
    if len(payload) > MAX_PACKET_BYTES:
        raise DataDiscrepancyCliError("review packet exceeds the input limit")
    if not payload:
        raise DataDiscrepancyCliError("review packet stdin is empty")
    try:
        return loads_object(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise DataDiscrepancyCliError("review packet stdin is invalid") from exc


def build_database(
    database: Path,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
    generated_at: datetime,
) -> dict:
    """Build through one read-only connection."""
    con = engine_db.connect(database, read_only=True, wait_s=0)
    try:
        return agent_data_discrepancy_review.build(
            con,
            dataset=dataset,
            ticker=ticker,
            fact_date=fact_date,
            kind=kind,
            generated_at=generated_at,
        )
    finally:
        con.close()


def verify_database(
    database: Path,
    packet: dict,
    *,
    reviewed_at: datetime,
) -> dict:
    """Revalidate through one read-only connection."""
    con = engine_db.connect(database, read_only=True, wait_s=0)
    try:
        return agent_data_discrepancy_review.verify_retained(
            con,
            packet,
            reviewed_at=reviewed_at,
        )
    finally:
        con.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser(
        "list",
        help="list bounded discrepancy identities and hashes without values",
    )
    list_command.add_argument("--db", type=Path, default=DEFAULT_DB)

    build = commands.add_parser(
        "build",
        help="build one packet from exact retained discrepancy evidence",
    )
    build.add_argument("dataset", choices=("daily_price", "corporate_action"))
    build.add_argument("ticker")
    build.add_argument("fact_date", type=_date)
    build.add_argument("kind")
    build.add_argument("--db", type=Path, default=DEFAULT_DB)

    verify = commands.add_parser(
        "verify",
        help="revalidate one packet supplied as strict JSON on stdin",
    )
    verify.add_argument("--db", type=Path, default=DEFAULT_DB)
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
    observed_at = datetime.now(timezone.utc) if now is None else now
    try:
        if args.command == "list":
            con = engine_db.connect(args.db, read_only=True, wait_s=0)
            try:
                result = agent_data_discrepancy_review.discrepancies(con)
            finally:
                con.close()
        elif args.command == "build":
            result = build_database(
                args.db,
                dataset=args.dataset,
                ticker=args.ticker,
                fact_date=args.fact_date,
                kind=args.kind,
                generated_at=observed_at,
            )
        else:
            source = sys.stdin.buffer if stdin is None else stdin
            result = verify_database(
                args.db,
                _packet(source),
                reviewed_at=observed_at,
            )
    except (
        DataDiscrepancyCliError,
        agent_data_discrepancy_review.DataDiscrepancyReviewError,
        duckdb.Error,
        OSError,
    ) as exc:
        print(f"data discrepancy review unavailable: {exc}", file=errors)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
