"""Offline census for P3's content-addressed frozen Kaggle price archive."""
from __future__ import annotations

import hashlib
import math
import re
import zipfile
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import duckdb

from engine.lib import db
from sim import nyse

ARCHIVE_SOURCE = "kaggle_huge_stock_market_dataset_v3"
ARCHIVE_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "borismarjanovic/price-volume-data-for-all-us-stocks-etfs"
)
DATASET_PAGE = (
    "https://www.kaggle.com/datasets/borismarjanovic/"
    "price-volume-data-for-all-us-stocks-etfs"
)
LICENSE = "CC0: Public Domain"
PRICE_BASIS = "adjusted_current_vintage"
EXPECTED_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume", "OpenInt")
MEMBER = re.compile(r"^Data/(Stocks|ETFs)/([a-z0-9_`^.-]+)\.us\.txt$")
ENDED_SESSION_LAG = 30
GAP_FLAG_DAYS = 45
PRICE_JUMP_FLAG = 10.0
SAMPLE_PER_YEAR = 15
DECISION_THRESHOLD = 0.30
KNOWN_SPLITS = {
    "AAPL": (date(2014, 6, 9), 7.0),
    "AIG": (date(2009, 7, 1), 0.05),
    "BIDU": (date(2010, 5, 12), 10.0),
    "C": (date(2011, 5, 9), 0.1),
    "CSCO": (date(2000, 3, 23), 2.0),
    "ISRG": (date(2017, 10, 6), 3.0),
    "MSFT": (date(2003, 2, 18), 2.0),
    "NFLX": (date(2015, 7, 15), 7.0),
    "NKE": (date(2015, 12, 24), 2.0),
    "SBUX": (date(2015, 4, 9), 2.0),
}


