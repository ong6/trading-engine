#!/usr/bin/env python3
"""Build or revalidate one non-authorizing human paper-review packet.

The command opens DuckDB read-only. ``build`` prints one exact-intent packet;
``verify`` accepts one bounded strict-JSON packet on stdin and reconstructs it
from retained evidence. It does not accept an approval, write a packet or
database row, activate a portfolio, issue a lease, or submit an order.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO, TextIO

import duckdb

from engine.lib import db as engine_db
from engine.lib.settings import DEFAULT_DB
from server import broker_human_paper_review
from server.broker_contract import SubmitOrderRequest
from server.json_utils import loads_object

MAX_PACKET_BYTES = 1_048_576


class ReviewCliError(ValueError):
    """The operator request or retained review packet is invalid."""


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must be a canonical ISO date")
    return parsed


def _positive(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _packet(source: BinaryIO) -> dict:
    payload = source.read(MAX_PACKET_BYTES + 1)
    if len(payload) > MAX_PACKET_BYTES:
        raise ReviewCliError("review packet exceeds the input limit")
    if not payload:
        raise ReviewCliError("review packet stdin is empty")
    try:
        return loads_object(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReviewCliError("review packet stdin is invalid") from exc


def build_database(
    database: Path,
    request: SubmitOrderRequest,
    *,
    decision_window_id: str,
    mode: str,
    generated_at: datetime,
) -> dict:
    """Build through one read-only connection."""
    con = engine_db.connect(database, read_only=True, wait_s=0)
    try:
        return broker_human_paper_review.build(
            con,
            request,
            decision_window_id=decision_window_id,
            mode=mode,
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
        return broker_human_paper_review.verify_retained(
            con,
            packet,
            reviewed_at=reviewed_at,
        )
    finally:
        con.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build",
        help="build one packet from exact retained intent evidence",
    )
    build.add_argument("mode", choices=("agent_only", "hybrid"))
    build.add_argument("decision_window_id")
    build.add_argument("idempotency_key")
    build.add_argument("account_id")
    build.add_argument("symbol")
    build.add_argument("side", choices=("buy", "sell"))
    build.add_argument("quantity", type=_positive)
    build.add_argument("signal_date", type=_date)
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
        if args.command == "build":
            request = SubmitOrderRequest(
                idempotency_key=args.idempotency_key,
                account_id=args.account_id,
                symbol=args.symbol,
                side=args.side,
                quantity=args.quantity,
                signal_date=args.signal_date,
            )
            result = build_database(
                args.db,
                request,
                decision_window_id=args.decision_window_id,
                mode=args.mode,
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
        ReviewCliError,
        ValueError,
        duckdb.Error,
        OSError,
    ) as exc:
        print(f"review unavailable: {exc}", file=errors)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
