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


def _source_with(days):
    def fetch(ticker, **_kw):
        return {"symbol": ticker, "bars": {d: {"open": 10, "high": 11, "low": 9,
                                                "close": 10, "volume": 100} for d in days},
                "parse_errors": [], "rows": len(days)}
    return fetch


def test_newest_session_reports_source_lag_rather_than_a_silent_gap(monkeypatch, con, tmp_path):
    """Rev-14 (h): `volume_median_abs_diff_pct_latest_session` was null every night
    since 09-08 while the note said the newest close is checked on every name: at
    22:35 UTC the source's newest row is still the previous session."""
    db.init_schema(con)
    days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)]
    for ticker in ("AAA", "BBB"):
        con.execute("INSERT INTO universe(ticker,etf) VALUES (?,FALSE)", [ticker])
        for day in days:
            con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume) "
                        "VALUES (?,?,10,11,9,10,100)", [ticker, day])
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", _source_with(days[:-1]))
    params = {"tickers": ["AAA", "BBB"], "sessions": 3}

    nightly = verify_prices.run(params, con, tmp_path / "meta.json")

    assert nightly["newest_session"] == {
        "session": "2026-10-14", "status": "not_checked", "reason": "source_lag",
        "names_with_store_bar": 2, "names_compared": 0,
        "source_latest_session": "2026-10-13",
    }
    assert nightly["volume_median_abs_diff_pct_latest_session"] is None
    assert "not compared" in nightly["provisional_note"]

    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", _source_with(days))
    weekly = verify_prices.run(params, con, tmp_path / "meta.json")

    assert weekly["newest_session"] == {
        "session": "2026-10-14", "status": "checked", "reason": None,
        "names_with_store_bar": 2, "names_compared": 2,
        "source_latest_session": "2026-10-14",
    }
    assert "close IS checked" in weekly["provisional_note"]


def test_weekly_full_verify_keeps_its_own_metadata_key(monkeypatch, tmp_path):
    """Rev-14 (h): the Saturday full-universe result was overwritten by the next
    nightly sample under the shared `price_verify` key."""
    import json
    import sys

    meta = tmp_path / "data" / "_meta.json"
    meta.parent.mkdir()
    monkeypatch.setattr(
        verify_prices, "run_connection_narrowed",
        lambda params, **_kw: {"as_of": "2026-10-09", "sample": params["sample"]},
    )
    for argv in (["--sample", "5000", "--meta-key", verify_prices.FULL_META_KEY],
                 ["--sample", "40"]):
        monkeypatch.setattr(sys, "argv", ["verify_prices", "--meta", str(meta), *argv])
        assert verify_prices.main() == 0

    stored = json.loads(meta.read_text())
    assert stored[verify_prices.FULL_META_KEY]["sample"] == 5000
    assert stored[verify_prices.META_KEY]["sample"] == 40


def _rows_response(symbol, rows):
    return _response({"symbol": symbol, "tradesTable": {"rows": rows}})


def test_etf_answer_with_no_volume_on_any_row_is_not_a_price_history(monkeypatch, con, tmp_path):
    """Weekly 10-18: VFLO and GFLW came back under their own symbol as index levels
    (84,130.335, volume N/A on every row), and the tax-exempt bond ETFs (VTEL,
    VTEC, VTEI, VTES) as an untraded three-decimal series, again with no volume on
    any row. All six disagreed, 65 of the 73 disagreements; every other ETF answer
    (1,224) carried volumes."""
    db.init_schema(con)
    days = [date(2026, 10, 15), date(2026, 10, 16)]
    for ticker in ("IDX", "BOND", "SPY", "THIN"):
        con.execute("INSERT INTO universe(ticker,etf) VALUES (?,?)", [ticker, ticker != "THIN"])
        for day in days:
            con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume) "
                        "VALUES (?,?,52.9,53.3,52.8,53.0,1000)", [ticker, day])

    def row(day, price, volume):
        return {"date": day.strftime("%m/%d/%Y"), "open": price, "high": price,
                "low": price, "close": price, "volume": volume}

    answers = {
        "IDX": [row(d, "84,130.335", "N/A") for d in days],
        "BOND": [row(d, "53.25", "N/A") for d in days],
        "SPY": [row(days[0], "53.25", "N/A"), row(days[1], "53.25", "1,000")],
        "THIN": [row(d, "$53.25", "N/A") for d in days],
    }
    monkeypatch.setattr(verify_prices, "fetch_nasdaq_response",
                        lambda ticker, **_kw: _rows_response(ticker, answers[ticker]))
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)
    result = verify_prices.run({"tickers": list(answers), "sessions": 2}, con,
                               tmp_path / "meta.json")

    status = {r["ticker"]: (r["status"], r.get("reason")) for r in result["name_results"]}
    assert status["IDX"] == ("not_checked", "source_identity")
    assert status["BOND"] == ("not_checked", "source_identity")
    # One volume-less row is not a non-trade series, and stocks are not exempted:
    # both are still compared and a real gap is still a disagreement.
    assert status["SPY"] == ("disagrees", None)
    assert status["THIN"] == ("disagrees", None)
    assert result["not_checked_reasons"] == {"source_identity": 2}
    assert {d["ticker"] for d in result["disagreements"]} == {"SPY", "THIN"}
    assert "no volume" in result["not_checked_names"][0]["detail"]


