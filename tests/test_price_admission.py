"""Revision 15: impossible observations never enter the operational projection."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from engine import actions, collect, intraday, price_quarantine, verify_prices
from engine.lib import db
from engine.lib.data_quality import (
    PRICE_VALIDATOR_VERSION,
    observation_reasons,
    provisional_open_only_fault,
)

BAR = dict(ticker="AAA", date=date(2026, 10, 16), open=10., high=11.,
           low=9., close=10.5, volume=1000, source="fixture")
FIXTURE = json.loads(Path(__file__).with_name("fixtures").joinpath("r15_price_bars.json").read_text())["bars"]


def frame(*rows):
    return pd.DataFrame(rows, dtype=object)


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value,reason", [(None, "null"), (float("nan"), "nonfinite"),
                                         (float("inf"), "nonfinite"), (-float("inf"), "nonfinite"),
                                         (0., "nonpositive"), (-1., "nonpositive")])
def test_invalid_prices_retained_without_cache_row(con, field, value, reason):
    bar = {**BAR, field: value}
    assert db.upsert_prices(con, frame(bar)) == 0
    assert con.execute("SELECT count(*) FROM prices").fetchone() == (0,)
    saved = con.execute("SELECT reason,source,validator_version,observation_json FROM price_observation_rejects").fetchone()
    assert f"{field}_{reason}" in saved[0]
    assert saved[1:3] == ("fixture", PRICE_VALIDATOR_VERSION)
    assert json.loads(saved[3])[field] == (None if value is None else repr(value))


@pytest.mark.parametrize("change,reason", [({"high": 10.}, "high_geometry"),
                                          ({"low": 10.2}, "low_geometry"),
                                          ({"high": 8.}, "high_geometry"),
                                          ({"volume": -1}, "volume_negative"),
                                          ({"volume": None}, "volume_unrepresentable"),
                                          ({"volume": float("inf")}, "volume_unrepresentable"),
                                          ({"volume": 2**63}, "volume_unrepresentable"),
                                          ({"volume": .5}, "volume_unrepresentable"),
                                          ({"date": "2026-10-17"}, "off_calendar"),
                                          ({"date": "2026-07-03"}, "off_calendar"),
                                          ({"date": "1968-06-12"}, "off_calendar"),
                                          ({"date": None}, "invalid_date"),
                                          ({"ticker": ""}, "invalid_ticker")])
def test_other_hard_invalid_shapes(con, change, reason):
    assert db.upsert_prices(con, frame({**BAR, **change})) == 0
    assert reason in con.execute("SELECT reason FROM price_observation_rejects").fetchone()[0]


@pytest.mark.parametrize("bar", FIXTURE, ids=lambda b: f"{b['ticker']}-{b['date']}")
def test_original_board_and_spy_observations(con, bar):
    assert len(FIXTURE) == 42  # 41 board observations plus the October 16 SPY tuple.
    reasons = observation_reasons(bar)
    assert reasons
    if provisional_open_only_fault(bar, reasons):
        # The October 16 SPY tuple was fetched that night and only its open lies
        # outside the range: it is admitted as fetched, still provisional.
        assert (bar["ticker"], bar["date"]) == ("SPY", "2026-10-16")
        assert db.upsert_prices(con, frame(bar)) == 1
        assert con.execute("SELECT open,high,low,close FROM prices").fetchone() == tuple(
            bar[f] for f in ("open", "high", "low", "close"))
        assert con.execute("SELECT count(*) FROM price_observation_rejects").fetchone() == (0,)
        return
    assert db.upsert_prices(con, frame(bar)) == 0
    assert con.execute("SELECT count(*) FROM prices").fetchone() == (0,)
    stored = con.execute("SELECT open,high,low,close,volume FROM price_observation_rejects").fetchone()
    assert stored == (*(bar[f] for f in ("open", "high", "low", "close")), str(bar["volume"]))


def test_bad_good_bad_preserves_every_vintage_and_availability(con):
    bad1 = {**BAR, "high": 10., "fetched_at": datetime(2026, 10, 16, 22, tzinfo=timezone.utc)}
    good = {**BAR, "fetched_at": datetime(2026, 10, 17, 1, tzinfo=timezone.utc)}
    bad2 = {**BAR, "low": 10.2, "fetched_at": datetime(2026, 10, 17, 2, tzinfo=timezone.utc)}
    assert db.upsert_prices(con, frame(bad1)) == 0
    assert db.upsert_prices(con, frame(good)) == 1
    trusted = con.execute("SELECT * FROM prices").fetchall()
    assert db.upsert_prices(con, frame(bad2)) == 0
    assert con.execute("SELECT * FROM prices").fetchall() == trusted
    correction = {**good, "close": 10.6, "fetched_at": datetime(2026, 10, 17, 3, tzinfo=timezone.utc)}
    assert db.upsert_prices(con, frame(correction)) == 1
    evidence = con.execute("SELECT high,low,close,reason,fetched_at FROM price_observation_rejects ORDER BY recorded_at").fetchall()
    assert len(evidence) == 3
    assert evidence[0][:3] == (10., 9., 10.5)
    assert evidence[1][:3] == (11., 10.2, 10.5)
    assert evidence[2][:4] == (11., 9., 10.5, "replacement_predecessor")
    assert evidence[2][4] == good["fetched_at"].replace(tzinfo=None)


def test_conflicting_duplicates_hold_all_and_identical_repeats_are_evidence(con):
    assert db.upsert_prices(con, frame(BAR)) == 1
    trusted = con.execute("SELECT * FROM prices").fetchall()
    assert db.upsert_prices(con, frame(BAR, {**BAR, "close": 10.6})) == 0
    assert con.execute("SELECT * FROM prices").fetchall() == trusted
    assert con.execute("SELECT count(*) FROM price_observation_rejects WHERE reason='conflicting_duplicate'").fetchone() == (2,)
    assert db.upsert_prices(con, frame(BAR, BAR)) == 1
    assert con.execute("SELECT count(*) FROM price_observation_rejects WHERE reason='identical_duplicate'").fetchone() == (1,)


def test_projection_and_evidence_rollback_together(con, monkeypatch):
    original = db.append_price_observations

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected evidence failure")

    assert db.upsert_prices(con, frame(BAR)) == 1
    before = con.execute("SELECT * FROM prices").fetchall()
    monkeypatch.setattr(db, "append_price_observations", fail)
    with pytest.raises(RuntimeError):
        db.upsert_prices(con, frame({**BAR, "close": 10.6}))
    assert con.execute("SELECT * FROM prices").fetchall() == before
    assert con.execute("SELECT count(*) FROM price_observation_rejects").fetchone() == (0,)
    with pytest.raises(RuntimeError):
        with db.transaction(con):
            db.upsert_prices(con, frame({**BAR, "high": 10.}))
    assert con.execute("SELECT * FROM prices").fetchall() == before


@pytest.mark.parametrize("bar", [{**BAR, "open": 4., "high": 4.4, "low": 3.9, "close": 4.2},
                                 {**BAR, "open": 10., "high": 10., "low": 10., "close": 10.},
                                 {**BAR, "volume": 0}, {**BAR, "date": date(1968, 6, 13)}])
def test_valid_controls_are_not_repaired_or_rejected(con, bar):
    assert db.upsert_prices(con, frame(bar)) == 1
    assert con.execute("SELECT open,high,low,close,volume FROM prices").fetchone() == tuple(bar[f] for f in ("open", "high", "low", "close", "volume"))


def test_real_60_percent_earnings_crash_is_admitted(con):
    assert db.upsert_prices(con, frame({**BAR, "date": date(2026, 10, 15)})) == 1
    crash = {**BAR, "open": 4., "high": 4.4, "low": 3.9, "close": 4.2}
    assert db.upsert_prices(con, frame(crash)) == 1
    assert con.execute("SELECT count(*) FROM price_observation_rejects").fetchone() == (0,)


@pytest.mark.parametrize("mode", ["new_boundary", "overlap", "right_boundary", "internal"])
def test_unrecorded_factor_step_holds_affected_ticker_batch(con, mode):
    old = {**BAR, "date": date(2026, 10, 14)}
    db.upsert_prices(con, frame(old))
    split = {**BAR, "open": 30., "high": 33., "low": 27., "close": 31.5}
    if mode == "overlap":
        split["date"] = old["date"]
    if mode == "right_boundary":
        split["date"] = date(2026, 10, 13)
    batch = [split]
    if mode == "internal":
        batch.insert(0, {**BAR, "date": date(2026, 10, 15)})
    trusted = con.execute("SELECT * FROM prices").fetchall()
    assert db.upsert_prices(con, frame(*batch)) == 0
    assert con.execute("SELECT * FROM prices").fetchall() == trusted
    assert con.execute("SELECT count(*) FROM price_observation_rejects WHERE reason='basis_unverified'").fetchone() == (len(batch),)


def test_recorded_split_passes_gate_and_reconciler_retains_predecessor(con):
    db.init_actions_schema(con)
    old = {**BAR, "date": date(2026, 10, 15), "fetched_at": datetime(2026, 10, 15, 22)}
    db.upsert_prices(con, frame(old))
    con.execute("INSERT INTO corporate_actions VALUES ('AAA','2026-10-16','split',3,'fixture',now())")
    split = {**BAR, "open": 10 / 3, "high": 11 / 3, "low": 3., "close": 3.5}
    assert db.upsert_prices(con, frame(split)) == 1
    assert actions.reconcile(con)["rows_restated"] == 1
    assert con.execute("SELECT close FROM prices ORDER BY date").fetchall() == [(3.5,), (3.5,)]
    assert con.execute("SELECT close,reason FROM price_observation_rejects").fetchone() == (10.5, "split_restatement_predecessor")


@pytest.mark.parametrize("change", [{"high": 10.}, {"volume": -1}, {"ts": "2026-10-17 13:30"},
                                     {"ts": "2026-10-16 20:00"}, {"ts": "2026-11-27 18:00"},
                                     {"ts": "2026-10-16 13:31", "interval": "5m"}])
def test_intraday_boundary_rejects_invalid_observations(con, change):
    db.init_schema(con)
    db.init_queue_schema(con)
    bar = {**BAR, "ts": pd.Timestamp("2026-10-16 13:30"), "interval": "1m", **change}
    assert db.insert_intraday(con, frame(bar)) == 0
    assert con.execute("SELECT count(*) FROM intraday_prices").fetchone() == (0,)
    assert con.execute("SELECT count(*) FROM price_observation_rejects").fetchone() == (1,)


def test_intraday_conflicting_duplicates_and_append_only_controls(con):
    db.init_schema(con)
    db.init_queue_schema(con)
    bar = {**BAR, "ts": pd.Timestamp("2026-10-16 13:30"), "interval": "5m"}
    assert db.insert_intraday(con, frame(bar, {**bar, "close": 10.6})) == 0
    assert db.insert_intraday(con, frame(bar)) == 1
    before = con.execute("SELECT * FROM intraday_prices").fetchall()
    assert db.insert_intraday(con, frame({**bar, "close": 10.6})) == 0
    assert con.execute("SELECT * FROM intraday_prices").fetchall() == before


def test_collectors_retain_null_close_for_admission(con):
    raw = pd.DataFrame({"Open": [10.], "High": [11.], "Low": [9.], "Close": [None], "Volume": [100]},
                       index=pd.DatetimeIndex(["2026-10-16"], name="Date"))
    daily = collect._frame_from_sub(raw, "AAA")
    assert len(daily) == 1
    assert db.upsert_prices(con, daily) == 0
    raw.index = pd.DatetimeIndex(["2026-10-16 13:30"], name="Datetime")
    minute = intraday._frame_from_sub(raw, "AAA", "1m")
    db.init_schema(con)
    db.init_queue_schema(con)
    assert db.insert_intraday(con, minute) == 0
    assert con.execute("SELECT count(*) FROM price_observation_rejects").fetchone() == (2,)


@pytest.mark.parametrize("side", ["store", "source"])
@pytest.mark.parametrize("bar", [{**BAR, "high": 10.}, {**BAR, "low": 10.2}, {**BAR, "open": None}])
def test_impossible_verifier_bar_never_agrees(side, bar):
    day = BAR["date"]
    bars = {"store": {day: BAR}, "source": {day: BAR}}
    bars[side] = {day: bar}
    settled_as_of = date(2026, 10, 19)
    result = verify_prices.compare_bars("AAA", bars["store"], bars["source"], 9999, 9999,
                                        settled_as_of)
    assert result["status"] == "not_checked"
    assert result["reason"] == "invalid_comparison_price"
    assert result["invalid_fields"][0]["side"] == side


@pytest.mark.parametrize("side,bar,agrees", [
    ("store", {**BAR, "low": 10.2}, True), ("store", {**BAR, "open": 11.5}, True),
    ("store", {**BAR, "high": 10.}, False), ("store", {**BAR, "open": None}, False),
    ("source", {**BAR, "low": 10.2}, False)])
def test_store_provisional_open_only_fault_is_not_a_comparison_fault(side, bar, agrees):
    day = BAR["date"]
    bars = {"store": {day: BAR}, "source": {day: BAR}}
    bars[side] = {day: bar}
    result = verify_prices.compare_bars("AAA", bars["store"], bars["source"], 9999, 9999, day)
    assert (result.get("reason") != "invalid_comparison_price") is agrees


def test_valid_provisional_drift_still_agrees():
    day = BAR["date"]
    result = verify_prices.compare_bars("AAA", {day: BAR}, {day: {**BAR, "high": 12.}}, 1, .01, day)
    assert result["status"] == "agrees"
    assert result["prov"]


def test_cleanup_is_dry_by_default_preserves_valid_rows_and_is_idempotent(con):
    db.init_schema(con)
    good = {**BAR, "volume": 0}
    db.upsert_prices(con, frame(good))
    con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES ('BAD','2026-10-16',10,9,8,8.5,100), ('OFF','2026-10-17',10,11,9,10.5,100)")
    before = con.execute("SELECT * FROM prices").fetchall()
    dry = price_quarantine.cleanup_hard_invalid_prices(con)
    assert dry["invalid_rows"] == 2 and dry["moved"] == 0
    assert con.execute("SELECT * FROM prices").fetchall() == before
    report = price_quarantine.cleanup_hard_invalid_prices(con, dry_run=False)
    assert report["moved"] == 2
    assert con.execute("SELECT ticker,volume FROM prices").fetchall() == [("AAA", 0)]
    assert con.execute("SELECT ticker,reason FROM price_observation_rejects ORDER BY ticker").fetchall() == [("BAD", "high_geometry"), ("OFF", "off_calendar")]
    assert price_quarantine.cleanup_hard_invalid_prices(con)["invalid_rows"] == 0


def test_missing_provider_field_is_preserved_as_rejected_observation(con):
    raw = pd.DataFrame({"Open": [10.], "Low": [9.], "Close": [10.5], "Volume": [100]},
                       index=pd.DatetimeIndex(["2026-10-16"], name="Date"))
    parsed = collect._frame_from_sub(raw, "AAA")
    assert len(parsed) == 1
    assert db.upsert_prices(con, parsed) == 0
    assert "high_nonfinite" in con.execute("SELECT reason FROM price_observation_rejects").fetchone()[0]


def test_duplicate_date_spellings_cannot_bypass_conflict_detection(con):
    assert db.upsert_prices(con, frame(BAR, {**BAR, "date": "2026-10-16", "close": 10.6})) == 0
    assert con.execute("SELECT count(*) FROM price_observation_rejects WHERE reason='conflicting_duplicate'").fetchone() == (2,)


def test_invalid_exact_fetch_is_retained_and_never_reported_missing(con):
    from server.p15_incremental_collect import _fetch_exact

    raw = pd.DataFrame({"Open": [10.], "High": [9.], "Low": [8.], "Close": [8.5], "Volume": [100]},
                       index=pd.DatetimeIndex(["2026-10-16"], name="Date"))
    obligation = {"ticker": "AAA", "provider_ticker": "AAA", "market_date": BAR["date"]}
    receipt, parsed = _fetch_exact(obligation, requested_at=datetime.now(timezone.utc),
                                  history=lambda *_: raw, sleep=lambda _: None)
    assert receipt is None and len(parsed) == 1
    assert db.upsert_prices(con, parsed) == 0


def test_insert_values_matches_executemany_across_statement_chunks():
    import duckdb
    rows = [[i, None if i % 3 else f"v{i}", float(i) / 7 if i % 2 else None,
             date(2026, 10, 1) if i % 5 else None] for i in range(1203)]
    stored = []
    for multi in (False, True):
        con = duckdb.connect()
        con.execute("CREATE TABLE t (i INTEGER, s VARCHAR, x DOUBLE, d DATE)")
        if multi:
            db.insert_values(con, "INSERT INTO t VALUES", rows, width=4)
        else:
            con.executemany("INSERT INTO t VALUES (?,?,?,?)", rows)
        stored.append(con.execute("SELECT * FROM t ORDER BY i").fetchall())
        con.close()
    assert stored[0] == stored[1] and len(stored[1]) == 1203
    with pytest.raises(ValueError, match="width"):
        db.insert_values(duckdb.connect(), "INSERT INTO t VALUES", [[1, 2]], width=4)
