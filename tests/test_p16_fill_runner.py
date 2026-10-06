"""End-to-end fixture proof for the inert P16 fill capture runner."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from farm import p16_fill_runner
from server import intraday_source, p15_scoring_store, p16_yfinance_intraday
from sim import nyse

DAY = date(2026, 10, 5)
NY = ZoneInfo("America/New_York")


def _at(hour, minute=0, second=0):
    return datetime(2026, 10, 5, hour, minute, second, tzinfo=NY)


def _bars(source, version, *, complete=True, offset=0.0):
    starts = [_at(9, 30), _at(9, 35), _at(9, 40)]
    return {"source": source, "source_version": version, "venue": "FIXTURE",
            "provider": "fixture", "currency": "USD", "adjustment": "splits",
            "resolution": "5m", "regular_session": True, "bars": [
                {"start_at": started, "open": 100 + index + offset,
                 "high": 101 + index + offset, "low": 99 + index + offset,
                 "close": 100.5 + index + offset, "volume": 1000,
                 "vwap_value": None, "vwap_kind": None, "volume_scope": "bar"}
                for index, started in enumerate(starts[:3 if complete else 2])]}


def _registration():
    sessions, current = [], DAY
    while len(sessions) < 80:
        if nyse.is_session(current):
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    body = {"registration_id": "p16-fills-v1", "sessions": sessions,
            "calendar_sha256": canonical_sha256(sessions), "session_split": {
                "rule": "first_80_exchange_sessions_after_w9_activation",
                "training_start_index": 0, "training_count": 60,
                "validation_start_index": 60, "validation_count": 20,
                "literal_dates_written_at_w9_activation": True}}
    return {**body, "registration_sha256": canonical_sha256(body)}


def _seed_manifest_inputs(con):
    db.init_schema(con)
    p15_scoring_store.init_schema(con)
    universe = {"candidates": [{"ticker": "AAA"}, {"ticker": "BBB"}]}
    run = p15_scoring_store.create_run(
        con, market_date=date(2026, 10, 2), universe=universe, context={},
        information_cutoff_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        started_at=datetime(2026, 10, 3, tzinfo=timezone.utc), news_receipts=[])
    p15_scoring_store.complete_run(
        con, run["run_id"], trace_sha256="a" * 64,
        completed_at=datetime(2026, 10, 3, tzinfo=timezone.utc))
    days = []
    current = DAY - timedelta(days=35)
    while len(days) < 20:
        if nyse.is_session(current):
            days.append(current)
        current += timedelta(days=1)
    for ticker in ("AAA", "BBB"):
        for current in days:
            con.execute(
                "INSERT INTO prices "
                "(ticker,date,open,high,low,close,volume,source,fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)", [
                ticker, current, 99.0, 101.0, 98.0, 100.0, 1_000_000,
                "fixture", datetime(2026, 10, 3)])


def test_fixture_run_selects_captures_observes_failures_and_writes_reports(tmp_path):
    con = db.connect(tmp_path / "fill.duckdb")
    _seed_manifest_inputs(con)

    def primary(security_id, _day, attempted_at):
        if security_id == "BBB":
            raise RuntimeError("fixture unavailable")
        local = attempted_at.astimezone(NY)
        return _bars("primary", "primary-v1", complete=(local.hour, local.minute) != (9, 46))

    def secondary(_security_id, _day, _attempted_at):
        return _bars("secondary", "secondary-v1", offset=0.01)

    def quote(security_id, index, observed_at):
        return {"received_at": observed_at, "bid": 99.9, "ask": 100.1,
                "bid_at": observed_at - timedelta(seconds=1),
                "ask_at": observed_at - timedelta(seconds=1), "venue": "FIXTURE",
                "currency": "USD", "receipt_sha256": f"{index + 1:064x}"}

    result = p16_fill_runner.run_capture(
        con, DAY, bar_sources={"primary": ("primary-v1", primary),
                               "secondary": ("secondary-v1", secondary)},
        quote_fetch=quote, quote_source="fixture-quotes",
        quote_source_version="fixture-quotes-v1", primary_source="primary",
        generated_at=_at(12, 5), registration=_registration(),
        report_dir=tmp_path / "reports")

    assert result["status"] == "complete"
    assert result["selected_count"] == result["observation_count"] == 2
    rows = {row["security_id"]: row for row in result["observations"]}
    assert rows["AAA"]["quote_target_bp"] is not None
    assert rows["AAA"]["cross_source_open_gap_bp"] is not None
    assert rows["BBB"]["quote_target_bp"] is not None
    assert rows["BBB"]["liquidity_tier"] == "gte_50m"
    assert "bar_capture_failed" in rows["BBB"]["missing_reasons"]
    assert "primary_measurement_unavailable" not in rows["BBB"]["missing_reasons"]
    assert con.execute(
        "SELECT COUNT(DISTINCT security_id) FROM p16_fill_measurements "
        "WHERE security_id IN ('AAA','BBB')"
    ).fetchone() == (2,)
    assert result["report"]["status"] == "collecting"
    assert all((tmp_path / "reports" / name).exists() for name in
               ("fill-calibration.json", "fill-calibration.md"))
    attempts = con.execute(
        "SELECT status FROM p16_fill_source_captures WHERE security_id='AAA' "
        "AND source='primary' ORDER BY attempted_at").fetchall()
    assert attempts == [("missing_slots",), ("complete",)]
    con.close()


def test_yfinance_adapter_recovers_opening_bars_from_noon_response():
    epochs = [int(_at(9, minute).astimezone(timezone.utc).timestamp())
              for minute in (30, 35, 40)]
    body = json.dumps({"chart": {"error": None, "result": [{
        "meta": {"symbol": "AAA"}, "timestamp": epochs, "indicators": {"quote": [{
            "open": [100, 101, 102], "high": [101, 102, 103],
            "low": [99, 100, 101], "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1001, 1002]}]}}]}}).encode()
    response = intraday_source.Response(
        body, "application/json", 200, _at(12), _at(12, 1))

    parsed = p16_yfinance_intraday.parse(DAY, "AAA", "AAA", response)
    assert [row["start_at"].minute for row in parsed["bars"]] == [30, 35, 40]
    assert parsed["source"] == "yfinance"
