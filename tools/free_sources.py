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
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import requests

from engine import free_sources
from engine.lib import db
from engine.lib.resources import write_text_atomic
from sim import nyse

TIINGO_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
MASSIVE_ENDPOINT = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}"
MASSIVE_SPLITS_ENDPOINT = "https://api.massive.com/v3/reference/splits"
MASSIVE_KEY_PATH = Path.home() / ".config/trading-engine/massive.key"
MASSIVE_INTERVAL_SECONDS = 13.0
MASSIVE_DAILY_SESSION_CAP = 10
HTTP_TIMEOUT_SECONDS = 60
USER_AGENT = "trading-engine-free-source-research/1"
UTC_NO_CALL_WINDOWS = (
    (day_time(1, 15), day_time(2, 45)),
    (day_time(5, 45), day_time(7, 0)),
    (day_time(21, 45), day_time(23, 30)),
)
NEW_YORK = ZoneInfo("America/New_York")
NYSE_REGULAR_CLOSE = day_time(16, 0)


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise free_sources.FreeSourceError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _two_years_ago(value: date) -> date:
    try:
        return value.replace(year=value.year - 2)
    except ValueError:  # February 29 becomes February 28 in a non-leap year.
        return value.replace(year=value.year - 2, day=28)


def massive_window(now: datetime) -> tuple[date, date]:
    """Return the free-tier start and most recent completed NYSE session."""
    utc = _aware_utc(now, "Massive window timestamp")
    earliest = _two_years_ago(utc.date()) + timedelta(days=1)
    local = utc.astimezone(NEW_YORK)
    latest = local.date()
    if not nyse.is_session(latest) or local.time().replace(tzinfo=None) < NYSE_REGULAR_CLOSE:
        latest -= timedelta(days=1)
    while not nyse.is_session(latest):
        latest -= timedelta(days=1)
    return earliest, latest


def _network_permitted(now: datetime) -> bool:
    utc = _aware_utc(now, "network-window timestamp")
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
    receipt = _massive_cache_receipt(data_dir, session_date)
    if receipt is None:
        return None
    raw_path, fetched_at, source_sha = receipt
    body = raw_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != source_sha:
        raise free_sources.FreeSourceError("Massive cached response hash is invalid")
    free_sources.parse_massive_grouped_daily(body, session_date)
    return body, fetched_at


def _massive_cache_receipt(
    data_dir: Path, session_date: date,
) -> tuple[Path, datetime, str] | None:
    directory = data_dir / "massive" / session_date.isoformat()
    receipt_path = directory / "receipt.json"
    if not receipt_path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise free_sources.FreeSourceError("Massive date cache is incomplete")
        return None
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise free_sources.FreeSourceError("Massive cache receipt is unsafe")
    receipt, fetched_at, source_sha = _parse_massive_cache_receipt(receipt_path, session_date)
    raw_path = directory / receipt["raw_file"]
    if raw_path.is_symlink() or not raw_path.is_file():
        raise free_sources.FreeSourceError("Massive cached response is missing or unsafe")
    return raw_path, fetched_at, source_sha


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
    rate_limit: Callable[[], object] | None = None,
    window: tuple[date, date] | None = None,
) -> list[dict]:
    requested = list(dates)
    window = massive_window(now()) if window is None else window
    window_start, window_end = window
    if (not requested or len(set(requested)) != len(requested)
            or any(not isinstance(item, date) or isinstance(item, datetime) for item in requested)
            or any(item < window_start or item > window_end or not nyse.is_session(item)
                   for item in requested)):
        raise free_sources.FreeSourceError(
            "Massive dates must be unique NYSE sessions inside "
            f"{window_start.isoformat()}..{window_end.isoformat()}"
        )
    client = session or requests.Session()
    results, last_started = [], None
    if rate_limit is None and monotonic is time.monotonic and sleep is time.sleep:
        rate_limit = free_sources.wait_for_massive_rate_limit
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
            last_started = _reserve_massive_request(now, monotonic, sleep, rate_limit, last_started)
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
            try:
                parsed = free_sources.parse_massive_grouped_daily(body, session_date)
            except free_sources.FreeSourceError:
                # Retain an invalid non-empty response so a parser fix does not spend a call.
                _cache_massive(data_dir, session_date, body, fetched_at)
                raise
            fetched_date = _aware_utc(fetched_at, "Massive fetched_at").date()
            if not parsed and (fetched_date - session_date).days < 2:
                results.append({
                    "source": free_sources.MASSIVE_SOURCE,
                    "date": session_date.isoformat(),
                    "status": "not_yet_published",
                    "row_count": 0,
                    "resumed": False,
                })
                continue
            _cache_massive(data_dir, session_date, body, fetched_at)
            results.append({
                **_load_massive_response(database, session_date, body, fetched_at),
                "resumed": False,
            })
    finally:
        if session is None:
            client.close()
    return results


