"""Execution profiles and persisted capital are explicit, compatible assumptions."""
from datetime import date

import duckdb
import pytest

from farm.stats import equity
from sim import execution, fills, portfolio
from sim.schema import INITIAL_CASH, init_sim_schema


def test_baseline_profile_reproduces_legacy_tiers():
    assert fills.slippage_bps_for(1_000_000_000) == 10.0
    assert fills.slippage_bps_for(25_000_000) == 15.0
    assert fills.slippage_bps_for(6_000_000) == 20.0
    assert fills.slippage_bps_for(None) == 30.0


def test_cost_2x_is_exactly_twice_baseline():
    for mdv in (None, 6_000_000, 25_000_000, 1_000_000_000):
        baseline = fills.slippage_bps_for(mdv)
        stressed = fills.slippage_bps_for(mdv, execution.COST_2X.id)
        assert stressed == pytest.approx(2 * baseline)


def test_participation_stress_is_nonlinear_and_transparent():
    low = execution.cost_components(
        execution.PARTICIPATION_STRESS, side="buy", qty=100, open_px=100,
        median_dollar_volume=100_000_000)
    high = execution.cost_components(
        execution.PARTICIPATION_STRESS, side="buy", qty=10_000, open_px=100,
        median_dollar_volume=100_000_000)
    assert low["participation"] == pytest.approx(0.0001)
    assert high["participation"] == pytest.approx(0.01)
    assert low["impact_bps"] == pytest.approx(1.0)
    assert high["impact_bps"] == pytest.approx(10.0)
    assert high["total_bps"] > low["total_bps"]


def test_broker_fees_are_separate_from_market_friction():
    profile = execution.ExecutionProfile(
        id="fee-test", description="test only", commission_per_share=0.01,
        commission_minimum=1.0, sell_fee_bps=2.0)
    buy = execution.cost_components(
        profile, side="buy", qty=10, open_px=100,
        median_dollar_volume=1_000_000_000)
    sell = execution.cost_components(
        profile, side="sell", qty=10, open_px=100,
        median_dollar_volume=1_000_000_000)

    assert buy["market_bps"] == pytest.approx(10.0)
    assert buy["fee_bps"] == pytest.approx(10.0)  # $1 / $1,000
    assert buy["total_bps"] == pytest.approx(20.0)
    assert sell["market_bps"] == pytest.approx(10.0)
    assert sell["fee_bps"] == pytest.approx(12.0)  # commission plus sell fee
    assert sell["total_bps"] == pytest.approx(22.0)


def test_schema_migration_stamps_assumptions_without_resetting_cash():
    con = duckdb.connect()
    con.execute("CREATE TABLE portfolios (id VARCHAR PRIMARY KEY, name VARCHAR, "
                "strategy VARCHAR, config VARCHAR, created DATE, active BOOLEAN, "
                "cash DOUBLE)")
    con.execute("INSERT INTO portfolios VALUES ('old', 'old', 'x', '{}', "
                "DATE '2024-01-01', TRUE, 123.45)")
    init_sim_schema(con)
    row = con.execute(
        "SELECT cash, initial_cash, execution_profile FROM portfolios WHERE id='old'"
    ).fetchone()
    assert row == (123.45, INITIAL_CASH, execution.DEFAULT_PROFILE_ID)
    con.close()


def test_rebuild_uses_each_books_persisted_starting_capital(con):
    con.execute(
        "INSERT INTO portfolios (id, name, active, cash, initial_cash, "
        "execution_profile) VALUES ('small', 'small', TRUE, 1, 10000, ?)",
        [execution.DEFAULT_PROFILE_ID])
    con.execute(
        "INSERT INTO portfolios (id, name, active, cash, initial_cash, "
        "execution_profile) VALUES ('large', 'large', TRUE, 1, 250000, ?)",
        [execution.DEFAULT_PROFILE_ID])
    portfolio.rebuild_state(con)
    assert dict(con.execute("SELECT id, cash FROM portfolios").fetchall()) == {
        "small": 10_000.0, "large": 250_000.0}


def test_full_replay_return_can_include_day_one_drag():
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    result = equity.equity_stats(dates, [99.0, 100.0, 101.0], initial_equity=100.0)
    assert result["return_base"] == 100.0
    assert result["total_return"] == pytest.approx(0.01)
    legacy = equity.equity_stats(dates, [99.0, 100.0, 101.0])
    assert legacy["total_return"] == pytest.approx(101 / 99 - 1)


def test_fill_model_version_marks_profile_aware_semantics():
    assert portfolio.FILL_MODEL_VERSION == "v4"
