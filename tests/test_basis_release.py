"""Release a market move only with completed action evidence and unchanged history."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from engine.lib import db

CASES = json.loads(Path(__file__).with_name("fixtures").joinpath(
    "basis_release_prices.json").read_text())


def seed(con, case, *, fetch_status="ok", fetch_day=None):
    db.init_schema(con)
    db.init_actions_schema(con)
    for row in case["stored"]:
        fields = list(row)
        con.execute(f"INSERT INTO prices ({','.join(fields)}) VALUES "
                    f"({','.join('?' for _ in fields)})", list(row.values()))
    if fetch_status is not None:
        day = fetch_day or case["actions_fetch"]["fetched_on"]
        con.execute("INSERT INTO actions_fetch_log "
                    "(ticker,fetched_on,n_splits,n_dividends,status) VALUES (?,?,0,0,?)",
                    [case["ticker"], day, fetch_status])


def incoming(case):
    frame = pd.DataFrame(case["incoming"], dtype=object)
    frame["ticker"] = case["ticker"]
    frame["date"] = pd.to_datetime(frame.date).dt.date
    frame["fetched_at"] = case["fetched_at"]
    frame["source"] = "yfinance"
    return frame


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["ticker"])
def test_recorded_market_drop_with_twenty_unchanged_sessions_is_admitted(con, case):
    seed(con, case)
    frame = incoming(case)
    assert db.upsert_prices(con, frame) == len(frame)
    assert con.execute("SELECT COUNT(*) FROM price_observation_rejects "
                       "WHERE reason='basis_unverified'").fetchone() == (0,)
    assert con.execute("SELECT date FROM prices WHERE ticker=? ORDER BY date",
                       [case["ticker"]]).fetchall() == [(d,) for d in frame.date]


@pytest.mark.parametrize("fetch_status", [None, "failed", "empty"])
def test_release_requires_a_completed_ok_actions_fetch(con, fetch_status):
    case = CASES[0]
    seed(con, case, fetch_status=fetch_status)
    assert db.upsert_prices(con, incoming(case)) == 0


def test_actions_fetch_before_the_break_does_not_release(con):
    case = CASES[0]
    seed(con, case, fetch_day=date.fromisoformat(case["break_date"]) - timedelta(days=1))
    assert db.upsert_prices(con, incoming(case)) == 0


@pytest.mark.parametrize("missing", ["nineteenth", "oldest"])
def test_all_twenty_pre_break_stored_sessions_must_overlap(con, missing):
    case = CASES[0]
    seed(con, case)
    frame = incoming(case).drop(index=0 if missing == "oldest" else 18)
    assert db.upsert_prices(con, frame) == 0


def test_nineteen_stored_sessions_are_not_enough(con):
    case = CASES[0]
    seed(con, {**case, "stored": case["stored"][1:]})
    assert db.upsert_prices(con, incoming(case)) == 0


def test_five_session_incremental_pull_does_not_release(con):
    case = CASES[0]
    seed(con, case)
    assert db.upsert_prices(con, incoming(case).tail(5)) == 0


def test_an_invalid_stored_close_cannot_count_as_unchanged_history(con):
    case = CASES[0]
    seed(con, case)
    con.execute("UPDATE prices SET close=0 WHERE date=?", [case["stored"][-1]["date"]])
    assert db.upsert_prices(con, incoming(case)) == 0


@pytest.mark.parametrize("revision,admitted", [(0.5e-6, True), (2e-6, False)])
def test_pre_break_close_revision_uses_the_existing_tolerance(con, revision, admitted):
    case = CASES[0]
    seed(con, case)
    frame = incoming(case)
    frame.loc[0, "close"] *= 1 + revision
    assert db.upsert_prices(con, frame) == (len(frame) if admitted else 0)


def test_a_genuine_split_with_restated_history_still_holds(con):
    case = CASES[0]
    seed(con, case)
    frame = incoming(case)
    pre = frame.date < date.fromisoformat(case["break_date"])
    for field in ("open", "high", "low", "close"):
        frame.loc[pre, field] *= 2 / 3
    original = con.execute("SELECT * FROM prices ORDER BY date").fetchall()
    assert db.upsert_prices(con, frame) == 0
    assert con.execute("SELECT * FROM prices ORDER BY date").fetchall() == original


def test_revision_of_an_existing_date_still_holds(con):
    case = CASES[0]
    seed(con, case)
    frame = incoming(case)
    bar = frame.iloc[20].to_dict()
    # Retain a real trusted bar directly: its following revision must still hold.
    fields = list(bar)
    con.execute(f"INSERT OR REPLACE INTO prices ({','.join(fields)}) VALUES "
                f"({','.join('?' for _ in fields)})", list(bar.values()))
    for field in ("open", "high", "low", "close"):
        frame.loc[20, field] *= 2
    assert db.upsert_prices(con, frame) == 0


@pytest.mark.parametrize("kind,value", [("split", 2), ("dividend", 0.1)])
@pytest.mark.parametrize("offset", [-7, 0, 7])
def test_any_captured_action_near_the_break_prevents_market_move_release(
    con, kind, value, offset,
):
    case = CASES[0]
    seed(con, case)
    con.execute("INSERT INTO corporate_actions VALUES (?,?,?,?, 'fixture',now())",
                [case["ticker"], date.fromisoformat(case["break_date"]) +
                 timedelta(days=offset), kind, value])
    assert db.upsert_prices(con, incoming(case)) == 0


def test_matching_captured_split_keeps_the_existing_split_path(con):
    case = CASES[0]
    seed(con, case)
    con.execute("INSERT INTO corporate_actions VALUES (?,?, 'split',1.5,'fixture',now())",
                [case["ticker"], case["break_date"]])
    frame = incoming(case)
    assert db.upsert_prices(con, frame) == len(frame)


def test_release_does_not_bypass_scalar_admission(con):
    case = CASES[0]
    seed(con, case)
    frame = incoming(case)
    frame.loc[frame.date == date.fromisoformat(case["break_date"]), "open"] = -1
    db.upsert_prices(con, frame)
    assert con.execute("SELECT 1 FROM prices WHERE date=?", [case["break_date"]]).fetchone() is None
    assert con.execute("SELECT reason FROM price_observation_rejects "
                       "WHERE date=?", [case["break_date"]]).fetchone() == ("open_nonpositive",)