def _sessions(start: date, end: date, *, newest_first: bool = False) -> list[date]:
    if start > end:
        raise free_sources.FreeSourceError("Massive start date is after end date")
    result, current = [], start
    while current <= end:
        if nyse.is_session(current):
            result.append(current)
        current += timedelta(days=1)
    return list(reversed(result)) if newest_first else result


def _loaded_massive_dates(database: Path) -> set[date]:
    if not database.exists():
        return set()
    con = db.connect(database, read_only=True)
    try:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name='free_daily_bars'"
        ).fetchone()[0]
        if not exists:
            return set()
        return {row[0] for row in con.execute(
            "SELECT DISTINCT date FROM free_daily_bars"
        ).fetchall()}
    finally:
        con.close()


def capture_massive_daily(
    *, database: Path, data_dir: Path, api_key: str | None = None,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    rate_limit: Callable[[], object] | None = None,
) -> dict:
    """Load cached sessions and fetch at most ten missing completed sessions, newest first."""
    window = massive_window(now())
    loaded = _loaded_massive_dates(database)
    work, missing_count = [], 0
    for session_date in _sessions(*window, newest_first=True):
        cached = _massive_cache_receipt(data_dir, session_date) is not None
        if cached and session_date not in loaded:
            work.append(session_date)
        elif not cached and missing_count < MASSIVE_DAILY_SESSION_CAP:
            work.append(session_date)
            missing_count += 1
    if not work:
        return {"status": "up_to_date"}
    key = _load_massive_key() if api_key is None else api_key
    result = capture_massive_dates(
        work, api_key=key, database=database, data_dir=data_dir, session=session,
        now=now, monotonic=monotonic, sleep=sleep, rate_limit=rate_limit, window=window,
    )
    return {
        "status": "complete",
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "fetched_sessions": missing_count,
        "result": result,
    }


def _split_start(database: Path, fallback: date) -> date:
    if not database.exists():
        return fallback - timedelta(days=30)
    con = db.connect(database, read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('free_splits','free_daily_bars')"
            ).fetchall()
        }
        if "free_splits" in tables:
            latest = con.execute("SELECT MAX(ex_date) FROM free_splits").fetchone()[0]
            if latest is not None:
                return min(latest, fallback) - timedelta(days=30)
        if "free_daily_bars" in tables:
            earliest = con.execute("SELECT MIN(date) FROM free_daily_bars").fetchone()[0]
            if earliest is not None:
                return earliest
        return fallback - timedelta(days=30)
    finally:
        con.close()


def _split_url(start: date) -> str:
    query = urlencode({
        "execution_date.gte": start.isoformat(),
        "limit": free_sources.MAX_SPLIT_RESULTS,
        "sort": "execution_date",
        "order": "asc",
    })
    return f"{MASSIVE_SPLITS_ENDPOINT}?{query}"


def _validate_split_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.massive.com"
        or parsed.path != "/v3/reference/splits"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise free_sources.FreeSourceError("Massive splits next_url is unsafe")


