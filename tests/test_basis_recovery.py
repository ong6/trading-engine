"""Replay the retained XP gap through nightly and exact-label collection."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from engine import collect
from engine.lib import db
from server import p15_incremental_collect as incremental

CASE = json.loads(Path(__file__).with_name("fixtures").joinpath(
    "basis_recovery_xp.json").read_text())
DATES = [date.fromisoformat(d) for d in CASE["obligation_dates"]]


def seed(database, *, actions=True):
    con = db.connect(database)
    db.init_schema(con)
    db.init_actions_schema(con)
    con.execute("INSERT INTO universe (ticker,yf_ticker,active,liquid) "
                "VALUES ('XP','XP',true,true)")
    for row in CASE["stored"]:
        fields = list(row)
        con.execute(f"INSERT INTO prices ({','.join(fields)}) VALUES "
                    f"({','.join('?' for _ in fields)})", list(row.values()))
    if actions:
        con.execute("INSERT INTO actions_fetch_log "
                    "(ticker,fetched_on,n_splits,n_dividends,status) "
                    "VALUES ('XP', '2026-11-12',0,0,'ok')")
    frame = source().loc[lambda f: f.date.isin(DATES)]
    assert db.upsert_prices(con, frame) == 0
    con.close()


def source():
    frame = pd.DataFrame(CASE["incoming"])
    frame["date"] = pd.to_datetime(frame.date).dt.date
    return frame


def raw(frame):
    return frame.drop(columns="ticker").set_index("date").rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "volume": "Volume",
    }).rename_axis("Date")


@pytest.mark.parametrize("actions", [True, False])
def test_incremental_held_name_fetches_twenty_prior_sessions(tmp_path, monkeypatch, actions):
    database = tmp_path / "market.duckdb"
    seed(database, actions=actions)
    calls = []

    def download(tickers, *, period, start):
        # Opening a separate reader proves no writer lease spans the fetch.
        con = db.connect(database, read_only=True, wait_s=0)
        con.close()
        calls.append((tickers, period, start))
        frame = source()
        return raw(frame if start else frame.loc[frame.date.isin(DATES)])

    monkeypatch.setattr(collect, "_download", download)
    monkeypatch.setattr(collect.time, "sleep", lambda _: None)
    assert collect.mode_incremental(database, force=True, limit=1) == (1, 0 if actions else 1)
    assert calls == [(["XP"], None, CASE["context_start"])]
    if actions:
        con = db.connect(database, read_only=True)
        assert con.execute("SELECT count(*) FROM prices WHERE ticker='XP' "
                           "AND date BETWEEN '2026-10-26' AND '2026-10-30'").fetchone() == (5,)
        con.close()


@pytest.mark.parametrize("actions,revision", [(True, False), (False, False), (True, True)])
def test_exact_obligations_recover_once_and_keep_the_fetch_limit(
    tmp_path, monkeypatch, actions, revision,
):
    database = tmp_path / "market.duckdb"
    seed(database, actions=actions)
    monkeypatch.setattr(collect, "mode_incremental", lambda *a, **k: (1, 0))
    monkeypatch.setattr(collect, "write_meta", lambda *a: None)
    obligations = [{"ticker": "XP", "provider_ticker": "XP", "market_date": d}
                   for d in DATES]
    obligations += [{"ticker": f"OTHER{i}", "provider_ticker": f"OTHER{i}",
                     "market_date": DATES[0]} for i in range(20)]
    monkeypatch.setattr(incremental.p15_price_fetch_attempts, "open_label_obligations",
                        lambda *a, **k: obligations)
    monkeypatch.setattr(db, "latest_operational_market_date", lambda _: date(2026, 11, 12))
    calls = []

    def history(provider, start, end):
        con = db.connect(database, read_only=True, wait_s=0)
        con.close()
        calls.append((provider, start, end))
        frame = source()
        if revision:
            frame.loc[frame.date < DATES[0], ["open", "high", "low", "close"]] *= 2
        if provider != "XP":
            raise incremental.YFPricesMissingError(provider, "exact", "No data found, symbol may be delisted")
        return raw(frame.loc[(frame.date >= start) & (frame.date < end)])

    result = incremental.run(database, now=datetime(2026, 11, 13, tzinfo=timezone.utc),
                             history=history, sleep=lambda _: None)
    assert calls[0] == ("XP", date.fromisoformat(CASE["context_start"]), date(2026, 11, 13))
    assert len(calls) == incremental.MAX_OPEN_LABEL_FETCHES
    assert sum(start == date.fromisoformat(CASE["context_start"])
               for _, start, _ in calls) == 1
    assert result["open_label_failed"] == (0 if actions and not revision else 5)
    assert result["open_label_deferred"] == 6
    # The context fetch never substitutes for a date-specific fetch or missing receipt.
    assert [call[1] for call in calls[1:6]] == DATES
    assert all((end - start).days == 1 for _, start, end in calls[1:])
