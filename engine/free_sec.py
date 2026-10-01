"""Parse and store the SEC Phase 0 sources without network access.

The selected Insider Transactions Data Sets columns retain the meanings in the
SEC data-set README: ``ACCESSION_NUMBER`` identifies the filing;
``FILING_DATE`` is its filing date; ``PERIOD_OF_REPORT`` is the statement's
period; ``ISSUERCIK``, ``ISSUERNAME`` and ``ISSUERTRADINGSYMBOL`` identify the
issuer; ``RPTOWNERCIK``, ``RPTOWNER_RELATIONSHIP`` and ``RPTOWNER_TITLE``
encode the owner and the director, officer, ten-percent-owner and other roles;
and the ``NONDERIV_TRANS`` fields describe transaction date,
code, shares, price, acquired/disposed direction, post-transaction ownership,
and direct/indirect ownership. Transaction date is never availability. When a
quarter supplies an acceptance timestamp it is authoritative; otherwise the
row is only filing-date-granular and consumers must wait until a later date.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import duckdb

from engine.free_sources import FreeSourceError
from engine.lib import db

DELISTING_FORMS = frozenset({"25", "25/A", "25-NSE", "25-NSE/A"})
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
INDEX_ROW = re.compile(
    r"^(?P<form>\S+)\s+(?P<company>.*?)\s+(?P<cik>[0-9]{1,10})\s+"
    r"(?P<filed>[0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"(?P<path>edgar/data/[0-9]+/(?P<accession>[0-9-]+)\.txt)\s*$"
)
MAX_INDEX_BYTES = 64_000_000
MAX_XML_BYTES = 8_000_000
MAX_ZIP_BYTES = 512_000_000
MAX_ZIP_EXPANDED_BYTES = 2_000_000_000
EASTERN = ZoneInfo("America/New_York")
NULLS = frozenset({"", "NULL", "NONE", "N/A", "NA", "\\N"})

SUBMISSION_FIELDS = frozenset({
    "ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "ISSUERCIK",
    "ISSUERNAME", "ISSUERTRADINGSYMBOL",
})
OWNER_FIELDS = frozenset({
    "ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE",
})
TRANS_FIELDS = frozenset({
    "ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
    "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS",
    "DIRECT_INDIRECT_OWNERSHIP",
})


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS free_delisting_notices (
        cik BIGINT NOT NULL, company VARCHAR NOT NULL, form VARCHAR NOT NULL,
        filed_date DATE NOT NULL, accession VARCHAR PRIMARY KEY,
        source_sha256 VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_delisting_notice_details (
        accession VARCHAR PRIMARY KEY, exchange VARCHAR NOT NULL,
        security_class VARCHAR NOT NULL, symbol VARCHAR,
        source_sha256 VARCHAR NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_insider_submissions (
        accession VARCHAR NOT NULL, filing_date DATE NOT NULL,
        period_of_report DATE, issuer_cik BIGINT NOT NULL, issuer_name VARCHAR NOT NULL,
        issuer_trading_symbol VARCHAR, document_type VARCHAR,
        accepted_at TIMESTAMPTZ, available_on DATE NOT NULL,
        source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_insider_owners (
        accession VARCHAR NOT NULL, owner_cik BIGINT,
        is_director BOOLEAN, is_officer BOOLEAN, officer_title VARCHAR,
        is_ten_percent_owner BOOLEAN, is_other BOOLEAN,
        source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_insider_nonderiv_trans (
        accession VARCHAR NOT NULL, transaction_date DATE, code VARCHAR,
        shares DECIMAL(38,10), price_per_share DECIMAL(38,10),
        acquired_disposed VARCHAR, shares_owned_after DECIMAL(38,10),
        direct_indirect VARCHAR, source_sha256 VARCHAR NOT NULL,
        source_row BIGINT NOT NULL, PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_company_tickers (
        cik BIGINT NOT NULL, ticker VARCHAR NOT NULL, company VARCHAR NOT NULL,
        snapshot_date DATE NOT NULL, source_sha256 VARCHAR NOT NULL,
        source_row BIGINT NOT NULL, PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE OR REPLACE VIEW free_cik_ticker_history AS
        SELECT issuer_cik AS cik, issuer_trading_symbol AS ticker,
          MIN(filing_date) AS first_seen, MAX(filing_date) AS last_seen,
          'insider_submissions' AS source
        FROM free_insider_submissions
        WHERE issuer_trading_symbol IS NOT NULL
        GROUP BY issuer_cik, issuer_trading_symbol
        UNION ALL
        SELECT cik, ticker, MIN(snapshot_date), MAX(snapshot_date),
          'company_tickers' AS source
        FROM free_company_tickers GROUP BY cik, ticker""")


