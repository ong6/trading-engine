"""Bounded SEC transport and deterministic W3/W4 discovery helpers."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from engine import p16_filing_parser
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

MIN_START_SPACING_SECONDS = 0.25
MAX_SCAN_STARTS = 240
MAX_SCAN_SECONDS = 240
MAX_RESPONSE_BYTES = 2_000_000
MAX_BUNDLE_BYTES = 8_000_000
MAX_MAP_AGE = timedelta(days=7)
DEFAULT_PAUSE_SECONDS = 600
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 20
DISPATCH_LOCK = REPO_ROOT / ".sec-dispatch.lock"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
TICKER = re.compile(r"[A-Z0-9.^=-]{1,32}")


class SecUnavailable(RuntimeError):
    """A bounded SEC request cannot start or cannot be trusted."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SecRequest:
    request_id: str
    scan_id: str
    consumer: str
    kind: str
    url: str
    attempt: int
    not_before: datetime
    scan_started_at: datetime


@dataclass(frozen=True)
class SecResponse:
    status_code: int
    content_type: str
    headers: dict[str, str]
    body: bytes
    requested_at: datetime
    received_at: datetime
    final_url: str
    observed_size_bytes: int
    complete: bool


@dataclass(frozen=True)
class Verified304:
    body: bytes
    body_sha256: str


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp requires an explicit offset")
    return parsed.astimezone(timezone.utc)


def configured_user_agent(environ: Mapping[str, str] | None = None) -> str | None:
    value = (os.environ if environ is None else environ).get("TRADING_ENGINE_SEC_USER_AGENT", "")
    if (not value.strip() or value != value.strip() or len(value) > 200
            or not value.isprintable() or " " not in value or
            re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", value) is None):
        return None
    return value


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.query or parsed.fragment):
        raise SecUnavailable("invalid_sec_url")
    if parsed.netloc == "www.sec.gov" and parsed.path == "/files/company_tickers.json":
        return
    if parsed.netloc == "data.sec.gov" and re.fullmatch(r"/submissions/CIK[0-9]{10}\.json", parsed.path):
        return
    if parsed.netloc == "www.sec.gov" and re.fullmatch(
            r"/Archives/edgar/data/[0-9]{1,10}/[0-9]{18}/[A-Za-z0-9][A-Za-z0-9_.-]{0,199}",
            parsed.path):
        return
    raise SecUnavailable("invalid_sec_url")


def archive_url(cik: str | int, accession: str, basename: str | None = None) -> str:
    normalized_cik = p16_filing_parser.cik_id(cik)
    if not isinstance(accession, str) or ACCESSION.fullmatch(accession) is None:
        raise ValueError("invalid accession")
    filename = p16_filing_parser.safe_filename(basename or f"{accession}-index.htm")
    url = ("https://www.sec.gov/Archives/edgar/data/"
           f"{int(normalized_cik)}/{accession.replace('-', '')}/{filename}")
    _validate_url(url)
    return url


def submissions_url(cik: str | int) -> str:
    return SUBMISSIONS_URL.format(cik=p16_filing_parser.cik_id(cik))


def _http_fetch(url: str, user_agent: str) -> SecResponse:
    requested_at = datetime.now(timezone.utc)
    raw = None
    try:
        raw = requests.get(
            url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS), stream=True,
            allow_redirects=False,
        )
        body, observed, complete = bytearray(), 0, True
        for chunk in raw.iter_content(64 * 1024):
            observed += len(chunk)
            remaining = MAX_RESPONSE_BYTES - len(body)
            if remaining > 0:
                body.extend(chunk[:remaining])
            if observed > MAX_RESPONSE_BYTES:
                complete = False
                break
    except (OSError, requests.RequestException) as exc:
        raise SecUnavailable("request_failed") from exc
    finally:
        if raw is not None:
            raw.close()
    return SecResponse(int(raw.status_code), raw.headers.get("content-type", ""),
                       {str(key): str(value) for key, value in raw.headers.items()}, bytes(body),
                       requested_at, datetime.now(timezone.utc), str(raw.url), observed, complete)


def _event(request: SecRequest, kind: str, at: datetime, **values) -> dict:
    return {
        "request_id": request.request_id, "scan_id": request.scan_id,
        "scan_started_at": _utc(request.scan_started_at).isoformat(), "consumer": request.consumer,
        "request_kind": request.kind, "attempt": request.attempt,
        "event_kind": kind, "event_at": at.isoformat(),
        "url_sha256": hashlib.sha256(request.url.encode()).hexdigest(), **values,
    }


