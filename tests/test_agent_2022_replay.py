"""Tests for the contamination-labelled 2022 model replay."""
from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import pytest

from farm import agent_2022_replay as replay


def _con():
    con = duckdb.connect()
    con.execute("CREATE TABLE prices (ticker VARCHAR, date DATE, open DOUBLE, close DOUBLE, volume BIGINT)")
    sessions = []
    current = date(2020, 12, 1)
    while len(sessions) < 600:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    for offset, ticker in enumerate(("AAPL", "MSFT", "XOM", "SPY"), start=1):
        rows = []
        for index, session in enumerate(sessions):
            close = 100 + offset + index * (0.03 + offset * 0.005)
            rows.append((ticker, session, close - 0.2, close, 1_000_000 + index))
        con.executemany("INSERT INTO prices VALUES (?, ?, ?, ?, ?)", rows)
    return con


def test_blinded_prompt_hides_symbols_and_date():
    con = _con()
    config = replay.registration()
    prompt, aliases = replay.build_input(
        con, config, date(2022, 1, 31), "price_blinded"
    )
    con.close()
    encoded = json.dumps(prompt)
    assert prompt["decision_date"] == "withheld"
    assert set(prompt["choices"]) == {"Asset A", "Asset B", "Asset C", "CASH"}
    assert all(symbol not in encoded for symbol in aliases)


def test_future_outcome_is_next_open_to_twentieth_close():
    con = _con()
    result = replay.outcome(con, "AAPL", date(2022, 1, 31), 20)
    con.close()
    assert result["entry_date"] > "2022-01-31"
    assert result["exit_date"] > result["entry_date"]
    assert result["round_trip_cost_bps"] == 20
    assert result["net_return"] < result["gross_return"]


def test_decision_contract_rejects_cash_direction_and_unknown_asset():
    base = {"schema_version": 1, "asset": "CASH", "direction": "up",
            "expected_return_pct": 0, "confidence": 0.5,
            "thesis": "Preserve capital.", "invalidation": "Trend improves."}
    with pytest.raises(replay.ReplayError):
        replay.validate(base, ["AAPL", "CASH"])
    with pytest.raises(replay.ReplayError):
        replay.validate({**base, "asset": "GOOG", "direction": "up",
                         "expected_return_pct": 1}, ["AAPL", "CASH"])


def test_direction_accuracy_uses_prediction_not_only_positive_return():
    rows = [
        {"decision": {"direction": "down"}, "selected_ticker": "AAPL",
         "outcome": {"net_return": -0.1, "round_trip_cost_bps": 20}, "excess_vs_spy": 0.0},
        {"decision": {"direction": "up"}, "selected_ticker": "MSFT",
         "outcome": {"net_return": -0.1, "round_trip_cost_bps": 20}, "excess_vs_spy": 0.0},
    ]
    assert replay.summarize(rows)["direction_accuracy"] == 0.5