def _date(value: str | None, field: str, *, optional: bool = False) -> date | None:
    text = "" if value is None else value.strip()
    if optional and text.upper() in NULLS:
        return None
    for pattern in (None, "%d-%b-%Y"):
        try:
            return date.fromisoformat(text) if pattern is None else datetime.strptime(
                text, pattern
            ).date()
        except ValueError:
            pass
    raise FreeSourceError(f"invalid {field}")


def _cik(value: str | int | None, field: str, *, optional: bool = False) -> int | None:
    text = "" if value is None else str(value).strip()
    if optional and text.upper() in NULLS:
        return None
    if not re.fullmatch(r"[0-9]{1,10}", text) or int(text) == 0:
        raise FreeSourceError(f"invalid {field}")
    return int(text)


def _accession(value: str | None) -> str:
    text = "" if value is None else value.strip()
    if ACCESSION.fullmatch(text) is None:
        raise FreeSourceError("invalid SEC accession")
    return text


def _text(value: str | None, field: str, *, optional: bool = False) -> str | None:
    text = "" if value is None else " ".join(value.split())
    if optional and text.upper() in NULLS:
        return None
    if not text or len(text) > 4096 or not text.isprintable():
        raise FreeSourceError(f"invalid {field}")
    return text


def parse_form_index(body: bytes) -> list[dict]:
    """Parse admitted Form 25 families from an EDGAR quarterly ``form.idx``."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_INDEX_BYTES:
        raise FreeSourceError("form index size is invalid")
    try:
        lines = body.decode("latin-1").splitlines()
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 is total
        raise FreeSourceError("form index encoding is invalid") from exc
    rows = []
    for line in lines:
        match = INDEX_ROW.match(line)
        if not match or match.group("form").upper() not in DELISTING_FORMS:
            continue
        accession = match.group("accession")
        if ACCESSION.fullmatch(accession) is None:
            raise FreeSourceError("form index accession is invalid")
        rows.append({
            "cik": _cik(match.group("cik"), "notice CIK"),
            "company": _text(match.group("company"), "notice company"),
            "form": match.group("form").upper(),
            "filed_date": _date(match.group("filed"), "notice filing date"),
            "accession": accession,
        })
    return rows


def load_form_index(con: duckdb.DuckDBPyConnection, body: bytes) -> dict:
    rows, source_sha = parse_form_index(body), hashlib.sha256(body).hexdigest()
    init_schema(con)
    before = con.execute("SELECT COUNT(*) FROM free_delisting_notices").fetchone()[0]
    with db.transaction(con):
        con.executemany(
            "INSERT OR IGNORE INTO free_delisting_notices VALUES (?,?,?,?,?,?)",
            [[r["cik"], r["company"], r["form"], r["filed_date"], r["accession"], source_sha]
             for r in rows],
        )
    after = con.execute("SELECT COUNT(*) FROM free_delisting_notices").fetchone()[0]
    return {"rows": len(rows), "inserted": after - before, "source_sha256": source_sha}


def parse_form25_xml(body: bytes) -> dict:
    """Extract exchange, security class and optional symbol from primary Form 25 XML."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_XML_BYTES:
        raise FreeSourceError("Form 25 XML size is invalid")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise FreeSourceError("Form 25 XML is invalid") from exc
    values: dict[str, list[str]] = {}
    nested: dict[tuple[str, str], list[str]] = {}
    for element in root.iter():
        name = re.sub(r"[^a-z]", "", element.tag.rsplit("}", 1)[-1].lower())
        value = " ".join("".join(element.itertext()).split())
        if value:
            values.setdefault(name, []).append(value)
        for child in element:
            child_name = re.sub(r"[^a-z]", "", child.tag.rsplit("}", 1)[-1].lower())
            child_value = " ".join("".join(child.itertext()).split())
            if child_value:
                nested.setdefault((name, child_name), []).append(child_value)

    def first(*names: str, optional: bool = False) -> str | None:
        found = []
        for name in names:
            found.extend(values.get(name, []))
        unique = list(dict.fromkeys(found))
        if not unique:
            if optional:
                return None
            raise FreeSourceError(f"Form 25 XML is missing {names[0]}")
        return _text(" | ".join(unique), f"Form 25 {names[0]}")

    exchange_names = nested.get(("exchange", "entityname"), [])
    exchange = _text(" | ".join(dict.fromkeys(exchange_names)), "Form 25 exchange") \
        if exchange_names else first("exchangename", "nameofexchange")
    return {
        "exchange": exchange,
        "security_class": first(
            "descriptionclasssecurity", "securityclasstitle", "titleofclass",
            "titleofsecurity", "securitydescription"
        ),
        "symbol": first("tickersymbol", "tradingsymbol", "issuersymbol", optional=True),
    }