def _retry_state(response: SecResponse, now: datetime, state: dict) -> dict | None:
    if response.status_code not in {403, 429}:
        return None
    headers = {key.casefold(): value for key, value in response.headers.items()}
    raw = headers.get("retry-after", "")
    pause = None
    try:
        pause = now + timedelta(seconds=int(raw)) if raw else None
    except ValueError:
        try:
            pause = parsedate_to_datetime(raw).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    reason = f"http_{response.status_code}"
    if response.status_code == 403 and int(state.get("session_403_count", 0)) >= 1:
        next_session = state.get("next_session_at")
        if not next_session:
            return {"pause_until": None, "reason": "repeated_403_calendar_unavailable",
                    "blocked": True, "alert": True}
        try:
            next_session = _utc(next_session)
        except (TypeError, ValueError, AttributeError):
            return {"pause_until": None, "reason": "repeated_403_calendar_unavailable",
                    "blocked": True, "alert": True}
        if next_session <= now:
            return {"pause_until": None, "reason": "repeated_403_calendar_unavailable",
                    "blocked": True, "alert": True}
        pause = max(value for value in (pause, next_session) if value is not None)
        reason = "repeated_403"
    if pause is None or pause <= now:
        pause = now + timedelta(seconds=DEFAULT_PAUSE_SECONDS)
    return {"pause_until": pause.isoformat(), "reason": reason,
            "blocked": False, "alert": response.status_code == 403}


def _validate_request(request: SecRequest) -> None:
    if (not isinstance(request.request_id, str) or not request.request_id
            or not isinstance(request.scan_id, str) or not request.scan_id
            or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", request.consumer)
            or not re.fullmatch(r"[a-z_]{1,32}", request.kind)
            or isinstance(request.attempt, bool) or not 1 <= request.attempt <= 4):
        raise SecUnavailable("invalid_request")
    _utc(request.not_before)
    _utc(request.scan_started_at)
    _validate_url(request.url)


def _validate_response(response: SecResponse, request: SecRequest) -> None:
    if (not isinstance(response, SecResponse) or response.final_url != request.url
            or (300 <= response.status_code < 400 and response.status_code != 304)
            or response.observed_size_bytes < len(response.body)
            or len(response.body) > MAX_RESPONSE_BYTES
            or (response.complete and response.observed_size_bytes != len(response.body))
            or (not response.complete and
                (len(response.body) != MAX_RESPONSE_BYTES
                 or response.observed_size_bytes <= MAX_RESPONSE_BYTES))
            or _utc(response.received_at) < _utc(response.requested_at)):
        raise SecUnavailable("invalid_response")


