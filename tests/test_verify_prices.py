"""Price verification releases its store snapshot before network work."""
from __future__ import annotations

import fcntl
import os
import threading
import time
from datetime import date
from itertools import pairwise

import pytest

from engine import verify_prices
from engine.lib import db


def test_held_tickers_include_only_active_portfolios(con):
    con.execute(
        "INSERT INTO portfolios (id, name, active, cash) VALUES "
        "('active', 'active', TRUE, 1000), ('retired', 'retired', FALSE, 1000)"
    )
    con.execute(
        "INSERT INTO sim_positions VALUES "
        "('active', 'LIVE', 2, 10), "
        "('active', 'ZERO', 0, 10), "
        "('retired', 'ARCHIVE', 3, 10), "
        "('retired', 'LIVE', 4, 10)"
    )

    assert verify_prices._held_tickers(con) == ["LIVE"]


def test_connection_narrowed_releases_reader_before_fetch(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    con.execute(
        "INSERT INTO universe (ticker, yf_ticker, etf, active, liquid) "
        "VALUES ('AAA', 'AAA', FALSE, TRUE, TRUE)"
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('AAA', '2026-09-08', 10, 11, 9, 10.5, 1000, 'yfinance', now())"
    )
    con.close()

    writer_opened: list[bool] = []
    release_path = tmp_path / "reader-release.lock"
    release_fd = os.open(release_path, os.O_CREAT | os.O_RDWR)
    fcntl.flock(release_fd, fcntl.LOCK_EX)

    def fetch_while_writing(ticker, *, assetclass, start, end, session):
        assert (ticker, assetclass, end) == ("AAA", "stocks", date(2026, 9, 8))
        assert start < end
        assert session is not None
        probe = os.open(release_path, os.O_RDWR)
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
        writer = db.connect(db_path, wait_s=0)
        try:
            writer.execute(
                "INSERT INTO universe (ticker, yf_ticker, etf, active, liquid) "
                "VALUES ('BBB', 'BBB', FALSE, TRUE, TRUE)"
            )
            writer_opened.append(True)
        finally:
            writer.close()
        return {
            "symbol": "AAA",
            "bars": {
                date(2026, 9, 8): {
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000,
                }
            },
            "parse_errors": [],
            "rows": 1,
        }

    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", fetch_while_writing)
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)

    result = verify_prices.run_connection_narrowed(
        {"tickers": "AAA", "sessions": 1},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
        release_lock_fd=release_fd,
    )

    assert writer_opened == [True]
    assert result["names_checked"] == 1
    assert result["names_agreeing"] == 1
    try:
        os.fstat(release_fd)
    except OSError:
        pass
    else:
        raise AssertionError("release lock descriptor remains open")
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute("SELECT COUNT(*) FROM universe").fetchone() == (2,)
    finally:
        check.close()


