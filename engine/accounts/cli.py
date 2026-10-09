"""Command-line interface for the engine-owned paper-account service."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from engine.accounts import api, results, service
from engine.accounts import late as late_settle
from engine.accounts import settle as account_settle
from engine.accounts import sources as account_sources
from engine.lib import db
from engine.paper_accounts import AccountRefused


def _json_file(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must contain an object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("spec")
    submit = commands.add_parser("submit")
    submit.add_argument("intent")
    cancel = commands.add_parser("cancel")
    cancel.add_argument("account_id")
    cancel.add_argument("order_id", type=int)
    halt = commands.add_parser("halt")
    halt.add_argument("account_id")
    halt.add_argument("--note", default="")
    resume = commands.add_parser("resume")
    resume.add_argument("account_id")
    resume.add_argument("--by", required=True, choices=("owner", "monthly-review"))
    resume.add_argument("--note", default="")
    retire = commands.add_parser("retire")
    retire.add_argument("account_id")
    commands.add_parser("list")
    result = commands.add_parser("results")
    result.add_argument("account_id")
    result.add_argument("--json", action="store_true", dest="as_json")
    verify = commands.add_parser("verify")
    verify.add_argument("account_id")
    settle = commands.add_parser("settle")
    settle.add_argument("--late", action="store_true")
    settle.add_argument("--date", type=date.fromisoformat)
    token = commands.add_parser("generate-token")
    token.add_argument("--force", action="store_true")
    return parser


def _settle(con, *, session_date: date | None, late: bool):
    if late:
        with account_sources.production_sources(con) as short_con:
            return late_settle.settle(con, session_date=session_date, short_con=short_con)
    if session_date is None:
        session_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if session_date is None:
        raise ValueError("no market session is available to settle")
    with account_sources.production_sources(con) as short_con:
        return account_settle.settle_session(
            con, session_date, late=late, short_con=short_con,
        )


def _execute(args, con, now: datetime):
    if args.command == "create":
        return service.create(con, _json_file(args.spec), now=now)
    if args.command == "submit":
        return service.submit(con, _json_file(args.intent), received_at=now)
    if args.command == "cancel":
        return service.cancel(con, args.account_id, args.order_id, now=now)
    if args.command == "halt":
        return service.halt(con, args.account_id, note=args.note, now=now)
    if args.command == "resume":
        return service.resume(con, args.account_id, resumed_by=args.by, note=args.note, now=now)
    if args.command == "retire":
        return service.retire(con, args.account_id, now=now)
    if args.command == "list":
        return service.account_list(con, include_private=True)
    if args.command == "results":
        return results.build(con, args.account_id)
    if args.command == "verify":
        with account_sources.production_sources(con):
            return service.verify(con, args.account_id)
    if args.command == "settle":
        return _settle(con, session_date=args.date, late=args.late)
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate-token":
        path = api.generate_token(force=args.force)
        print(json.dumps({"token_file": str(path), "mode": "0600"}, sort_keys=True))
        return 0
    now = datetime.now(timezone.utc)
    try:
        with db.connect(wait_s=180) as con:
            payload = _execute(args, con, now)
    except service.VerificationError as exc:
        print(json.dumps(exc.result, sort_keys=True, default=str))
        return 1
    except AccountRefused as exc:
        if args.command == "submit":
            payload = {"order_id": None, "state": "refused", "received_at": now.isoformat(),
                       "cutoff": None, "refusal_reason": str(exc)}
        else:
            payload = {"error": str(exc)}
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
    return int(bool(payload.get("errors")) or payload.get("status") == "mismatch")
