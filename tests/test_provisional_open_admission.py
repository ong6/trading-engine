"""Same-night bars whose only fault is the open are admitted as fetched, never traded on.

On 2026-10-19 the nightly stored 228 of 4,058 same-session yfinance bars with the open
outside [low, high] and every close inside; settled re-fetches show 0-2. Ingest admits
exactly that shape while the bar is provisional (fetched on or before its New York
session date), stores the open unchanged, and leaves every open-consuming path (fills,
P15 limit-on-open, labels, the opportunity gap return) to wait for the settled bar.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from engine import daily_opportunities, price_quarantine
from engine.lib import db
from engine.lib.data_quality import (
    PROVISIONAL_REPLACEMENT_SKIPPED,
    bar_is_provisional,
    observation_reasons,
    provisional_open_fault_sql,
    provisional_open_only_fault,
)
from farm import experiment_runner
from server import (
    agent_context,
    agent_data_contract,
    agent_evaluation,
    market_read_models,
    p16_transfer,
)
from sim import fills, p15_fills
from tests.conftest import insert_bars
from tests.test_daily_opportunities import MARKET_DATE, _database

DAY = date(2026, 10, 19)
PRIOR = date(2026, 10, 16)
SAME_NIGHT = datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc)
NEXT_NIGHT = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)
GAP_UP = dict(ticker="AAA", date=DAY, open=10.8, high=10.6, low=9.9, close=10.4,
              volume=1000, source="fixture", fetched_at=SAME_NIGHT)
GAP_DOWN = {**GAP_UP, "open": 9.7}
SETTLED = {**GAP_UP, "open": 10.1, "high": 10.7, "low": 9.8, "close": 10.45,
           "volume": 1200, "fetched_at": NEXT_NIGHT}


def frame(*rows):
    return pd.DataFrame(rows, dtype=object)


def stored(con, ticker="AAA", day=DAY):
    return con.execute(
        "SELECT open,high,low,close,volume,fetched_at FROM prices WHERE ticker=? AND date=?",
        [ticker, day],
    ).fetchone()


def reject_reasons(con):
    return [row[0] for row in con.execute(
        "SELECT reason FROM price_observation_rejects ORDER BY recorded_at,reason"
    ).fetchall()]


@pytest.mark.parametrize("bar", [GAP_UP, GAP_DOWN], ids=["above_high", "below_low"])
def test_provisional_open_only_fault_is_admitted_as_fetched(con, bar):
    assert observation_reasons(bar) in (["high_geometry"], ["low_geometry"])
    assert db.upsert_prices(con, frame(bar)) == 1
    open_, high, low, close, volume, fetched_at = stored(con)
    assert (open_, high, low, close, volume) == (bar["open"], 10.6, 9.9, 10.4, 1000)
    assert bar_is_provisional(DAY, fetched_at)
    assert reject_reasons(con) == []


@pytest.mark.parametrize("change,reason", [
    ({"close": 10.7}, "high_geometry"),             # close above the high
    ({"close": 9.8}, "low_geometry"),               # close below the low
    ({"high": 9.8}, "high_geometry"),               # high below the low
    ({"low": 0.}, "low_nonpositive"),
    ({"close": float("nan")}, "close_nonfinite"),
    ({"volume": -1}, "volume_negative"),
    ({"volume": 0.5}, "volume_unrepresentable"),
    ({"ticker": "aaa"}, "invalid_ticker"),
    ({"date": "2026-10-18", "fetched_at": datetime(2026, 10, 18, 22, tzinfo=timezone.utc)},
     "off_calendar"),
])
def test_any_other_fault_on_a_provisional_bar_stays_rejected(con, change, reason):
    bar = {**GAP_UP, **change}
    assert not provisional_open_only_fault(bar, observation_reasons(bar))
    assert db.upsert_prices(con, frame(bar)) == 0
    assert con.execute("SELECT count(*) FROM prices").fetchone() == (0,)
    assert reason in reject_reasons(con)[0]


@pytest.mark.parametrize("fetched_at,admitted", [
    (datetime(2026, 10, 20, 3, 59, tzinfo=timezone.utc), True),    # 23:59 New York
    (datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc), False),    # next New York day
    (NEXT_NIGHT, False),
    (datetime(2026, 10, 20, 4, 0), False),                         # naive UTC as stored
    (datetime(2026, 10, 19, 22, 30), True),
])
def test_the_same_fault_on_a_settled_bar_stays_rejected(con, fetched_at, admitted):
    assert db.upsert_prices(con, frame({**GAP_UP, "fetched_at": fetched_at})) == int(admitted)
    assert reject_reasons(con) == ([] if admitted else ["high_geometry"])


def test_unknown_fetch_time_is_not_provisional(con):
    bar = {key: value for key, value in GAP_UP.items() if key != "fetched_at"}
    assert not provisional_open_only_fault({**bar, "fetched_at": None}, ["high_geometry"])
    # Ingest stamps a missing fetched_at with its own clock, which is after the session.
    assert db.upsert_prices(con, frame({**bar, "date": date(2026, 10, 1)})) == 0


def test_settled_refetch_replaces_the_provisional_bar_through_the_normal_path(con):
    assert db.upsert_prices(con, frame(GAP_UP)) == 1
    assert db.upsert_prices(con, frame(SETTLED)) == 1
    open_, high, low, close, volume, fetched_at = stored(con)
    assert (open_, high, low, close, volume) == (10.1, 10.7, 9.8, 10.45, 1200)
    assert not bar_is_provisional(DAY, fetched_at)
    predecessor = con.execute(
        "SELECT reason,open,high,low,close FROM price_observation_rejects").fetchall()
    assert predecessor == [("replacement_predecessor", 10.8, 10.6, 9.9, 10.4)]


def test_an_invalid_settled_refetch_keeps_the_provisional_bar_and_is_counted(con):
    assert db.upsert_prices(con, frame(GAP_UP)) == 1
    assert db.upsert_prices(con, frame({**GAP_UP, "fetched_at": NEXT_NIGHT})) == 0
    assert stored(con)[0] == 10.8
    assert reject_reasons(con) == ["high_geometry"]
    quality = market_read_models.retained_bar_quality(con, ["AAA"], DAY)["AAA"]
    assert quality["invalid_count"] == 1 and quality["reason"] == "high_geometry"


def test_a_provisional_open_fault_never_displaces_a_complete_bar(con):
    complete = {**SETTLED, "fetched_at": SAME_NIGHT}
    assert db.upsert_prices(con, frame(complete)) == 1
    later = {**GAP_UP, "fetched_at": SAME_NIGHT + timedelta(minutes=30)}
    incoming = frame(later)
    assert db.upsert_prices(con, incoming) == 0
    assert stored(con)[:5] == (10.1, 10.7, 9.8, 10.45, 1200)
    # Retained as evidence of a skipped replacement, not as an invalid date.
    assert reject_reasons(con) == [PROVISIONAL_REPLACEMENT_SKIPPED]
    assert incoming.attrs["rejected_tickers"] == set()
    quality = market_read_models.retained_bar_quality(con, ["AAA"], DAY)["AAA"]
    assert (quality["retained_count"], quality["invalid_count"]) == (1, 0)
    # A newer same-night observation may still replace an admitted provisional one.
    con.execute("DELETE FROM prices")
    con.execute("DELETE FROM price_observation_rejects")
    assert db.upsert_prices(con, frame(GAP_UP)) == 1
    assert db.upsert_prices(con, frame({**GAP_DOWN, "fetched_at": later["fetched_at"]})) == 1
    assert stored(con)[0] == 9.7
    assert reject_reasons(con) == ["replacement_predecessor"]


def test_retained_bar_quality_does_not_count_an_admitted_provisional_bar(con):
    insert_bars(con, "AAA", [PRIOR], open_=10, high=10.5, low=9.5, close=10.2)
    assert db.upsert_prices(con, frame(GAP_UP)) == 1
    quality = market_read_models.retained_bar_quality(con, ["AAA"], DAY)["AAA"]
    assert quality == {"as_of": DAY, "retained_count": 2, "invalid_count": 0,
                       "latest_invalid_date": None, "reason": None}
    assert db.upsert_prices(con, frame(SETTLED)) == 1
    assert market_read_models.retained_bar_quality(con, ["AAA"], DAY)["AAA"] == quality


def test_the_2026_10_19_shape_admits_only_same_night_open_faults(con):
    """A night like 2026-10-19: provisional open faults admitted, settled days unchanged."""
    names = [f"N{index:02d}" for index in range(40)]
    settled_night = datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc)
    history = []
    for index, ticker in enumerate(names):
        valid = dict(ticker=ticker, date=PRIOR, open=10., high=10.5, low=9.5, close=10.2,
                     volume=1000, source="fixture", fetched_at=settled_night)
        # Two settled re-fetches carry the open fault; they stay rejected.
        history.append({**valid, "open": 10.7} if index < 2 else valid)
    assert db.upsert_prices(con, frame(*history)) == 38
    tonight = []
    for index, ticker in enumerate(names):
        bar = dict(ticker=ticker, date=DAY, open=10.3, high=10.6, low=10.0, close=10.4,
                   volume=1000, source="fixture", fetched_at=SAME_NIGHT)
        if index % 4 == 0:
            bar["open"] = 10.9 if index % 8 == 0 else 9.9   # open-only fault
        elif index == 3:
            bar["close"] = 10.8                              # close outside: still rejected
        tonight.append(bar)
    assert db.upsert_prices(con, frame(*tonight)) == 39
    counts = dict(con.execute("SELECT date,count(*) FROM prices GROUP BY date").fetchall())
    assert counts == {PRIOR: 38, DAY: 39}
    rejected = con.execute(
        "SELECT date,count(*) FROM price_observation_rejects GROUP BY date ORDER BY date"
    ).fetchall()
    assert rejected == [(PRIOR, 2), (DAY, 1)]
    open_faults = con.execute(
        "SELECT count(*) FROM prices WHERE date=? AND (open>high OR open<low)", [DAY]
    ).fetchone()
    assert open_faults == (10,)


@pytest.mark.parametrize("zone", ["UTC", "Asia/Singapore", "America/New_York"])
@pytest.mark.parametrize("fetched_at", [None, datetime(2026, 10, 19, 22, 30),
                                        datetime(2026, 10, 20, 3, 59),
                                        datetime(2026, 10, 20, 4, 0), datetime(2026, 10, 21)])
@pytest.mark.parametrize("open_", [10.8, 10.3, 9.7])
def test_sql_twin_matches_the_validator(con, zone, fetched_at, open_):
    con.execute(f"SET TimeZone='{zone}'")
    con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
                "VALUES ('AAA',?,?,10.6,9.9,10.4,1000,?)", [DAY, open_, fetched_at])
    found = con.execute(f"SELECT {provisional_open_fault_sql()} FROM prices").fetchone()[0]
    bar = {**GAP_UP, "open": open_, "fetched_at": fetched_at}
    assert bool(found) is provisional_open_only_fault(bar, observation_reasons(bar))


def _admitted_entry(con):
    """SPY and AAA traded on PRIOR; tonight's AAA bar carries an open-only fault."""
    settled = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
    for ticker in ("SPY", "AAA"):
        insert_bars(con, ticker, [PRIOR], open_=10, high=10.5, low=9.5, close=10.2)
        con.execute("UPDATE prices SET fetched_at=? WHERE ticker=?",
                    [settled.replace(tzinfo=None), ticker])
    spy = {**SETTLED, "ticker": "SPY", "fetched_at": SAME_NIGHT}
    assert db.upsert_prices(con, frame(spy, GAP_UP)) == 2