def test_workers_overlap_waits_but_share_one_request_rate(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    tickers = [f"T{i}" for i in range(6)]
    for ticker in tickers:
        con.execute(
            "INSERT INTO universe (ticker, yf_ticker, etf, active, liquid) "
            "VALUES (?, ?, FALSE, TRUE, TRUE)",
            [ticker, ticker],
        )
        con.execute(
            "INSERT INTO prices "
            "(ticker, date, open, high, low, close, volume, source, fetched_at) "
            "VALUES (?, '2026-09-08', 10, 11, 9, 10.5, 1000, 'yfinance', now())",
            [ticker],
        )
    con.close()

    starts: list[float] = []
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fetch(ticker, *, assetclass, start, end, session):
        nonlocal active, max_active
        with lock:
            starts.append(time.monotonic())
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {
            "symbol": ticker,
            "bars": {date(2026, 9, 8): {
                "open": 10.0, "high": 11.0, "low": 9.0,
                "close": 10.5, "volume": 1000,
            }},
            "parse_errors": [],
            "rows": 1,
        }

    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", fetch)
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0.02)
    result = verify_prices.run_connection_narrowed(
        {"tickers": tickers, "sessions": 1},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert result["names_agreeing"] == len(tickers)
    assert max_active > 1
    ordered = sorted(starts)
    assert all(later - earlier >= 0.015 for earlier, later in pairwise(ordered))


def test_retains_every_disagreeing_name_and_field(monkeypatch, tmp_path, con):
    from datetime import timedelta

    db.init_schema(con)
    tickers = [f"BAD{i}" for i in range(6)]
    days = [date(2026, 9, 8) + timedelta(days=i) for i in range(5)]
    for ticker in tickers:
        con.execute("INSERT INTO universe(ticker,etf) VALUES (?,FALSE)", [ticker])
        for day in days:
            con.execute(
                "INSERT INTO prices(ticker,date,open,high,low,close,volume) "
                "VALUES (?,?,10,11,9,10,100)", [ticker, day],
            )
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", lambda ticker, **_kw: {
        "symbol": ticker, "bars": {d: {"open": 100, "high": 110, "low": 90,
                                        "close": 100, "volume": 100} for d in days},
        "parse_errors": [], "rows": 5,
    })
    result = verify_prices.run({"tickers": tickers}, con, tmp_path / "meta.json")
    assert result["names_disagreeing"] == 6
    assert {item["ticker"] for item in result["disagreements"]} == set(tickers)
    assert len(result["disagreements"]) == result["n_disagreements"] == 102
    assert {item["ticker"] for item in result["name_results"]} == set(tickers)


def _response(data):
    import json
    from datetime import datetime, timezone
    return verify_prices.NasdaqResponse(
        json.dumps({"status": {"rCode": 200}, "data": data}).encode(),
        "application/json", 200, datetime.now(timezone.utc),
    )


def test_source_symbol_must_be_explicit_and_match():
    import pytest
    for symbol in (None, "", "OTHER"):
        with pytest.raises(verify_prices.SourceError, match="symbol"):
            verify_prices.parse_nasdaq_history("AAA", _response({
                "symbol": symbol, "tradesTable": {"rows": []},
            }))
    result = verify_prices.parse_nasdaq_history("BRK.B", _response({
        "symbol": "BRK/B", "tradesTable": {"rows": []},
    }))
    assert result["symbol"] == "BRK/B"


def test_source_nonfinite_and_duplicate_prices_are_not_silent():
    import pytest
    row = {"date": "09/08/2026", "open": "10", "high": "11", "low": "9",
           "close": "NaN", "volume": "100"}
    parsed = verify_prices.parse_nasdaq_history("AAA", _response({
        "symbol": "AAA", "tradesTable": {"rows": [row]},
    }))
    assert parsed["parse_errors"] and not parsed["bars"]
    row["close"] = "10"
    with pytest.raises(verify_prices.SourceError, match="duplicate"):
        verify_prices.parse_nasdaq_history("AAA", _response({
            "symbol": "AAA", "tradesTable": {"rows": [row, row]},
        }))


def test_exact_source_response_retained_and_receipt_is_immutable(monkeypatch, tmp_path):
    import base64
    import hashlib
    import json

    response = _response({"symbol": "AAA", "tradesTable": {"rows": []}})
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_response", lambda *_a, **_kw: response)
    fetched = verify_prices.fetch_nasdaq_history(
        "AAA", assetclass="stocks", start=date(2026, 9, 1), end=date(2026, 9, 8),
    )
    evidence = fetched["evidence"]
    assert base64.b64decode(evidence["body_base64"]) == response.body
    assert evidence["body_sha256"] == hashlib.sha256(response.body).hexdigest()
    acc = {"source_evidence": {"AAA": [evidence]}, "names_checked": 0}
    summary = verify_prices.retain_evidence(acc, tmp_path)
    receipt = summary["evidence_receipt"]
    assert receipt["path"] == f"price-verify/{receipt['sha256']}.json"
    path = tmp_path / f"{receipt['sha256']}.json"
    assert json.loads(path.read_bytes()) == acc
    assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"]
    assert "source_evidence" not in summary
    assert verify_prices.retain_evidence(acc, tmp_path) == summary
    assert list(tmp_path.glob(".receipt-*")) == []


