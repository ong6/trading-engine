"""Resumable, research-only TradingView daily-history archive.

The cohort is a frozen snapshot of today's liquid universe, not point-in-time
historical membership. Each completed symbol/date window is an append-only
checkpoint. Network work happens without a DuckDB connection.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import duckdb

from engine import bitemporal_facts
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import merge_meta
from engine.lib.settings import DEFAULT_DB

COHORT = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
EXCHANGE_PREFIX = {"Q": "NASDAQ", "P": "AMEX", "N": "NYSE",
                   "A": "AMEX", "Z": "CBOE", "F": "OTC"}
CHUNK_DAYS = 550
MAX_CHUNKS_PER_RUN = 100
DEFAULT_MAX_CHUNKS = 50
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_START = date(2022, 1, 1)
LIMITATION = ("current-liquid-universe snapshot; survivor-biased and retrieval-time-only; "
              "not historical membership or promotion-quality stock-selection evidence")


class ArchiveError(ValueError):
    """Archive parameters or persisted state are invalid."""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    bitemporal_facts.init_schema(con)
    con.execute(
        """CREATE TABLE IF NOT EXISTS tradingview_history_cohorts (
        cohort_id VARCHAR PRIMARY KEY, schema_version INTEGER NOT NULL,
        selected_at TIMESTAMP NOT NULL, start_date DATE NOT NULL,
        selection_rule VARCHAR NOT NULL, selection_sha256 VARCHAR NOT NULL,
        symbol_count INTEGER NOT NULL, limitation VARCHAR NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS tradingview_history_symbols (
        cohort_id VARCHAR NOT NULL, ordinal INTEGER NOT NULL, ticker VARCHAR NOT NULL,
        provider_symbol VARCHAR NOT NULL, exchange_code VARCHAR NOT NULL,
        PRIMARY KEY(cohort_id,ticker), UNIQUE(cohort_id,ordinal))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS tradingview_history_attempts (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, cohort_id VARCHAR NOT NULL,
        ticker VARCHAR NOT NULL, provider_symbol VARCHAR NOT NULL, start_date DATE NOT NULL,
        end_date DATE NOT NULL, status VARCHAR NOT NULL, fact_count INTEGER NOT NULL,
        receipt_sha256 VARCHAR, error VARCHAR, started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP NOT NULL, attempt_sha256 VARCHAR NOT NULL UNIQUE)"""
    )


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ArchiveError("archive time must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _provider_symbol(ticker: str, exchange: str) -> str:
    prefix = EXCHANGE_PREFIX.get(exchange)
    if prefix is None or not re.fullmatch(r"[A-Z0-9._-]{1,32}", ticker):
        raise ArchiveError(f"unsupported TradingView universe symbol: {ticker}/{exchange}")
    return f"{prefix}:{ticker}"


def ensure_cohort(
    con: duckdb.DuckDBPyConnection, *, cohort_id: str, start: date,
    selected_at: datetime, symbols: list[str] | None = None,
) -> dict:
    """Freeze one current-liquid-universe selection, or verify its replay."""
    if COHORT.fullmatch(cohort_id) is None or not isinstance(start, date):
        raise ArchiveError("archive cohort id or start date is invalid")
    init_schema(con)
    existing = con.execute(
        "SELECT start_date,selection_sha256,symbol_count FROM tradingview_history_cohorts "
        "WHERE cohort_id=?", [cohort_id],
    ).fetchone()
    if existing is not None:
        if existing[0] != start:
            raise ArchiveError("archive cohort start date differs from frozen state")
        if symbols is not None:
            stored = [row[0] for row in con.execute(
                "SELECT ticker FROM tradingview_history_symbols WHERE cohort_id=? "
                "ORDER BY ordinal", [cohort_id]).fetchall()]
            if sorted(set(symbols)) != stored:
                raise ArchiveError("archive cohort symbols differ from frozen state")
        return {"cohort_id": cohort_id, "selection_sha256": existing[1],
                "symbol_count": int(existing[2]), "replayed": True}
    where, values = "active AND liquid", []
    if symbols is not None:
        requested = sorted(set(symbols))
        if not requested:
            raise ArchiveError("archive cohort symbols are empty")
        where += f" AND ticker IN ({','.join(['?'] * len(requested))})"
        values = requested
    rows = con.execute(
        f"SELECT ticker,exchange FROM universe WHERE {where} ORDER BY ticker", values
    ).fetchall()
    if not rows or (symbols is not None and len(rows) != len(set(symbols))):
        raise ArchiveError("archive cohort contains unavailable or non-liquid symbols")
    selection = [{"ticker": ticker, "exchange_code": exchange,
                  "provider_symbol": _provider_symbol(ticker, exchange)}
                 for ticker, exchange in rows]
    selection_sha = canonical_sha256(selection)
    selected = _utc_naive(selected_at)
    with db.transaction(con):
        con.execute(
            "INSERT INTO tradingview_history_cohorts VALUES (?,?,?,?,?,?,?,?)",
            [cohort_id, 1, selected, start, "universe.active AND universe.liquid",
             selection_sha, len(selection), LIMITATION],
        )
        con.executemany(
            "INSERT INTO tradingview_history_symbols VALUES (?,?,?,?,?)",
            [[cohort_id, ordinal, item["ticker"], item["provider_symbol"],
              item["exchange_code"]] for ordinal, item in enumerate(selection)],
        )
    return {"cohort_id": cohort_id, "selection_sha256": selection_sha,
            "symbol_count": len(selection), "replayed": False}


def _pending_chunks(
    con: duckdb.DuckDBPyConnection, cohort_id: str, through: date,
    limit: int, max_attempts: int,
) -> list[dict]:
    cohort = con.execute(
        "SELECT start_date FROM tradingview_history_cohorts WHERE cohort_id=?",
        [cohort_id],
    ).fetchone()
    if cohort is None or through < cohort[0]:
        raise ArchiveError("archive cohort is absent or through date precedes its start")
    rows = con.execute(
        "SELECT s.ordinal,s.ticker,s.provider_symbol,COALESCE(MAX(a.end_date) FILTER "
        "(WHERE a.status IN ('complete','empty')),? - INTERVAL 1 DAY) AS completed_through "
        "FROM tradingview_history_symbols s LEFT JOIN tradingview_history_attempts a "
        "ON a.cohort_id=s.cohort_id AND a.ticker=s.ticker "
        "WHERE s.cohort_id=? GROUP BY s.ordinal,s.ticker,s.provider_symbol "
        "ORDER BY s.ordinal", [cohort[0], cohort_id],
    ).fetchall()
    rows.sort(key=lambda row: (row[3], row[0]))
    pending = []
    for _ordinal, ticker, provider_symbol, completed_through in rows:
        if isinstance(completed_through, datetime):
            completed_through = completed_through.date()
        start = completed_through + timedelta(days=1)
        if start > through:
            continue
        end = min(start + timedelta(days=CHUNK_DAYS), through)
        failures = int(con.execute(
            "SELECT COUNT(*) FROM tradingview_history_attempts WHERE cohort_id=? "
            "AND ticker=? AND start_date=? AND end_date=? AND status='failed'",
            [cohort_id, ticker, start, end],
        ).fetchone()[0])
        if failures >= max_attempts:
            continue
        pending.append({"ticker": ticker, "provider_symbol": provider_symbol,
                        "start": start, "end": end})
        if len(pending) == limit:
            break
    return pending


def _record_attempt(
    con: duckdb.DuckDBPyConnection, *, cohort_id: str, chunk: dict, status: str,
    fact_count: int, receipt_sha256: str | None, error: str | None,
    started_at: datetime, completed_at: datetime,
) -> None:
    if status not in {"complete", "empty", "failed"}:
        raise ArchiveError("archive attempt status is invalid")
    started, completed = _utc_naive(started_at), _utc_naive(completed_at)
    attempt_number = int(con.execute(
        "SELECT COUNT(*)+1 FROM tradingview_history_attempts WHERE cohort_id=? "
        "AND ticker=? AND start_date=? AND end_date=?",
        [cohort_id, chunk["ticker"], chunk["start"], chunk["end"]],
    ).fetchone()[0])
    identity = {"schema_version": 1, "attempt_number": attempt_number,
                "cohort_id": cohort_id,
                "ticker": chunk["ticker"], "provider_symbol": chunk["provider_symbol"],
                "start_date": chunk["start"].isoformat(),
                "end_date": chunk["end"].isoformat(), "status": status,
                "fact_count": fact_count, "receipt_sha256": receipt_sha256,
                "error": error, "started_at": started.isoformat(),
                "completed_at": completed.isoformat()}
    attempt_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM tradingview_history_attempts"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO tradingview_history_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [attempt_id, 1, cohort_id, chunk["ticker"], chunk["provider_symbol"],
         chunk["start"], chunk["end"], status, fact_count, receipt_sha256, error,
         started, completed, canonical_sha256(identity)],
    )


def archive_status(con: duckdb.DuckDBPyConnection, cohort_id: str) -> dict:
    present = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN "
        "('tradingview_history_cohorts','tradingview_history_symbols',"
        "'tradingview_history_attempts','bitemporal_facts')"
    ).fetchone()[0]
    if present != 4:
        return {"status": "absent", "cohort_id": cohort_id}
    cohort = con.execute(
        "SELECT selected_at,start_date,selection_sha256,symbol_count,limitation "
        "FROM tradingview_history_cohorts WHERE cohort_id=?", [cohort_id],
    ).fetchone()
    if cohort is None:
        return {"status": "absent", "cohort_id": cohort_id}
    counts = dict(con.execute(
        "SELECT status,COUNT(*) FROM tradingview_history_attempts WHERE cohort_id=? "
        "GROUP BY status", [cohort_id],
    ).fetchall())
    facts = con.execute(
        "SELECT COUNT(*),COUNT(DISTINCT entity_id),MIN(event_at),MAX(event_at) "
        "FROM bitemporal_facts WHERE source='tradingview_unofficial' "
        "AND fact_type='market.ohlcv.1d.retrieved' AND receipt_sha256 IN "
        "(SELECT receipt_sha256 FROM tradingview_history_attempts WHERE cohort_id=? "
        "AND status='complete')",
        [cohort_id],
    ).fetchone()
    target_through = db.latest_operational_market_date(con)
    progress = con.execute(
        "SELECT COUNT(*) FILTER (WHERE completed_through IS NOT NULL),"
        "MIN(completed_through),MAX(completed_through),"
        "COUNT(*) FILTER (WHERE completed_through>=?) FROM ("
        "SELECT s.ticker,MAX(a.end_date) FILTER "
        "(WHERE a.status IN ('complete','empty')) AS completed_through "
        "FROM tradingview_history_symbols s LEFT JOIN tradingview_history_attempts a "
        "ON a.cohort_id=s.cohort_id AND a.ticker=s.ticker WHERE s.cohort_id=? "
        "GROUP BY s.ticker)", [target_through or date.max, cohort_id],
    ).fetchone()
    unresolved = int(con.execute(
        "SELECT COUNT(DISTINCT (a.ticker,a.start_date,a.end_date)) "
        "FROM tradingview_history_attempts a WHERE a.cohort_id=? "
        "AND a.status='failed' AND NOT EXISTS (SELECT 1 FROM tradingview_history_attempts b "
        "WHERE b.cohort_id=a.cohort_id AND b.ticker=a.ticker "
        "AND b.start_date=a.start_date AND b.end_date=a.end_date "
        "AND b.status IN ('complete','empty'))", [cohort_id],
    ).fetchone()[0])
    return {"status": "active", "cohort_id": cohort_id,
            "selected_at": cohort[0].isoformat() + "Z",
            "start_date": cohort[1].isoformat(), "selection_sha256": cohort[2],
            "target_symbols": int(cohort[3]), "limitation": cohort[4],
            "attempts": {key: int(counts.get(key, 0)) for key in
                         ("complete", "empty", "failed")},
            "unresolved_failed_windows": unresolved, "fact_count": int(facts[0]),
            "symbols_with_facts": int(facts[1]),
            "symbols_checkpointed": int(progress[0]),
            "symbols_unstarted": int(cohort[3]) - int(progress[0]),
            "checkpoint_start": None if progress[1] is None else progress[1].isoformat(),
            "checkpoint_end": None if progress[2] is None else progress[2].isoformat(),
            "target_through": None if target_through is None else target_through.isoformat(),
            "symbols_caught_up": int(progress[3]) if target_through is not None else 0,
            "symbols_pending": (int(cohort[3]) - int(progress[3])
                                  if target_through is not None else int(cohort[3])),
            "fact_start": None if facts[2] is None else facts[2].date().isoformat(),
            "fact_end": None if facts[3] is None else facts[3].date().isoformat(),
            "historical_authority": "retrieval_time_research_only",
            "execution_authority": "none", "operational_price_mutation": False}


def run_connection_narrowed(
    params: dict | None, db_path: str | Path | None = None, meta_path: str | Path | None = None,
    *, capture: Callable | None = None, clock: Callable[[], datetime] | None = None,
) -> dict:
    """Run one bounded archive slice while leasing DuckDB only for checkpoints."""
    values = params or {}
    allowed = {"cohort_id", "start", "through", "max_chunks", "max_attempts",
               "pause_seconds", "symbols"}
    if not isinstance(values, dict) or set(values) - allowed:
        raise ArchiveError("archive job parameters are invalid")
    cohort_id = values.get("cohort_id", "liquid-current-v1")
    start = date.fromisoformat(values.get("start", DEFAULT_START.isoformat()))
    limit = int(values.get("max_chunks", DEFAULT_MAX_CHUNKS))
    max_attempts = int(values.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    pause = float(values.get("pause_seconds", 0.5))
    symbols = values.get("symbols")
    if (not 1 <= limit <= MAX_CHUNKS_PER_RUN or not 1 <= max_attempts <= 10
            or not 0 <= pause <= 10 or symbols is not None
            and (not isinstance(symbols, list) or not all(isinstance(x, str) for x in symbols))):
        raise ArchiveError("archive job bounds are invalid")
    if cohort_id == "liquid-current-v1" and symbols is not None:
        raise ArchiveError("production liquid cohort cannot use an explicit symbol subset")
    now = clock or (lambda: datetime.now(timezone.utc))
    path = Path(db_path) if db_path is not None else DEFAULT_DB
    con = db.connect(path)
    try:
        db.init_schema(con)
        ensure_cohort(con, cohort_id=cohort_id, start=start, selected_at=now(), symbols=symbols)
        if values.get("through"):
            through = date.fromisoformat(values["through"])
        else:
            through = db.latest_operational_market_date(con)
            if through is None:
                raise ArchiveError("archive has no breadth-qualified through date")
        chunks = _pending_chunks(con, cohort_id, through, limit, max_attempts)
    finally:
        con.close()
    if capture is None:
        from server.official_quote_source import capture_tradingview_history
        capture = capture_tradingview_history
    completed = empty = failed = 0
    for index, chunk in enumerate(chunks):
        if index and pause:
            time.sleep(pause)
        begun = now()
        try:
            result = capture(chunk["provider_symbol"], chunk["start"], chunk["end"],
                             database=path)
            status = "empty" if result["fact_count"] == 0 else "complete"
            fact_count, receipt, error = int(result["fact_count"]), result["receipt_sha256"], None
            completed += status == "complete"
            empty += status == "empty"
        except Exception as exc:  # noqa: BLE001 - one symbol cannot abort checkpointing others
            status, fact_count, receipt, error = "failed", 0, None, str(exc)[:500]
            failed += 1
        con = db.connect(path)
        try:
            init_schema(con)
            with db.transaction(con):
                _record_attempt(con, cohort_id=cohort_id, chunk=chunk, status=status,
                                fact_count=fact_count, receipt_sha256=receipt, error=error,
                                started_at=begun, completed_at=now())
        finally:
            con.close()
    con = db.connect(path, read_only=True)
    try:
        result = archive_status(con, cohort_id)
    finally:
        con.close()
    result.update(attempted_this_run=len(chunks), completed_this_run=completed,
                  empty_this_run=empty, failed_this_run=failed, through=through.isoformat())
    result["last_run"] = now().isoformat()
    if meta_path is not None:
        merge_meta(meta_path, {"tradingview_history": result})
    if chunks and failed == len(chunks):
        raise ArchiveError(f"all {failed} TradingView history chunks failed")
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Read TradingView history archive status.")
    parser.add_argument("--cohort", default="liquid-current-v1")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    con = db.connect(args.db, read_only=True)
    try:
        print(json.dumps(archive_status(con, args.cohort), indent=2, sort_keys=True))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
