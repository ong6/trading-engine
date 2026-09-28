"""Known-answer tests for P16's inert fill capture and measurements."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from engine import p16_fill_capture
from engine.lib import db
from server import p15_scoring_store, p16_fill_store
from sim import p15_books

DAY = date(2026, 10, 5)
NY = ZoneInfo("America/New_York")


def _at(hour, minute, second=0):
    return datetime(2026, 10, 5, hour, minute, second, tzinfo=NY)


def _bars(*, missing=False, with_vwap=True):
    starts = p16_fill_capture.expected_bar_starts(DAY)
    rows = []
    for index, started in enumerate(starts[:2] if missing else starts):
        o = 100 + index
        rows.append({
            "start_at": started, "open": o, "high": o + 1, "low": o - 1,
            "close": o + 0.5, "volume": 1000 + index,
            "vwap_value": o + 0.25 if index == 0 and with_vwap else None,
            "vwap_kind": "reported_provider" if index == 0 and with_vwap else None,
            "volume_scope": "bar",
        })
    return {
        "source": "fixture", "source_version": "fixture-v1", "venue": "TEST",
        "provider": "fixture", "currency": "USD", "adjustment": "splits",
        "resolution": "5m", "regular_session": True, "bars": rows,
    }


def _quote(index, *, native_times=True):
    received = _at(9, 31, 5) if index == 0 else _at(9, 34, 5)
    return {
        "received_at": received, "bid": 99.9, "ask": 100.1,
        "bid_at": received - timedelta(seconds=1) if native_times else None,
        "ask_at": received - timedelta(seconds=1) if native_times else None,
        "venue": "TEST", "currency": "USD", "source": "fixture",
        "receipt_sha256": f"{index + 1:064x}",
    }


def test_hash_sample_is_fixed_without_replacement_and_reports_shortfall():
    rows = [{"ticker": f"T{index:02d}"} for index in range(25)]
    first = p16_fill_capture.select_sample(DAY, rows)
    second = p16_fill_capture.select_sample(DAY, list(reversed(rows)))
    short = p16_fill_capture.select_sample(DAY, rows[:3])

    assert first == second
    assert len(first["selected_security_ids"]) == len(set(first["selected_security_ids"])) == 20
    assert first["inclusion_probability"] == 0.8
    assert short["sample_shortfall"] == 17
    assert short["inclusion_probability"] == 1.0


def test_bar_and_quote_measurements_keep_proxy_vwap_and_open_distinct():
    bar_set = p16_fill_capture.normalize_bars(DAY, _bars())
    quotes = [p16_fill_capture.normalize_quote(DAY, index, _quote(index))
              for index in (0, 1)]
    measured = p16_fill_capture.measure_symbol_day(
        session_date=DAY, security_id="AAA", source="fixture",
        bar_set=bar_set, quote_rows=quotes, operational_open=99.5,
        simulated_fill=100.5, side="buy",
    )

    assert bar_set["status"] == "complete"
    assert bar_set["metrics"]["vwap_gap_bp"] == pytest.approx(25)
    assert bar_set["metrics"]["hlc3_gap_bp"] == pytest.approx(16.6666667)
    assert measured["quote_target_bp"] == pytest.approx(10)
    assert measured["open_source_gap_bp"] == pytest.approx(50.2512563)
    assert measured["sim_vs_vwap_bp"] == pytest.approx(24.9376559)
    assert measured["execution_basis_verified"] is False
    assert measured["v5_activation_eligible"] is False


def test_missing_slot_and_unverified_side_timestamps_are_visible():
    bar_set = p16_fill_capture.normalize_bars(DAY, _bars(missing=True, with_vwap=False))
    quotes = [p16_fill_capture.normalize_quote(
        DAY, index, _quote(index, native_times=False)) for index in (0, 1)]
    measured = p16_fill_capture.measure_symbol_day(
        session_date=DAY, security_id="AAA", source="fixture",
        bar_set=bar_set, quote_rows=quotes)

    assert bar_set["status"] == "missing_slots"
    assert bar_set["metrics"].get("half_range_proxy_bp") is None
    assert measured["quote_target_bp"] is None
    assert measured["quote_statuses"] == ["quote_target_unverified"] * 2


def test_zero_volume_and_halted_bars_record_explicit_reasons():
    payload = _bars()
    payload["bars"][0]["volume"] = 0
    payload["bars"][1]["halted"] = True
    bar_set = p16_fill_capture.normalize_bars(DAY, payload)

    assert bar_set["status"] == "quality_unavailable"
    assert bar_set["missing_reasons"] == ["zero_volume_0930", "halted_0935"]
    assert bar_set["metrics"].get("half_range_proxy_bp") is None


def test_measurement_identity_distinguishes_names_and_all_missing_days():
    empty = _bars(missing=True, with_vwap=False)
    empty["bars"] = []
    bar_set = p16_fill_capture.normalize_bars(DAY, empty)
    first = p16_fill_capture.measure_symbol_day(
        session_date=DAY, security_id="AAA", source="fixture",
        bar_set=bar_set, quote_rows=[])
    second = p16_fill_capture.measure_symbol_day(
        session_date=DAY, security_id="BBB", source="fixture",
        bar_set=bar_set, quote_rows=[])

    assert first["measurement_sha256"] != second["measurement_sha256"]
    assert first["first_open"] is None
    assert first["session_date"] == DAY.isoformat()


def test_manifest_and_measurement_run_end_to_end_on_fixture_store(tmp_path):
    con = db.connect(tmp_path / "fixture.duckdb")
    p15_scoring_store.init_schema(con)
    p15_books.init_schema(con)
    p16_fill_store.init_schema(con)
    candidates = [{"ticker": f"T{index:02d}"} for index in range(25)]
    universe = {"market_date": "2026-10-02", "candidates": candidates}
    run = p15_scoring_store.create_run(
        con, market_date=date(2026, 10, 2), universe=universe, context={},
        information_cutoff_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        started_at=datetime(2026, 10, 3, tzinfo=timezone.utc), news_receipts=[],
    )
    p15_scoring_store.complete_run(
        con, run["run_id"], trace_sha256="a" * 64,
        completed_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    con.execute(
        "INSERT INTO p15_order_intents "
        "(id,decision_id,portfolio_id,ticker,side,qty,signal_date,order_role,priority,"
        "signal_close,entry_atr,limit_px,status,reason,sim_order_id,created_at) "
        "VALUES (1,NULL,'p15_ai_ranked','ORDERED','buy',2,DATE '2026-10-02',"
        "'entry',1,100,2,101,'pending',NULL,NULL,?)",
        [_at(9, 25).astimezone(timezone.utc).replace(tzinfo=None)],
    )

    manifest = p16_fill_store.build_manifest(con, DAY)
    assert manifest["status"] == "ready"
    assert "ORDERED" in manifest["targets"] and "SPY" in manifest["targets"]
    assert p16_fill_store.record_manifest(con, manifest) == manifest["manifest_sha256"]
    assert p16_fill_store.record_manifest(con, manifest) == manifest["manifest_sha256"]
    con.execute("UPDATE p15_order_intents SET status='filled',reason='after_open',sim_order_id=7")
    assert p16_fill_store.build_manifest(con, DAY) == manifest
    assert p16_fill_store.order_outcomes(con, DAY) == [{
        "id": 1, "status": "filled", "reason": "after_open", "sim_order_id": 7}]

    bar_set = p16_fill_capture.normalize_bars(DAY, _bars())
    receipt = "b" * 64
    capture_sha = p16_fill_store.record_source_capture(
        con, session_date=DAY, security_id="T00", receipt_sha256=receipt,
        attempted_at=_at(9, 46), payload=bar_set,
    )
    assert len(capture_sha) == 64
    quotes = [p16_fill_capture.normalize_quote(DAY, index, _quote(index))
              for index in (0, 1)]
    measured = p16_fill_capture.measure_symbol_day(
        session_date=DAY, security_id="T00", source="fixture",
        bar_set=bar_set, quote_rows=quotes)
    assert p16_fill_store.record_measurement(
        con, session_date=DAY, security_id="T00", source="fixture",
        median_dollar_volume=60_000_000, bar_set_sha256=bar_set["bar_set_sha256"],
        measured_at=_at(12, 5), measurement=measured,
    ) == measured["measurement_sha256"]
    assert con.execute("SELECT COUNT(*) FROM p16_fill_manifests").fetchone() == (1,)
    assert con.execute("SELECT liquidity_tier FROM p16_fill_measurements").fetchone() == (
        "gte_50m",)
    con.close()


def test_liquidity_uses_up_to_60_prior_rows_known_by_selection(tmp_path):
    con = db.connect(tmp_path / "liquidity.duckdb")
    db.init_schema(con)
    day = DAY - timedelta(days=35)
    inserted = 0
    while inserted < 20:
        if p16_fill_capture.nyse.is_session(day):
            con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?)", [
                "AAA", day, 99.0, 101.0, 98.0, 100.0, 1000, "fixture",
                _at(9, 19).astimezone(timezone.utc).replace(tzinfo=None)])
            inserted += 1
        day += timedelta(days=1)
    late_day = DAY - timedelta(days=1)
    con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?)", [
        "AAA", late_day, 199.0, 201.0, 198.0, 200.0, 1000, "fixture",
        _at(9, 21).astimezone(timezone.utc).replace(tzinfo=None)])

    result = p16_fill_store.liquidity_as_of(
        con, "AAA", DAY, information_cutoff_at=_at(9, 20))
    assert result["status"] == "available"
    assert result["valid_sessions"] == 20
    assert result["median_dollar_volume_60d"] == 100_000
    with pytest.raises(ValueError, match="after selection"):
        p16_fill_store.liquidity_as_of(
            con, "AAA", DAY, information_cutoff_at=_at(9, 21))
    con.close()


def test_manifest_refuses_snapshot_completed_after_selection(tmp_path):
    con = db.connect(tmp_path / "fixture.duckdb")
    p15_scoring_store.init_schema(con)
    run = p15_scoring_store.create_run(
        con, market_date=date(2026, 10, 2),
        universe={"candidates": [{"ticker": "AAA"}]}, context={},
        information_cutoff_at=_at(9, 21), started_at=_at(9, 21), news_receipts=[],
    )
    p15_scoring_store.complete_run(
        con, run["run_id"], trace_sha256="c" * 64, completed_at=_at(9, 21),
    )
    assert p16_fill_store.build_manifest(con, DAY)["status"] == "unavailable"
    con.close()