def test_fills_and_limit_on_open_never_consume_a_provisional_open(con):
    _admitted_entry(con)
    result = fills.attempt_fill(con, "AAA", "buy", 10, PRIOR, DAY, "baseline_v1")
    assert (result.status, result.reject_reason) == ("pending", "untrusted_bar")
    limit = p15_fills.attempt_limit_on_open(con, "AAA", "buy", 10, PRIOR, DAY, 11.0,
                                           "baseline_v1")
    assert (limit.status, limit.reject_reason) == ("pending", "untrusted_bar")
    assert limit.counterfactual_fill_px is None
    assert db.upsert_prices(con, frame(SETTLED)) == 1
    filled = fills.attempt_fill(con, "AAA", "buy", 10, PRIOR, DAY, "baseline_v1")
    assert filled.status == "filled" and filled.fill_px >= 10.1


def test_labels_wait_for_the_settled_open(con):
    _admitted_entry(con)
    labeled_at = SAME_NIGHT + timedelta(hours=1)
    assert agent_evaluation._label_outcome_when_ready(con, "AAA", [DAY], labeled_at) is None
    assert db.upsert_prices(con, frame(SETTLED)) == 1
    outcome = agent_evaluation._label_outcome_when_ready(
        con, "AAA", [DAY], NEXT_NIGHT + timedelta(hours=1))
    assert outcome["missing_bar_status"] == "complete"
    assert outcome["entry_open"] == 10.1