@contextmanager
def _dispatcher_state(path: str | Path):
    """Lock and expose the host-wide minimum dispatcher state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read()
            state = json.loads(raw) if raw else {}
            if not isinstance(state, dict):
                raise SecUnavailable("invalid_dispatch_state")
            yield handle, state
        except json.JSONDecodeError as exc:
            raise SecUnavailable("invalid_dispatch_state") from exc
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _save_dispatch_state(handle, state: dict) -> None:
    handle.seek(0)
    handle.write(json.dumps(state, sort_keys=True, separators=(",", ":")))
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def dispatch(
    request: SecRequest,
    *,
    load_state: Callable[[], dict],
    append_event: Callable[[dict], None],
    fetch: Callable[[str, str], SecResponse] = _http_fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    lock_path: str | Path = DISPATCH_LOCK,
    environ: Mapping[str, str] | None = None,
) -> SecResponse:
    """Serialize every cooperating SEC consumer and persist one bounded attempt."""
    user_agent = configured_user_agent(environ)
    if user_agent is None:
        raise SecUnavailable("unconfigured")
    _validate_request(request)
    with _dispatcher_state(lock_path) as (state_file, shared_state):
        state = load_state()
        now, scan_started = _utc(clock()), _utc(request.scan_started_at)
        try:
            persisted_scan_started = _utc(state["scan_started_at"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SecUnavailable("invalid_scan_state") from exc
        if state.get("scan_id") != request.scan_id or persisted_scan_started != scan_started:
            raise SecUnavailable("invalid_scan_state")
        session_key = scan_started.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if shared_state.get("session_key") != session_key:
            shared_state["session_key"] = session_key
            shared_state["session_403_count"] = 0
        if state.get("blocked") or shared_state.get("blocked"):
            raise SecUnavailable("dispatcher_blocked")
        if now < _utc(request.not_before):
            raise SecUnavailable("not_before")
        pauses = [value for value in (state.get("pause_until"), shared_state.get("pause_until"))
                  if value]
        if pauses and now < max(_utc(value) for value in pauses):
            raise SecUnavailable("dispatcher_paused")
        if int(state.get("scan_starts", 0)) >= MAX_SCAN_STARTS:
            raise SecUnavailable("scan_request_cap")
        if (now - scan_started).total_seconds() >= MAX_SCAN_SECONDS:
            raise SecUnavailable("scan_wall_cap")
        last_started = shared_state.get("last_started_at")
        wait = max(0.0, MIN_START_SPACING_SECONDS - (now - _utc(last_started)).total_seconds()) \
            if last_started else 0.0
        if now + timedelta(seconds=wait) - scan_started >= timedelta(seconds=MAX_SCAN_SECONDS):
            raise SecUnavailable("scan_wall_cap")
        if wait:
            sleep(wait)
        started = _utc(clock())
        if (started - scan_started).total_seconds() >= MAX_SCAN_SECONDS:
            raise SecUnavailable("scan_wall_cap")
        shared_state["last_started_at"] = started.isoformat()
        _save_dispatch_state(state_file, shared_state)
        append_event(_event(request, "started", started))
        if (_utc(clock()) - scan_started).total_seconds() >= MAX_SCAN_SECONDS:
            append_event(_event(request, "failed", _utc(clock()), reason="scan_wall_cap"))
            raise SecUnavailable("scan_wall_cap")
        try:
            response = fetch(request.url, user_agent)
            _validate_response(response, request)
        except Exception as exc:
            append_event(_event(request, "failed", _utc(clock()), reason="invalid_or_failed_response"))
            if isinstance(exc, SecUnavailable):
                raise
            raise SecUnavailable("request_failed") from exc
        received = _utc(response.received_at)
        values = {
            "status_code": response.status_code, "complete": response.complete,
            "observed_size_bytes": response.observed_size_bytes,
            "prefix_sha256": hashlib.sha256(response.body).hexdigest(),
        }
        retry_state = {**state, "session_403_count": max(
            int(state.get("session_403_count", 0)), int(shared_state.get("session_403_count", 0)),
        )}
        retry = _retry_state(response, received, retry_state)
        if retry:
            values.update(retry)
            shared_state.update(retry)
        if response.status_code == 403:
            shared_state["session_403_count"] = retry_state["session_403_count"] + 1
        _save_dispatch_state(state_file, shared_state)
        append_event(_event(request, "response", received, **values))
        if not response.complete:
            raise SecUnavailable("response_oversized")
        return response


@contextmanager
def scan_lease(path: str | Path):
    """Refuse overlapping scans instead of waiting behind an active producer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SecUnavailable("scan_in_progress") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _trusted_json_body(response: SecResponse, verified_304: Verified304 | None) -> tuple[bytes, str]:
    if (response.status_code == 200 and response.complete and response.body
            and response.observed_size_bytes == len(response.body) <= MAX_RESPONSE_BYTES
            and response.content_type.split(";", 1)[0].casefold() == "application/json"):
        return response.body, "fresh_200"
    if (response.status_code == 304 and response.complete and not response.body
            and response.observed_size_bytes == 0 and isinstance(verified_304, Verified304)
            and hashlib.sha256(verified_304.body).hexdigest() == verified_304.body_sha256
            and verified_304.body):
        return verified_304.body, "verified_304"
    raise ValueError("untrusted SEC JSON response")


def parse_submissions(
    response: SecResponse, *, cik: str | int, verified_304: Verified304 | None = None,
) -> dict:
    body, source_status = _trusted_json_body(response, verified_304)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid submissions JSON") from exc
    parsed = p16_filing_parser.parse_submissions(payload, expected_cik=cik)
    return {**parsed, "source_status": source_status,
            "source_body_sha256": hashlib.sha256(body).hexdigest(),
            "received_at": _utc(response.received_at).isoformat()}


