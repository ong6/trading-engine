"""Bounded forward SEC submissions capture with exact acceptance timestamps."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from datetime import time as day_time
from pathlib import Path
from typing import Callable

import duckdb
import requests

from engine import bitemporal_facts
from engine.lib import db
from engine.lib.settings import DEFAULT_DB
from engine.lib.util import table_exists

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SOURCE_VERSION = "sec_submissions_v1"
MAX_TICKERS = 5
REQUEST_DELAY_SECONDS = 0.15
FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A",
                   "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"})
TICKER = re.compile(r"^[A-Z0-9.^=-]{1,32}$")
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class SecCaptureError(RuntimeError):
    """An SEC response or filing record is unusable."""


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str
    status_code: int
    requested_at: datetime
    received_at: datetime


Fetch = Callable[[str], Response]


def _user_agent() -> str:
    value = os.environ.get("TRADING_ENGINE_SEC_USER_AGENT", "")
    if (not value.strip() or len(value) > 200 or not value.isprintable()
            or "@" not in value or " " not in value.strip()):
        raise SecCaptureError("TRADING_ENGINE_SEC_USER_AGENT contact identity is required")
    return value


def _fetch(url: str) -> Response:
    requested_at = datetime.now(timezone.utc)
    try:
        response = requests.get(
            url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise SecCaptureError("SEC request failed") from exc
    return Response(bytes(response.content), response.headers.get("content-type", ""),
                    int(response.status_code), requested_at, datetime.now(timezone.utc))


def _safe_fetch(fetch: Fetch, url: str) -> Response:
    try:
        return fetch(url)
    except (OSError, requests.RequestException, SecCaptureError) as exc:
        raise SecCaptureError("SEC request failed") from exc


def _payload(response: Response) -> dict:
    if (response.status_code != 200
            or not response.content_type.lower().startswith("application/json")
            or not response.body or len(response.body) > bitemporal_facts.MAX_RAW_BYTES):
        raise SecCaptureError("SEC response metadata is invalid")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SecCaptureError("SEC response JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SecCaptureError("SEC response shape is invalid")
    return payload


def ticker_map(response: Response) -> dict[str, dict]:
    payload = _payload(response)
    result = {}
    for item in payload.values():
        if not isinstance(item, dict):
            raise SecCaptureError("SEC ticker mapping shape is invalid")
        ticker, cik, title = item.get("ticker"), item.get("cik_str"), item.get("title")
        if (not isinstance(ticker, str) or TICKER.fullmatch(ticker.upper()) is None
                or isinstance(cik, bool) or not isinstance(cik, int) or cik <= 0
                or not isinstance(title, str) or not title.strip()):
            raise SecCaptureError("SEC ticker mapping value is invalid")
        key = ticker.upper()
        value = {"ticker": key, "cik": f"{cik:010d}", "title": title.strip()}
        if key in result and result[key] != value:
            raise SecCaptureError("SEC ticker mapping is ambiguous")
        result[key] = value
    return result


def filing_facts(response: Response, ticker: str, cik: str) -> list[dict]:
    payload = _payload(response)
    if str(payload.get("cik", "")).zfill(10) != cik:
        raise SecCaptureError("SEC submission CIK differs from request")
    recent = payload.get("filings", {}).get("recent")
    fields = ("accessionNumber", "filingDate", "reportDate",
              "acceptanceDateTime", "form", "primaryDocument")
    if not isinstance(recent, dict) or any(not isinstance(recent.get(field), list) for field in fields):
        raise SecCaptureError("SEC recent filings shape is invalid")
    lengths = {len(recent[field]) for field in fields}
    if len(lengths) != 1:
        raise SecCaptureError("SEC recent filing arrays differ in length")
    facts = []
    for index, form in enumerate(recent["form"]):
        if form not in FORMS:
            continue
        accession = recent["accessionNumber"][index]
        try:
            filing_date = date.fromisoformat(recent["filingDate"][index])
            report_raw = recent["reportDate"][index]
            report_date = filing_date if not report_raw else date.fromisoformat(report_raw)
            accepted = datetime.fromisoformat(
                recent["acceptanceDateTime"][index].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (AttributeError, TypeError, ValueError) as exc:
            raise SecCaptureError("SEC filing timestamp is invalid") from exc
        primary = recent["primaryDocument"][index]
        if (not isinstance(accession, str) or ACCESSION.fullmatch(accession) is None
                or not isinstance(primary, str) or not primary or "/" in primary
                or accepted.date() != filing_date or report_date > filing_date):
            raise SecCaptureError("SEC filing identity is invalid")
        facts.append({
            "ticker": ticker, "cik": cik, "accession": accession, "form": form,
            "filing_date": filing_date.isoformat(), "report_date": report_date.isoformat(),
            "acceptance_datetime": accepted.isoformat(), "primary_document": primary,
            "archive_url": ("https://www.sec.gov/Archives/edgar/data/"
                            f"{int(cik)}/{accession.replace('-', '')}/{primary}"),
        })
    return facts


def _retain_response(
    con: duckdb.DuckDBPyConnection, response: Response, *, endpoint: str, dataset: str, request: dict,
) -> dict:
    return bitemporal_facts.record_receipt(
        con, source="sec_edgar", dataset=dataset, endpoint=endpoint, request=request,
        requested_at=response.requested_at, received_at=response.received_at,
        http_status=response.status_code, content_type=response.content_type or "application/octet-stream",
        body=response.body, license_class="us-government-public-data",
    )


def capture(
    con: duckdb.DuckDBPyConnection, tickers: list[str], *, fetch: Fetch = _fetch,
    sleep: Callable[[float], None] = time.sleep, ingested_at: datetime | None = None,
) -> dict:
    """Capture current ticker identity and recent material filings for a bounded set."""
    wanted = sorted(set(tickers))
    if len(wanted) > MAX_TICKERS or any(TICKER.fullmatch(item) is None for item in wanted):
        raise SecCaptureError("SEC ticker scope is invalid")
    bitemporal_facts.init_schema(con)
    try:
        map_response = _safe_fetch(fetch, TICKERS_URL)
    except SecCaptureError as exc:
        return {
            "status": "failed", "ticker_count": len(wanted), "request_count": 1,
            "filing_fact_count": 0, "failures": [{"ticker": None, "reason": str(exc)}],
            "historical_membership_authority": False, "execution_authority": "none",
        }
    with db.transaction(con):
        map_receipt = _retain_response(
            con, map_response, endpoint=TICKERS_URL, dataset="sec_current_ticker_map", request={}
        )
    try:
        mapping = ticker_map(map_response)
    except SecCaptureError as exc:
        return {
            "status": "failed", "ticker_count": len(wanted), "request_count": 1,
            "filing_fact_count": 0,
            "failures": [{"ticker": None, "reason": str(exc),
                          "receipt_sha256": map_receipt["receipt_sha256"]}],
            "historical_membership_authority": False, "execution_authority": "none",
        }
    with db.transaction(con):
        for ticker in wanted:
            item = mapping.get(ticker)
            if item is None:
                continue
            bitemporal_facts.record_fact(
                con, entity_id=f"sec-cik:{item['cik']}", security_id=ticker,
                fact_type="sec.current_ticker_mapping", event_at=map_response.received_at,
                published_at=None, available_at=map_response.received_at,
                ingested_at=ingested_at or datetime.now(timezone.utc), payload={**item,
                    "historical_membership_authority": False}, source="sec_edgar",
                source_version=SOURCE_VERSION, receipt_sha256=map_receipt["receipt_sha256"],
            )
    filings, failures, requests = 0, [], 1
    for ticker in wanted:
        item = mapping.get(ticker)
        if item is None:
            failures.append({"ticker": ticker, "reason": "ticker absent from current SEC map"})
            continue
        endpoint = SUBMISSIONS_URL.format(cik=item["cik"])
        sleep(REQUEST_DELAY_SECONDS)
        try:
            response = _safe_fetch(fetch, endpoint)
        except SecCaptureError as exc:
            failures.append({"ticker": ticker, "reason": str(exc)})
            continue
        requests += 1
        try:
            facts = filing_facts(response, ticker, item["cik"])
        except SecCaptureError as exc:
            with db.transaction(con):
                receipt = _retain_response(
                    con, response, endpoint=endpoint, dataset="sec_submissions",
                    request={"cik": item["cik"]},
                )
            failures.append({"ticker": ticker, "reason": str(exc),
                             "receipt_sha256": receipt["receipt_sha256"]})
            continue
        with db.transaction(con):
            receipt = _retain_response(
                con, response, endpoint=endpoint, dataset="sec_submissions",
                request={"cik": item["cik"]},
            )
            for fact in facts:
                accepted = datetime.fromisoformat(fact["acceptance_datetime"])
                event = datetime.combine(date.fromisoformat(fact["report_date"]), day_time.min,
                                         tzinfo=timezone.utc)
                bitemporal_facts.record_fact(
                    con, entity_id=f"sec-cik:{item['cik']}", security_id=ticker,
                    fact_type=f"sec.filing:{fact['accession']}", event_at=event,
                    published_at=accepted, available_at=response.received_at,
                    ingested_at=ingested_at or datetime.now(timezone.utc), payload=fact,
                    source="sec_edgar", source_version=SOURCE_VERSION,
                    receipt_sha256=receipt["receipt_sha256"],
                )
                filings += 1
    return {"status": "complete" if not failures else "partial",
            "ticker_count": len(wanted), "request_count": requests,
            "filing_fact_count": filings, "failures": failures,
            "historical_membership_authority": False, "execution_authority": "none"}


def _latest_tickers(con) -> list[str]:
    if not table_exists(con, "daily_opportunity_runs"):
        return []
    row = con.execute(
        "SELECT id FROM daily_opportunity_runs WHERE status='completed' "
        "ORDER BY market_date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return []
    return [item[0] for item in con.execute(
        "SELECT ticker FROM daily_opportunity_assessments WHERE run_id=? ORDER BY id LIMIT ?",
        [row[0], MAX_TICKERS],
    ).fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--tickers", default=None, help="comma-separated bounded override")
    args = parser.parse_args(argv)
    con = db.connect(args.database, wait_s=0)
    try:
        tickers = ([item.strip().upper() for item in args.tickers.split(",") if item.strip()]
                   if args.tickers is not None else _latest_tickers(con))
        if not tickers:
            result = {"status": "waiting", "ticker_count": 0,
                      "historical_membership_authority": False,
                      "execution_authority": "none"}
        else:
            result = capture(con, tickers)
    finally:
        con.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"complete", "waiting"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