def test_opportunity_gap_return_never_reads_a_provisional_open(tmp_path):
    path = tmp_path / "market.duckdb"
    _database(path)
    con = db.connect(path)
    try:
        before = {row[0] for row in daily_opportunities._candidate_rows(con, MARKET_DATE)}
        assert "FAST" in before
        fetched = datetime.combine(MARKET_DATE, datetime.min.time()) + timedelta(hours=22)
        con.execute("UPDATE prices SET open=high+5, fetched_at=? WHERE ticker='FAST' AND date=?",
                    [fetched, MARKET_DATE])
        after = {row[0] for row in daily_opportunities._candidate_rows(con, MARKET_DATE)}
        assert after == before - {"FAST"}
        p15 = {row[0] for row in daily_opportunities._p15_candidate_rows(con, MARKET_DATE)}
        assert "FAST" not in p15
    finally:
        con.close()


def test_cleanup_keeps_an_admissible_provisional_bar(con):
    con.executemany(
        "INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [("AAA", DAY, 10.8, 10.6, 9.9, 10.4, 1000, SAME_NIGHT.replace(tzinfo=None)),
         ("BBB", PRIOR, 10.8, 10.6, 9.9, 10.4, 1000, NEXT_NIGHT.replace(tzinfo=None))])
    report = price_quarantine.cleanup_hard_invalid_prices(con)
    assert (report["invalid_rows"], report["provisional_kept"]) == (1, 1)
    applied = price_quarantine.cleanup_hard_invalid_prices(con, dry_run=False)
    assert applied["moved"] == 1
    assert con.execute("SELECT ticker FROM prices").fetchall() == [("AAA",)]