def parse_ticker_map(response: SecResponse, *, verified_304: Verified304 | None = None) -> dict:
    body, source_status = _trusted_json_body(response, verified_304)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid ticker map JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid ticker map shape")
    by_cik: dict[str, set[str]] = {}
    for row in payload.values():
        if not isinstance(row, dict):
            raise ValueError("invalid ticker map row")
        ticker, raw_cik = row.get("ticker"), row.get("cik_str")
        if not isinstance(ticker, str) or TICKER.fullmatch(ticker.upper()) is None:
            raise ValueError("invalid ticker map row")
        cik = p16_filing_parser.cik_id(raw_cik)
        by_cik.setdefault(cik, set()).add(ticker.upper())
    received = _utc(response.received_at)
    return {"received_at": received.isoformat(),
            "expires_at": (received + MAX_MAP_AGE).isoformat(),
            "cik_tickers": {cik: sorted(tickers) for cik, tickers in sorted(by_cik.items())},
            "source_status": source_status, "source_body_sha256": hashlib.sha256(body).hexdigest()}


def ticker_map_status(snapshot: dict | None, *, at: datetime) -> str:
    if not snapshot:
        return "map_unavailable"
    try:
        return "ready" if _utc(at) <= _utc(snapshot["expires_at"]) else "map_stale"
    except (KeyError, TypeError, ValueError, AttributeError):
        return "map_unavailable"


def bundle_size_status(responses: list[SecResponse]) -> str:
    if any(not isinstance(item, SecResponse) or not item.complete for item in responses):
        return "response_oversized"
    return ("bundle_oversized" if sum(item.observed_size_bytes for item in responses) > MAX_BUNDLE_BYTES
            else "complete")


def classify_discoveries(
    current: dict,
    *,
    previous_accessions=(),
    known_accessions=(),
    activation_at: datetime,
    cik_entered_at: datetime,
    response_id: str,
    previous_response_id: str | None = None,
) -> list[dict]:
    previous, known = set(previous_accessions), set(known_accessions)
    threshold_at = max(_utc(activation_at), _utc(cik_entered_at))
    threshold = threshold_at.isoformat()
    threshold_date = threshold_at.astimezone(ZoneInfo("America/New_York")).date()
    result = []
    for filing in current.get("filings", ()):
        accession = filing["accession"]
        status = ("already_queued_or_consumed" if accession in known else
                  "present_in_previous_response" if accession in previous else
                  "baseline_inventory" if previous_response_id is None and
                  datetime.strptime(filing["filing_date"], "%Y-%m-%d").date() < threshold_date else
                  "acceptance_pending_crosscheck")
        matched = [item for item in filing["metadata_items"] if item in p16_filing_parser.EVENTS]
        if not matched and status == "acceptance_pending_crosscheck":
            status = "not_requested"
        result.append({
            **filing, "cik": current["cik"], "response_id": response_id,
            "previous_response_id": previous_response_id,
            "previous_accessions_sha256": canonical_sha256(sorted(previous)),
            "activation_at": _utc(activation_at).isoformat(),
            "cik_entered_at": _utc(cik_entered_at).isoformat(),
            "eligibility_threshold": threshold, "matched_items": matched, "status": status,
        })
    return result


def resolve_pending(
    discovery: dict,
    *,
    json_value: str | None = None,
    sgml_value: str | None = None,
    index_value: str | None = None,
    reference_received_at: datetime | None = None,
    normalized_sha256: str | None = None,
    available_at: datetime | None = None,
    prior_facts: list[dict] | None = None,
) -> dict:
    if discovery.get("status") != "acceptance_pending_crosscheck":
        return dict(discovery)
    resolution = p16_filing_parser.resolve_acceptance(
        json_value=json_value, sgml_value=sgml_value, index_value=index_value,
        reference_received_at=reference_received_at,
    )
    if resolution["status"] != "resolved":
        return {**discovery, **resolution}
    resolved = {**discovery, **resolution}
    if normalized_sha256 is None or available_at is None:
        return {**resolved, "status": "bundle_pending"}
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_sha256):
        raise ValueError("invalid normalized identity")
    candidate = {
        **resolved, "entity_id": f"sec-cik:{discovery['cik']}",
        "fact_type": f"sec.filing:{str(discovery['form']).casefold()}",
        "normalized_sha256": normalized_sha256, "available_at": _utc(available_at).isoformat(),
    }
    status = p16_filing_parser.filing_eligibility(
        candidate, prior_facts or [], activation_at=discovery["activation_at"],
        cik_entered_at=discovery["cik_entered_at"],
    )
    return {**candidate, "status": status}


def scheduled_work(document_jobs, cik_jobs):
    """Yield one document then two CIK requests, lending unused slots."""
    documents, ciks = deque(document_jobs), deque(cik_jobs)
    while documents or ciks:
        if documents:
            yield documents.popleft()
        for _ in range(2):
            if ciks:
                yield ciks.popleft()
        if not ciks:
            while documents:
                yield documents.popleft()