def load_form25_detail(
    con: duckdb.DuckDBPyConnection, accession: str, body: bytes,
) -> dict:
    accession, row = _accession(accession), parse_form25_xml(body)
    source_sha = hashlib.sha256(body).hexdigest()
    init_schema(con)
    with db.transaction(con):
        before = con.execute(
            "SELECT COUNT(*) FROM free_delisting_notice_details WHERE accession=?", [accession]
        ).fetchone()[0]
        con.execute(
            "INSERT OR IGNORE INTO free_delisting_notice_details VALUES (?,?,?,?,?)",
            [accession, row["exchange"], row["security_class"], row["symbol"], source_sha],
        )
    return {"inserted": 1 - before, "source_sha256": source_sha, **row}


def _zip_tables(body: bytes) -> dict[str, tuple[bytes, int]]:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_ZIP_BYTES:
        raise FreeSourceError("insider archive size is invalid")
    wanted = {"SUBMISSION.TSV", "REPORTINGOWNER.TSV", "NONDERIV_TRANS.TSV"}
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if sum(item.file_size for item in members) > MAX_ZIP_EXPANDED_BYTES:
                raise FreeSourceError("insider archive expands beyond the size limit")
            for member in members:
                name = Path(member.filename).name.upper()
                if (name in wanted and not Path(member.filename).is_absolute()
                        and ".." not in Path(member.filename).parts and not member.flag_bits & 0x1):
                    if name in result:
                        raise FreeSourceError(f"duplicate insider member {name}")
                    result[name] = (archive.read(member), member.file_size)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FreeSourceError("insider archive is unreadable") from exc
    if set(result) != wanted:
        raise FreeSourceError("insider archive is missing a required table")
    return result


