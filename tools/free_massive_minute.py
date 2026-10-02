#!/usr/bin/env python3
"""Build and run the resumable P3 Massive free minute-bar capture."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from datetime import time as day_time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from engine import free_massive_minute as minute
from engine import free_sources
from engine.lib import db
from engine.lib.resources import write_text_atomic
from tools import free_sources as daily_capture

ENDPOINT = "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}"
MANIFEST_FILE = "manifest.json"
HTTP_TIMEOUT_SECONDS = 60
# Until this branch reaches the daily service, leave its two ten-call starts uncontested.
DAILY_HANDOFF_WINDOWS = (
    (day_time(6, 59), day_time(7, 13)),
    (day_time(11, 19), day_time(11, 23)),
)


class MinuteWindowClosed(free_sources.FreeSourceError):
    """The next provider call falls in a registered no-call window."""


def _minute_network_permitted(now: datetime) -> bool:
    utc = daily_capture._aware_utc(now, "minute network-window timestamp")
    current = utc.time().replace(tzinfo=None)
    return (daily_capture._network_permitted(utc)
            and not any(start <= current < end for start, end in DAILY_HANDOFF_WINDOWS))


def _require_minute_window(now: datetime) -> None:
    if not _minute_network_permitted(now):
        raise MinuteWindowClosed("network request is inside a configured no-call window")


def _next_permitted(now: datetime) -> datetime:
    candidate = daily_capture._aware_utc(now, "next permitted timestamp")
    while not _minute_network_permitted(candidate):
        ends: list[datetime] = []
        current = candidate.time().replace(tzinfo=None)
        for start, end in (*daily_capture.UTC_NO_CALL_WINDOWS, *DAILY_HANDOFF_WINDOWS):
            if start <= current < end:
                ends.append(datetime.combine(candidate.date(), end, timezone.utc))
        local = candidate.astimezone(daily_capture.NEW_YORK)
        local_time = local.time().replace(tzinfo=None)
        if local.weekday() < 5 and day_time(8, 45) <= local_time < day_time(16, 15):
            ends.append(datetime.combine(
                local.date(), day_time(16, 15), daily_capture.NEW_YORK
            ).astimezone(timezone.utc))
        if not ends:
            raise free_sources.FreeSourceError("cannot resolve the Massive no-call window")
        candidate = max(ends)
    return candidate


def _read_priority_tickers(path: Path | None) -> set[str]:
    if path is None:
        return set()
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise free_sources.FreeSourceError("priority ticker file is unreadable") from exc
    tickers = {line.strip() for line in lines if line.strip()}
    if any(free_sources.MASSIVE_TICKER.fullmatch(ticker) is None for ticker in tickers):
        raise free_sources.FreeSourceError("priority ticker file contains an invalid ticker")
    return tickers


def _read_priority_json(path: Path | None) -> set[str]:
    if path is None:
        return set()
    try:
        pending = [json.loads(path.read_text())]
    except (OSError, ValueError) as exc:
        raise free_sources.FreeSourceError("priority JSON is unreadable") from exc
    tickers: set[str] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            ticker = item.get("ticker")
            if isinstance(ticker, str):
                tickers.add(ticker)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if any(free_sources.MASSIVE_TICKER.fullmatch(ticker) is None for ticker in tickers):
        raise free_sources.FreeSourceError("priority JSON contains an invalid ticker")
    return tickers


def _manifest_identity(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive minute manifest is invalid") from exc
    if (not isinstance(payload, dict)
            or free_sources.SHA256.fullmatch(str(payload.get("manifest_sha256", ""))) is None
            or payload["manifest_sha256"] != _manifest_identity(payload)):
        raise free_sources.FreeSourceError("Massive minute manifest identity is invalid")
    return payload


def prepare_manifest(
    *, daily_database: Path, data_dir: Path,
    priority_tickers_path: Path | None = None,
    priority_json_path: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    path = data_dir / MANIFEST_FILE
    if path.exists():
        return _load_manifest(path)
    start, end = daily_capture.massive_window(now())
    con = db.connect(daily_database, read_only=True)
    try:
        payload = minute.manifest_payload(
            con, created_at=now(), start=start, end=end,
            priority_tickers=(_read_priority_tickers(priority_tickers_path)
                              | _read_priority_json(priority_json_path)),
        )
    finally:
        con.close()
    daily_capture._write_private_atomic(
        path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    )
    return payload


def _chunk_directory(data_dir: Path, ticker: str, start: date, end: date) -> Path:
    identity = hashlib.sha256(f"{ticker}\0{start}\0{end}".encode()).hexdigest()
    return data_dir / "chunks" / identity


def _write_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_text_atomic(path, json.dumps(payload, sort_keys=True) + "\n")
    path.chmod(0o600)


def _read_progress(data_dir: Path, ticker: str, start: date, end: date) -> dict | None:
    path = _chunk_directory(data_dir, ticker, start, end) / "receipt.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise free_sources.FreeSourceError("Massive minute cache receipt is unsafe")
    try:
        payload = json.loads(path.read_text())
        if (payload.get("schema_version") != 1 or payload.get("ticker") != ticker
                or payload.get("start") != start.isoformat()
                or payload.get("end") != end.isoformat()
                or not isinstance(payload.get("pages"), list)
                or not isinstance(payload.get("complete"), bool)):
            raise ValueError
        next_url = payload.get("next_url")
        if next_url is not None:
            _validate_next_url(next_url)
        for page in payload["pages"]:
            if (set(page) != {"fetched_at", "source_sha256"}
                    or free_sources.SHA256.fullmatch(page["source_sha256"]) is None
                    or datetime.fromisoformat(page["fetched_at"]).utcoffset() is None):
                raise ValueError
            raw_path = data_dir / "raw" / f"{page['source_sha256']}.json"
            body = raw_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != page["source_sha256"]:
                raise ValueError
            minute.parse_page(body, ticker=ticker, start=start, end=end)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive minute cache receipt is invalid") from exc
    return payload


def _cached_pages(data_dir: Path, progress: dict) -> list[tuple[bytes, datetime]]:
    return [
        ((data_dir / "raw" / f"{page['source_sha256']}.json").read_bytes(),
         datetime.fromisoformat(page["fetched_at"]))
        for page in progress["pages"]
    ]


def _validate_next_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.massive.com"
            or not parsed.path.startswith("/v2/aggs/ticker/")
            or parsed.username is not None or parsed.password is not None):
        raise free_sources.FreeSourceError("Massive minute next_url is unsafe")


def capture_chunk(
    con, *, manifest_sha256: str, ticker: str, start: date, end: date,
    api_key: str, data_dir: Path, session: requests.Session,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    rate_limit: Callable[[], object] | None = None,
) -> dict:
    directory = _chunk_directory(data_dir, ticker, start, end)
    receipt_path = directory / "receipt.json"
    progress = _read_progress(data_dir, ticker, start, end)
    if progress is not None and progress["complete"]:
        return minute.load_chunk(
            con, _cached_pages(data_dir, progress), manifest_sha256=manifest_sha256,
            ticker=ticker, start=start, end=end,
        )
    if progress is None:
        progress = {"schema_version": 1, "ticker": ticker, "start": start.isoformat(),
                    "end": end.isoformat(), "pages": [], "next_url": None, "complete": False}
    encoded = quote(ticker, safe="")
    first_url = ENDPOINT.format(ticker=encoded, start=start.isoformat(), end=end.isoformat())
    url = progress["next_url"] or first_url
    while not progress["complete"]:
        _require_minute_window(now())
        if rate_limit is None:
            free_sources.wait_for_massive_rate_limit(check=lambda: _require_minute_window(now()))
        else:
            rate_limit()
            _require_minute_window(now())
        try:
            response = session.get(
                url, params={"adjusted": "true", "sort": "asc", "limit": 50_000}
                if url == first_url else None,
                timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=False,
                headers={"Authorization": f"Bearer {api_key}",
                         "User-Agent": daily_capture.USER_AGENT, "Accept": "application/json"},
            )
        except requests.RequestException as exc:
            raise free_sources.FreeSourceError("Massive minute request failed") from exc
        fetched_at = now()
        body = daily_capture._response_body(response, "Massive minute")
        _, next_url = minute.parse_page(body, ticker=ticker, start=start, end=end)
        if next_url is not None:
            _validate_next_url(next_url)
        source_sha = hashlib.sha256(body).hexdigest()
        daily_capture._write_private_atomic(data_dir / "raw" / f"{source_sha}.json", body)
        progress["pages"].append({"fetched_at": fetched_at.isoformat(),
                                  "source_sha256": source_sha})
        progress["next_url"] = next_url
        progress["complete"] = next_url is None
        _write_progress(receipt_path, progress)
        url = next_url
    return minute.load_chunk(
        con, _cached_pages(data_dir, progress), manifest_sha256=manifest_sha256,
        ticker=ticker, start=start, end=end,
    )


def capture_manifest(
    manifest: dict, *, database: Path, data_dir: Path, api_key: str,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    rate_limit: Callable[[], object] | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    client = session or requests.Session()
    database.parent.mkdir(parents=True, exist_ok=True)
    con = db.connect(database, wait_s=0)
    completed = 0
    try:
        minute.init_schema(con)
        for ticker_item in manifest["tickers"]:
            ticker = ticker_item["ticker"]
            for chunk in manifest["chunks"]:
                start, end = date.fromisoformat(chunk["start"]), date.fromisoformat(chunk["end"])
                if not _minute_network_permitted(now()):
                    resume_at = _next_permitted(now())
                    sleep(max(0.0, (resume_at - daily_capture._aware_utc(
                        now(), "capture timestamp"
                    )).total_seconds()))
                try:
                    result = capture_chunk(
                        con, manifest_sha256=manifest["manifest_sha256"], ticker=ticker,
                        start=start, end=end, api_key=api_key, data_dir=data_dir,
                        session=client, now=now, rate_limit=rate_limit,
                    )
                except MinuteWindowClosed:
                    resume_at = _next_permitted(now())
                    sleep(max(0.0, (resume_at - daily_capture._aware_utc(
                        now(), "capture timestamp"
                    )).total_seconds()))
                    result = capture_chunk(
                        con, manifest_sha256=manifest["manifest_sha256"], ticker=ticker,
                        start=start, end=end, api_key=api_key, data_dir=data_dir,
                        session=client, now=now, rate_limit=rate_limit,
                    )
                completed += 1
                if progress is not None:
                    progress({**result, "completed_chunks": completed,
                              "total_chunks": manifest["requests_estimate"]})
    finally:
        con.close()
        if session is None:
            client.close()
    return {"status": "complete", "completed_chunks": completed,
            "manifest_sha256": manifest["manifest_sha256"]}


def _summary(manifest: dict) -> dict:
    return {
        "status": "prepared", "manifest_sha256": manifest["manifest_sha256"],
        "universe": manifest["ticker_count"], "requests_estimate": manifest["requests_estimate"],
        "runtime_estimate_hours": manifest["runtime_at_five_per_minute_hours"],
        "window": manifest["window"], "chunks_per_ticker": len(manifest["chunks"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=minute.default_database())
    parser.add_argument("--data-dir", type=Path, default=minute.default_data_dir())
    parser.add_argument("--daily-database", type=Path, default=free_sources.default_database())
    parser.add_argument("--priority-tickers", type=Path)
    parser.add_argument("--priority-json", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = prepare_manifest(
            daily_database=args.daily_database, data_dir=args.data_dir,
            priority_tickers_path=args.priority_tickers,
            priority_json_path=args.priority_json,
        )
        print(json.dumps(_summary(manifest), sort_keys=True), flush=True)
        if args.prepare_only:
            return 0
        api_key = daily_capture._load_massive_key()
        result = capture_manifest(
            manifest, database=args.database, data_dir=args.data_dir, api_key=api_key,
            progress=lambda item: print(json.dumps(item, sort_keys=True), flush=True),
        )
        print(json.dumps(result, sort_keys=True), flush=True)
    except free_sources.FreeSourceError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
