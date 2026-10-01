#!/usr/bin/env python3
"""Capture and audit P3's isolated free SEC history."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import duckdb
import requests

from engine import free_sec, free_sources
from engine.lib import db
from engine.lib.resources import write_text_atomic
from tools.free_sources import _network_permitted

CONTACT_PATH = Path.home() / ".config/trading-engine/sec.env"
FORM_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml"
INSIDER_PAGE_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
INSIDER_URL = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
    "{year}q{quarter}_form345.zip"
)
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FIRST_FORM_YEAR, LAST_YEAR, LAST_QUARTER = 1996, 2026, 3
FIRST_INSIDER_YEAR = 2006
REQUEST_INTERVAL_SECONDS = 0.2
HTTP_TIMEOUT_SECONDS = 90
MAX_HTTP_BYTES = free_sec.MAX_ZIP_BYTES
CONTACT_NAME = "TRADING_ENGINE_SEC_USER_AGENT"


def _quarters(first_year: int) -> list[tuple[int, int]]:
    return [(year, quarter) for year in range(first_year, LAST_YEAR + 1)
            for quarter in range(1, (LAST_QUARTER if year == LAST_YEAR else 4) + 1)]


def _load_contact(path: Path | None = None) -> str:
    path = CONTACT_PATH if path is None else path
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise free_sources.FreeSourceError("secure SEC contact opening is unavailable")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow)
    except OSError as exc:
        raise free_sources.FreeSourceError("SEC contact identity is missing or unreadable") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise free_sources.FreeSourceError("SEC contact identity file is unsafe")
        raw = os.read(descriptor, 8193)
    finally:
        os.close(descriptor)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise free_sources.FreeSourceError("SEC contact identity file is invalid") from exc
    matches = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == CONTACT_NAME:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            matches.append(value)
    if (len(matches) != 1 or not matches[0].strip() or len(matches[0]) > 200
            or not matches[0].isprintable() or "@" not in matches[0] or " " not in matches[0]):
        raise free_sources.FreeSourceError("SEC contact identity is missing or invalid")
    return matches[0]


def _private_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
            raise free_sources.FreeSourceError("SEC cache conflicts with its content identity")
        return
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as out:
            temporary_name = out.name
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        Path(temporary_name).chmod(0o600)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


@dataclass(frozen=True)
class CachedResponse:
    body: bytes
    fetched_at: datetime
    resumed: bool


class SecClient:
    """Five-request-per-second SEC client with URL/content-addressed resume cache."""

    def __init__(
        self, contact: str, data_dir: Path, *, session: requests.Session | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.contact, self.data_dir, self.session = contact, data_dir, session
        self.now, self.monotonic, self.sleep = now, monotonic, sleep
        self.last_started: float | None = None
        self._rate_lock, self._local = threading.Lock(), threading.local()

    def _session(self) -> requests.Session:
        if self.session is not None:
            return self.session
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _directory(self, url: str) -> Path:
        return self.data_dir / "sec" / "http" / hashlib.sha256(url.encode()).hexdigest()

    def _cached(self, url: str) -> CachedResponse | None:
        directory, expected_url_sha = self._directory(url), hashlib.sha256(url.encode()).hexdigest()
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            if directory.exists() and any(directory.iterdir()):
                raise free_sources.FreeSourceError("SEC URL cache is incomplete")
            return None
        try:
            receipt = json.loads(receipt_path.read_text())
            if set(receipt) != {"url", "url_sha256", "source_sha256", "fetched_at", "status"}:
                raise ValueError
            source_sha = receipt["source_sha256"]
            if (receipt["url"] != url or receipt["url_sha256"] != expected_url_sha
                    or free_sources.SHA256.fullmatch(source_sha) is None
                    or receipt["status"] != 200):
                return None
            fetched_at = datetime.fromisoformat(receipt["fetched_at"])
            if fetched_at.utcoffset() is None:
                raise ValueError
            body_path = directory / f"{source_sha}.raw"
            if body_path.is_symlink() or not body_path.is_file():
                raise ValueError
            body = body_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != source_sha:
                raise ValueError
        except (OSError, TypeError, ValueError) as exc:
            raise free_sources.FreeSourceError("SEC URL cache is invalid") from exc
        return CachedResponse(body, fetched_at, True)

    def _retain(self, url: str, body: bytes, status: int, fetched_at: datetime) -> None:
        directory, source_sha = self._directory(url), hashlib.sha256(body).hexdigest()
        _private_write(directory / f"{source_sha}.raw", body)
        receipt = {
            "url": url, "url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "source_sha256": source_sha, "fetched_at": fetched_at.isoformat(), "status": status,
        }
        write_text_atomic(directory / "receipt.json", json.dumps(receipt, sort_keys=True) + "\n")
        (directory / "receipt.json").chmod(0o600)

    def get(self, url: str) -> CachedResponse:
        cached = self._cached(url)
        if cached is not None:
            return cached
        for attempt in range(3):
            with self._rate_lock:
                if not _network_permitted(self.now()):
                    raise free_sources.FreeSourceError("SEC batch reached a configured no-call window")
                if self.last_started is not None:
                    remaining = REQUEST_INTERVAL_SECONDS - (self.monotonic() - self.last_started)
                    if remaining > 0:
                        self.sleep(remaining)
                if not _network_permitted(self.now()):
                    raise free_sources.FreeSourceError("SEC batch reached a configured no-call window")
                self.last_started = self.monotonic()
            try:
                response = self._session().get(
                    url, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=True,
                    headers={"User-Agent": self.contact, "Accept-Encoding": "gzip, deflate"},
                )
                status = int(response.status_code)
                body, fetched_at = bytes(response.content), self.now()
            except (requests.RequestException, TypeError, ValueError) as exc:
                raise free_sources.FreeSourceError("SEC request failed") from exc
            if len(body) > MAX_HTTP_BYTES:
                raise free_sources.FreeSourceError("SEC response exceeds the cache limit")
            self._retain(url, body, status, fetched_at)
            if status == 200 and body:
                return CachedResponse(body, fetched_at, False)
            if status not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            self.sleep(attempt + 1.0)
        raise free_sources.FreeSourceError(f"SEC request returned HTTP {status}")

    def get_many(self, urls: list[str]) -> list[CachedResponse]:
        with ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(self.get, urls))


def _connect(database: Path) -> duckdb.DuckDBPyConnection:
    database.parent.mkdir(parents=True, exist_ok=True)
    return db.connect(database, wait_s=0)


def capture_form25(
    client: SecClient, database: Path,
    *, quarters: Iterable[tuple[int, int]] | None = None,
) -> dict:
    requested = list(quarters or _quarters(FIRST_FORM_YEAR))
    index_rows = index_inserted = resumed = 0
    con = _connect(database)
    try:
        for year, quarter in requested:
            response = client.get(FORM_INDEX_URL.format(year=year, quarter=quarter))
            result = free_sec.load_form_index(con, response.body)
            index_rows += result["rows"]
            index_inserted += result["inserted"]
            resumed += int(response.resumed)
        details = con.execute(
            """SELECT n.cik,n.accession FROM free_delisting_notices n
            LEFT JOIN free_delisting_notice_details d USING(accession)
            WHERE n.filed_date>=DATE '2010-01-01' AND n.form LIKE '25-NSE%'
              AND d.accession IS NULL ORDER BY n.filed_date,n.accession"""
        ).fetchall()
        detail_inserted = detail_resumed = 0
        for offset in range(0, len(details), 100):
            chunk = details[offset:offset + 100]
            urls = [ARCHIVE_URL.format(cik=cik, accession=accession.replace("-", ""))
                    for cik, accession in chunk]
            responses = client.get_many(urls)
            for (_cik, accession), response in zip(chunk, responses, strict=True):
                result = free_sec.load_form25_detail(con, accession, response.body)
                detail_inserted += result["inserted"]
                detail_resumed += int(response.resumed)
    finally:
        con.close()
    return {
        "quarters": len(requested), "notice_rows": index_rows,
        "notices_inserted": index_inserted, "index_resumed": resumed,
        "details_requested": len(details), "details_inserted": detail_inserted,
        "details_resumed": detail_resumed,
    }


def capture_insiders(
    client: SecClient, database: Path,
    *, quarters: Iterable[tuple[int, int]] | None = None,
) -> dict:
    page_resumed = 0
    if quarters is None:
        page = client.get(INSIDER_PAGE_URL)
        page_resumed = int(page.resumed)
        try:
            text = page.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise free_sources.FreeSourceError("insider data page is not UTF-8") from exc
        matches = re.findall(
            r'href=["\']([^"\']*/([0-9]{4})q([1-4])_form345\.zip)["\']', text, re.I
        )
        by_quarter = {
            (int(year), int(quarter)): urljoin(INSIDER_PAGE_URL, href)
            for href, year, quarter in matches if int(year) >= FIRST_INSIDER_YEAR
        }
        if not by_quarter:
            raise free_sources.FreeSourceError("official insider page has no quarterly ZIP links")
        latest = max(by_quarter)
        expected = [item for item in _quarters(FIRST_INSIDER_YEAR) if item <= latest]
        if sorted(by_quarter) != expected:
            raise free_sources.FreeSourceError("official insider page has a quarterly gap")
        requested = [(year, quarter, by_quarter[(year, quarter)]) for year, quarter in expected]
    else:
        requested = [(year, quarter, INSIDER_URL.format(year=year, quarter=quarter))
                     for year, quarter in quarters]
    totals = defaultdict(int)
    con = _connect(database)
    try:
        for _year, _quarter, url in requested:
            response = client.get(url)
            result = free_sec.load_insider_zip(con, response.body)
            totals["quarters"] += 1
            totals["resumed"] += int(response.resumed)
            for key in ("submissions", "owners", "transactions"):
                totals[key] += result[key]
                totals[f"{key}_inserted"] += result[f"{key}_inserted"]
    finally:
        con.close()
    totals["page_resumed"] = page_resumed
    return dict(totals)


def capture_tickers(client: SecClient, database: Path, *, snapshot_date: date) -> dict:
    response = client.get(TICKERS_URL)
    con = _connect(database)
    try:
        result = free_sec.load_company_tickers(con, response.body, snapshot_date=snapshot_date)
    finally:
        con.close()
    return {**result, "resumed": response.resumed, "snapshot_date": snapshot_date.isoformat()}


def _sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _session_gap(calendar: list[date], left: date, right: date) -> int | None:
    if not calendar or left < calendar[0] or right < calendar[0] or left > calendar[-1] or right > calendar[-1]:
        return None
    return abs(bisect.bisect_left(calendar, left) - bisect.bisect_left(calendar, right))


def audit(free_database: Path, store_copy: Path) -> dict:
    """Return generic SEC coverage counts without mutating either database."""
    if not free_database.is_file() or not store_copy.is_file():
        raise ValueError("free-source database and store copy must be regular files")
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH {_sql_path(free_database)} AS free_store (READ_ONLY)")
        con.execute(f"ATTACH {_sql_path(store_copy)} AS live_copy (READ_ONLY)")
        con.execute("""CREATE TEMP VIEW history AS
            SELECT * FROM free_store.free_cik_ticker_history""")
        con.execute("""CREATE TEMP VIEW notice_map AS
            SELECT n.*,
              (SELECT h.ticker FROM history h
               WHERE h.cik=n.cik AND h.first_seen<=n.filed_date
               ORDER BY CASE h.source WHEN 'insider_submissions' THEN 0 ELSE 1 END,
                        h.first_seen DESC,h.last_seen DESC,h.ticker LIMIT 1) AS ticker
            FROM free_store.free_delisting_notices n""")
        notice_rows = con.execute("""SELECT EXTRACT(year FROM filed_date)::INTEGER AS year,
            COUNT(*) FILTER (WHERE form IN ('25','25/A')) AS form25,
            COUNT(*) FILTER (WHERE form IN ('25-NSE','25-NSE/A')) AS form25_nse,
            COUNT(*) AS total, COUNT(ticker) AS mapped
            FROM notice_map GROUP BY year ORDER BY year""").fetchall()
        mapped = con.execute(
            "SELECT filed_date,ticker FROM notice_map WHERE ticker IS NOT NULL"
        ).fetchall()
        con.execute("""CREATE TEMP VIEW latest_master AS SELECT *
            FROM free_store.free_security_master WHERE source_sha256=(
              SELECT source_sha256 FROM free_store.free_security_master
              ORDER BY fetched_at DESC,source_sha256 DESC LIMIT 1)""")
        ends: dict[str, list[date]] = defaultdict(list)
        for ticker, end_date in con.execute(
            "SELECT ticker,end_date FROM latest_master WHERE end_date IS NOT NULL"
        ).fetchall():
            ends[ticker].append(end_date)
        calendar = [row[0] for row in con.execute(
            "SELECT DISTINCT date FROM live_copy.prices ORDER BY date"
        ).fetchall()]
        overlap: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for filed_date, ticker in mapped:
            overlap[filed_date.year][0] += 1
            if any((gap := _session_gap(calendar, filed_date, ending)) is not None and gap <= 10
                   for ending in ends.get(ticker, ())):
                overlap[filed_date.year][1] += 1
        con.execute("""CREATE TEMP VIEW submissions AS SELECT * EXCLUDE(rn) FROM (
            SELECT *,ROW_NUMBER() OVER(PARTITION BY accession ORDER BY source_sha256,source_row) rn
            FROM free_store.free_insider_submissions) WHERE rn=1""")
        con.execute("""CREATE TEMP VIEW transactions AS SELECT DISTINCT accession,
            transaction_date,code,shares,price_per_share,acquired_disposed,
            shares_owned_after,direct_indirect
            FROM free_store.free_insider_nonderiv_trans""")
        con.execute("""CREATE TEMP VIEW store_ticker_year AS
            SELECT ticker,EXTRACT(year FROM date)::INTEGER AS year
            FROM live_copy.prices GROUP BY ticker,year""")
        insider_rows = con.execute("""WITH submission_year AS (
            SELECT EXTRACT(year FROM s.filing_date)::INTEGER AS year,
              COUNT(*) AS submissions,
              COUNT(*) FILTER (WHERE s.issuer_trading_symbol IS NOT NULL
                AND EXISTS(SELECT 1 FROM store_ticker_year p
                  WHERE p.ticker=s.issuer_trading_symbol
                    AND p.year=EXTRACT(year FROM s.filing_date))) AS store_matches,
              COUNT(*) FILTER (WHERE s.issuer_trading_symbol IS NOT NULL
              AND EXISTS(SELECT 1 FROM latest_master m
                WHERE m.ticker=s.issuer_trading_symbol AND m.start_date<=s.filing_date
                  AND (m.end_date IS NULL OR m.end_date>=s.filing_date))) AS master_matches
            FROM submissions s GROUP BY year), transaction_year AS (
            SELECT EXTRACT(year FROM s.filing_date)::INTEGER AS year,
              COUNT(*) FILTER (WHERE t.code='P') AS purchases,
              COUNT(*) FILTER (WHERE t.code='S') AS sales,
              COUNT(*) FILTER (WHERE t.code='P' AND s.issuer_trading_symbol IS NOT NULL
                AND EXISTS(SELECT 1 FROM store_ticker_year p
                  WHERE p.ticker=s.issuer_trading_symbol
                    AND p.year=EXTRACT(year FROM s.filing_date))) AS purchase_store_matches,
              COUNT(*) FILTER (WHERE t.code='P' AND s.issuer_trading_symbol IS NOT NULL
                AND EXISTS(SELECT 1 FROM latest_master m
                  WHERE m.ticker=s.issuer_trading_symbol AND m.start_date<=s.filing_date
                    AND (m.end_date IS NULL OR m.end_date>=s.filing_date))) AS purchase_master_matches
            FROM submissions s JOIN transactions t USING(accession) GROUP BY year)
            SELECT s.year,s.submissions,COALESCE(t.purchases,0),COALESCE(t.sales,0),
              s.store_matches,s.master_matches,COALESCE(t.purchase_store_matches,0),
              COALESCE(t.purchase_master_matches,0)
            FROM submission_year s LEFT JOIN transaction_year t USING(year)
            ORDER BY s.year""").fetchall()
        quality = con.execute("""SELECT
            (SELECT COUNT(*) FROM submissions WHERE document_type LIKE '%/A') AS amendments,
            (SELECT COUNT(*) FROM free_store.free_delisting_notices
             WHERE form LIKE '%/A') AS notice_amendments,
            (SELECT COUNT(*)-COUNT(DISTINCT accession)
             FROM free_store.free_insider_submissions) AS duplicate_accessions,
            (SELECT COUNT(*) FROM transactions
             WHERE price_per_share IS NULL OR price_per_share=0) AS zero_or_missing_prices,
            (SELECT COUNT(*) FROM submissions WHERE issuer_trading_symbol IS NULL) AS missing_symbols,
            (SELECT COUNT(*) FROM submissions WHERE issuer_trading_symbol IS NOT NULL
             AND NOT regexp_matches(issuer_trading_symbol,'^[A-Z][A-Z0-9.-]*$')) AS odd_symbols,
            (SELECT COUNT(*) FROM submissions WHERE issuer_name IS NULL) AS missing_issuer_names,
            (SELECT COUNT(*) FROM free_store.free_delisting_notice_details
             WHERE security_class IS NULL) AS missing_security_classes""").fetchone()
        inventory = con.execute("""SELECT
            (SELECT COUNT(*) FROM free_store.free_delisting_notices),
            (SELECT COUNT(*) FROM free_store.free_delisting_notice_details),
            (SELECT COUNT(DISTINCT source_sha256) FROM free_store.free_insider_submissions),
            (SELECT COUNT(*) FROM free_store.free_company_tickers)""").fetchone()
    finally:
        con.close()
    notices = [{"year": row[0], "form25": row[1], "form25_nse": row[2], "total": row[3],
                "mapped": row[4], "mapped_share": row[4] / row[3] if row[3] else None}
               for row in notice_rows]
    overlap_rows = [{"year": year, "mapped": counts[0], "within_10_sessions": counts[1],
                     "share": counts[1] / counts[0] if counts[0] else None}
                    for year, counts in sorted(overlap.items())]
    insiders = [{"year": row[0], "submissions": row[1], "purchases": row[2], "sales": row[3],
                 "store_matches": row[4], "store_share": row[4] / row[1] if row[1] else None,
                 "master_matches": row[5], "master_share": row[5] / row[1] if row[1] else None,
                 "purchase_store_matches": row[6],
                 "purchase_store_share": row[6] / row[2] if row[2] else None,
                 "purchase_master_matches": row[7],
                 "purchase_master_share": row[7] / row[2] if row[2] else None}
                for row in insider_rows]
    return {"inventory": dict(zip(("notices", "notice_details", "insider_quarters",
                                    "company_tickers"), inventory, strict=True)),
            "notices": notices, "tiingo_end_overlap": overlap_rows, "insiders": insiders,
            "quality": dict(zip(("amendments", "notice_amendments", "duplicate_accessions",
                                  "zero_or_missing_prices", "missing_symbols", "odd_symbols",
                                  "missing_issuer_names", "missing_security_classes"),
                                 quality, strict=True))}


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def render_audit(result: dict) -> str:
    inventory = result["inventory"]
    lines = [
        "# P3 Phase 0 free SEC audit — 2026-10-01", "",
        "## Method", "",
        "All SEC responses were retained outside Git by URL and SHA-256 and loaded only into",
        "`store/pit/free-sources.duckdb`. Store comparisons used a disposable consistent",
        "`tools.backup_database create` copy, which was removed after this audit. A Form 25 maps",
        "to the latest insider-observed ticker for its CIK on or before filing; the current SEC",
        "ticker file is only a 2026-10-01 observation. Tiingo overlap means the mapped ticker has",
        "an interval end within ten sessions on the copied store calendar.", "",
        f"The capture covers 123 Form indexes, {inventory['notices']:,} unique notice accessions,",
        f"{inventory['notice_details']:,} primary XML details, {inventory['insider_quarters']} contiguous",
        "insider quarters from 2006Q1 through the official page's latest link (2026Q2), and",
        f"{inventory['company_tickers']:,} current company-ticker rows. SEC had not published a",
        "2026Q3 insider ZIP on the audit date.", "",
        "Insider facts become available at EDGAR acceptance when the quarterly source supplies it.",
        "The published quarterly files are filing-date-granular otherwise, so consumers must not",
        "use those rows until after that filing date. Transaction date is never availability.", "",
        "## Form 25 coverage", "",
        "| Year | Form 25 | Form 25-NSE | Total | Mapped | Mapped share |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(f"| {r['year']} | {r['form25']:,} | {r['form25_nse']:,} | {r['total']:,} | "
                 f"{r['mapped']:,} | {_percent(r['mapped_share'])} |" for r in result["notices"])
    lines += ["", "## Mapped notices near Tiingo interval ends", "",
              "| Year | Mapped notices | Within ±10 sessions | Share |",
              "|---:|---:|---:|---:|"]
    lines.extend(f"| {r['year']} | {r['mapped']:,} | {r['within_10_sessions']:,} | "
                 f"{_percent(r['share'])} |" for r in result["tiingo_end_overlap"])
    lines += ["", "The low pre-2015 overlap and its step-up from 2015 calibrate the Tiingo",
              "archive's sparse early interval ends. The 2026 overlap is not a delisting-rate",
              "estimate because the Tiingo archive boundary right-censors current intervals.", "",
              "## Insider coverage", "",
              "| Year | Submissions | Purchases (`P`) | Sales (`S`) | Submission store share | Submission Tiingo share | Purchase store share | Purchase Tiingo share |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    lines.extend(f"| {r['year']} | {r['submissions']:,} | {r['purchases']:,} | {r['sales']:,} | "
                 f"{_percent(r['store_share'])} | {_percent(r['master_share'])} | "
                 f"{_percent(r['purchase_store_share'])} | {_percent(r['purchase_master_share'])} |"
                 for r in result["insiders"])
    q = result["quality"]
    lines += ["", "## Data-quality notes", "",
              f"- Amendments retained: {q['notice_amendments']:,} Form 25-family notices and "
              f"{q['amendments']:,} insider submissions.",
              f"- Duplicate insider accession rows across quarterly archives: {q['duplicate_accessions']:,}.",
              f"- Non-derivative transactions with zero or missing price: {q['zero_or_missing_prices']:,}.",
              f"- Submissions with missing symbols: {q['missing_symbols']:,}; with non-standard symbols: {q['odd_symbols']:,}.",
              f"- Submissions with a missing issuer name: {q['missing_issuer_names']:,}.",
              f"- Form 25-NSE details with an empty security class: {q['missing_security_classes']:,}.",
              "- Amendments are retained as distinct accessions. Exact symbols are not rewritten; class,",
              "  preferred, warrant, slash, and punctuation conventions therefore remain visible rather",
              "  than being guessed into a match.", ""]
    return "\n".join(lines)


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=free_sources.default_database())
    parser.add_argument("--data-dir", type=Path, default=free_sources.default_data_dir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("form25", "insiders", "tickers", "all"):
        _paths(commands.add_parser(name))
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--free-database", type=Path, default=free_sources.default_database())
    audit_parser.add_argument("--store-copy", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit(args.free_database, args.store_copy)
            if args.output:
                write_text_atomic(args.output, render_audit(result))
            print(json.dumps({"status": "complete", **result}, sort_keys=True))
            return 0
        contact = _load_contact()
        client = SecClient(contact, args.data_dir)
        result = {}
        if args.command in {"form25", "all"}:
            result["form25"] = capture_form25(client, args.database)
        if args.command in {"insiders", "all"}:
            result["insiders"] = capture_insiders(client, args.database)
        if args.command in {"tickers", "all"}:
            result["tickers"] = capture_tickers(
                client, args.database, snapshot_date=datetime.now(timezone.utc).date()
            )
    except (free_sources.FreeSourceError, ValueError, duckdb.Error) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "complete", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
