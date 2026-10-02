#!/usr/bin/env python3
"""Capture and audit P3's isolated public shorting-stress sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import duckdb
import requests

from engine import free_short_data
from engine.free_sources import FreeSourceError
from engine.lib import db
from engine.lib.resources import write_text_atomic
from sim import nyse
from tools.free_sec import _load_contact
from tools.free_sources import _network_permitted

DEFAULT_DATA_DIR = Path.home() / "trading-engine/store/pit/short-data"
DEFAULT_DATABASE = Path.home() / "trading-engine/store/pit/short-data.duckdb"
DEFAULT_REFERENCE_DATABASE = Path.home() / "trading-engine/store/pit/free-sources.duckdb"
FINRA_STATIC_INDEX = (
    "https://otce.finra.org/otce/assets/archives/equityShortInterest/equityShortInterest.json"
)
FINRA_PARTITIONS = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"
FINRA_CDN = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{stamp}.csv"
FINRA_OTC_PARTITIONS = "https://api.finra.org/partitions/group/otcMarket/name/vwthresholdList"
FINRA_OTC_DATA = "https://api.finra.org/data/group/otcMarket/name/vwthresholdList"
SEC_FTD_PAGE = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{stamp}.txt"
NYSE_URL = (
    "https://www.nyse.com/api/regulatory/threshold-securities/download"
    "?selectedDate={date}&market="
)
CBOE_URL = (
    "https://cdn.cboe.com/resources/us/equities/market-statistics/reg-sho-threshold/"
    "bzx_equities_reg_sho_threshold_{stamp}.txt"
)
USER_AGENT = "trading-engine-short-data-research/1"
REQUEST_INTERVAL_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 90
SOURCE_STARTS = {"nasdaq": date(2005, 1, 7), "nyse": date(2005, 1, 3),
                 "cboe": date(2014, 8, 20)}


class _NotFound(FreeSourceError):
    pass


@dataclass(frozen=True)
class Response:
    body: bytes
    sha256: str
    fetched_at: datetime
    resumed: bool
    url: str


class Pacer:
    """One-at-a-time, process-local request pacing with a pre-dispatch window check."""

    def __init__(
        self, interval: float = REQUEST_INTERVAL_SECONDS,
        *, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.interval, self.clock, self.sleep, self.now = interval, clock, sleep, now
        self.last_started: float | None = None

    def reserve(self) -> None:
        current = self.clock()
        if self.last_started is not None:
            remaining = self.interval - (current - self.last_started)
            if remaining > 0:
                self.sleep(remaining)
        if not _network_permitted(self.now()):
            raise FreeSourceError("network request is inside a configured no-call window")
        self.last_started = self.clock()


class CachedClient:
    def __init__(
        self, con: duckdb.DuckDBPyConnection, data_dir: Path, *,
        session: requests.Session | None = None, pacer: Pacer | None = None,
        sec_contact: str | None = None,
    ) -> None:
        self.con, self.data_dir = con, Path(data_dir)
        self.session = session or requests.Session()
        self.owned_session = session is None
        self.pacer = pacer or Pacer()
        self.sec_contact = sec_contact

    def close(self) -> None:
        if self.owned_session:
            self.session.close()

    def get(self, source: str, url: str, *, method: str = "GET", payload: dict | None = None,
            suffix: str = ".raw", request_key: str | None = None) -> Response:
        key = request_key or f"{method}:{url}:{json.dumps(payload, sort_keys=True)}"
        stored = self.con.execute(
            "SELECT source_sha256,fetched_at FROM short_source_receipts WHERE request_key=?", [key]
        ).fetchone()
        if stored:
            path = self.data_dir / source / f"{stored[0]}{suffix}"
            try:
                body = path.read_bytes()
            except OSError as exc:
                raise FreeSourceError(f"cached {source} response is missing") from exc
            if hashlib.sha256(body).hexdigest() != stored[0]:
                raise FreeSourceError(f"cached {source} response failed its SHA-256 check")
            fetched = stored[1]
            if fetched.utcoffset() is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            return Response(body, stored[0], fetched, True, url)
        if self.con.execute(
            "SELECT 1 FROM short_source_misses WHERE request_key=?", [key]
        ).fetchone():
            raise _NotFound(f"previously missing source response: {url}")
        self.pacer.reserve()
        headers = {"User-Agent": self.sec_contact if source == "sec_ftd" else USER_AGENT}
        headers["Accept"] = "application/json" if payload is not None else "*/*"
        try:
            response = self.session.request(
                method, url, json=payload, headers=headers, timeout=HTTP_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise FreeSourceError(f"{source} request failed") from exc
        if response.status_code == 404:
            with db.transaction(self.con):
                self.con.execute("INSERT OR IGNORE INTO short_source_misses VALUES (?,?,?,?,?)", [
                    key, source, url, datetime.now(timezone.utc), 404,
                ])
            raise _NotFound(f"{source} request returned HTTP 404: {url}")
        if response.status_code != 200:
            raise FreeSourceError(f"{source} request returned HTTP {response.status_code}: {url}")
        body = bytes(response.content)
        if not 0 < len(body) <= free_short_data.MAX_RAW_BYTES:
            raise FreeSourceError(f"{source} response size is invalid")
        digest = hashlib.sha256(body).hexdigest()
        self._write_private(self.data_dir / source / f"{digest}{suffix}", body)
        return Response(body, digest, datetime.now(timezone.utc), False, url)

    @staticmethod
    def _write_private(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
                raise FreeSourceError("short-data cache conflicts with its content identity")
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                             delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _receipt(
    con: duckdb.DuckDBPyConnection, response: Response, source: str, *,
    request_key: str, rows: list[dict], publication_date: date | None = None,
    measurement_date: date | None = None,
) -> None:
    measured = [row.get("settlement_date") or row.get("trade_date") for row in rows]
    published = [row["publication_date"] for row in rows]
    with db.transaction(con):
        con.execute("""INSERT INTO short_source_receipts VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(request_key) DO UPDATE SET
              measurement_start=COALESCE(short_source_receipts.measurement_start,
                                         excluded.measurement_start),
              measurement_end=COALESCE(short_source_receipts.measurement_end,
                                       excluded.measurement_end),
              publication_date=COALESCE(short_source_receipts.publication_date,
                                        excluded.publication_date),
              row_count=excluded.row_count""", [
            request_key, source, response.url, response.sha256, response.fetched_at,
            min(measured) if measured else measurement_date,
            max(measured) if measured else measurement_date,
            publication_date or (max(published) if published else None), len(rows),
        ])


def _manifest(
    client: CachedClient, source: str, url: str, parser: Callable[[bytes], object],
    *, suffix: str,
) -> object:
    key = f"GET:{url}:null"
    response = client.get(source, url, suffix=suffix, request_key=key)
    parsed = parser(response.body)
    _receipt(client.con, response, source, request_key=key, rows=[])
    return parsed


def _json_object(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FreeSourceError("source manifest is not JSON") from exc
    if not isinstance(value, dict):
        raise FreeSourceError("source manifest is not an object")
    return value


def _json_list(body: bytes) -> list:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FreeSourceError("source manifest is not JSON") from exc
    if not isinstance(value, list):
        raise FreeSourceError("source manifest is not a list")
    return value


def _bounded(items: Iterable, max_files: int | None) -> list:
    values = list(items)
    return values if max_files is None else values[:max_files]


def _resumed_rows(con: duckdb.DuckDBPyConnection, request_key: str) -> int | None:
    row = con.execute(
        "SELECT row_count FROM short_source_receipts WHERE request_key=?", [request_key]
    ).fetchone()
    return int(row[0]) if row is not None else None


def _record_resume(totals: dict, count: int) -> None:
    totals["files"] += 1
    totals["rows"] += count
    totals["resumed"] += 1


def capture_finra_short_interest(client: CachedClient, max_files: int | None = None) -> dict:
    static = _manifest(client, "finra_short_interest", FINRA_STATIC_INDEX, _json_list,
                       suffix=".json")
    partitions = _manifest(client, "finra_short_interest", FINRA_PARTITIONS, _json_object,
                           suffix=".json")
    targets: dict[date, str] = {}
    for item in static:
        measured = datetime.strptime(item["date"], "%m/%d/%Y").date()
        # The official manifest transposes January 15, 2019; filenames otherwise use YYYYDDMM.
        filename = f"shrt{measured.strftime('%Y%d%m')}.txt"
        targets[measured] = urljoin(
            "https://otce.finra.org/otce/", f"assets/archives/equityShortInterest/{filename}"
        )
    for item in partitions.get("availablePartitions", []):
        measured = date.fromisoformat(item["partitions"][0])
        if measured not in targets:
            targets[measured] = FINRA_CDN.format(stamp=measured.strftime("%Y%m%d"))
    totals = {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
    for measured, url in _bounded(sorted(targets.items()), max_files):
        key = f"GET:{url}:null"
        response = client.get("finra_short_interest", url,
                              suffix=Path(url).suffix, request_key=key)
        if response.resumed and (count := _resumed_rows(client.con, key)) is not None:
            _record_resume(totals, count)
            continue
        rows = free_short_data.parse_finra_short_interest(response.body, settlement_date=measured)
        result = free_short_data.load_rows(
            client.con, "finra_short_interest", response.body, rows,
            ingested_at=response.fetched_at,
        )
        _receipt(client.con, response, "finra_short_interest", request_key=key, rows=rows)
        totals["files"] += 1
        totals["rows"] += result["rows"]
        totals["inserted"] += result["inserted"]
        totals["resumed"] += int(response.resumed)
    return totals


def _ftd_links(body: bytes) -> list[str]:
    text = body.decode("utf-8")
    paths = re.findall(r'href="([^\"]*cns[^\"]+\.zip)"', text, flags=re.IGNORECASE)
    links = sorted({urljoin(SEC_FTD_PAGE, path.replace("&amp;", "&")) for path in paths})
    if len(links) < 400:
        raise FreeSourceError("SEC FTD page did not expose the historical archive")
    return links


def capture_sec_ftd(client: CachedClient, max_files: int | None = None) -> dict:
    links = _manifest(client, "sec_ftd", SEC_FTD_PAGE, _ftd_links, suffix=".html")
    totals = {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
    for url in _bounded(links, max_files):
        key = f"GET:{url}:null"
        response = client.get("sec_ftd", url, suffix=".zip", request_key=key)
        if response.resumed and (count := _resumed_rows(client.con, key)) is not None:
            _record_resume(totals, count)
            continue
        rows = free_short_data.parse_sec_ftd(response.body)
        result = free_short_data.load_rows(
            client.con, "sec_fails_to_deliver", response.body, rows,
            ingested_at=response.fetched_at,
        )
        _receipt(client.con, response, "sec_ftd", request_key=key, rows=rows)
        totals["files"] += 1
        totals["rows"] += result["rows"]
        totals["inserted"] += result["inserted"]
        totals["resumed"] += int(response.resumed)
    return totals


def _session_dates(start: date, end: date) -> list[date]:
    result = []
    while start <= end:
        if nyse.is_session(start):
            result.append(start)
        start += timedelta(days=1)
    return result


def _finra_otc_dates(client: CachedClient) -> list[date]:
    manifest = _manifest(client, "finra_otc", FINRA_OTC_PARTITIONS, _json_object, suffix=".json")
    return sorted(date.fromisoformat(item["partitions"][0])
                  for item in manifest.get("availablePartitions", []))


def capture_regsho(
    client: CachedClient, venue: str, *, start: date | None = None, end: date | None = None,
    max_files: int | None = None,
) -> dict:
    venue = venue.lower()
    if venue == "finra_otc":
        dates = _finra_otc_dates(client)
    elif venue in SOURCE_STARTS:
        dates = _session_dates(start or SOURCE_STARTS[venue], end or (date.today() - timedelta(days=1)))
    else:
        raise ValueError(f"unknown Reg SHO venue {venue}")
    if start:
        dates = [value for value in dates if value >= start]
    if end:
        dates = [value for value in dates if value <= end]
    if venue == "finra_otc":
        if not dates:
            return {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
        return _capture_finra_otc_pages(client, dates[0], dates[-1], max_files)
    totals = {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
    for measured in _bounded(dates, max_files):
        stamp = measured.strftime("%Y%m%d")
        template = {"nasdaq": NASDAQ_URL, "nyse": NYSE_URL, "cboe": CBOE_URL}[venue]
        url = template.format(stamp=stamp, date=measured.isoformat())
        key = f"GET:{url}:null"
        try:
            response = client.get(venue, url, suffix=".txt", request_key=key)
        except _NotFound:
            continue
        if response.resumed and (count := _resumed_rows(client.con, key)) is not None:
            _record_resume(totals, count)
            continue
        rows = free_short_data.parse_regsho_text(
            response.body, venue={"nasdaq": "Nasdaq", "nyse": "NYSE", "cboe": "Cboe"}[venue],
            trade_date=measured,
        )
        result = free_short_data.load_rows(
            client.con, "regsho_threshold", response.body, rows,
            ingested_at=response.fetched_at,
        )
        _receipt(client.con, response, venue, request_key=key, rows=rows,
                 measurement_date=measured)
        totals["files"] += 1
        totals["rows"] += result["rows"]
        totals["inserted"] += result["inserted"]
        totals["resumed"] += int(response.resumed)
    return totals


def _capture_finra_otc_pages(
    client: CachedClient, start: date, end: date, max_pages: int | None,
) -> dict:
    totals = {"files": 0, "rows": 0, "inserted": 0, "resumed": 0}
    offset, limit = 0, 5000
    while max_pages is None or totals["files"] < max_pages:
        payload = {"limit": limit, "offset": offset, "dateRangeFilters": [{
            "fieldName": "tradeDate", "startDate": start.isoformat(), "endDate": end.isoformat(),
        }]}
        key = f"POST:{FINRA_OTC_DATA}:{start}:{end}:{offset}"
        response = client.get("finra_otc", FINRA_OTC_DATA, method="POST", payload=payload,
                              suffix=".json", request_key=key)
        if response.resumed and (count := _resumed_rows(client.con, key)) is not None:
            _record_resume(totals, count)
            if count < limit:
                break
            offset += limit
            continue
        rows = free_short_data.parse_finra_otc_threshold(response.body)
        result = free_short_data.load_rows(
            client.con, "regsho_threshold", response.body, rows,
            ingested_at=response.fetched_at,
        )
        _receipt(client.con, response, "finra_otc", request_key=key, rows=rows)
        totals["files"] += 1
        totals["rows"] += result["rows"]
        totals["inserted"] += result["inserted"]
        totals["resumed"] += int(response.resumed)
        if len(rows) < limit:
            break
        offset += limit
    return totals


def audit(database: Path) -> dict:
    con = duckdb.connect(str(database), read_only=True)
    try:
        coverage = con.execute("""WITH facts AS (
            SELECT 'FINRA short interest' source,settlement_date measured FROM finra_short_interest
            UNION ALL SELECT 'SEC FTD',settlement_date FROM sec_fails_to_deliver
            UNION ALL SELECT venue,trade_date FROM regsho_threshold)
          SELECT source,EXTRACT(year FROM measured)::INTEGER year,COUNT(*) rows,
            COUNT(DISTINCT measured) dates FROM facts GROUP BY source,year ORDER BY source,year""").fetchall()
        ranges = con.execute("""WITH facts AS (
            SELECT 'FINRA short interest' source,settlement_date measured FROM finra_short_interest
            UNION ALL SELECT 'SEC FTD',settlement_date FROM sec_fails_to_deliver
            UNION ALL SELECT venue,trade_date FROM regsho_threshold)
          SELECT source,MIN(measured),MAX(measured),COUNT(*) FROM facts GROUP BY source ORDER BY source""").fetchall()
        matches = con.execute("""SELECT dataset,COUNT(*) total,COUNT(mapped_ticker) matched,
            COUNT(*) FILTER(WHERE collision) collisions
          FROM short_ticker_map GROUP BY dataset ORDER BY dataset""").fetchall()
        lags = con.execute("""WITH facts AS (
            SELECT 'FINRA short interest' source,date_diff('day',settlement_date,publication_date) lag
              FROM finra_short_interest
            UNION ALL SELECT 'SEC FTD',date_diff('day',settlement_date,publication_date)
              FROM sec_fails_to_deliver
            UNION ALL SELECT venue,date_diff('day',trade_date,publication_date)
              FROM regsho_threshold)
          SELECT source,MIN(lag),quantile_cont(lag,.5),quantile_cont(lag,.9),MAX(lag)
          FROM facts GROUP BY source ORDER BY source""").fetchall()
        limitations = con.execute("""SELECT
            COUNT(*) FILTER(WHERE settlement_date<'2021-06-01') pre_2021_rows,
            COUNT(DISTINCT settlement_date) FILTER(WHERE settlement_date<'2021-06-01') pre_2021_dates,
            MIN(settlement_date),MAX(settlement_date) FROM finra_short_interest""").fetchone()
    finally:
        con.close()
    match_rows = [{"dataset": row[0], "total": row[1], "matched": row[2],
                   "collisions": row[3], "match_rate": row[2] / row[1] if row[1] else None}
                  for row in matches]
    return {
        "coverage": [{"source": r[0], "year": r[1], "rows": r[2], "dates": r[3]}
                     for r in coverage],
        "ranges": [{"source": r[0], "start": r[1].isoformat(), "end": r[2].isoformat(),
                    "rows": r[3]} for r in ranges],
        "matches": match_rows,
        "match_rate": (sum(r["matched"] for r in match_rows) /
                       sum(r["total"] for r in match_rows)) if match_rows else None,
        "lags": [{"source": r[0], "min": r[1], "median": float(r[2]),
                  "p90": float(r[3]), "max": r[4]} for r in lags],
        "finra_pre_2021": {"rows": limitations[0], "dates": limitations[1],
                           "start": limitations[2].isoformat(), "end": limitations[3].isoformat()},
    }


def render_audit(result: dict) -> str:
    lines = ["# P3 shorting-stress data audit — 2026-10-02", "", "## Method", "",
             "All raw responses are held outside Git in a content-addressed owner-only cache.",
             "The isolated database records measurement, official publication, and ingestion",
             "clocks. `short_data_asof(as_of)` excludes rows before publication. Exact symbols",
             "are matched on observation date against the read-only Tiingo listing intervals and",
             "SEC CIK/ticker history; ambiguous reference intervals are flagged, not guessed.", "",
             "## Overall ranges", "", "| Source | First date | Last date | Rows |",
             "|---|---|---|---:|"]
    lines.extend(f"| {r['source']} | {r['start']} | {r['end']} | {r['rows']:,} |"
                 for r in result["ranges"])
    lines += ["",
             "## Coverage by source and year", "",
             "| Source | Year | Rows | Dates |", "|---|---:|---:|---:|"]
    lines.extend(f"| {r['source']} | {r['year']} | {r['rows']:,} | {r['dates']:,} |"
                 for r in result["coverage"])
    lines += ["", "## Ticker mapping", "", "| Dataset | Rows | Matched | Match rate | Collisions |",
              "|---|---:|---:|---:|---:|"]
    lines.extend(f"| {r['dataset']} | {r['total']:,} | {r['matched']:,} | "
                 f"{100 * r['match_rate']:.1f}% | {r['collisions']:,} |"
                 for r in result["matches"])
    lines += ["", "## Publication lag distribution", "",
              "Calendar days from measurement/settlement through official publication.", "",
              "| Source | Min | Median | P90 | Max |", "|---|---:|---:|---:|---:|"]
    lines.extend(f"| {r['source']} | {r['min']} | {r['median']:.1f} | {r['p90']:.1f} | {r['max']} |"
                 for r in result["lags"])
    limitation = result["finra_pre_2021"]
    lines += ["", "## Source limitations", "",
              f"FINRA coverage is {limitation['start']} through {limitation['end']}. The "
              f"{limitation['rows']:,} rows on {limitation['dates']:,} settlement dates before "
              "June 2021 are OTC-only; exchange-listed consolidated history is unavailable there.",
              "FINRA publication is the seventh business day after settlement. SEC FTD uses the",
              "SEC's stated availability schedule: month-end for first-half data and the 15th of",
              "the next month for second-half data; the SEC cautions that posting can be later.",
              "SEC FTD is an aggregate outstanding settlement balance, not short interest and not",
              "a daily flow. Threshold membership is a venue list, not evidence of abusive shorting.",
              "CUSIPs remain only in the private raw cache and isolated local database.", ""]
    return "\n".join(lines)


def _parse_date(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("finra", "ftd", "nasdaq", "nyse", "cboe",
                                            "finra-otc", "all", "map", "audit"))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--reference-database", type=Path, default=DEFAULT_REFERENCE_DATABASE)
    parser.add_argument("--start-date", type=_parse_date)
    parser.add_argument("--end-date", type=_parse_date)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.max_files is not None and args.max_files < 1:
        parser.error("--max-files must be positive")
    try:
        if args.command == "map":
            result = free_short_data.map_tickers(args.database, args.reference_database)
        elif args.command == "audit":
            result = audit(args.database)
            if args.output:
                write_text_atomic(args.output, render_audit(result))
        else:
            args.database.parent.mkdir(parents=True, exist_ok=True)
            con = db.connect(args.database, wait_s=0)
            free_short_data.init_schema(con)
            sec_contact = _load_contact() if args.command in {"ftd", "all"} else None
            client = CachedClient(con, args.data_dir, sec_contact=sec_contact)
            try:
                result = {}
                if args.command in {"finra", "all"}:
                    result["finra"] = capture_finra_short_interest(client, args.max_files)
                if args.command in {"ftd", "all"}:
                    result["ftd"] = capture_sec_ftd(client, args.max_files)
                venues = ("nasdaq", "nyse", "cboe", "finra_otc") if args.command == "all" \
                    else (args.command.replace("-", "_"),)
                for venue in venues:
                    if venue in {"nasdaq", "nyse", "cboe", "finra_otc"}:
                        result[venue] = capture_regsho(
                            client, venue, start=args.start_date, end=args.end_date,
                            max_files=args.max_files,
                        )
            finally:
                client.close()
                con.close()
            result["mapping"] = free_short_data.map_tickers(args.database,
                                                             args.reference_database)
    except (FreeSourceError, ValueError, OSError, duckdb.Error) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "complete", "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
