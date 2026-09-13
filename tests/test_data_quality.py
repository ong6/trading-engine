"""Data evidence labels, fingerprints, and explicit quarantine behavior."""
import json

from engine import price_quarantine
from engine.lib import data_quality
from sim import league
from tests.conftest import SESSIONS, insert_bars


def test_strategy_quality_classes_are_explicit():
    assert data_quality.quality_class("spy_benchmark") == "fixed_etf_history"
    assert data_quality.quality_class("sleeve_alloc") == "fixed_etf_history"
    assert data_quality.quality_class("ew_benchmark") == "current_universe_survivor_biased"
    # It buys SPY, but its internally-computed breadth history uses today's
    # surviving liquid universe; evidence quality follows inputs, not holdings.
    assert data_quality.quality_class("macro_composite") == (
        "current_universe_survivor_biased")
    assert data_quality.quality_class("low_vol") == "static_fundamental_lookahead"


def test_snapshot_changes_when_source_data_changes(con):
    before = data_quality.data_snapshot(con)
    insert_bars(con, "AAA", [SESSIONS[0]])
    after = data_quality.data_snapshot(con)
    assert before["sha256"] != after["sha256"]
    assert after["tables"]["prices"]["rows"] == 1


def test_quarantine_activation_and_resolution_are_audited(con):
    price_quarantine.set_quarantine(
        con, "aph", reason="confirmed split-scale corruption", evidence="manual audit")
    assert data_quality.quarantine_reason(con, "APH") == "confirmed split-scale corruption"
    action, payload = con.execute(
        "SELECT action, payload FROM audit_log ORDER BY ts DESC LIMIT 1").fetchone()
    assert action == "activate" and json.loads(payload)["ticker"] == "APH"
    price_quarantine.resolve_quarantine(con, "APH", resolution="audited full refetch")
    assert data_quality.quarantine_reason(con, "APH") is None
    assert con.execute("SELECT status FROM price_quarantine WHERE ticker='APH'").fetchone() == (
        "resolved",)


def test_fill_pending_rejects_quarantined_buy_but_allows_sell(con, book):
    insert_bars(con, "AAA", SESSIONS[:31], open_=100, close=100, volume=1_000_000)
    signal, fill_date = SESSIONS[29], SESSIONS[30]
    price_quarantine.set_quarantine(
        con, "AAA", reason="confirmed corrupt bars", evidence="primary audit")
    con.execute(
        "INSERT INTO sim_orders VALUES (1, ?, 'AAA', 'buy', 1, ?, 'pending', NULL)",
        [book, signal])
    result = league.fill_pending(con, fill_date)
    assert result["rejected"] == 1
    assert con.execute("SELECT reject_reason FROM sim_orders WHERE id=1").fetchone()[0].startswith(
        "data_quarantine:")
    con.execute("INSERT INTO sim_positions VALUES (?, 'AAA', 2, 100)", [book])
    con.execute(
        "INSERT INTO sim_orders VALUES (2, ?, 'AAA', 'sell', 2, ?, 'pending', NULL)",
        [book, signal])
    result = league.fill_pending(con, fill_date)
    assert result["filled"] == 1
    assert con.execute("SELECT status FROM sim_orders WHERE id=2").fetchone() == (
        "filled",)
