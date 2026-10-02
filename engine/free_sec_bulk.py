"""Parse SEC nightly bulk archives into an isolated point-in-time store."""
from __future__ import annotations

import hashlib
import json
import math
import re
import zipfile
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path, PurePosixPath

import duckdb
import pandas as pd

from engine.free_sources import FreeSourceError
from engine.lib import db

ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
CIK_FILE = re.compile(r"^CIK(?P<cik>[0-9]{10})\.json$")
PAGE_FILE = re.compile(r"^CIK(?P<cik>[0-9]{10})-submissions-[0-9]{3}\.json$")
MAX_JSON_BYTES = 512_000_000
MAX_ZIP_MEMBERS = 1_000_000

# Ordered fallbacks. Every source fact is retained; the rank only resolves competing
# tags in the point-in-time consumer view.
CONCEPT_TAGS: dict[str, tuple[tuple[str, str], ...]] = {
    "revenue": (
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
        ("us-gaap", "SalesRevenueGoodsNet"),
        ("us-gaap", "SalesRevenueServicesNet"),
        ("ifrs-full", "Revenue"),
    ),
    "net_income": (
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
        ("ifrs-full", "ProfitLoss"),
    ),
    "eps_basic": (
        ("us-gaap", "EarningsPerShareBasic"),
        ("ifrs-full", "BasicEarningsLossPerShare"),
    ),
    "eps_diluted": (
        ("us-gaap", "EarningsPerShareDiluted"),
        ("ifrs-full", "DilutedEarningsLossPerShare"),
    ),
    "operating_cash_flow": (
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ),
    "total_assets": (("us-gaap", "Assets"), ("ifrs-full", "Assets")),
    "total_liabilities": (("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities")),
    "stockholders_equity": (
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("us-gaap", "PartnersCapital"),
        ("ifrs-full", "Equity"),
    ),
    "shares_outstanding": (
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
        ("ifrs-full", "NumberOfSharesOutstanding"),
    ),
    "dividends_per_share": (
        ("us-gaap", "CommonStockDividendsPerShareDeclared"),
        ("us-gaap", "CommonStockDividendsPerShareCashPaid"),
        ("ifrs-full", "DividendsPaidPerShare"),
    ),
    "research_and_development": (
        ("us-gaap", "ResearchAndDevelopmentExpense"),
        ("ifrs-full", "ResearchAndDevelopmentExpense"),
    ),
    "selling_general_and_administrative": (
        ("us-gaap", "SellingGeneralAndAdministrativeExpense"),
        ("ifrs-full", "GeneralAndAdministrativeExpense"),
    ),
}
TAG_LOOKUP = {
    pair: (concept, rank)
    for concept, pairs in CONCEPT_TAGS.items()
    for rank, pair in enumerate(pairs)
}


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS sec_submission_index (
        accession VARCHAR PRIMARY KEY, cik BIGINT NOT NULL, filed DATE NOT NULL,
        accepted_at TIMESTAMPTZ, form VARCHAR NOT NULL, items VARCHAR NOT NULL,
        source_sha256 VARCHAR NOT NULL, source_file VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_submission_pages (
        name VARCHAR PRIMARY KEY, cik BIGINT NOT NULL, filing_from DATE, filing_to DATE,
        source_sha256 VARCHAR, loaded_at TIMESTAMPTZ)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_facts (
        fact_key VARCHAR PRIMARY KEY, cik BIGINT NOT NULL, concept VARCHAR NOT NULL,
        tag_priority SMALLINT NOT NULL, taxonomy VARCHAR NOT NULL, tag VARCHAR NOT NULL,
        unit VARCHAR NOT NULL, value DOUBLE NOT NULL, period_start DATE, period_end DATE NOT NULL,
        fy INTEGER, fp VARCHAR, form VARCHAR NOT NULL, filed DATE NOT NULL,
        accn VARCHAR NOT NULL, frame VARCHAR, source_sha256 VARCHAR NOT NULL,
        source_file VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_earnings_events (
        accession VARCHAR PRIMARY KEY, cik BIGINT NOT NULL,
        acceptance_datetime TIMESTAMPTZ NOT NULL, filed DATE NOT NULL,
        form VARCHAR NOT NULL, items VARCHAR NOT NULL,
        source_sha256 VARCHAR NOT NULL, source_file VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_cik_ticker_history (
        cik BIGINT NOT NULL, ticker VARCHAR NOT NULL, first_seen DATE NOT NULL,
        last_seen DATE NOT NULL, source VARCHAR NOT NULL,
        PRIMARY KEY(cik,ticker,first_seen,last_seen,source))""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_archive_loads (
        source_sha256 VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, source_file VARCHAR NOT NULL,
        loaded_at TIMESTAMPTZ NOT NULL, members BIGINT NOT NULL, rows BIGINT NOT NULL)""")
    con.execute("""CREATE OR REPLACE VIEW sec_facts_available AS
        SELECT f.*,
          COALESCE(s.accepted_at,
            f.filed::TIMESTAMP AT TIME ZONE 'America/New_York'
              + INTERVAL '1 day' - INTERVAL '1 microsecond') AS available_at
        FROM sec_facts f LEFT JOIN sec_submission_index s ON s.accession=f.accn""")
    ticker_lateral = """LEFT JOIN LATERAL (
        SELECT h.ticker FROM sec_cik_ticker_history h WHERE h.cik=x.cik
        ORDER BY
          CASE WHEN x.filed BETWEEN h.first_seen AND h.last_seen THEN 0
               WHEN h.source='insider_submissions' AND h.first_seen<=x.filed THEN 1
               WHEN h.source='company_tickers' THEN 2 ELSE 3 END,
          CASE WHEN h.first_seen<=x.filed THEN h.first_seen END DESC NULLS LAST,
          h.first_seen,h.ticker LIMIT 1) t ON TRUE"""
    con.execute(f"""CREATE OR REPLACE VIEW sec_facts_with_ticker AS
        SELECT x.*,t.ticker FROM sec_facts_available x {ticker_lateral}""")
    con.execute(f"""CREATE OR REPLACE VIEW sec_earnings_events_with_ticker AS
        SELECT x.*,t.ticker FROM sec_earnings_events x {ticker_lateral}""")
    con.execute("""CREATE OR REPLACE MACRO sec_fundamentals_asof(as_of_ts) AS TABLE
        SELECT * EXCLUDE(row_number) FROM (
          SELECT f.*,ROW_NUMBER() OVER (
            PARTITION BY cik,concept ORDER BY available_at DESC,period_end DESC,
              tag_priority,accn DESC,fact_key) AS row_number
          FROM sec_facts_with_ticker f
          WHERE available_at<=CAST(as_of_ts AS TIMESTAMPTZ))
        WHERE row_number=1""")


def _cik(raw: object) -> int:
    text = str(raw)
    if not re.fullmatch(r"[0-9]{1,10}", text) or int(text) == 0:
        raise FreeSourceError("SEC bulk CIK is invalid")
    return int(text)


def _date(raw: object, field: str, *, optional: bool = False) -> date | None:
    if optional and raw in {None, ""}:
        return None
    if not isinstance(raw, str):
        raise FreeSourceError(f"SEC bulk {field} is invalid")
    try:
        value = date.fromisoformat(raw)
    except ValueError as exc:
        raise FreeSourceError(f"SEC bulk {field} is invalid") from exc
    if value.isoformat() != raw:
        raise FreeSourceError(f"SEC bulk {field} is not canonical")
    return value


def _text(raw: object, field: str, *, optional: bool = False) -> str | None:
    if optional and raw in {None, ""}:
        return None
    if not isinstance(raw, str):
        raise FreeSourceError(f"SEC bulk {field} is invalid")
    value = " ".join(raw.split())
    if not value or len(value) > 4096 or not value.isprintable():
        raise FreeSourceError(f"SEC bulk {field} is invalid")
    return value


def _acceptance(raw: object) -> datetime | None:
    if raw in {None, ""}:
        return None
    if not isinstance(raw, str):
        raise FreeSourceError("SEC bulk acceptance timestamp is invalid")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreeSourceError("SEC bulk acceptance timestamp is invalid") from exc
    if value.utcoffset() is None:
        raise FreeSourceError("SEC bulk acceptance timestamp has no timezone")
    return value


def _json(body: bytes) -> dict:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_JSON_BYTES:
        raise FreeSourceError("SEC bulk JSON size is invalid")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreeSourceError("SEC bulk JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise FreeSourceError("SEC bulk JSON root is invalid")
    return payload


def parse_companyfacts_document(body: bytes, *, expected_cik: int | None = None) -> list[dict]:
    """Return selected numerical facts from one Companyfacts company document."""
    payload = _json(body)
    cik = _cik(payload.get("cik"))
    if expected_cik is not None and cik != expected_cik:
        raise FreeSourceError("Companyfacts member CIK differs")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise FreeSourceError("Companyfacts facts object is missing")
    result = []
    for taxonomy, taxonomy_facts in facts.items():
        if not isinstance(taxonomy, str) or not isinstance(taxonomy_facts, dict):
            raise FreeSourceError("Companyfacts taxonomy is invalid")
        for tag, fact in taxonomy_facts.items():
            selected = TAG_LOOKUP.get((taxonomy, tag))
            if selected is None:
                continue
            if not isinstance(fact, dict) or not isinstance(fact.get("units"), dict):
                raise FreeSourceError("Companyfacts selected tag is invalid")
            concept, tag_priority = selected
            for unit, observations in fact["units"].items():
                unit = _text(unit, "unit")
                if not isinstance(observations, list):
                    raise FreeSourceError("Companyfacts unit observations are invalid")
                for observation in observations:
                    if not isinstance(observation, dict):
                        raise FreeSourceError("Companyfacts observation is invalid")
                    try:
                        value = float(observation.get("val"))
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise FreeSourceError("Companyfacts value is invalid") from exc
                    if not math.isfinite(value):
                        raise FreeSourceError("Companyfacts value is invalid")
                    accn = _text(observation.get("accn"), "accession")
                    if ACCESSION.fullmatch(accn) is None:
                        raise FreeSourceError("Companyfacts accession is invalid")
                    fy_raw = observation.get("fy")
                    if fy_raw is None:
                        fy = None
                    elif isinstance(fy_raw, int) and 1800 <= fy_raw <= 2200:
                        fy = fy_raw
                    else:
                        raise FreeSourceError("Companyfacts fiscal year is invalid")
                    row = {
                        "cik": cik, "concept": concept, "tag_priority": tag_priority,
                        "taxonomy": taxonomy, "tag": tag, "unit": unit, "value": value,
                        "period_start": _date(observation.get("start"), "period start", optional=True),
                        "period_end": _date(observation.get("end"), "period end"),
                        "fy": fy, "fp": _text(observation.get("fp"), "fiscal period", optional=True),
                        "form": _text(observation.get("form"), "form"),
                        "filed": _date(observation.get("filed"), "filing date"),
                        "accn": accn,
                        "frame": _text(observation.get("frame"), "frame", optional=True),
                    }
                    result.append(row)
    return result


def _parallel_rows(payload: dict) -> list[dict]:
    required = ("accessionNumber", "filingDate", "form")
    if any(not isinstance(payload.get(name), list) for name in required):
        raise FreeSourceError("Submissions parallel arrays are missing")
    length = len(payload["accessionNumber"])
    arrays = {name: value for name, value in payload.items() if isinstance(value, list)}
    if any(len(value) != length for value in arrays.values()):
        raise FreeSourceError("Submissions parallel arrays differ")
    rows = []
    for index in range(length):
        accession = _text(payload["accessionNumber"][index], "accession")
        if ACCESSION.fullmatch(accession) is None:
            raise FreeSourceError("Submissions accession is invalid")
        items_raw = arrays.get("items", [""] * length)[index]
        if items_raw in {None, ""}:
            items = ()
        elif isinstance(items_raw, str):
            items = tuple(part.strip() for part in items_raw.split(",") if part.strip())
            # Historical SEC rows include coarse sections (``5,7``) and a small
            # number of malformed legacy strings. Keep the source text, but only
            # an exact ``2.02`` token can qualify as an earnings event.
            if len(items_raw) > 4096 or not items_raw.isprintable():
                raise FreeSourceError("Submissions items are invalid")
        else:
            raise FreeSourceError("Submissions items are invalid")
        rows.append({
            "accession": accession,
            "filed": _date(payload["filingDate"][index], "filing date"),
            "accepted_at": _acceptance(arrays.get("acceptanceDateTime", [None] * length)[index]),
            "form": _text(payload["form"][index], "form"),
            "items": items,
        })
    return rows


def parse_submissions_document(
    body: bytes, *, expected_cik: int | None = None,
) -> tuple[int, list[dict], list[dict]]:
    """Parse one main or paged submissions document and its older-page references."""
    payload = _json(body)
    if "filings" in payload:
        cik = _cik(payload.get("cik"))
        filings = payload.get("filings")
        if not isinstance(filings, dict) or not isinstance(filings.get("recent"), dict):
            raise FreeSourceError("Submissions recent filings are missing")
        rows = _parallel_rows(filings["recent"])
        raw_pages = filings.get("files", [])
        if not isinstance(raw_pages, list):
            raise FreeSourceError("Submissions page list is invalid")
        pages = []
        for item in raw_pages:
            if not isinstance(item, dict):
                raise FreeSourceError("Submissions page reference is invalid")
            name = _text(item.get("name"), "page name")
            match = PAGE_FILE.fullmatch(name)
            if match is None or int(match.group("cik")) != cik:
                raise FreeSourceError("Submissions page name is invalid")
            pages.append({
                "name": name, "cik": cik,
                "filing_from": _date(item.get("filingFrom"), "page start", optional=True),
                "filing_to": _date(item.get("filingTo"), "page end", optional=True),
            })
    else:
        if expected_cik is None:
            raise FreeSourceError("Paged submissions document has no expected CIK")
        cik, rows, pages = expected_cik, _parallel_rows(payload), []
    if expected_cik is not None and cik != expected_cik:
        raise FreeSourceError("Submissions member CIK differs")
    if len({row["accession"] for row in rows}) != len(rows):
        raise FreeSourceError("Submissions document has duplicate accessions")
    return cik, rows, pages


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _members(archive: zipfile.ZipFile, pattern: re.Pattern[str]) -> list[zipfile.ZipInfo]:
    members = [member for member in archive.infolist() if not member.is_dir()]
    if not members or len(members) > MAX_ZIP_MEMBERS:
        raise FreeSourceError("SEC bulk ZIP member count is invalid")
    selected, names = [], set()
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or member.flag_bits & 0x1:
            raise FreeSourceError("SEC bulk ZIP member is unsafe")
        name = path.name
        if pattern.fullmatch(name):
            if name in names or member.file_size > MAX_JSON_BYTES:
                raise FreeSourceError("SEC bulk ZIP member identity is invalid")
            names.add(name)
            selected.append(member)
    if not selected:
        raise FreeSourceError("SEC bulk ZIP has no expected JSON members")
    return selected


def _fact_key(row: dict) -> str:
    identity = [
        row[name].isoformat() if isinstance(row[name], date) else row[name]
        for name in ("cik", "concept", "taxonomy", "tag", "unit", "value", "period_start",
                     "period_end", "fy", "fp", "form", "filed", "accn", "frame")
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _insert_submission_rows(
    con: duckdb.DuckDBPyConnection, cik: int, rows: Iterable[dict],
    *, source_sha256: str, source_file: str,
) -> tuple[int, int, int]:
    rows = list(rows)
    events = [row for row in rows if row["form"] in {"8-K", "8-K/A"}
              and "2.02" in row["items"] and row["filed"] >= date(2004, 1, 1)]
    complete = [row for row in events if row["accepted_at"] is not None]
    submissions = [[row["accession"], cik, row["filed"], row["accepted_at"], row["form"],
                    ",".join(row["items"]), source_sha256, source_file] for row in rows]
    event_values = [[row["accession"], cik, row["accepted_at"], row["filed"], row["form"],
                     ",".join(row["items"]), source_sha256, source_file] for row in complete]
    _flush_submissions(con, submissions, event_values)
    return len(rows), len(complete), len(events) - len(complete)


def _flush_submissions(
    con: duckdb.DuckDBPyConnection, submissions: list[list], events: list[list],
) -> None:
    if submissions:
        frame = pd.DataFrame(submissions, columns=(
            "accession", "cik", "filed", "accepted_at", "form", "items",
            "source_sha256", "source_file",
        ))
        with db.registered_frame(con, "_sec_submission_batch", frame):
            con.execute("INSERT OR IGNORE INTO sec_submission_index SELECT * FROM _sec_submission_batch")
        submissions.clear()
    if events:
        frame = pd.DataFrame(events, columns=(
            "accession", "cik", "acceptance_datetime", "filed", "form", "items",
            "source_sha256", "source_file",
        ))
        with db.registered_frame(con, "_sec_event_batch", frame):
            con.execute("INSERT OR IGNORE INTO sec_earnings_events SELECT * FROM _sec_event_batch")
        events.clear()


def _flush_facts(con: duckdb.DuckDBPyConnection, facts: list[list]) -> None:
    if not facts:
        return
    frame = pd.DataFrame(facts, columns=(
        "fact_key", "cik", "concept", "tag_priority", "taxonomy", "tag", "unit", "value",
        "period_start", "period_end", "fy", "fp", "form", "filed", "accn", "frame",
        "source_sha256", "source_file",
    ))
    with db.registered_frame(con, "_sec_fact_batch", frame):
        con.execute("INSERT OR IGNORE INTO sec_facts SELECT * FROM _sec_fact_batch")
    facts.clear()


def load_submissions_zip(
    con: duckdb.DuckDBPyConnection, path: Path, *, source_sha256: str | None = None,
) -> dict:
    init_schema(con)
    source_sha256 = source_sha256 or _sha256(path)
    loaded = con.execute(
        "SELECT members,rows FROM sec_archive_loads WHERE source_sha256=?", [source_sha256]
    ).fetchone()
    if loaded:
        return {"members": loaded[0], "filings": loaded[1], "inserted": 0, "resumed": True}
    before_index = con.execute("SELECT COUNT(*) FROM sec_submission_index").fetchone()[0]
    before_events = con.execute("SELECT COUNT(*) FROM sec_earnings_events").fetchone()[0]
    filings = missing_acceptance = page_count = 0
    submission_batch: list[list] = []
    event_batch: list[list] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = _members(archive, CIK_FILE)
            for member in members:
                match = CIK_FILE.fullmatch(PurePosixPath(member.filename).name)
                cik, rows, pages = parse_submissions_document(
                    archive.read(member), expected_cik=int(match.group("cik"))
                )
                source_file = PurePosixPath(member.filename).name
                submission_batch.extend([
                    row["accession"], cik, row["filed"], row["accepted_at"], row["form"],
                    ",".join(row["items"]), source_sha256, source_file,
                ] for row in rows)
                qualifying = [
                    row for row in rows if row["form"] in {"8-K", "8-K/A"}
                    and "2.02" in row["items"] and row["filed"] >= date(2004, 1, 1)
                ]
                event_batch.extend([
                    row["accession"], cik, row["accepted_at"], row["filed"], row["form"],
                    ",".join(row["items"]), source_sha256, source_file,
                ] for row in qualifying if row["accepted_at"] is not None)
                filings += len(rows)
                missing_acceptance += sum(row["accepted_at"] is None for row in qualifying)
                if len(submission_batch) >= 50_000:
                    _flush_submissions(con, submission_batch, event_batch)
                if pages:
                    con.executemany(
                        "INSERT OR IGNORE INTO sec_submission_pages VALUES (?,?,?,?,NULL,NULL)",
                        [[page["name"], page["cik"], page["filing_from"], page["filing_to"]]
                         for page in pages],
                    )
                    page_count += len(pages)
            _flush_submissions(con, submission_batch, event_batch)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FreeSourceError("Submissions ZIP is unreadable") from exc
    con.execute(
        "INSERT INTO sec_archive_loads VALUES (?, 'submissions', ?, now(), ?, ?)",
        [source_sha256, path.name, len(members), filings],
    )
    inserted = con.execute("SELECT COUNT(*) FROM sec_submission_index").fetchone()[0] - before_index
    events = con.execute("SELECT COUNT(*) FROM sec_earnings_events").fetchone()[0] - before_events
    return {"members": len(members), "filings": filings, "inserted": inserted,
            "events_inserted": events, "events_missing_acceptance": missing_acceptance,
            "page_references": page_count, "resumed": False}


def load_submission_page(
    con: duckdb.DuckDBPyConnection, path: Path, *, name: str, cik: int,
    source_sha256: str | None = None,
) -> dict:
    init_schema(con)
    match = PAGE_FILE.fullmatch(name)
    if match is None or int(match.group("cik")) != cik:
        raise FreeSourceError("Submissions page identity is invalid")
    source_sha256 = source_sha256 or _sha256(path)
    current = con.execute(
        "SELECT source_sha256 FROM sec_submission_pages WHERE name=?", [name]
    ).fetchone()
    if current and current[0] is not None:
        if current[0] != source_sha256:
            raise FreeSourceError("Submissions page changed after loading")
        return {"filings": 0, "inserted": 0, "events_inserted": 0, "resumed": True}
    parsed_cik, rows, pages = parse_submissions_document(path.read_bytes(), expected_cik=cik)
    if pages:
        raise FreeSourceError("Paged submissions document references another page")
    additions = _insert_submission_rows(
        con, parsed_cik, rows, source_sha256=source_sha256, source_file=name,
    )
    con.execute(
        "UPDATE sec_submission_pages SET source_sha256=?,loaded_at=now() WHERE name=?",
        [source_sha256, name],
    )
    return {"filings": len(rows), "inserted": additions[0],
            "events_inserted": additions[1], "events_missing_acceptance": additions[2],
            "resumed": False}


def pending_submission_pages(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    init_schema(con)
    return con.execute(
        "SELECT name,cik FROM sec_submission_pages WHERE source_sha256 IS NULL ORDER BY name"
    ).fetchall()


def load_companyfacts_zip(
    con: duckdb.DuckDBPyConnection, path: Path, *, source_sha256: str | None = None,
) -> dict:
    init_schema(con)
    source_sha256 = source_sha256 or _sha256(path)
    loaded = con.execute(
        "SELECT members,rows FROM sec_archive_loads WHERE source_sha256=?", [source_sha256]
    ).fetchone()
    if loaded:
        return {"members": loaded[0], "facts": loaded[1], "inserted": 0, "resumed": True}
    before = con.execute("SELECT COUNT(*) FROM sec_facts").fetchone()[0]
    facts = 0
    fact_batch: list[list] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = _members(archive, CIK_FILE)
            for member in members:
                name = PurePosixPath(member.filename).name
                match = CIK_FILE.fullmatch(name)
                rows = parse_companyfacts_document(
                    archive.read(member), expected_cik=int(match.group("cik"))
                )
                facts += len(rows)
                fact_batch.extend([
                    _fact_key(row), row["cik"], row["concept"], row["tag_priority"],
                    row["taxonomy"], row["tag"], row["unit"], row["value"],
                    row["period_start"], row["period_end"], row["fy"], row["fp"],
                    row["form"], row["filed"], row["accn"], row["frame"],
                    source_sha256, name,
                ] for row in rows)
                if len(fact_batch) >= 50_000:
                    _flush_facts(con, fact_batch)
            _flush_facts(con, fact_batch)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FreeSourceError("Companyfacts ZIP is unreadable") from exc
    inserted = con.execute("SELECT COUNT(*) FROM sec_facts").fetchone()[0] - before
    con.execute(
        "INSERT INTO sec_archive_loads VALUES (?, 'companyfacts', ?, now(), ?, ?)",
        [source_sha256, path.name, len(members), facts],
    )
    return {"members": len(members), "facts": facts, "inserted": inserted, "resumed": False}


def copy_ticker_history(con: duckdb.DuckDBPyConnection, free_database: Path) -> dict:
    """Copy only the public CIK mapping view from the existing read-only P3 database."""
    if not free_database.is_file():
        raise FreeSourceError("free-source database is missing")
    init_schema(con)
    before = con.execute("SELECT COUNT(*) FROM sec_cik_ticker_history").fetchone()[0]
    escaped = str(free_database).replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS free_source (READ_ONLY)")
    try:
        con.execute("""INSERT OR IGNORE INTO sec_cik_ticker_history
            SELECT DISTINCT cik,upper(ticker),first_seen,last_seen,source
            FROM free_source.free_cik_ticker_history
            WHERE cik>0 AND ticker IS NOT NULL AND ticker<>''
              AND first_seen IS NOT NULL AND last_seen IS NOT NULL""")
    finally:
        con.execute("DETACH free_source")
    after = con.execute("SELECT COUNT(*) FROM sec_cik_ticker_history").fetchone()[0]
    return {"rows": after, "inserted": after - before}


def audit(
    database: Path, free_database: Path, market_snapshot: Path,
) -> dict:
    """Compute generic annual coverage, ticker matching, and earnings-date overlap."""
    for path in (database, free_database, market_snapshot):
        if not path.is_file():
            raise FreeSourceError(f"audit database is missing: {path.name}")
    con = db.connect(database, wait_s=0)
    try:
        copy_ticker_history(con, free_database)
        facts = con.execute("""SELECT year(filed),COUNT(*),COUNT(DISTINCT cik)
            FROM sec_facts GROUP BY ALL ORDER BY 1""").fetchall()
        events = con.execute("""SELECT year(acceptance_datetime),COUNT(*)
            FROM sec_earnings_events GROUP BY ALL ORDER BY 1""").fetchall()
        fact_match = con.execute("""SELECT COUNT(*),COUNT(ticker)
            FROM sec_facts_with_ticker""").fetchone()
        event_match = con.execute("""SELECT COUNT(*),COUNT(ticker)
            FROM sec_earnings_events_with_ticker""").fetchone()
        escaped = str(market_snapshot).replace("'", "''")
        con.execute(f"ATTACH '{escaped}' AS market (READ_ONLY)")
        try:
            tables = {row[0] for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_catalog='market'"
            ).fetchall()}
            earnings_table = "earnings" if "earnings" in tables else "earnings_calendar"
            if earnings_table not in tables:
                raise FreeSourceError("market snapshot has no earnings table")
            overlap = con.execute(f"""SELECT COUNT(*) AS events,
                COUNT(*) FILTER (WHERE e.ticker IS NOT NULL),
                COUNT(*) FILTER (WHERE EXISTS (
                  SELECT 1 FROM market.{earnings_table} m WHERE m.ticker=e.ticker
                    AND abs(date_diff('day',CAST(e.acceptance_datetime AS DATE),
                                      m.earnings_date))<=1))
                FROM sec_earnings_events_with_ticker e""").fetchone()
        finally:
            con.execute("DETACH market")
    finally:
        con.close()
    combined_total = fact_match[0] + event_match[0]
    combined_matched = fact_match[1] + event_match[1]
    return {
        "facts_by_year": [
            {"year": row[0], "facts": row[1], "companies": row[2]} for row in facts
        ],
        "earnings_events_by_year": [
            {"year": row[0], "events": row[1]} for row in events
        ],
        "facts_rows": fact_match[0],
        "companies": sum(row[2] for row in facts),
        "earnings_events": event_match[0],
        "ticker_match": {
            "matched": combined_matched, "total": combined_total,
            "share": combined_matched / combined_total if combined_total else None,
            "facts_matched": fact_match[1], "facts_total": fact_match[0],
            "events_matched": event_match[1], "events_total": event_match[0],
        },
        "earnings_overlap": {
            "matched": overlap[2], "total": overlap[0], "ticker_mapped": overlap[1],
            "share": overlap[2] / overlap[0] if overlap[0] else None,
        },
    }
