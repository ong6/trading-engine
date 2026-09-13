"""Cross-domain contracts shared by dashboard read models."""

from datetime import date, timedelta

import pytest

from server import (
    journal_read_models,
    league_read_models,
    market_read_models,
    order_read_models,
    position_read_models,
)
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe, portfolio, screen_table


def test_empty_store_read_models_are_explicit(con):
    assert market_read_models.screen(con) is None
    assert league_read_models.league(con) == {
        "as_of": None,
        "regime": "unknown",
        "reference_notional": 39_000.0,
        "ranking_basis": "total_return_since_each_portfolio_inception",
        "comparison_basis": "SPY_over_each_portfolio_inception_window",
        "evidence_role": "operational_only",
        "notice": league_read_models.LEAGUE_NOTICE,
        "limit": 100,
        "matching_count": 0,
        "truncated": False,
        "rows": [],
    }
    assert league_read_models.equity(con, "missing") is None
    assert league_read_models.equities(con) == {
        "as_of": None,
        "portfolio_limit": 100,
        "portfolio_matching_count": 0,
        "portfolios_truncated": False,
        "limit_per_portfolio": 500,
        "equity_by_portfolio": {},
        "matching_count_by_portfolio": {},
        "truncated_by_portfolio": {},
    }
    assert market_read_models.candidate(con, "missing") is None
    assert position_read_models.positions(con, None, discretionary_id="discretionary") == {
        "portfolio": None,
        "limit": 500,
        "matching_count": 0,
        "truncated": False,
        "positions": [],
    }


def test_latest_prices_date_ignores_later_phantom_quote(con):
    traded = date(2026, 9, 4)
    phantom = date(2026, 9, 8)
    liquid_universe(con, ("SPY",))
    insert_bars(con, "SPY", [traded], open_=100.0, close=101.0, volume=1_000_000)
    insert_bars(con, "DEAD", [phantom], open_=50.0, close=50.0, volume=0)

    assert market_read_models.latest_prices_date(con) == traded
    assert order_read_models.orders(con, None) == {
        "status": None,
        "limit": 500,
        "matching_count": 0,
        "truncated": False,
        "orders": [],
    }
    assert journal_read_models.journal(con) == {
        "discretionary": {
            "tickets": [],
            "tickets_limit": 100,
            "tickets_matching_count": 0,
            "tickets_truncated": False,
            "round_trips": [],
            "round_trips_limit": 100,
            "round_trips_matching_count": 0,
            "round_trips_truncated": False,
        },
        "league_events": [],
        "league_events_limit": 100,
        "league_events_matching_count": 0,
        "league_events_truncated": False,
    }


def test_latest_prices_date_avoids_exhaustive_scan_when_newest_date_is_complete(con, monkeypatch):
    current = date(2026, 9, 10)
    liquid_universe(con, ("AAA", "BBB"))
    for ticker in ("AAA", "BBB"):
        insert_bars(con, ticker, [current], open_=100, high=101, low=99, close=100)

    def unexpected_fallback(_con):
        raise AssertionError("complete recent date should not scan all price history")

    monkeypatch.setattr(market_read_models, "latest_operational_market_date", unexpected_fallback)

    assert market_read_models.latest_prices_date(con) == current


def test_latest_prices_date_falls_back_after_bounded_incomplete_tail(con, monkeypatch):
    complete = date(2026, 9, 4)
    liquid_universe(con, ("AAA", "BBB"))
    for ticker in ("AAA", "BBB"):
        insert_bars(con, ticker, [complete], open_=100, high=101, low=99, close=100)
    for offset in range(1, 4):
        insert_bars(
            con,
            "AAA",
            [complete + timedelta(days=offset)],
            open_=101,
            high=102,
            low=100,
            close=101,
        )

    canonical = market_read_models.latest_operational_market_date
    fallback_calls = 0

    def tracked_fallback(actual):
        nonlocal fallback_calls
        fallback_calls += 1
        return canonical(actual)

    monkeypatch.setattr(market_read_models, "RECENT_MARKET_DATE_PROBE_LIMIT", 2)
    monkeypatch.setattr(market_read_models, "latest_operational_market_date", tracked_fallback)

    assert market_read_models.latest_prices_date(con) == complete
    assert fallback_calls == 1


def test_candidate_positions_orders_and_journal_projection(con):
    screen_table(con)
    days = [date(2026, 9, 3), date(2026, 9, 4)]
    liquid_universe(con, ("AAA",))
    insert_bars(
        con,
        "AAA",
        days,
        open_=[9.0, 10.0],
        high=[9.5, 11.0],
        low=[9.0, 10.0],
        close=[9.5, 11.0],
    )
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(?, 'AAA', 11, 88, 8, TRUE, .1, .2, .3, -.1, TRUE, TRUE, TRUE)",
        [days[-1]],
    )
    portfolio(con, "discretionary")
    con.execute("INSERT INTO sim_positions VALUES ('discretionary', 'AAA', 2, 8)")
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, 'filled', NULL)",
        [days[0]],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, entry_ref, stop, target, playbook, gates, status, "
        "order_id, created_at) VALUES "
        "(1, 'AAA', 'buy', 2, 9, 7, 13, 'experiment', 'not-json', 'filled', 1, now())"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, 9, 9, 0, 0)",
        [days[0]],
    )

    candidate = market_read_models.candidate(con, "aaa")
    positions = position_read_models.positions(
        con, "discretionary", discretionary_id="discretionary"
    )
    orders = order_read_models.orders(con, "filled")
    journal = journal_read_models.journal(con)

    assert candidate["ticker"] == "AAA"
    assert candidate["as_of"] == days[-1]
    assert candidate["n_bars"] == 2
    assert candidate["latest_close_date"] == days[-1]
    assert candidate["latest_close"] == pytest.approx(11.0)
    assert candidate["screen"]["rs_rank"] == 88
    position = positions["positions"][0]
    assert position["market_value"] == pytest.approx(22.0)
    assert position["unrealized_pnl"] == pytest.approx(6.0)
    assert position["stop"] == pytest.approx(7.0)
    assert position["unrealized_r"] == pytest.approx(3.0)
    assert orders["orders"][0]["ticket_id"] == 1
    assert orders["orders"][0]["playbook"] == "experiment"
    malformed_ticket = journal["discretionary"]["tickets"][0]
    assert malformed_ticket["gates"] == []
    assert malformed_ticket["gates_error"] == "malformed-json"
    assert "gates_raw" not in malformed_ticket
    assert "gates_parse_error" not in malformed_ticket
    assert len(journal["discretionary"]["tickets"][0]["fills"]) == 1
    assert len(journal["league_events"]) == 1
