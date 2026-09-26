"""Append exact-date EOD fetch outcomes used by P15 missing-bar labels."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from sim import nyse

SOURCE = "yfinance"
OPEN_LABEL_SOURCE = "yfinance_ticker_history_v1"
OPEN_LABEL_MISSING_REASON = "not_found_no_data_symbol_may_be_delisted"
HORIZONS = (1, 5, 10, 20)


def open_label_request_sha256(
    ticker: str, provider_ticker: str, market_date: date,
) -> str:
    return canonical_sha256({
        "ticker": ticker, "provider_ticker": provider_ticker,
        "market_date": market_date.isoformat(), "source": OPEN_LABEL_SOURCE,
        "interval": "1d", "auto_adjust": False,
    })


def open_label_missing_response_sha256() -> str:
    return canonical_sha256({
        "result": "completed_missing", "outcome_reason": OPEN_LABEL_MISSING_REASON,
    })


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_price_fetch_batches (
        id BIGINT PRIMARY KEY, market_date DATE NOT NULL, attempted_at TIMESTAMP NOT NULL,
        source VARCHAR NOT NULL, requested_count INTEGER NOT NULL,
        failed_count INTEGER NOT NULL, present_count INTEGER NOT NULL,
        missing_count INTEGER NOT NULL, batch_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS price_fetch_attempts (
        id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, market_date DATE NOT NULL,
        attempted_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, status VARCHAR NOT NULL,
        batch_sha256 VARCHAR NOT NULL, attempt_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(batch_sha256,ticker))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_open_label_fetch_receipts (
        id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, provider_ticker VARCHAR NOT NULL,
        market_date DATE NOT NULL, requested_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, status VARCHAR NOT NULL,
        outcome_reason VARCHAR,
        request_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL,
        receipt_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        "ALTER TABLE p15_open_label_fetch_receipts ADD COLUMN IF NOT EXISTS "
        "outcome_reason VARCHAR"
    )


def _missing_dates(
    con: duckdb.DuckDBPyConnection, ticker: str, boundary: date,
    labeled: set[tuple[int, str]], through_date: date, known_at: datetime,
) -> set[date]:
    cutoff = known_at.astimezone(timezone.utc).replace(tzinfo=None)
    sessions = [row[0] for row in con.execute(
        f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? AND date<=? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} "
        "ORDER BY date LIMIT 20",
        [boundary, through_date, cutoff],
    ).fetchall()]
    missing = set()
    for horizon in HORIZONS:
        if len(sessions) < horizon or any(
            item[0] == horizon for item in labeled
        ):
            continue
        required = sessions[:horizon]
        present = {row[0] for row in con.execute(
            f"SELECT date FROM prices WHERE ticker=? AND date IN "
            f"({','.join('?' for _ in required)}) AND fetched_at IS NOT NULL "
            f"AND fetched_at<=? AND {REAL_BAR_SQL}",
            [ticker, *required, cutoff],
        ).fetchall()}
        absent = set(required) - present
        if not absent:
            continue
        later = con.execute(
            f"SELECT 1 FROM prices WHERE ticker=? AND date>? AND date<=? "
            f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL} LIMIT 1",
            [ticker, max(absent), through_date, cutoff],
        ).fetchone()
        if later is None:
            missing.update(absent)
    return missing


def open_label_obligations(
    con: duckdb.DuckDBPyConnection, *, through_date: date, known_at: datetime,
) -> list[dict]:
    """Exact-date fetches still owed by immutable P15 decisions."""
    if known_at.utcoffset() is None:
        raise ValueError("open-label fetch cutoff is invalid")
    obligations: set[tuple[str, date]] = set()
    nightly_tables = {
        "agent_evaluation_traces", "agent_evaluation_decisions",
        "agent_evaluation_labels_v2",
    }
    if all(table_exists(con, name) for name in nightly_tables):
        rows = con.execute(
            "SELECT d.id,d.ticker,t.market_date,d.decision,d.decision_payload "
            "FROM agent_evaluation_decisions d JOIN agent_evaluation_traces t "
            "ON t.id=d.trace_id WHERE t.policy_id='p15-scoring-v1' ORDER BY d.id"
        ).fetchall()
        for decision_id, ticker, market_date, decision, raw in rows:
            try:
                available = json.loads(raw).get("scoring_status") == "available"
            except (TypeError, ValueError):
                available = False
            if decision == "unavailable" or not available:
                continue
            labeled = set(con.execute(
                "SELECT horizon_sessions,label_basis FROM agent_evaluation_labels_v2 "
                "WHERE decision_id=? AND label_basis IN "
                "('next_session_open','missing_entry_last_available_close')",
                [decision_id],
            ).fetchall())
            obligations.update(
                (ticker, missing_date) for missing_date in _missing_dates(
                    con, ticker, market_date, labeled, through_date, known_at,
                )
            )
    event_tables = {"p15_event_decisions", "p15_event_labels"}
    if all(table_exists(con, name) for name in event_tables):
        rows = con.execute(
            "SELECT id,ticker,decision_at FROM p15_event_decisions "
            "WHERE scoring_status='available' ORDER BY id"
        ).fetchall()
        for decision_id, ticker, decision_at in rows:
            labeled = set(con.execute(
                "SELECT horizon_sessions,label_basis FROM p15_event_labels "
                "WHERE decision_id=? AND label_basis='next_session_open'",
                [decision_id],
            ).fetchall())
            obligations.update(
                (ticker, missing_date) for missing_date in _missing_dates(
                    con, ticker, decision_at.date(), labeled, through_date, known_at,
                )
            )
    if table_exists(con, "p15_open_label_fetch_receipts") and obligations:
        cutoff = known_at.astimezone(timezone.utc).replace(tzinfo=None)
        confirmed = set(con.execute(
            "SELECT ticker,market_date FROM p15_open_label_fetch_receipts "
            "WHERE status='missing' AND completed_at<=?",
            [cutoff],
        ).fetchall())
        obligations -= confirmed
    result = []
    for ticker, market_date in sorted(obligations, key=lambda item: (item[1], item[0])):
        row = con.execute(
            "SELECT yf_ticker FROM universe WHERE ticker=?", [ticker]
        ).fetchone()
        result.append({
            "ticker": ticker,
            "provider_ticker": ticker if row is None or not row[0] else row[0],
            "market_date": market_date,
        })
    return result


def record_open_label_receipt(
    con: duckdb.DuckDBPyConnection, *, ticker: str, provider_ticker: str,
    market_date: date, requested_at: datetime, completed_at: datetime,
    status: str, outcome_reason: str | None,
    request_sha256: str, response_sha256: str,
) -> str:
    """Append one completed, exact-date, per-ticker fetch receipt."""
    if (
        requested_at.utcoffset() is None or completed_at.utcoffset() is None
        or completed_at < requested_at or not nyse.is_session(market_date)
        or status != "missing" or outcome_reason != OPEN_LABEL_MISSING_REASON
        or request_sha256 != open_label_request_sha256(
            ticker, provider_ticker, market_date,
        )
        or response_sha256 != open_label_missing_response_sha256()
    ):
        raise ValueError("open-label fetch receipt is invalid")
    init_schema(con)
    completed = completed_at.astimezone(timezone.utc)
    had_bar = con.execute(
        f"SELECT 1 FROM prices WHERE ticker=? AND date=? AND fetched_at<=? "
        f"AND {REAL_BAR_SQL} LIMIT 1",
        [ticker, market_date, completed.replace(tzinfo=None)],
    ).fetchone() is not None
    if had_bar:
        raise ValueError("open-label fetch receipt differs from stored prices")
    body = {
        "ticker": ticker, "provider_ticker": provider_ticker,
        "market_date": market_date.isoformat(),
        "requested_at": requested_at.astimezone(timezone.utc).isoformat(),
        "completed_at": completed.isoformat(), "source": OPEN_LABEL_SOURCE,
        "status": status, "outcome_reason": outcome_reason,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
    }
    receipt_sha = canonical_sha256(body)
    next_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM p15_open_label_fetch_receipts"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO p15_open_label_fetch_receipts "
        "(id,ticker,provider_ticker,market_date,requested_at,completed_at,source,status,"
        "outcome_reason,request_sha256,response_sha256,receipt_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [next_id, ticker, provider_ticker, market_date,
         requested_at.astimezone(timezone.utc).replace(tzinfo=None),
         completed.replace(tzinfo=None), OPEN_LABEL_SOURCE, status, outcome_reason,
         request_sha256, response_sha256, receipt_sha],
    )
    return receipt_sha


def record(
    con: duckdb.DuckDBPyConnection, *, market_date: date, attempted_at: datetime,
    requested_count: int, failed_count: int,
) -> dict:
    """Record outcomes only after a complete all-liquid incremental collection."""
    if attempted_at.utcoffset() is None or not nyse.is_session(market_date):
        raise ValueError("price fetch attempt timestamp or market date is invalid")
    init_schema(con)
    tickers = [row[0] for row in con.execute(
        "SELECT ticker FROM universe WHERE liquid=TRUE ORDER BY ticker"
    ).fetchall()]
    if failed_count or requested_count != len(tickers):
        return {
            "status": "withheld", "market_date": market_date.isoformat(),
            "reason": "collection_incomplete", "attempt_count": 0,
            "present_count": 0, "missing_count": 0,
        }
    present = {row[0] for row in con.execute(
        f"SELECT ticker FROM prices WHERE date=? AND ticker IN "
        "(SELECT ticker FROM universe WHERE liquid=TRUE) "
        f"AND {REAL_BAR_SQL} ORDER BY ticker",
        [market_date],
    ).fetchall()}
    next_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM price_fetch_attempts"
    ).fetchone()[0])
    attempted = attempted_at.astimezone(timezone.utc)
    missing = sorted(set(tickers) - present)
    batch_identity = {
        "market_date": market_date.isoformat(), "attempted_at": attempted.isoformat(),
        "source": SOURCE, "requested_count": requested_count, "failed_count": failed_count,
        "present_count": len(present & set(tickers)), "missing_count": len(missing),
        "missing_tickers": missing,
    }
    batch_sha = canonical_sha256(batch_identity)
    batch_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM p15_price_fetch_batches"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO p15_price_fetch_batches VALUES (?,?,?,?,?,?,?,?,?)",
        [batch_id, market_date, attempted.replace(tzinfo=None), SOURCE,
         requested_count, failed_count, len(present & set(tickers)), len(missing), batch_sha],
    )
    rows = []
    for offset, ticker in enumerate(missing):
        status = "missing"
        identity = {
            "ticker": ticker, "market_date": market_date.isoformat(),
            "attempted_at": attempted.isoformat(), "source": SOURCE, "status": status,
            "batch_sha256": batch_sha,
        }
        rows.append([
            next_id + offset, ticker, market_date, attempted.replace(tzinfo=None),
            SOURCE, status, batch_sha, canonical_sha256(identity),
        ])
    if rows:
        con.executemany(
            "INSERT INTO price_fetch_attempts VALUES (?,?,?,?,?,?,?,?)", rows,
        )
    return {
        "status": "complete", "market_date": market_date.isoformat(),
        "attempt_count": requested_count, "present_count": len(present & set(tickers)),
        "missing_count": len(missing),
    }


def validate(con: duckdb.DuckDBPyConnection, error_type) -> None:
    """Replay every batch and row identity that can confirm a missing label."""
    present = [
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [name]
        ).fetchone()[0] > 0
        for name in ("p15_price_fetch_batches", "price_fetch_attempts")
    ]
    if not any(present):
        return
    if not all(present):
        raise error_type("P15 price fetch attempt schema is incomplete")
    for batch in con.execute(
        "SELECT market_date,attempted_at,source,requested_count,failed_count,"
        "present_count,missing_count,batch_sha256 "
        "FROM p15_price_fetch_batches ORDER BY id"
    ).fetchall():
        (market_date, attempted_at, source, requested, failed,
         present_count, missing_count, batch_sha) = batch
        attempts = con.execute(
            "SELECT ticker,status,attempt_sha256 FROM price_fetch_attempts "
            "WHERE batch_sha256=? ORDER BY ticker", [batch_sha],
        ).fetchall()
        tickers = [row[0] for row in attempts]
        batch_identity = {
            "market_date": market_date.isoformat(),
            "attempted_at": attempted_at.replace(tzinfo=timezone.utc).isoformat(),
            "source": source, "requested_count": requested, "failed_count": failed,
            "present_count": present_count, "missing_count": missing_count,
            "missing_tickers": tickers,
        }
        if (failed != 0 or requested != present_count + missing_count
                or missing_count != len(attempts) or len(tickers) != len(set(tickers))) \
                or canonical_sha256(batch_identity) != batch_sha:
            raise error_type("P15 price fetch batch evidence differs")
        for ticker, status, attempt_sha in attempts:
            identity = {
                "ticker": ticker, "market_date": market_date.isoformat(),
                "attempted_at": attempted_at.replace(tzinfo=timezone.utc).isoformat(),
                "source": source, "status": status, "batch_sha256": batch_sha,
            }
            had_bar = con.execute(
                f"SELECT 1 FROM prices WHERE ticker=? AND date=? "
                f"AND fetched_at<=? AND {REAL_BAR_SQL} LIMIT 1",
                [ticker, market_date, attempted_at],
            ).fetchone() is not None
            if status != "missing" or had_bar \
                    or canonical_sha256(identity) != attempt_sha:
                raise error_type("P15 price fetch attempt evidence differs")
    orphans = int(con.execute(
        "SELECT COUNT(*) FROM price_fetch_attempts a LEFT JOIN p15_price_fetch_batches b "
        "ON b.batch_sha256=a.batch_sha256 WHERE b.batch_sha256 IS NULL"
    ).fetchone()[0])
    if orphans:
        raise error_type("P15 price fetch attempt evidence differs")
    if not table_exists(con, "p15_open_label_fetch_receipts"):
        return
    for row in con.execute(
        "SELECT ticker,provider_ticker,market_date,requested_at,completed_at,source,status,"
        "outcome_reason,"
        "request_sha256,response_sha256,receipt_sha256 "
        "FROM p15_open_label_fetch_receipts ORDER BY id"
    ).fetchall():
        (ticker, provider_ticker, market_date, requested_at, completed_at, source, status,
         outcome_reason, request_sha, response_sha, receipt_sha) = row
        body = {
            "ticker": ticker, "provider_ticker": provider_ticker,
            "market_date": market_date.isoformat(),
            "requested_at": requested_at.replace(tzinfo=timezone.utc).isoformat(),
            "completed_at": completed_at.replace(tzinfo=timezone.utc).isoformat(),
            "source": source, "status": status, "outcome_reason": outcome_reason,
            "request_sha256": request_sha,
            "response_sha256": response_sha,
        }
        had_bar = con.execute(
            f"SELECT 1 FROM prices WHERE ticker=? AND date=? AND fetched_at<=? "
            f"AND {REAL_BAR_SQL} LIMIT 1",
            [ticker, market_date, completed_at],
        ).fetchone() is not None
        if (
            source != OPEN_LABEL_SOURCE or status != "missing"
            or outcome_reason != OPEN_LABEL_MISSING_REASON
            or request_sha != open_label_request_sha256(
                ticker, provider_ticker, market_date,
            )
            or response_sha != open_label_missing_response_sha256()
            or requested_at > completed_at or had_bar
            or canonical_sha256(body) != receipt_sha
        ):
            raise error_type("P15 open-label fetch receipt differs")
