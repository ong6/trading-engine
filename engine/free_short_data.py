"""Offline parsers and isolated storage for public shorting-stress data."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb
import pandas as pd

from engine.free_sources import FreeSourceError
from engine.lib import db
from sim import nyse

MAX_RAW_BYTES = 512_000_000
MAX_EXPANDED_BYTES = 2_000_000_000
FOOTER_TIMESTAMP = re.compile(r"^(\d{8})(\d{6})$")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise FreeSourceError("ingestion time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _date(raw: object, field: str, pattern: str | None = None) -> date:
    text = str(raw).strip()
    try:
        parsed = datetime.strptime(text, pattern).date() if pattern else date.fromisoformat(text)
    except ValueError as exc:
        raise FreeSourceError(f"invalid {field}") from exc
    return parsed


def _integer(raw: object, field: str, *, optional: bool = False) -> int | None:
    text = str(raw or "").strip().replace(",", "")
    if optional and text in {"", ".", "NA", "N/A"}:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise FreeSourceError(f"invalid {field}") from exc
    if value < 0:
        raise FreeSourceError(f"invalid {field}")
    return value


def _decimal(raw: object, field: str, *, optional: bool = False) -> Decimal | None:
    text = str(raw or "").strip().replace(",", "")
    if optional and text in {"", ".", "NA", "N/A"}:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise FreeSourceError(f"invalid {field}") from exc
    if not value.is_finite() or value < 0:
        raise FreeSourceError(f"invalid {field}")
    return value


def _text(raw: object, field: str, *, optional: bool = False) -> str | None:
    value = " ".join(str(raw or "").split())
    if optional and not value:
        return None
    if not value or len(value) > 4096 or not value.isprintable():
        raise FreeSourceError(f"invalid {field}")
    return value


def finra_publication_date(settlement_date: date) -> date:
    """FINRA disseminates short interest on the seventh business day after settlement."""
    current = settlement_date
    for _ in range(7):
        current = nyse.next_session(current)
    return current


def ftd_publication_date(settlement_date: date) -> date:
    """Conservative SEC schedule: first half at month-end, second half on next-month day 15."""
    if settlement_date.day <= 15:
        return date(settlement_date.year, settlement_date.month,
                    monthrange(settlement_date.year, settlement_date.month)[1])
    if settlement_date.month == 12:
        return date(settlement_date.year + 1, 1, 15)
    return date(settlement_date.year, settlement_date.month + 1, 15)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS short_source_receipts (
        request_key VARCHAR PRIMARY KEY, source VARCHAR NOT NULL, url VARCHAR NOT NULL,
        source_sha256 VARCHAR NOT NULL, fetched_at TIMESTAMPTZ NOT NULL,
        measurement_start DATE, measurement_end DATE, publication_date DATE,
        row_count BIGINT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS finra_short_interest (
        settlement_date DATE NOT NULL, publication_date DATE NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL, symbol VARCHAR NOT NULL,
        issue_name VARCHAR NOT NULL, exchange VARCHAR, market_class VARCHAR,
        current_short BIGINT NOT NULL, previous_short BIGINT,
        average_daily_volume BIGINT, days_to_cover DECIMAL(18,6),
        revision_flag VARCHAR, source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS sec_fails_to_deliver (
        settlement_date DATE NOT NULL, publication_date DATE NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL, cusip VARCHAR NOT NULL,
        symbol VARCHAR NOT NULL, issuer_name VARCHAR NOT NULL,
        quantity BIGINT NOT NULL, price DECIMAL(20,6),
        source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS regsho_threshold (
        trade_date DATE NOT NULL, publication_date DATE NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL, venue VARCHAR NOT NULL,
        symbol VARCHAR NOT NULL, security_name VARCHAR NOT NULL,
        market_category VARCHAR, reg_sho_flag VARCHAR, rule_4320_flag VARCHAR,
        source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        PRIMARY KEY(source_sha256, source_row))""")
    con.execute("""CREATE TABLE IF NOT EXISTS short_ticker_map (
        dataset VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL, source_row BIGINT NOT NULL,
        mapped_ticker VARCHAR, collision BOOLEAN NOT NULL, match_basis VARCHAR NOT NULL,
        PRIMARY KEY(dataset, source_sha256, source_row))""")
    con.execute("""CREATE OR REPLACE MACRO short_data_asof(as_of) AS TABLE (
        SELECT 'finra_short_interest' AS dataset, 'FINRA' AS venue,
          s.settlement_date AS measurement_date, s.publication_date, s.ingested_at,
          s.symbol, m.mapped_ticker, COALESCE(m.collision,FALSE) AS ticker_collision,
          s.issue_name AS issuer_name, s.current_short AS quantity,
          NULL::DECIMAL(20,6) AS price, s.previous_short AS previous_quantity,
          s.average_daily_volume, s.days_to_cover, NULL::VARCHAR AS reg_sho_flag,
          NULL::VARCHAR AS rule_4320_flag, s.source_sha256, s.source_row
        FROM finra_short_interest s LEFT JOIN short_ticker_map m
          ON m.dataset='finra_short_interest' AND m.source_sha256=s.source_sha256
          AND m.source_row=s.source_row
        WHERE s.publication_date <= CAST(as_of AS DATE)
        UNION ALL
        SELECT 'sec_fails_to_deliver','SEC',s.settlement_date,s.publication_date,s.ingested_at,
          s.symbol,m.mapped_ticker,COALESCE(m.collision,FALSE),s.issuer_name,s.quantity,s.price,
          NULL::BIGINT,NULL::BIGINT,NULL::DECIMAL(18,6),NULL::VARCHAR,NULL::VARCHAR,
          s.source_sha256,s.source_row
        FROM sec_fails_to_deliver s LEFT JOIN short_ticker_map m
          ON m.dataset='sec_fails_to_deliver' AND m.source_sha256=s.source_sha256
          AND m.source_row=s.source_row
        WHERE s.publication_date <= CAST(as_of AS DATE)
        UNION ALL
        SELECT 'regsho_threshold',s.venue,s.trade_date,s.publication_date,s.ingested_at,
          s.symbol,m.mapped_ticker,COALESCE(m.collision,FALSE),s.security_name,
          NULL::BIGINT,NULL::DECIMAL(20,6),NULL::BIGINT,NULL::BIGINT,NULL::DECIMAL(18,6),
          s.reg_sho_flag,s.rule_4320_flag,s.source_sha256,s.source_row
        FROM regsho_threshold s LEFT JOIN short_ticker_map m
          ON m.dataset='regsho_threshold' AND m.source_sha256=s.source_sha256
          AND m.source_row=s.source_row
        WHERE s.publication_date <= CAST(as_of AS DATE))""")


