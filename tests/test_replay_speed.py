"""Offline replay fast paths return exactly what the original paths return."""
from __future__ import annotations

import numpy as np
import pytest

from sim import ledger, portfolio, settle
from tests.conftest import SESSIONS, insert_bars


def _fill(con, book, order_id, ticker, side, qty, price, session):
    applied = ledger.apply_fill(con, {
        "order_id": order_id, "portfolio_id": book, "ticker": ticker, "side": side,
        "qty": qty, "fill_px": price, "fill_date": session,
    })
    if applied:
        con.execute("INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,0,0)",
                    [order_id, book, ticker, side, applied, session, price, price])


@pytest.mark.slow
def test_projection_checkpoints_reproduce_full_replays(con, book, monkeypatch):
    applied = {"cached": 0, "plain": 0}
    original = ledger.apply_event

    def counting(target, event, **kwargs):
        applied["cached" if ledger._CHECKPOINTS is not None else "plain"] += 1
        return original(target, event, **kwargs)

    monkeypatch.setattr(ledger, "apply_event", counting)
    con.execute("CREATE TABLE split_adjustments (ticker VARCHAR, ex_date DATE, "
                "ratio DOUBLE, outcome VARCHAR)")
    con.execute("INSERT INTO split_adjustments VALUES ('BBB', ?, 2.0, 'applied')", [SESSIONS[20]])
    settle.ensure_table(con)
    rng = np.random.default_rng(3)
    order_id, cached, plain = 0, [], []
    with ledger.projection_checkpoints(limit=4):
        for index, session in enumerate(SESSIONS[1:], 1):
            for ticker in ("AAA", "BBB", "CCC"):
                held = portfolio.get_positions(con, book).get(ticker, {}).get("qty", 0)
                side = "sell" if held and rng.random() < 0.4 else "buy"
                order_id += 1
                _fill(con, book, order_id, ticker, side, float(rng.integers(1, 9)) / 3,
                      float(rng.uniform(10, 50)), session)
            if index == 12:  # a dividend credited after later fills were booked
                con.execute("INSERT INTO sim_dividends VALUES (?, 'AAA', ?, 1, 0.5, 0.5)",
                            [book, SESSIONS[5]])
            if index == 25:
                ledger.apply_cash_event(con, {"portfolio_id": book, "event_date": session,
                                              "kind": "adjustment", "amount": -1.25})
            days = {SESSIONS[max(0, index - lag)] for lag in (0, 1, 4)}
            cached.append(ledger.projected_states_at_closes(con, book, days))
            previous, ledger._CHECKPOINTS = ledger._CHECKPOINTS, None
            try:
                plain.append(ledger.projected_states_at_closes(con, book, days))
            finally:
                ledger._CHECKPOINTS = previous
    assert ledger._CHECKPOINTS is None
    assert repr(cached) == repr(plain)
    assert any(snapshot["positions"] for result in plain for snapshot in result.values())
    assert applied["cached"] < applied["plain"] / 4


def test_batched_closes_match_per_ticker_closes(con):
    insert_bars(con, "AAA", SESSIONS[:10], close=[float(10 + i) for i in range(10)])
    insert_bars(con, "BBB", SESSIONS[:5], close=20.0)
    insert_bars(con, "CCC", SESSIONS[3:4], close=30.0, volume=0)  # never a traded bar
    for day in (SESSIONS[0], SESSIONS[4], SESSIONS[9], SESSIONS[20]):
        names = ["AAA", "BBB", "CCC", "ZZZ"]
        assert portfolio.close_observations(con, names, day) == {
            name: portfolio.close_observation(con, name, day) for name in names}


def test_delistings_without_inactive_snapshots_is_empty(con):
    con.execute("CREATE TABLE universe_snapshot (ticker VARCHAR, snapshot_date DATE, "
                "active BOOLEAN)")
    insert_bars(con, "AAA", SESSIONS[:3])
    con.execute("INSERT INTO universe_snapshot VALUES ('AAA', ?, TRUE)", [SESSIONS[0]])
    assert settle.delistings(con, SESSIONS[-1], ["AAA"]) == []
    con.execute("INSERT INTO universe_snapshot VALUES ('AAA', ?, FALSE)", [SESSIONS[5]])
    assert [row.ticker for row in settle.delistings(con, SESSIONS[-1], ["AAA"])] == ["AAA"]