# --------------------------------------------------------------------------- round 2
MONDAY = date(2026, 10, 26)
MONDAY_NIGHT = datetime(2026, 10, 26, 22, 30)


def _spy_monday(con, *, fetched_at, open_=780.0):
    con.execute(
        "INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES ('SPY',?,?,775.0,765.0,770.0,1000000,?)", [MONDAY, open_, fetched_at])


def test_e1_never_trades_an_admitted_provisional_monday_open(con):
    """Reviewer reproduction: candidate (2026-10-26, 780.0, 770.0) existed only after
    admission; E1's candidates must equal the store without the admitted bar."""
    start = date(2026, 10, 1)
    insert_bars(con, "SPY", [date(2026, 10, 19)], open_=760, high=770, low=755, close=765)
    without = experiment_runner._mondays(con, "SPY", 0, start, None)
    _spy_monday(con, fetched_at=MONDAY_NIGHT)
    assert experiment_runner._mondays(con, "SPY", 0, start, None) == without
    assert (MONDAY, 780.0, 770.0) not in experiment_runner._mondays(con, "SPY", 0, start, None)
    # The settled re-fetch (open inside its range) is a normal tradeable Monday.
    con.execute("UPDATE prices SET open=768.0, fetched_at=? WHERE date=?",
                [MONDAY_NIGHT + timedelta(days=1), MONDAY])
    assert experiment_runner._mondays(con, "SPY", 0, start, None)[-1] == (MONDAY, 768.0, 770.0)


