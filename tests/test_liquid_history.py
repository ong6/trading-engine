"""Weekly history accounting against retained Yahoo responses."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from engine import collect, liquid_history
from engine.lib import db

FIXTURE = json.loads((Path(__file__).parent / "fixtures/liquid_history_recorded.json").read_text())


def recorded_batch():
    frames = {}
    for ticker in ("BGIG", "MHD", "SVA"):
        rows = [r[1:] for r in FIXTURE["rows"] if r[0] == ticker]
        frame = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        frames[ticker] = frame.set_index(pd.to_datetime(frame.pop("Date")))
    return pd.concat(frames, axis=1, sort=True)


def test_recorded_padding_is_absent_but_invalid_source_bar_stays_rejected(tmp_path):
    path = tmp_path / "market.duckdb"
    con = db.connect(path)
    db.init_schema(con)
    frame, got = collect._extract_long(recorded_batch(), {t: t for t in ("BGIG", "MHD", "SVA")})
    assert got == {"BGIG", "MHD", "SVA"}
    db.upsert_prices(con, frame)
    assert frame.attrs["rejected_tickers"] == {"SVA"}
    assert con.execute("SELECT ticker FROM prices ORDER BY ticker").fetchall() == [("BGIG",), ("MHD",)]
    assert con.execute("SELECT ticker,reason FROM price_observation_rejects").fetchall() == [
        ("SVA", "open_nonpositive"),
    ]
    con.close()


def source_response(status, body):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(str(status))
    return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=raise_for_status)


@pytest.mark.parametrize("ticker", ["MSGK-V", "MSGR-V"])
def test_recorded_no_history_is_a_completed_absence(monkeypatch, ticker):
    response = FIXTURE["absences"][ticker]
    monkeypatch.setattr(liquid_history.requests, "get", lambda *_a, **_k: source_response(
        response["status"], response["body"],
    ))
    assert liquid_history.probe(ticker) == ("no_data", None)


@pytest.mark.parametrize("status,body", [
    (429, FIXTURE["absences"]["MSGR-V"]["body"]),
    (404, {"chart": {"result": None, "error": {"code": "Not Found", "description": "Bad request"}}}),
    (200, {"chart": {"result": []}}),
    (200, {}),
])
def test_http_and_ambiguous_errors_are_retryable(monkeypatch, status, body):
    monkeypatch.setattr(liquid_history.requests, "get", lambda *_a, **_k: source_response(status, body))
    reason, frame = liquid_history.probe("MSGR-V")
    assert reason.startswith("fetch_error:") and frame is None


def history_store(path, *, liquid):
    con = db.connect(path)
    db.init_schema(con)
    con.executemany("INSERT INTO universe (ticker,yf_ticker,name,added,active,liquid) "
                    "VALUES (?,?,?, '2026-10-23', TRUE, ?)", [
                        ("BGIG", "BGIG", "Bahl & Gaynor Income Growth ETF", liquid),
                        ("MSGR.V", "MSGR-V", "MSG Rangers Corp. Class A Common Stock When-Issued", liquid),
                    ])
    con.close()


@pytest.mark.parametrize("liquid", [False, True])
def test_weekly_absence_persists_without_bars_or_weekly_retries(monkeypatch, tmp_path, liquid):
    path = tmp_path / "market.duckdb"
    history_store(path, liquid=liquid)
    batch = recorded_batch()[["BGIG"]]
    calls = []
    monkeypatch.setattr(collect, "_download", lambda *_a, **_k: batch)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(liquid_history, "probe", lambda ticker: calls.append(ticker) or ("no_data", None))
    if liquid:
        assert collect.mode_backfill(path, None) == (2, 0)
        assert collect.mode_backfill(path, None) == (0, 0)
    else:
        total, failed, summary = collect.mode_refresh_liquid(path, None, False)
        assert (total, failed, summary["candidates_no_data"]) == (2, 0, 1)
        total, failed, summary = collect.mode_refresh_liquid(path, None, False)
        assert (total, failed, summary["candidates_suppressed"]) == (0, 0, 1)
    assert calls == ["MSGR-V"]
    con = db.connect(path)
    assert con.execute("SELECT COUNT(*) FROM prices WHERE ticker='MSGR.V'").fetchone() == (0,)
    assert con.execute("SELECT backfill_done FROM universe WHERE ticker='MSGR.V'").fetchone() == (False,)
    con.execute("UPDATE universe SET name='New directory identity' WHERE ticker='MSGR.V'")
    con.close()
    mapping, _ = liquid_history.exclude_absences(path, {"MSGR-V": "MSGR.V"})
    assert mapping == {"MSGR-V": "MSGR.V"}


def test_absence_cooldown_expires_and_true_failure_stays_pending(monkeypatch, tmp_path):
    path = tmp_path / "market.duckdb"
    history_store(path, liquid=True)
    monkeypatch.setattr(collect, "_download", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(liquid_history, "probe", lambda t: ("no_data" if t == "MSGR-V" else "fetch_error:Timeout", None))
    assert collect.mode_backfill(path, None) == (2, 1)
    assert collect.mode_backfill(path, None) == (1, 1)
    con = db.connect(path)
    payload = json.loads(con.execute("SELECT params FROM jobs ORDER BY id LIMIT 1").fetchone()[0])
    assert payload["failed"] == {"BGIG": "fetch_error:Timeout"}
    con.execute("UPDATE jobs SET updated_at=?", [datetime.now(timezone.utc) - timedelta(days=91)])
    con.close()
    assert collect.mode_backfill(path, None) == (2, 1)


def test_missing_batch_name_with_history_is_recovered(monkeypatch, tmp_path):
    path = tmp_path / "market.duckdb"
    history_store(path, liquid=True)
    monkeypatch.setattr(collect, "_download", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    frame = recorded_batch()["BGIG"]
    monkeypatch.setattr(liquid_history, "probe", lambda t: ("data", frame) if t == "BGIG" else ("no_data", None))
    assert collect.mode_backfill(path, None) == (2, 0)
    con = db.connect(path)
    assert con.execute("SELECT ticker,backfill_done FROM universe ORDER BY ticker").fetchall() == [
        ("BGIG", True), ("MSGR.V", False),
    ]
    con.close()


def test_no_recent_history_is_not_a_fetch_failure_or_a_max_history_absence(monkeypatch, tmp_path):
    path = tmp_path / "market.duckdb"
    history_store(path, liquid=False)
    monkeypatch.setattr(collect.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(liquid_history, "probe", lambda _t: ("data", recorded_batch()["BGIG"]))
    _, _, absent, failed, _ = collect._weekly_absent(pd.DataFrame(), set(), {"BGIG": "BGIG"}, 1, start="2026-10-24")
    assert absent == {"BGIG": "no_recent_history"} and failed == {}
    con = db.connect(path)
    jid = collect._start_job(con, "refresh-liquid", "{}", 1)
    liquid_history.record(con, jid, with_data=set(), no_data=absent, failed=failed)
    collect._update_job(con, jid, "1/1", state="done")
    con.close()
    assert liquid_history.exclude_absences(path, {"BGIG": "BGIG"}) == ({}, ["BGIG"])
    assert liquid_history.exclude_absences(path, {"BGIG": "BGIG"}, mode="backfill") == ({"BGIG": "BGIG"}, [])
