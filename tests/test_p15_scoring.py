"""P15 scoring-universe and policy-contract tests."""
from __future__ import annotations

from datetime import timedelta

from engine.daily_opportunities import p15_universe
from engine.lib import db
from tests.test_daily_opportunities import MARKET_DATE, _database


def test_p15_universe_keeps_p8_frozen_and_assigns_deterministic_strata(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET open=119,high=120,low=118,close=119 "
        "WHERE ticker='QUIET' AND date=?",
        [MARKET_DATE],
    )
    before = p15_universe(con, MARKET_DATE, held_tickers={"FAST", "QUIET"})
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('FAST',?,?,?,?,?,?)",
        [MARKET_DATE + timedelta(days=1), 200, 201, 199, 200, 9_000_000],
    )
    con.execute(
        "INSERT INTO screen_results (run_date,ticker,close,rs_rank,template_score,"
        "passes_template,dist_50d,dist_200d,off_52w_low,off_52w_high,base_tight,"
        "vol_dryup,new_today,universe_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'all')",
        [MARKET_DATE + timedelta(days=1), "QUIET", 119, 100, 9, True,
         0.2, 0.3, 1.0, -0.01, False, False, True],
    )
    after = p15_universe(con, MARKET_DATE, held_tickers={"FAST", "QUIET"})
    con.close()

    assert before == after
    assert before["universe_version"] == "p15-universe-v1"
    assert [(item["ticker"], item["stratum"]) for item in before["candidates"]] == [
        ("FAST", "mover"), ("QUIET", "held_only")
    ]
    assert before["candidates"][0]["held"] is True
    assert before["candidates"][1]["tradeable"] is False
    assert before["candidates"][1]["reason"] == "held_only"
    assert [item["selection_ordinal"] for item in before["candidates"]] == [1, 2]
    assert [item["baseline_score"] for item in before["candidates"]] == [2, 1]


def test_p15_universe_uses_prior_session_dollar_volume_and_quarantine(tmp_path):
    database = tmp_path / "market.duckdb"
    _database(database)
    con = db.connect(database)
    con.execute(
        "UPDATE prices SET volume=1000 WHERE ticker='FAST' AND date<?",
        [MARKET_DATE],
    )
    low_liquidity = p15_universe(con, MARKET_DATE, held_tickers={"FAST"})
    held = next(item for item in low_liquidity["candidates"] if item["ticker"] == "FAST")
    assert held["median_dollar_volume_20d"] < 20_000_000
    assert held["reason"] == "low_median_dollar_volume"
    assert held["stratum"] == "held_only" and held["tradeable"] is False

    con.execute(
        "UPDATE prices SET volume=1000000 WHERE ticker='FAST' AND date<?",
        [MARKET_DATE],
    )
    con.execute(
        "INSERT INTO price_quarantine "
        "(ticker,status,reason,evidence,confirmed_at,resolved_at,resolution) "
        "VALUES ('FAST','active','bad scale','receipt',CURRENT_TIMESTAMP,NULL,NULL)"
    )
    quarantined = p15_universe(con, MARKET_DATE, held_tickers={"FAST"})
    con.close()

    held = next(item for item in quarantined["candidates"] if item["ticker"] == "FAST")
    assert held["reason"] == "quarantined"
    assert held["stratum"] == "held_only" and held["tradeable"] is False