def test_p16_holding_marks_skip_an_admitted_provisional_open(con):
    _spy_monday(con, fetched_at=MONDAY_NIGHT)
    cutoff = MONDAY_NIGHT + timedelta(hours=2)
    assert p16_transfer._holding_marks(con, {"SPY": {}}, MONDAY, cutoff) == {}
    con.execute("UPDATE prices SET open=768.0")
    assert p16_transfer._holding_marks(con, {"SPY": {}}, MONDAY, cutoff) == {"SPY": 768.0}


ROW = (MONDAY, 780.0, 775.0, 765.0, 770.0, 1_000_000, "yfinance", MONDAY_NIGHT)


def test_agent_price_fact_withholds_a_provisional_open(con):
    fact = agent_context._price_fact(con, "SPY", ROW)
    normalized = fact["record"]["normalized"]
    assert normalized["open"] is None
    assert normalized["open_withheld"] == "provisional_open_fault"
    assert (normalized["high"], normalized["low"], normalized["close"]) == (775.0, 765.0, 770.0)
    assert "780" not in json.dumps(fact)
    agent_data_contract.validate_daily_price_fact(fact)
    # A forged or immutable-bound withheld record never validates.
    forged = json.loads(json.dumps(fact))
    forged["record"]["normalized"]["open_withheld"] = "other"
    with pytest.raises(agent_data_contract.DataContractError):
        agent_data_contract.validate_daily_price_fact(forged)
    # The same geometry on a settled bar is still refused, never withheld.
    settled = (*ROW[:7], MONDAY_NIGHT + timedelta(days=1))
    with pytest.raises(agent_context.ContextError):
        agent_context._price_fact(con, "SPY", settled)
    # An ordinary provisional bar keeps its open.
    inside = (MONDAY, 768.0, *ROW[2:])
    assert agent_context._price_fact(con, "SPY", inside)["record"]["normalized"]["open"] == 768.0


def test_agent_instrument_quote_withholds_a_provisional_open(con):
    con.execute("CREATE TABLE universe (ticker VARCHAR, active BOOLEAN, liquid BOOLEAN, "
                "etf BOOLEAN)")
    con.execute("INSERT INTO universe VALUES ('SPY', TRUE, TRUE, TRUE)")
    _spy_monday(con, fetched_at=MONDAY_NIGHT)
    con.execute("UPDATE prices SET source='yfinance'")
    record = agent_context._instrument(con, "SPY", MONDAY)
    normalized = record["data_contract"]["record"]["normalized"]
    assert record["close"] == 770.0
    assert normalized["open"] is None and normalized["open_withheld"] == "provisional_open_fault"


# The live 2026-10-19 store held three stale same-night open faults never re-fetched.
STALE = [
    ("DDS", date(2026, 10, 12), 648.7000122070312, 648.5399780273438, 618.6400146484375,
     642.2899780273438, 129097, datetime(2026, 10, 12, 22, 30, 44)),
    ("SUNC", date(2026, 10, 12), 74.45999908447266, 75.875, 74.68499755859375,
     74.83000183105469, 243610, datetime(2026, 10, 12, 22, 31, 52)),
    ("CIB", date(2026, 10, 16), 95.97000122070312, 98.12999725341797, 96.87000274658203,
     97.91000366210938, 183418, datetime(2026, 10, 16, 22, 30, 49)),
]