@pytest.mark.parametrize("payload", [
    ["unexpected envelope"],
    {"status": [200]},
    {"status": {"rCode": 200}, "data": ["AAA"]},
    {"status": {"rCode": 200}, "data": {"symbol": "AAA", "tradesTable": [1]}},
    {"status": {"rCode": 200}, "data": {"symbol": "AAA", "tradesTable": {"rows": {}}}},
    {"status": {"rCode": 200}, "data": {"symbol": "AAA", "tradesTable": {"rows": [None]}}},
])
def test_malformed_source_shapes_retain_exact_body(monkeypatch, payload):
    import base64
    import json
    from datetime import datetime, timezone

    body = json.dumps(payload).encode()
    response = verify_prices.NasdaqResponse(body, "application/json", 200,
                                            datetime.now(timezone.utc))
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_response", lambda *_a, **_kw: response)
    with pytest.raises(verify_prices.SourceError) as caught:
        verify_prices.fetch_nasdaq_history(
            "AAA", assetclass="stocks", start=date(2026, 9, 1), end=date(2026, 9, 8),
        )
    assert base64.b64decode(caught.value.evidence["body_base64"]) == body


def test_malformed_source_does_not_abandon_other_names(monkeypatch, con, tmp_path):
    import base64

    db.init_schema(con)
    for ticker in ("AAA", "BBB"):
        con.execute("INSERT INTO universe(ticker,etf) VALUES (?,FALSE)", [ticker])
        con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume) "
                    "VALUES (?,'2026-09-08',10,11,9,10,100)", [ticker])
    invalid = _response({"symbol": "AAA", "tradesTable": {"rows": [None]}})
    valid = _response({"symbol": "BBB", "tradesTable": {"rows": [{
        "date": "09/08/2026", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100,
    }]}})
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_response",
                        lambda ticker, **_kw: invalid if ticker == "AAA" else valid)
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(verify_prices, "RETRY_SLEEP", 0)
    result = verify_prices.run({"tickers": ["AAA", "BBB"]}, con, tmp_path / "meta.json")
    assert result["names_agreeing"] == 1
    assert result["names_not_checked"] == 1
    assert base64.b64decode(result["source_evidence"]["AAA"][0]["body_base64"]) == invalid.body


def test_rate_limiter_oversleep_does_not_compress_next_request_slot():
    instant, waits = [0.0], []

    def sleep(delay):
        waits.append(delay)
        instant[0] += delay + 10.0

    limiter = verify_prices._GlobalRateLimiter(1.0, clock=lambda: instant[0], sleep=sleep)
    assert limiter.wait(100)
    assert limiter.wait(100)
    assert instant[0] == 11
    assert limiter.wait(100)
    assert instant[0] == 22
    assert waits == [1.0, 1.0]


def test_rate_limiter_oversleep_past_deadline_does_not_admit_request():
    instant = [0.0]
    limiter = verify_prices._GlobalRateLimiter(
        1.0, clock=lambda: instant[0], sleep=lambda _delay: instant.__setitem__(0, 10.0),
    )
    assert limiter.wait(2)
    assert not limiter.wait(2)


def test_nonfinite_or_nonpositive_store_price_is_never_agreement():
    import pytest

    day = date(2026, 10, 2)
    for value in (float("nan"), float("inf"), -1.0, 0.0):
        result = verify_prices.compare_bars(
            "AAA", {day: {"close": value}}, {day: {"close": 10}}, 10, 0.01, day,
        )
        assert result["status"] == "not_checked"
        assert result["reason"] == "invalid_comparison_price"
        assert result["fields_compared"] == 0
        assert result["worst"] is None
        assert result["invalid_fields"][0]["side"] == "store"
    with pytest.raises(ValueError):
        verify_prices._num("inf", "close")
