"""Bounded exact-response Yahoo headline capture for P8 research context."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from engine.lib.provenance import canonical_sha256

ENDPOINT = "https://query2.finance.yahoo.com/v1/finance/search"
MAX_RESPONSE_BYTES = 262_144
MAX_HEADLINES = 3
MAX_AGE = timedelta(days=3)


class NewsError(RuntimeError):
    """A headline response could not be retained or interpreted safely."""


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str
    status_code: int
    requested_at: datetime
    received_at: datetime


Fetch = Callable[[str, datetime], Response]


def _fetch(ticker: str, now: datetime) -> Response:
    try:
        from yfinance.data import YfData

        response = YfData().get(
            ENDPOINT,
            params={"q": ticker, "quotesCount": 0, "newsCount": MAX_HEADLINES},
            timeout=20,
        )
    except Exception as exc:
        raise NewsError("headline request failed") from exc
    return Response(
        bytes(response.content),
        response.headers.get("content-type", ""),
        int(response.status_code),
        now,
        datetime.now(timezone.utc),
    )


def _timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.utcoffset() is None:
        raise NewsError("headline timestamp is invalid")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(ticker: str, response: Response) -> tuple[dict, list[dict]]:
    content_type = response.content_type.split(";", 1)[0].strip().lower()
    if response.status_code != 200 or content_type != "application/json":
        raise NewsError("headline response metadata is invalid")
    if not response.body or len(response.body) > MAX_RESPONSE_BYTES:
        raise NewsError("headline response size is invalid")
    try:
        payload = json.loads(response.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise NewsError("headline response JSON is invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
        raise NewsError("headline response shape is invalid")
    received = response.received_at.astimezone(timezone.utc)
    response_sha256 = hashlib.sha256(response.body).hexdigest()
    receipt_body = {
        "ticker": ticker,
        "endpoint": ENDPOINT,
        "requested_at": _timestamp(response.requested_at),
        "received_at": _timestamp(response.received_at),
        "http_status": response.status_code,
        "content_type": response.content_type,
        "response_sha256": response_sha256,
    }
    receipt = {
        **receipt_body,
        "response_body": response.body,
        "receipt_sha256": canonical_sha256(receipt_body),
    }
    observations = []
    for item in payload["news"][:MAX_HEADLINES]:
        if not isinstance(item, dict):
            continue
        title, link, publisher, epoch = (
            item.get("title"), item.get("link"), item.get("publisher"),
            item.get("providerPublishTime"),
        )
        if (
            not isinstance(title, str) or not title.strip() or len(title) > 500
            or not isinstance(link, str) or not link.startswith("https://") or len(link) > 2048
            or not isinstance(publisher, str) or not publisher.strip() or len(publisher) > 200
            or isinstance(epoch, bool) or not isinstance(epoch, int)
        ):
            continue
        published = datetime.fromtimestamp(epoch, timezone.utc)
        if published > received + timedelta(minutes=5) or received - published > MAX_AGE:
            continue
        body = {
            "ticker": ticker,
            "title": title.strip(),
            "publisher": publisher.strip(),
            "url": link,
            "published_at": _timestamp(published),
            "retrieved_at": _timestamp(response.received_at),
            "text_sha256": hashlib.sha256(title.strip().encode()).hexdigest(),
            "response_sha256": response_sha256,
            "receipt_sha256": receipt["receipt_sha256"],
        }
        observations.append({**body, "evidence_id": canonical_sha256(body)})
    return receipt, observations


def capture(tickers: list[str], *, now: datetime, fetch: Fetch = _fetch) -> dict:
    receipts, observations, failures = [], [], []
    for ticker in sorted(set(tickers)):
        try:
            receipt, items = _parse(ticker, fetch(ticker, now))
            receipts.append(receipt)
            observations.extend(items)
        except (NewsError, OSError, ValueError) as exc:
            failures.append({"ticker": ticker, "reason": str(exc)[:200]})
    status = "unavailable" if not receipts else ("partial" if failures else "available")
    return {
        "status": status, "receipts": receipts,
        "observations": observations, "failures": failures,
    }
