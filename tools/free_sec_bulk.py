#!/usr/bin/env python3
"""Capture and audit SEC Companyfacts and Submissions nightly bulk archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from engine import free_sec_bulk, free_sources
from engine.lib import db
from engine.lib.resources import write_text_atomic
from tools.free_sec import _load_contact
from tools.free_sources import _network_permitted

COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SUBMISSION_PAGE_URL = "https://data.sec.gov/submissions/{name}"
REQUEST_INTERVAL_SECONDS = 0.2
HTTP_TIMEOUT_SECONDS = 120
MAX_DOWNLOAD_BYTES = 16_000_000_000
CHUNK_BYTES = 2 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def default_database() -> Path:
    return Path(os.environ.get(
        "TRADING_ENGINE_SEC_BULK_DB",
        Path.home() / "trading-engine/store/pit/sec-bulk.duckdb",
    )).expanduser()


def default_data_dir() -> Path:
    return Path(os.environ.get(
        "TRADING_ENGINE_SEC_BULK_DIR",
        Path.home() / "trading-engine/store/pit/sec-bulk",
    )).expanduser()


def default_free_database() -> Path:
    return Path(os.environ.get(
        "TRADING_ENGINE_FREE_SOURCES_DB",
        Path.home() / "trading-engine/store/pit/free-sources.duckdb",
    )).expanduser()


def default_market_snapshot() -> Path:
    return Path(os.environ.get(
        "TRADING_ENGINE_MARKET_SNAPSHOT",
        Path.home() / "trading-engine/store/snapshots/market-latest.duckdb",
    )).expanduser()


def _private_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as out:
            temporary = Path(out.name)
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Download:
    path: Path
    source_sha256: str
    size: int
    resumed: bool


class BulkClient:
    """Sequential fair-access client with content-addressed, range-resumable files."""

    def __init__(
        self, contact: str, data_dir: Path, *, session: requests.Session | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not contact or not isinstance(contact, str):
            raise free_sources.FreeSourceError("SEC contact identity is missing")
        self.contact, self.data_dir = contact, data_dir
        self.session, self.now = session or requests.Session(), now
        self._owns_session = session is None
        self.monotonic, self.sleep = monotonic, sleep
        self.last_started: float | None = None

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.contact,
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    def _pace(self) -> None:
        if not _network_permitted(self.now()):
            raise free_sources.FreeSourceError("SEC bulk request is inside a configured no-call window")
        if self.last_started is not None:
            remaining = REQUEST_INTERVAL_SECONDS - (self.monotonic() - self.last_started)
            if remaining > 0:
                self.sleep(remaining)
        if not _network_permitted(self.now()):
            raise free_sources.FreeSourceError("SEC bulk request reached a configured no-call window")
        self.last_started = self.monotonic()

    def head(self, url: str) -> dict:
        self._pace()
        try:
            response = self.session.head(
                url, headers=self._headers(), timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=True,
            )
            status = int(response.status_code)
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise free_sources.FreeSourceError("SEC bulk HEAD request failed") from exc
        if status != 200:
            raise free_sources.FreeSourceError(f"SEC bulk HEAD returned HTTP {status}")
        try:
            size = int(response.headers.get("Content-Length", 0)) or None
        except (TypeError, ValueError) as exc:
            raise free_sources.FreeSourceError("SEC bulk HEAD length is invalid") from exc
        if size is not None and not 0 < size <= MAX_DOWNLOAD_BYTES:
            raise free_sources.FreeSourceError("SEC bulk HEAD length is outside the limit")
        return {
            "url": url, "size": size, "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    def _directory(self, url: str) -> Path:
        return self.data_dir / hashlib.sha256(url.encode()).hexdigest()

    def _cached(self, url: str, suffix: str) -> Download | None:
        receipt_path = self._directory(url) / "receipt.json"
        if not receipt_path.exists():
            return None
        try:
            receipt = json.loads(receipt_path.read_text())
            source_sha = receipt["source_sha256"]
            if (receipt["url"] != url or not SHA256.fullmatch(source_sha)
                    or receipt["size"] <= 0):
                raise ValueError
            path = receipt_path.parent / f"{source_sha}{suffix}"
            if path.is_symlink() or not path.is_file() or path.stat().st_size != receipt["size"]:
                raise ValueError
            if _file_sha256(path) != source_sha:
                raise ValueError
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise free_sources.FreeSourceError("SEC bulk cache receipt is invalid") from exc
        return Download(path, source_sha, receipt["size"], True)

    def download(self, url: str, *, suffix: str) -> Download:
        """Download one URL, preserving an interrupted partial for a later Range request."""
        cached = self._cached(url, suffix)
        if cached is not None:
            return cached
        directory = self._directory(url)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        partial, state_path = directory / "download.part", directory / "partial.json"
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > MAX_DOWNLOAD_BYTES:
            raise free_sources.FreeSourceError("SEC bulk partial exceeds the download limit")
        if offset and not state_path.is_file():
            raise free_sources.FreeSourceError("SEC bulk partial has no resume metadata")
        headers = self._headers()
        if offset:
            headers["Range"] = f"bytes={offset}-"
        self._pace()
        try:
            response = self.session.get(
                url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS,
                allow_redirects=True, stream=True,
            )
            status = int(response.status_code)
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise free_sources.FreeSourceError("SEC bulk download request failed") from exc
        if status not in ({206} if offset else {200}):
            response.close()
            raise free_sources.FreeSourceError(f"SEC bulk download returned HTTP {status}")
        content_range = response.headers.get("Content-Range")
        total = None
        if offset:
            match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", content_range or "")
            if match is None or int(match.group(1)) != offset:
                response.close()
                raise free_sources.FreeSourceError("SEC bulk resume range is invalid")
            total = int(match.group(3))
        else:
            try:
                total = int(response.headers.get("Content-Length", 0)) or None
            except (TypeError, ValueError) as exc:
                response.close()
                raise free_sources.FreeSourceError("SEC bulk download length is invalid") from exc
        if total is not None and not 0 < total <= MAX_DOWNLOAD_BYTES:
            response.close()
            raise free_sources.FreeSourceError("SEC bulk download length is outside the limit")
        _private_atomic(state_path, json.dumps({"url": url, "total": total}).encode() + b"\n")
        mode = "ab" if offset else "wb"
        try:
            with partial.open(mode) as output:
                partial.chmod(0o600)
                for chunk in response.iter_content(CHUNK_BYTES):
                    if not _network_permitted(self.now()):
                        raise free_sources.FreeSourceError(
                            "SEC bulk download reached a configured no-call window"
                        )
                    if chunk:
                        output.write(chunk)
                        if output.tell() > MAX_DOWNLOAD_BYTES:
                            raise free_sources.FreeSourceError(
                                "SEC bulk download exceeds the size limit"
                            )
                output.flush()
                os.fsync(output.fileno())
        except requests.RequestException as exc:
            raise free_sources.FreeSourceError("SEC bulk download was interrupted") from exc
        finally:
            response.close()
        size = partial.stat().st_size
        if total is not None and size != total:
            raise free_sources.FreeSourceError("SEC bulk download ended before its declared length")
        source_sha = _file_sha256(partial)
        path = directory / f"{source_sha}{suffix}"
        if path.exists():
            if path.is_symlink() or not path.is_file() or _file_sha256(path) != source_sha:
                raise free_sources.FreeSourceError("SEC bulk content cache conflicts")
            partial.unlink()
        else:
            os.replace(partial, path)
            path.chmod(0o600)
        receipt = {
            "url": url, "source_sha256": source_sha, "size": size,
            "fetched_at": self.now().isoformat(),
        }
        _private_atomic(
            directory / "receipt.json",
            json.dumps(receipt, sort_keys=True).encode() + b"\n",
        )
        state_path.unlink(missing_ok=True)
        return Download(path, source_sha, size, bool(offset))


def verify_urls(client: BulkClient) -> list[dict]:
    return [client.head(url) for url in (COMPANYFACTS_URL, SUBMISSIONS_URL)]


def capture(
    *, database: Path, data_dir: Path, free_database: Path,
    client: BulkClient,
) -> dict:
    """Download and load submissions, every referenced old page, then Companyfacts."""
    verified = verify_urls(client)
    submissions = client.download(SUBMISSIONS_URL, suffix=".zip")
    database.parent.mkdir(parents=True, exist_ok=True)
    con = db.connect(database, wait_s=0)
    try:
        submission_result = free_sec_bulk.load_submissions_zip(
            con, submissions.path, source_sha256=submissions.source_sha256,
        )
        pages = free_sec_bulk.pending_submission_pages(con)
        page_totals = {"requested": len(pages), "loaded": 0, "filings": 0, "events_inserted": 0}
        for name, cik in pages:
            page = client.download(SUBMISSION_PAGE_URL.format(name=name), suffix=".json")
            result = free_sec_bulk.load_submission_page(
                con, page.path, name=name, cik=cik, source_sha256=page.source_sha256,
            )
            page_totals["loaded"] += 1
            page_totals["filings"] += result["filings"]
            page_totals["events_inserted"] += result["events_inserted"]
    finally:
        con.close()
    companyfacts = client.download(COMPANYFACTS_URL, suffix=".zip")
    con = db.connect(database, wait_s=0)
    try:
        facts_result = free_sec_bulk.load_companyfacts_zip(
            con, companyfacts.path, source_sha256=companyfacts.source_sha256,
        )
        ticker_result = free_sec_bulk.copy_ticker_history(con, free_database)
    finally:
        con.close()
    return {
        "verified": verified, "submissions": submission_result,
        "submission_pages": page_totals, "companyfacts": facts_result,
        "ticker_history": ticker_result, "database": str(database),
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def render_audit(result: dict) -> str:
    lines = [
        "# SEC bulk point-in-time audit — 2026-10-02", "",
        "## Method", "",
        "The two official nightly bulk ZIPs and every older submissions page were cached",
        "outside Git by URL and SHA-256. Facts are available at the matching accession's",
        "timezone-aware SEC acceptance timestamp; unmatched accessions become available only",
        "at the end of their filing date in America/New_York. Restated accessions remain",
        "separate source rows. Tickers come from the read-only `free_cik_ticker_history` view.", "",
        "Tag fallbacks, in priority order, are:", "",
    ]
    for concept, tags in free_sec_bulk.CONCEPT_TAGS.items():
        lines.append(f"- `{concept}`: " + ", ".join(f"`{taxonomy}:{tag}`" for taxonomy, tag in tags))
    lines += ["", "## Fundamental coverage", "",
              "| Year | Facts | Companies |", "|---:|---:|---:|"]
    lines.extend(
        f"| {row['year']} | {row['facts']:,} | {row['companies']:,} |"
        for row in result["facts_by_year"]
    )
    lines += ["", "## Earnings events", "", "| Year | 8-K item 2.02 events |", "|---:|---:|"]
    lines.extend(
        f"| {row['year']} | {row['events']:,} |" for row in result["earnings_events_by_year"]
    )
    ticker, overlap = result["ticker_match"], result["earnings_overlap"]
    lines += [
        "", "## Mapping and overlap", "",
        f"- Combined fact/event ticker match: {ticker['matched']:,}/{ticker['total']:,} "
        f"({_percent(ticker['share'])}).",
        f"- Fundamental ticker match: {ticker['facts_matched']:,}/{ticker['facts_total']:,}; "
        f"earnings-event ticker match: {ticker['events_matched']:,}/{ticker['events_total']:,}.",
        f"- SEC earnings events within ±1 calendar day of an existing engine earnings date: "
        f"{overlap['matched']:,}/{overlap['total']:,} ({_percent(overlap['share'])}); "
        f"{overlap['ticker_mapped']:,} events had a ticker mapping.", "",
        "The overlap denominator is every SEC item 2.02 event, so an unmapped CIK cannot count",
        "as an overlap. The engine snapshot was attached read-only and was not modified.", "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--database", type=Path, default=default_database())
    capture_parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    capture_parser.add_argument("--free-database", type=Path, default=default_free_database())
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--database", type=Path, default=default_database())
    audit_parser.add_argument("--free-database", type=Path, default=default_free_database())
    audit_parser.add_argument("--market-snapshot", type=Path, default=default_market_snapshot())
    audit_parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    client = None
    try:
        if args.command == "capture":
            contact = _load_contact()
            client = BulkClient(contact, args.data_dir)
            result = capture(
                database=args.database, data_dir=args.data_dir,
                free_database=args.free_database, client=client,
            )
        else:
            result = free_sec_bulk.audit(
                args.database, args.free_database, args.market_snapshot,
            )
            if args.output:
                write_text_atomic(args.output, render_audit(result))
    except (OSError, ValueError, duckdb.Error) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    finally:
        if client is not None:
            client.close()
    print(json.dumps({"status": "complete", **result}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