def _evidence_acc():
    return {"as_of": "2026-10-16", "names_checked": 1,
            "source_evidence": {"AAA": [{"body_base64": "Ym9keQ==", "body_sha256": "x"}]},
            "store_evidence": {"AAA": {"2026-10-16": {"close": 10.0}}}}


@pytest.mark.parametrize("extra", [[], ["--no-meta"]])
def test_main_prints_the_summary_never_the_raw_evidence(monkeypatch, tmp_path, capsys, extra):
    """Weekly logs grew from 0.23 MB to ~18 MB: main() printed the full accounting,
    base64 response bodies included, before retain_evidence stripped them."""
    import json
    import sys

    meta = tmp_path / "data" / "_meta.json"
    meta.parent.mkdir()
    monkeypatch.setattr(verify_prices, "run_connection_narrowed", lambda *_a, **_kw: _evidence_acc())
    monkeypatch.setattr(sys, "argv", ["verify_prices", "--meta", str(meta), *extra])
    assert verify_prices.main() == 0

    out = capsys.readouterr().out
    assert "body_base64" not in out and "source_evidence" not in out
    assert "store_evidence" not in out
    printed, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    assert printed["names_checked"] == 1
    if not extra:
        receipt = printed["evidence_receipt"]
        stored = json.loads((meta.parent / receipt["path"]).read_text())
        assert stored["source_evidence"]["AAA"][0]["body_base64"] == "Ym9keQ=="


def test_old_unreferenced_receipts_are_pruned(monkeypatch, tmp_path):
    """data/price-verify had no retention: 66 MB in two weeks, ~15 MB per weekly pass."""
    import json
    import sys

    meta = tmp_path / "data" / "_meta.json"
    receipts = meta.parent / "price-verify"
    receipts.mkdir(parents=True)
    old = time.time() - (verify_prices.RECEIPT_RETENTION_DAYS + 1) * 86_400
    names = {kind: f"{kind[0] * 64}.json" for kind in ("aged", "cited", "fresh")}
    for kind, name in names.items():
        (receipts / name).write_text("{}")
        if kind != "fresh":
            os.utime(receipts / name, (old, old))
    for other in (".receipt-partial", "notes.json"):
        (receipts / other).write_text("{}")
        os.utime(receipts / other, (old, old))
    cited = {"evidence_receipt": {"sha256": "c" * 64, "path": f"price-verify/{'c' * 64}.json"}}
    meta.write_text(json.dumps({verify_prices.FULL_META_KEY: cited}))
    monkeypatch.setattr(verify_prices, "run_connection_narrowed", lambda *_a, **_kw: _evidence_acc())
    monkeypatch.setattr(sys, "argv", ["verify_prices", "--meta", str(meta)])
    assert verify_prices.main() == 0

    left = {p.name for p in receipts.iterdir()}
    written = json.loads(meta.read_text())[verify_prices.META_KEY]["evidence_receipt"]["sha256"]
    assert left == {names["cited"], names["fresh"], f"{written}.json",
                    ".receipt-partial", "notes.json"}