class FrozenArchiveError(ValueError):
    """The archive or a reference violates the frozen-census contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(raw: bytes, field: str, line_number: int, *, positive: bool | None) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise FrozenArchiveError(f"line {line_number} {field} is not numeric") from exc
    if (
        not math.isfinite(value)
        or (positive is True and value <= 0)
        or (positive is False and value < 0)
    ):
        raise FrozenArchiveError(f"line {line_number} {field} is invalid")
    return value


def parse_price_file(body: bytes, member_name: str) -> list[dict]:
    """Parse one exact archive member, preserving adjusted OHLCV values."""
    if not isinstance(body, bytes):
        raise FrozenArchiveError("price member must be bytes")
    if not body:
        return []
    lines = body.splitlines()
    try:
        columns = tuple(part.decode("ascii") for part in lines[0].split(b","))
    except UnicodeDecodeError as exc:
        raise FrozenArchiveError(f"{member_name} header is not ASCII") from exc
    if columns != EXPECTED_COLUMNS:
        raise FrozenArchiveError(f"{member_name} columns are invalid")
    rows: list[dict] = []
    prior_date = None
    for line_number, line in enumerate(lines[1:], 2):
        fields = line.split(b",")
        if len(fields) != len(EXPECTED_COLUMNS):
            raise FrozenArchiveError(f"{member_name} line {line_number} shape is invalid")
        try:
            session_date = date.fromisoformat(fields[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FrozenArchiveError(
                f"{member_name} line {line_number} date is invalid"
            ) from exc
        if prior_date is not None and session_date <= prior_date:
            raise FrozenArchiveError(f"{member_name} dates are not strictly increasing")
        # The archive uses zero as a missing-value sentinel in some OHLC fields. Keep it
        # visible for the census; an ingest would have to reject those rows.
        o, h, low, c = (
            _number(fields[index], name, line_number, positive=None)
            for index, name in enumerate(("open", "high", "low", "close"), 1)
        )
        volume = _number(fields[5], "volume", line_number, positive=False)
        open_interest = _number(fields[6], "open interest", line_number, positive=False)
        ohlc_consistent = h >= max(o, low, c) and low <= min(o, h, c)
        rows.append({
            "date": session_date,
            "o": o,
            "h": h,
            "l": low,
            "c": c,
            "v": volume,
            "open_interest": open_interest,
            "ohlc_consistent": ohlc_consistent,
        })
        prior_date = session_date
    return rows


def _sessions(start: date, end: date) -> list[date]:
    sessions = []
    current = start
    while current <= end:
        if nyse.is_session(current):
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def _session_distance(sessions: list[date], left: date, right: date) -> int:
    if left == right:
        return 0
    earlier, later = sorted((left, right))
    return bisect_right(sessions, later) - bisect_right(sessions, earlier)


def _member_identity(filename: str) -> tuple[str, str]:
    match = MEMBER.fullmatch(filename)
    if match is None:
        raise FrozenArchiveError(f"unexpected archive member {filename!r}")
    return match.group(1), match.group(2).upper()


def _split_check(ticker: str, rows: list[dict]) -> dict | None:
    event = KNOWN_SPLITS.get(ticker)
    if event is None or len(rows) < 2:
        return None
    ex_date, ratio = event
    dates = [row["date"] for row in rows]
    index = bisect_left(dates, ex_date)
    if index == 0 or index == len(rows):
        return None
    before, after = rows[index - 1], rows[index]
    observed = after["c"] / before["c"]
    raw_expected = 1.0 / ratio
    adjusted_distance = abs(math.log(observed))
    raw_distance = abs(math.log(observed / raw_expected))
    return {
        "ticker": ticker,
        "ex_date": ex_date.isoformat(),
        "split_ratio": ratio,
        "before_date": before["date"].isoformat(),
        "after_date": after["date"].isoformat(),
        "before_close": before["c"],
        "after_close": after["c"],
        "observed_post_pre": observed,
        "raw_expected_post_pre": raw_expected,
        "adjusted_like": adjusted_distance < raw_distance,
    }


def _security_census(kind: str, ticker: str, rows: list[dict]) -> tuple[dict, dict | None]:
    gap_events = 0
    jump_events = 0
    max_gap_days = 0
    max_close_ratio = 0.0
    for before, after in zip(rows, rows[1:], strict=False):
        gap_days = (after["date"] - before["date"]).days
        if before["c"] <= 0 or after["c"] <= 0:
            continue
        close_ratio = max(after["c"] / before["c"], before["c"] / after["c"])
        max_gap_days = max(max_gap_days, gap_days)
        max_close_ratio = max(max_close_ratio, close_ratio)
        gap_events += gap_days > GAP_FLAG_DAYS
        jump_events += close_ratio >= PRICE_JUMP_FLAG
    security = {
        "kind": kind,
        "ticker": ticker,
        "first_date": rows[0]["date"].isoformat() if rows else None,
        "last_date": rows[-1]["date"].isoformat() if rows else None,
        "row_count": len(rows),
        "incomplete_ohlc_rows": sum(
            any(row[field] <= 0 for field in ("o", "h", "l", "c")) for row in rows
        ),
        "inconsistent_ohlc_rows": sum(not row["ohlc_consistent"] for row in rows),
        "gap_events": gap_events,
        "price_jump_events": jump_events,
        "max_gap_days": max_gap_days,
        "max_close_ratio": max_close_ratio,
        "ticker_reuse_flag": bool(gap_events or jump_events),
    }
    return security, _split_check(ticker, rows)


def census_archive(archive_path: Path) -> dict:
    """Validate the ZIP and return its complete per-security census."""
    archive_path = Path(archive_path)
    if not archive_path.is_file() or archive_path.is_symlink():
        raise FrozenArchiveError("archive must be a regular file")
    source_sha = _sha256(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in files}
            if len(names) != len(files):
                raise FrozenArchiveError("archive contains duplicate member names")
            canonical = [item for item in files if item.filename.startswith("Data/")]
            expected = {item.filename for item in canonical}
            expected.update(item.filename.removeprefix("Data/") for item in canonical)
            if names != expected:
                raise FrozenArchiveError("archive is not one canonical tree and one exact copy")
            securities = []
            split_checks = []
            for item in sorted(canonical, key=lambda value: value.filename):
                kind, ticker = _member_identity(item.filename)
                if item.flag_bits & 0x1:
                    raise FrozenArchiveError("archive contains encrypted members")
                peer = archive.getinfo(item.filename.removeprefix("Data/"))
                if (peer.CRC, peer.file_size) != (item.CRC, item.file_size):
                    raise FrozenArchiveError(f"duplicate tree differs for {item.filename}")
                rows = parse_price_file(archive.read(item), item.filename)
                security, split_check = _security_census(kind, ticker, rows)
                securities.append(security)
                if split_check is not None:
                    split_checks.append(split_check)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise FrozenArchiveError("archive ZIP is unreadable") from exc

    populated = [row for row in securities if row["row_count"]]
    if not populated:
        raise FrozenArchiveError("archive has no price rows")
    archive_start = min(date.fromisoformat(row["first_date"]) for row in populated)
    archive_end = max(date.fromisoformat(row["last_date"]) for row in populated)
    sessions = _sessions(archive_start, archive_end)
    end_index = bisect_right(sessions, archive_end)
    for row in populated:
        last_date = date.fromisoformat(row["last_date"])
        sessions_after = end_index - bisect_right(sessions, last_date)
        row["sessions_to_archive_end"] = sessions_after
        row["ended"] = sessions_after > ENDED_SESSION_LAG
    ended = [row for row in populated if row["ended"]]
    kind_counts = Counter(row["kind"] for row in securities)
    nonempty_counts = Counter(row["kind"] for row in populated)
    flag_counts = Counter()
    for row in populated:
        flag_counts["gap"] += bool(row["gap_events"])
        flag_counts["jump"] += bool(row["price_jump_events"])
        flag_counts["union"] += row["ticker_reuse_flag"]
    return {
        "source": ARCHIVE_SOURCE,
        "source_sha256": source_sha,
        "archive_bytes": archive_path.stat().st_size,
        "dataset_page": DATASET_PAGE,
        "download_url": ARCHIVE_URL,
        "license": LICENSE,
        "stated_universe": "all US-based NYSE, Nasdaq, and NYSE MKT stocks and ETFs",
        "stated_cutoff": "2017-11-10",
        "price_basis": PRICE_BASIS,
        "fit_for_event_time_returns": False,
        "canonical_files": len(securities),
        "duplicate_files": len(securities),
        "files_by_kind": dict(sorted(kind_counts.items())),
        "nonempty_files_by_kind": dict(sorted(nonempty_counts.items())),
        "empty_files": len(securities) - len(populated),
        "price_rows": sum(row["row_count"] for row in populated),
        "incomplete_ohlc_rows": sum(row["incomplete_ohlc_rows"] for row in populated),
        "inconsistent_ohlc_rows": sum(row["inconsistent_ohlc_rows"] for row in populated),
        "archive_start": archive_start.isoformat(),
        "archive_end": archive_end.isoformat(),
        "ended_session_lag": ENDED_SESSION_LAG,
        "ended_count": len(ended),
        "ended_share": len(ended) / len(populated),
        "ended_stock_count": sum(row["kind"] == "Stocks" for row in ended),
        "ended_stock_share": sum(row["kind"] == "Stocks" for row in ended)
        / nonempty_counts["Stocks"],
        "ticker_reuse_flags": dict(flag_counts),
        "split_checks": sorted(split_checks, key=lambda row: row["ticker"]),
        "securities": securities,
    }


def stratified_sample(
    intervals: Iterable[dict], corroborated: set[tuple[str, date, date]],
    *, start_year: int = 2006, end_year: int = 2024, per_year: int = SAMPLE_PER_YEAR,
) -> list[dict]:
    """Select deterministic yearly strata, preferring SEC-corroborated intervals."""
    if per_year < 1 or start_year > end_year:
        raise FrozenArchiveError("sample bounds are invalid")
    by_year: dict[int, list[dict]] = defaultdict(list)
    for interval in intervals:
        end_date = interval["end_date"]
        if start_year <= end_date.year <= end_year:
            by_year[end_date.year].append(interval)
    sample = []
    for year in range(start_year, end_year + 1):
        ranked = sorted(
            by_year[year],
            key=lambda row: (
                (row["ticker"], row["start_date"], row["end_date"]) not in corroborated,
                hashlib.sha256(
                    f"{row['ticker']}|{row['start_date']}|{row['end_date']}".encode()
                ).hexdigest(),
            ),
        )
        sample.extend(ranked[:per_year])
    return sample


def _reference_intervals(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], set[tuple]]:
    latest = con.execute(
        """SELECT source_sha256 FROM free_security_master
        GROUP BY source_sha256 ORDER BY MAX(fetched_at) DESC LIMIT 1"""
    ).fetchone()
    if latest is None:
        raise FrozenArchiveError("Tiingo security master is empty")
    rows = con.execute(
        """SELECT ticker,start_date,end_date,exchange,source_row
        FROM free_security_master WHERE source_sha256=?
          AND end_date BETWEEN DATE '2005-01-01' AND DATE '2024-12-31'
        ORDER BY end_date,ticker,start_date""",
        [latest[0]],
    ).fetchall()
    intervals = [
        dict(zip(
            ("ticker", "start_date", "end_date", "exchange", "source_row"), row, strict=True
        ))
        for row in rows
    ]
    sec_rows = con.execute(
        """WITH h AS (
          SELECT DISTINCT cik,upper(ticker) ticker,first_seen,last_seen
          FROM free_cik_ticker_history WHERE ticker IS NOT NULL
        ), notices AS (
          SELECT DISTINCT n.filed_date,h.ticker,n.cik
          FROM free_delisting_notices n JOIN h ON h.cik=n.cik
          WHERE n.filed_date BETWEEN DATE '2005-01-01' AND DATE '2024-12-31'
            AND h.first_seen <= n.filed_date + INTERVAL 366 DAY
            AND h.last_seen >= n.filed_date - INTERVAL 366 DAY
        )
        SELECT DISTINCT m.ticker,m.start_date,m.end_date
        FROM free_security_master m JOIN notices n ON n.ticker=m.ticker
          AND abs(date_diff('day',m.end_date,n.filed_date)) <= 60
        WHERE m.source_sha256=? AND m.end_date BETWEEN DATE '2005-01-01'
          AND DATE '2024-12-31'""",
        [latest[0]],
    ).fetchall()
    return intervals, set(sec_rows)


def _supplemental_sec_2005(con: duckdb.DuckDBPyConnection, stock_map: dict[str, dict]) -> dict:
    notices = con.execute(
        """WITH h AS (
          SELECT DISTINCT cik,upper(ticker) ticker,first_seen,last_seen
          FROM free_cik_ticker_history WHERE ticker IS NOT NULL
        ), mapped AS (
          SELECT DISTINCT h.ticker,n.filed_date,n.cik,n.accession
          FROM free_delisting_notices n JOIN h ON h.cik=n.cik
          WHERE year(n.filed_date)=2005
            AND h.first_seen <= n.filed_date + INTERVAL 366 DAY
            AND h.last_seen >= n.filed_date - INTERVAL 366 DAY
        ), deduplicated AS (
          SELECT *,row_number() OVER (
            PARTITION BY ticker,cik ORDER BY filed_date,accession
          ) AS ordinal FROM mapped
        )
        SELECT ticker,filed_date,cik,accession
        FROM deduplicated WHERE ordinal=1
        ORDER BY ticker,filed_date,accession"""
    ).fetchall()
    ranked = sorted(
        notices,
        key=lambda row: hashlib.sha256(f"{row[0]}|{row[1]}|{row[2]}".encode()).hexdigest(),
    )[:SAMPLE_PER_YEAR]
    sessions = _sessions(date(1962, 1, 1), date(2024, 12, 31))
    sample = []
    for ticker, filed_date, cik, accession in ranked:
        archive = stock_map.get(ticker)
        last_distance = None
        if archive is not None:
            last_distance = _session_distance(
                sessions, filed_date, date.fromisoformat(archive["last_date"])
            )
        sample.append({
            "ticker": ticker,
            "cik": cik,
            "filed_date": filed_date.isoformat(),
            "accession": accession,
            "archive_first": None if archive is None else archive["first_date"],
            "archive_last": None if archive is None else archive["last_date"],
            "last_session_distance": last_distance,
            "last_within_5": last_distance is not None and last_distance <= 5,
        })
    return {
        "candidate_count": len(notices),
        "sample_count": len(ranked),
        "archive_ticker_matches": sum(row[0] in stock_map for row in ranked),
        "archive_last_within_5": sum(row["last_within_5"] for row in sample),
        "note": "SEC-only rows have no reference first date and are excluded from the "
        "two-endpoint decision denominator.",
        "sample": sample,
    }


def compare_references(census: dict, reference_database: Path) -> dict:
    """Compare a deterministic ended-interval sample with Tiingo and SEC references."""
    stock_map = {
        row["ticker"]: row
        for row in census["securities"]
        if row["kind"] == "Stocks" and row["row_count"]
    }
    con = db.connect(reference_database, read_only=True, wait_s=0)
    try:
        intervals, corroborated = _reference_intervals(con)
        sample = stratified_sample(intervals, corroborated)
        supplemental = _supplemental_sec_2005(con, stock_map)
        notice_count = con.execute(
            """SELECT count(*) FROM free_delisting_notices
            WHERE filed_date BETWEEN DATE '2005-01-01' AND DATE '2024-12-31'"""
        ).fetchone()[0]
    finally:
        con.close()
    sessions = _sessions(date(1962, 1, 1), date(2024, 12, 31))
    annual = defaultdict(Counter)
    sample_rows = []
    for interval in sample:
        ticker = interval["ticker"]
        start = interval["start_date"]
        end = interval["end_date"]
        sec_match = (ticker, start, end) in corroborated
        archive = stock_map.get(ticker)
        result = annual[end.year]
        result["sample"] += 1
        result["sec_corroborated"] += sec_match
        first_distance = last_distance = None
        if archive is not None:
            result["ticker_match"] += 1
            first_distance = _session_distance(
                sessions, start, date.fromisoformat(archive["first_date"])
            )
            last_distance = _session_distance(
                sessions, end, date.fromisoformat(archive["last_date"])
            )
            result["first_within_5"] += first_distance <= 5
            result["last_within_5"] += last_distance <= 5
            result["both_within_5"] += first_distance <= 5 and last_distance <= 5
        sample_rows.append({
            "year": end.year,
            "ticker": ticker,
            "reference_start": start.isoformat(),
            "reference_end": end.isoformat(),
            "sec_corroborated": sec_match,
            "archive_first": None if archive is None else archive["first_date"],
            "archive_last": None if archive is None else archive["last_date"],
            "first_session_distance": first_distance,
            "last_session_distance": last_distance,
            "consistent": first_distance is not None
            and first_distance <= 5
            and last_distance <= 5,
        })
    totals = sum((counter for counter in annual.values()), Counter())
    sample_count = totals["sample"]
    coverage = totals["both_within_5"] / sample_count if sample_count else 0.0
    interval_counts = Counter(row["end_date"].year for row in intervals)
    return {
        "method": "exact ticker; 15 per end-year, SEC-corroborated intervals first, "
        "then SHA-256 rank; all intervals used where a year has fewer than 15",
        "reference_years": [2005, 2024],
        "tiingo_interval_counts_by_year": {
            str(year): interval_counts[year] for year in range(2005, 2025)
        },
        "sec_form25_notice_count": int(notice_count),
        "sec_corroborated_sample": totals["sec_corroborated"],
        "supplemental_sec_2005": supplemental,
        "sample_count": sample_count,
        "ticker_matches": totals["ticker_match"],
        "first_within_5": totals["first_within_5"],
        "last_within_5": totals["last_within_5"],
        "both_within_5": totals["both_within_5"],
        "sample_coverage": coverage,
        "by_year": {str(year): dict(annual[year]) for year in range(2006, 2025)},
        "sample": sample_rows,
    }


def massive_overlap(census: dict, reference_database: Path) -> dict:
    """Describe the Massive overlap window without mutating its isolated store."""
    con = db.connect(reference_database, read_only=True, wait_s=0)
    try:
        row = con.execute(
            "SELECT min(date),max(date),count(*) FROM free_daily_bars"
        ).fetchone()
    finally:
        con.close()
    massive_start, massive_end, count = row
    archive_end = date.fromisoformat(census["archive_end"])
    if massive_start is None or archive_end < massive_start:
        status = "no_overlap"
    else:
        status = "overlap_requires_adjustment_ledger"
    return {
        "status": status,
        "archive_end": archive_end.isoformat(),
        "massive_start": None if massive_start is None else massive_start.isoformat(),
        "massive_end": None if massive_end is None else massive_end.isoformat(),
        "massive_rows": int(count),
        "compared_rows": 0,
    }


def recommendation(sample_coverage: float, threshold: float = DECISION_THRESHOLD) -> str:
    """Apply the frozen ingest decision rule."""
    if not 0 <= sample_coverage <= 1 or not 0 <= threshold <= 1:
        raise FrozenArchiveError("coverage and threshold must be fractions")
    return "ingest" if sample_coverage >= threshold else "skip"


def build_census(archive_path: Path, reference_database: Path) -> dict:
    """Run the complete offline census and frozen decision rule."""
    census = census_archive(archive_path)
    if len(census["split_checks"]) != len(KNOWN_SPLITS):
        raise FrozenArchiveError("archive does not contain all ten known split checks")
    references = compare_references(census, reference_database)
    overlap = massive_overlap(census, reference_database)
    decision = recommendation(references["sample_coverage"])
    return {
        **census,
        "reference_comparison": references,
        "overlap_quality": overlap,
        "decision_threshold": DECISION_THRESHOLD,
        "recommendation": decision,
        "rows_loaded": 0,
        "decision_reason": (
            "two-endpoint ended-security coverage is below 30%; no loader is admitted"
            if decision == "skip"
            else "two-endpoint ended-security coverage meets the 30% ingest threshold"
        ),
    }