def parse_finra_short_interest(body: bytes, *, settlement_date: date | None = None) -> list[dict]:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_RAW_BYTES:
        raise FreeSourceError("FINRA short-interest file size is invalid")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    fields = set(reader.fieldnames or ())
    current = {"symbolCode", "issueName", "currentShortPositionQuantity", "settlementDate"}
    standardized = {"issueSymbolIdentifier", "issueName", "currentShortShareNumber"}
    legacy = {"Security Symbol", "Security Name", "Current Shares Short"}
    if not (current <= fields or standardized <= fields or legacy <= fields):
        raise FreeSourceError("FINRA short-interest columns are invalid")
    rows = []
    for source_row, raw in enumerate(reader, 2):
        if None in raw or any(value is None for value in raw.values()):
            raise FreeSourceError("FINRA short-interest row shape is invalid")
        row_date = (_date(raw["settlementDate"], "settlement date") if current <= fields
                    else settlement_date)
        if row_date is None:
            raise FreeSourceError("legacy FINRA short interest needs a settlement date")
        modern = current <= fields or standardized <= fields
        symbol_key = ("symbolCode" if current <= fields else "issueSymbolIdentifier"
                      if standardized <= fields else "Security Symbol")
        name_key = "issueName" if modern else "Security Name"
        rows.append({
            "source_row": source_row, "settlement_date": row_date,
            "publication_date": finra_publication_date(row_date),
            "symbol": _text(raw[symbol_key], "FINRA symbol").upper(),
            "issue_name": _text(raw[name_key], "FINRA issue name"),
            "exchange": _text(raw.get("issuerServicesGroupExchangeCode"), "FINRA exchange",
                              optional=True),
            "market_class": _text(raw.get("marketClassCode") or raw.get("marketCategoryCode")
                                  or raw.get("OTC Market"),
                                  "FINRA market class", optional=True),
            "current_short": _integer(raw.get("currentShortPositionQuantity")
                                      or raw.get("currentShortShareNumber")
                                      or raw.get("Current Shares Short"), "current short"),
            "previous_short": _integer(raw.get("previousShortPositionQuantity")
                                       or raw.get("previousShortShareNumber")
                                       or raw.get("Previous Report Shares Short"),
                                       "previous short", optional=True),
            "average_daily_volume": _integer(raw.get("averageDailyVolumeQuantity")
                                             or raw.get("averageShortShareNumber")
                                             or raw.get("Average Daily Share Volume"),
                                             "average daily volume", optional=True),
            "days_to_cover": _decimal(raw.get("daysToCoverQuantity")
                                      or raw.get("daysToCoverNumber")
                                      or raw.get("Days to Cover"), "days to cover", optional=True),
            "revision_flag": _text(raw.get("revisionFlag"), "revision flag", optional=True),
        })
    return rows


