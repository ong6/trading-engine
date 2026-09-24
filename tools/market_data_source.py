#!/usr/bin/env python3
"""Inspect or capture an admitted optional market-data source."""
import argparse
import json
import os
import stat
from datetime import date
from pathlib import Path

from engine.lib.settings import DEFAULT_DB
from server import market_data_sources, official_quote_source

ENV_FILE = Path.home() / ".config/trading-engine/market-data.env"


def _credential_file_status(path: Path = ENV_FILE) -> dict:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    info = path.lstat()
    safe = stat.S_ISREG(info.st_mode) and not path.is_symlink()
    safe = safe and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
    return {"path": str(path), "status": "safe" if safe else "unsafe",
            "mode": oct(stat.S_IMODE(info.st_mode))}


def _load_environment(path: Path) -> dict[str, str]:
    status = _credential_file_status(path)
    if status["status"] == "unsafe":
        raise ValueError("credential file is unsafe")
    values = dict(os.environ)
    if status["status"] == "missing":
        return values
    allowed = {"TRADING_ENGINE_ALPACA_DATA_TERMS_ACCEPTED",
               "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or key not in allowed or not value or any(
                char in value for char in "\r\n\0"):
            raise ValueError("credential file has an invalid entry")
        values[key] = value
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--run-observer", choices=(
        "hourly_market_watch_v3", "four_hour_opportunity_review_v3"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--realtime")
    action.add_argument("--history")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args(argv)
    file_status = _credential_file_status(args.preflight or ENV_FILE)
    if args.preflight is not None:
        try:
            _load_environment(args.preflight)
        except ValueError:
            print(json.dumps({"status": "failed", "credential_file": file_status}))
            return 1
        print(json.dumps({"status": "complete", "credential_file": file_status}))
        return 0
    try:
        environ = _load_environment(ENV_FILE)
    except ValueError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 1
    if args.run_observer:
        os.environ.clear()
        os.environ.update(environ)
        from server.hourly_opportunity_observer import observe
        print(json.dumps(observe(args.run_observer), sort_keys=True))
        return 0
    if args.history and (args.start is None or args.end is None):
        parser.error("--history requires --start and --end")
    if not args.history and (args.start is not None or args.end is not None):
        parser.error("--start/--end require --history")
    if args.realtime:
        result = official_quote_source.capture_realtime(
            args.realtime, database=args.database, environ=environ)
    elif args.history and args.start and args.end:
        result = official_quote_source.capture_history(
            args.history, args.start, args.end, database=args.database, environ=environ)
    else:
        result = {"credential_file": file_status,
                  "sources": market_data_sources.public_statuses(environ)}
    print(json.dumps(result, sort_keys=True))
    if args.realtime or args.history:
        return 0 if result.get("status") == "complete" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