def _tsv(raw: bytes, required: frozenset[str], table: str) -> list[tuple[int, dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
    except UnicodeDecodeError as exc:
        raise FreeSourceError(f"{table} is not UTF-8") from exc
    fields = tuple(reader.fieldnames or ())
    if not required <= set(fields):
        raise FreeSourceError(f"{table} columns are invalid")
    rows = []
    for source_row, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise FreeSourceError(f"{table} row shape is invalid")
        rows.append((source_row, row))
    return rows


def _relationships(value: str | None) -> set[str]:
    text = "" if value is None else value.strip()
    relationships = {part.strip() for part in text.split(",") if part.strip()}
    allowed = {"Director", "Officer", "TenPercentOwner", "Other"}
    if not relationships <= allowed:
        raise FreeSourceError("invalid reporting-owner relationship")
    return relationships


def _decimal(value: str | None, field: str) -> Decimal | None:
    text = "" if value is None else value.strip()
    if text.upper() in NULLS:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise FreeSourceError(f"invalid {field}") from exc
    if not number.is_finite():
        raise FreeSourceError(f"invalid {field}")
    return number


def _acceptance(row: dict[str, str], filing_date: date) -> datetime | None:
    raw = next((row[key] for key in (
        "ACCEPTANCE_DATETIME", "ACCEPTANCE_TIME", "ACCEPTED_AT"
    ) if key in row and row[key].strip().upper() not in NULLS), None)
    if raw is None:
        return None
    try:
        if re.fullmatch(r"[0-9]{14}", raw.strip()):
            local = datetime.strptime(raw.strip(), "%Y%m%d%H%M%S").replace(tzinfo=EASTERN)
            accepted = local.astimezone(timezone.utc)
        else:
            accepted = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if accepted.utcoffset() is None:
                raise ValueError
            accepted = accepted.astimezone(timezone.utc)
    except ValueError as exc:
        raise FreeSourceError("invalid insider acceptance timestamp") from exc
    if accepted.astimezone(EASTERN).date() != filing_date:
        raise FreeSourceError("insider acceptance differs from filing date")
    return accepted


def parse_insider_zip(body: bytes) -> dict[str, list[dict]]:
    tables = _zip_tables(body)
    submissions = []
    for source_row, row in _tsv(tables["SUBMISSION.TSV"][0], SUBMISSION_FIELDS, "SUBMISSION"):
        filing = _date(row["FILING_DATE"], "insider filing date")
        symbol = _text(row["ISSUERTRADINGSYMBOL"], "issuer symbol", optional=True)
        submissions.append({
            "source_row": source_row, "accession": _accession(row["ACCESSION_NUMBER"]),
            "filing_date": filing,
            "period_of_report": _date(row["PERIOD_OF_REPORT"], "period of report", optional=True),
            "issuer_cik": _cik(row["ISSUERCIK"], "issuer CIK"),
            "issuer_name": _text(row["ISSUERNAME"], "issuer name"),
            "issuer_trading_symbol": symbol.upper() if symbol else None,
            "document_type": _text(row.get("DOCUMENT_TYPE"), "document type", optional=True),
            "accepted_at": _acceptance(row, filing), "available_on": filing,
        })
    accessions = {row["accession"] for row in submissions}
    owners = []
    for source_row, row in _tsv(tables["REPORTINGOWNER.TSV"][0], OWNER_FIELDS, "REPORTINGOWNER"):
        accession = _accession(row["ACCESSION_NUMBER"])
        if accession not in accessions:
            raise FreeSourceError("owner references an absent submission")
        relationships = _relationships(row["RPTOWNER_RELATIONSHIP"])
        owners.append({
            "source_row": source_row, "accession": accession,
            "owner_cik": _cik(row["RPTOWNERCIK"], "owner CIK", optional=True),
            "is_director": "Director" in relationships,
            "is_officer": "Officer" in relationships,
            "officer_title": _text(row["RPTOWNER_TITLE"], "officer title", optional=True),
            "is_ten_percent_owner": "TenPercentOwner" in relationships,
            "is_other": "Other" in relationships,
        })
    transactions = []
    for source_row, row in _tsv(tables["NONDERIV_TRANS.TSV"][0], TRANS_FIELDS, "NONDERIV_TRANS"):
        accession = _accession(row["ACCESSION_NUMBER"])
        if accession not in accessions:
            raise FreeSourceError("transaction references an absent submission")
        code = _text(row["TRANS_CODE"], "transaction code", optional=True)
        direction = _text(row["TRANS_ACQUIRED_DISP_CD"], "acquired/disposed", optional=True)
        ownership = _text(row["DIRECT_INDIRECT_OWNERSHIP"], "ownership", optional=True)
        transactions.append({
            "source_row": source_row, "accession": accession,
            "transaction_date": _date(row["TRANS_DATE"], "transaction date", optional=True),
            "code": code.upper() if code else None,
            "shares": _decimal(row["TRANS_SHARES"], "transaction shares"),
            "price_per_share": _decimal(row["TRANS_PRICEPERSHARE"], "transaction price"),
            "acquired_disposed": direction.upper() if direction else None,
            "shares_owned_after": _decimal(row["SHRS_OWND_FOLWNG_TRANS"], "owned shares"),
            "direct_indirect": ownership.upper() if ownership else None,
        })
    return {"submissions": submissions, "owners": owners, "transactions": transactions}


def load_insider_zip(con: duckdb.DuckDBPyConnection, body: bytes) -> dict:
    parsed, source_sha = parse_insider_zip(body), hashlib.sha256(body).hexdigest()
    init_schema(con)
    specs = (
        ("submissions", "free_insider_submissions", (
            "accession", "filing_date", "period_of_report", "issuer_cik", "issuer_name",
            "issuer_trading_symbol", "document_type", "accepted_at", "available_on")),
        ("owners", "free_insider_owners", (
            "accession", "owner_cik", "is_director", "is_officer", "officer_title",
            "is_ten_percent_owner", "is_other")),
        ("transactions", "free_insider_nonderiv_trans", (
            "accession", "transaction_date", "code", "shares", "price_per_share",
            "acquired_disposed", "shares_owned_after", "direct_indirect")),
    )
    result = {"source_sha256": source_sha}
    with db.transaction(con):
        for key, table, fields in specs:
            before = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE source_sha256=?", [source_sha]
            ).fetchone()[0]
            placeholders = ",".join("?" for _ in range(len(fields) + 2))
            con.executemany(
                f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})",
                [[*(row[field] for field in fields), source_sha, row["source_row"]]
                 for row in parsed[key]],
            )
            after = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE source_sha256=?", [source_sha]
            ).fetchone()[0]
            if after != len(parsed[key]):
                raise FreeSourceError(f"stored {key} differ from insider archive")
            result[key] = len(parsed[key])
            result[f"{key}_inserted"] = after - before
    return result