def _safe_zip_members(body: bytes) -> list[tuple[str, bytes]]:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_RAW_BYTES:
        raise FreeSourceError("SEC FTD archive size is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            members = sorted((item for item in archive.infolist() if not item.is_dir()),
                             key=lambda item: item.filename)
            if (not members or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES
                    or any(Path(item.filename).is_absolute() or ".." in Path(item.filename).parts
                           or item.flag_bits & 0x1 for item in members)):
                raise FreeSourceError("SEC FTD archive members are unsafe")
            return [(item.filename, archive.read(item)) for item in members]
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FreeSourceError("SEC FTD archive is unreadable") from exc


def parse_sec_ftd(body: bytes) -> list[dict]:
    rows, source_row = [], 1
    required = {"SETTLEMENT DATE", "CUSIP", "SYMBOL", "QUANTITY (FAILS)",
                "DESCRIPTION", "PRICE"}
    for _, raw_member in _safe_zip_members(body):
        text = raw_member.decode("latin-1")
        lines = text.splitlines()
        trailer_at = next((index for index, line in enumerate(lines)
                           if line.startswith("Trailer record count ")), len(lines))
        trailer = lines[trailer_at:]
        reader = csv.DictReader(io.StringIO("\n".join(lines[:trailer_at])), delimiter="|")
        if not required <= set(reader.fieldnames or ()):
            raise FreeSourceError("SEC FTD columns are invalid")
        member_start = len(rows)
        for raw in reader:
            source_row += 1
            if None in raw or any(value is None for value in raw.values()):
                raise FreeSourceError("SEC FTD row shape is invalid")
            measured = _date(raw["SETTLEMENT DATE"], "FTD settlement date", "%Y%m%d")
            rows.append({
                "source_row": source_row, "settlement_date": measured,
                "publication_date": ftd_publication_date(measured),
                "cusip": _text(raw["CUSIP"], "FTD CUSIP"),
                "symbol": _text(raw["SYMBOL"], "FTD symbol").upper(),
                "issuer_name": _text(raw["DESCRIPTION"], "FTD issuer"),
                "quantity": _integer(raw["QUANTITY (FAILS)"], "FTD quantity"),
                "price": _decimal(raw["PRICE"], "FTD price", optional=True),
            })
        if trailer:
            try:
                expected_rows = int(trailer[0].removeprefix("Trailer record count ").strip())
            except ValueError as exc:
                raise FreeSourceError("SEC FTD trailer is invalid") from exc
            if len(rows) - member_start != expected_rows:
                raise FreeSourceError("SEC FTD trailer row count does not match")
    return rows