def capture_massive_splits(
    *, database: Path, data_dir: Path, api_key: str | None = None,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    rate_limit: Callable[[], object] | None = None,
    max_pages: int = 2,
) -> dict:
    """Capture at most two pages of reference splits through the shared limiter."""
    if max_pages < 1 or max_pages > 2:
        raise free_sources.FreeSourceError("Massive splits page limit must be between 1 and 2")
    instant = now()
    start = _split_start(database, _aware_utc(instant, "split capture timestamp").date())
    key = _load_massive_key() if api_key is None else api_key
    client = session or requests.Session()
    url = _split_url(start)
    pages, observed, page_shas = [], set(), []
    reconciliation_at = instant
    try:
        for _page in range(max_pages):
            _validate_split_url(url)
            _require_network_window(now())
            if rate_limit is None:
                free_sources.wait_for_massive_rate_limit(
                    check=lambda: _require_network_window(now())
                )
            else:
                rate_limit()
                _require_network_window(now())
            try:
                response = client.get(
                    url, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=False,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    },
                )
            except requests.RequestException as exc:
                raise free_sources.FreeSourceError("Massive splits request failed") from exc
            fetched_at = now()
            body = _response_body(response, "Massive splits")
            rows, next_url = free_sources.parse_massive_splits(body)
            source_sha = hashlib.sha256(body).hexdigest()
            observed.update((row["ticker"], row["ex_date"]) for row in rows)
            page_shas.append(source_sha)
            reconciliation_at = fetched_at
            _write_private_atomic(data_dir / "massive" / "splits" / f"{source_sha}.json", body)
            con = db.connect(database, wait_s=0)
            try:
                loaded = free_sources.load_splits(con, body, fetched_at=fetched_at)
            finally:
                con.close()
            pages.append({**loaded, "row_count": len(rows)})
            if next_url is None:
                if len(rows) == free_sources.MAX_SPLIT_RESULTS:
                    raise free_sources.FreeSourceError(
                        "Massive splits full page without next_url is incomplete"
                    )
                reconciliation_sha = hashlib.sha256("\n".join(page_shas).encode()).hexdigest()
                con = db.connect(database, wait_s=0)
                try:
                    reconciliation = free_sources.reconcile_splits(
                        con, observed=observed, start=start,
                        through=_aware_utc(reconciliation_at, "split fetched_at").date(),
                        fetched_at=reconciliation_at, source_sha256=reconciliation_sha,
                    )
                finally:
                    con.close()
                return {
                    "status": "complete", "start": start.isoformat(),
                    "pages": pages, **reconciliation,
                }
            url = next_url
    finally:
        if session is None:
            client.close()
    raise free_sources.FreeSourceError("Massive splits response exceeded the two-page daily bound")


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=free_sources.default_database())
    parser.add_argument("--data-dir", type=Path, default=free_sources.default_data_dir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tiingo = commands.add_parser("tiingo", help="download and load the public ticker archive")
    _paths(tiingo)
    massive = commands.add_parser("massive", help="capture the rolling free grouped-daily window")
    _paths(massive)
    massive.add_argument("--start", type=date.fromisoformat)
    massive.add_argument("--end", type=date.fromisoformat)
    massive.add_argument(
        "--daily", action="store_true",
        help="fetch at most ten missing completed sessions, newest first",
    )
    massive.add_argument(
        "--splits", action="store_true",
        help="capture reference splits since the latest stored execution date",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "tiingo":
            result: object = capture_tiingo(database=args.database, data_dir=args.data_dir)
        elif args.daily:
            if args.splits:
                raise free_sources.FreeSourceError("--daily and --splits are mutually exclusive")
            if args.start is not None or args.end is not None:
                raise free_sources.FreeSourceError("--daily cannot be combined with --start/--end")
            result = capture_massive_daily(database=args.database, data_dir=args.data_dir)
        elif args.splits:
            if args.start is not None or args.end is not None:
                raise free_sources.FreeSourceError("--splits cannot be combined with --start/--end")
            result = capture_massive_splits(database=args.database, data_dir=args.data_dir)
        else:
            window = massive_window(datetime.now(timezone.utc))
            start = window[0] if args.start is None else args.start
            end = window[1] if args.end is None else args.end
            key = _load_massive_key()
            result = capture_massive_dates(
                _sessions(start, end), api_key=key, window=window,
                database=args.database, data_dir=args.data_dir,
            )
    except free_sources.FreeSourceError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    if args.command == "massive" and (args.daily or args.splits):
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps({"status": "complete", "result": result}, sort_keys=True))
    return 0





def _parse_massive_cache_receipt(receipt_path, session_date):
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
    return receipt, fetched_at, source_sha


def _reserve_massive_request(now, monotonic, sleep, rate_limit, last_started):
    _require_network_window(now())
    if last_started is not None:
        remaining = MASSIVE_INTERVAL_SECONDS - (monotonic() - last_started)
        if remaining > 0:
            sleep(remaining)
    _require_network_window(now())
    if rate_limit is not None:
        rate_limit()
        _require_network_window(now())
    return monotonic()


if __name__ == "__main__":
    raise SystemExit(main())
