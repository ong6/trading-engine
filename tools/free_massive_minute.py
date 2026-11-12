#!/usr/bin/env python3
"""Build and run the resumable P3 Massive free minute-bar capture.

The capture is finite. When every chunk is loaded or terminally rejected it writes
``capture-complete.json`` with an explicit completion status and any rejections. A later
start for the same manifest exits 0; its unit does not start while that file exists.
``--max-runtime-hours`` pauses between chunks once the run is that old and exits 75 (resume
later); the unit restarts it, so the capture keeps a bounded run without a failed result.
Rejected chunks retain their evidence and do not stop later chunks. Cooldown-only work
waits until due within the runtime bound, otherwise pauses. Three identical parser
rejections spanning at least 48 hours become terminal; only --retry-terminal retries them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
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
COMPLETE_FILE = "capture-complete.json"
EXIT_PAUSED = 75
EXIT_INCOMPLETE = 1
CHUNK_RETRY_SECONDS = 3600
TERMINAL_MIN_ATTEMPTS = 3
TERMINAL_MIN_SECONDS = 48 * 3600
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
        failure = payload.get("failure")
        if failure is not None:
            if (not isinstance(failure, dict) or not isinstance(failure.get("reason"), str)
                    or datetime.fromisoformat(failure["retry_after"]).utcoffset() is None):
                raise ValueError
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


def _terminal_result(progress: dict) -> dict:
    return {"status": "rejected_terminal",
            **{key: progress[key] for key in ("ticker", "start", "end")},
            **progress["rejected_terminal"]}


def _record_rejection(directory: Path, progress: dict, failure: dict, evidence_sha: str) -> None:
    """Track consecutive parser rejections; older evidence never implies new attempts."""
    if not failure["parser_rejection"] or failure["source_sha256"] is None:
        progress.pop("rejection_attempts", None)
        return
    attempts = progress.get("rejection_attempts", [])
    if attempts and any(attempts[-1][key] != failure[key]
                        for key in ("source_sha256", "reason")):
        attempts = []
    attempts.append({"attempted_at": failure["fetched_at"],
                     "source_sha256": failure["source_sha256"], "reason": failure["reason"],
                     "failure_evidence_sha256": evidence_sha})
    progress["rejection_attempts"] = attempts
    span = (datetime.fromisoformat(attempts[-1]["attempted_at"])
            - datetime.fromisoformat(attempts[0]["attempted_at"])).total_seconds()
    if len(attempts) < TERMINAL_MIN_ATTEMPTS or span < TERMINAL_MIN_SECONDS:
        return
    decision = {"status": "rejected_terminal", "manifest_sha256": failure["manifest_sha256"],
                **{key: failure[key] for key in ("ticker", "start", "end", "reason")},
                "decided_at": failure["failed_at"], "attempts": attempts}
    body = (json.dumps(decision, sort_keys=True) + "\n").encode()
    sha = hashlib.sha256(body).hexdigest()
    daily_capture._write_private_atomic(directory / "rejections" / f"{sha}.json", body)
    progress["rejected_terminal"] = {"reason": failure["reason"], "evidence_sha256": sha}


def _validate_next_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.massive.com"
            or not parsed.path.startswith("/v2/aggs/ticker/")
            or parsed.username is not None or parsed.password is not None):
        raise free_sources.FreeSourceError("Massive minute next_url is unsafe")


PAGE_ATTEMPTS = 3
RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})


def _request_page(session, *, url, first_url, api_key, now, rate_limit, sleep):
    """Retry transient requests; every attempt obeys the shared pacing/window."""
    for attempt in range(PAGE_ATTEMPTS):
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
        except requests.RequestException:
            response = None
        if response is not None and response.status_code not in RETRYABLE_HTTP:
            return response
        if attempt + 1 < PAGE_ATTEMPTS:
            sleep(3.0 * (2 ** attempt))
    raise free_sources.FreeSourceError("Massive minute request failed after 3 attempts")


def capture_chunk(
    con, *, manifest_sha256: str, ticker: str, start: date, end: date,
    api_key: str, data_dir: Path, session: requests.Session,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    rate_limit: Callable[[], object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    retry_terminal: bool = False,
) -> dict:
    directory = _chunk_directory(data_dir, ticker, start, end)
    receipt_path = directory / "receipt.json"
    progress = {"schema_version": 1, "ticker": ticker, "start": start.isoformat(),
                "end": end.isoformat(), "pages": [], "next_url": None, "complete": False}
    encoded = quote(ticker, safe="")
    first_url = ENDPOINT.format(ticker=encoded, start=start.isoformat(), end=end.isoformat())
    url, source_sha, fetched_at = first_url, None, None
    loading, parsing = False, False
    try:
        saved = _read_progress(data_dir, ticker, start, end)
        if saved is not None:
            progress = saved
        terminal = progress.get("rejected_terminal")
        if terminal is not None:
            if not retry_terminal:
                return _terminal_result(progress)
            # The explicit retry starts new evidence; the old decision file is retained.
            progress.pop("rejected_terminal")
            progress.pop("rejection_attempts", None)
            progress.pop("failure", None)
            _write_progress(receipt_path, progress)
        failure = progress.get("failure")
        if failure is not None and now() < datetime.fromisoformat(failure["retry_after"]):
            return {"status": "failed", "ticker": ticker, "start": start.isoformat(),
                    "end": end.isoformat(), "reason": failure["reason"], "deferred": True,
                    "retry_after": failure["retry_after"]}
        url = progress["next_url"] or first_url
        while not progress["complete"]:
            source_sha, fetched_at = None, None
            response = _request_page(
                session, url=url, first_url=first_url, api_key=api_key,
                now=now, rate_limit=rate_limit, sleep=sleep,
            )
            fetched_at = now()
            body = bytes(response.content)
            if 0 < len(body) <= free_sources.MAX_RESPONSE_BYTES:
                source_sha = hashlib.sha256(body).hexdigest()
                daily_capture._write_private_atomic(data_dir / "raw" / f"{source_sha}.json", body)
            body = daily_capture._response_body(response, "Massive minute")
            parsing = True
            _, next_url = minute.parse_page(body, ticker=ticker, start=start, end=end)
            parsing = False
            progress.pop("rejection_attempts", None)
            if next_url is not None:
                _validate_next_url(next_url)
            progress["pages"].append({"fetched_at": fetched_at.isoformat(),
                                      "source_sha256": source_sha})
            progress["next_url"] = next_url
            progress["complete"] = next_url is None
            _write_progress(receipt_path, progress)
            url = next_url
        loading = True
        result = minute.load_chunk(
            con, _cached_pages(data_dir, progress), manifest_sha256=manifest_sha256,
            ticker=ticker, start=start, end=end,
        )
        if progress.pop("failure", None) is not None:
            _write_progress(receipt_path, progress)
        return result
    except MinuteWindowClosed:
        raise
    except free_sources.FreeSourceError as exc:
        failed_at = now()
        failure = {"manifest_sha256": manifest_sha256, "ticker": ticker,
                   "start": start.isoformat(), "end": end.isoformat(), "reason": str(exc),
                   "failed_at": failed_at.isoformat(), "source_sha256": source_sha,
                   "parser_rejection": parsing,
                   "fetched_at": None if fetched_at is None else fetched_at.isoformat(),
                   "url": url, "pages": list(progress["pages"]),
                   "retry_after": (failed_at + timedelta(seconds=CHUNK_RETRY_SECONDS)).isoformat()}
        evidence = (json.dumps(failure, sort_keys=True) + "\n").encode()
        evidence_sha = hashlib.sha256(evidence).hexdigest()
        daily_capture._write_private_atomic(directory / "failures" / f"{evidence_sha}.json", evidence)
        _record_rejection(directory, progress, failure, evidence_sha)
        if loading:
            # A whole-chunk rejection (such as overlapping pages) needs a fresh fetch.
            progress["pages"], progress["next_url"] = [], None
        progress["complete"], progress["failure"] = False, failure
        _write_progress(receipt_path, progress)
        if "rejected_terminal" in progress:
            return _terminal_result(progress)
        raise


def capture_manifest(
    manifest: dict, *, database: Path, data_dir: Path, api_key: str,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    rate_limit: Callable[[], object] | None = None,
    progress: Callable[[dict], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    max_runtime_seconds: float | None = None,
    retry_terminal: bool = False,
) -> dict:
    monotonic = monotonic or time.monotonic
    client = session or requests.Session()
    deadline = None if max_runtime_seconds is None else monotonic() + max_runtime_seconds
    database.parent.mkdir(parents=True, exist_ok=True)
    con = db.connect(database, wait_s=0)
    completed, skipped = 0, 0
    failures: dict[tuple, dict] = {}
    rejections: dict[tuple, dict] = {}

    def summary(status: str) -> dict:
        return {"status": status, "completed_chunks": completed, "failed_chunks": len(failures),
                "rejected_terminal_chunks": len(rejections), "rejections": list(rejections.values()),
                "skipped_chunks": skipped, "manifest_sha256": manifest["manifest_sha256"]}

    def wait_until(resume_at: datetime) -> bool:
        wait = max(0.0, (resume_at - daily_capture._aware_utc(
            now(), "capture timestamp"
        )).total_seconds())
        if deadline is not None and monotonic() + wait >= deadline:
            return False
        sleep(wait)
        return True

    try:
        minute.init_schema(con)
        loaded = set(con.execute(
            """SELECT ticker,start_date,end_date FROM massive_minute_chunks
            WHERE manifest_sha256=?""", [manifest["manifest_sha256"]],
        ).fetchall())
        # The store records successful loads atomically; avoid re-reading every raw page.
        skipped = sum((item["ticker"], date.fromisoformat(chunk["start"]),
                       date.fromisoformat(chunk["end"])) in loaded
                      for item in manifest["tickers"] for chunk in manifest["chunks"])
        completed = skipped
        pending = []
        for item in manifest["tickers"]:
            for chunk in manifest["chunks"]:
                key = (item["ticker"], date.fromisoformat(chunk["start"]),
                       date.fromisoformat(chunk["end"]))
                if key in loaded:
                    continue
                saved = _read_progress(data_dir, *key)
                if saved is not None and "rejected_terminal" in saved:
                    rejections[key] = {k: v for k, v in _terminal_result(saved).items()
                                       if k != "status"}
                    if not retry_terminal:
                        continue
                if saved is not None and "failure" in saved:
                    failures[key] = saved["failure"]
                pending.append(key)
        if progress is not None and skipped:
            progress({**summary("resumed"), "total_chunks": manifest["requests_estimate"]})
        while pending:
            remaining = []
            for key in pending:
                ticker, start, end = key
                failure = failures.get(key)
                if (failure is not None and not (retry_terminal and key in rejections)
                        and now() < datetime.fromisoformat(failure["retry_after"])):
                    remaining.append(key)
                    if progress is not None:
                        progress({**summary("failed"), "ticker": ticker,
                                  "start": start.isoformat(), "end": end.isoformat(),
                                  "reason": failure["reason"], "deferred": True,
                                  "retry_after": failure["retry_after"]})
                    continue
                if deadline is not None and monotonic() >= deadline:
                    return summary("paused")
                if not _minute_network_permitted(now()):
                    if not wait_until(_next_permitted(now())):
                        return summary("paused")
                try:
                    try:
                        result = capture_chunk(
                            con, manifest_sha256=manifest["manifest_sha256"], ticker=ticker,
                            start=start, end=end, api_key=api_key, data_dir=data_dir,
                            session=client, now=now, rate_limit=rate_limit, sleep=sleep,
                            retry_terminal=retry_terminal,
                        )
                    except MinuteWindowClosed:
                        if not wait_until(_next_permitted(now())):
                            return summary("paused")
                        result = capture_chunk(
                            con, manifest_sha256=manifest["manifest_sha256"], ticker=ticker,
                            start=start, end=end, api_key=api_key, data_dir=data_dir,
                            session=client, now=now, rate_limit=rate_limit, sleep=sleep,
                            retry_terminal=retry_terminal,
                        )
                except MinuteWindowClosed:
                    return summary("paused")
                except free_sources.FreeSourceError as exc:
                    result = {"status": "failed", "ticker": ticker, "start": start.isoformat(),
                              "end": end.isoformat(), "reason": str(exc)}
                if result.get("status") == "failed":
                    saved = _read_progress(data_dir, *key)
                    if saved is None or "failure" not in saved:
                        return {**summary("incomplete"), "reason": result["reason"]}
                    failures[key] = saved["failure"]
                    rejections.pop(key, None)
                    remaining.append(key)
                elif result.get("status") == "rejected_terminal":
                    failures.pop(key, None)
                    rejections[key] = {k: v for k, v in result.items() if k != "status"}
                else:
                    failures.pop(key, None)
                    rejections.pop(key, None)
                    completed += 1
                if progress is not None:
                    progress({**summary(result.get("status", "loaded")), **result,
                              "total_chunks": manifest["requests_estimate"]})
            pending = remaining
            if pending:
                earliest = min(datetime.fromisoformat(failures[key]["retry_after"])
                               for key in pending)
                if not wait_until(earliest):
                    return summary("paused")
    finally:
        con.close()
        if session is None:
            client.close()
    return summary("complete_with_rejections" if rejections else "complete")


def completed_manifest(data_dir: Path) -> str | None:
    """The manifest identity of a clean full capture, or None."""
    payload = _completion(data_dir)
    if payload is None or payload["status"] != "complete":
        return None
    return payload["manifest_sha256"]


def _completion(data_dir: Path) -> dict | None:
    try:
        payload = json.loads((data_dir / COMPLETE_FILE).read_text())
    except (OSError, ValueError):
        return None
    value = payload.get("manifest_sha256") if isinstance(payload, dict) else None
    if not isinstance(value, str) or free_sources.SHA256.fullmatch(value) is None:
        return None
    status = payload.get("status", "complete")
    if status not in {"complete", "complete_with_rejections"}:
        return None
    if status == "complete" and (payload.get("rejections") or payload.get("rejected_terminal_chunks")):
        return None
    return {**payload, "status": status}


def _mark_complete(data_dir: Path, result: dict) -> None:
    payload = {"manifest_sha256": result["manifest_sha256"],
               "status": result["status"],
               "completed_chunks": result["completed_chunks"],
               "completed_at": datetime.now(timezone.utc).isoformat()}
    if result["status"] == "complete_with_rejections":
        payload.update(rejected_terminal_chunks=result["rejected_terminal_chunks"],
                       rejections=result["rejections"])
    daily_capture._write_private_atomic(
        data_dir / COMPLETE_FILE, (json.dumps(payload, sort_keys=True) + "\n").encode()
    )


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
    parser.add_argument("--retry-terminal", action="store_true",
                        help="retry terminal chunks, retaining their earlier decision evidence")
    parser.add_argument("--max-runtime-hours", type=float,
                        help="pause between chunks after this long and exit 75 to resume later")
    args = parser.parse_args(argv)
    if args.max_runtime_hours is not None and not args.max_runtime_hours > 0:
        parser.error("--max-runtime-hours must be positive")
    try:
        manifest = prepare_manifest(
            daily_database=args.daily_database, data_dir=args.data_dir,
            priority_tickers_path=args.priority_tickers,
            priority_json_path=args.priority_json,
        )
        print(json.dumps(_summary(manifest), sort_keys=True), flush=True)
        if args.prepare_only:
            return 0
        completion = _completion(args.data_dir)
        if (completion is not None and completion["manifest_sha256"] == manifest["manifest_sha256"]
                and not args.retry_terminal):
            print(json.dumps({**completion, "reason": "capture already complete"},
                             sort_keys=True), flush=True)
            return 0
        if args.retry_terminal:
            # A paused operator retry must not leave a stale marker stopping the unit.
            (args.data_dir / COMPLETE_FILE).unlink(missing_ok=True)
        api_key = daily_capture._load_massive_key()
        result = capture_manifest(
            manifest, database=args.database, data_dir=args.data_dir, api_key=api_key,
            progress=lambda item: print(json.dumps(item, sort_keys=True), flush=True),
            max_runtime_seconds=(None if args.max_runtime_hours is None
                                 else args.max_runtime_hours * 3600),
            retry_terminal=args.retry_terminal,
        )
        if result["status"] in {"complete", "complete_with_rejections"}:
            _mark_complete(args.data_dir, result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if result["status"] == "paused":
            return EXIT_PAUSED
        if result["status"] == "incomplete":
            return EXIT_INCOMPLETE
    except free_sources.FreeSourceError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