def parse_regsho_text(body: bytes, *, venue: str, trade_date: date) -> list[dict]:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_RAW_BYTES:
        raise FreeSourceError("Reg SHO file size is invalid")
    try:
        lines = [line for line in body.decode("utf-8-sig").splitlines() if line.strip()]
    except UnicodeDecodeError:
        lines = [line for line in body.decode("latin-1").splitlines() if line.strip()]
    if len(lines) < 2:
        raise FreeSourceError("Reg SHO file is incomplete")
    footer = FOOTER_TIMESTAMP.fullmatch(lines[-1].strip())
    if footer is None:
        raise FreeSourceError("Reg SHO file lacks a creation timestamp")
    published = _date(footer.group(1), "Reg SHO publication date", "%Y%m%d")
    reader = csv.DictReader(io.StringIO("\n".join(lines[:-1])), delimiter="|")
    fields = set(reader.fieldnames or ())
    symbol_field = "Symbol"
    name_field = "CompanyName" if "CompanyName" in fields else "Security Name"
    if symbol_field not in fields or name_field not in fields:
        raise FreeSourceError("Reg SHO columns are invalid")
    rows = []
    for source_row, raw in enumerate(reader, 2):
        if None in raw or any(value is None for value in raw.values()):
            raise FreeSourceError("Reg SHO row shape is invalid")
        rows.append({
            "source_row": source_row, "trade_date": trade_date,
            "publication_date": published, "venue": venue,
            "symbol": _text(raw[symbol_field], "Reg SHO symbol").upper(),
            "security_name": _text(raw[name_field], "Reg SHO security name"),
            "market_category": _text(raw.get("Market Category"), "market category", optional=True),
            "reg_sho_flag": _text(raw.get("Reg SHO Threshold Flag"), "Reg SHO flag",
                                  optional=True),
            "rule_4320_flag": _text(raw.get("Rule 3210"), "Rule 3210 flag", optional=True),
        })
    return rows


def parse_finra_otc_threshold(body: bytes, *, trade_date: date | None = None) -> list[dict]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FreeSourceError("FINRA OTC threshold response is not JSON") from exc
    if not isinstance(payload, list):
        raise FreeSourceError("FINRA OTC threshold response is not a list")
    rows = []
    for source_row, raw in enumerate(payload, 1):
        if not isinstance(raw, dict):
            raise FreeSourceError("FINRA OTC threshold row is invalid")
        measured = _date(raw.get("tradeDate"), "FINRA OTC trade date")
        if trade_date is not None and measured != trade_date:
            raise FreeSourceError("FINRA OTC threshold row has the wrong trade date")
        rows.append({
            "source_row": source_row, "trade_date": measured,
            "publication_date": measured, "venue": "FINRA OTC",
            "symbol": _text(raw.get("issueSymbolIdentifier"), "FINRA OTC symbol").upper(),
            "security_name": _text(raw.get("issueName"), "FINRA OTC issue name"),
            "market_category": _text(raw.get("marketCategoryDescription"), "market category",
                                     optional=True),
            "reg_sho_flag": _text(raw.get("regShoThresholdFlag"), "Reg SHO flag", optional=True),
            "rule_4320_flag": _text(raw.get("rule4320Flag"), "Rule 4320 flag", optional=True),
        })
    return rows


