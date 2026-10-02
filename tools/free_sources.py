#!/usr/bin/env python3
"""Capture P3 free sources into the isolated free-source store."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from engine import free_sources
from engine.lib import db
from engine.lib.resources import write_text_atomic

TIINGO_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
MASSIVE_ENDPOINT = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}"
MASSIVE_KEY_PATH = Path.home() / ".config/trading-engine/massive.key"
MASSIVE_WINDOW_START = date(2024, 10, 1)
MASSIVE_WINDOW_END = date(2026, 9, 30)
MASSIVE_INTERVAL_SECONDS = 13.0
HTTP_TIMEOUT_SECONDS = 60
USER_AGENT = "trading-engine-free-source-research/1"
UTC_NO_CALL_WINDOWS = (
    (day_time(1, 15), day_time(2, 45)),
    (day_time(5, 45), day_time(7, 0)),
    (day_time(21, 45), day_time(23, 30)),
)
NEW_YORK = ZoneInfo("America/New_York")


def _network_permitted(now: datetime) -> bool:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise free_sources.FreeSourceError("network-window timestamp must be timezone-aware")
    utc = now.astimezone(timezone.utc)
    current = utc.time().replace(tzinfo=None)
    if any(start <= current < end for start, end in UTC_NO_CALL_WINDOWS):
        return False
    local = utc.astimezone(NEW_YORK)
    return not (
        local.weekday() < 5
        and day_time(8, 45) <= local.time().replace(tzinfo=None) < day_time(16, 15)
    )


def _require_network_window(now: datetime) -> None:
    if not _network_permitted(now):
        raise free_sources.FreeSourceError("network request is inside a configured no-call window")


def _load_massive_key(path: Path | None = None) -> str:
    path = MASSIVE_KEY_PATH if path is None else path
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise free_sources.FreeSourceError("secure Massive key opening is unavailable")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow)
    except FileNotFoundError as exc:
        raise free_sources.FreeSourceError(
            "Massive API key is missing; create ~/.config/trading-engine/massive.key with mode 600"
        ) from exc
    except OSError as exc:
        raise free_sources.FreeSourceError("Massive API key file is unsafe or unreadable") from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise free_sources.FreeSourceError(
                "Massive API key must be an owner-only regular file with mode 600"
            )
        body = os.read(descriptor, 513)
    finally:
        os.close(descriptor)
    try:
        key = body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise free_sources.FreeSourceError("Massive API key file is not valid UTF-8") from exc
    if (not key or len(body) > 512 or len(key) > 512 or not key.isprintable()
            or any(character.isspace() for character in key)):
        raise free_sources.FreeSourceError("Massive API key file has invalid contents")
    return key


def _write_private_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != body:
            raise free_sources.FreeSourceError("cached raw source differs from its content identity")
        return
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
            temporary_name = tmp.name
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
        Path(temporary_name).chmod(0o600)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _response_body(response, source: str) -> bytes:
    try:
        status_code = int(response.status_code)
        body = bytes(response.content)
    except (AttributeError, TypeError, ValueError) as exc:
        raise free_sources.FreeSourceError(f"{source} response metadata is invalid") from exc
    if status_code != 200:
        raise free_sources.FreeSourceError(f"{source} request returned HTTP {status_code}")
    if not body or len(body) > free_sources.MAX_RESPONSE_BYTES:
        raise free_sources.FreeSourceError(f"{source} response size is invalid")
    return body


def capture_tiingo(
    *, database: Path, data_dir: Path, session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    _require_network_window(now())
    client = session or requests.Session()
    try:
        response = client.get(
            TIINGO_URL, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/zip"},
        )
    except requests.RequestException as exc:
        raise free_sources.FreeSourceError("Tiingo request failed") from exc
    finally:
        if session is None:
            client.close()
    fetched_at = now()
    body = _response_body(response, "Tiingo")
    free_sources.parse_tiingo_archive(body)
    source_sha = hashlib.sha256(body).hexdigest()
    raw_path = data_dir / "tiingo" / f"{source_sha}.zip"
    _write_private_atomic(raw_path, body)
    con = db.connect(database, wait_s=0)
    try:
        result = free_sources.load_security_master(con, body, fetched_at=fetched_at)
    finally:
        con.close()
    return {**result, "raw_path": str(raw_path), "database": str(database)}


def _massive_cache(data_dir: Path, session_date: date) -> tuple[bytes, datetime] | None:
    directory = data_dir / "massive" / session_date.isoformat()
    receipt_path = directory / "receipt.json"
    if not receipt_path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise free_sources.FreeSourceError("Massive date cache is incomplete")
        return None
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise free_sources.FreeSourceError("Massive cache receipt is unsafe")
    try:
        receipt = json.loads(receipt_path.read_text())
        if set(receipt) != {"date", "fetched_at", "raw_file", "source_sha256"}:
            raise ValueError
        if receipt["date"] != session_date.isoformat():
            raise ValueError
        source_sha = receipt["source_sha256"]
        if free_sources.SHA256.fullmatch(source_sha) is None:
            raise ValueError
        if receipt["raw_file"] != f"{source_sha}.json":
            raise ValueError
        fetched_at = datetime.fromisoformat(receipt["fetched_at"])
        if fetched_at.utcoffset() is None:
            raise ValueError
    except (OSError, TypeError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive cache receipt is invalid") from exc
    raw_path = directory / receipt["raw_file"]
    if raw_path.is_symlink() or not raw_path.is_file():
        raise free_sources.FreeSourceError("Massive cached response is missing or unsafe")
    body = raw_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != source_sha:
        raise free_sources.FreeSourceError("Massive cached response hash is invalid")
    free_sources.parse_massive_grouped_daily(body, session_date)
    return body, fetched_at


def _cache_massive(
    data_dir: Path, session_date: date, body: bytes, fetched_at: datetime,
) -> None:
    source_sha = hashlib.sha256(body).hexdigest()
    directory = data_dir / "massive" / session_date.isoformat()
    raw_path = directory / f"{source_sha}.json"
    receipt_path = directory / "receipt.json"
    existing = _massive_cache(data_dir, session_date)
    if existing is not None:
        if existing[0] != body:
            raise free_sources.FreeSourceError("Massive date already has a different response")
        return
    _write_private_atomic(raw_path, body)
    receipt = {
        "date": session_date.isoformat(), "fetched_at": fetched_at.isoformat(),
        "raw_file": raw_path.name, "source_sha256": source_sha,
    }
    write_text_atomic(receipt_path, json.dumps(receipt, sort_keys=True) + "\n")
    receipt_path.chmod(0o600)


def _load_massive_response(
    database: Path, session_date: date, body: bytes, fetched_at: datetime,
) -> dict:
    con = db.connect(database, wait_s=0)
    try:
        return free_sources.load_daily_bars(
            con, body, session_date=session_date, fetched_at=fetched_at
        )
    finally:
        con.close()


def capture_massive_dates(
    dates: Iterable[date], *, api_key: str, database: Path, data_dir: Path,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    requested = list(dates)
    if (not requested or requested != sorted(set(requested))
            or any(not isinstance(item, date) for item in requested)
            or requested[0] < MASSIVE_WINDOW_START or requested[-1] > MASSIVE_WINDOW_END):
        raise free_sources.FreeSourceError(
            "Massive dates must be unique, ordered, and inside 2024-10-01..2026-09-30"
        )
    client = session or requests.Session()
    results, last_started = [], None
    try:
        for session_date in requested:
            cached = _massive_cache(data_dir, session_date)
            if cached is not None:
                body, fetched_at = cached
                results.append({
                    **_load_massive_response(database, session_date, body, fetched_at),
                    "resumed": True,
                })
                continue
            _require_network_window(now())
            if last_started is not None:
                remaining = MASSIVE_INTERVAL_SECONDS - (monotonic() - last_started)
                if remaining > 0:
                    sleep(remaining)
            _require_network_window(now())
            last_started = monotonic()
            try:
                response = client.get(
                    MASSIVE_ENDPOINT.format(date=session_date.isoformat()),
                    params={"adjusted": "true"}, timeout=HTTP_TIMEOUT_SECONDS,
                    allow_redirects=False,
                    headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT,
                             "Accept": "application/json"},
                )
            except requests.RequestException as exc:
                raise free_sources.FreeSourceError("Massive request failed") from exc
            fetched_at = now()
            body = _response_body(response, "Massive")
            # Cache before validating, so a parser fix can reload without spending a call.
            _cache_massive(data_dir, session_date, body, fetched_at)
            free_sources.parse_massive_grouped_daily(body, session_date)
            results.append({
                **_load_massive_response(database, session_date, body, fetched_at),
                "resumed": False,
            })
    finally:
        if session is None:
            client.close()
    return results


def _weekdays(start: date, end: date) -> list[date]:
    if start > end:
        raise free_sources.FreeSourceError("Massive start date is after end date")
    result, current = [], start
    while current <= end:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=free_sources.default_database())
    parser.add_argument("--data-dir", type=Path, default=free_sources.default_data_dir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tiingo = commands.add_parser("tiingo", help="download and load the public ticker archive")
    _paths(tiingo)
    massive = commands.add_parser("massive", help="capture the fixed free grouped-daily window")
    _paths(massive)
    massive.add_argument("--start", type=date.fromisoformat, default=MASSIVE_WINDOW_START)
    massive.add_argument("--end", type=date.fromisoformat, default=MASSIVE_WINDOW_END)
    args = parser.parse_args(argv)
    try:
        if args.command == "tiingo":
            result: object = capture_tiingo(database=args.database, data_dir=args.data_dir)
        else:
            key = _load_massive_key()
            result = capture_massive_dates(
                _weekdays(args.start, args.end), api_key=key,
                database=args.database, data_dir=args.data_dir,
            )
    except free_sources.FreeSourceError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "complete", "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