def parse_company_tickers(body: bytes) -> list[dict]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FreeSourceError("company tickers JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise FreeSourceError("company tickers shape is invalid")
    rows = []
    for source_row, key in enumerate(sorted(payload, key=lambda value: int(value)), 1):
        item = payload[key]
        if not isinstance(item, dict):
            raise FreeSourceError("company ticker row is invalid")
        ticker = _text(item.get("ticker"), "company ticker").upper()
        rows.append({"source_row": source_row, "cik": _cik(item.get("cik_str"), "company CIK"),
                     "ticker": ticker, "company": _text(item.get("title"), "company name")})
    return rows


def load_company_tickers(
    con: duckdb.DuckDBPyConnection, body: bytes, *, snapshot_date: date,
) -> dict:
    rows, source_sha = parse_company_tickers(body), hashlib.sha256(body).hexdigest()
    init_schema(con)
    before = con.execute(
        "SELECT COUNT(*) FROM free_company_tickers WHERE source_sha256=?", [source_sha]
    ).fetchone()[0]
    with db.transaction(con):
        con.executemany(
            "INSERT OR IGNORE INTO free_company_tickers VALUES (?,?,?,?,?,?)",
            [[row["cik"], row["ticker"], row["company"], snapshot_date, source_sha,
              row["source_row"]] for row in rows],
        )
    after = con.execute(
        "SELECT COUNT(*) FROM free_company_tickers WHERE source_sha256=?", [source_sha]
    ).fetchone()[0]
    if after != len(rows):
        raise FreeSourceError("stored company tickers differ from response")
    return {"rows": len(rows), "inserted": after - before, "source_sha256": source_sha}