def load_rows(
    con: duckdb.DuckDBPyConnection, dataset: str, body: bytes, rows: list[dict],
    *, ingested_at: datetime,
) -> dict:
    init_schema(con)
    source_sha = hashlib.sha256(body).hexdigest()
    ingested = _utc(ingested_at)
    if dataset == "finra_short_interest":
        columns = ("settlement_date", "publication_date", "symbol", "issue_name", "exchange",
                   "market_class", "current_short", "previous_short", "average_daily_volume",
                   "days_to_cover", "revision_flag")
        table = dataset
    elif dataset == "sec_fails_to_deliver":
        columns = ("settlement_date", "publication_date", "cusip", "symbol", "issuer_name",
                   "quantity", "price")
        table = dataset
    elif dataset == "regsho_threshold":
        columns = ("trade_date", "publication_date", "venue", "symbol", "security_name",
                   "market_category", "reg_sho_flag", "rule_4320_flag")
        table = dataset
    else:  # pragma: no cover - internal caller contract
        raise ValueError(f"unknown short-data dataset {dataset}")
    before = con.execute(f"SELECT COUNT(*) FROM {table} WHERE source_sha256=?", [source_sha]).fetchone()[0]
    values = [[str(value) if isinstance(value, Decimal) else value
               for value in (row[column] for column in columns)] for row in rows]
    frame = pd.DataFrame(values, columns=list(columns))
    frame.insert(2, "ingested_at", ingested)
    frame["source_sha256"] = source_sha
    frame["source_row"] = [row["source_row"] for row in rows]
    with db.transaction(con):
        if not frame.empty:
            con.register("_short_batch", frame)
            try:
                con.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM _short_batch")
            finally:
                con.unregister("_short_batch")
    after = con.execute(f"SELECT COUNT(*) FROM {table} WHERE source_sha256=?", [source_sha]).fetchone()[0]
    if after != len(rows):
        raise FreeSourceError(f"stored {dataset} batch differs from its source")
    return {"source_sha256": source_sha, "rows": len(rows), "inserted": after - before}


def map_tickers(short_database: Path, reference_database: Path) -> dict:
    """Map exact symbols on their observation dates using both read-only P3 references."""
    if not reference_database.is_file():
        raise FreeSourceError("free-source reference database is missing")
    con = duckdb.connect(str(short_database))
    try:
        init_schema(con)
        escaped = str(reference_database).replace("'", "''")
        con.execute(f"ATTACH '{escaped}' AS reference (READ_ONLY)")
        con.execute("""CREATE OR REPLACE TEMP VIEW _short_observations AS
            SELECT 'finra_short_interest' dataset,source_sha256,source_row,symbol,
              settlement_date measurement_date FROM finra_short_interest
            UNION ALL SELECT 'sec_fails_to_deliver',source_sha256,source_row,symbol,
              settlement_date FROM sec_fails_to_deliver
            UNION ALL SELECT 'regsho_threshold',source_sha256,source_row,symbol,
              trade_date FROM regsho_threshold""")
        con.execute("""CREATE OR REPLACE TEMP VIEW _latest_master AS SELECT *
            FROM reference.free_security_master WHERE source_sha256=(
              SELECT source_sha256 FROM reference.free_security_master
              ORDER BY fetched_at DESC,source_sha256 DESC LIMIT 1)""")
        with db.transaction(con):
            con.execute("""INSERT OR IGNORE INTO short_ticker_map
                WITH matches AS (
                  SELECT o.dataset,o.source_sha256,o.source_row,o.symbol,
                    COUNT(DISTINCT m.source_row) AS tiingo_matches,
                    COUNT(DISTINCT h.cik) AS cik_matches
                  FROM _short_observations o
                  LEFT JOIN _latest_master m ON m.ticker=o.symbol
                    AND m.start_date<=o.measurement_date
                    AND (m.end_date IS NULL OR m.end_date>=o.measurement_date)
                  LEFT JOIN reference.free_cik_ticker_history h ON h.ticker=o.symbol
                    AND h.first_seen<=o.measurement_date AND h.last_seen>=o.measurement_date
                  GROUP BY o.dataset,o.source_sha256,o.source_row,o.symbol)
                SELECT dataset,source_sha256,source_row,
                  CASE WHEN tiingo_matches+cik_matches>0 THEN symbol END,
                  tiingo_matches>1 OR cik_matches>1,
                  CASE WHEN tiingo_matches>0 AND cik_matches>0 THEN 'tiingo+cik'
                       WHEN tiingo_matches>0 THEN 'tiingo'
                       WHEN cik_matches>0 THEN 'cik' ELSE 'unmatched' END
                FROM matches""")
        total, matched, collisions = con.execute("""SELECT COUNT(*),
            COUNT(mapped_ticker),COUNT(*) FILTER (WHERE collision) FROM short_ticker_map""").fetchone()
        return {"total": total, "matched": matched, "collisions": collisions,
                "match_rate": matched / total if total else None}
    finally:
        con.close()