def _insert_stale(con):
    con.executemany(
        "INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?)", STALE)
    con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
                "VALUES ('SPY',?,700,705,695,701,1000,?)", [DAY, SAME_NIGHT.replace(tzinfo=None)])


def test_stale_provisional_open_faults_are_judged_as_settled(con):
    _insert_stale(con)
    # Cleanup moves them like any other hard-invalid bar; the newest session is kept.
    con.execute("INSERT INTO prices(ticker,date,open,high,low,close,volume,fetched_at) "
                "VALUES ('AAA',?,10.8,10.6,9.9,10.4,1000,?)", [DAY, SAME_NIGHT.replace(tzinfo=None)])
    report = price_quarantine.cleanup_hard_invalid_prices(con)
    assert (report["invalid_rows"], report["provisional_kept"]) == (3, 1)
    assert report["by_date"] == {"2026-10-12": 2, "2026-10-16": 1}
    # Until then, retained-bar quality counts them invalid (stale is not provisional).
    quality = market_read_models.retained_bar_quality(con, ["DDS", "CIB"], DAY)
    assert quality["DDS"]["invalid_count"] == 1 and quality["CIB"]["invalid_count"] == 1
    # Open consumers keep excluding them, stale or not.
    assert con.execute(f"SELECT count(*) FROM prices WHERE {provisional_open_fault_sql()}"
                       ).fetchone() == (4,)
    applied = price_quarantine.cleanup_hard_invalid_prices(con, dry_run=False)
    assert applied["moved"] == 3
    assert price_quarantine.cleanup_hard_invalid_prices(con)["invalid_rows"] == 0


def test_a_stale_same_night_open_fault_is_not_admitted(con):
    insert_bars(con, "SPY", [DAY], open_=700, high=705, low=695, close=701)
    ticker, day, open_, high, low, close, volume, fetched = STALE[0]
    bar = dict(ticker=ticker, date=day, open=open_, high=high, low=low, close=close,
               volume=volume, source="yfinance", fetched_at=fetched)
    assert db.upsert_prices(con, frame(bar)) == 0
    assert reject_reasons(con) == ["high_geometry"]
    # A valid settled re-fetch replaces nothing and is simply admitted.
    assert db.upsert_prices(con, frame({**bar, "open": 640.0,
                                        "fetched_at": datetime(2026, 10, 20, 22)})) == 1


_TZ_PROBE = """
import json, os, sys
from datetime import date, datetime, timezone
import pandas as pd
from engine.lib import db
from engine.lib.data_quality import provisional_open_fault_sql
from server import market_read_models
con = db.connect(sys.argv[1])
db.init_schema(con)
bar = dict(ticker="AAA", date=date(2026, 10, 19), open=10.8, high=10.6, low=9.9, close=10.4,
           volume=1000, source="fixture",
           fetched_at=datetime(2026, 10, 19, 22, 30, tzinfo=timezone.utc))
admitted = db.upsert_prices(con, pd.DataFrame([bar], dtype=object))
stamp, fault = con.execute(f"SELECT fetched_at, {provisional_open_fault_sql()} FROM prices").fetchone()
quality = market_read_models.retained_bar_quality(con, ["AAA"], date(2026, 10, 19))["AAA"]
print(json.dumps({"admitted": admitted, "stamp": stamp.isoformat(), "fault": fault,
                  "invalid": quality["invalid_count"]}))
"""


@pytest.mark.parametrize("zone", ["Asia/Singapore", "America/Los_Angeles"])
def test_ingest_and_reads_agree_on_a_non_utc_host(tmp_path, zone):
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "-c", _TZ_PROBE, str(tmp_path / "store.duckdb")],
        env={**os.environ, "TZ": zone, "PYTHONPATH": str(root)}, cwd=root,
        capture_output=True, text=True, check=True)
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {
        "admitted": 1, "stamp": "2026-10-19T22:30:00", "fault": True, "invalid": 0}
